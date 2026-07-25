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
from map_viewer_dialog import MapViewerDialog

logger = logging.getLogger(__name__)
DATE_FORMAT = "yyyy-MM-dd HH:mm:ss"

class AddSpotReadingDialog(QDialog):
    def __init__(self, parent=None, incident_path=None, initial_data=None, existing_readings=None, exclude_index=None):
        super().__init__(parent)
        self.incident_path = incident_path
        self.db = IncidentDatabase(incident_path)
        
        # ✅ Populate choices directly from the database every time the dialog is opened
        self.available_labels = self.db.get_markers()
        self.available_devices = self.db.get_devices("spot") # Only returns device_type == 'spot'
        
        analytes_data = self.db.get_analytes()
        self.available_analytes = [a['label'] for a in analytes_data]
        
        self.initial_data = initial_data
        self.existing_readings = existing_readings or []
        self.exclude_index = exclude_index

        self.setWindowTitle("Edit Spot Reading" if initial_data else "Add Spot Reading")
        self.setMinimumWidth(450)
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(10)
        layout.setContentsMargins(16, 16, 16, 16)
        form = QFormLayout()
        form.setSpacing(8)
        form.setLabelAlignment(Qt.AlignRight)

        self.cmb_location = QComboBox()
        self.cmb_location.setMinimumHeight(28)
        self.cmb_location.setEditable(False)
        self.cmb_location.addItems(self.available_labels if self.available_labels else [])
        self.cmb_location.setPlaceholderText("Select location...")
        form.addRow("Location *:", self.cmb_location)

        self.cmb_device = QComboBox()
        self.cmb_device.setEditable(True)
        self.cmb_device.setMinimumHeight(28)
        self.cmb_device.setPlaceholderText("Optional device label...")
        self.cmb_device.addItems(self.available_devices)
        form.addRow("Device:", self.cmb_device)

        self.dt_logtime = QDateTimeEdit()
        self.dt_logtime.setCalendarPopup(True)
        self.dt_logtime.setDateTime(QDateTime.currentDateTime())
        self.dt_logtime.setDisplayFormat(DATE_FORMAT)
        self.dt_logtime.setMinimumHeight(28)
        form.addRow("Log Time *:", self.dt_logtime)

        self.le_observations = QLineEdit()
        self.le_observations.setPlaceholderText("Optional observations...")
        self.le_observations.setMinimumHeight(28)
        form.addRow("Observations:", self.le_observations)

        layout.addLayout(form)
        layout.addWidget(QLabel("<b>Analyte Readings:</b>"))

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setMinimumHeight(200)
        self.scroll.setMaximumHeight(300)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        
        self.scroll_widget = QWidget()
        self.analyte_layout = QFormLayout(self.scroll_widget)
        self.analyte_layout.setSpacing(6)
        self.analyte_layout.setLabelAlignment(Qt.AlignRight)
        
        self.analyte_inputs = {}
        for analyte in self.available_analytes:
            le = QLineEdit()
            le.setPlaceholderText("Optional")
            le.setMinimumHeight(26)
            le.setValidator(QDoubleValidator())
            self.analyte_layout.addRow(f"{analyte}:", le)
            self.analyte_inputs[analyte] = le
            
        self.scroll.setWidget(self.scroll_widget)
        layout.addWidget(self.scroll)

        if self.initial_data:
            self.cmb_location.setCurrentText(self.initial_data.get("location", ""))
            self.cmb_device.setCurrentText(self.initial_data.get("device", ""))
            dt = QDateTime.fromString(self.initial_data.get("logtime", ""), DATE_FORMAT)
            if dt.isValid():
                self.dt_logtime.setDateTime(dt)
            self.le_observations.setText(self.initial_data.get("observations", ""))
            for analyte in self.available_analytes:
                val = self.initial_data.get(analyte)
                if val is not None and analyte in self.analyte_inputs:
                    self.analyte_inputs[analyte].setText(str(val))

        layout.addSpacing(10)
        btn_box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        btn_box.setMinimumHeight(34)
        layout.addWidget(btn_box)

        btn_box.rejected.connect(self.reject)
        ok_button = btn_box.button(QDialogButtonBox.Ok)
        ok_button.clicked.connect(self._validate_and_accept)

    def _validate_and_accept(self):
        location = self.cmb_location.currentText().strip()
        if not location:
            QMessageBox.warning(self, "Validation Error", "Location is mandatory.")
            self.cmb_location.setFocus()
            return

        has_value = any(le.text().strip() for le in self.analyte_inputs.values())
        if not has_value:
            QMessageBox.warning(self, "Validation Error", "Please enter a value for at least one analyte.")
            return

        self.accept()

    def get_data(self):
        data = {
            "location": self.cmb_location.currentText().strip(),
            "device": self.cmb_device.currentText().strip(),
            "logtime": self.dt_logtime.dateTime().toString(DATE_FORMAT),
            "observations": self.le_observations.text().strip()
        }
        for analyte, le in self.analyte_inputs.items():
            val_str = le.text().strip()
            if val_str:
                try: data[analyte] = float(val_str)
                except ValueError: pass
        return data


