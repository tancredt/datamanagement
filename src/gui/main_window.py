import os
import sys
import glob
import json
import logging
import pandas as pd
import numpy as np
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QStatusBar, QVBoxLayout, QHBoxLayout,
    QWidget, QLabel, QDialog, QFileDialog, QMessageBox, QProgressDialog,
    QStackedWidget, QDockWidget, QButtonGroup, QPushButton, QGroupBox, QComboBox
)
from PySide6.QtGui import QKeySequence
from PySide6.QtCore import Qt, Slot, QThread, Signal, QObject

# Existing dialogs
from incident_dialog import IncidentDialog
from open_incident_dialog import OpenIncidentDialog
from map_dialog import MapEditorDialog
from spot_readings_dialog import SpotReadingsDialog
from device_locations_dialog import DeviceLocationsDialog
from device_validations_dialog import DeviceValidationsDialog
from battery_analysis_dialog import BatteryAnalysisDialog
from objective_dialog import ObjectiveDialog
from spectral_results_dialog import SpectralResultsDialog

# New modular data view components
from overview_view import OverviewView
from table_view import TableView
from chart_view import ChartView
from summary_table_view import SummaryTableView
from summary_chart_view import SummaryChartView
from summary_map_view import SummaryMapView

# Filter dialog and logic
from filter_dialog import FilterDialog
from datamanagement.filtering import filter_data

# Importer workers
from datamanagement.importer import (
    copy_files_to_realtime,
    process_realtime_data,
    update_site_from_device_log,
    update_validations
)

# Import shared metadata helpers
from device_combo import get_available_devices, get_available_locations

current_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.dirname(current_dir)
if parent_dir not in sys.path:
    sys.path.insert(0, parent_dir)

logger = logging.getLogger(__name__)


class CopyWorker(QObject):
    finished = Signal(int)
    error = Signal(str)

    def __init__(self, incident_path, source_dir):
        super().__init__()
        self.incident_path = incident_path
        self.source_dir = source_dir

    @Slot()
    def do_work(self):
        try:
            copied_count = copy_files_to_realtime(self.incident_path, self.source_dir)
            if copied_count >= 0:
                self.finished.emit(copied_count)
            else:
                self.error.emit("Failed to copy files.")
        except Exception as e:
            self.error.emit(str(e))


class ProcessWorker(QObject):
    finished = Signal(str)
    error = Signal(str)

    def __init__(self, incident_path):
        super().__init__()
        self.incident_path = incident_path

    @Slot()
    def do_work(self):
        try:
            result = process_realtime_data(self.incident_path)
            if result:
                update_site_from_device_log(self.incident_path)
                update_validations(self.incident_path)
            self.finished.emit(result if result else "")
        except Exception as e:
            self.error.emit(str(e))


