from config.constants import AssetType, DataSource


def normalize_daily_bar_source_code(
    asset_code: str,
    source_id: str,
    asset_type: str,
    source_code: str | None,
) -> str | None:
    """Normalize only Lixinren index daily-bar source codes."""
    cleaned_source_code = source_code.strip() if source_code else None

    if source_id != DataSource.LIXINREN:
        return cleaned_source_code
    if asset_type != AssetType.INDEX:
        return cleaned_source_code

    if not cleaned_source_code:
        return asset_code
    if cleaned_source_code == asset_code:
        return cleaned_source_code

    known_exchange_codes = {
        f"{asset_code}.SH",
        f"{asset_code}.SZ",
        f"{asset_code}.HK",
    }
    if cleaned_source_code in known_exchange_codes:
        return asset_code
    if cleaned_source_code.lower() == f"csi{asset_code}".lower():
        return asset_code
    if (
        cleaned_source_code.startswith("cn_index:")
        or cleaned_source_code.startswith("hk_index:")
    ):
        return cleaned_source_code.split(":", 1)[1]

    return cleaned_source_code
