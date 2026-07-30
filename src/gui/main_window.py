import os
import sys
import shutil
import glob
import json
import logging
import datetime
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QStatusBar, QVBoxLayout, QHBoxLayout,
    QWidget, QLabel, QDialog, QFileDialog, QMessageBox, QProgressDialog,
    QStackedWidget, QDockWidget, QButtonGroup, QPushButton, QGroupBox, QComboBox
)
from PySide6.QtGui import QKeySequence
from PySide6.QtCore import Qt, Slot, QThread, Signal, QObject

# Ensure parent directory is in sys.path BEFORE local imports
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
from spectral_results_dialog import SpectralResultsDialog
from preferences_dialog import PreferencesDialog
from plume_dialog import PlumeDialog
from last_readings_dialog import LastReadingsDialog
from objectives_manager_dialog import ObjectivesManagerDialog

# New self-contained data view components
from table_view import TableView
from chart_view import ChartView
from summary_table_view import SummaryTableView
from summary_chart_view import SummaryChartView
from summary_map_view import SummaryMapView

# Filter dialog
from filter_dialog import FilterDialog
from thresholds_dialog import ThresholdsDialog

# Importer workers
from datamanagement.importer import copy_files_to_realtime, import_area_data
from datamanagement.updater import sync_all  # ✅ REPLACED OLD IMPORTS

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────
# VIEW CONSTRAINTS (Single source of truth for UI rules)
# Note: Overview is removed. Indices are now 0-4.
# ─────────────────────────────────────────────────────────
VIEW_CONSTRAINTS = {
    "spot":     {"enabled": [0, 1, 2, 3, 4], "default": 0},
    "area":     {"enabled": [0, 1, 2, 3, 4], "default": 0},
    "spectral": {"enabled": [0, 4],             "default": 0},
    "exposure": {"enabled": [2, 3],          "default": 2},
    "plume":    {"enabled": [4],             "default": 4}
}
#This is for the filter summary to work out which set of devices to use
DEVICE_KEY_MAP = {
    "area": "selected_area_devices",
    "spot": "selected_spot_devices",
    "spectral": "selected_spectral_devices",
    "exposure": "selected_exposure_identifiers"
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
    finished = Signal(int)
    error = Signal(str)

    def __init__(self, incident_path):
        super().__init__()
        self.incident_path = incident_path

    @Slot()
    def do_work(self):
        try:
            # 1. Import raw CSVs into DB (Returns row count)
            row_count = import_area_data(self.incident_path)
            
            # 2. Sync the relational IDs based on locations and invalidations
            if row_count > 0:
                sync_all(self.incident_path)
                
            self.finished.emit(row_count if row_count is not None else 0)
        except Exception as e:
            self.error.emit(str(e))

class DataAnalyzerGUI(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Hazmat Data Analyzer")
        self.resize(1200, 800)

        self._active_incident = None
        self.data_type = "spot"

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
            # ==========================================
            # ✅ DEFAULT TO OVERVIEW VIEW (Index 5)
            # ==========================================
            self._load_view(5)
            
            # Uncheck all standard navigation buttons since Overview is separate
            for btn in self.nav_btns.values():
                btn.setChecked(False)
            # ==========================================
            
            self.central_stack.setCurrentIndex(1)
            self.data_type_combo.blockSignals(True)
            self.data_type_combo.setCurrentText("Spot Readings")
            self.data_type_combo.blockSignals(False)
            
            # Update filter summary labels from file
            self._update_filter_summary_labels()

    def _update_app_state(self, has_incident: bool):
        # All actions that require an active incident
        actions = [
            self.action_edit_incident, self.action_preferences,
            self.action_maps, self.action_spot_readings,
            self.action_import_area, self.action_device_locations,
            self.action_device_validations, self.action_battery,
            self.action_thresholds,
            self.action_publish, self.action_spectral_results,
            self.action_exposures, self.action_plumes,
            self.action_thresholds,
            self.action_publish, self.action_spectral_results,
            self.action_exposures, self.action_plumes,
        ]
        for action in actions:
            action.setEnabled(has_incident)
            
        # Disable the dock controls and navigation buttons
        controls = [self.data_type_combo, self.btn_filters, self.btn_global_export, self.filter_summary_group]
        for ctrl in controls:
            ctrl.setEnabled(has_incident)
            
        for btn in self.nav_btns.values():
            btn.setEnabled(has_incident)
            
        # Show/hide the dock and reset the central stack
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

        self.btn_overview = QPushButton("Overview")
        self.btn_overview.setMinimumHeight(45)
        self.btn_overview.setCursor(Qt.PointingHandCursor)
        self.btn_overview.setStyleSheet("""
            QPushButton { 
                text-align: center; border: none; border-radius: 6px; 
                font-size: 14px; color: white; background-color: #8b5cf6; font-weight: bold;  
            }
            QPushButton:hover { background-color: #7c3aed; }
        """)
        self.btn_overview.clicked.connect(self._show_overview)
        dock_layout.addWidget(self.btn_overview)
        dock_layout.addSpacing(5)
        
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
            ("Table", 0), ("Chart", 1),
            ("Summary Table", 2), ("Summary Chart", 3), ("Summary Map", 4)
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

        # ── Filter Summary Group (reads from disk) ──
        self.filter_summary_group = QGroupBox("Filter Summary")
        fs_layout = QVBoxLayout(self.filter_summary_group)
        fs_layout.setContentsMargins(10, 15, 10, 10)
        labels = ["Time: --", "Interval: --", "Group: --", "Sites: --", "Devices: --", "Analytes: --"]
        self.filter_labels = []
        for text in labels:
            lbl = QLabel(text)
            lbl.setStyleSheet("font-weight: bold; color: #374151; font-size: 12px;")
            lbl.setWordWrap(True)
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

        # Global Export Button
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

        # ── File Menu ──
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

        # ── Edit Menu ──
        edit_menu = menubar.addMenu("&Edit")
        self.action_preferences = edit_menu.addAction("&Preferences...", self._on_preferences)
        self.action_preferences.setShortcut(QKeySequence("Ctrl+,"))
        self.action_thresholds = edit_menu.addAction("&Thresholds...", self._on_manage_thresholds)
        
        # ── Combined Data Menu ──
        data_menu = menubar.addMenu("&Data")
        self.action_maps = data_menu.addAction("&Maps...", self._on_maps)

        spot_menu = data_menu.addMenu("&Spot Readings")
        self.action_spot_readings = spot_menu.addAction("&Readings...", self._on_spot_readings)

        area_menu = data_menu.addMenu("&Area Readings")
        self.action_import_area = area_menu.addAction("&Import Data...", self._on_import_area)
        area_menu.addSeparator()
        self.action_device_locations = area_menu.addAction("Device &Locations...", self._on_device_locations)
        self.action_device_validations = area_menu.addAction("Device &Validations...", self._on_device_validations)
        self.action_battery = area_menu.addAction("&Battery...", self._on_battery_analysis)
        self.action_last_readings = area_menu.addAction("&Last Readings...", self._on_last_readings) 
        
        spectral_menu = data_menu.addMenu("&Spectral Results")
        self.action_spectral_results = spectral_menu.addAction("&Results...", self._on_spectral_results)

        exposure_menu = data_menu.addMenu("E&xposures")
        self.action_exposures = exposure_menu.addAction("&Exposures...", self._on_exposures)

        spectral_menu = data_menu.addMenu("&Spectral Results")
        self.action_spectral_results = spectral_menu.addAction("&Results...", self._on_spectral_results)
        exposure_menu = data_menu.addMenu("E&xposures")
        self.action_exposures = exposure_menu.addAction("&Exposures...", self._on_exposures)
        
        self.action_plumes = data_menu.addAction("&Plumes...", self._on_plumes)
        
        # ── Reports Menu ──
        reports_menu = menubar.addMenu("&Reports")
        
        self.action_manage_objectives = reports_menu.addAction("&Objectives...", self._on_manage_objectives)
        
        reports_menu.addSeparator()
        self.action_publish = reports_menu.addAction("&Publish")
        self.action_publish.triggered.connect(self._on_report_publish)

        # ── View Menu ──
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
    # FILTER SUMMARY (Reads directly from disk)
    # ─────────────────────────────────────────────────────────
    def _read_filter_file(self):
        """Reads the filter file from disk."""
        if not self.active_incident_path:
            return {}
        
        filters_file = os.path.join(
            self.active_incident_path, "meta", "last_filters.json"
        )
        
        if not os.path.exists(filters_file):
            return {}
        
        try:
            with open(filters_file, 'r', encoding='utf-8') as f:
                raw = json.load(f)
            
            # Strip whitespace from keys and string values
            def clean(obj):
                if isinstance(obj, dict):
                    return {k.strip(): clean(v) for k, v in obj.items()}
                elif isinstance(obj, list):
                    return [clean(elem) for elem in obj]
                elif isinstance(obj, str):
                    return obj.strip()
                return obj
            
            raw = clean(raw)
            
            # Deserialize datetimes
            for key in ("start_time", "stop_time"):
                val = raw.get(key)
                if isinstance(val, str):
                    try:
                        raw[key] = datetime.datetime.fromisoformat(val)
                    except (ValueError, TypeError):
                        raw[key] = None
            
            return raw
        except Exception as e:
            logger.error(f"Failed to read filter file: {e}")
            return {}

    def _update_filter_summary_labels(self):
        """Updates the filter summary labels by reading the filter file from disk."""
        summary = self._read_filter_file()
        
        if self.data_type == "plume":
            # Plume has special handling
            plumes_dir = os.path.join(self.active_incident_path, "plumes") if self.active_incident_path else None
            count = 0
            if plumes_dir and os.path.exists(plumes_dir):
                count = len([f for f in os.listdir(plumes_dir) if f.lower().endswith(".png")])
            
            start_t = summary.get('start_time', '--')
            stop_t = summary.get('stop_time', '--')
            if hasattr(start_t, 'strftime'):
                start_t = start_t.strftime("%Y-%m-%d %H:%M")
            if hasattr(stop_t, 'strftime'):
                stop_t = stop_t.strftime("%Y-%m-%d %H:%M")
            
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
        
        if not summary:
            texts = ["Time: --", "Interval: --", "Group: --", "Sites: --", "Devices: --", "Analytes: --"]
            for lbl, text in zip(self.filter_labels, texts):
                lbl.setText(text)
            return
        
        # Format time range
        start_t = summary.get('start_time', '--')
        stop_t = summary.get('stop_time', '--')
        if hasattr(start_t, 'strftime'):
            start_t = start_t.strftime("%Y-%m-%d %H:%M")
        if hasattr(stop_t, 'strftime'):
            stop_t = stop_t.strftime("%Y-%m-%d %H:%M")
        
        # Interval
        interval_text = summary.get('interval', '--')
        if self.data_type in ["spectral", "exposure"]:
            interval_text = "Raw (N/A)"
        
        # Comma-delimited lists
        sites_list = summary.get('selected_sites', [])
        devices_list = summary.get('selected_devices', [])
        analytes_list = summary.get('selected_analytes', [])
        
        sites_text = ", ".join(sites_list) if sites_list else "None"

        device_key = DEVICE_KEY_MAP.get(self.data_type, "selected_area_devices")
        devices_list = summary.get(device_key)
        if devices_list is None:
            devices_list = summary.get('selected_devices', [])
            
        devices_text = ", ".join(devices_list) if devices_list else "None"
        
        if self.data_type == "spectral":
            analytes_text = "N/A"
        else:
            analytes_text = ", ".join(analytes_list) if analytes_list else "None"
        
        # Site/Device labels based on data type
        is_exposure = self.data_type == "exposure"
        site_label = "Areas" if is_exposure else "Sites"
        device_label = "Identifiers" if is_exposure else "Devices"
        
        texts = [
            f"Time: {start_t} to {stop_t}",
            f"Interval: {interval_text}",
            f"Group: {summary.get('group_by', '--')}",
            f"{site_label}: {sites_text}",
            f"{device_label}: {devices_text}",
            f"Analytes: {analytes_text}"
        ]
        
        for lbl, text in zip(self.filter_labels, texts):
            lbl.setText(text)

    def _refresh_current_view(self):
        """Helper to refresh the currently active view in the stack."""
        current_widget = self.view_stack.currentWidget()
        if current_widget and hasattr(current_widget, 'refresh'):
            current_widget.refresh()
            
    # ─────────────────────────────────────────────────────────
    # DYNAMIC VIEW ENGINE
    # ─────────────────────────────────────────────────────────
    def _clear_current_view(self):
        """Safely removes and destroys the currently active view in the stack."""
        import matplotlib.pyplot as plt  # ✅ Import pyplot for cleanup
        
        while self.view_stack.count() > 0:
            w = self.view_stack.widget(0)
            self.view_stack.removeWidget(w)
            
            # ✅ FIX: Safely close matplotlib figures to prevent Qt backend crashes
            if hasattr(w, 'figure'):
                try: plt.close(w.figure)
                except Exception: pass
            if hasattr(w, 'summary_figure'):
                try: plt.close(w.summary_figure)
                except Exception: pass
                
            w.deleteLater()

    def _load_view(self, index):
        """Instantiates the requested view and displays it."""
        self._clear_current_view()
        if not self.active_incident_path:
            return
        
        view = None
        if index == 0:
            view = TableView(incident_path=self.active_incident_path, data_type=self.data_type, parent=self)
        elif index == 1:
            view = ChartView(incident_path=self.active_incident_path, data_type=self.data_type, parent=self)
        elif index == 2:
            view = SummaryTableView(incident_path=self.active_incident_path, data_type=self.data_type, parent=self)
        elif index == 3:
            view = SummaryChartView(incident_path=self.active_incident_path, data_type=self.data_type, parent=self)
        elif index == 4:
            view = SummaryMapView(
                incident_path=self.active_incident_path,
                data_type=self.data_type,
                parent=self
            )
        elif index == 5:
            from overview_view import OverviewWidget
            view = OverviewWidget(incident_path=self.active_incident_path, parent=self)

        if view is not None:
            self.view_stack.addWidget(view)
            self.view_stack.setCurrentWidget(view)

            
    # ─────────────────────────────────────────────────────────
    # DATA TYPE SWITCHING
    # ─────────────────────────────────────────────────────────
    @Slot(str)
    def _on_data_type_changed(self, text):
        if not self.active_incident_path:
            return

        if "Spectral" in text: 
            new_data_type = "spectral"
        elif "Spot" in text: 
            new_data_type = "spot"
        elif "Exposures" in text: 
            new_data_type = "exposure"
        elif "Plume" in text: 
            new_data_type = "plume"
        else: 
            new_data_type = "area"

        self.data_type = new_data_type

        # Update nav button constraints
        constraints = VIEW_CONSTRAINTS.get(self.data_type, VIEW_CONSTRAINTS["area"])
        enabled_indices = constraints["enabled"]
        default_idx = constraints["default"]

        for idx, btn in self.nav_btns.items():
            btn.setEnabled(idx in enabled_indices)

        current_btn_idx = next((idx for idx, btn in self.nav_btns.items() if btn.isChecked()), 0)
        target_idx = current_btn_idx if current_btn_idx in enabled_indices else default_idx
        
        self.nav_btns[target_idx].setChecked(True)
        
        # Reload the current view with the new data type
        self._load_view(target_idx)
        
        # Update filter summary labels from file
        self._update_filter_summary_labels()
        
        self._update_status_bar(f"📊 Switched to {self.data_type.title()} Data.")

    # ─────────────────────────────────────────────────────────
    # FILTERING & NAVIGATION
    # ─────────────────────────────────────────────────────────
    @Slot(int)
    def _on_nav_clicked(self, index):
        constraints = VIEW_CONSTRAINTS.get(self.data_type, VIEW_CONSTRAINTS["area"])
        if index not in constraints["enabled"]:
            index = constraints["default"]
            self.nav_btns[index].setChecked(True)
        
        self._load_view(index)

    def _export_current_view(self):
        """Triggers the export method on whichever view is currently active."""
        current_widget = self.view_stack.currentWidget()
        if current_widget and hasattr(current_widget, 'export') and callable(current_widget.export):
            current_widget.export()
        else:
            QMessageBox.information(self, "Export", "The current view does not support exporting.")

    def _open_filter_dialog(self):
        """Opens the FilterDialog in 'view' mode to save filters to disk."""
        if not self.active_incident_path:
            return
            
        dialog = FilterDialog(
            parent=self,
            incident_path=self.active_incident_path,
            data_type=self.data_type,
            mode="view"  # Save to disk
        )
        
        if dialog.exec() == QDialog.Accepted:
            # Refresh the current view (it will reload filters from disk)
            current_widget = self.view_stack.currentWidget()
            if hasattr(current_widget, 'refresh'):
                current_widget.refresh()
            else:
                # Fallback: just reload the view entirely
                current_idx = next((idx for idx, btn in self.nav_btns.items() if btn.isChecked()), 0)
                self._load_view(current_idx)
            
            # Update filter summary labels from file
            self._update_filter_summary_labels()

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
    def _on_manage_thresholds(self):
        if not self.active_incident_path:
            self._update_status_bar("⚠️ No active incident.")
            return
        dialog = ThresholdsDialog(self, self.active_incident_path)
        if dialog.exec() == QDialog.Accepted:
            self._update_status_bar("✅ Thresholds updated.")
            # Refresh current view so it picks up new thresholds
            current_widget = self.view_stack.currentWidget()
            if hasattr(current_widget, 'refresh'):
                current_widget.refresh()

    @Slot()
    def _on_manage_objectives(self):
        if not self.active_incident_path:
            self._update_status_bar("⚠️ No active incident.")
            return
        from objectives_manager_dialog import ObjectivesManagerDialog
        dialog = ObjectivesManagerDialog(self, self.active_incident_path)
        dialog.exec()
        
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
    def _on_preferences(self):
        if not self.active_incident_path:
            self._update_status_bar("⚠️ No active incident.")
            return
        dialog = PreferencesDialog(self, self.active_incident_path)
        if dialog.exec() == QDialog.Accepted:
            self._update_status_bar("✅ Preferences updated.")
            
    @Slot()
    def _on_maps(self):
        if not self.active_incident_path: 
            return
        dialog = MapEditorDialog(self, self.active_incident_path)
        if dialog.exec() == QDialog.Accepted:
            # Refresh current view so it picks up new maps
            current_widget = self.view_stack.currentWidget()
            if hasattr(current_widget, 'refresh'):
                current_widget.refresh()
            else:
                current_idx = next((idx for idx, btn in self.nav_btns.items() if btn.isChecked()), 0)
                self._load_view(current_idx)

    @Slot()
    def _on_spot_readings(self):
        if not self.active_incident_path: 
            return
        dialog = SpotReadingsDialog(self, self.active_incident_path)
        if dialog.exec() == QDialog.Accepted:
            self._update_status_bar("💾 Spot readings saved.")
            self._refresh_current_view()

    @Slot()
    def _on_spectral_results(self):
        if not self.active_incident_path: 
            return
        dialog = SpectralResultsDialog(self, self.active_incident_path)
        if dialog.exec() == QDialog.Accepted:
            self._update_status_bar("💾 Spectral records saved.")
            self._refresh_current_view()

    @Slot()
    def _on_exposures(self):
        if not self.active_incident_path: 
            return
        from exposure_dialog import ExposuresDialog
        dialog = ExposuresDialog(self, self.active_incident_path)
        if dialog.exec() == QDialog.Accepted:
            self._update_status_bar("💾 Exposures saved.")
            self._refresh_current_view()

    @Slot()
    def _on_plumes(self):
        if not self.active_incident_path:
            self._update_status_bar("⚠️ No active incident.")
            return
        dialog = PlumeDialog(self, self.active_incident_path)
        if dialog.exec() == QDialog.Accepted:
            self._update_status_bar("💾 Plumes updated.")
            self._refresh_current_view()

    @Slot()
    def _on_device_locations(self):
        if not self.active_incident_path: 
            return
        dialog = DeviceLocationsDialog(self, self.active_incident_path)
        if dialog.exec() == QDialog.Accepted:
            self._refresh_current_view()

    @Slot()
    def _on_device_validations(self):
        if not self.active_incident_path: 
            return
        # Note: Changed to capture the dialog result so we can refresh on success
        dialog = DeviceValidationsDialog(self, self.active_incident_path)
        if dialog.exec() == QDialog.Accepted:
            self._refresh_current_view()

    @Slot()
    def _on_battery_analysis(self):
        if not self.active_incident_path: 
            return
        BatteryAnalysisDialog(self, self.active_incident_path).exec()

    @Slot()
    def _on_last_readings(self):
        dialog = LastReadingsDialog(parent=self, incident_path=self.active_incident_path)
        dialog.exec()
        
    @Slot()
    def _show_overview(self):
        """Loads the Overview grid into the central view stack."""
        if not self.active_incident_path:
            return
        # Index 5 will be our designated slot for the Overview widget
        self._load_view(5)
        
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

    @Slot(int)
    def _on_import_finished(self, row_count):
        if hasattr(self, 'process_progress') and self.process_progress:
            self.process_progress.close()
            self.process_progress.deleteLater()
            self.process_progress = None
        if hasattr(self, 'process_thread') and self.process_thread:
            self.process_thread.quit()
            self.process_thread.wait()
        QApplication.processEvents()
        
        if row_count > 0:
            realtime_dir = os.path.join(self.active_incident_path, "data", "realtime")
            file_count = len(glob.glob(os.path.join(realtime_dir, "*.csv")))
            QMessageBox.information(
                self, "Processing Complete",
                f"Area data successfully processed!\n\nFiles in realtime directory: {file_count}\nTotal rows imported: {row_count}"
            )
            self._update_status_bar(f"✅ Area data processed ({row_count} rows).")
            
            current_widget = self.view_stack.currentWidget()
            if current_widget and hasattr(current_widget, 'refresh'):
                current_widget.refresh()
        else:
            QMessageBox.warning(self, "Processing Issue", "No new data was processed. Check if CSV files were valid or already imported.")
            self._update_status_bar("⚠️ No new data processed.")

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
