"""Filter dialog for data analysis with time, site, device, and analyte filtering."""
import os
import sys
import json
import logging
from datetime import datetime, timedelta

from PySide6.QtWidgets import (
    QDialog,
    QVBoxLayout,
    QHBoxLayout,
    QGroupBox,
    QComboBox,
    QPushButton,
    QLabel,
    QMessageBox,
    QDateTimeEdit,
    QWidget,
    QScrollArea,
    QCheckBox,
    QFrame,
)
from PySide6.QtCore import Qt, QDateTime

current_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.dirname(current_dir)
if parent_dir not in sys.path:
    sys.path.insert(0, parent_dir)

from datamanagement.db_manager import IncidentDatabase


logger = logging.getLogger(__name__)

DATE_FORMAT = "yyyy-MM-dd HH:mm"

INTERVAL_OPTIONS = [
    "Raw",
    "5",
    "15",
    "30",
    "60",
    "120",
    "240",
    "480",
    "1440",
]

# Mapping data types to their specific device/identifier keys in last_filters.json
DEVICE_KEY_MAP = {
    "area": "selected_area_devices",
    "spot": "selected_spot_devices",
    "spectral": "selected_spectral_devices",
    "exposure": "selected_exposure_identifiers",
}


class FilterGroup(QGroupBox):
    """A group box containing checkboxes for filtering."""

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
        all_checked = (
            len(self.checkboxes) > 0
            and all(cb.isChecked() for cb in self.checkboxes)
        )

        new_state = not all_checked

        for cb in self.checkboxes:
            cb.setChecked(new_state)

        self._update_toggle_button()

    def _update_toggle_button(self):
        all_checked = (
            len(self.checkboxes) > 0
            and all(cb.isChecked() for cb in self.checkboxes)
        )

        self.toggle_btn.setText(
            "Uncheck All" if all_checked else "Check All"
        )

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


