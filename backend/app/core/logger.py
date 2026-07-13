import logging
import sys
from pprint import pformat
from loguru import logger
from loguru._defaults import LOGURU_FORMAT

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

        # 向上追溯，找到产生日志消息的实际调用者
        frame, depth = logging.currentframe(), 2
        while frame.f_code.co_filename == logging.__file__:
            frame = frame.f_back
            depth += 1

        logger.opt(depth=depth, exception=record.exc_info).log(
            level, record.getMessage()
        )

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

    # 配置 Loguru 的输出端 (控制台和文件)
    logger.configure(
        handlers=[
            {"sink": sys.stdout, "level": logging.DEBUG, "format": format_record},
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
    
    logger.info("🔥 Loguru 日志引擎初始化成功 (Console + File: logs/app.log)")