class DataAnalyzerGUI(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Hazmat Data Analyzer")
        self.resize(1200, 800)

        self._active_incident = None

        # Data viewing state
        self.data_type = "spot"
        self.raw_data = None
        self.filtered_data = None

        # Separate filter storage
        self.spot_filters = {}
        self.area_filters = {}
        self.spectral_filters = {}
        self._spot_threshold_level = None
        self._area_threshold_level = None
        self._spectral_threshold_level = None

        # Active filters
        self.filter_summary = {}
        self._selected_threshold_level = None

        self.available_locations = []
        self.available_devices = []
        self.available_analytes = []
        self.analyte_dec_pls = {}
        self.thresholds_lookup = {}

        self.maps_data = {}
        self.map_filenames = []
        self.mapping_dir = ""

        self.area_data = None
        self.spot_data = None
        self.spectral_data = None  # NEW: Track spectral data for overview

        self._views_initialized = False
        self._last_data_type = None

        self._setup_ui()
        self._setup_menus()
        self._setup_status_bar()
        self._update_app_state(False)

    @property
    def active_label(self) -> str | None:
        return self._active_incident.get("label") if self._active_incident else None

    @property
    def active_incident_path(self) -> str | None:
        return self._active_incident.get("incident_path") if self._active_incident else None

    def set_active_incident(self, data: dict):
        self._active_incident = data
        self._update_app_state(data is not None)
        self._update_status_bar()

        if data is not None:
            self._load_analytes_config()
            self._load_overview_data()
            self._load_spectral_data_for_overview()  # NEW

            if not self._views_initialized:
                self._initialize_data_views()
                self._views_initialized = True

            # UPDATED: Always pass all three data sources to overview
            self.overview_view.update_data(
                self.area_data,
                self.spot_data,
                self.spectral_data,
            )
            self.view_stack.setCurrentIndex(0)
            self.nav_btns[0].setChecked(True)
            self.central_stack.setCurrentIndex(1)

            self.data_type_combo.blockSignals(True)
            self.data_type_combo.setCurrentText("Spot Readings")
            self.data_type_combo.blockSignals(False)
            self._on_data_type_changed("Spot Readings")

    def _update_app_state(self, has_incident: bool):
        actions = [
            self.action_edit_incident, self.action_map_spot, self.action_spot_readings,
            self.action_import_area, self.action_map_area, self.action_device_locations,
            self.action_device_validations, self.action_battery, self.action_hotzone,
            self.action_warmzone, self.action_fireground, self.action_community,
            self.action_publish, self.action_map_spectral, self.action_spectral_results
        ]
        for action in actions:
            action.setEnabled(has_incident)

        controls = [self.data_type_combo, self.btn_filters, self.filter_summary_group]
        for ctrl in controls:
            ctrl.setEnabled(has_incident)

        for btn in self.nav_btns.values():
            btn.setEnabled(has_incident)

        if has_incident:
            self.dock.show()
            self.action_toggle_dock.setChecked(True)
        else:
            self.dock.hide()
            self.action_toggle_dock.setChecked(False)
            self.central_stack.setCurrentIndex(0)

    # ─────────────────────────────────────────────────────────
    # UI SETUP
    # ─────────────────────────────────────────────────────────
    def _setup_ui(self):
        self.central_stack = QStackedWidget()
        self.setCentralWidget(self.central_stack)

        self.welcome_page = QWidget()
        welcome_layout = QVBoxLayout(self.welcome_page)
        self.info_label = QLabel("📊 Ready to import data.\nCreate or open an incident to begin analysis.")
        self.info_label.setAlignment(Qt.AlignCenter)
        self.info_label.setStyleSheet("font-size: 18px; color: #6b7280;")
        welcome_layout.addWidget(self.info_label)
        self.central_stack.addWidget(self.welcome_page)

        self.data_page = QWidget()
        data_layout = QVBoxLayout(self.data_page)
        data_layout.setContentsMargins(0, 0, 0, 0)

        self.view_stack = QStackedWidget()
        data_layout.addWidget(self.view_stack)
        self.central_stack.addWidget(self.data_page)

        self.dock = QDockWidget("Data Controls", self)
        self.dock.setAllowedAreas(Qt.LeftDockWidgetArea | Qt.RightDockWidgetArea)
        self.dock.setFeatures(QDockWidget.DockWidgetMovable | QDockWidget.DockWidgetFloatable | QDockWidget.DockWidgetClosable)
        self.dock.setMinimumWidth(250)
        self.dock.setMaximumWidth(300)
        self.dock.setMinimumSize(250, 400)

        dock_widget = QWidget()
        dock_layout = QVBoxLayout(dock_widget)
        dock_layout.setContentsMargins(10, 15, 10, 15)
        dock_layout.setSpacing(10)

        self.data_type_combo = QComboBox()
        self.data_type_combo.addItems(["Spot Readings", "Area Readings", "Spectral Results"])
        self.data_type_combo.setMinimumHeight(35)
        self.data_type_combo.setStyleSheet("font-size: 13px; font-weight: bold;")
        self.data_type_combo.currentTextChanged.connect(self._on_data_type_changed)
        dock_layout.addWidget(self.data_type_combo)
        dock_layout.addSpacing(5)

        self.nav_group = QButtonGroup(self)
        self.nav_group.setExclusive(True)
        nav_items = [
            ("Overview", 0), ("Table", 1), ("Chart", 2),
            ("Summary Table", 3), ("Summary Chart", 4), ("Summary Map", 5)
        ]
        self.nav_btns = {}
        for text, idx in nav_items:
            btn = QPushButton(text)
            btn.setCheckable(True)
            btn.setMinimumHeight(35)
            btn.setCursor(Qt.PointingHandCursor)
            btn.setStyleSheet("""
                QPushButton { text-align: left; padding-left: 15px; border: none; border-radius: 6px; font-size: 13px; color: #374151; }
                QPushButton:hover { background-color: #e5e7eb; }
                QPushButton:checked { background-color: #2563eb; color: white; font-weight: bold; }
            """)
            btn.clicked.connect(lambda checked, i=idx: self._on_nav_clicked(i))
            self.nav_group.addButton(btn, idx)
            dock_layout.addWidget(btn)
            self.nav_btns[idx] = btn

        dock_layout.addStretch()

        self.filter_summary_group = QGroupBox("Filter Summary")
        fs_layout = QVBoxLayout(self.filter_summary_group)
        fs_layout.setContentsMargins(10, 15, 10, 10)

        labels = ["Time: --", "Interval: --", "Group: --", "Sites: --", "Devices: --", "Analytes: --"]
        self.filter_labels = []
        for text in labels:
            lbl = QLabel(text)
            lbl.setStyleSheet("font-weight: bold; color: #374151; font-size: 12px;")
            fs_layout.addWidget(lbl)
            self.filter_labels.append(lbl)

        dock_layout.addWidget(self.filter_summary_group)
        dock_layout.addSpacing(10)

        self.btn_filters = QPushButton("Filters")
        self.btn_filters.setMinimumHeight(45)
        self.btn_filters.setCursor(Qt.PointingHandCursor)
        self.btn_filters.setStyleSheet("""
            QPushButton { 
                text-align: center; border: none; border-radius: 6px; 
                font-size: 14px; color: white; background-color: #10b981; font-weight: bold;  
            }
            QPushButton:hover { background-color: #059669; }
        """)
        self.btn_filters.clicked.connect(self._open_filter_dialog)
        dock_layout.addWidget(self.btn_filters)

        self.dock.setWidget(dock_widget)
        self.addDockWidget(Qt.RightDockWidgetArea, self.dock)
        self.dock.hide()

    def _setup_menus(self):
        menubar = self.menuBar()

        file_menu = menubar.addMenu("&File")
        self.action_new_incident = file_menu.addAction("&New Incident", self._on_new_incident)
        self.action_new_incident.setShortcut(QKeySequence("Ctrl+N"))
        self.action_open_incident = file_menu.addAction("&Open Incident...", self._on_open_incident)
        self.action_open_incident.setShortcut(QKeySequence("Ctrl+O"))
        self.action_edit_incident = file_menu.addAction("&Edit Incident...", self._on_edit_incident)
        self.action_edit_incident.setShortcut(QKeySequence("Ctrl+Shift+E"))
        file_menu.addSeparator()
        self.action_exit = file_menu.addAction("&Exit", self.close)
        self.action_exit.setShortcut(QKeySequence("Ctrl+Q"))

        spot_menu = menubar.addMenu("&Spot Readings")
        self.action_map_spot = spot_menu.addAction("&Map...", self._on_map_spot)
        self.action_spot_readings = spot_menu.addAction("&Readings...", self._on_spot_readings)

        area_menu = menubar.addMenu("&Area Readings")
        self.action_import_area = area_menu.addAction("&Import Data...", self._on_import_area)
        self.action_map_area = area_menu.addAction("&Map...", self._on_map_area)
        area_menu.addSeparator()
        self.action_device_locations = area_menu.addAction("Device &Locations...", self._on_device_locations)
        self.action_device_validations = area_menu.addAction("Device &Validations...", self._on_device_validations)
        self.action_battery = area_menu.addAction("&Battery...", self._on_battery_analysis)

        spectral_menu = menubar.addMenu("&Spectral Records")
        self.action_map_spectral = spectral_menu.addAction("&Map...", self._on_map_spectral)
        self.action_spectral_results = spectral_menu.addAction("&Results...", self._on_spectral_results)

        reports_menu = menubar.addMenu("&Reports")
        self.action_hotzone = reports_menu.addAction("&Hotzone", self._on_report_hotzone)
        self.action_warmzone = reports_menu.addAction("&Warmzone", self._on_report_warmzone)
        self.action_fireground = reports_menu.addAction("&Fireground", self._on_report_fireground)
        self.action_community = reports_menu.addAction("&Community", self._on_report_community)
        reports_menu.addSeparator()
        self.action_publish = reports_menu.addAction("&Publish")
        self.action_publish.triggered.connect(self._on_report_publish)

        view_menu = menubar.addMenu("&View")
        self.action_toggle_dock = view_menu.addAction("&Data Controls")
        self.action_toggle_dock.setCheckable(True)
        self.action_toggle_dock.setChecked(True)
        self.action_toggle_dock.triggered.connect(self._toggle_dock_visibility)
        self.dock.visibilityChanged.connect(self.action_toggle_dock.setChecked)

    def _toggle_dock_visibility(self, checked):
        self.dock.setVisible(checked)

    def _setup_status_bar(self):
        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)
        self.status_label = QLabel()
        self.status_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.status_bar.addPermanentWidget(self.status_label)
        self._update_status_bar("Ready")

    def _update_status_bar(self, message: str = ""):
        incident_text = f"| 📍 Active: {self.active_label}" if self.active_label else ""
        self.status_bar.showMessage(f"{message} {incident_text}")
        self.status_label.setText(incident_text.lstrip("| ") if self.active_label else "No active incident")

    # ─────────────────────────────────────────────────────────
    # DATA TYPE SWITCHING & LOADING
    # ─────────────────────────────────────────────────────────
    @Slot(str)
    def _on_data_type_changed(self, text):
        if not self.active_incident_path:
            return

        # Save current state
        if self.data_type == "spot":
            self.spot_filters = self.filter_summary.copy() if self.filter_summary else {}
            self._spot_threshold_level = self._selected_threshold_level
        elif self.data_type == "area":
            self.area_filters = self.filter_summary.copy() if self.filter_summary else {}
            self._area_threshold_level = self._selected_threshold_level
        elif self.data_type == "spectral":
            self.spectral_filters = self.filter_summary.copy() if self.filter_summary else {}
            self._spectral_threshold_level = self._selected_threshold_level

        if "Spectral" in text:
            new_data_type = "spectral"
        elif "Spot" in text:
            new_data_type = "spot"
        else:
            new_data_type = "area"
        self.data_type = new_data_type

        # Restore state
        if self.data_type == "spot":
            self.filter_summary = self.spot_filters.copy() if self.spot_filters else {}
            self._selected_threshold_level = self._spot_threshold_level
        elif self.data_type == "area":
            self.filter_summary = self.area_filters.copy() if self.area_filters else {}
            self._area_threshold_level = self._area_threshold_level
        elif self.data_type == "spectral":
            self.filter_summary = self.spectral_filters.copy() if self.spectral_filters else {}
            self._spectral_threshold_level = self._spectral_threshold_level

        # Handle dock navigation buttons for Spectral
        is_spectral = (self.data_type == "spectral")
        for idx, btn in self.nav_btns.items():
            if idx in [0, 1]:  # Overview and Table
                btn.setEnabled(True)
            else:
                btn.setEnabled(not is_spectral)
                if is_spectral and btn.isChecked():
                    self.nav_btns[0].setChecked(True)  # Force Overview

        progress = QProgressDialog("Loading data...", None, 0, 0, self)
        progress.setWindowTitle("Loading")
        progress.setWindowModality(Qt.WindowModal)
        progress.setCancelButton(None)
        progress.show()
        QApplication.processEvents()

        try:
            self._load_thresholds()
            QApplication.processEvents()

            if self.data_type == "spot":
                self._load_spot_data()
            elif self.data_type == "area":
                self._load_area_data()
            elif self.data_type == "spectral":
                self._load_spectral_data()
            QApplication.processEvents()

            if self.data_type != "spectral":
                self._load_map_data()
            QApplication.processEvents()

            # Rebuild views if switching to/from spectral
            if not self._views_initialized or self._last_data_type != self.data_type:
                self._initialize_data_views()
                self._views_initialized = True
            self._last_data_type = self.data_type

            self._apply_initial_filters()
            QApplication.processEvents()

            self.central_stack.setCurrentIndex(1)
            self._update_status_bar(f"📊 Loaded {self.data_type.title()} Data.")
        finally:
            progress.close()
            progress.deleteLater()

    def _load_analytes_config(self):
        analyte_config_path = os.path.normpath(os.path.join(current_dir, '..', 'static', 'lists', 'analytes.json'))
        self.available_analytes = []
        self.analyte_dec_pls = {}

        if os.path.exists(analyte_config_path):
            try:
                with open(analyte_config_path, 'r', encoding='utf-8') as f:
                    analyte_config = json.load(f)
                    analytes_list = analyte_config.get("analytes", [])
                    for analyte in analytes_list:
                        clean_analyte = {k.strip(): str(v).strip() for k, v in analyte.items()}
                        name = clean_analyte.get("name")
                        dec_pls = clean_analyte.get("dec_pls", 2)
                        if name:
                            self.available_analytes.append(name)
                            try:
                                self.analyte_dec_pls[name] = int(dec_pls)
                            except (ValueError, TypeError):
                                self.analyte_dec_pls[name] = 2
            except Exception as e:
                logger.error(f"Failed to load analytes config: {e}")

    def _load_thresholds(self):
        thresholds_file = os.path.join(self.active_incident_path, "meta", "thresholds.json")
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
                            for key in ["hotzone_value", "warmzone_value", "fireground_value", "community_value"]:
                                raw = clean.get(key, "0")
                                try:
                                    entry[key] = float(str(raw).strip())
                                except (ValueError, TypeError):
                                    entry[key] = 0.0
                            self.thresholds_lookup[analyte_name.upper()] = entry
            except Exception as e:
                logger.error(f"Failed to load thresholds: {e}")

    def _load_spot_data(self):
        data_file = os.path.join(self.active_incident_path, "mapping", "spot_locations.json")
        if os.path.exists(data_file):
            try:
                with open(data_file, 'r', encoding='utf-8') as f:
                    spot_json = json.load(f)
                self.raw_data = self._convert_spot_to_df(spot_json)
                self._extract_metadata_from_df()
            except Exception as e:
                logger.error(f"Failed to load spot data: {e}")
                self.raw_data = pd.DataFrame()
        else:
            self.raw_data = pd.DataFrame()

    def _load_area_data(self):
        data_file = os.path.join(self.active_incident_path, "data", "processed", "area_data.csv")
        if os.path.exists(data_file):
            try:
                self.raw_data = pd.read_csv(data_file, low_memory=False)
                self.raw_data['LOG TIME'] = pd.to_datetime(self.raw_data['LOG TIME'], errors='coerce')
                self._extract_metadata_from_df()
            except Exception as e:
                logger.error(f"Failed to load area data: {e}")
                self.raw_data = pd.DataFrame()
        else:
            self.raw_data = pd.DataFrame()

    def _load_spectral_data(self):
        data_file = os.path.join(self.active_incident_path, "mapping", "spectral_locations.json")
        if os.path.exists(data_file):
            try:
                with open(data_file, 'r', encoding='utf-8') as f:
                    spectral_json = json.load(f)
                self.raw_data = self._convert_spectral_to_df(spectral_json)
                self._extract_spectral_metadata(spectral_json)
            except Exception as e:
                logger.error(f"Failed to load spectral data: {e}")
                self.raw_data = pd.DataFrame()
                self.available_locations = []
                self.available_devices = []
        else:
            self.raw_data = pd.DataFrame()
            self.available_locations = []
            self.available_devices = []

    def _convert_spectral_to_df(self, spectral_data):
        rows = []
        for loc in spectral_data.get("maps", {}).get("locations", []):
            for marker in loc.get("markers", []):
                label = marker.get("label", "")
                site = label if label else "Unassigned"
                for r in marker.get("readings", []):
                    clean_r = {k.strip(): v for k, v in r.items()}
                    row = {
                        "LOG TIME": clean_r.get("datetime"),
                        "DEVICE": clean_r.get("device", ""),
                        "SITE": site,
                        "chemicals_identified": clean_r.get("chemicals_identified", ""),
                        "comments": clean_r.get("comments", ""),
                        "file_ref": clean_r.get("file_ref", "")
                    }
                    rows.append(row)
        df = pd.DataFrame(rows)
        if not df.empty:
            df['LOG TIME'] = pd.to_datetime(df['LOG TIME'], errors='coerce')
        return df

    def _extract_spectral_metadata(self, spectral_json):
        locations = set()
        devices = set()
        for loc in spectral_json.get("maps", {}).get("locations", []):
            for marker in loc.get("markers", []):
                label = marker.get("label", "")
                if label:
                    locations.add(label)
                for r in marker.get("readings", []):
                    dev = r.get("device", "")
                    if dev:
                        devices.add(dev)
        self.available_locations = sorted(list(locations))
        self.available_devices = sorted(list(devices))

    def _load_overview_data(self):
        """Loads area and spot data for the overview view."""
        area_file = os.path.join(self.active_incident_path, "data", "processed", "area_data.csv")
        if os.path.exists(area_file):
            try:
                self.area_data = pd.read_csv(area_file, low_memory=False)
                self.area_data['LOG TIME'] = pd.to_datetime(self.area_data['LOG TIME'], errors='coerce')
            except Exception as e:
                logger.error(f"Failed to load area data for overview: {e}")
                self.area_data = pd.DataFrame()
        else:
            self.area_data = pd.DataFrame()

        spot_file = os.path.join(self.active_incident_path, "mapping", "spot_locations.json")
        if os.path.exists(spot_file):
            try:
                with open(spot_file, 'r', encoding='utf-8') as f:
                    spot_json = json.load(f)
                self.spot_data = self._convert_spot_to_df(spot_json)
            except Exception as e:
                logger.error(f"Failed to load spot data for overview: {e}")
                self.spot_data = pd.DataFrame()
        else:
            self.spot_data = pd.DataFrame()

    def _load_spectral_data_for_overview(self):
        """Loads spectral data specifically for the Overview view."""
        spectral_file = os.path.join(self.active_incident_path, "mapping", "spectral_locations.json")
        if os.path.exists(spectral_file):
            try:
                with open(spectral_file, 'r', encoding='utf-8') as f:
                    spectral_json = json.load(f)
                self.spectral_data = self._convert_spectral_to_df(spectral_json)
            except Exception as e:
                logger.error(f"Failed to load spectral data for overview: {e}")
                self.spectral_data = pd.DataFrame()
        else:
            self.spectral_data = pd.DataFrame()

    def _load_map_data(self):
        self.mapping_dir = os.path.join(self.active_incident_path, "mapping")
        json_file = os.path.join(self.mapping_dir, f"{self.data_type}_locations.json")
        self.maps_data = {}
        self.map_filenames = []

        if os.path.exists(json_file):
            try:
                with open(json_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                for loc in data.get("maps", {}).get("locations", []):
                    fname = loc.get("filename")
                    if fname:
                        self.maps_data[fname] = loc.get("markers", [])
                        self.map_filenames.append(fname)
            except Exception as e:
                logger.error(f"Failed to load map data: {e}")

    def _convert_spot_to_df(self, spot_data):
        rows = []
        maps_dict = spot_data.get("maps", {})
        locations_list = maps_dict.get("locations", [])

        for loc in locations_list:
            markers = loc.get("markers", [])
            for marker in markers:
                label = marker.get("label", "")
                site = label if label else "Unassigned"
                readings = marker.get("readings", [])
                for r in readings:
                    clean_r = {k.strip(): v for k, v in r.items()}
                    row = {
                        "LOG TIME": clean_r.get("datetime"),
                        "DEVICE": clean_r.get("device", ""),
                        "SITE": site,
                        "observations": clean_r.get("observations", ""),
                        "Latitude": np.nan,
                        "Longitude": np.nan
                    }
                    for analyte in self.available_analytes:
                        row[analyte] = clean_r.get(analyte)
                        row[f"INVALID_{analyte}"] = 0
                    rows.append(row)
        df = pd.DataFrame(rows)
        if not df.empty:
            df['LOG TIME'] = pd.to_datetime(df['LOG TIME'], errors='coerce')
        return df

    def _extract_metadata_from_df(self):
        self.available_locations = get_available_locations(self.active_incident_path, self.data_type)
        self.available_devices = get_available_devices(self.active_incident_path, self.data_type)

    def _initialize_data_views(self):
        while self.view_stack.count() > 0:
            w = self.view_stack.widget(0)
            self.view_stack.removeWidget(w)
            w.deleteLater()

        # Always initialize the standard 6 views
        self.overview_view = OverviewView(analyte_dec_pls=self.analyte_dec_pls, parent=self)
        self.table_view = TableView(analyte_dec_pls=self.analyte_dec_pls, parent=self)
        self.chart_view = ChartView(parent=self)
        self.summary_table_view = SummaryTableView(analyte_dec_pls=self.analyte_dec_pls, parent=self)
        self.summary_chart_view = SummaryChartView(parent=self)
        self.summary_map_view = SummaryMapView(
            map_filenames=self.map_filenames,
            available_analytes=self.available_analytes,
            analyte_dec_pls=self.analyte_dec_pls,
            mapping_dir=self.mapping_dir,
            maps_data=self.maps_data,
            parent=self
        )

        self.table_view.connect_signals(
            export_callback=self._export_table_csv,
            prev_callback=self._on_prev_page,
            next_callback=self._on_next_page
        )
        self.summary_table_view.connect_signals(export_callback=self._export_summary_csv)
        self.summary_map_view.connect_signals(export_callback=self._on_export_summary_map)

        self.view_stack.addWidget(self.overview_view)
        self.view_stack.addWidget(self.table_view)
        self.view_stack.addWidget(self.chart_view)
        self.view_stack.addWidget(self.summary_table_view)
        self.view_stack.addWidget(self.summary_chart_view)
        self.view_stack.addWidget(self.summary_map_view)

        self.view_stack.setCurrentIndex(0)
        for idx, btn in self.nav_btns.items():
            btn.setChecked(idx == 0)

    def _apply_initial_filters(self):
        if self.raw_data is None or self.raw_data.empty:
            # UPDATED: Even if current data is empty, still update overview with all sources
            self._load_overview_data()
            self._load_spectral_data_for_overview()
            self.overview_view.update_data(
                self.area_data,
                self.spot_data,
                self.spectral_data,
                self.available_analytes
            )
            return

        df = self.raw_data.copy()

        # Calculate data bounds
        if 'LOG TIME' in df.columns and not df['LOG TIME'].dropna().empty:
            data_start = df['LOG TIME'].min()
            data_stop = df['LOG TIME'].max()
        else:
            data_start = pd.Timestamp.now()
            data_stop = pd.Timestamp.now()

        # If filter_summary is empty (first load), initialize with data bounds
        if not self.filter_summary:
            self.filter_summary = {
                "start_time": data_start,
                "stop_time": data_stop,
                "interval": "Raw",
                "group_by": "Device",
                "only_valid": False,
                "selected_sites": ["Unassigned"] + list(self.available_locations),
                "selected_devices": list(self.available_devices),
                "selected_analytes": list(self.available_analytes),
                "threshold_level": None
            }
        else:
            # Preserve user's previously set times when switching data types
            old_sites = self.filter_summary.get('selected_sites', [])
            valid_sites = [s for s in old_sites if s in self.available_locations or s == 'Unassigned']
            self.filter_summary['selected_sites'] = valid_sites if valid_sites else (["Unassigned"] + list(self.available_locations))

            old_devices = self.filter_summary.get('selected_devices', [])
            valid_devices = [d for d in old_devices if d in self.available_devices]
            self.filter_summary['selected_devices'] = valid_devices if valid_devices else list(self.available_devices)

            old_analytes = self.filter_summary.get('selected_analytes', [])
            valid_analytes = [g for g in old_analytes if g in self.available_analytes]
            self.filter_summary['selected_analytes'] = valid_analytes if valid_analytes else list(self.available_analytes)

        # Save to data type specific storage
        if self.data_type == "spot":
            self.spot_filters = self.filter_summary.copy()
            self._spot_threshold_level = self._selected_threshold_level
        elif self.data_type == "area":
            self.area_filters = self.filter_summary.copy()
            self._area_threshold_level = self._selected_threshold_level
        elif self.data_type == "spectral":
            self.spectral_filters = self.filter_summary.copy()
            self._spectral_threshold_level = self._selected_threshold_level

        # Custom filtering logic for Spectral to avoid analyte crashes
        if self.data_type == "spectral":
            mask = pd.Series([True] * len(df))
            if 'LOG TIME' in df.columns:
                mask &= (df['LOG TIME'] >= self.filter_summary['start_time'])
                mask &= (df['LOG TIME'] <= self.filter_summary['stop_time'])
            if 'SITE' in df.columns:
                mask &= df['SITE'].isin(self.filter_summary['selected_sites'])
            if 'DEVICE' in df.columns:
                mask &= df['DEVICE'].isin(self.filter_summary['selected_devices'])
            self.filtered_data = df[mask].copy()
            if not self.filtered_data.empty and 'LOG TIME' in self.filtered_data.columns:
                self.filtered_data = self.filtered_data.sort_values(by='LOG TIME')
            self._update_all_views()
            self._update_filter_summary_labels()
            return

        self.filtered_data = filter_data(
            self.raw_data,
            self.filter_summary['start_time'],
            self.filter_summary['stop_time'],
            self.filter_summary['interval'],
            self.filter_summary['selected_sites'],
            self.filter_summary['selected_analytes'],
            self.filter_summary['selected_devices'],
            self.filter_summary['only_valid'],
            self.filter_summary['group_by']
        )

        if self.filtered_data is not None and not self.filtered_data.empty:
            if 'LOG TIME' in self.filtered_data.columns:
                self.filtered_data = self.filtered_data.sort_values(by='LOG TIME')
            interval = self.filter_summary.get("interval", "Raw")
            group_by = self.filter_summary.get("group_by", "Device")
            if interval != "Raw":
                if group_by == "Device" and "SITE" in self.filtered_data.columns:
                    self.filtered_data = self.filtered_data.drop(columns=["SITE"])
                elif group_by == "Site" and "DEVICE" in self.filtered_data.columns:
                    self.filtered_data = self.filtered_data.drop(columns=["DEVICE"])
            self.filtered_data = self._reorder_columns(self.filtered_data)

        self._update_all_views()

    # ─────────────────────────────────────────────────────────
    # UPDATED: _update_all_views - Always shows all three accordions in Overview
    # ─────────────────────────────────────────────────────────
    def _update_all_views(self):
        if self.filtered_data is None:
            return

        # ── Always load all three data sources for the Overview ──
        self._load_overview_data()
        self._load_spectral_data_for_overview()

        # ── Overview always shows ALL accordions regardless of data type ──
        self.overview_view.update_data(
            self.area_data,
            self.spot_data,
            self.spectral_data,
            self.available_analytes
        )

        # ── Handle Spectral-specific views (Table only) ──
        if self.data_type == "spectral":
            self.table_view.set_data(self.filtered_data, show_invalid_bg=False, active_thresholds={})
            self._update_filter_summary_labels()
            return

        # ── Handle Spot / Area Views ──
        only_valid = self.filter_summary.get("only_valid", False)
        active_thresholds = self._get_active_thresholds()
        self.table_view.set_data(self.filtered_data, show_invalid_bg=not only_valid, active_thresholds=active_thresholds)
        self.chart_view.plot_data(self.filtered_data, self.filter_summary, self.available_analytes, self._get_active_thresholds)
        self.summary_table_view.update_data(self.filtered_data, self.filter_summary, self.available_analytes, self._get_active_thresholds)
        self.summary_chart_view.update_data(self.summary_table_view.get_summary_data(), self.filter_summary, active_thresholds)
        self.summary_map_view.update_data(self.filtered_data)
        self._update_filter_summary_labels()

    def _get_active_thresholds(self):
        if not self._selected_threshold_level:
            return {}
        result = {}
        for analyte in self.available_analytes:
            analyte_upper = analyte.upper()
            if analyte_upper in self.thresholds_lookup:
                val = self.thresholds_lookup[analyte_upper].get(self._selected_threshold_level)
                if val is not None:
                    result[analyte] = val
        return result

    def _reorder_columns(self, df):
        if df is None or df.empty:
            return df
        ordered = []
        for col in ['LOG TIME', 'SITE', 'DEVICE', 'observations']:
            if col in df.columns:
                ordered.append(col)
        for analyte in self.available_analytes:
            if analyte in df.columns and analyte not in ordered:
                ordered.append(analyte)
        for col in df.columns:
            if col.upper().startswith('INVALID_') and col not in ordered:
                ordered.append(col)
        for col in df.columns:
            if col not in ordered:
                ordered.append(col)
        return df[ordered]

    # ─────────────────────────────────────────────────────────
    # FILTERING & NAVIGATION
    # ─────────────────────────────────────────────────────────
    @Slot(int)
    def _on_nav_clicked(self, index):
        if self.data_type == "spectral" and index > 1:
            index = 0
        self.view_stack.setCurrentIndex(index)

    def _open_filter_dialog(self):
        if self.raw_data is None or self.raw_data.empty:
            QMessageBox.warning(self, "No Data", "No data loaded to filter.")
            return

        dialog = FilterDialog(
            parent=self,
            incident_path=self.active_incident_path,
            raw_data=self.raw_data,
            analyte_dec_pls=self.analyte_dec_pls,
            thresholds_lookup=self.thresholds_lookup,
            initial_filters=self.filter_summary,
            data_type=self.data_type
        )

        if dialog.exec() == QDialog.Accepted:
            new_filters = dialog.get_filters()

            if self.data_type == "spectral":
                df = self.raw_data.copy()
                mask = pd.Series([True] * len(df))
                if 'LOG TIME' in df.columns:
                    mask &= (df['LOG TIME'] >= new_filters['start_time'])
                    mask &= (df['LOG TIME'] <= new_filters['stop_time'])
                if 'SITE' in df.columns:
                    mask &= df['SITE'].isin(new_filters['selected_sites'])
                if 'DEVICE' in df.columns:
                    mask &= df['DEVICE'].isin(new_filters['selected_devices'])
                self.filtered_data = df[mask].copy()
                if not self.filtered_data.empty and 'LOG TIME' in self.filtered_data.columns:
                    self.filtered_data = self.filtered_data.sort_values(by='LOG TIME')
            else:
                self.filtered_data = filter_data(
                    self.raw_data,
                    new_filters['start_time'],
                    new_filters['stop_time'],
                    new_filters['interval'],
                    new_filters['selected_sites'],
                    new_filters['selected_analytes'],
                    new_filters['selected_devices'],
                    new_filters['only_valid'],
                    new_filters['group_by']
                )
                if self.filtered_data is not None and not self.filtered_data.empty:
                    if 'LOG TIME' in self.filtered_data.columns:
                        self.filtered_data = self.filtered_data.sort_values(by='LOG TIME')
                    interval = self.filter_summary.get("interval", "Raw")
                    group_by = self.filter_summary.get("group_by", "Device")
                    if interval != "Raw":
                        if group_by == "Device" and "SITE" in self.filtered_data.columns:
                            self.filtered_data = self.filtered_data.drop(columns=["SITE"])
                        elif group_by == "Site" and "DEVICE" in self.filtered_data.columns:
                            self.filtered_data = self.filtered_data.drop(columns=["DEVICE"])
                    self.filtered_data = self._reorder_columns(self.filtered_data)

            self._selected_threshold_level = new_filters['threshold_level']
            self.thresholds_lookup = dialog.thresholds_lookup
            self.filter_summary = new_filters

            if self.data_type == "spot":
                self.spot_filters = self.filter_summary.copy()
                self._spot_threshold_level = self._selected_threshold_level
            elif self.data_type == "area":
                self.area_filters = self.filter_summary.copy()
                self._area_threshold_level = self._selected_threshold_level
            elif self.data_type == "spectral":
                self.spectral_filters = self.filter_summary.copy()
                self._spectral_threshold_level = self._selected_threshold_level

            self._update_all_views()
            self._update_filter_summary_labels()

    def _update_filter_summary_labels(self):
        summary = self.filter_summary
        if not summary:
            texts = ["Time: --", "Interval: --", "Group: --", "Sites: --", "Devices: --", "Analytes: --"]
            for lbl, text in zip(self.filter_labels, texts):
                lbl.setText(text)
            return

        start_t = summary.get('start_time', '--')
        stop_t = summary.get('stop_time', '--')
        if hasattr(start_t, 'strftime'):
            start_t = start_t.strftime("%Y-%m-%d %H:%M")
        if hasattr(stop_t, 'strftime'):
            stop_t = stop_t.strftime("%Y-%m-%d %H:%M")

        interval_text = summary.get('interval', '--')
        if self.data_type == "spectral":
            interval_text = "Raw (N/A)"

        analytes_count = len(summary.get('selected_analytes', []))
        analytes_text = "N/A" if self.data_type == "spectral" else str(analytes_count)

        texts = [
            f"Time: {start_t} to {stop_t}",
            f"Interval: {interval_text}",
            f"Group: {summary.get('group_by', '--')}",
            f"Sites: {len(summary.get('selected_sites', []))}",
            f"Devices: {len(summary.get('selected_devices', []))}",
            f"Analytes: {analytes_text}"
        ]
        for lbl, text in zip(self.filter_labels, texts):
            lbl.setText(text)

    @Slot()
    def _on_prev_page(self):
        if hasattr(self, 'table_view') and self.table_view.model.prev_page():
            self.table_view._update_table()

    @Slot()
    def _on_next_page(self):
        if hasattr(self, 'table_view') and self.table_view.model.next_page():
            self.table_view._update_table()

    def _export_table_csv(self):
        if self.filtered_data is None or self.filtered_data.empty:
            QMessageBox.warning(self, "No Data", "There is no filtered data to export.")
            return

        file_path, _ = QFileDialog.getSaveFileName(
            self, "Export Table to CSV", "filtered_data.csv",
            "CSV Files (*.csv);;All Files (*)"
        )
        if file_path:
            try:
                export_df = self.filtered_data.copy()
                inv_cols = [c for c in export_df.columns if c.upper().startswith('INVALID_')]
                export_df.drop(columns=inv_cols, inplace=True, errors='ignore')
                export_df.to_csv(file_path, index=False)
                QMessageBox.information(self, "Success", f"Table exported successfully to:\n{file_path}")
            except Exception as e:
                QMessageBox.critical(self, "Error", f"Failed to export table:\n{e}")

    def _export_summary_csv(self):
        if not hasattr(self, 'summary_table_view') or not self.summary_table_view.summary_data:
            QMessageBox.warning(self, "No Data", "There is no summary data to export.")
            return

        group_by = self.filter_summary.get("group_by", "Device")
        self.summary_table_view.export_csv(group_by_name=group_by)

    def _on_export_summary_map(self):
        if hasattr(self, 'summary_map_view'):
            self.summary_map_view.export_map()

    # ─────────────────────────────────────────────────────────
    # UPDATED: _refresh_overview - Always loads all three data sources
    # ─────────────────────────────────────────────────────────
    def _refresh_overview(self):
        if not self.active_incident_path:
            return
        if not hasattr(self, 'overview_view') or self.overview_view is None:
            return

        self._load_analytes_config()
        # Always reload all three data sources
        self._load_overview_data()
        self._load_spectral_data_for_overview()
        self.overview_view.update_data(
            self.area_data,
            self.spot_data,
            self.spectral_data,
            self.available_analytes
        )

    # ─────────────────────────────────────────────────────────
    # EXISTING & NEW MENU ACTIONS
    # ─────────────────────────────────────────────────────────
    def _launch_objective_dialog(self, zone_name):
        if not self.active_incident_path:
            self._update_status_bar("⚠️ No active incident.")
            return

        current_data_type = "spot" if "Spot" in self.data_type_combo.currentText() else "area"
        dialog = ObjectiveDialog(self, self.active_incident_path, zone_name=zone_name, data_type=current_data_type)
        dialog.exec()

    @Slot()
    def _on_report_hotzone(self):
        self._launch_objective_dialog("Hotzone")

    @Slot()
    def _on_report_warmzone(self):
        self._launch_objective_dialog("Warmzone")

    @Slot()
    def _on_report_fireground(self):
        self._launch_objective_dialog("Fireground")

    @Slot()
    def _on_report_community(self):
        self._launch_objective_dialog("Community")

    @Slot()
    def _on_report_publish(self):
        if not self.active_incident_path:
            self._update_status_bar("⚠️ No active incident.")
            return

        try:
            from report_generator import generate_pdf_report
            self._update_status_bar("⏳ Generating PDF report...")
            QApplication.processEvents()

            pdf_path = generate_pdf_report(self.active_incident_path, self)
            if pdf_path:
                QMessageBox.information(self, "Report Published", f"PDF report successfully generated at:\n\n{pdf_path}")
                self._update_status_bar("✅ PDF report generated.")
            else:
                self._update_status_bar("⚠️ PDF report generation cancelled.")
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to generate PDF report:\n{e}")
            self._update_status_bar("❌ Failed to generate PDF report.")

    @Slot()
    def _on_new_incident(self):
        dialog = IncidentDialog(self)
        if dialog.exec() == QDialog.Accepted:
            incident_data = dialog.get_data()
            self.set_active_incident(incident_data)
            self._update_status_bar(f"📂 New incident '{self.active_label}'.")

    @Slot()
    def _on_open_incident(self):
        dialog = OpenIncidentDialog(self)
        if dialog.exec() == QDialog.Accepted:
            incident_data = dialog.get_data()
            if incident_data:
                self.set_active_incident(incident_data)
                self._update_status_bar(f"📂 Opened incident '{self.active_label}'.")

    @Slot()
    def _on_edit_incident(self):
        dialog = IncidentDialog(self, incident_data=self._active_incident)
        if dialog.exec() == QDialog.Accepted:
            self._update_status_bar(f"✅ Incident '{self.active_label}' updated.")

    @Slot()
    def _on_map_spot(self):
        if not self.active_incident_path:
            return
        dialog = MapEditorDialog(self, self.active_incident_path, mode="spot")
        if dialog.exec() == QDialog.Accepted:
            self._refresh_overview()
            if self.data_type == "spot":
                self._on_data_type_changed("Spot Readings")

    @Slot()
    def _on_map_area(self):
        if not self.active_incident_path:
            return
        dialog = MapEditorDialog(self, self.active_incident_path, mode="area")
        if dialog.exec() == QDialog.Accepted:
            self._refresh_overview()
            if self.data_type == "area":
                self._on_data_type_changed("Area Readings")

    @Slot()
    def _on_map_spectral(self):
        if not self.active_incident_path:
            return
        dialog = MapEditorDialog(self, self.active_incident_path, mode="spectral")
        if dialog.exec() == QDialog.Accepted:
            self._update_status_bar("💾 Spectral map saved.")

    @Slot()
    def _on_spot_readings(self):
        if not self.active_incident_path:
            return
        dialog = SpotReadingsDialog(self, self.active_incident_path)
        if dialog.exec() == QDialog.Accepted:
            self._update_status_bar("💾 Spot readings saved.")
            self._refresh_overview()
            if self.data_type == "spot":
                self._on_data_type_changed("Spot Readings")

    @Slot()
    def _on_spectral_results(self):
        if not self.active_incident_path:
            return
        dialog = SpectralResultsDialog(self, self.active_incident_path)
        if dialog.exec() == QDialog.Accepted:
            self._update_status_bar("💾 Spectral records saved.")
            if self.data_type == "spectral":
                self._on_data_type_changed("Spectral Results")

    @Slot()
    def _on_device_locations(self):
        if not self.active_incident_path:
            return
        dialog = DeviceLocationsDialog(self, self.active_incident_path)
        if dialog.exec() == QDialog.Accepted:
            self._refresh_overview()
            if self.data_type == "area":
                self._on_data_type_changed("Area Readings")

    @Slot()
    def _on_device_validations(self):
        if not self.active_incident_path:
            return
        DeviceValidationsDialog(self, self.active_incident_path).exec()

    @Slot()
    def _on_battery_analysis(self):
        if not self.active_incident_path:
            return
        BatteryAnalysisDialog(self, self.active_incident_path).exec()

    @Slot()
    def _on_import_area(self):
        if not self.active_incident_path:
            self._update_status_bar("⚠️ No active incident.")
            return

        files, _ = QFileDialog.getOpenFileNames(
            self, "Select Area Data CSV Files", "",
            "CSV Files (*.csv);;All Files (*)"
        )
        if not files:
            self._update_status_bar("Import Area Data cancelled.")
            return

        self.copy_progress = QProgressDialog("Copying files to realtime directory...", None, 0, 0, self)
        self.copy_progress.setWindowTitle("Copying Files")
        self.copy_progress.setWindowModality(Qt.WindowModal)
        self.copy_progress.setMinimumDuration(0)
        self.copy_progress.setValue(0)
        self.copy_progress.setCancelButton(None)
        self.copy_progress.show()

        self.copy_thread = QThread()
        self.copy_worker = CopyWorker(self.active_incident_path, files)
        self.copy_worker.moveToThread(self.copy_thread)
        self.copy_thread.started.connect(self.copy_worker.do_work)
        self.copy_worker.finished.connect(self._on_copy_finished)
        self.copy_worker.error.connect(self._on_copy_error)
        self.copy_worker.finished.connect(self.copy_worker.deleteLater)
        self.copy_worker.error.connect(self.copy_worker.deleteLater)
        self.copy_thread.finished.connect(self.copy_thread.deleteLater)
        self.copy_thread.start()

    @Slot(int)
    def _on_copy_finished(self, copied_count):
        if hasattr(self, 'copy_progress') and self.copy_progress:
            self.copy_progress.close()
            self.copy_progress.deleteLater()
            self.copy_progress = None

        if hasattr(self, 'copy_thread') and self.copy_thread:
            self.copy_thread.quit()
            self.copy_thread.wait()

        QApplication.processEvents()
        QMessageBox.information(self, "Copy Complete", f"Successfully copied {copied_count} file(s) to the realtime directory.")
        self._update_status_bar(f"📂 Copied {copied_count} file(s) to data/realtime.")
        self._start_processing()

    def _start_processing(self):
        try:
            self._update_status_bar("⏳ Processing area data...")
            self.process_progress = QProgressDialog("Processing area data...", None, 0, 0, self)
            self.process_progress.setWindowTitle("Processing Data")
            self.process_progress.setWindowModality(Qt.WindowModal)
            self.process_progress.setMinimumDuration(0)
            self.process_progress.setValue(0)
            self.process_progress.setCancelButton(None)
            self.process_progress.show()

            self.process_thread = QThread()
            self.process_worker = ProcessWorker(self.active_incident_path)
            self.process_worker.moveToThread(self.process_thread)
            self.process_thread.started.connect(self.process_worker.do_work)
            self.process_worker.finished.connect(self._on_import_finished)
            self.process_worker.error.connect(self._on_import_error)
            self.process_worker.finished.connect(self.process_worker.deleteLater)
            self.process_worker.error.connect(self.process_worker.deleteLater)
            self.process_thread.finished.connect(self.process_thread.deleteLater)
            self.process_thread.start()
        except Exception as e:
            logger.error(f"Setup error: {e}")
            QMessageBox.critical(self, "Error", f"Failed to start processing:\n{e}")
            self._update_status_bar("❌ Error starting processing.")
            self._cleanup_process_progress()

    def _cleanup_process_progress(self):
        if hasattr(self, 'process_progress') and self.process_progress:
            self.process_progress.close()
            self.process_progress.deleteLater()
            self.process_progress = None

    @Slot(str)
    def _on_import_finished(self, result_path):
        if hasattr(self, 'process_progress') and self.process_progress:
            self.process_progress.close()
            self.process_progress.deleteLater()
            self.process_progress = None

        if hasattr(self, 'process_thread') and self.process_thread:
            self.process_thread.quit()
            self.process_thread.wait()

        QApplication.processEvents()

        if result_path and os.path.exists(result_path):
            try:
                with open(result_path, 'r', encoding='utf-8') as f:
                    row_count = sum(1 for _ in f) - 1
            except Exception:
                row_count = "unknown"

            realtime_dir = os.path.join(self.active_incident_path, "data", "realtime")
            file_count = len(glob.glob(os.path.join(realtime_dir, "*.csv")))

            QMessageBox.information(
                self, "Processing Complete",
                f"Area data successfully processed!\n\nFiles in realtime directory: {file_count}\nTotal rows in processed data: {row_count}"
            )
            self._update_status_bar(f"✅ Area data processed ({row_count} rows).")
            self._refresh_overview()
            if self.data_type == "area":
                self._on_data_type_changed("Area Readings")
        else:
            QMessageBox.warning(self, "Processing Issue", "No data was processed. Check if CSV files were valid.")
            self._update_status_bar("⚠️ No data processed.")

    @Slot(str)
    def _on_copy_error(self, error_msg):
        QMessageBox.critical(self, "Copy Error", f"Failed:\n{error_msg}")

    @Slot(str)
    def _on_import_error(self, error_msg):
        if hasattr(self, 'process_progress') and self.process_progress:
            self.process_progress.cancel()
            self.process_progress.close()
            self.process_progress.deleteLater()
            self.process_progress = None

        QApplication.processEvents()
        QMessageBox.critical(self, "Processing Error", f"Failed:\n{error_msg}")

    def closeEvent(self, event):
        for thread_attr in ['process_thread', 'copy_thread']:
            if hasattr(self, thread_attr):
                thread = getattr(self, thread_attr)
                if thread:
                    try:
                        if thread.isRunning():
                            thread.quit()
                            thread.wait(2000)
                    except RuntimeError:
                        pass
        super().closeEvent(event)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)-8s| %(message)s")
    app = QApplication(sys.argv)
    window = DataAnalyzerGUI()
    window.show()
    sys.exit(app.exec())
