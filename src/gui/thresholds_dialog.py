import os
import sys
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

from datamanagement.db_manager import IncidentDatabase

logger = logging.getLogger(__name__)

class ThresholdsDialog(QDialog):
    """Dialog for managing analyte thresholds directly in the database."""
    
    def __init__(self, parent, incident_path):
        super().__init__(parent)
        self.incident_path = incident_path
        self.db = IncidentDatabase(incident_path)
        
        self.available_analytes = []
        self.thresholds_data = []
        
        self._load_data_from_db()
        
        self.setWindowTitle("Manage Thresholds")
        self.resize(600, 400)
        self._setup_ui()
        self._populate_table()
    
    def _load_data_from_db(self):
        """Load available analytes and their thresholds from the database."""
        try:
            # ✅ Use db_manager method instead of direct SQL
            thresholds = self.db.get_all_thresholds()
            
            for t in thresholds:
                label = t.get('label', '')
                self.available_analytes.append(label)
                self.thresholds_data.append({
                    "analyte": label,
                    "hotzone_value": str(t.get('hotzone_threshold', 0.0)),
                    "warmzone_value": str(t.get('warmzone_threshold', 0.0)),
                    "fireground_value": str(t.get('fireground_threshold', 0.0)),
                    "community_value": str(t.get('community_threshold', 0.0))
                })
        except Exception as e:
            logger.error(f"Failed to load thresholds from DB: {e}")
            QMessageBox.critical(self, "Error", f"Failed to load thresholds from database:\n{e}")
    
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
                val = t.get(key, "0.0")
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
                    "Threshold for this analyte already exists in the list."
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
        """Handle save button click - writes directly to the database."""
        try:
            # Build list of threshold updates
            updates = []
            for row in range(self.table.rowCount()):
                analyte_item = self.table.item(row, 0)
                if not analyte_item:
                    continue
                
                analyte = analyte_item.text().strip()
                
                def get_val(c):
                    item = self.table.item(row, c)
                    return float(item.text()) if item and item.text() else 0.0
                
                updates.append({
                    'label': analyte,
                    'hotzone': get_val(1),
                    'warmzone': get_val(2),
                    'fireground': get_val(3),
                    'community': get_val(4)
                })
            
            # ✅ Use db_manager method instead of direct SQL
            self.db.update_thresholds(updates)
            
            QMessageBox.information(self, "Saved", "Thresholds saved successfully to database.")
            self.accept()
        except ValueError as e:
            QMessageBox.critical(self, "Validation Error", f"Please enter valid numbers for thresholds:\n{e}")
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to save thresholds to database:\n{e}")
