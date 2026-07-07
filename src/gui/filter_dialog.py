import os
import sys
import json
import shutil
import logging
from datetime import datetime
import pandas as pd
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QGroupBox, QComboBox,
    QPushButton, QLabel, QMessageBox, QDateTimeEdit, QWidget,
    QScrollArea, QCheckBox, QFrame, QHeaderView, QTableWidget,
    QTableWidgetItem, QDialogButtonBox
)
from PySide6.QtCore import Qt, QDateTime

# Import shared metadata helpers
from datamanagement.choices import get_available_devices, get_available_locations

current_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.dirname(current_dir)
if parent_dir not in sys.path:
    sys.path.insert(0, parent_dir)

logger = logging.getLogger(__name__)

DATE_FORMAT = "yyyy-MM-dd HH:mm "
INTERVAL_OPTIONS = ["Raw", "5", "15", "30", "60", "120", "240", "480", "1440"]

class FilterGroup(QGroupBox):
    def __init__(self, title, parent=None):
        super().__init__(f"{title}:", parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 15, 8, 8)
        layout.setSpacing(5)

        self.toggle_btn = QPushButton("Check All")
        self.toggle_btn.setFixedHeight(24)
        self.toggle_btn.clicked.connect(self._toggle_all)
        layout.addWidget(self.toggle_btn)

        self.scroll = QScrollArea()
        self.scroll.setFrameShape(QFrame.NoFrame)
        self.scroll.setWidgetResizable(True)
        self.scroll.setMaximumHeight(150)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)

        self.container = QWidget()
        self.container_layout = QVBoxLayout(self.container)
        self.container_layout.setContentsMargins(0, 0, 0, 0)
        self.container_layout.setSpacing(2)
        self.scroll.setWidget(self.container)
        layout.addWidget(self.scroll)
        layout.addStretch()

        self.checkboxes = []

    def add_checkbox(self, text, checked=True):
        cb = QCheckBox(text)
        cb.setChecked(checked)
        cb.stateChanged.connect(self._update_toggle_button)
        self.container_layout.addWidget(cb)
        self.checkboxes.append(cb)
        self._update_toggle_button()

    def set_checked_items(self, items):
        items_set = set(items)
        for cb in self.checkboxes:
            cb.setChecked(cb.text() in items_set)
        self._update_toggle_button()

    def _toggle_all(self):
        all_checked = len(self.checkboxes) > 0 and all(cb.isChecked() for cb in self.checkboxes)
        new_state = not all_checked
        for cb in self.checkboxes:
            cb.setChecked(new_state)
        self._update_toggle_button()

    def _update_toggle_button(self):
        all_checked = len(self.checkboxes) > 0 and all(cb.isChecked() for cb in self.checkboxes)
        self.toggle_btn.setText("Uncheck All" if all_checked else "Check All")

    def get_checked_items(self):
        return [cb.text() for cb in self.checkboxes if cb.isChecked()]

    def clear(self):
        for cb in self.checkboxes:
            self.container_layout.removeWidget(cb)
            cb.deleteLater()
        self.checkboxes.clear()
        self._update_toggle_button()

    def set_enabled(self, enabled):
        self.setEnabled(enabled)
        self.toggle_btn.setEnabled(enabled)
        for cb in self.checkboxes:
            cb.setEnabled(enabled)


