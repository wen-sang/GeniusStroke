from typing import Any, NoReturn

from fastapi import HTTPException

from utils.logger import logger


def raise_client_http_error(
    log_message: str,
    client_detail: str,
    *log_args: Any,
    status_code: int = 400,
) -> NoReturn:
    """Log a client-facing error and return the provided detail with a 4xx status."""
    logger.warning(log_message, *log_args)
    raise HTTPException(status_code=status_code, detail=client_detail)


def raise_validation_http_error(
    log_message: str,
    exc: Exception,
    *log_args: Any,
    status_code: int = 400,
) -> NoReturn:
    """Log a validation-style error and return the exception detail with a 4xx status."""
    raise_client_http_error(
        log_message,
        str(exc),
        *log_args,
        str(exc),
        status_code=status_code,
    )


def raise_internal_http_error(log_message: str, client_detail: str, *log_args: Any) -> NoReturn:
    """Log the full exception server-side and return a sanitized 500 detail."""
    logger.exception(log_message, *log_args)
    raise HTTPException(status_code=500, detail=client_detail)
