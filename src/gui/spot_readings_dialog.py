import os
import json
import logging
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QComboBox,
    QTableWidget, QTableWidgetItem, QPushButton, QDialogButtonBox,
    QLabel, QMessageBox, QHeaderView, QFormLayout, QDateTimeEdit, QLineEdit,
    QStyle, QScrollArea, QWidget
)
from PySide6.QtCore import Qt, QDateTime, QSize
from PySide6.QtGui import QDoubleValidator

logger = logging.getLogger(__name__)
DATE_FORMAT = "yyyy-MM-dd HH:mm:ss"

class AddSpotReadingDialog(QDialog):
    """Dialog to input details for a spot reading event (supports multiple analytes at once)."""
    def __init__(self, parent=None, available_labels=None, available_analytes=None, initial_data=None, existing_readings=None, exclude_index=None, spot_locations_json=None):
        super().__init__(parent)
        self.available_labels = available_labels or []
        self.available_analytes = available_analytes or []
        self.initial_data = initial_data
        self.existing_readings = existing_readings or []
        self.exclude_index = exclude_index
        self.spot_locations_json = spot_locations_json

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

        # Location
        self.cmb_location = QComboBox()
        self.cmb_location.setMinimumHeight(28)
        self.cmb_location.setEditable(False)
        self.cmb_location.addItems(self.available_labels if self.available_labels else [])
        self.cmb_location.setPlaceholderText("Select location...")
        form.addRow("Location *:", self.cmb_location)

        # Device (Label)
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

        # Observations Field
        self.le_observations = QLineEdit()
        self.le_observations.setPlaceholderText("Optional observations...")
        self.le_observations.setMinimumHeight(28)
        form.addRow("Observations:", self.le_observations)

        layout.addLayout(form)

        # Analytes Scroll Area
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

        # Pre-fill if editing an existing reading
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

    def _load_available_devices(self):
        """Loads unique device labels from the spot_locations.json file."""
        devices = set()
        if self.spot_locations_json and os.path.exists(self.spot_locations_json):
            try:
                with open(self.spot_locations_json, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                locations_list = data.get("maps", {}).get("locations", [])
                for loc in locations_list:
                    for marker in loc.get("markers", []):
                        for r in marker.get("readings", []):
                            device = r.get("device")
                            if device and str(device).strip():
                                devices.add(str(device).strip())
            except Exception as e:
                logger.warning(f"Failed to load devices from {self.spot_locations_json}: {e}")
        return sorted(list(devices))

    def _validate_and_accept(self):
        location = self.cmb_location.currentText().strip()
        if not location:
            QMessageBox.warning(self, "Validation Error", "Location is mandatory.")
            self.cmb_location.setFocus()
            return

        has_value = False
        for analyte, le in self.analyte_inputs.items():
            if le.text().strip():
                has_value = True
                break

        if not has_value:
            QMessageBox.warning(self, "Validation Error", "Please enter a value for at least one analyte.")
            return

        self.accept()

    def get_data(self):
        """Returns a single dictionary representing the reading event with all analytes."""
        data = {
            "location": self.cmb_location.currentText().strip(),
            "device": self.cmb_device.currentText().strip(),
            "logtime": self.dt_logtime.dateTime().toString(DATE_FORMAT),
            "observations": self.le_observations.text().strip()
        }
        for analyte, le in self.analyte_inputs.items():
            val_str = le.text().strip()
            if val_str:
                try:
                    data[analyte] = float(val_str)
                except ValueError:
                    pass
        return data

class SpotReadingsDialog(QDialog):
    def __init__(self, parent=None, incident_path=None):
        super().__init__(parent)
        self.incident_path = incident_path
        self.mapping_dir = os.path.join(incident_path, "mapping")
        self.spot_locations_json = os.path.join(self.mapping_dir, "spot_locations.json")

        self.all_readings = []
        self.map_data = {"maps": {"locations": []}}
        self.available_labels = []
        self.available_analytes = []

        self.setWindowTitle("Spot Readings Manager")
        self.resize(1000, 600)
        self._load_analytes()
        self._load_data()
        self._setup_ui()
        self._connect_signals()
        self._populate_filter()
        self._update_table()

    def _load_analytes(self):
        """Loads analyte names and decimal places strictly from the static analytes.json config."""
        current_dir = os.path.dirname(os.path.abspath(__file__))
        analyte_config_path = os.path.normpath(os.path.join(current_dir, '..', 'static', 'lists', 'analytes.json'))
        self.analyte_dec_pls = {} 
        
        if os.path.exists(analyte_config_path):
            try:
                with open(analyte_config_path, 'r', encoding='utf-8') as f:
                    analyte_config = json.load(f)
                    for analyte in analyte_config.get("analytes", []):
                        clean_analyte = {k.strip(): str(v).strip() for k, v in analyte.items()}
                        name = clean_analyte.get("name")
                        if name:
                            self.available_analytes.append(name)
                            dec_pls = clean_analyte.get("dec_pls", 2)
                            try:
                                self.analyte_dec_pls[name] = int(dec_pls)
                            except (ValueError, TypeError):
                                self.analyte_dec_pls[name] = 2
            except Exception as e:
                logger.error(f"Failed to load analytes config: {e}")

    def _load_data(self):
        """Loads the JSON file, preserves the map structure, and flattens readings for the UI table."""
        self.all_readings = []
        if os.path.exists(self.spot_locations_json):
            try:
                with open(self.spot_locations_json, 'r', encoding='utf-8') as f:
                    self.map_data = json.load(f)
            except Exception as e:
                logger.error(f"Failed to load spot locations: {e}")
                self.map_data = {"maps": {"locations": []}}

        labels = set()
        locations_list = self.map_data.get("maps", {}).get("locations", [])
        for loc in locations_list:
            for marker in loc.get("markers", []):
                label = marker.get("label", "")
                if label:
                    labels.add(label)
                for r in marker.get("readings", []):
                    # Clean keys to remove accidental trailing spaces from JSON
                    clean_r = {k.strip(): v for k, v in r.items()}
                    dt = clean_r.get("datetime", "")
                    device = clean_r.get("device", "")
                    row_data = {
                        "location": label,
                        "device": device,
                        "logtime": dt,
                        "observations": clean_r.get("observations", "")
                    }
                    for analyte in self.available_analytes:
                        row_data[analyte] = clean_r.get(analyte)
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
        headers = ["Location", "Device", "Log Time", "Observations"] + self.available_analytes
        self.table.setColumnCount(len(headers))
        self.table.setHorizontalHeaderLabels(headers)
        
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(3, QHeaderView.Stretch) # Observations column
        for i in range(4, len(headers)):
            self.table.horizontalHeader().setSectionResizeMode(i, QHeaderView.ResizeToContents)
            
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
            self.table.setItem(i, 3, QTableWidgetItem(r_data.get("observations", "")))
            
            for j, analyte in enumerate(self.available_analytes):
                val = r_data.get(analyte)
                if val is not None:
                    dec_pls = self.analyte_dec_pls.get(analyte, 2) 
                    val_str = f"{val:.{dec_pls}f}" if isinstance(val, (int, float)) else str(val)
                    self.table.setItem(i, 4 + j, QTableWidgetItem(val_str))
                else:
                    self.table.setItem(i, 4 + j, QTableWidgetItem(""))

        self.table.resizeRowsToContents()
        self._update_button_states()

    def _on_add(self):
        dialog = AddSpotReadingDialog(self, self.available_labels, self.available_analytes, existing_readings=self.all_readings, spot_locations_json=self.spot_locations_json)
        if dialog.exec() == QDialog.Accepted:
            data = dialog.get_data()
            self.all_readings.append(data)
            self._update_table()
            QMessageBox.information(self, "Added", "Reading added.")

    def _on_edit(self):
        selected_row = self.table.currentRow()
        if selected_row >= 0:
            item = self.table.item(selected_row, 0)
            orig_idx = item.data(Qt.UserRole)
            if orig_idx is not None and 0 <= orig_idx < len(self.all_readings):
                old_data = self.all_readings[orig_idx]
                dialog = AddSpotReadingDialog(
                    self, self.available_labels, self.available_analytes,
                    initial_data=old_data,
                    existing_readings=self.all_readings,
                    exclude_index=orig_idx,
                    spot_locations_json=self.spot_locations_json
                )
                if dialog.exec() == QDialog.Accepted:
                    new_data = dialog.get_data()
                    self.all_readings[orig_idx] = new_data
                    self._update_table()
                    QMessageBox.information(self, "Updated", "Reading updated.")
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
                    self.all_readings.pop(orig_idx)
                    self._update_table()
        else:
            QMessageBox.information(self, "No Selection", "Please select a row in the table to remove.")

    def _on_save_and_accept(self):
        self._save_data()
        self.accept()

    def _save_data(self):
        """Reconstructs the nested JSON structure from the flat UI table and saves it."""
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
                                "observations": r.get("observations", "")
                            }
                            for analyte in self.available_analytes:
                                if analyte in r and r[analyte] is not None:
                                    reading_dict[analyte] = r[analyte]
                            marker["readings"].append(reading_dict)

            with open(self.spot_locations_json, 'w', encoding='utf-8') as f:
                json.dump(self.map_data, f, indent=2)
            logger.info("✅ Saved spot readings to spot_locations.json")
        except Exception as e:
            QMessageBox.critical(self, "Save Error", f"Failed to save spot readings:\n{e}")

    def reject(self):
        super().reject()
