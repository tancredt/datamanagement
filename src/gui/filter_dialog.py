"""Filter dialog for data analysis with time, site, device, and analyte filtering."""
import os
import sys
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
from datamanagement.filter import FilterManager, DEVICE_KEY_MAP

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

    def _update_toggle_button(self, *_):
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
        mode="view",
        initial_filters=None,
        form=None,
    ):
        super().__init__(parent)
        self.incident_path = incident_path
        self.data_type = str(data_type).strip().lower() if data_type else "spot"
        self.mode = mode
        self.form = str(form).strip() if form else None

        self.filter_manager = None
        if self.incident_path is not None:
            self.filter_manager = FilterManager(
                self.incident_path,
                self.data_type,
            )

        # Determine initial filters based on mode.
        if initial_filters is not None:
            self.initial_filters = initial_filters
        elif mode == "view" and self.filter_manager:
            self.initial_filters = self._load_persisted_filters()
        else:
            self.initial_filters = {}

        # Initialize Database Connection
        self.db = IncidentDatabase(self.incident_path) if self.incident_path else None

        # Load metadata from Database

        if self.db:
            if self.data_type == "exposure":
                self.available_devices = self.db.get_exposure_ids()
            else:
                self.available_devices = self.db.get_devices(self.data_type)
            self.available_locations = self.db.get_markers()
            self.available_analytes = [a["label"] for a in self.db.get_analytes()]
        else:
            self.available_devices = []
            self.available_locations = []
            self.available_analytes = []

        self._selected_threshold_level = None

        # Build UI
        self.setWindowTitle("Data Filters")
        self.resize(900, 600)
        self._setup_ui()
        self._populate_filters()

    # ─────────────────────────────────────────────────────────
    # FILTER MANAGER HELPERS
    # ─────────────────────────────────────────────────────────
    def _load_persisted_filters(self):
        """
        Load persisted filters through FilterManager.
        Returns an empty dict when there is no meaningful saved filter set,
        allowing the dialog to default to all items checked.
        """
        if not self.filter_manager:
            return {}
        filters = self.filter_manager.load_filters()
        if filters.get("start_time") is None and filters.get("stop_time") is None:
            return {}
        return filters

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
            self.site_group.setVisible(True)
            self.site_group.setEnabled(True)
            self.device_group.setVisible(False)
            self.device_group.setEnabled(False)
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
            self.site_group.setVisible(False)
            self.site_group.setEnabled(False)
            self.device_group.setVisible(True)
            self.device_group.setEnabled(True)
        elif group_by_text == "Site":
            self.site_group.setVisible(True)
            self.site_group.setEnabled(True)
            self.device_group.setVisible(False)
            self.device_group.setEnabled(False)

    def _populate_filters(self):
        self._set_time_range()

        # Devices / Identifiers
        self.device_group.clear()
        for device in self.available_devices:
            self.device_group.add_checkbox(device, checked=True)

        # Sites / Areas
        self.site_group.clear()
        if self.data_type != "exposure":
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
        if isinstance(value, str):
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
            interval_text = str(interval).strip()
            if self.interval_combo.findText(interval_text) >= 0:
                self.interval_combo.setCurrentText(interval_text)

        group_by = self.initial_filters.get("group_by")
        if group_by:
            ui_group_by = "Identifier" if str(group_by).strip() == "Device" else str(group_by).strip()
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
                level_map.get(str(threshold).strip(), "No Threshold")
            )

        device_key = DEVICE_KEY_MAP.get(self.data_type, "selected_area_devices")
        devices = self.initial_filters.get(device_key)
        if devices is None:
            devices = self.initial_filters.get("selected_devices", [])
        if devices is not None:
            if isinstance(devices, str):
                devices = [devices]
            self.device_group.set_checked_items(devices)

        sites = self.initial_filters.get("selected_sites")
        if sites is not None:
            if isinstance(sites, str):
                sites = [sites]
            self.site_group.set_checked_items(sites)

        if self.data_type != "spectral":
            analytes = self.initial_filters.get("selected_analytes")
            if analytes is not None:
                if isinstance(analytes, str):
                    analytes = [analytes]
                self.analyte_group.set_checked_items(analytes)

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
        if not self.filter_manager:
            return
        try:
            filters = self.get_filters()
            self.filter_manager.save_filters(filters)
        except Exception as e:
            logger.error(f"Failed to save filters via FilterManager: {e}")

    def get_filters(self):
        """Return the current filter settings as a dictionary."""
        if self.site_group.isEnabled() and self.site_group.isVisible():
            selected_sites = self.site_group.get_checked_items()
        else:
            selected_sites = []

        if self.device_group.isEnabled():
            selected_devices = self.device_group.get_checked_items()
        else:
            selected_devices = []

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

        device_key = DEVICE_KEY_MAP.get(self.data_type, "selected_area_devices")

        filters = {
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

        if self.form is not None:
            filters["form"] = self.form

        return filters
