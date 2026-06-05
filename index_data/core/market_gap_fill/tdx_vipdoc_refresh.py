from __future__ import annotations

import json
import re
import shutil
import tempfile
import urllib.request
import zipfile
from datetime import datetime
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urljoin
from urllib.parse import urlparse
from urllib.parse import urlunparse

from config import settings
from core.market_gap_fill.models import TdxRefreshStatus
from core.market_gap_fill.tdx_day_parser import scan_max_trade_date
from dao.market_dao import market_dao
from utils.logger import logger


TDX_DOWNLOAD_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/125.0.0.0 Safari/537.36"
)


def refresh_tdx_vipdoc(
    target_date: str | None = None,
    zip_url: str | None = None,
    root: str | Path | None = None,
) -> dict:
    root_path = Path(root or settings.TDX_VIPDOC_ROOT)
    source_url = (zip_url if zip_url is not None else settings.TDX_VIPDOC_ZIP_URL).strip()
    started_at = _now_text()
    root_path.mkdir(parents=True, exist_ok=True)
    current_dir = root_path / "current"
    status_path = root_path / "refresh_status.json"
    resolved_target_date = target_date or _resolve_target_date()
    current_max_date = scan_max_trade_date(current_dir)

    if current_max_date and resolved_target_date and current_max_date >= resolved_target_date:
        result = {
            "status": TdxRefreshStatus.SKIPPED_FRESH,
            "started_at": started_at,
            "finished_at": _now_text(),
            "max_trade_date": current_max_date,
            "page_url": "",
            "page_update_date": "",
            "resolved_zip_url": "",
            "package_path": str(current_dir),
            "error_message": "",
        }
        _write_status(status_path, result)
        return result

    staging_dir = root_path / "staging"
    _remove_tree(staging_dir)
    staging_dir.mkdir(parents=True, exist_ok=True)

    temp_path = None
    resolved_package = None
    try:
        resolved_package = resolve_tdx_vipdoc_package(source_url)
        with tempfile.NamedTemporaryFile(suffix=".zip", delete=False) as temp_file:
            temp_path = Path(temp_file.name)
        _download_zip(resolved_package.zip_url, temp_path)
        with zipfile.ZipFile(temp_path) as archive:
            archive.extractall(staging_dir)
        staging_max_date = scan_max_trade_date(staging_dir)
        _validate_staging(staging_dir, staging_max_date, current_max_date)
        _switch_current(root_path, current_dir, staging_dir)
        result = {
            "status": TdxRefreshStatus.SUCCESS,
            "started_at": started_at,
            "finished_at": _now_text(),
            "max_trade_date": staging_max_date,
            "page_url": resolved_package.page_url,
            "page_update_date": resolved_package.page_update_date,
            "resolved_zip_url": resolved_package.zip_url,
            "package_path": str(current_dir),
            "error_message": "",
        }
        _write_status(status_path, result)
        return result
    except OSError as exc:
        logger.error("[TDX_REFRESH] switch failed: %s", exc, exc_info=True)
        result = _failed_status(
            started_at,
            current_max_date,
            current_dir,
            str(exc),
            status=TdxRefreshStatus.FAILED_SWITCH,
            package=resolved_package,
        )
        _write_status(status_path, result)
        return result
    except Exception as exc:
        logger.error("[TDX_REFRESH] failed: %s", exc, exc_info=True)
        result = _failed_status(
            started_at,
            current_max_date,
            current_dir,
            str(exc),
            package=resolved_package,
        )
        _write_status(status_path, result)
        return result
    finally:
        if temp_path is not None:
            try:
                temp_path.unlink(missing_ok=True)
            except Exception:
                pass


def read_refresh_status(root: str | Path | None = None) -> dict:
    status_path = Path(root or settings.TDX_VIPDOC_ROOT) / "refresh_status.json"
    if not status_path.exists():
        return {}
    return json.loads(status_path.read_text(encoding="utf-8"))


def current_package_dir(root: str | Path | None = None) -> Path:
    return Path(root or settings.TDX_VIPDOC_ROOT) / "current"


def current_package_covers(
    target_date: str,
    root: str | Path | None = None,
) -> bool:
    max_date = scan_max_trade_date(current_package_dir(root))
    return bool(max_date and max_date >= target_date)


class ResolvedTdxPackage:
    def __init__(
        self,
        zip_url: str,
        page_url: str = "",
        page_update_date: str = "",
    ) -> None:
        self.zip_url = zip_url
        self.page_url = page_url
        self.page_update_date = page_update_date