class FilterDialog(QDialog):
    """Main dialog for filtering data by time, site, device, and analyte."""

    def __init__(
        self,
        parent=None,
        incident_path=None,
        data_type="spot",
        mode="view",          # "view" or "objective"
        initial_filters=None,
        plume_data=None,
        form=None,            # The form type (Table, Summary Map, etc.)
    ):
        super().__init__(parent)

        self.incident_path = incident_path
        self.data_type = str(data_type).strip().lower() if data_type else "spot"
        self.mode = mode
        self.plume_data = plume_data or []
        self.form = str(form).strip() if form else None

        # Determine initial filters based on mode
        if mode == "objective":
            self.initial_filters = initial_filters if initial_filters is not None else {}
        else:
            if initial_filters is not None:
                self.initial_filters = initial_filters
            else:
                self.initial_filters = self._load_last_filters_from_disk()

        # Initialize Database Connection
        self.db = IncidentDatabase(self.incident_path) if self.incident_path else None

        # Load metadata from Database
        self.analyte_dec_pls = self._load_analyte_dec_pls()
        self.thresholds_lookup = self._load_thresholds_lookup()

        if self.db:
            if self.data_type == "exposure":
                self.available_devices = self.db.get_exposure_ids()
            else:
                self.available_devices = self.db.get_devices(self.data_type)

            self.available_locations = self.db.get_markers()
        else:
            self.available_devices = []
            self.available_locations = []

        self.available_analytes = list(self.analyte_dec_pls.keys())

        self._selected_threshold_level = None

        # Build UI
        self.setWindowTitle("Data Filters")
        self.resize(900, 600)

        self._setup_ui()
        self._populate_filters()

    # ─────────────────────────────────────────────────────────
    # DISK I/O & DB LOADERS
    # ─────────────────────────────────────────────────────────
    def _load_last_filters_from_disk(self):
        """Loads the last-used filters from meta/last_filters.json."""
        if not self.incident_path:
            return {}

        filters_file = os.path.join(self.incident_path, "meta", "last_filters.json")

        if not os.path.exists(filters_file):
            return {}

        try:
            with open(filters_file, "r", encoding="utf-8") as f:
                raw = json.load(f)

            def clean(obj):
                if isinstance(obj, dict):
                    return {k.strip(): clean(v) for k, v in obj.items()}
                elif isinstance(obj, list):
                    return [clean(elem) for elem in obj]
                elif isinstance(obj, str):
                    return obj.strip()
                return obj

            raw = clean(raw)

            for key in ("start_time", "stop_time"):
                val = raw.get(key)

                if isinstance(val, str):
                    try:
                        raw[key] = datetime.fromisoformat(val)
                    except (ValueError, TypeError):
                        raw[key] = None

            return raw

        except Exception as e:
            logger.error(f"Failed to load last filters from disk: {e}")
            return {}

    def _load_analyte_dec_pls(self):
        """Load {analyte_name: decimal_places} from the database."""
        result = {}

        if not self.db:
            return result

        try:
            analytes = self.db.get_analytes()

            for a in analytes:
                result[a["label"]] = a["dec_pls"]

        except Exception as e:
            logger.error("Failed to load analytes from DB: %s", e)

        return result

    def _load_thresholds_lookup(self):
        """Load thresholds from meta/thresholds.json."""
        lookup = {}

        if not self.incident_path:
            return lookup

        thresholds_file = os.path.join(self.incident_path, "meta", "thresholds.json")

        if not os.path.exists(thresholds_file):
            return lookup

        try:
            with open(thresholds_file, "r", encoding="utf-8") as f:
                data = json.load(f)

            for t in data.get("thresholds", []):
                clean = {k.strip(): v for k, v in t.items()}

                analyte_name = str(clean.get("analyte", "")).strip()

                if not analyte_name:
                    continue

                entry = {}

                for key in (
                    "hotzone_value",
                    "warmzone_value",
                    "fireground_value",
                    "community_value",
                ):
                    raw = clean.get(key, "0")

                    try:
                        entry[key] = float(str(raw).strip())
                    except (ValueError, TypeError):
                        entry[key] = 0.0

                lookup[analyte_name.upper()] = entry

        except (OSError, json.JSONDecodeError) as e:
            logger.error("Failed to load thresholds: %s", e)

        return lookup

    # ─────────────────────────────────────────────────────────
    # UI SETUP
    # ─────────────────────────────────────────────────────────
    def _setup_ui(self):
        layout = QVBoxLayout(self)

        # Top row: Group By + Threshold + Stats Pref
        top_row = QHBoxLayout()

        top_row.addWidget(QLabel("<b>Group By:</b>"))

        self.group_by_combo = QComboBox()
        self.group_by_combo.addItems(["Identifier", "Site"])
        self.group_by_combo.setCurrentText("Identifier")
        self.group_by_combo.setMinimumWidth(120)
        self.group_by_combo.currentTextChanged.connect(self._on_group_by_changed)
        top_row.addWidget(self.group_by_combo)

        top_row.addStretch()

        self.threshold_label = QLabel("<b>Active Threshold:</b>")
        top_row.addWidget(self.threshold_label)

        self.threshold_combo = QComboBox()
        self.threshold_combo.addItems(
            [
                "No Threshold",
                "Hotzone",
                "Warmzone",
                "Fireground",
                "Community",
            ]
        )
        self.threshold_combo.setCurrentText("No Threshold")
        self.threshold_combo.setMinimumWidth(140)
        top_row.addWidget(self.threshold_combo)

        top_row.addStretch()

        self.lbl_stats_pref = QLabel("<b>Stats Pref:</b>")
        top_row.addWidget(self.lbl_stats_pref)

        self.stats_pref_combo = QComboBox()
        self.stats_pref_combo.addItems(["Mean", "Max", "Min", "Count"])
        self.stats_pref_combo.setCurrentText("Mean")
        self.stats_pref_combo.setMinimumWidth(100)
        top_row.addWidget(self.stats_pref_combo)

        # Initial visibility, refined further by _apply_data_type_constraints()
        if self.mode != "objective":
            self.lbl_stats_pref.setVisible(False)
            self.stats_pref_combo.setVisible(False)

        layout.addLayout(top_row)

        # Time / Interval row
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

        self.interval_label = QLabel("Interval:")
        time_interval_row.addWidget(self.interval_label)

        self.interval_combo = QComboBox()
        self.interval_combo.addItems(INTERVAL_OPTIONS)
        self.interval_combo.setCurrentText("Raw")
        time_interval_row.addWidget(self.interval_combo)

        self.only_valid_cb = QCheckBox("Only Valid")
        time_interval_row.addWidget(self.only_valid_cb)

        time_interval_row.addStretch()
        layout.addLayout(time_interval_row)

        # Filter groups
        filters_row = QHBoxLayout()

        self.site_group = FilterGroup("Sites")
        filters_row.addWidget(self.site_group)

        self.device_group = FilterGroup("Identifier")
        filters_row.addWidget(self.device_group)

        self.analyte_group = FilterGroup("Analytes")
        filters_row.addWidget(self.analyte_group)

        layout.addLayout(filters_row)

        # Buttons
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

        # Per-data-type UI adjustments
        self._apply_data_type_constraints()

    def _apply_data_type_constraints(self):
        """Enable/disable/hide controls based on the current data type and form."""

        # ─────────────────────────────────────────────────────────
        # Reset visibility/state first
        # ─────────────────────────────────────────────────────────
        self.threshold_label.setVisible(True)
        self.threshold_combo.setVisible(True)
        self.threshold_combo.setEnabled(True)

        self.interval_label.setVisible(True)
        self.interval_combo.setVisible(True)
        self.interval_combo.setEnabled(True)

        self.only_valid_cb.setVisible(True)
        self.only_valid_cb.setEnabled(True)

        self.site_group.setVisible(True)
        self.device_group.setVisible(True)
        self.analyte_group.setVisible(True)

        self.device_group.setTitle("Identifier")

        # ─────────────────────────────────────────────────────────
        # Rebuild Group By according to data type
        # ─────────────────────────────────────────────────────────
        current_group_by = self.group_by_combo.currentText()

        self.group_by_combo.blockSignals(True)
        self.group_by_combo.clear()

        if self.data_type == "exposure":
            self.group_by_combo.addItems(["Identifier"])
        else:
            self.group_by_combo.addItems(["Identifier", "Site"])

        if current_group_by and self.group_by_combo.findText(current_group_by) >= 0:
            self.group_by_combo.setCurrentText(current_group_by)
        else:
            self.group_by_combo.setCurrentIndex(0)

        self.group_by_combo.blockSignals(False)

        # ─────────────────────────────────────────────────────────
        # Summary Map should be grouped by Site where applicable
        # ─────────────────────────────────────────────────────────
        if (
            self.form == "Summary Map"
            and self.data_type in ("area", "spot", "spectral")
        ):
            self.group_by_combo.setEnabled(False)
            self.group_by_combo.setCurrentText("Site")

            self.site_group.set_enabled(True)
            self.device_group.set_enabled(False)
        else:
            self.group_by_combo.setEnabled(True)
            self._on_group_by_changed(self.group_by_combo.currentText())

        # ─────────────────────────────────────────────────────────
        # Data-type-specific rules
        # ─────────────────────────────────────────────────────────
        if self.data_type == "spectral":
            if self.form != "Summary Map":
                self.group_by_combo.setEnabled(True)

            # Hide interval / only valid / threshold widgets for spectral
            self.threshold_label.setVisible(False)
            self.threshold_combo.setVisible(False)
            self.threshold_combo.setEnabled(False)

            self.interval_label.setVisible(False)
            self.interval_combo.setVisible(False)
            self.interval_combo.setEnabled(False)

            self.only_valid_cb.setVisible(False)
            self.only_valid_cb.setEnabled(False)

            # Force safe hidden values
            self.threshold_combo.setCurrentText("No Threshold")
            self.interval_combo.setCurrentText("Raw")
            self.only_valid_cb.setChecked(False)

            # Spectral does not use analytes
            self.analyte_group.setVisible(False)
            self.analyte_group.setEnabled(False)

        elif self.data_type == "exposure":
            # Exposure only allows Identifier grouping
            self.group_by_combo.setEnabled(False)
            self.group_by_combo.setCurrentText("Identifier")

            self.interval_combo.setEnabled(False)
            self.only_valid_cb.setEnabled(False)

            self.site_group.setVisible(False)
            self.site_group.setEnabled(False)

            self.device_group.setTitle("Identifiers:")
            self.device_group.setEnabled(True)

        elif self.data_type == "spot":
            self.only_valid_cb.setEnabled(False)
            self.only_valid_cb.setChecked(False)

            self.interval_combo.setEnabled(False)
            self.interval_combo.setCurrentText("Raw")

        elif self.data_type == "plume":
            self.group_by_combo.setEnabled(False)

            self.threshold_combo.setEnabled(False)
            self.interval_combo.setEnabled(False)
            self.only_valid_cb.setEnabled(False)

            self.site_group.set_enabled(False)
            self.site_group.setVisible(False)

            self.device_group.set_enabled(False)
            self.device_group.setVisible(False)

            self.analyte_group.set_enabled(False)
            self.analyte_group.setVisible(False)

        # ─────────────────────────────────────────────────────────
        # Stats Pref visibility
        # ─────────────────────────────────────────────────────────
        show_stats_pref = (
            self.mode == "objective"
            and self.data_type not in ("spectral", "plume")
        )

        self.lbl_stats_pref.setVisible(show_stats_pref)
        self.stats_pref_combo.setVisible(show_stats_pref)

    def _on_group_by_changed(self, group_by_text):
        if group_by_text == "Identifier":
            self.site_group.set_enabled(False)
            self.device_group.set_enabled(True)
        elif group_by_text == "Site":
            self.site_group.set_enabled(True)
            self.device_group.set_enabled(False)

    def _populate_filters(self):
        self._set_time_range()

        # Devices / Identifiers
        self.device_group.clear()

        for device in self.available_devices:
            self.device_group.add_checkbox(device, checked=True)

        # Sites / Areas
        self.site_group.clear()

        if self.data_type != "exposure":
            self.site_group.add_checkbox("Unassigned", checked=True)

            for loc in self.available_locations:
                self.site_group.add_checkbox(loc, checked=True)

        # Analytes, still excluded for spectral
        if self.data_type != "spectral":
            self.analyte_group.clear()

            for analyte in self.available_analytes:
                self.analyte_group.add_checkbox(analyte, checked=True)

        # Apply any persisted initial filters
        self._apply_initial_filters()

    def _set_datetime_edit(self, editor, value):
        """Safely set a QDateTimeEdit from datetime or string."""
        if not value:
            return

        if isinstance(value, datetime):
            editor.setDateTime(QDateTime(value))
            return

        if isinstance(value, str) and value != "All":
            dt = QDateTime.fromString(value, DATE_FORMAT)

            if not dt.isValid():
                try:
                    parsed = datetime.fromisoformat(value)
                    dt = QDateTime(parsed)
                except Exception:
                    dt = None

            if dt is not None and dt.isValid():
                editor.setDateTime(dt)

    def _apply_initial_filters(self):
        """Restore controls from self.initial_filters, if any."""
        if not self.initial_filters:
            return

        if self.data_type == "plume":
            self._set_datetime_edit(
                self.start_time_edit,
                self.initial_filters.get("start_time")
            )
            self._set_datetime_edit(
                self.stop_time_edit,
                self.initial_filters.get("stop_time")
            )

            self._apply_data_type_constraints()
            return

        self._set_datetime_edit(
            self.start_time_edit,
            self.initial_filters.get("start_time")
        )
        self._set_datetime_edit(
            self.stop_time_edit,
            self.initial_filters.get("stop_time")
        )

        interval = self.initial_filters.get("interval")

        if interval is not None and self.data_type not in ("spot", "spectral"):
            self.interval_combo.setCurrentText(str(interval))

        group_by = self.initial_filters.get("group_by")

        if group_by:
            ui_group_by = "Identifier" if group_by == "Device" else group_by

            if self.group_by_combo.findText(ui_group_by) >= 0:
                self.group_by_combo.setCurrentText(ui_group_by)
                self._on_group_by_changed(ui_group_by)

        self.only_valid_cb.setChecked(
            bool(self.initial_filters.get("only_valid", False))
        )

        threshold = self.initial_filters.get("threshold_level")

        if threshold:
            level_map = {
                "hotzone_value": "Hotzone",
                "warmzone_value": "Warmzone",
                "fireground_value": "Fireground",
                "community_value": "Community",
            }

            self.threshold_combo.setCurrentText(
                level_map.get(threshold, "No Threshold")
            )

        device_key = DEVICE_KEY_MAP.get(
            self.data_type,
            "selected_area_devices"
        )

        devices = self.initial_filters.get(device_key)

        if devices is None:
            devices = self.initial_filters.get("selected_devices", [])

        if devices is not None:
            self.device_group.set_checked_items(devices)

        if "selected_sites" in self.initial_filters:
            self.site_group.set_checked_items(
                self.initial_filters["selected_sites"]
            )

        if (
            self.data_type != "spectral"
            and "selected_analytes" in self.initial_filters
        ):
            self.analyte_group.set_checked_items(
                self.initial_filters["selected_analytes"]
            )

        # Re-assert data-type/form constraints after restoring saved filters
        self._apply_data_type_constraints()

    def _set_time_range(self):
        """Sets default start/stop times to the previous full hour and current full hour."""
        now_py = datetime.now()

        # Floor to the current hour, e.g. 16:09 -> 16:00
        current_hour = now_py.replace(minute=0, second=0, microsecond=0)

        # Subtract one hour for the start time, e.g. 16:00 -> 15:00
        previous_hour = current_hour - timedelta(hours=1)

        # Apply to UI
        self.start_time_edit.setDateTime(QDateTime(previous_hour))
        self.stop_time_edit.setDateTime(QDateTime(current_hour))

    # ─────────────────────────────────────────────────────────
    # APPLY / GET FILTERS
    # ─────────────────────────────────────────────────────────
    def _apply_filters(self):
        start_dt = self.start_time_edit.dateTime().toPython().replace(
            second=0,
            microsecond=0
        )

        stop_dt = self.stop_time_edit.dateTime().toPython().replace(
            second=0,
            microsecond=0
        )

        if start_dt >= stop_dt:
            QMessageBox.warning(
                self,
                "Invalid Time Range",
                "The start time must be strictly before the stop time.",
            )
            return

        level_map = {
            "No Threshold": None,
            "Hotzone": "hotzone_value",
            "Warmzone": "warmzone_value",
            "Fireground": "fireground_value",
            "Community": "community_value",
        }

        if self.data_type == "spectral":
            self._selected_threshold_level = None
        else:
            self._selected_threshold_level = level_map.get(
                self.threshold_combo.currentText()
            )

        if self.mode == "view":
            self._save_filters_to_disk()

        self.accept()

    def _save_filters_to_disk(self):
        """Save filters to meta/last_filters.json."""
        if not self.incident_path:
            return

        filters = self.get_filters()

        for key in ("start_time", "stop_time"):
            val = filters.get(key)

            if isinstance(val, datetime):
                filters[key] = val.isoformat()

        meta_dir = os.path.join(self.incident_path, "meta")
        os.makedirs(meta_dir, exist_ok=True)

        filters_file = os.path.join(meta_dir, "last_filters.json")

        try:
            with open(filters_file, "w", encoding="utf-8") as f:
                json.dump(filters, f, indent=2)
        except Exception as e:
            logger.error(f"Failed to save filters: {e}")

    def get_filters(self):
        """Return the current filter settings as a dictionary."""

        if self.site_group.isEnabled() and self.site_group.isVisible():
            selected_sites = self.site_group.get_checked_items()
        else:
            if self.data_type == "exposure":
                selected_sites = list(self.available_locations)
            else:
                selected_sites = ["Unassigned"] + list(self.available_locations)

        if self.device_group.isEnabled():
            selected_devices = self.device_group.get_checked_items()
        else:
            selected_devices = list(self.available_devices)

        if self.data_type in ("spectral", "plume"):
            selected_analytes = []
        else:
            selected_analytes = self.analyte_group.get_checked_items()

            if not selected_analytes and self.available_analytes:
                selected_analytes = list(self.available_analytes)

        group_by_text = self.group_by_combo.currentText()

        if group_by_text == "Identifier":
            group_by_text = "Device"

        interval = self.interval_combo.currentText()

        if self.data_type in ("spot", "spectral", "exposure", "plume"):
            interval = "Raw"

        only_valid = (
            self.only_valid_cb.isChecked()
            if self.data_type == "area"
            else False
        )

        threshold_level = self._selected_threshold_level

        if self.data_type in ("spectral", "plume"):
            threshold_level = None

        device_key = DEVICE_KEY_MAP.get(
            self.data_type,
            "selected_area_devices"
        )

        return {
            "start_time": self.start_time_edit.dateTime().toPython(),
            "stop_time": self.stop_time_edit.dateTime().toPython(),
            "interval": interval,
            "group_by": group_by_text,
            "only_valid": only_valid,
            "selected_sites": selected_sites,
            device_key: selected_devices,
            "selected_analytes": selected_analytes,
            "threshold_level": threshold_level,
            "data_type": self.data_type,
            "stats_pref": self.stats_pref_combo.currentText(),
        }
