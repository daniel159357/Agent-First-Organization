"""Logging utilities for the Arklex framework.

This module provides standardized logging patterns, context management,
and error handling utilities to ensure consistent logging across the application.
"""

import asyncio
import functools
import logging
import inspect
import traceback
from typing import Any, Callable, Dict, Optional, Type, Union, List
from tenacity import (
    retry,
    stop_after_attempt,
    wait_exponential,
    retry_if_exception_type,
)

from arklex.utils.exceptions import ArklexError, RetryableError

# Standard log messages for consistent usage
LOG_MESSAGES = {
    "ERROR": {
        "API_FAILURE": "API call failed: {error}",
        "VALIDATION_ERROR": "Validation failed: {error}",
        "UNEXPECTED_ERROR": "Unexpected error in {function}: {error}",
        "OPERATION_FAILED": "Operation failed: {error}",
        "RETRY_FAILED": "Retry failed after {attempts} attempts: {error}",
        "RESOURCE_ERROR": "Resource error: {error}",
        "PERMISSION_ERROR": "Permission denied: {error}",
        "CONFIGURATION_ERROR": "Configuration error: {error}",
        "INITIALIZATION_ERROR": "Initialization error: {error}",
    },
    "WARNING": {
        "RETRY_ATTEMPT": "Retrying operation (attempt {attempt}/{max_attempts}): {error}",
        "DEPRECATED_FEATURE": "Deprecated feature used: {feature}",
        "PERFORMANCE_WARNING": "Performance warning: {message}",
        "RESOURCE_WARNING": "Resource warning: {message}",
        "CONFIGURATION_WARNING": "Configuration warning: {message}",
    },
    "INFO": {
        "REQUEST_START": "Request started: {request_id}",
        "REQUEST_END": "Request completed: {request_id}",
        "OPERATION_START": "Starting operation: {operation}",
        "OPERATION_END": "Completed operation: {operation}",
        "RESOURCE_ACCESS": "Accessing resource: {resource}",
        "CONFIGURATION_LOAD": "Loading configuration: {config}",
    },
    "DEBUG": {
        "FUNCTION_ENTRY": "Entering function: {function}",
        "FUNCTION_EXIT": "Exiting function: {function}",
        "STATE_CHANGE": "State changed: {old_state} -> {new_state}",
        "RESOURCE_DETAILS": "Resource details: {details}",
        "CONFIGURATION_DETAILS": "Configuration details: {details}",
    },
}


class RequestIdFilter(logging.Filter):
    """Filter to add request ID to log records."""

    def __init__(self, request_id: Optional[str] = None) -> None:
        """Initialize filter with request ID."""
        super().__init__()
        self.request_id = request_id

    def filter(self, record: logging.LogRecord) -> bool:
        """Add request ID to log record."""
        record.request_id = self.request_id or getattr(record, "request_id", None)
        return True


class ContextFilter(logging.Filter):
    """Filter to add context to log records."""

    def __init__(self, context: Optional[dict] = None) -> None:
        """Initialize filter with context."""
        super().__init__()
        self.context = context or {}

    def filter(self, record: logging.LogRecord) -> bool:
        """Add context to record."""
        record.context = self.context
        return True