class SpotReadingsDialog(QDialog):
    def __init__(self, parent=None, incident_path=None):
        super().__init__(parent)
        self.incident_path = incident_path
        self.mapping_dir = os.path.join(incident_path, "mapping")
        
        # Initialize Database Manager
        self.db = IncidentDatabase(incident_path)
        
        # Load initial reference data and readings
        self._refresh_reference_data()
        self.all_readings = self.db.get_spot_readings()

        self.setWindowTitle("Spot Readings Manager")
        self.resize(1000, 600)
        self._setup_ui()
        self._connect_signals()
        self._populate_filter()
        self._update_table()

    def _refresh_reference_data(self):
        """Helper to fetch the latest labels, devices, and analytes from the DB."""
        self.available_labels = self.db.get_markers()
        self.available_devices = self.db.get_devices("spot")
        
        analytes_data = self.db.get_analytes()
        self.available_analytes = [a['label'] for a in analytes_data]
        self.analyte_dec_pls = {a['label']: a['dec_pls'] for a in analytes_data}
        self.analyte_lookup = {a['label']: a['id'] for a in analytes_data}

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(12)
        layout.setContentsMargins(16, 16, 16, 16)

        ctrl_row = QHBoxLayout()
        self.btn_show_maps = QPushButton("Show Map(s)")
        self.btn_show_maps.setMinimumHeight(32)
        self.btn_show_maps.setIcon(self.style().standardIcon(QStyle.SP_FileDialogListView))
        self.btn_show_maps.setIconSize(QSize(18, 18))
        ctrl_row.addWidget(self.btn_show_maps)

        ctrl_row.addWidget(QLabel("Filter by Location:"))
        self.cmb_filter = QComboBox()
        self.cmb_filter.setMinimumWidth(150)
        ctrl_row.addWidget(self.cmb_filter)
        ctrl_row.addStretch()
        layout.addLayout(ctrl_row)

        self.table = QTableWidget()
        
        # Analytes come BEFORE Observations
        headers = ["Location", "Device", "Log Time"] + self.available_analytes + ["Observations"]
        self.table.setColumnCount(len(headers))
        self.table.setHorizontalHeaderLabels(headers)
        
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        for i in range(3, 3 + len(self.available_analytes)):
            self.table.horizontalHeader().setSectionResizeMode(i, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(3 + len(self.available_analytes), QHeaderView.Stretch)
        
        self.table.setAlternatingRowColors(True)
        self.table.setStyleSheet("QTableWidget { font-size: 12px; }")
        layout.addWidget(self.table)

        btn_row = QHBoxLayout()
        self.btn_add = QPushButton("Add Reading...")
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
        self.btn_show_maps.clicked.connect(self._on_show_maps)
        self.btn_add.clicked.connect(self._on_add)
        self.btn_edit.clicked.connect(self._on_edit)
        self.btn_remove.clicked.connect(self._on_remove)
        self.btn_box.accepted.connect(self.accept) 
        self.cmb_filter.currentTextChanged.connect(self._update_table)
        self.table.currentCellChanged.connect(self._update_button_states)

    def _update_button_states(self):
        has_selection = self.table.currentRow() >= 0
        self.btn_edit.setEnabled(has_selection)
        self.btn_remove.setEnabled(has_selection)

    def _populate_filter(self):
        self.cmb_filter.blockSignals(True)
        self.cmb_filter.clear()
        self.cmb_filter.addItem("All")
        self.cmb_filter.addItems(self.available_labels)
        self.cmb_filter.setCurrentText("All")
        self.cmb_filter.blockSignals(False)

    def _update_table(self):
        # 1. Determine which analytes actually have data across all readings
        active_analytes = []
        for analyte in self.available_analytes:
            for r in self.all_readings:
                val = r.get(analyte)
                if val is not None and str(val).strip() != "":
                    active_analytes.append(analyte)
                    break

        filter_val = self.cmb_filter.currentText()
        rows_data = [(i, r) for i, r in enumerate(self.all_readings) if filter_val == "All" or r.get("location") == filter_val]

        # 2. Dynamically set headers and column count based on active analytes
        headers = ["Location", "Device", "Log Time"] + active_analytes + ["Observations"]
        self.table.setColumnCount(len(headers))
        self.table.setHorizontalHeaderLabels(headers)

        # Re-apply column resizing modes
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        for i in range(3, 3 + len(active_analytes)):
            self.table.horizontalHeader().setSectionResizeMode(i, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(3 + len(active_analytes), QHeaderView.Stretch)

        self.table.setRowCount(len(rows_data))
        for i, (orig_idx, r_data) in enumerate(rows_data):
            item = QTableWidgetItem(r_data.get("location", ""))
            item.setData(Qt.UserRole, orig_idx)
            self.table.setItem(i, 0, item)
            self.table.setItem(i, 1, QTableWidgetItem(r_data.get("device", "")))
            self.table.setItem(i, 2, QTableWidgetItem(r_data.get("logtime", "")))

            # Populate active analyte columns
            for j, analyte in enumerate(active_analytes):
                val = r_data.get(analyte)
                if val is not None:
                    dec_pls = self.analyte_dec_pls.get(analyte, 2) 
                    val_str = f"{val:.{dec_pls}f}" if isinstance(val, (int, float)) else str(val)
                    self.table.setItem(i, 3 + j, QTableWidgetItem(val_str))
                else:
                    self.table.setItem(i, 3 + j, QTableWidgetItem(""))
            
            # Populate Observations column
            obs_col_idx = 3 + len(active_analytes)
            self.table.setItem(i, obs_col_idx, QTableWidgetItem(r_data.get("observations", "")))

        self.table.resizeRowsToContents()
        self._update_button_states()

    def _on_show_maps(self):
        maps_data = self.db.get_maps_data()
        # Translate x_coord/y_coord to x/y for the MapViewerDialog canvas
        for fname, markers in maps_data.items():
            for m in markers:
                m['x'] = m.pop('x_coord', 0)
                m['y'] = m.pop('y_coord', 0)
                
        available_markers = {fname: [m.get("label") for m in markers if m.get("label")] for fname, markers in maps_data.items()}
        dialog = MapViewerDialog(self, available_markers, maps_data, self.mapping_dir)
        dialog.exec()

    def _on_add(self):
        # ✅ Pass incident_path so the dialog can fetch fresh choices from the DB
        dialog = AddSpotReadingDialog(
            self, 
            incident_path=self.incident_path,
            existing_readings=self.all_readings
        )
        if dialog.exec() == QDialog.Accepted:
            new_data = dialog.get_data()
            success, msg = self.db.add_spot_reading(new_data, self.analyte_lookup)
            if success:
                # ✅ Refresh reference data in case a new device was auto-created
                self._refresh_reference_data()
                self.all_readings = self.db.get_spot_readings()
                self._populate_filter() # Update filter dropdown with any new markers
                self._update_table()
                QMessageBox.information(self, "Added", "Reading added.")
            else:
                QMessageBox.warning(self, "Duplicate Reading", msg)

    def _on_edit(self):
        selected_row = self.table.currentRow()
        if selected_row >= 0:
            item = self.table.item(selected_row, 0)
            orig_idx = item.data(Qt.UserRole)
            if orig_idx is not None and 0 <= orig_idx < len(self.all_readings):
                old_data = self.all_readings[orig_idx]
                # ✅ Pass incident_path so the dialog can fetch fresh choices from the DB
                dialog = AddSpotReadingDialog(
                    self, 
                    incident_path=self.incident_path,
                    initial_data=old_data,
                    existing_readings=self.all_readings,
                    exclude_index=orig_idx
                )
                if dialog.exec() == QDialog.Accepted:
                    new_data = dialog.get_data()
                    success, msg = self.db.edit_spot_reading(new_data, old_data, self.analyte_lookup)
                    if success:
                        # ✅ Refresh reference data in case a new device was auto-created
                        self._refresh_reference_data()
                        self.all_readings = self.db.get_spot_readings()
                        self._populate_filter()
                        self._update_table()
                        QMessageBox.information(self, "Updated", "Reading updated.")
                    else:
                        QMessageBox.warning(self, "Constraint Violation", msg)
        else:
            QMessageBox.information(self, "No Selection", "Please select a row in the table to edit.")

    def _on_remove(self):
        selected_row = self.table.currentRow()
        if selected_row >= 0:
            item = self.table.item(selected_row, 0)
            orig_idx = item.data(Qt.UserRole)
            if orig_idx is not None and 0 <= orig_idx < len(self.all_readings):
                r_data = self.all_readings[orig_idx]
                reply = QMessageBox.question(
                    self, "Confirm Deletion",
                    f"Are you sure you want to remove the reading at {r_data.get('location')} ({r_data.get('logtime')})?",
                    QMessageBox.Yes | QMessageBox.No, QMessageBox.No
                )
                if reply == QMessageBox.Yes:
                    self.db.delete_spot_reading(r_data)
                    self.all_readings = self.db.get_spot_readings()
                    self._update_table()
        else:
            QMessageBox.information(self, "No Selection", "Please select a row in the table to remove.")
