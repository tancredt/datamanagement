import logging
from PyQt6.QtWidgets import QTextEdit
from PyQt6.QtCore import QObject, pyqtSignal

class GUILogHandler(logging.Handler):
    def __init__(self, text_widget: QTextEdit):
        super().__init__()
        self.widget = text_widget
        self.setLevel(logging.INFO)

    def emit(self, record):
        msg = self.format(record)
        color = {
            "WARNING": "orange",
            "ERROR": "red",
            "CRITICAL": "darkred"
        }.get(record.levelname, "black")
        self.widget.append(f'<span style="color:{color}">{msg}</span>')

# In your GUI setup:
configure_logging(handler=GUILogHandler(your_log_textbox))
