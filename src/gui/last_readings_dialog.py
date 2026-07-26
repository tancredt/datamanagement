import os
import sys
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QTableWidget, QTableWidgetItem,
    QHeaderView, QDialogButtonBox, QLabel
)
from PySide6.QtCore import Qt

current_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.dirname(current_dir)
if parent_dir not in sys.path:
    sys.path.insert(0, parent_dir)

from datamanagement.db_manager import IncidentDatabase


class LastReadingsDialog(QDialog):
    """Dialog showing the last reading timestamp for each area device."""

    def __init__(self, parent=None, incident_path=None):
        super().__init__(parent)
        self.incident_path = incident_path
        self.db = IncidentDatabase(incident_path) if incident_path else None

        self.setWindowTitle("Last Area Readings")
        self.resize(500, 400)
        self._setup_ui()
        self._load_data()

    def _setup_ui(self):
        layout = QVBoxLayout(self)

        self.lbl_info = QLabel("Most recent reading timestamp for each device:")
        layout.addWidget(self.lbl_info)

        self.table = QTableWidget()
        self.table.setColumnCount(2)
        self.table.setHorizontalHeaderLabels(["Device", "Last Reading"])
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.setAlternatingRowColors(True)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.verticalHeader().setVisible(False)

        # ✅ Enable sorting by clicking column headers
        self.table.setSortingEnabled(True)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)

        layout.addWidget(self.table)

        btn_box = QDialogButtonBox(QDialogButtonBox.Close)
        btn_box.rejected.connect(self.reject)
        layout.addWidget(btn_box)

    def _load_data(self):
        if not self.db:
            return

        try:
            readings = self.db.get_last_area_readings()
        except Exception as e:
            self.lbl_info.setText(f"Error loading data: {e}")
            return

        # Disable sorting while populating to avoid row reordering during insert
        self.table.setSortingEnabled(False)
        self.table.setRowCount(len(readings))

        for row, r in enumerate(readings):
            device = r.get("device") or "Unknown"
            last_reading = r.get("last_reading") or ""

            device_item = QTableWidgetItem(device)
            time_item = QTableWidgetItem(str(last_reading))

            # Store raw timestamp as sort role so sorting works correctly
            time_item.setData(Qt.UserRole, str(last_reading))

            self.table.setItem(row, 0, device_item)
            self.table.setItem(row, 1, time_item)

        # Re-enable sorting after population
        self.table.setSortingEnabled(True)

        self.lbl_info.setText(
            f"Most recent reading timestamp for each device ({len(readings)} devices):"
        )
