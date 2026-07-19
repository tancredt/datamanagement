import os
import sys
import json
import logging
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QComboBox,
    QPushButton, QLabel, QMessageBox, QHeaderView, QTableWidget,
    QTableWidgetItem, QDialogButtonBox
)
from PySide6.QtCore import Qt

current_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.dirname(current_dir)
if parent_dir not in sys.path:
    sys.path.insert(0, parent_dir)

logger = logging.getLogger(__name__)

class ThresholdsDialog(QDialog):
    """Dialog for managing analyte thresholds."""
    def __init__(self, parent, incident_path):
        """Initialize the thresholds dialog."""
        super().__init__(parent)
        self.incident_path = incident_path
        self.meta_dir = os.path.join(incident_path, "meta")
        self.thresholds_file = os.path.join(self.meta_dir, "thresholds.json")
        self.static_thresholds_file = os.path.normpath(
            os.path.join(current_dir, '..', 'static', 'lists', 'thresholds.json')
        )
        self.static_analytes_file = os.path.normpath(
            os.path.join(current_dir, '..', 'static', 'lists', 'analytes.json')
        )
        self.available_analytes = []
        self._load_available_analytes()
        self.thresholds_data = []
        self._load_thresholds()
        self.setWindowTitle("Manage Thresholds")
        self.resize(600, 400)
        self._setup_ui()
        self._populate_table()

    def _load_available_analytes(self):
        """Load available analytes from static config."""
        if os.path.exists(self.static_analytes_file):
            try:
                with open(self.static_analytes_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    analytes_list = data.get("analytes", [])
                    for g in analytes_list:
                        name = g.get("name")
                        if name:
                            self.available_analytes.append(name.strip())
            except (OSError, json.JSONDecodeError) as e:
                logger.error("Failed to load analytes: %s", e)

    def _load_thresholds(self):
        """Load thresholds from incident meta directory."""
        if os.path.exists(self.thresholds_file):
            try:
                with open(self.thresholds_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    thresholds_list = data.get("thresholds", [])
                    for t in thresholds_list:
                        clean_t = {
                            k.strip(): str(v).strip() for k, v in t.items()
                        }
                        self.thresholds_data.append(clean_t)
            except (OSError, json.JSONDecodeError) as e:
                logger.error("Failed to load thresholds: %s", e)

    def _setup_ui(self):
        """Set up the dialog UI."""
        layout = QVBoxLayout(self)
        self.table = QTableWidget()
        self.table.setColumnCount(5)
        self.table.setHorizontalHeaderLabels([
            "Analyte", "Hotzone", "Warmzone", "Fireground", "Community"
        ])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        layout.addWidget(self.table)
        
        add_layout = QHBoxLayout()
        add_layout.addWidget(QLabel("Add Analyte:"))
        self.cmb_add_analyte = QComboBox()
        self.cmb_add_analyte.addItems(self.available_analytes)
        self.cmb_add_analyte.setEditable(True)
        add_layout.addWidget(self.cmb_add_analyte)
        
        self.btn_add = QPushButton("Add")
        self.btn_add.clicked.connect(self._on_add)
        add_layout.addWidget(self.btn_add)
        
        self.btn_remove = QPushButton("Remove Selected")
        self.btn_remove.clicked.connect(self._on_remove)
        add_layout.addWidget(self.btn_remove)
        add_layout.addStretch()
        layout.addLayout(add_layout)
        
        btn_box = QDialogButtonBox(
            QDialogButtonBox.Save | QDialogButtonBox.Close
        )
        btn_box.accepted.connect(self._on_save)
        btn_box.rejected.connect(self.reject)
        layout.addWidget(btn_box)

    def _populate_table(self):
        """Populate the table with threshold data."""
        self.table.setRowCount(len(self.thresholds_data))
        for row, t in enumerate(self.thresholds_data):
            analyte_item = QTableWidgetItem(t.get("analyte", ""))
            analyte_item.setFlags(analyte_item.flags() & ~Qt.ItemIsEditable)
            self.table.setItem(row, 0, analyte_item)
            for col, key in enumerate([
                "hotzone_value", "warmzone_value",
                "fireground_value", "community_value"
            ], start=1):
                val = t.get(key, "")
                self.table.setItem(row, col, QTableWidgetItem(str(val)))

    def _on_add(self):
        """Handle add button click."""
        analyte = self.cmb_add_analyte.currentText().strip()
        if not analyte:
            return
        for t in self.thresholds_data:
            if t.get("analyte", "").strip().upper() == analyte.upper():
                QMessageBox.warning(
                    self, "Duplicate",
                    "Threshold for this analyte already exists."
                )
                return
        self.thresholds_data.append({
            "analyte": analyte,
            "hotzone_value": "0.0",
            "warmzone_value": "0.0",
            "fireground_value": "0.0",
            "community_value": "0.0"
        })
        self._populate_table()

    def _on_remove(self):
        """Handle remove button click."""
        row = self.table.currentRow()
        if row >= 0:
            self.thresholds_data.pop(row)
            self._populate_table()

    def _on_save(self):
        """Handle save button click."""
        for row in range(self.table.rowCount()):
            analyte_item = self.table.item(row, 0)
            if not analyte_item:
                continue
            analyte = analyte_item.text()
            t = next(
                (x for x in self.thresholds_data
                 if x.get("analyte") == analyte),
                None
            )
            if not t:
                t = {"analyte": analyte}
                self.thresholds_data.append(t)
            for col, key in enumerate([
                "hotzone_value", "warmzone_value",
                "fireground_value", "community_value"
            ], start=1):
                item = self.table.item(row, col)
                t[key] = item.text() if item else ""
        try:
            os.makedirs(self.meta_dir, exist_ok=True)
            with open(self.thresholds_file, 'w', encoding='utf-8') as f:
                json.dump({"thresholds": self.thresholds_data}, f, indent=1)
            QMessageBox.information(
                self, "Saved", "Thresholds saved successfully."
            )
            self.accept()
        except OSError as e:
            QMessageBox.critical(
                self, "Error", f"Failed to save thresholds:\n{e}"
            )