class LogContext:
    """Context manager for logging with request ID and context."""

    def __init__(
        self,
        name: str,
        level: str = "INFO",
        base_context: Optional[Dict[str, Any]] = None,
        log_format: Optional[str] = None,
    ):
        self.logger = logging.getLogger(name)
        if "." in name:
            self.logger.setLevel(logging.NOTSET)
        else:
            self.logger.setLevel(getattr(logging, level))
        self.logger.propagate = True
        self.base_context = base_context or {}
        handler = self._get_console_handler(log_format)
        handler.addFilter(RequestIdFilter())
        handler.addFilter(ContextFilter(self.base_context))
        self.logger.addHandler(handler)

    def __enter__(self) -> logging.Logger:
        """Enter context."""
        return self.logger

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        """Exit context."""
        pass

    @property
    def name(self):
        return self.logger.name

    @property
    def level(self):
        return self.logger.level

    @property
    def handlers(self):
        return self.logger.handlers

    @property
    def propagate(self):
        return self.logger.propagate

    @propagate.setter
    def propagate(self, value):
        self.logger.propagate = value

    @property
    def parent(self) -> Optional["LogContext"]:
        if self.logger.parent:
            parent_level = self.logger.parent.level
            if isinstance(parent_level, int):
                parent_level = logging.getLevelName(parent_level)
            return LogContext(self.logger.parent.name, level=parent_level)
        return None

    def _get_console_handler(
        self, log_format: Optional[str] = None
    ) -> logging.StreamHandler:
        handler = logging.StreamHandler()
        handler.setFormatter(
            logging.Formatter(log_format or "%(levelname)s - %(message)s")
        )
        return handler

    def setLevel(self, level: Union[str, int]) -> None:
        """Set the log level for the logger."""
        if isinstance(level, str):
            self.logger.setLevel(getattr(logging, level))
        else:
            self.logger.setLevel(level)

    def _merge_extra(self, context: Optional[Dict[str, Any]], kwargs: dict) -> dict:
        # Merge context and any extra fields from kwargs into a single extra dict
        extra = {"context": context or {}}
        # Remove 'extra' from kwargs if present and is a dict
        user_extra = kwargs.pop("extra", None)
        if isinstance(user_extra, dict):
            extra.update(user_extra)
        # Merge any other kwargs into extra (for arbitrary fields like 'method', 'error_type')
        for k in list(kwargs.keys()):
            if k not in ("exc_info",):  # don't merge exc_info
                extra[k] = kwargs.pop(k)
        return extra

    def info(
        self, message: str, context: Optional[Dict[str, Any]] = None, **kwargs: Any
    ) -> None:
        self.logger.info(message, extra=self._merge_extra(context, kwargs), **kwargs)

    def debug(
        self, message: str, context: Optional[Dict[str, Any]] = None, **kwargs: Any
    ) -> None:
        self.logger.debug(message, extra=self._merge_extra(context, kwargs), **kwargs)

    def warning(
        self, message: str, context: Optional[Dict[str, Any]] = None, **kwargs: Any
    ) -> None:
        self.logger.warning(message, extra=self._merge_extra(context, kwargs), **kwargs)

    def error(
        self, message: str, context: Optional[Dict[str, Any]] = None, **kwargs: Any
    ) -> None:
        self.logger.error(message, extra=self._merge_extra(context, kwargs), **kwargs)

    def critical(
        self, message: str, context: Optional[Dict[str, Any]] = None, **kwargs: Any
    ) -> None:
        self.logger.critical(
            message, extra=self._merge_extra(context, kwargs), **kwargs
        )

    def push_context(self, context: Dict[str, Any]) -> None:
        pass

    def pop_context(self) -> None:
        pass


def handle_exceptions(
    *,
    reraise: bool = True,
    default_error: Type[ArklexError] = ArklexError,
    log_level: str = "ERROR",
    include_stack_trace: bool = True,
) -> Callable:
    """Decorator for consistent exception handling and logging.

    Args:
        reraise: Whether to re-raise the exception
        default_error: Default error type to use for unknown exceptions
        log_level: Log level to use for error logging
        include_stack_trace: Whether to include stack trace in logs

    Returns:
        Decorated function
    """
    logger = logging.getLogger("arklex")

    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        async def async_wrapper(*args: Any, **kwargs: Any) -> Any:
            try:
                return await func(*args, **kwargs)
            except ArklexError:
                raise
            except Exception as e:
                context = {
                    "function": func.__name__,
                    "module": func.__module__,
                    "args": str(args),
                    "kwargs": str(kwargs),
                }
                if include_stack_trace:
                    context["stack_trace"] = traceback.format_exc()

                logger.log(
                    getattr(logging, log_level.upper(), logging.ERROR),
                    LOG_MESSAGES["ERROR"]["UNEXPECTED_ERROR"].format(
                        function=func.__name__, error=str(e)
                    ),
                    extra={"context": context},
                    exc_info=e,
                )
                if reraise:
                    raise default_error(
                        f"Operation failed in {func.__name__}",
                        details={
                            "original_error": str(e),
                            "error_type": type(e).__name__,
                            "module": func.__module__,
                        },
                    )
                return None

        @functools.wraps(func)
        def sync_wrapper(*args: Any, **kwargs: Any) -> Any:
            try:
                return func(*args, **kwargs)
            except ArklexError:
                raise
            except Exception as e:
                context = {
                    "function": func.__name__,
                    "module": func.__module__,
                    "args": str(args),
                    "kwargs": str(kwargs),
                }
                if include_stack_trace:
                    context["stack_trace"] = traceback.format_exc()

                logger.log(
                    getattr(logging, log_level.upper(), logging.ERROR),
                    LOG_MESSAGES["ERROR"]["UNEXPECTED_ERROR"].format(
                        function=func.__name__, error=str(e)
                    ),
                    extra={"context": context},
                    exc_info=e,
                )
                if reraise:
                    raise default_error(
                        f"Operation failed in {func.__name__}",
                        details={
                            "original_error": str(e),
                            "error_type": type(e).__name__,
                            "module": func.__module__,
                        },
                    )
                return None

        return async_wrapper if asyncio.iscoroutinefunction(func) else sync_wrapper

    return decorator


