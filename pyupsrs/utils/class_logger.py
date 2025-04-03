"""Mixin Logger for per Class logging."""

import logging
from typing import Optional


class LoggerMixin:
    """A mixin class that provides a class-specific logger."""

    _loggers: dict[str, logging.Logger] = {}

    @classmethod
    def get_logger(cls) -> logging.Logger:
        """
        Get a logger for the class.

        Returns:
            logging.Logger: A logger instance specific to the class.

        """
        class_name = cls.__name__
        if class_name not in cls._loggers:
            cls._loggers[class_name] = logging.getLogger(f"{cls.__module__}.{class_name}")
        return cls._loggers[class_name]

    @property
    def logger(self) -> logging.Logger:
        """
        Property to access the class logger.

        Returns:
            logging.Logger: A logger instance specific to the class.

        """
        return self.get_logger()


def configure_logging(level: int = logging.INFO, log_format: Optional[str] = None, log_file: Optional[str] = None) -> None:
    """
    Configure the logging system.

    Args:
        level: The logging level to use.
        log_format: The format string to use for log messages.
        log_file: The file to write log messages to.

    """
    if log_format is None:
        log_format = "%(asctime)s - %(name)s - %(levelname)s - %(filename)s:%(lineno)d:%(funcName)s - %(message)s"

    # Add console handler
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(logging.Formatter(log_format))
    handlers = [console_handler]
    # Add file handler if specified
    if log_file:
        file_handler = logging.FileHandler(log_file)
        file_handler.setFormatter(logging.Formatter(log_format))
        handlers.append(file_handler)

    # Configure root logger
    logging.basicConfig(level=level, format=log_format, handlers=handlers, force=True)


# Example usage
class ExampleClass(LoggerMixin):
    """Self test for LoggerMixin."""

    def __init__(self, name: str) -> None:
        """Initialize ExampleClass."""
        self.name = name
        self.logger.info(f"Created instance of {self.__class__.__name__} with name: {name}")

    def do_something(self) -> None:
        """Do Dummy method."""
        self.logger.debug(f"Instance {self.name} is doing something")


if __name__ == "__main__":
    # Configure logging
    configure_logging(level=logging.DEBUG)

    # Use the logger in a class
    example = ExampleClass("test")
    example.do_something()

    # Use the class logger directly
    ExampleClass.get_logger().warning("This is a class-level log message")
