import os
import logging
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QComboBox,
    QTableWidget, QTableWidgetItem, QPushButton, QDialogButtonBox,
    QLabel, QMessageBox, QHeaderView, QFormLayout, QDateTimeEdit, QLineEdit,
    QStyle, QScrollArea, QWidget
)
from PySide6.QtCore import Qt, QDateTime, QSize
from PySide6.QtGui import QDoubleValidator
from datamanagement.db_manager import IncidentDatabase

logger = logging.getLogger(__name__)
DATE_FORMAT = "yyyy-MM-dd HH:mm:ss"


class AddExposureDialog(QDialog):
    """Dialog to input details for a personnel exposure event."""
    def __init__(self, parent=None, incident_path=None, initial_data=None):
        super().__init__(parent)
        self.incident_path = incident_path
        self.db = IncidentDatabase(incident_path)

        # ✅ Fetch choices directly from the database
        analytes_data = self.db.get_analytes()
        self.available_analytes = [a['label'] for a in analytes_data]
        self.analyte_lookup = {a['label']: a['id'] for a in analytes_data}
        
        self.available_ids = self.db.get_exposure_ids()
        self.available_devices = self.db.get_devices("exposure") # <-- FIXED: Pass "exposure" to get spot & personal devices
        
        self.initial_data = initial_data

        self.setWindowTitle("Edit Exposure" if initial_data else "Add Exposure")
        self.setMinimumWidth(550)
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(10)
        layout.setContentsMargins(16, 16, 16, 16)

        form = QFormLayout()
        form.setSpacing(8)
        form.setLabelAlignment(Qt.AlignRight)

        # Id (Editable Combo Box)
        self.cmb_id = QComboBox()
        self.cmb_id.setEditable(True)
        self.cmb_id.setMinimumHeight(28)
        self.cmb_id.setPlaceholderText("e.g., reg no or name")
        self.cmb_id.addItems(self.available_ids)
        form.addRow("Id *:", self.cmb_id)

        # Device (Editable Combo Box)
        self.cmb_device = QComboBox()
        self.cmb_device.setEditable(True)
        self.cmb_device.setMinimumHeight(28)
        self.cmb_device.setPlaceholderText("Device label...")
        self.cmb_device.addItems(self.available_devices)
        form.addRow("Device *:", self.cmb_device)

        # Start & Stop
        self.dt_start = QDateTimeEdit()
        self.dt_start.setCalendarPopup(True)
        self.dt_start.setDateTime(QDateTime.currentDateTime())
        self.dt_start.setDisplayFormat(DATE_FORMAT)
        self.dt_start.setMinimumHeight(28)
        form.addRow("Start *:", self.dt_start)

        self.dt_stop = QDateTimeEdit()
        self.dt_stop.setCalendarPopup(True)
        self.dt_stop.setDateTime(QDateTime.currentDateTime())
        self.dt_stop.setDisplayFormat(DATE_FORMAT)
        self.dt_stop.setMinimumHeight(28)
        form.addRow("Stop *:", self.dt_stop)

        # Area (Editable Combo Box)
        self.cmb_area = QComboBox()
        self.cmb_area.setEditable(False)
        self.cmb_area.setMinimumHeight(28)
        self.cmb_area.addItems(["Hotzone", "Warmzone", "Fireground", "Community"])
        form.addRow("Area:", self.cmb_area)

        self.le_activities = QLineEdit()
        self.le_activities.setPlaceholderText("Activities performed...")
        self.le_activities.setMinimumHeight(28)
        form.addRow("Activities Performed:", self.le_activities)

        # ✅ Resp. Protection Combo (Added "Unknown")
        self.cmb_resp_protection = QComboBox()
        self.cmb_resp_protection.addItems(["None", "SCBA", "P3", "Canister", "Unknown", "Other"])
        self.cmb_resp_protection.setMinimumHeight(28)
        form.addRow("Resp. Protection:", self.cmb_resp_protection)

        # ✅ Clothing (Suit) Combo (Added "Unknown")
        self.cmb_clothing = QComboBox()
        self.cmb_clothing.addItems(["Structural", "Splash", "Fully Encapsulated", "Unknown", "Other"])
        self.cmb_clothing.setMinimumHeight(28)
        form.addRow("Clothing:", self.cmb_clothing)

        # ✅ Footwear Combo (Added "Unknown")
        self.cmb_footwear = QComboBox()
        self.cmb_footwear.addItems(["Structural boots", "Chemical boots", "Shoes", "Unknown", "Other"])
        self.cmb_footwear.setMinimumHeight(28)
        form.addRow("Footwear:", self.cmb_footwear)

        layout.addLayout(form)

        # ─────────────────────────────────────────────────────────
        # Analyte Readings Grid (Scrollable)
        # ─────────────────────────────────────────────────────────
        layout.addWidget(QLabel("<b>Analyte Readings (Min, Max, Mean):</b>"))
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setMinimumHeight(180)
        self.scroll.setMaximumHeight(250)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)

        self.analyte_table = QTableWidget()
        self.analyte_table.setColumnCount(4)
        self.analyte_table.setHorizontalHeaderLabels(["Analyte", "Min", "Max", "Mean"])
        self.analyte_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.analyte_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.analyte_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        self.analyte_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.Stretch)
        self.analyte_table.setRowCount(len(self.available_analytes))
        self.analyte_table.verticalHeader().setVisible(False)

        self.analyte_inputs = {}
        for row, analyte in enumerate(self.available_analytes):
            item_analyte = QTableWidgetItem(analyte)
            item_analyte.setFlags(item_analyte.flags() & ~Qt.ItemIsEditable)
            self.analyte_table.setItem(row, 0, item_analyte)

            self.analyte_inputs[analyte] = {}
            for col, key in enumerate(["min", "max", "mean"], start=1):
                le = QLineEdit()
                le.setValidator(QDoubleValidator())
                le.setPlaceholderText("Optional")
                le.setStyleSheet("QLineEdit { padding: 4px; }")
                self.analyte_table.setCellWidget(row, col, le)
                self.analyte_inputs[analyte][key] = le

        self.scroll.setWidget(self.analyte_table)
        layout.addWidget(self.scroll)

        # Populate fields if editing
        if self.initial_data:
            self.cmb_id.setCurrentText(self.initial_data.get("id", ""))
            self.cmb_device.setCurrentText(self.initial_data.get("device", ""))
            
            dt_start = QDateTime.fromString(self.initial_data.get("start", ""), DATE_FORMAT)
            if dt_start.isValid(): self.dt_start.setDateTime(dt_start)
            
            dt_stop = QDateTime.fromString(self.initial_data.get("stop", ""), DATE_FORMAT)
            if dt_stop.isValid(): self.dt_stop.setDateTime(dt_stop)
            
            self.cmb_area.setCurrentText(self.initial_data.get("area", ""))
            self.le_activities.setText(self.initial_data.get("activities", ""))
            
            idx = self.cmb_resp_protection.findText(self.initial_data.get("resp_protection", "None"))
            if idx >= 0: self.cmb_resp_protection.setCurrentIndex(idx)
            
            idx = self.cmb_clothing.findText(self.initial_data.get("clothing", "Structural"))
            if idx >= 0: self.cmb_clothing.setCurrentIndex(idx)
            
            idx = self.cmb_footwear.findText(self.initial_data.get("footwear", "Structural boots"))
            if idx >= 0: self.cmb_footwear.setCurrentIndex(idx)

            values_data = self.initial_data.get("values", {})
            for analyte in self.available_analytes:
                analyte_stats = values_data.get(analyte, {})
                for key in ["min", "max", "mean"]:
                    val = analyte_stats.get(key)
                    if val is not None and analyte in self.analyte_inputs:
                        self.analyte_inputs[analyte][key].setText(str(val))

        layout.addSpacing(10)
        btn_box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        btn_box.setMinimumHeight(34)
        layout.addWidget(btn_box)
        btn_box.rejected.connect(self.reject)
        ok_button = btn_box.button(QDialogButtonBox.Ok)
        ok_button.clicked.connect(self._validate_and_accept)

    def _validate_and_accept(self):
        exp_id = self.cmb_id.currentText().strip()
        if not exp_id:
            QMessageBox.warning(self, "Validation Error", "Id is mandatory.")
            self.cmb_id.setFocus()
            return

        device = self.cmb_device.currentText().strip()
        if not device:
            QMessageBox.warning(self, "Validation Error", "Device is mandatory.")
            self.cmb_device.setFocus()
            return

        if self.dt_start.dateTime() >= self.dt_stop.dateTime():
            QMessageBox.warning(self, "Validation Error", "Start time must be before Stop time.")
            self.dt_stop.setFocus()
            return

        self.accept()

    def get_data(self):
        data = {
            "id": self.cmb_id.currentText().strip(),
            "device": self.cmb_device.currentText().strip(),
            "start": self.dt_start.dateTime().toString(DATE_FORMAT),
            "stop": self.dt_stop.dateTime().toString(DATE_FORMAT),
            "area": self.cmb_area.currentText().strip(),
            "activities": self.le_activities.text().strip(),
            "resp_protection": self.cmb_resp_protection.currentText(),
            "clothing": self.cmb_clothing.currentText(),
            "footwear": self.cmb_footwear.currentText()
        }
        
        values = {}
        for analyte, inputs in self.analyte_inputs.items():
            mean_str = inputs["mean"].text().strip()
            max_str = inputs["max"].text().strip()
            min_str = inputs["min"].text().strip()
            
            if mean_str or max_str or min_str:
                analyte_data = {}
                if mean_str:
                    try: analyte_data["mean"] = float(mean_str)
                    except ValueError: pass
                if max_str:
                    try: analyte_data["max"] = float(max_str)
                    except ValueError: pass
                if min_str:
                    try: analyte_data["min"] = float(min_str)
                    except ValueError: pass
                    
                if analyte_data:
                    values[analyte] = analyte_data
                    
        data["values"] = values
        return data


