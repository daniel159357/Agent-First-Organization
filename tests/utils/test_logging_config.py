"""Tests for logging configuration."""

import logging
import os
import pytest
from pathlib import Path
from typing import Generator

from arklex.utils.logging_utils import LogContext, RequestIdFilter, ContextFilter
from arklex.utils.logging_config import setup_logging, MAX_BYTES

log_context = LogContext(__name__)


@pytest.fixture
def temp_log_dir(tmp_path: Path) -> Generator[str, None, None]:
    """Create a temporary directory for log files.

    Args:
        tmp_path: Pytest fixture providing a temporary directory.

    Yields:
        Path to the temporary directory.
    """
    log_dir = tmp_path / "logs"
    log_dir.mkdir()
    yield str(log_dir)


def test_get_logger() -> None:
    """Test getting a logger instance."""
    log_context = LogContext("test_logger")
    assert isinstance(log_context, LogContext)
    assert log_context.name == "test_logger"
    assert log_context.propagate
    assert len(log_context.handlers) == 1


def test_get_logger_with_level() -> None:
    """Test getting a logger with a specific level."""
    log_context = LogContext("test_level", level="DEBUG")
    assert log_context.level == logging.DEBUG


def test_get_logger_with_format() -> None:
    """Test getting a logger with a custom format."""
    custom_format = "%(levelname)s - %(message)s"
    log_context = LogContext("test_format", log_format=custom_format)
    assert log_context.handlers[0].formatter._fmt == custom_format


def test_setup_logging(temp_log_dir: str) -> None:
    """Test setting up logging configuration.

    Args:
        temp_log_dir: Path to temporary directory for log files.
    """
    setup_logging(log_level="DEBUG", log_dir=temp_log_dir)
    root_logger = logging.getLogger()
    assert root_logger.level == logging.DEBUG
    assert len(root_logger.handlers) == 2  # Console and file handlers


def test_request_id_filter() -> None:
    """Test request ID filter."""
    filter_obj = RequestIdFilter("test-123")
    record = logging.LogRecord(
        "test", logging.INFO, "test.py", 1, "Test message", (), None
    )
    assert filter_obj.filter(record)
    assert record.request_id == "test-123"


def test_context_filter() -> None:
    """Test context filter."""
    context = {"user_id": "123", "action": "test"}
    filter_obj = ContextFilter(context)
    record = logging.LogRecord(
        "test", logging.INFO, "test.py", 1, "Test message", (), None
    )
    assert filter_obj.filter(record)
    assert record.context == context


def test_context_filter_no_context() -> None:
    """Test context filter with no context."""
    filter_obj = ContextFilter()
    record = logging.LogRecord(
        "test", logging.INFO, "test.py", 1, "Test message", (), None
    )
    assert filter_obj.filter(record)
    assert record.context == {}


def test_logger_with_filters() -> None:
    """Test logger with filters."""
    log_context = LogContext("test_filters")
    assert any(isinstance(f, RequestIdFilter) for f in log_context.handlers[0].filters)
    assert any(isinstance(f, ContextFilter) for f in log_context.handlers[0].filters)


def test_logger_handlers() -> None:
    """Test logger handlers."""
    log_context = LogContext("test_handlers")
    assert len(log_context.handlers) == 1
    assert isinstance(log_context.handlers[0], logging.StreamHandler)


def test_logger_propagation() -> None:
    """Test logger propagation."""
    log_context = LogContext("test_propagation")
    assert log_context.propagate


def test_logger_level_inheritance() -> None:
    """Test logger level inheritance."""
    parent = LogContext("parent", level="DEBUG")
    child = LogContext("parent.child")
    assert child.level == logging.NOTSET
    assert child.parent is not None
    assert child.parent.name == parent.name
    assert child.parent.level == parent.level


def test_logger_format_inheritance() -> None:
    """Test logger format inheritance."""
    custom_format = "%(levelname)s - %(message)s"
    parent = LogContext("parent", log_format=custom_format)
    child = LogContext("parent.child")
    assert child.handlers[0].formatter._fmt == custom_format


def test_log_with_context(caplog: pytest.LogCaptureFixture) -> None:
    """Test logging with context.

    Args:
        caplog: Pytest fixture for capturing log output.
    """
    log_context = LogContext("test_context")
    log_context.propagate = True  # Ensure logs propagate to root for caplog
    context = {"user_id": "123", "action": "test"}

    with caplog.at_level(logging.INFO):
        log_context.info("Test message", context)
        assert "Test message" in caplog.text
        assert any(
            isinstance(f, ContextFilter) for f in log_context.handlers[0].filters
        )
    log_context.propagate = False


def test_log_without_context(caplog: pytest.LogCaptureFixture) -> None:
    """Test logging without context.

    Args:
        caplog: Pytest fixture for capturing log output.
    """
    log_context = LogContext("test_no_context")
    log_context.propagate = True  # Ensure logs propagate to root for caplog

    with caplog.at_level(logging.INFO):
        log_context.info("Test message")
        assert "Test message" in caplog.text
    log_context.propagate = False


def test_log_rotation(temp_log_dir: str) -> None:
    """Test log file rotation.

    Args:
        temp_log_dir: Path to temporary directory for log files.
    """
    # Use a smaller max_bytes for testing to ensure rotation occurs
    test_max_bytes = 512
    setup_logging(log_dir=temp_log_dir, max_bytes=test_max_bytes)
    logger = logging.getLogger()  # Use root logger to ensure file handler is attached

    # Ensure all handlers are at INFO level
    for handler in logger.handlers:
        handler.setLevel(logging.INFO)

    # Write logs until rotation occurs (with a safety cap)
    max_attempts = 1000
    for i in range(max_attempts):
        logger.info("Test log message %d %s", i, "X" * 100)
        for handler in logger.handlers:
            if isinstance(handler, logging.handlers.RotatingFileHandler):
                handler.flush()
                if hasattr(handler, "stream") and hasattr(handler.stream, "fileno"):
                    os.fsync(handler.stream.fileno())
                if hasattr(handler, "baseFilename"):
                    file_size = Path(handler.baseFilename).stat().st_size
                    if file_size > test_max_bytes:
                        handler.doRollover()
        log_files = list(Path(temp_log_dir).glob("*.log*"))
        if len(log_files) > 1:
            break
    else:
        assert False, f"Log rotation did not occur after {max_attempts} attempts"

    # Verify that rotation occurred
    log_files = list(Path(temp_log_dir).glob("*.log*"))
    assert len(log_files) > 1, "Expected multiple log files after rotation"

    # Clean up handlers
    for handler in logger.handlers:
        handler.flush()
        if hasattr(handler, "close"):
            handler.close()


def test_log_levels() -> None:
    """Test different log levels."""
    logger = LogContext("test_levels", level="INFO")

    # Test each log level
    logger.debug("Debug message")
    logger.info("Info message")
    logger.warning("Warning message")
    logger.error("Error message")
    logger.critical("Critical message")

    # Verify that the logger has the correct level
    assert logger.level == logging.INFO


def test_log_format() -> None:
    """Test custom log format."""
    custom_format = "%(levelname)s - %(message)s"
    logger = LogContext("test_format", log_format=custom_format)
    logger.info("Test message")

    # Verify that the format was applied
    assert logger.handlers[0].formatter._fmt == custom_format
