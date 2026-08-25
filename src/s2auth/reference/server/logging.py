from enum import Enum
import logging
import sys


class LogLevel(str, Enum):
    DEBUG = "DEBUG"
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"
    EXCEPTION = "EXCEPTION"

    def to_logging_level(self) -> int:
        return getattr(logging, self.value)


__all__ = [
    "LogLevel",
    "setupLogging",
]


def setupLogging(default_log_level: LogLevel, logger_config: dict[str, LogLevel]):
    """Configure JSON logging with structlog + stdlib interoperability."""
    loggers: dict[str, LogLevel] = {
        "boto3": LogLevel.WARNING,
        "botocore": LogLevel.WARNING,
        "httpx": LogLevel.INFO,
        "httpcore": LogLevel.INFO,
        "aioboto3": LogLevel.WARNING,
        "aiobotocore": LogLevel.WARNING,
        "asyncpg": LogLevel.WARNING,
        "sqlalchemy": LogLevel.WARNING,
        "sqlalchemy.engine": LogLevel.WARNING,
        "asyncio": LogLevel.INFO,
        "uvicorn": LogLevel.INFO,
        "websockets": LogLevel.INFO,
    }
    loggers.update(logger_config)

    handler = logging.StreamHandler()
    formatter = logging.Formatter(fmt="%(asctime)s-%(levelname)s-%(name)s:%(message)s")
    handler.setFormatter(formatter)
    handler.setStream(sys.stdout)

    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(default_log_level.to_logging_level())

    for logger, level in loggers.items():
        logging.getLogger(logger).setLevel(level.to_logging_level())