class ExposuresDialog(QDialog):
    def __init__(self, parent=None, incident_path=None):
        super().__init__(parent)
        self.incident_path = incident_path

        # ✅ Initialize Database Manager
        self.db = IncidentDatabase(incident_path)
        
        # ✅ Load analytes and decimal places from DB
        analytes_data = self.db.get_analytes()
        self.available_analytes = [a['label'] for a in analytes_data]
        self.analyte_dec_pls = {a['label']: a['dec_pls'] for a in analytes_data}
        self.analyte_lookup = {a['label']: a['id'] for a in analytes_data}
        
        # ✅ Load all exposures from DB
        self.all_exposures = self.db.get_exposures()

        self.setWindowTitle("Exposure Records Manager")
        self.resize(1100, 600)
        self._setup_ui()
        self._connect_signals()
        self._update_table()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(12)
        layout.setContentsMargins(16, 16, 16, 16)

        self.table = QTableWidget()
        headers = ["Id", "Device", "Start", "Stop", "Area", "Activities Performed", 
                   "Resp. Protection", "Clothing", "Footwear"] + self.available_analytes
        self.table.setColumnCount(len(headers))
        self.table.setHorizontalHeaderLabels(headers)
        
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(5, QHeaderView.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(6, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(7, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(8, QHeaderView.ResizeToContents)
        for i in range(9, len(headers)):
            self.table.horizontalHeader().setSectionResizeMode(i, QHeaderView.ResizeToContents)
            
        self.table.setAlternatingRowColors(True)
        self.table.setWordWrap(True)
        self.table.setStyleSheet("QTableWidget { font-size: 12px; }")
        layout.addWidget(self.table)

        btn_row = QHBoxLayout()
        self.btn_add = QPushButton("Add Exposure...")
        self.btn_add.setMinimumHeight(32)
        self.btn_add.setIcon(self.style().standardIcon(QStyle.SP_FileDialogNewFolder))
        self.btn_add.setIconSize(QSize(18, 18))
        btn_row.addWidget(self.btn_add)

        self.btn_edit = QPushButton("Edit Selected...")
        self.btn_edit.setMinimumHeight(32)
        self.btn_edit.setIcon(self.style().standardIcon(QStyle.SP_FileDialogDetailedView))
        self.btn_edit.setIconSize(QSize(18, 18))
        self.btn_edit.setEnabled(False)
        btn_row.addWidget(self.btn_edit)

        self.btn_remove = QPushButton("Remove Selected")
        self.btn_remove.setMinimumHeight(32)
        self.btn_remove.setIcon(self.style().standardIcon(QStyle.SP_TrashIcon))
        self.btn_remove.setIconSize(QSize(18, 18))
        self.btn_remove.setEnabled(False)
        btn_row.addWidget(self.btn_remove)
        btn_row.addStretch()
        layout.addLayout(btn_row)  

        self.btn_box = QDialogButtonBox(QDialogButtonBox.Ok)
        self.btn_box.setMinimumHeight(34)
        layout.addWidget(self.btn_box)

    def _connect_signals(self):
        self.btn_add.clicked.connect(self._on_add)
        self.btn_edit.clicked.connect(self._on_edit)
        self.btn_remove.clicked.connect(self._on_remove)
        self.btn_box.accepted.connect(self.accept) # Just closes dialog, data is already saved
        self.table.currentCellChanged.connect(self._update_button_states)

    def _update_button_states(self):
        has_selection = self.table.currentRow() >= 0
        self.btn_edit.setEnabled(has_selection)
        self.btn_remove.setEnabled(has_selection)

    def _update_table(self):
        # Determine which analytes actually have data across all exposures
        active_analytes = []
        for analyte in self.available_analytes:
            for exp in self.all_exposures:
                has_data = False
                values = exp.get("values", {})
                if analyte in values:
                    stats = values[analyte]
                    if any(stats.get(k) not in [None, ""] for k in ["min", "max", "mean"]):
                        has_data = True
                if has_data:
                    active_analytes.append(analyte)
                    break

        headers = ["Id", "Device", "Start", "Stop", "Area", "Activities Performed", 
                   "Resp. Protection", "Clothing", "Footwear"] + active_analytes
        self.table.setColumnCount(len(headers))
        self.table.setHorizontalHeaderLabels(headers)
        
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(5, QHeaderView.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(6, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(7, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(8, QHeaderView.ResizeToContents)
        for i in range(9, len(headers)):
            self.table.horizontalHeader().setSectionResizeMode(i, QHeaderView.ResizeToContents)

        self.table.setRowCount(len(self.all_exposures))
        for i, exp_data in enumerate(self.all_exposures):
            self.table.setItem(i, 0, QTableWidgetItem(exp_data.get("id", "")))
            self.table.setItem(i, 1, QTableWidgetItem(exp_data.get("device", "")))
            self.table.setItem(i, 2, QTableWidgetItem(exp_data.get("start", "")))
            self.table.setItem(i, 3, QTableWidgetItem(exp_data.get("stop", "")))
            self.table.setItem(i, 4, QTableWidgetItem(exp_data.get("area", "")))
            self.table.setItem(i, 5, QTableWidgetItem(exp_data.get("activities", "")))
            self.table.setItem(i, 6, QTableWidgetItem(exp_data.get("resp_protection", "")))
            self.table.setItem(i, 7, QTableWidgetItem(exp_data.get("clothing", "")))
            self.table.setItem(i, 8, QTableWidgetItem(exp_data.get("footwear", "")))

            values = exp_data.get("values", {})
            for j, analyte in enumerate(active_analytes):
                dec_pls = self.analyte_dec_pls.get(analyte, 2)
                stats = values.get(analyte, {})
                min_val = stats.get("min")
                max_val = stats.get("max")
                mean_val = stats.get("mean")

                parts = []
                if mean_val is not None and mean_val != "": parts.append(f"Mean: {float(mean_val):.{dec_pls}f}")
                if min_val is not None and min_val != "": parts.append(f"Min: {float(min_val):.{dec_pls}f}")
                if max_val is not None and max_val != "": parts.append(f"Max: {float(max_val):.{dec_pls}f}")

                text = "\n".join(parts) if parts else ""
                self.table.setItem(i, 9 + j, QTableWidgetItem(text))

        self.table.resizeRowsToContents()
        self._update_button_states()

    def _on_add(self):
        dialog = AddExposureDialog(self, incident_path=self.incident_path)
        if dialog.exec() == QDialog.Accepted:
            new_data = dialog.get_data()
            # ✅ Save immediately to DB
            self.db.add_exposure(new_data, self.analyte_lookup)
            self.all_exposures = self.db.get_exposures()
            self._update_table()
            QMessageBox.information(self, "Added", "Exposure added.")

    def _on_edit(self):
        selected_row = self.table.currentRow()
        if selected_row >= 0:
            old_data = self.all_exposures[selected_row]
            dialog = AddExposureDialog(
                self, 
                incident_path=self.incident_path,
                initial_data=old_data
            )
            if dialog.exec() == QDialog.Accepted:
                new_data = dialog.get_data()
                # ✅ Update DB
                success, msg = self.db.edit_exposure(old_data, new_data, self.analyte_lookup)
                if success:
                    self.all_exposures = self.db.get_exposures()
                    self._update_table()
                    QMessageBox.information(self, "Updated", "Exposure updated.")
                else:
                    QMessageBox.critical(self, "Database Error", msg)
        else:
            QMessageBox.information(self, "No Selection", "Please select a row in the table to edit.")

    def _on_remove(self):
        selected_row = self.table.currentRow()
        if selected_row >= 0:
            exp_data = self.all_exposures[selected_row]
            reply = QMessageBox.question(
                self, "Confirm Deletion",
                f"Are you sure you want to remove exposure '{exp_data.get('id')}'?",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No
            )
            if reply == QMessageBox.Yes:
                # ✅ Delete from DB
                self.db.delete_exposure(exp_data)
                self.all_exposures = self.db.get_exposures()
                self._update_table()
        else:
            QMessageBox.information(self, "No Selection", "Please select a row in the table to remove.")