def resolve_tdx_vipdoc_package(source_url: str | None = None) -> ResolvedTdxPackage:
    source = (source_url or "").strip()
    if source and _is_zip_url(source):
        return ResolvedTdxPackage(zip_url=source)

    page_url = source or settings.TDX_VIPDOC_PAGE_URL
    html = _download_text(page_url)
    page_info = parse_tdx_vipdoc_page(html, page_url)
    page_update_date = page_info["page_update_date"]
    if not page_update_date:
        info_url = page_info.get("update_info_url", "")
        if not info_url:
            raise ValueError("TDX vipdoc page missing update date")
        page_update_date = _extract_update_date_from_info_script(_download_text(info_url))
    return ResolvedTdxPackage(
        zip_url=page_info["zip_url"],
        page_url=page_url,
        page_update_date=page_update_date,
    )


def parse_tdx_vipdoc_page(html: str, page_url: str) -> dict:
    parser = _TdxVipdocPageParser(page_url)
    parser.feed(html)
    parser.close()
    result = parser.resolve()
    if not result.get("page_update_date"):
        result["update_info_url"] = _extract_hsjday_info_url(html, page_url)
    return result


def _download_zip(url: str, target_path: Path) -> None:
    cookie_header = ""
    for _ in range(2):
        challenge_cookie = _download_zip_once(url, target_path, cookie_header)
        if not challenge_cookie:
            return
        cookie_header = challenge_cookie
    raise ValueError("TDX zip download returned bot challenge after retry")


def _download_zip_once(
    url: str,
    target_path: Path,
    cookie_header: str = "",
) -> str:
    headers = {
        "User-Agent": TDX_DOWNLOAD_USER_AGENT,
        "Accept": "application/zip,application/octet-stream,*/*",
        "Referer": settings.TDX_VIPDOC_PAGE_URL,
    }
    if cookie_header:
        headers["Cookie"] = cookie_header
    request = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(
        request,
        timeout=settings.TDX_REFRESH_TIMEOUT_SECONDS,
    ) as response:
        first_bytes = response.read(4)
        if first_bytes != b"PK\x03\x04":
            body = first_bytes + response.read(16384)
            challenge_cookie = _build_tdx_bot_cookie_header(
                body.decode("utf-8", errors="replace")
            )
            if challenge_cookie:
                return challenge_cookie
            content_type = response.headers.get("content-type", "")
            raise ValueError(
                "TDX zip response is not zip: "
                f"status={response.status}, content_type={content_type}"
            )
        with target_path.open("wb") as output:
            output.write(first_bytes)
            shutil.copyfileobj(response, output)

    expected_size = _parse_int(response.headers.get("content-length"))
    actual_size = target_path.stat().st_size
    if expected_size is not None and actual_size != expected_size:
        raise ValueError(
            "TDX zip download incomplete: "
            f"expected {expected_size} bytes, got {actual_size} bytes"
        )
    if not zipfile.is_zipfile(target_path):
        raise ValueError("TDX zip download is not a valid zip file")
    return ""


def _download_text(url: str) -> str:
    with urllib.request.urlopen(url, timeout=settings.TDX_REFRESH_TIMEOUT_SECONDS) as response:
        charset = "utf-8"
        content_type = response.headers.get("content-type", "")
        if "charset=" in content_type:
            charset = content_type.rsplit("charset=", 1)[-1].strip()
        return response.read().decode(charset, errors="replace")


def _validate_staging(
    staging_dir: Path,
    staging_max_date: str | None,
    current_max_date: str | None,
) -> None:
    if not any(staging_dir.rglob("*.day")):
        raise ValueError("TDX staging package contains no .day files")
    if not staging_max_date:
        raise ValueError("TDX staging package max trade date not found")
    if current_max_date and staging_max_date < current_max_date:
        raise ValueError("TDX staging package is older than current package")


def _switch_current(root_path: Path, current_dir: Path, staging_dir: Path) -> None:
    archive_root = root_path / "archive"
    archive_root.mkdir(parents=True, exist_ok=True)
    if current_dir.exists():
        archive_dir = archive_root / datetime.now().strftime("%Y%m%d_%H%M%S")
        current_dir.rename(archive_dir)
    staging_dir.rename(current_dir)


def _remove_tree(path: Path) -> None:
    if path.exists():
        shutil.rmtree(path)


def _write_status(status_path: Path, result: dict) -> None:
    status_path.parent.mkdir(parents=True, exist_ok=True)
    status_path.write_text(
        json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )


def _failed_status(
    started_at: str,
    max_trade_date: str | None,
    current_dir: Path,
    error_message: str,
    status: str = TdxRefreshStatus.FAILED,
    package: ResolvedTdxPackage | None = None,
) -> dict:
    return {
        "status": status,
        "started_at": started_at,
        "finished_at": _now_text(),
        "max_trade_date": max_trade_date,
        "page_url": package.page_url if package else "",
        "page_update_date": package.page_update_date if package else "",
        "resolved_zip_url": package.zip_url if package else "",
        "package_path": str(current_dir),
        "error_message": error_message[:1000],
    }


