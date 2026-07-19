"""Filter dialog for data analysis with time, site, device, and analyte filtering."""
import os
import sys
import json
import logging
from datetime import datetime
import pandas as pd
from PySide6.QtWidgets import (  # pylint: disable=no-name-in-module
    QDialog, QVBoxLayout, QHBoxLayout, QGroupBox, QComboBox,
    QPushButton, QLabel, QMessageBox, QDateTimeEdit, QWidget,
    QScrollArea, QCheckBox, QFrame, QHeaderView, QTableWidget,
    QTableWidgetItem, QDialogButtonBox
)
from PySide6.QtCore import Qt, QDateTime  # pylint: disable=no-name-in-module

# Import shared metadata helpers
from datamanagement.choices import (  # pylint: disable=import-error
    get_available_devices, get_available_locations
)

current_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.dirname(current_dir)
if parent_dir not in sys.path:
    sys.path.insert(0, parent_dir)

logger = logging.getLogger(__name__)

DATE_FORMAT = "yyyy-MM-dd HH:mm"
INTERVAL_OPTIONS = [
    "Raw", "5", "15", "30", "60", "120", "240", "480", "1440"
]


class FilterGroup(QGroupBox):
    """A group box containing checkboxes for filtering."""

    def __init__(self, title, parent=None):
        """Initialize the filter group with a title."""
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
        """Add a checkbox to the group."""
        cb = QCheckBox(text)
        cb.setChecked(checked)
        cb.stateChanged.connect(self._update_toggle_button)
        self.container_layout.addWidget(cb)
        self.checkboxes.append(cb)
        self._update_toggle_button()

    def set_checked_items(self, items):
        """Set which items are checked."""
        items_set = set(items)
        for cb in self.checkboxes:
            cb.setChecked(cb.text() in items_set)
        self._update_toggle_button()

    def _toggle_all(self):
        """Toggle all checkboxes on or off."""
        all_checked = (
            len(self.checkboxes) > 0
            and all(cb.isChecked() for cb in self.checkboxes)
        )
        new_state = not all_checked
        for cb in self.checkboxes:
            cb.setChecked(new_state)
        self._update_toggle_button()

    def _update_toggle_button(self):
        """Update the toggle button text based on checkbox states."""
        all_checked = (
            len(self.checkboxes) > 0
            and all(cb.isChecked() for cb in self.checkboxes)
        )
        self.toggle_btn.setText(
            "Uncheck All" if all_checked else "Check All"
        )

    def get_checked_items(self):
        """Get list of checked item texts."""
        return [cb.text() for cb in self.checkboxes if cb.isChecked()]

    def clear(self):
        """Remove all checkboxes."""
        for cb in self.checkboxes:
            self.container_layout.removeWidget(cb)
            cb.deleteLater()
        self.checkboxes.clear()
        self._update_toggle_button()

    def set_enabled(self, enabled):
        """Enable or disable the group and all checkboxes."""
        self.setEnabled(enabled)
        self.toggle_btn.setEnabled(enabled)
        for cb in self.checkboxes:
            cb.setEnabled(enabled)