def with_retry(
    *,
    max_attempts: int = 3,
    min_wait: int = 1,
    max_wait: int = 10,
    retry_on: Optional[Type[Exception]] = None,
    include_stack_trace: bool = True,
) -> Callable:
    """Decorator for retrying operations with exponential backoff.

    Args:
        max_attempts: Maximum number of retry attempts
        min_wait: Minimum wait time between retries in seconds
        max_wait: Maximum wait time between retries in seconds
        retry_on: Exception type(s) to retry on
        include_stack_trace: Whether to include stack trace in logs

    Returns:
        Decorated function
    """
    logger = logging.getLogger("arklex")

    def decorator(func: Callable) -> Callable:
        @retry(
            stop=stop_after_attempt(max_attempts),
            wait=wait_exponential(multiplier=1, min=min_wait, max=max_wait),
            retry=retry_if_exception_type(retry_on or RetryableError),
        )
        @functools.wraps(func)
        async def async_wrapper(*args: Any, **kwargs: Any) -> Any:
            try:
                return await func(*args, **kwargs)
            except Exception as e:
                if isinstance(e, (retry_on or RetryableError)):
                    context = {
                        "function": func.__name__,
                        "module": func.__module__,
                        "args": str(args),
                        "kwargs": str(kwargs),
                        "attempt": getattr(e, "attempt", 0),
                        "max_attempts": max_attempts,
                    }
                    if include_stack_trace:
                        context["stack_trace"] = traceback.format_exc()

                    logger.warning(
                        LOG_MESSAGES["WARNING"]["RETRY_ATTEMPT"].format(
                            attempt=getattr(e, "attempt", 0),
                            max_attempts=max_attempts,
                            error=str(e),
                        ),
                        extra={"context": context},
                    )
                raise

        @retry(
            stop=stop_after_attempt(max_attempts),
            wait=wait_exponential(multiplier=1, min=min_wait, max=max_wait),
            retry=retry_if_exception_type(retry_on or RetryableError),
        )
        @functools.wraps(func)
        def sync_wrapper(*args: Any, **kwargs: Any) -> Any:
            try:
                return func(*args, **kwargs)
            except Exception as e:
                if isinstance(e, (retry_on or RetryableError)):
                    context = {
                        "function": func.__name__,
                        "module": func.__module__,
                        "args": str(args),
                        "kwargs": str(kwargs),
                        "attempt": getattr(e, "attempt", 0),
                        "max_attempts": max_attempts,
                    }
                    if include_stack_trace:
                        context["stack_trace"] = traceback.format_exc()

                    logger.warning(
                        LOG_MESSAGES["WARNING"]["RETRY_ATTEMPT"].format(
                            attempt=getattr(e, "attempt", 0),
                            max_attempts=max_attempts,
                            error=str(e),
                        ),
                        extra={"context": context},
                    )
                raise

        return async_wrapper if asyncio.iscoroutinefunction(func) else sync_wrapper

    return decorator
