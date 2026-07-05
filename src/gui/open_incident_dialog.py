import os
import json
import logging
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QListWidget, QDialogButtonBox, QMessageBox
)
from PySide6.QtCore import Qt

logger = logging.getLogger(__name__)

class OpenIncidentDialog(QDialog):
    BASE_DIR = "../../incidents"

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Open Incident")
        self.setMinimumSize(400, 300)
        self._selected_data = None

        self._setup_ui()
        self._load_incidents()
        self._connect_signals()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        self.incident_list = QListWidget()
        self.incident_list.setSelectionMode(QListWidget.SingleSelection)
        layout.addWidget(self.incident_list)

        self.btn_box = QDialogButtonBox(QDialogButtonBox.Open | QDialogButtonBox.Cancel)
        layout.addWidget(self.btn_box)

    def _load_incidents(self):
        """Scan incidents directory and populate list."""
        if not os.path.isdir(self.BASE_DIR):
            os.makedirs(self.BASE_DIR, exist_ok=True)

        incidents = sorted([
            d for d in os.listdir(self.BASE_DIR) 
            if os.path.isdir(os.path.join(self.BASE_DIR, d))
        ])
        
        if not incidents:
            self.incident_list.addItem("No incidents found in directory.")
            self.btn_box.button(QDialogButtonBox.Open).setEnabled(False)
        else:
            self.incident_list.addItems(incidents)
            self.incident_list.setCurrentRow(0)

    def _connect_signals(self):
        self.btn_box.accepted.connect(self._on_open)
        self.btn_box.rejected.connect(self.reject)
        self.incident_list.itemDoubleClicked.connect(lambda: self._on_open())

    def _on_open(self):
        item = self.incident_list.currentItem()
        if not item or item.text().startswith("No "):
            return

        incident_label = item.text()
        meta_path = os.path.join(self.BASE_DIR, incident_label, "meta", "incident.json")

        if not os.path.exists(meta_path):
            QMessageBox.warning(self, "Open Error", f"Missing metadata file:\n{meta_path}")
            return

        try:
            with open(meta_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            # Ensure absolute path is stored for pipeline consistency
            data["incident_path"] = os.path.abspath(os.path.join(self.BASE_DIR, incident_label))
            self._selected_data = data
            self.accept()
        except json.JSONDecodeError as e:
            QMessageBox.critical(self, "Open Error", f"Invalid JSON in metadata:\n{e}")
        except Exception as e:
            QMessageBox.critical(self, "Open Error", f"Failed to load incident:\n{e}")
            logger.error("Failed to open incident %s: %s", incident_label, e)

    def get_data(self) -> dict:
        return self._selected_data
