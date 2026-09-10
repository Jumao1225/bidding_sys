"""日志桥接单元测试。"""

import logging
from io import StringIO

from loguru import logger

from app.core.logger import InterceptHandler, _configure_logger_family


def _save_logger_state(target_logger: logging.Logger) -> tuple[list[logging.Handler], int, bool]:
    """保存日志器状态，避免测试污染其他用例。"""
    return list(target_logger.handlers), target_logger.level, target_logger.propagate


def _restore_logger_state(
    target_logger: logging.Logger,
    state: tuple[list[logging.Handler], int, bool],
) -> None:
    """恢复日志器原始状态。"""
    handlers, level, propagate = state
    target_logger.handlers = handlers
    target_logger.setLevel(level)
    target_logger.propagate = propagate


def test_configure_logger_family_should_replace_direct_handler_with_loguru_bridge() -> None:
    """正常场景：第三方日志器的独立 Handler 应被替换为 Loguru 桥接 Handler。"""
    family_name = "test_loguru_httpx"
    family_logger = logging.getLogger(family_name)
    child_logger = logging.getLogger(f"{family_name}.client")
    family_state = _save_logger_state(family_logger)
    child_state = _save_logger_state(child_logger)

    try:
        family_logger.handlers = [logging.StreamHandler()]
        family_logger.propagate = True
        child_logger.handlers = [logging.StreamHandler()]
        child_logger.propagate = False

        _configure_logger_family(family_name)

        assert len(family_logger.handlers) == 1
        assert isinstance(family_logger.handlers[0], InterceptHandler)
        assert family_logger.level == logging.INFO
        assert family_logger.propagate is False
        assert child_logger.handlers == []
        assert child_logger.propagate is True
    finally:
        _restore_logger_state(family_logger, family_state)
        _restore_logger_state(child_logger, child_state)


def test_intercept_handler_should_forward_httpx_record_to_loguru() -> None:
    """正常场景：标准 logging 的 HTTP 请求记录应通过 Loguru 输出。"""
    output = StringIO()
    sink_id = logger.add(output, format="{message}", level="INFO")

    try:
        record = logging.LogRecord(
            name="httpx",
            level=logging.INFO,
            pathname="_client.py",
            lineno=1026,
            msg='HTTP Request: POST https://llm.example/chat/completions "HTTP/1.1 200 OK"',
            args=(),
            exc_info=None,
        )
        InterceptHandler().emit(record)
    finally:
        logger.remove(sink_id)

    assert "HTTP Request: POST https://llm.example/chat/completions" in output.getvalue()


def test_configure_logger_family_should_remove_existing_child_handlers() -> None:
    """边界场景：已注册的子日志器不能保留原有 Handler，避免重复打印。"""
    family_name = "test_loguru_httpcore"
    child_logger = logging.getLogger(f"{family_name}.connection")
    child_state = _save_logger_state(child_logger)

    try:
        child_logger.handlers = [logging.StreamHandler()]
        child_logger.propagate = False

        _configure_logger_family(family_name)

        assert child_logger.handlers == []
        assert child_logger.propagate is True
    finally:
        _restore_logger_state(child_logger, child_state)
