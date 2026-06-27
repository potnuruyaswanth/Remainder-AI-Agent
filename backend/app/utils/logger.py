import logging
import sys

def setup_logger():
    """Configures and returns the application-wide logger."""
    logger = logging.getLogger("email_productivity_agent")
    logger.setLevel(logging.INFO)

    # Avoid duplicate handlers if the module is re-imported
    if not logger.handlers:
        # standard log format: [timestamp] LEVEL in module: message
        formatter = logging.Formatter(
            "[%(asctime)s] %(levelname)s in %(module)s: %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S"
        )

        # stdout stream handler
        stream_handler = logging.StreamHandler(sys.stdout)
        stream_handler.setFormatter(formatter)
        logger.addHandler(stream_handler)

    return logger

logger = setup_logger()
