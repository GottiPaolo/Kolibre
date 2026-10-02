from datetime import datetime

from . import config


def log_message(level: str, section: str, message: str) -> None:
    timestamp = datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')
    log_line = f"{timestamp} [{level.upper()}] {section}: {message}\n"
    with open(config.LOGS_FILE, "a") as lf:
        lf.write(log_line)