def _resolve_target_date() -> str | None:
    return market_dao.get_latest_trade_date_global()


def _now_text() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _is_zip_url(url: str) -> bool:
    return urlparse(url).path.lower().endswith(".zip")


class _TdxVipdocPageParser(HTMLParser):
    def __init__(self, page_url: str) -> None:
        super().__init__(convert_charrefs=True)
        self.page_url = page_url
        self._in_row = False
        self._row_depth = 0
        self._current_cell_id = ""
        self._current_link = ""
        self._current_text: list[str] = []
        self._rows: list[dict] = []
        self._row: dict | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attrs_dict = {name: value or "" for name, value in attrs}
        if tag == "tr":
            self._in_row = True
            self._row_depth = 1
            self._row = {"text": "", "hsjdayinfo": "", "links": []}
            return
        if not self._in_row:
            return
        if tag == "tr":
            self._row_depth += 1
        if tag in {"td", "span"}:
            self._current_cell_id = attrs_dict.get("id", self._current_cell_id)
        if tag == "a" and attrs_dict.get("href"):
            self._current_link = attrs_dict["href"]
            if self._row is not None:
                self._row["links"].append(attrs_dict["href"])

    def handle_endtag(self, tag: str) -> None:
        if not self._in_row:
            return
        if tag == "tr":
            self._row_depth -= 1
            if self._row_depth <= 0:
                if self._row is not None:
                    self._row["text"] = "".join(self._current_text).strip()
                    self._rows.append(self._row)
                self._in_row = False
                self._current_text = []
                self._current_cell_id = ""
                self._current_link = ""
                self._row = None
            return
        if tag == "td":
            self._current_cell_id = ""

    def handle_data(self, data: str) -> None:
        if not self._in_row or self._row is None:
            return
        self._current_text.append(data)
        if self._current_cell_id == "hsjdayinfo":
            self._row["hsjdayinfo"] += data

    def resolve(self) -> dict:
        for row in self._rows:
            if "沪深京日线数据完整包" not in row.get("text", ""):
                continue
            links = row.get("links") or []
            if not links:
                raise ValueError("TDX vipdoc page row has no download link")
            update_text = row.get("hsjdayinfo", "") or row.get("text", "")
            try:
                update_date = _extract_update_date(update_text)
            except ValueError:
                update_date = ""
            return {
                "page_update_date": update_date,
                "zip_url": urljoin(self.page_url, links[0]),
            }
        raise ValueError("TDX vipdoc page missing hsjday package row")


def _extract_hsjday_info_url(html: str, page_url: str) -> str:
    match = re.search(
        r"""["'](?P<url>(?:https?:)?//[^"']*_hsjdayinfo\.js)(?:\?[^"']*)?["']""",
        html,
    )
    if not match:
        return ""
    return _with_cache_buster(urljoin(page_url, match.group("url")))


def _extract_update_date_from_info_script(script: str) -> str:
    match = re.search(r"""HSJDAY_SOFT_TIME\s*=\s*["']([^"']+)["']""", script)
    if not match:
        raise ValueError("TDX vipdoc info script missing update date")
    return _extract_update_date(match.group(1))


def _build_tdx_bot_cookie_header(html: str) -> str:
    if "__tst_status" not in html or "EO_Bot_Ssid" not in html:
        return ""
    status_match = re.search(
        r"\{[^{}]*?:\s*(\d+)\s*,[^{}]*?:\s*(\d+)\s*,"
        r"[^{}]*?:\s*function\([^)]*\)\{return a\+n\}\s*,"
        r"[^{}]*?:\s*(\d+)\s*,[^{}]*?:\s*function",
        html,
    )
    ssid_match = re.search(r"\(t,\s*(\d+)\s*\)", html)
    if not status_match or not ssid_match:
        return ""
    status_value = sum(int(value) for value in status_match.groups())
    ssid_value = ssid_match.group(1)
    return f"__tst_status={status_value}#; EO_Bot_Ssid={ssid_value}"


def _parse_int(value: str | None) -> int | None:
    if not value:
        return None
    try:
        return int(value)
    except ValueError:
        return None


def _with_cache_buster(url: str) -> str:
    parsed = urlparse(url)
    query = f"t={int(datetime.now().timestamp() / 10)}"
    return urlunparse(parsed._replace(query=query))


def _extract_update_date(text: str) -> str:
    marker = "更新日期："
    if marker in text:
        text = text.split(marker, 1)[-1]
    value = " ".join(text.split())
    match = re.search(r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}", value)
    if match:
        value = match.group(0)
    if not value:
        raise ValueError("TDX vipdoc page missing update date")
    datetime.strptime(value, "%Y-%m-%d %H:%M:%S")
    return value
