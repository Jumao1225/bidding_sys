import logging
import sys
from pprint import pformat
from typing import Any, Mapping

from loguru import logger
from loguru._defaults import LOGURU_FORMAT

LOGURU_INTERCEPTED_LOGGER_FAMILIES = ("httpx", "httpcore", "openai")


def console_log_filter(record: Mapping[str, Any]) -> bool:
    """
    过滤控制台中的高频 BOM 成本保存和层级汇总过程日志。

    文件 sink 不使用此过滤器，因此完整日志仍会写入 app.log；控制台仅隐藏
    高频且可由文件日志追溯的例行输出，保留慢请求、客户端错误和服务端错误，便于排查问题。
    """
    message = str(record.get("message", ""))

    # 隐藏 BOM 汇总时每个节点都会重复打印的稳定父节点关系。
    if message.startswith("BOM 使用稳定父节点关系："):
        return False

    # 隐藏业务层重复打印的成本保存成功提示。
    if message.startswith("成功更新文档 ") and "的 BOM 成本测算" in message:
        return False

    # 以下请求日志均属于成功 PUT /cost-analysis 的例行输出。
    is_cost_analysis_request = "/cost-analysis" in message
    if not is_cost_analysis_request:
        return True

    if message.startswith("👉 请求开始 | PUT | "):
        return False

    if message.startswith("👈 请求结束 | PUT | ") and "Status: 200" in message:
        # 超过 1 秒的请求带有慢请求标记，应继续显示用于性能排查。
        return "🐌" in message

    # Uvicorn access 日志也会被 InterceptHandler 转发到 Loguru，成功请求需要同步过滤。
    if (
        'PUT /api/v1/analysis/' in message
        and "/cost-analysis HTTP/" in message
        and '" 200' in message
    ):
        return False

    return True


class InterceptHandler(logging.Handler):
    """
    Loguru 官方文档中提供的默认拦截处理器。
    参考: https://loguru.readthedocs.io/en/stable/overview.html#entirely-compatible-with-standard-logging
    """
    def emit(self, record: logging.LogRecord):
        # 获取对应的 Loguru 日志级别（如果存在）
        try:
            level = logger.level(record.levelname).name
        except ValueError:
            level = record.levelno

        # 标准 logging 调用栈在当前 Python 版本固定占用 4 层，depth=6 指向真实业务调用方。
        # 这样来自 Uvicorn、OpenAI SDK 等标准 logging 的记录也会显示统一的业务来源。
        depth = 6

        logger.opt(depth=depth, exception=record.exc_info).log(
            level, record.getMessage()
        )


def _configure_logger_family(logger_name: str) -> None:
    """将指定日志器及其子日志器统一转发到 Loguru。"""
    family_logger = logging.getLogger(logger_name)
    family_logger.handlers.clear()
    family_logger.addHandler(InterceptHandler())
    family_logger.setLevel(logging.INFO)
    family_logger.propagate = False

    child_prefix = f"{logger_name}."
    for registered_name in list(logging.root.manager.loggerDict.keys()):
        if not registered_name.startswith(child_prefix):
            continue

        child_logger = logging.getLogger(registered_name)
        child_logger.handlers.clear()
        child_logger.propagate = True


def format_record(record: dict) -> str:
    """
    Loguru 的自定义日志格式。
    在调试期间，使用 pformat 漂亮地打印请求/响应体等数据。
    """
    format_string = LOGURU_FORMAT
    
    if record["extra"].get("payload") is not None:
        record["extra"]["payload"] = pformat(
            record["extra"]["payload"], indent=4, compact=True, width=88
        )
        format_string += "\n<level>{extra[payload]}</level>"
        
    format_string += "{exception}\n"
    return format_string

def setup_app_logging():
    """
    初始化 FastAPI 应用的日志系统。
    拦截并覆盖 Python 标准库的 logging，统一使用 Loguru。
    """
    # 在根日志器上拦截所有日志
    logging.root.handlers = [InterceptHandler()]
    logging.root.setLevel(logging.INFO)

    # 遍历并替换所有已注册的日志器，将其处理器替换为 InterceptHandler
    for name in logging.root.manager.loggerDict.keys():
        logging.getLogger(name).handlers = [InterceptHandler()]
        logging.getLogger(name).propagate = False

    # 第三方客户端可能在应用启动前或启动后挂载独立的终端 Handler，必须显式清理并接入 Loguru。
    for logger_name in LOGURU_INTERCEPTED_LOGGER_FAMILIES:
        _configure_logger_family(logger_name)

    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

    # 配置 Loguru 的输出端 (控制台和文件)
    logger.configure(
        handlers=[
            {
                "sink": sys.stdout,
                "level": logging.DEBUG,
                "format": format_record,
                "filter": console_log_filter,
            },

            {
                "sink": "logs/app.log", 
                "level": logging.INFO, 
                "format": format_record, 
                "rotation": "10 MB", 
                "retention": "14 days",
                "enqueue": True # 开启异步队列，保证多线程/多进程安全
            }
        ]
    )
    
    logger.info("🔥 Loguru 日志引擎初始化成功 (Console + File: logs/app.log，控制台已过滤高频成本保存及 BOM 父节点关系日志)")