class FilterDialog(QDialog):
    """Main dialog for filtering data by time, site, device, and analyte."""
    def __init__(  # pylint: disable=too-many-arguments,too-many-positional-arguments
        self, parent=None, incident_path=None, raw_data=None,
        analyte_dec_pls=None, thresholds_lookup=None,
        initial_filters=None, data_type="spot", plume_data=None  # <--- ADD THIS
    ):
        """Initialize the filter dialog."""
        super().__init__(parent)
        self.incident_path = incident_path
        self.raw_data = raw_data
        self.data_type = data_type
        self.plume_data = plume_data or []  # <--- Now this will work perfectly
        self.analyte_dec_pls = analyte_dec_pls or {}
        self.thresholds_lookup = thresholds_lookup or {}
        self.initial_filters = initial_filters or {}
        self._selected_threshold_level = None

        self._reload_thresholds()

        if self.data_type == "spectral":
            self.available_devices, self.available_locations = (
                self._load_spectral_metadata()
            )
        elif self.data_type == "exposure":
            if self.raw_data is not None:
                if 'DEVICE' in self.raw_data.columns:
                    devs = self.raw_data['DEVICE'].dropna().unique().tolist()
                    self.available_devices = sorted(
                        [str(d) for d in devs if str(d).strip()]
                    )
                else:
                    self.available_devices = []

                if 'SITE' in self.raw_data.columns:
                    sites = self.raw_data['SITE'].dropna().unique().tolist()
                    self.available_locations = sorted(
                        [str(s) for s in sites if str(s).strip()]
                    )
                else:
                    self.available_locations = []
            else:
                self.available_devices = []
                self.available_locations = []
        else:
            self.available_devices = get_available_devices(
                self.incident_path, self.data_type
            )
            self.available_locations = get_available_locations(
                self.incident_path, self.data_type
            )

        self.available_analytes = self._load_available_analytes()

        self.setWindowTitle("Data Filters")
        self.resize(900, 600)
        self._setup_ui()
        self._populate_filters()

    def _load_spectral_metadata(self):
        """Extract unique devices and locations from spectral_locations.json."""
        devices = set()
        locations = set()
        spectral_file = os.path.join(
            self.incident_path, "mapping", "spectral_locations.json"
        )
        if os.path.exists(spectral_file):
            try:
                with open(spectral_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                for loc in data.get("maps", {}).get("locations", []):
                    for marker in loc.get("markers", []):
                        label = marker.get("label", "")
                        if label:
                            locations.add(label)
                        for r in marker.get("readings", []):
                            dev = r.get("device", "")
                            if dev:
                                devices.add(dev)
            except (OSError, json.JSONDecodeError) as e:
                logger.error("Failed to load spectral metadata: %s", e)
        return sorted(list(devices)), sorted(list(locations))

    def _load_available_analytes(self):
        """Load available analytes from static config."""
        analytes = []
        analyte_config_path = os.path.normpath(
            os.path.join(current_dir, '..', 'static', 'lists', 'analytes.json')
        )
        if os.path.exists(analyte_config_path):
            try:
                with open(analyte_config_path, 'r', encoding='utf-8') as f:
                    analyte_config = json.load(f)
                    analytes_list = analyte_config.get("analytes", [])
                    for analyte in analytes_list:
                        clean_analyte = {
                            k.strip(): str(v).strip()
                            for k, v in analyte.items()
                        }
                        name = clean_analyte.get("name")
                        if name:
                            analytes.append(name)
            except (OSError, json.JSONDecodeError) as e:
                logger.error("Failed to load analytes: %s", e)
        return sorted(list(set(analytes)))

    def _setup_ui(self):
        """Set up the dialog UI."""
        layout = QVBoxLayout(self)

        top_row = QHBoxLayout()
        top_row.addWidget(QLabel("<b>Group By:</b>"))
        self.group_by_combo = QComboBox()
        self.group_by_combo.addItems(["Identifier", "Site"])
        self.group_by_combo.setCurrentText("Identifier")
        self.group_by_combo.setMinimumWidth(120)
        self.group_by_combo.currentTextChanged.connect(
            self._on_group_by_changed
        )
        top_row.addWidget(self.group_by_combo)
        top_row.addStretch()

        top_row.addWidget(QLabel("<b>Active Threshold:</b>"))
        self.threshold_combo = QComboBox()
        self.threshold_combo.addItems([
            "No Threshold", "Hotzone", "Warmzone", "Fireground", "Community"
        ])
        self.threshold_combo.setCurrentText("No Threshold")
        self.threshold_combo.setMinimumWidth(140)
        top_row.addWidget(self.threshold_combo)
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

        self.device_group = FilterGroup("Identifier")
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

        if self.data_type == "spectral":
            self.group_by_combo.setEnabled(False)
            self.threshold_combo.setEnabled(True)
            self.btn_thresholds.setEnabled(True)
            self.interval_combo.setEnabled(False)
            self.only_valid_cb.setEnabled(False)
            self.site_group.set_enabled(False)
            self.device_group.set_enabled(False)
            self.analyte_group.setVisible(False)
            self.analyte_group.setEnabled(False)
        elif self.data_type == "exposure":
            self.group_by_combo.setEnabled(True)
            self.group_by_combo.setCurrentText("Identifier")
            self.interval_combo.setEnabled(False)
            self.only_valid_cb.setEnabled(False)
            self.site_group.setVisible(True)
            self.site_group.setTitle("Areas:")
            self.device_group.setTitle("Identifiers:")
            self._on_group_by_changed("Identifier")
        elif self.data_type == "spot":
            self.only_valid_cb.setEnabled(False)
            self.only_valid_cb.setChecked(False)
        elif self.data_type == "plume":
            self.group_by_combo.setEnabled(False)
            self.threshold_combo.setEnabled(False)
            self.interval_combo.setEnabled(False)
            self.only_valid_cb.setEnabled(False)
            self.site_group.set_enabled(False)
            self.site_group.setVisible(False)  # Hide to save space
            self.device_group.set_enabled(False)
            self.device_group.setVisible(False)
            self.analyte_group.set_enabled(False)
            self.analyte_group.setVisible(False)

    def _on_group_by_changed(self, group_by_text):
        """Handle group by combo box change."""
        if group_by_text == "Identifier":
            self.site_group.set_enabled(False)
            self.device_group.set_enabled(True)
        elif group_by_text == "Site":
            self.site_group.set_enabled(True)
            self.device_group.set_enabled(False)

    # pylint: disable=too-many-branches,too-many-statements
    def _populate_filters(self):
        """Populate all filter controls with data."""
        self._set_time_range()

        self.device_group.clear()
        if self.data_type == "exposure":
            for id_val in self.available_devices:
                self.device_group.add_checkbox(id_val, checked=True)
        else:
            for device in self.available_devices:
                self.device_group.add_checkbox(device, checked=True)

        if self.data_type != "spectral":
            self.site_group.clear()
            if self.data_type == "exposure":
                for loc in self.available_locations:
                    self.site_group.add_checkbox(loc, checked=True)
            else:
                self.site_group.add_checkbox("Unassigned", checked=True)
                for loc in self.available_locations:
                    self.site_group.add_checkbox(loc, checked=True)

        if self.data_type != "spectral":
            self.analyte_group.clear()
            for analyte in self.available_analytes:
                self.analyte_group.add_checkbox(analyte, checked=True)

        if self.initial_filters:
            start = self.initial_filters.get('start_time')
            if start:
                if isinstance(start, datetime):
                    self.start_time_edit.setDateTime(QDateTime(start))
                elif isinstance(start, str) and start != "All":
                    dt = QDateTime.fromString(start, DATE_FORMAT)
                    if dt.isValid():
                        self.start_time_edit.setDateTime(dt)

            stop = self.initial_filters.get('stop_time')
            if stop:
                if isinstance(stop, datetime):
                    self.stop_time_edit.setDateTime(QDateTime(stop))
                elif isinstance(stop, str) and stop != "All":
                    dt = QDateTime.fromString(stop, DATE_FORMAT)
                    if dt.isValid():
                        self.stop_time_edit.setDateTime(dt)

            interval = self.initial_filters.get('interval')
            if interval is not None:
                self.interval_combo.setCurrentText(str(interval))

            group_by = self.initial_filters.get('group_by')
            if group_by:
                ui_group_by = (
                    "Identifier" if group_by == "Device" else group_by
                )
                self.group_by_combo.setCurrentText(ui_group_by)
                self._on_group_by_changed(ui_group_by)

            self.only_valid_cb.setChecked(
                self.initial_filters.get('only_valid', False)
            )

            threshold = self.initial_filters.get('threshold_level')
            if threshold:
                level_map = {
                    "hotzone_value": "Hotzone",
                    "warmzone_value": "Warmzone",
                    "fireground_value": "Fireground",
                    "community_value": "Community"
                }
                self.threshold_combo.setCurrentText(
                    level_map.get(threshold, "No Threshold")
                )

            if 'selected_devices' in self.initial_filters:
                self.device_group.set_checked_items(
                    self.initial_filters['selected_devices']
                )

            if (self.data_type != "spectral"
                    and 'selected_sites' in self.initial_filters):
                self.site_group.set_checked_items(
                    self.initial_filters['selected_sites']
                )

            if (self.data_type != "spectral"
                    and 'selected_analytes' in self.initial_filters):
                self.analyte_group.set_checked_items(
                    self.initial_filters['selected_analytes']
                )

    def _set_time_range(self):
        if self.data_type == "plume" and self.plume_data:
            times = [dt for dt, _ in self.plume_data]
            if times:
                start_py = min(times).replace(second=0, microsecond=0)
                stop_py = max(times).replace(second=0, microsecond=0)
                
                # QDateTime will correctly interpret naive datetime objects as LocalTime
                self.start_time_edit.setDateTime(QDateTime(start_py))
                self.stop_time_edit.setDateTime(QDateTime(stop_py))
                return
                
        # Default fallback (last 24 hours)
        now_py = pd.Timestamp.now().to_pydatetime().replace(second=0, microsecond=0)
        now = QDateTime(now_py)
        self.start_time_edit.setDateTime(now.addDays(-1))
        self.stop_time_edit.setDateTime(now)

    def _reload_thresholds(self):
        """Reload thresholds from the incident's meta directory."""
        thresholds_file = os.path.join(
            self.incident_path, "meta", "thresholds.json"
        )
        self.thresholds_lookup = {}
        if os.path.exists(thresholds_file):
            try:
                with open(thresholds_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    thresholds_list = data.get("thresholds", [])
                    for t in thresholds_list:
                        clean = {k.strip(): v for k, v in t.items()}
                        analyte_name = str(clean.get("analyte", "")).strip()
                        if analyte_name:
                            entry = {}
                            for key in [
                                "hotzone_value", "warmzone_value",
                                "fireground_value", "community_value"
                            ]:
                                raw = clean.get(key, "0")
                                try:
                                    entry[key] = float(str(raw).strip())
                                except (ValueError, TypeError):
                                    entry[key] = 0.0
                            self.thresholds_lookup[
                                analyte_name.upper()
                            ] = entry
            except (OSError, json.JSONDecodeError) as e:
                logger.error("Failed to load thresholds: %s", e)

    def _apply_filters(self):
        """Validate and apply the filters."""
        start_dt = self.start_time_edit.dateTime().toPython().replace(
            second=0, microsecond=0
        )
        stop_dt = self.stop_time_edit.dateTime().toPython().replace(
            second=0, microsecond=0
        )

        if start_dt >= stop_dt:
            QMessageBox.warning(
                self, "Invalid Time Range",
                "The start time must be strictly before the stop time."
            )
            return

        level_map = {
            "No Threshold": None,
            "Hotzone": "hotzone_value",
            "Warmzone": "warmzone_value",
            "Fireground": "fireground_value",
            "Community": "community_value"
        }
        self._selected_threshold_level = level_map.get(
            self.threshold_combo.currentText()
        )

        self.accept()

    def get_filters(self):
        """Get the current filter settings as a dictionary."""
        if self.site_group.isEnabled() and self.site_group.isVisible():
            selected_sites = self.site_group.get_checked_items()
        else:
            if self.data_type == "exposure":
                selected_sites = list(self.available_locations)
            else:
                selected_sites = (
                    ["Unassigned"] + list(self.available_locations)
                )

        if self.device_group.isEnabled():
            selected_devices = self.device_group.get_checked_items()
        else:
            selected_devices = list(self.available_devices)

        if self.data_type == "spectral":
            selected_analytes = []
        else:
            selected_analytes = self.analyte_group.get_checked_items()

        group_by_text = self.group_by_combo.currentText()
        if group_by_text == "Identifier":
            group_by_text = "Device"

        return {
            "start_time": self.start_time_edit.dateTime().toPython(),
            "stop_time": self.stop_time_edit.dateTime().toPython(),
            "interval": self.interval_combo.currentText(),
            "group_by": group_by_text,
            "only_valid": self.only_valid_cb.isChecked(),
            "selected_sites": selected_sites,
            "selected_devices": selected_devices,
            "selected_analytes": selected_analytes,
            "threshold_level": self._selected_threshold_level,
            "data_type": self.data_type
        }