class ThresholdsDialog(QDialog):
    def __init__(self, parent, incident_path):
        super().__init__(parent)
        self.incident_path = incident_path
        self.meta_dir = os.path.join(incident_path, "meta")
        self.thresholds_file = os.path.join(self.meta_dir, "thresholds.json")
        self.static_thresholds_file = os.path.normpath(os.path.join(current_dir, '..', 'static', 'lists', 'thresholds.json'))
        self.static_analytes_file = os.path.normpath(os.path.join(current_dir, '..', 'static', 'lists', 'analytes.json'))

        self.available_analytes = []
        self._load_available_analytes()
        self.thresholds_data = []
        self._load_thresholds()

        self.setWindowTitle("Manage Thresholds")
        self.resize(600, 400)
        self._setup_ui()
        self._populate_table()

    def _load_available_analytes(self):
        if os.path.exists(self.static_analytes_file):
            try:
                with open(self.static_analytes_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    analytes_list = data.get("analytes", [])
                    for g in analytes_list:
                        name = g.get("name")
                        if name:
                            self.available_analytes.append(name.strip())
            except Exception as e:
                logger.error(f"Failed to load analytes: {e}")

    def _load_thresholds(self):
        os.makedirs(self.meta_dir, exist_ok=True)
        if not os.path.exists(self.thresholds_file):
            if os.path.exists(self.static_thresholds_file):
                try:
                    shutil.copy(self.static_thresholds_file, self.thresholds_file)
                except Exception as e:
                    logger.error(f"Failed to copy thresholds: {e}")

        if os.path.exists(self.thresholds_file):
            try:
                with open(self.thresholds_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    thresholds_list = data.get("thresholds", [])
                    for t in thresholds_list:
                        clean_t = {k.strip(): str(v).strip() for k, v in t.items()}
                        self.thresholds_data.append(clean_t)
            except Exception as e:
                logger.error(f"Failed to load thresholds: {e}")

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        self.table = QTableWidget()
        self.table.setColumnCount(5)
        self.table.setHorizontalHeaderLabels(["Analyte", "Hotzone", "Warmzone", "Fireground", "Community"])
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

        btn_box = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Close)
        btn_box.accepted.connect(self._on_save)
        btn_box.rejected.connect(self.reject)
        layout.addWidget(btn_box)

    def _populate_table(self):
        self.table.setRowCount(len(self.thresholds_data))
        for row, t in enumerate(self.thresholds_data):
            analyte_item = QTableWidgetItem(t.get("analyte", ""))
            analyte_item.setFlags(analyte_item.flags() & ~Qt.ItemIsEditable)
            self.table.setItem(row, 0, analyte_item)

            for col, key in enumerate(["hotzone_value", "warmzone_value", "fireground_value", "community_value"], start=1):
                val = t.get(key, "")
                self.table.setItem(row, col, QTableWidgetItem(str(val)))

    def _on_add(self):
        analyte = self.cmb_add_analyte.currentText().strip()
        if not analyte: return
        for t in self.thresholds_data:
            if t.get("analyte", "").strip().upper() == analyte.upper():
                QMessageBox.warning(self, "Duplicate", "Threshold for this analyte already exists.")
                return
        self.thresholds_data.append({
            "analyte": analyte, "hotzone_value": "0.0",
            "warmzone_value": "0.0", "fireground_value": "0.0", "community_value": "0.0"
        })
        self._populate_table()

    def _on_remove(self):
        row = self.table.currentRow()
        if row >= 0:
            self.thresholds_data.pop(row)
            self._populate_table()

    def _on_save(self):
        for row in range(self.table.rowCount()):
            analyte_item = self.table.item(row, 0)
            if not analyte_item: continue
            analyte = analyte_item.text()
            t = next((x for x in self.thresholds_data if x.get("analyte") == analyte), None)
            if not t:
                t = {"analyte": analyte}
                self.thresholds_data.append(t)
            for col, key in enumerate(["hotzone_value", "warmzone_value", "fireground_value", "community_value"], start=1):
                item = self.table.item(row, col)
                t[key] = item.text() if item else ""

        try:
            with open(self.thresholds_file, 'w', encoding='utf-8') as f:
                json.dump({"thresholds": self.thresholds_data}, f, indent=1)
            QMessageBox.information(self, "Saved", "Thresholds saved successfully.")
            self.accept()
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to save thresholds:\n{e}")


class FilterDialog(QDialog):
    def __init__(self, parent=None, incident_path=None, raw_data=None,
                 analyte_dec_pls=None, thresholds_lookup=None,
                 initial_filters=None, data_type="spot"):
        super().__init__(parent)
        self.incident_path = incident_path
        self.raw_data = raw_data
        self.data_type = data_type
        self.analyte_dec_pls = analyte_dec_pls or {}
        self.thresholds_lookup = thresholds_lookup or {}
        self.initial_filters = initial_filters or {}
        self._selected_threshold_level = None

        # Load thresholds from the incident's meta directory
        self._reload_thresholds()

        # Handle Spectral metadata loading
        if self.data_type == "spectral":
            self.available_devices, self.available_locations = self._load_spectral_metadata()
        else:
            self.available_devices = get_available_devices(self.incident_path, self.data_type)
            self.available_locations = get_available_locations(self.incident_path, self.data_type)

        self.available_analytes = self._load_available_analytes()

        self.setWindowTitle("Data Filters")
        self.resize(900, 600)
        self._setup_ui()
        self._populate_filters()

    def _load_spectral_metadata(self):
        """Extracts unique devices and locations directly from spectral_locations.json."""
        devices = set()
        locations = set()
        spectral_file = os.path.join(self.incident_path, "mapping", "spectral_locations.json")
        if os.path.exists(spectral_file):
            try:
                with open(spectral_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                for loc in data.get("maps", {}).get("locations", []):
                    for marker in loc.get("markers", []):
                        label = marker.get("label", "")
                        if label: locations.add(label)
                        for r in marker.get("readings", []):
                            dev = r.get("device", "")
                            if dev: devices.add(dev)
            except Exception as e:
                logger.error(f"Failed to load spectral metadata: {e}")
        return sorted(list(devices)), sorted(list(locations))

    def _load_available_analytes(self):
        analytes = []
        analyte_config_path = os.path.normpath(os.path.join(current_dir, '..', 'static', 'lists', 'analytes.json'))
        if os.path.exists(analyte_config_path):
            try:
                with open(analyte_config_path, 'r', encoding='utf-8') as f:
                    analyte_config = json.load(f)
                    analytes_list = analyte_config.get("analytes", [])
                    for analyte in analytes_list:
                        clean_analyte = {k.strip(): str(v).strip() for k, v in analyte.items()}
                        name = clean_analyte.get("name")
                        if name:
                            analytes.append(name)
            except Exception as e:
                logger.error(f"Failed to load analytes: {e}")
        return sorted(list(set(analytes)))

    def _setup_ui(self):
        layout = QVBoxLayout(self)

        top_row = QHBoxLayout()
        top_row.addWidget(QLabel("<b>Group By:</b>"))
        self.group_by_combo = QComboBox()
        self.group_by_combo.addItems(["Device", "Site"])
        self.group_by_combo.setCurrentText("Device")
        self.group_by_combo.setMinimumWidth(120)
        self.group_by_combo.currentTextChanged.connect(self._on_group_by_changed)
        top_row.addWidget(self.group_by_combo)
        top_row.addStretch()

        top_row.addWidget(QLabel("<b>Active Threshold:</b>"))
        self.threshold_combo = QComboBox()
        self.threshold_combo.addItems(["No Threshold", "Hotzone", "Warmzone", "Fireground", "Community"])
        self.threshold_combo.setCurrentText("No Threshold")
        self.threshold_combo.setMinimumWidth(140)
        
        self.btn_thresholds = QPushButton("Thresholds...")
        self.btn_thresholds.clicked.connect(self._on_open_thresholds)

        top_row.addWidget(self.threshold_combo)
        top_row.addWidget(self.btn_thresholds)
        layout.addLayout(top_row)

        time_interval_row = QHBoxLayout()
        time_interval_row.addWidget(QLabel("Start Time:"))
        self.start_time_edit = QDateTimeEdit()
        self.start_time_edit.setCalendarPopup(True)
        self.start_time_edit.setDisplayFormat(DATE_FORMAT)
        time_interval_row.addWidget(self.start_time_edit)

        time_interval_row.addWidget(QLabel("Stop Time:"))
        self.stop_time_edit = QDateTimeEdit()
        self.stop_time_edit.setCalendarPopup(True)
        self.stop_time_edit.setDisplayFormat(DATE_FORMAT)
        time_interval_row.addWidget(self.stop_time_edit)

        time_interval_row.addWidget(QLabel("Interval:"))
        self.interval_combo = QComboBox()
        self.interval_combo.addItems(INTERVAL_OPTIONS)
        self.interval_combo.setCurrentText("Raw")
        time_interval_row.addWidget(self.interval_combo)

        self.only_valid_cb = QCheckBox("Only Valid")
        time_interval_row.addWidget(self.only_valid_cb)
        time_interval_row.addStretch()
        layout.addLayout(time_interval_row)

        filters_row = QHBoxLayout()
        self.site_group = FilterGroup("Sites")
        filters_row.addWidget(self.site_group)

        self.device_group = FilterGroup("Devices")
        filters_row.addWidget(self.device_group)

        self.analyte_group = FilterGroup("Analytes")
        filters_row.addWidget(self.analyte_group)
        layout.addLayout(filters_row)

        btn_row = QHBoxLayout()
        btn_row.addStretch()
        self.btn_apply = QPushButton("Apply Filters")
        self.btn_apply.setMinimumHeight(32)
        self.btn_apply.setMinimumWidth(120)
        self.btn_apply.clicked.connect(self._apply_filters)
        btn_row.addWidget(self.btn_apply)

        self.btn_cancel = QPushButton("Cancel")
        self.btn_cancel.setMinimumHeight(32)
        self.btn_cancel.clicked.connect(self.reject)
        btn_row.addWidget(self.btn_cancel)
        layout.addLayout(btn_row)

        # UPDATED: Disable everything except Start/Stop times and Dialog buttons for Spectral
        if self.data_type == "spectral":
            self.group_by_combo.setEnabled(False)
            # Enable threshold selection for spectral data
            self.threshold_combo.setEnabled(True)
            self.btn_thresholds.setEnabled(True)
            self.interval_combo.setEnabled(False)
            self.only_valid_cb.setEnabled(False)
            self.site_group.set_enabled(False)
            self.device_group.set_enabled(False)
            self.analyte_group.setVisible(False)
            self.analyte_group.setEnabled(False)
        # NEW: Disable "Only Valid" for Spot Readings
        elif self.data_type == "spot":
            self.only_valid_cb.setEnabled(False)
            self.only_valid_cb.setChecked(False)

    def _on_group_by_changed(self, group_by_text):
        if group_by_text == "Device":
            self.site_group.set_enabled(False)
            self.device_group.set_enabled(True)
        elif group_by_text == "Site":
            self.site_group.set_enabled(True)
            self.device_group.set_enabled(False)

    def _populate_filters(self):
        self._set_time_range()

        self.site_group.clear()
        self.site_group.add_checkbox("Unassigned", checked=True)
        for loc in self.available_locations:
            self.site_group.add_checkbox(loc, checked=True)

        self.device_group.clear()
        for device in self.available_devices:
            self.device_group.add_checkbox(device, checked=True)

        self.analyte_group.clear()
        if self.data_type != "spectral":
            for analyte in self.available_analytes:
                self.analyte_group.add_checkbox(analyte, checked=True)

        # Apply initial filters if provided
        if self.initial_filters:
            start = self.initial_filters.get('start_time')
            if start:
                if isinstance(start, datetime):
                    self.start_time_edit.setDateTime(QDateTime(start))
                elif isinstance(start, str) and start != "All":
                    dt = QDateTime.fromString(start, DATE_FORMAT)
                    if dt.isValid(): self.start_time_edit.setDateTime(dt)
                    
            stop = self.initial_filters.get('stop_time')
            if stop:
                if isinstance(stop, datetime):
                    self.stop_time_edit.setDateTime(QDateTime(stop))
                elif isinstance(stop, str) and stop != "All":
                    dt = QDateTime.fromString(stop, DATE_FORMAT)
                    if dt.isValid(): self.stop_time_edit.setDateTime(dt)

            interval = self.initial_filters.get('interval')
            if interval is not None: self.interval_combo.setCurrentText(str(interval))

            group_by = self.initial_filters.get('group_by')
            if group_by:
                self.group_by_combo.setCurrentText(group_by)
                self._on_group_by_changed(group_by)

            self.only_valid_cb.setChecked(self.initial_filters.get('only_valid', False))

            threshold = self.initial_filters.get('threshold_level')
            if threshold:
                level_map = {"hotzone_value": "Hotzone", "warmzone_value": "Warmzone", "fireground_value": "Fireground", "community_value": "Community"}
                self.threshold_combo.setCurrentText(level_map.get(threshold, "No Threshold"))

            if 'selected_sites' in self.initial_filters:
                self.site_group.set_checked_items(self.initial_filters['selected_sites'])
            if 'selected_devices' in self.initial_filters:
                self.device_group.set_checked_items(self.initial_filters['selected_devices'])
            if 'selected_analytes' in self.initial_filters and self.data_type != "spectral":
                self.analyte_group.set_checked_items(self.initial_filters['selected_analytes'])

    def _set_time_range(self):
        now_py = pd.Timestamp.now().to_pydatetime().replace(second=0, microsecond=0)
        now = QDateTime(now_py)
        self.start_time_edit.setDateTime(now.addDays(-1))
        self.stop_time_edit.setDateTime(now)

    def _on_open_thresholds(self):
        dialog = ThresholdsDialog(self, self.incident_path)
        if dialog.exec() == QDialog.Accepted:
            self._reload_thresholds()

    def _reload_thresholds(self):
        thresholds_file = os.path.join(self.incident_path, "meta", "thresholds.json")
        self.thresholds_lookup = {}
        if os.path.exists(thresholds_file):
            try:
                with open(thresholds_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    thresholds_list = data.get("thresholds", [])
                    for t in thresholds_list:
                        clean = {k.strip(): v for k, v in t.items()}
                        analyte_name = str(clean.get("analyte")).strip()
                        if analyte_name:
                            entry = {}
                            for key in ["hotzone_value", "warmzone_value", "fireground_value", "community_value"]:
                                raw = clean.get(key, "0")
                                try: entry[key] = float(str(raw).strip())
                                except (ValueError, TypeError): entry[key] = 0.0
                            # Store with uppercase key for case-insensitive lookup
                            self.thresholds_lookup[analyte_name.upper()] = entry
            except Exception as e:
                logger.error(f"Failed to load thresholds: {e}")

    def _apply_filters(self):
        start_dt = self.start_time_edit.dateTime().toPython().replace(second=0, microsecond=0)
        stop_dt = self.stop_time_edit.dateTime().toPython().replace(second=0, microsecond=0)
        if start_dt >= stop_dt:
            QMessageBox.warning(self, "Invalid Time Range", "The start time must be strictly before the stop time.")
            return

        level_map = {"No Threshold": None, "Hotzone": "hotzone_value", "Warmzone": "warmzone_value", "Fireground": "fireground_value", "Community": "community_value"}
        self._selected_threshold_level = level_map.get(self.threshold_combo.currentText())
        self.accept()

    def get_filters(self):
        # If disabled (like in Spectral mode), default to selecting ALL available items
        if self.site_group.isEnabled():
            selected_sites = self.site_group.get_checked_items()
        else:
            selected_sites = ["Unassigned"] + list(self.available_locations)

        if self.device_group.isEnabled():
            selected_devices = self.device_group.get_checked_items()
        else:
            selected_devices = list(self.available_devices)

        if self.data_type == "spectral":
            selected_analytes = []
        else:
            selected_analytes = self.analyte_group.get_checked_items()

        return {
            "start_time": self.start_time_edit.dateTime().toPython(),
            "stop_time": self.stop_time_edit.dateTime().toPython(),
            "interval": self.interval_combo.currentText(),
            "group_by": self.group_by_combo.currentText(),
            "only_valid": self.only_valid_cb.isChecked(),
            "selected_sites": selected_sites,
            "selected_devices": selected_devices,
            "selected_analytes": selected_analytes,
            "threshold_level": self._selected_threshold_level
        }
