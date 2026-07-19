import os
import sys
import shutil
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

# ─────────────────────────────────────────────────────────
# CRITICAL: Add parent directory to sys.path BEFORE local imports
# ─────────────────────────────────────────────────────────
current_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.dirname(current_dir)
if parent_dir not in sys.path:
    sys.path.insert(0, parent_dir)

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
from thresholds_dialog import ThresholdsDialog
from datamanagement.filtering import filter_data, aggregate_data

# Importer workers
from datamanagement.importer import copy_files_to_realtime, import_area_data
from datamanagement.updater import update_site_from_device_log, update_validations

# Reader and Locations
from datamanagement.reader import read_area_data, read_spot_data, read_spectral_data, read_exposure_data
from datamanagement.locations import LocationManager

# Import shared metadata helpers
from datamanagement.choices import get_available_devices, get_available_locations

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────
# VIEW CONSTRAINTS (Single source of truth for UI rules)
# ─────────────────────────────────────────────────────────
VIEW_CONSTRAINTS = {
    "spot":     { "enabled": [0, 1, 2, 3, 4, 5],  "default": 0},
    "area":     { "enabled": [0, 1, 2, 3, 4, 5],  "default": 0},
    "spectral": { "enabled": [0, 1],              "default": 0},
    "exposure": { "enabled": [3, 4],              "default": 3},
    "plume":    { "enabled": [5],                 "default": 5}
}

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
            result = import_area_data(self.incident_path)
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
        self.exposure_filters = {}
        
        self._spot_threshold_level = None
        self._area_threshold_level = None
        self._spectral_threshold_level = None
        self._exposure_threshold_level = None
        
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
        self.spectral_data = None
        self.exposure_data = None
        self.plume_data = []
        
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
            
            if not self._views_initialized:
                self._views_initialized = True
                
            # ── FIX: Use _load_view(0) to create and display the Overview ──
            self._load_view(0)
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
            self.action_publish, self.action_map_spectral, self.action_spectral_results,
            self.action_exposures, self.action_import_plumes, self.action_delete_plumes
        ]
        for action in actions:
            action.setEnabled(has_incident)
            
        controls = [self.data_type_combo, self.btn_filters, self.btn_global_export, self.filter_summary_group]
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
        self.data_type_combo.addItems(["Spot Readings", "Area Readings", "Spectral Results", "Exposures", "Plume"])
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
                QPushButton:disabled { background-color: #f3f4f6; color: #9ca3af; }
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
        
        # ── NEW: Global Export Button ──
        self.btn_global_export = QPushButton("Export Current View")
        self.btn_global_export.setMinimumHeight(45)
        self.btn_global_export.setCursor(Qt.PointingHandCursor)
        self.btn_global_export.setStyleSheet("""
            QPushButton { 
                text-align: center; border: none; border-radius: 6px; 
                font-size: 14px; color: white; background-color: #3b82f6; font-weight: bold;  
            }
            QPushButton:hover { background-color: #2563eb; }
        """)
        self.btn_global_export.clicked.connect(self._export_current_view)
        dock_layout.addWidget(self.btn_global_export)
        
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
        
        exposure_menu = menubar.addMenu("E&xposure Records")
        self.action_exposures = exposure_menu.addAction("&Exposures...", self._on_exposures)
        
        plumes_menu = menubar.addMenu("&Plumes")
        self.action_import_plumes = plumes_menu.addAction("&Import...", self._on_import_plumes)
        self.action_delete_plumes = plumes_menu.addAction("&Delete...", self._on_delete_plumes)
        
        reports_menu = menubar.addMenu("&Reports")
        self.action_hotzone = reports_menu.addAction("&Hotzone", self._on_report_hotzone)
        self.action_warmzone = reports_menu.addAction("&Warmzone", self._on_report_warmzone)
        self.action_fireground = reports_menu.addAction("&Fireground", self._on_report_fireground)
        self.action_community = reports_menu.addAction("&Community", self._on_report_community)
        reports_menu.addSeparator()
        self.action_thresholds = reports_menu.addAction("&Thresholds...", self._on_manage_thresholds)
        reports_menu.addSeparator()
        self.action_clear_objectives = reports_menu.addAction("Clear &Objectives...", self._on_clear_objectives)
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
    # DYNAMIC VIEW ENGINE (Lazy Load & Destroy)
    # ─────────────────────────────────────────────────────────
    def _clear_current_view(self):
        """Safely removes and destroys the currently active view in the stack."""
        while self.view_stack.count() > 0:
            w = self.view_stack.widget(0)
            self.view_stack.removeWidget(w)
            w.deleteLater()

    def _load_view(self, index):
        """Instantiates the requested view, feeds it current data, and displays it."""
        self._clear_current_view()
        
        if index == 0:
            view = OverviewView(analyte_dec_pls=self.analyte_dec_pls, parent=self)
            view.update_data(self.area_data, self.spot_data, self.spectral_data, self.exposure_data)
            
        elif index == 1:
            view = TableView(analyte_dec_pls=self.analyte_dec_pls, parent=self)
            view.btn_prev_page.clicked.connect(self._on_prev_page)
            view.btn_next_page.clicked.connect(self._on_next_page)
            
            if self.data_type == "spectral":
                view.set_data(self.filtered_data, show_invalid_bg=False, active_thresholds={})
            elif self.filtered_data is not None:
                only_valid = self.filter_summary.get("only_valid", False) if self.filter_summary else False
                view.set_data(self.filtered_data, show_invalid_bg=not only_valid, active_thresholds=self._get_active_thresholds())
                
        elif index == 2:
            view = ChartView(parent=self)
            if self.data_type not in ["spectral", "exposure", "plume"] and self.filtered_data is not None:
                view.plot_data(self.filtered_data, self.filter_summary, self.available_analytes, self._get_active_thresholds)
                
        elif index == 3:
            view = SummaryTableView(analyte_dec_pls=self.analyte_dec_pls, parent=self)
            if self.filtered_data is not None:
                view.update_data(self.filtered_data, self.filter_summary, self.available_analytes, self._get_active_thresholds)
                
        elif index == 4:
            view = SummaryChartView(parent=self)
            if self.filtered_data is not None:
                # SummaryChartView relies on SummaryTableView's output. 
                # We calculate it on-the-fly without adding the table to the UI.
                temp_table = SummaryTableView(analyte_dec_pls=self.analyte_dec_pls)
                temp_table.update_data(self.filtered_data, self.filter_summary, self.available_analytes, self._get_active_thresholds)
                summary_data = temp_table.get_summary_data()
                view.update_data(summary_data, self.filter_summary, self._get_active_thresholds())
                
        elif index == 5:
            view = SummaryMapView(
                map_filenames=self.map_filenames,
                available_analytes=self.available_analytes,
                analyte_dec_pls=self.analyte_dec_pls,
                mapping_dir=self.mapping_dir,
                maps_data=self.maps_data,
                parent=self
            )
            if self.data_type == "plume":
                view.show_plume_animation(self.plume_data)
            elif self.filtered_data is not None:
                view.update_data(self.filtered_data)
                
        self.view_stack.addWidget(view)
        self.view_stack.setCurrentIndex(0) # Stack only ever holds 1 widget at a time

    def _initialize_data_views(self, target_index=0):
        """Kept for compatibility. Clears stack and loads the target view."""
        self._load_view(target_index)
        self.nav_btns[target_index].setChecked(True)

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
        elif self.data_type == "exposure":
            self.exposure_filters = self.filter_summary.copy() if self.filter_summary else {}
            self._exposure_threshold_level = self._selected_threshold_level
            
        if "Spectral" in text: new_data_type = "spectral"
        elif "Spot" in text: new_data_type = "spot"
        elif "Exposures" in text: new_data_type = "exposure"
        elif "Plume" in text: new_data_type = "plume"
        else: new_data_type = "area"
        
        self.data_type = new_data_type
        
        # Restore state
        if self.data_type == "spot":
            self.filter_summary = self.spot_filters.copy() if self.spot_filters else {}
            self._selected_threshold_level = self._spot_threshold_level
        elif self.data_type == "area":
            self.filter_summary = self.area_filters.copy() if self.area_filters else {}
            self._selected_threshold_level = self._area_threshold_level
        elif self.data_type == "spectral":
            self.filter_summary = self.spectral_filters.copy() if self.spectral_filters else {}
            self._selected_threshold_level = self._spectral_threshold_level
        elif self.data_type == "exposure":
            self.filter_summary = self.exposure_filters.copy() if self.exposure_filters else {}
            self._selected_threshold_level = self._exposure_threshold_level
            
        constraints = VIEW_CONSTRAINTS.get(self.data_type, VIEW_CONSTRAINTS["area"])
        enabled_indices = constraints["enabled"]
        default_idx = constraints["default"]
        
        for idx, btn in self.nav_btns.items():
            btn.setEnabled(idx in enabled_indices)
            
        # Determine which view to load
        current_btn_idx = next((idx for idx, btn in self.nav_btns.items() if btn.isChecked()), 0)
        target_idx = current_btn_idx if current_btn_idx in enabled_indices else default_idx
        self.nav_btns[target_idx].setChecked(True)
        
        progress = QProgressDialog("Loading data...", None, 0, 0, self)
        progress.setWindowTitle("Loading")
        progress.setWindowModality(Qt.WindowModal)
        progress.setCancelButton(None)
        progress.show()
        QApplication.processEvents()
        
        try:
            self._load_thresholds()
            QApplication.processEvents()
            
            if self.data_type == "spot": self._load_spot_data()
            elif self.data_type == "area": self._load_area_data()
            elif self.data_type == "spectral": self._load_spectral_data()
            elif self.data_type == "plume": self._load_plume_data()
            
            QApplication.processEvents()
            if self.data_type not in ["spectral", "exposure", "plume"]:
                self._load_map_data()
            QApplication.processEvents()
            
            if not self._views_initialized or self._last_data_type != self.data_type:
                self._initialize_data_views(target_idx)
                self._views_initialized = True
                self._refresh_overview()
                
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
                            try: self.analyte_dec_pls[name] = int(dec_pls)
                            except (ValueError, TypeError): self.analyte_dec_pls[name] = 2
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
                                try: entry[key] = float(str(raw).strip())
                                except (ValueError, TypeError): entry[key] = 0.0
                            self.thresholds_lookup[analyte_name.upper()] = entry
            except Exception as e:
                logger.error(f"Failed to load thresholds: {e}")

    def _load_spot_data(self):
        self.raw_data = read_spot_data(self.active_incident_path)
        self._extract_metadata_from_df()

    def _load_area_data(self):
        self.raw_data = read_area_data(self.active_incident_path)
        self._extract_metadata_from_df()

    def _load_spectral_data(self):
        self.raw_data = read_spectral_data(self.active_incident_path)
        self._extract_metadata_from_df()

    def _load_plume_data(self):
        import datetime
        plumes_dir = os.path.join(self.active_incident_path, "plumes")
        self.all_plume_data = []
        if os.path.exists(plumes_dir):
            for f in os.listdir(plumes_dir):
                if f.lower().endswith(".png"):
                    try:
                        dt_str = os.path.splitext(f)[0]
                        # 1. Parse filename as UTC
                        dt_utc = datetime.datetime.strptime(dt_str, "%Y%m%d%H%M")
                        # 2. Convert to local time and remove tzinfo (naive) 
                        #    to match how QDateTimeEdit.toPython() behaves
                        dt_local = dt_utc.replace(tzinfo=datetime.timezone.utc).astimezone().replace(tzinfo=None)
                        self.all_plume_data.append((dt_local, os.path.join(plumes_dir, f)))
                    except ValueError:
                        continue
        self.all_plume_data.sort(key=lambda x: x[0])
        # Initialize filtered plume data to show all by default
        self.plume_data = self.all_plume_data.copy()

    def _load_overview_data(self):
        self.area_data = read_area_data(self.active_incident_path)
        self.spot_data = read_spot_data(self.active_incident_path)
        self.exposure_data = read_exposure_data(self.active_incident_path)
        self.spectral_data = read_spectral_data(self.active_incident_path)

    def _load_map_data(self):
        self.mapping_dir = os.path.join(self.active_incident_path, "mapping")
        manager = LocationManager(self.active_incident_path, mode=self.data_type)
        self.maps_data = manager.get_maps_data()
        self.map_filenames = list(self.maps_data.keys())

    def _extract_metadata_from_df(self):
        self.available_locations = get_available_locations(self.active_incident_path, self.data_type)
        self.available_devices = get_available_devices(self.active_incident_path, self.data_type)

    def _process_exposure_data(self):
        exposure_df = read_exposure_data(self.active_incident_path)
        if exposure_df.empty:
            self.filtered_data = pd.DataFrame()
            self._update_all_views()
            return
            
        self.filtered_data = filter_data(
            df=exposure_df,
            start_dt=self.filter_summary.get('start_time'),
            stop_dt=self.filter_summary.get('stop_time'),
            selected_sites=self.filter_summary.get('selected_sites', []),
            selected_devices=self.filter_summary.get('selected_devices', []),
            selected_analytes=self.filter_summary.get('selected_analytes', []),
            only_valid=False,
            group_by='Device',
            data_type="exposure"
        )
        if self.filtered_data is not None and not self.filtered_data.empty and 'LOG TIME' in self.filtered_data.columns:
            self.filtered_data = self.filtered_data.sort_values(by='LOG TIME')
        self._update_all_views()

    def _apply_initial_filters(self):
        if self.data_type == "plume":
            # Initialize filter summary for plumes if not set
            if not self.filter_summary or self.filter_summary.get("data_type") != "plume":
                if self.all_plume_data:
                    data_start = min(dt for dt, _ in self.all_plume_data)
                    data_stop = max(dt for dt, _ in self.all_plume_data)
                else:
                    data_start = pd.Timestamp.now()
                    data_stop = pd.Timestamp.now()
                self.filter_summary = {
                    "start_time": data_start,
                    "stop_time": data_stop,
                    "data_type": "plume"
                }
            else:
                # Apply existing filter summary to the master list
                start_dt = self.filter_summary.get('start_time')
                stop_dt = self.filter_summary.get('stop_time')
                if start_dt and stop_dt:
                    self.plume_data = [
                        (dt, path) for dt, path in self.all_plume_data
                        if start_dt <= dt <= stop_dt
                    ]
                else:
                    self.plume_data = self.all_plume_data.copy()
                    
            self._update_all_views()
            self._update_filter_summary_labels()
            return
            
        if self.data_type == "exposure":
            exposure_df = read_exposure_data(self.active_incident_path)
            self.raw_data = exposure_df
            if not exposure_df.empty and 'LOG TIME' in exposure_df.columns:
                data_start = exposure_df['LOG TIME'].min()
                data_stop = exposure_df['LOG TIME'].max()
            else:
                data_start = pd.Timestamp.now()
                data_stop = pd.Timestamp.now()
                
            if not self.filter_summary:
                self.filter_summary = {
                    "start_time": data_start, "stop_time": data_stop, "interval": "Raw",
                    "group_by": "Device", "only_valid": False,
                    "selected_sites": exposure_df['SITE'].dropna().unique().tolist() if 'SITE' in exposure_df.columns else [],
                    "selected_devices": exposure_df['DEVICE'].dropna().unique().tolist() if 'DEVICE' in exposure_df.columns else [],
                    "selected_analytes": list(self.available_analytes), "threshold_level": None, "data_type": "exposure"
                }
            else:
                self.filter_summary["data_type"] = "exposure"
                if 'DEVICE' in exposure_df.columns:
                    valid_devs = exposure_df['DEVICE'].dropna().unique().tolist()
                    old_devices = self.filter_summary.get('selected_devices', [])
                    valid_devices = [d for d in old_devices if d in valid_devs]
                    self.filter_summary['selected_devices'] = valid_devices if valid_devices else valid_devs
                else: self.filter_summary['selected_devices'] = []
                
                if 'SITE' in exposure_df.columns:
                    valid_sites = exposure_df['SITE'].dropna().unique().tolist()
                    old_sites = self.filter_summary.get('selected_sites', [])
                    valid_sites_list = [s for s in old_sites if s in valid_sites]
                    self.filter_summary['selected_sites'] = valid_sites_list if valid_sites_list else valid_sites
                else: self.filter_summary['selected_sites'] = []
                
                old_analytes = self.filter_summary.get('selected_analytes', [])
                valid_analytes = [g for g in old_analytes if g in self.available_analytes]
                self.filter_summary['selected_analytes'] = valid_analytes if valid_analytes else list(self.available_analytes)
                
            self.exposure_filters = self.filter_summary.copy()
            self._exposure_threshold_level = self._selected_threshold_level
            self._process_exposure_data()
            return

        # ── STANDARD HANDLING FOR SPOT, AREA, SPECTRAL ──
        if self.raw_data is None or self.raw_data.empty:
            self._load_overview_data()
            # ── FIX: Route through _refresh_overview() to respect the ephemeral architecture ──
            self._refresh_overview()
            return
            
        df = self.raw_data.copy()
        if 'LOG TIME' in df.columns and not df['LOG TIME'].dropna().empty:
            data_start = df['LOG TIME'].min()
            data_stop = df['LOG TIME'].max()
        else:
            data_start = pd.Timestamp.now()
            data_stop = pd.Timestamp.now()
            
        if not self.filter_summary:
            self.filter_summary = {
                "start_time": data_start, "stop_time": data_stop, "interval": "Raw",
                "group_by": "Device", "only_valid": False,
                "selected_sites": ["Unassigned"] + list(self.available_locations),
                "selected_devices": list(self.available_devices),
                "selected_analytes": list(self.available_analytes), "threshold_level": None
            }
        else:
            old_sites = self.filter_summary.get('selected_sites', [])
            valid_sites = [s for s in old_sites if s in self.available_locations or s == 'Unassigned']
            self.filter_summary['selected_sites'] = valid_sites if valid_sites else (["Unassigned"] + list(self.available_locations))
            old_devices = self.filter_summary.get('selected_devices', [])
            valid_devices = [d for d in old_devices if d in self.available_devices]
            self.filter_summary['selected_devices'] = valid_devices if valid_devices else list(self.available_devices)
            old_analytes = self.filter_summary.get('selected_analytes', [])
            valid_analytes = [g for g in old_analytes if g in self.available_analytes]
            self.filter_summary['selected_analytes'] = valid_analytes if valid_analytes else list(self.available_analytes)
            
        if self.data_type == "spot":
            self.spot_filters = self.filter_summary.copy()
            self._spot_threshold_level = self._selected_threshold_level
        elif self.data_type == "area":
            self.area_filters = self.filter_summary.copy()
            self._area_threshold_level = self._selected_threshold_level
        elif self.data_type == "spectral":
            self.spectral_filters = self.filter_summary.copy()
            self._spectral_threshold_level = self._selected_threshold_level
            
        self.filtered_data = filter_data(
            df=self.raw_data,
            start_dt=self.filter_summary['start_time'], stop_dt=self.filter_summary['stop_time'],
            selected_sites=self.filter_summary['selected_sites'], selected_devices=self.filter_summary['selected_devices'],
            selected_analytes=self.filter_summary['selected_analytes'], only_valid=self.filter_summary['only_valid'],
            group_by=self.filter_summary['group_by'], data_type=self.data_type
        )
        
        if self.filtered_data is not None and not self.filtered_data.empty:
            if 'LOG TIME' in self.filtered_data.columns:
                self.filtered_data = self.filtered_data.sort_values(by='LOG TIME')
            interval = self.filter_summary.get("interval", "Raw")
            group_by = self.filter_summary.get("group_by", "Device")
            if interval != "Raw":
                start = self.filter_summary['start_time']
                stop = self.filter_summary['stop_time']
                self.filtered_data = aggregate_data(df=self.filtered_data, interval=interval, group_by=group_by, start_dt=start, stop_dt=stop)
                if group_by == "Device" and "SITE" in self.filtered_data.columns:
                    self.filtered_data = self.filtered_data.drop(columns=["SITE"])
                elif group_by == "Site" and "DEVICE" in self.filtered_data.columns:
                    self.filtered_data = self.filtered_data.drop(columns=["DEVICE"])
            self.filtered_data = self._reorder_columns(self.filtered_data)
            
        self._update_all_views()

    def _update_all_views(self):
        """Refreshes ONLY the currently active view in the stack."""
        current_widget = self.view_stack.currentWidget()
        if not current_widget:
            return
            
        if self.data_type == "plume":
            if isinstance(current_widget, SummaryMapView):
                current_widget.show_plume_animation(self.plume_data)
            self._update_filter_summary_labels()
            return
            
        if self.filtered_data is None:
            return
            
        if isinstance(current_widget, OverviewView):
            current_widget.update_data(self.area_data, self.spot_data, self.spectral_data, self.exposure_data)
            
        elif isinstance(current_widget, TableView):
            if self.data_type == "spectral":
                current_widget.set_data(self.filtered_data, show_invalid_bg=False, active_thresholds={})
            else:
                only_valid = self.filter_summary.get("only_valid", False) if self.filter_summary else False
                current_widget.set_data(self.filtered_data, show_invalid_bg=not only_valid, active_thresholds=self._get_active_thresholds())
                
        elif isinstance(current_widget, ChartView):
            if self.data_type not in ["spectral", "exposure", "plume"]:
                current_widget.plot_data(self.filtered_data, self.filter_summary, self.available_analytes, self._get_active_thresholds)
                
        elif isinstance(current_widget, SummaryTableView):
            current_widget.update_data(self.filtered_data, self.filter_summary, self.available_analytes, self._get_active_thresholds)
            
        elif isinstance(current_widget, SummaryChartView):
            temp_table = SummaryTableView(analyte_dec_pls=self.analyte_dec_pls)
            temp_table.update_data(self.filtered_data, self.filter_summary, self.available_analytes, self._get_active_thresholds)
            summary_data = temp_table.get_summary_data()
            current_widget.update_data(summary_data, self.filter_summary, self._get_active_thresholds())
            
        elif isinstance(current_widget, SummaryMapView):
            current_widget.update_data(self.filtered_data)
            
        self._update_filter_summary_labels()

    def _get_active_thresholds(self):
        if not self._selected_threshold_level: return {}
        result = {}
        for analyte in self.available_analytes:
            analyte_upper = analyte.upper()
            if analyte_upper in self.thresholds_lookup:
                val = self.thresholds_lookup[analyte_upper].get(self._selected_threshold_level)
                if val is not None: result[analyte] = val
        return result

    def _reorder_columns(self, df):
        if df is None or df.empty: return df
        ordered = []
        for col in ['LOG TIME', 'SITE', 'DEVICE', 'observations']:
            if col in df.columns: ordered.append(col)
        for analyte in self.available_analytes:
            if analyte in df.columns and analyte not in ordered: ordered.append(analyte)
        for col in df.columns:
            if col.upper().startswith('INVALID_') and col not in ordered: ordered.append(col)
        for col in df.columns:
            if col not in ordered: ordered.append(col)
        return df[ordered]

    # ─────────────────────────────────────────────────────────
    # FILTERING & NAVIGATION
    # ─────────────────────────────────────────────────────────
    @Slot(int)
    def _on_nav_clicked(self, index):
        constraints = VIEW_CONSTRAINTS.get(self.data_type, VIEW_CONSTRAINTS["area"])
        if index not in constraints["enabled"]:
            index = constraints["default"]
            self.nav_btns[index].setChecked(True)
            
        # Dynamically load the requested view and destroy the old one
        self._load_view(index)

    def _export_current_view(self):
        """Triggers the export method on whichever view is currently active."""
        current_widget = self.view_stack.currentWidget()
        if current_widget and hasattr(current_widget, 'export') and callable(current_widget.export):
            current_widget.export()
        else:
            QMessageBox.information(self, "Export", "The current view does not support exporting.")

    def _open_filter_dialog(self):
        # ── 1. Handle Plume Filtering ──
        if self.data_type == "plume":
            if not hasattr(self, 'all_plume_data') or not self.all_plume_data:
                QMessageBox.warning(self, "No Data", "No plume images available to filter.")
                return
                
            dialog = FilterDialog(
                parent=self, 
                incident_path=self.active_incident_path,
                initial_filters=self.filter_summary, 
                data_type="plume",
                plume_data=self.all_plume_data
            )
            if dialog.exec() == QDialog.Accepted:
                new_filters = dialog.get_filters()
                self.filter_summary = new_filters
                start_dt = new_filters['start_time']
                stop_dt = new_filters['stop_time']
                
                # Filter the master list down to the selected time window
                self.plume_data = [
                    (dt, path) for dt, path in self.all_plume_data
                    if start_dt <= dt <= stop_dt
                ]
                self._update_all_views()
                self._update_filter_summary_labels()
            return

        # ── 2. Handle Exposure Filtering ──
        if self.data_type == "exposure":
            exposure_df = read_exposure_data(self.active_incident_path)
            self.raw_data = exposure_df
            if exposure_df.empty:
                QMessageBox.warning(self, "No Data", "No exposure data available.")
                return
            raw_data_for_dialog = exposure_df
            
        # ── 3. Handle Spot, Area, Spectral ──
        else:
            if self.raw_data is None or self.raw_data.empty:
                QMessageBox.warning(self, "No Data", "No data loaded to filter.")
                return
            raw_data_for_dialog = self.raw_data

        dialog = FilterDialog(
            parent=self, incident_path=self.active_incident_path, raw_data=raw_data_for_dialog,
            analyte_dec_pls=self.analyte_dec_pls, thresholds_lookup=self.thresholds_lookup,
            initial_filters=self.filter_summary, data_type=self.data_type
        )
        
        if dialog.exec() == QDialog.Accepted:
            new_filters = dialog.get_filters()
            if self.data_type == "exposure":
                self.filter_summary = new_filters
                self.exposure_filters = self.filter_summary.copy()
                self._exposure_threshold_level = self._selected_threshold_level = new_filters['threshold_level']
                self.thresholds_lookup = dialog.thresholds_lookup
                self._process_exposure_data()
                self._update_filter_summary_labels()
                return
                
            self.filtered_data = filter_data(
                df=self.raw_data, start_dt=new_filters['start_time'], stop_dt=new_filters['stop_time'],
                selected_sites=new_filters['selected_sites'], selected_devices=new_filters['selected_devices'],
                selected_analytes=new_filters['selected_analytes'], only_valid=new_filters['only_valid'],
                group_by=new_filters['group_by'], data_type=self.data_type
            )
            
            if self.filtered_data is not None and not self.filtered_data.empty:
                if 'LOG TIME' in self.filtered_data.columns:
                    self.filtered_data = self.filtered_data.sort_values(by='LOG TIME')
                interval = new_filters.get("interval", "Raw")
                group_by = new_filters.get("group_by", "Device")
                if interval != "Raw":
                    start = new_filters['start_time']
                    stop = new_filters['stop_time']
                    self.filtered_data = aggregate_data(df=self.filtered_data, interval=interval, group_by=group_by, start_dt=start, stop_dt=stop)
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
        if self.data_type == "plume":
            count = len(self.plume_data) if hasattr(self, 'plume_data') else 0
            start_t = self.filter_summary.get('start_time', '--')
            stop_t = self.filter_summary.get('stop_time', '--')
            if hasattr(start_t, 'strftime'): start_t = start_t.strftime("%Y-%m-%d %H:%M")
            if hasattr(stop_t, 'strftime'): stop_t = stop_t.strftime("%Y-%m-%d %H:%M")
            
            texts = [
                f"Time: {start_t} to {stop_t}",
                "Interval: 3s",
                "Group: N/A",
                f"Files: {count}",
                "Devices: N/A",
                "Analytes: N/A"
            ]
            for lbl, text in zip(self.filter_labels, texts): 
                lbl.setText(text)
            return
            
        summary = self.filter_summary
        if not summary:
            texts = ["Time: --", "Interval: --", "Group: --", "Sites: --", "Devices: --", "Analytes: --"]
            for lbl, text in zip(self.filter_labels, texts): lbl.setText(text)
            return
            
        start_t = summary.get('start_time', '--')
        stop_t = summary.get('stop_time', '--')
        if hasattr(start_t, 'strftime'): start_t = start_t.strftime("%Y-%m-%d %H:%M")
        if hasattr(stop_t, 'strftime'): stop_t = stop_t.strftime("%Y-%m-%d %H:%M")
        
        interval_text = summary.get('interval', '--')
        if self.data_type in ["spectral", "exposure"]: interval_text = "Raw (N/A)"
        
        analytes_count = len(summary.get('selected_analytes', []))
        analytes_text = "N/A" if self.data_type == "spectral" else str(analytes_count)
        
        is_exposure = self.data_type == "exposure"
        site_label = "Areas" if is_exposure else "Sites"
        device_label = "Identifiers" if is_exposure else "Devices"
        
        texts = [
            f"Time: {start_t} to {stop_t}", f"Interval: {interval_text}",
            f"Group: {summary.get('group_by', '--')}", f"{site_label}: {len(summary.get('selected_sites', []))}",
            f"{device_label}: {len(summary.get('selected_devices', []))}", f"Analytes: {analytes_text}"
        ]
        for lbl, text in zip(self.filter_labels, texts): lbl.setText(text)

    @Slot()
    def _on_prev_page(self):
        current_widget = self.view_stack.currentWidget()
        if isinstance(current_widget, TableView):
            if current_widget.model.prev_page():
                current_widget._update_table()

    @Slot()
    def _on_next_page(self):
        current_widget = self.view_stack.currentWidget()
        if isinstance(current_widget, TableView):
            if current_widget.model.next_page():
                current_widget._update_table()

    def _refresh_overview(self):
        if not self.active_incident_path:
            return
            
        self._load_analytes_config()
        self._load_overview_data()
        
        # ── FIX: Check the active widget in the stack ──
        current_widget = self.view_stack.currentWidget()
        if isinstance(current_widget, OverviewView):
            current_widget.update_data(
                self.area_data,
                self.spot_data,
                self.spectral_data,
                self.exposure_data
            )

    # ─────────────────────────────────────────────────────────
    # MENU ACTIONS
    # ─────────────────────────────────────────────────────────
    def _launch_objective_dialog(self, zone_name):
        if not self.active_incident_path:
            self._update_status_bar("⚠️ No active incident.")
            return
        current_data_type = "spot" if "Spot" in self.data_type_combo.currentText() else "area"
        dialog = ObjectiveDialog(self, self.active_incident_path, zone_name=zone_name, data_type=current_data_type)
        dialog.exec()

    @Slot()
    def _on_report_hotzone(self): self._launch_objective_dialog("Hotzone")
    @Slot()
    def _on_report_warmzone(self): self._launch_objective_dialog("Warmzone")
    @Slot()
    def _on_report_fireground(self): self._launch_objective_dialog("Fireground")
    @Slot()
    def _on_report_community(self): self._launch_objective_dialog("Community")

    @Slot()
    def _on_manage_thresholds(self):
        if not self.active_incident_path:
            self._update_status_bar("⚠️ No active incident.")
            return
        dialog = ThresholdsDialog(self, self.active_incident_path)
        if dialog.exec() == QDialog.Accepted:
            self._load_thresholds()
            self._update_status_bar("✅ Thresholds updated.")

    @Slot()
    def _on_clear_objectives(self):
        if not self.active_incident_path:
            self._update_status_bar("⚠️ No active incident.")
            return
        objectives_file = os.path.join(self.active_incident_path, "reports", "objectives.json")
        reply = QMessageBox.question(
            self, "Clear Objectives", "Are you sure you want to delete all objectives?\n\nThis action cannot be undone.",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No
        )
        if reply == QMessageBox.Yes:
            if os.path.exists(objectives_file):
                try:
                    os.remove(objectives_file)
                    self._update_status_bar("✅ All objectives cleared.")
                    QMessageBox.information(self, "Success", "All objectives have been deleted.")
                except OSError as e:
                    QMessageBox.critical(self, "Error", f"Failed to delete objectives file:\n{e}")
            else:
                QMessageBox.information(self, "Info", "No objectives file found to delete.")

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
        if not self.active_incident_path: return
        dialog = MapEditorDialog(self, self.active_incident_path, mode="spot")
        if dialog.exec() == QDialog.Accepted:
            self._refresh_overview()
            if self.data_type == "spot": self._on_data_type_changed("Spot Readings")

    @Slot()
    def _on_map_area(self):
        if not self.active_incident_path: return
        dialog = MapEditorDialog(self, self.active_incident_path, mode="area")
        if dialog.exec() == QDialog.Accepted:
            self._refresh_overview()
            if self.data_type == "area": self._on_data_type_changed("Area Readings")

    @Slot()
    def _on_map_spectral(self):
        if not self.active_incident_path: return
        dialog = MapEditorDialog(self, self.active_incident_path, mode="spectral")
        if dialog.exec() == QDialog.Accepted:
            self._update_status_bar("💾 Spectral map saved.")

    @Slot()
    def _on_spot_readings(self):
        if not self.active_incident_path: return
        dialog = SpotReadingsDialog(self, self.active_incident_path)
        if dialog.exec() == QDialog.Accepted:
            self._update_status_bar("💾 Spot readings saved.")
            self._refresh_overview()
            if self.data_type == "spot": self._on_data_type_changed("Spot Readings")

    @Slot()
    def _on_spectral_results(self):
        if not self.active_incident_path: return
        dialog = SpectralResultsDialog(self, self.active_incident_path)
        if dialog.exec() == QDialog.Accepted:
            self._update_status_bar("💾 Spectral records saved.")
            if self.data_type == "spectral": self._on_data_type_changed("Spectral Results")

    @Slot()
    def _on_exposures(self):
        if not self.active_incident_path: return
        from exposure_dialog import ExposuresDialog
        dialog = ExposuresDialog(self, self.active_incident_path, available_analytes=self.available_analytes, analyte_dec_pls=self.analyte_dec_pls)
        if dialog.exec() == QDialog.Accepted:
            self._update_status_bar("💾 Exposures saved.")
            if self.data_type == "exposure": self._on_data_type_changed("Exposures")

    @Slot()
    def _on_import_plumes(self):
        if not self.active_incident_path:
            self._update_status_bar("⚠️ No active incident.")
            return
        plumes_dir = os.path.join(self.active_incident_path, "plumes")
        os.makedirs(plumes_dir, exist_ok=True)
        files, _ = QFileDialog.getOpenFileNames(self, "Select Plume Images", "", "PNG Files (*.png);;All Files (*)")
        if not files: return
        
        copied_count = 0
        for src in files:
            dst = os.path.join(plumes_dir, os.path.basename(src))
            try:
                shutil.copy(src, dst)
                copied_count += 1
            except Exception as e:
                logger.error(f"Failed to copy {src}: {e}")
                
        QMessageBox.information(self, "Import Complete", f"Successfully copied {copied_count} file(s) to the plumes directory.")
        self._update_status_bar(f"📂 Imported {copied_count} plume image(s).")
        
        if self.data_type == "plume":
            self._load_plume_data()
            self._apply_initial_filters() 

    @Slot()
    def _on_delete_plumes(self):
        if not self.active_incident_path:
            self._update_status_bar("⚠️ No active incident.")
            return
        plumes_dir = os.path.join(self.active_incident_path, "plumes")
        if not os.path.exists(plumes_dir):
            QMessageBox.information(self, "Info", "The plumes directory does not exist yet.")
            return
            
        dialog = QFileDialog(self, "Select Plume Images to Delete", plumes_dir, "PNG Files (*.png);;All Files (*)")
        dialog.setFileMode(QFileDialog.ExistingFiles)
        dialog.setLabelText(QFileDialog.Accept, "Select")
        if dialog.exec(): files = dialog.selectedFiles()
        else: return
        
        if not files: return
        reply = QMessageBox.question(
            self, "Confirm Deletion", f"Are you sure you want to delete {len(files)} selected file(s)?\n\nThis action cannot be undone.",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No
        )
        if reply == QMessageBox.Yes:
            deleted_count = 0
            for f in files:
                try:
                    os.remove(f)
                    deleted_count += 1
                except Exception as e:
                    logger.error(f"Failed to delete {f}: {e}")
            QMessageBox.information(self, "Delete Complete", f"Successfully deleted {deleted_count} file(s).")
            self._update_status_bar(f"🗑️ Deleted {deleted_count} plume image(s).")

    @Slot()
    def _on_device_locations(self):
        if not self.active_incident_path: return
        dialog = DeviceLocationsDialog(self, self.active_incident_path)
        if dialog.exec() == QDialog.Accepted:
            self._refresh_overview()
            if self.data_type == "area": self._on_data_type_changed("Area Readings")

    @Slot()
    def _on_device_validations(self):
        if not self.active_incident_path: return
        DeviceValidationsDialog(self, self.active_incident_path).exec()

    @Slot()
    def _on_battery_analysis(self):
        if not self.active_incident_path: return
        BatteryAnalysisDialog(self, self.active_incident_path).exec()

    @Slot()
    def _on_import_area(self):
        if not self.active_incident_path:
            self._update_status_bar("⚠️ No active incident.")
            return
        files, _ = QFileDialog.getOpenFileNames(self, "Select Area Data CSV Files", "", "CSV Files (*.csv);;All Files (*)")
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
            if self.data_type == "area": self._on_data_type_changed("Area Readings")
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
