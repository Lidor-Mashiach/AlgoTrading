import sys
from datetime import datetime


class ConsoleLogger:
    COLORS = {
        "INFO": "\033[36m",       # Cyan
        "OK": "\033[32m",         # Green
        "WARNING": "\033[33m",    # Yellow
        "ERROR": "\033[31m",      # Red
        "DEBUG": "\033[90m",      # Gray
        "START": "\033[38;5;213m",  # Pink
        "END": "\033[38;5;213m",    # Pink, to pair with START
        "REFRESH": "\033[38;5;208m",  # Orange
    }
    RESET = "\033[0m"

    def __init__(self, caller="", width=70, use_colors=True, show_time=True):
        self.caller = caller
        self.width = width
        self.use_colors = use_colors and sys.stdout.isatty()
        self.show_time = show_time

    def _timestamp(self):
        return datetime.now().strftime("%H:%M:%S")

    def _colorize(self, text, level):
        if not self.use_colors:
            return text
        color = self.COLORS.get(level, "")
        return f"{color}{text}{self.RESET}"

    def _format_label(self, level):
        label = f"[{self.caller}] [{level:^7}]"
        return self._colorize(label, level)

    def _format_timestamp(self, level):
        if not self.show_time:
            return ""
        timestamp = f"[{self._timestamp()}]"
        return self._colorize(timestamp, level) + " "

    def _log(self, level, message, end="\n"):
        timestamp = self._format_timestamp(level)
        label = self._format_label(level)
        print(f"{timestamp}{label} {message}", end=end)

    def section(self, title, end="\n"):
        self._log("START", f"----- {title} -----", end=end)

    def section_end(self, title, end="\n"):
        """Closes a section opened with section(). Same shape, different word."""
        self._log("END", f"----- {title} -----", end=end)

    def refresh(self, message, end="\n"):
        """Model refresh activity. Its own level so it stands out from ordinary info."""
        self._log("REFRESH", message, end=end)

    def subsection(self, title, end="\n"):
        self._log("START", f"----- {title} -----", end=end)

    def info(self, message, end="\n"):
        self._log("INFO", message, end=end)

    def success(self, message, end="\n"):
        self._log("OK", message, end=end)

    def warning(self, message, end="\n"):
        self._log("WARNING", message, end=end)

    def error(self, message, end="\n"):
        self._log("ERROR", message, end=end)

    def debug(self, message, end="\n"):
        self._log("DEBUG", message, end=end)