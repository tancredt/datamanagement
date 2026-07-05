import os
import json
import logging
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QComboBox,
    QTableWidget, QTableWidgetItem, QPushButton, QDialogButtonBox,
    QLabel, QMessageBox, QHeaderView, QFormLayout, QDateTimeEdit, QLineEdit,
    QStyle
)
from PySide6.QtCore import Qt, QDateTime, QSize

logger = logging.getLogger(__name__)
DATE_FORMAT = "yyyy-MM-dd HH:mm:ss"

class AddSpectralRecordDialog(QDialog):
    """Dialog to input details for a spectral record event."""
    def __init__(self, parent=None, available_labels=None, initial_data=None, existing_readings=None, exclude_index=None, spectral_json_path=None):
        super().__init__(parent)
        self.available_labels = available_labels or []
        self.initial_data = initial_data
        self.existing_readings = existing_readings or []
        self.exclude_index = exclude_index
        self.spectral_json_path = spectral_json_path

        self.setWindowTitle("Edit Spectral Record" if initial_data else "Add Spectral Record")
        self.setMinimumWidth(450)
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(10)
        layout.setContentsMargins(16, 16, 16, 16)
        
        form = QFormLayout()
        form.setSpacing(8)
        form.setLabelAlignment(Qt.AlignRight)

        # Location
        self.cmb_location = QComboBox()
        self.cmb_location.setMinimumHeight(28)
        self.cmb_location.setEditable(False)
        self.cmb_location.addItems(self.available_labels if self.available_labels else [])
        self.cmb_location.setPlaceholderText("Select location...")
        form.addRow("Location *:", self.cmb_location)

        # Device
        self.cmb_device = QComboBox()
        self.cmb_device.setEditable(True)
        self.cmb_device.setMinimumHeight(28)
        self.cmb_device.setPlaceholderText("Optional device label...")
        devices = self._load_available_devices()
        self.cmb_device.addItems(devices)
        form.addRow("Device:", self.cmb_device)

        # Log Time
        self.dt_logtime = QDateTimeEdit()
        self.dt_logtime.setCalendarPopup(True)
        self.dt_logtime.setDateTime(QDateTime.currentDateTime())
        self.dt_logtime.setDisplayFormat(DATE_FORMAT)
        self.dt_logtime.setMinimumHeight(28)
        form.addRow("Log Time *:", self.dt_logtime)

        # Chemicals Identified (Compulsory)
        self.le_chemicals = QLineEdit()
        self.le_chemicals.setPlaceholderText("Compulsory: Chemicals identified...")
        self.le_chemicals.setMinimumHeight(28)
        form.addRow("Chemicals Identified *:", self.le_chemicals)

        # Comments (Optional)
        self.le_comments = QLineEdit()
        self.le_comments.setPlaceholderText("Optional comments...")
        self.le_comments.setMinimumHeight(28)
        form.addRow("Comments:", self.le_comments)

        # File Ref (Optional)
        self.le_file_ref = QLineEdit()
        self.le_file_ref.setPlaceholderText("Optional file reference...")
        self.le_file_ref.setMinimumHeight(28)
        form.addRow("File Ref:", self.le_file_ref)

        layout.addLayout(form)

        # Pre-fill if editing an existing record
        if self.initial_data:
            self.cmb_location.setCurrentText(self.initial_data.get("location", ""))
            self.cmb_device.setCurrentText(self.initial_data.get("device", ""))
            dt = QDateTime.fromString(self.initial_data.get("logtime", ""), DATE_FORMAT)
            if dt.isValid():
                self.dt_logtime.setDateTime(dt)
            self.le_chemicals.setText(self.initial_data.get("chemicals_identified", ""))
            self.le_comments.setText(self.initial_data.get("comments", ""))
            self.le_file_ref.setText(self.initial_data.get("file_ref", ""))

        layout.addSpacing(10)
        btn_box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        btn_box.setMinimumHeight(34)
        layout.addWidget(btn_box)
        btn_box.rejected.connect(self.reject)
        
        ok_button = btn_box.button(QDialogButtonBox.Ok)
        ok_button.clicked.connect(self._validate_and_accept)

    def _load_available_devices(self):
        """Loads unique device labels from the spectral JSON file."""
        devices = set()
        if self.spectral_json_path and os.path.exists(self.spectral_json_path):
            try:
                with open(self.spectral_json_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                locations_list = data.get("maps", {}).get("locations", [])
                for loc in locations_list:
                    for marker in loc.get("markers", []):
                        for r in marker.get("readings", []):
                            device = r.get("device")
                            if device and str(device).strip():
                                devices.add(str(device).strip())
            except Exception as e:
                logger.warning(f"Failed to load devices: {e}")
        return sorted(list(devices))

    def _validate_and_accept(self):
        location = self.cmb_location.currentText().strip()
        if not location:
            QMessageBox.warning(self, "Validation Error", "Location is mandatory.")
            self.cmb_location.setFocus()
            return

        chemicals = self.le_chemicals.text().strip()
        if not chemicals:
            QMessageBox.warning(self, "Validation Error", "Chemicals Identified is mandatory.")
            self.le_chemicals.setFocus()
            return

        self.accept()

    def get_data(self):
        """Returns a dictionary representing the spectral record."""
        return {
            "location": self.cmb_location.currentText().strip(),
            "device": self.cmb_device.currentText().strip(),
            "logtime": self.dt_logtime.dateTime().toString(DATE_FORMAT),
            "chemicals_identified": self.le_chemicals.text().strip(),
            "comments": self.le_comments.text().strip(),
            "file_ref": self.le_file_ref.text().strip()
        }

class SpectralResultsDialog(QDialog):
    def __init__(self, parent=None, incident_path=None):
        super().__init__(parent)
        self.incident_path = incident_path
        
        # UPDATED: Save directly to the standard mapping directory
        self.mapping_dir = os.path.join(incident_path, "mapping")
        self.spectral_json_path = os.path.join(self.mapping_dir, "spectral_locations.json")

        self.all_readings = []
        self.map_data = {"maps": {"locations": []}}
        self.available_labels = []

        self.setWindowTitle("Spectral Results Manager")
        self.resize(900, 500)
        self._load_data()
        self._setup_ui()
        self._connect_signals()
        self._populate_filter()
        self._update_table()

    def _load_data(self):
        self.all_readings = []
        if os.path.exists(self.spectral_json_path):
            try:
                with open(self.spectral_json_path, 'r', encoding='utf-8') as f:
                    self.map_data = json.load(f)
            except Exception as e:
                logger.error(f"Failed to load spectral locations: {e}")
                self.map_data = {"maps": {"locations": []}}

        labels = set()
        locations_list = self.map_data.get("maps", {}).get("locations", [])
        for loc in locations_list:
            for marker in loc.get("markers", []):
                label = marker.get("label", "")
                if label:
                    labels.add(label)
                for r in marker.get("readings", []):
                    # Clean keys to prevent trailing space issues
                    clean_r = {k.strip(): v for k, v in r.items()}
                    row_data = {
                        "location": label,
                        "device": clean_r.get("device", ""),
                        "logtime": clean_r.get("datetime", ""),
                        "chemicals_identified": clean_r.get("chemicals_identified", ""),
                        "comments": clean_r.get("comments", ""),
                        "file_ref": clean_r.get("file_ref", "")
                    }
                    self.all_readings.append(row_data)

        self.available_labels = sorted(list(labels))

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(12)
        layout.setContentsMargins(16, 16, 16, 16)

        ctrl_row = QHBoxLayout()
        ctrl_row.addWidget(QLabel("Filter by Location:"))
        self.cmb_filter = QComboBox()
        self.cmb_filter.setMinimumWidth(150)
        ctrl_row.addWidget(self.cmb_filter)
        ctrl_row.addStretch()
        layout.addLayout(ctrl_row)

        self.table = QTableWidget()
        headers = ["Location", "Device", "Log Time", "Chemicals Identified", "Comments", "File Ref"]
        self.table.setColumnCount(len(headers))
        self.table.setHorizontalHeaderLabels(headers)
        
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(3, QHeaderView.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(4, QHeaderView.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(5, QHeaderView.ResizeToContents)
            
        self.table.setAlternatingRowColors(True)
        self.table.setStyleSheet("QTableWidget { font-size: 12px; }")
        layout.addWidget(self.table)

        btn_row = QHBoxLayout()
        self.btn_add = QPushButton("Add Record...")
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
        self.btn_box.accepted.connect(self._on_save_and_accept)
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
        filter_val = self.cmb_filter.currentText()
        rows_data = []
        for i, r_data in enumerate(self.all_readings):
            if filter_val == "All" or r_data.get("location") == filter_val:
                rows_data.append((i, r_data))

        self.table.setRowCount(len(rows_data))
        for i, (orig_idx, r_data) in enumerate(rows_data):
            item = QTableWidgetItem(r_data.get("location", ""))
            item.setData(Qt.UserRole, orig_idx)
            self.table.setItem(i, 0, item)
            self.table.setItem(i, 1, QTableWidgetItem(r_data.get("device", "")))
            self.table.setItem(i, 2, QTableWidgetItem(r_data.get("logtime", "")))
            self.table.setItem(i, 3, QTableWidgetItem(r_data.get("chemicals_identified", "")))
            self.table.setItem(i, 4, QTableWidgetItem(r_data.get("comments", "")))
            self.table.setItem(i, 5, QTableWidgetItem(r_data.get("file_ref", "")))

        self.table.resizeRowsToContents()
        self._update_button_states()

    def _on_add(self):
        dialog = AddSpectralRecordDialog(self, self.available_labels, existing_readings=self.all_readings, spectral_json_path=self.spectral_json_path)
        if dialog.exec() == QDialog.Accepted:
            data = dialog.get_data()
            self.all_readings.append(data)
            self._update_table()
            QMessageBox.information(self, "Added", "Record added.")

    def _on_edit(self):
        selected_row = self.table.currentRow()
        if selected_row >= 0:
            item = self.table.item(selected_row, 0)
            orig_idx = item.data(Qt.UserRole)
            if orig_idx is not None and 0 <= orig_idx < len(self.all_readings):
                old_data = self.all_readings[orig_idx]
                dialog = AddSpectralRecordDialog(
                    self, self.available_labels,
                    initial_data=old_data,
                    existing_readings=self.all_readings,
                    exclude_index=orig_idx,
                    spectral_json_path=self.spectral_json_path
                )
                if dialog.exec() == QDialog.Accepted:
                    new_data = dialog.get_data()
                    self.all_readings[orig_idx] = new_data
                    self._update_table()
                    QMessageBox.information(self, "Updated", "Record updated.")
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
                    f"Are you sure you want to remove the record at {r_data.get('location')} ({r_data.get('logtime')})?",
                    QMessageBox.Yes | QMessageBox.No, QMessageBox.No
                )
                if reply == QMessageBox.Yes:
                    self.all_readings.pop(orig_idx)
                    self._update_table()
        else:
            QMessageBox.information(self, "No Selection", "Please select a row in the table to remove.")

    def _on_save_and_accept(self):
        self._save_data()
        self.accept()

    def _save_data(self):
        """Reconstructs the nested JSON structure and saves it to the mapping directory."""
        try:
            os.makedirs(self.mapping_dir, exist_ok=True)
            locations_list = self.map_data.get("maps", {}).get("locations", [])
            
            for loc in locations_list:
                for marker in loc.get("markers", []):
                    marker["readings"] = []

            for loc in locations_list:
                for marker in loc.get("markers", []):
                    label = marker.get("label", "")
                    for r in self.all_readings:
                        if r["location"] == label:
                            reading_dict = {
                                "datetime": r["logtime"],
                                "device": r["device"],
                                "chemicals_identified": r.get("chemicals_identified", ""),
                                "comments": r.get("comments", ""),
                                "file_ref": r.get("file_ref", "")
                            }
                            marker["readings"].append(reading_dict)

            with open(self.spectral_json_path, 'w', encoding='utf-8') as f:
                json.dump(self.map_data, f, indent=2)
            logger.info("✅ Saved spectral records to spectral_locations.json")
        except Exception as e:
            QMessageBox.critical(self, "Save Error", f"Failed to save spectral records:\n{e}")

    def reject(self):
        super().reject()
