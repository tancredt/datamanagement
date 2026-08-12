import os
import json
import logging
import tempfile
import pandas as pd
from datetime import datetime
from PySide6.QtWidgets import QWidget, QApplication, QProgressDialog
from PySide6.QtCore import Qt
from datamanagement.db_manager import IncidentDatabase
from datamanagement.filter import FilterManager, DEVICE_KEY_MAP

logger = logging.getLogger(__name__)

class DataView(QWidget):
    """
    Abstract base class for all data views.
    Views are self-contained: they load their own data, filters, and configs.
    Filtering is now handled natively by the SQL queries in reader.py.
    """
    def __init__(self, incident_path, data_type, parent=None):
        super().__init__(parent)
        self.incident_path = incident_path
        self.data_type = data_type
        self.db = IncidentDatabase(incident_path) if incident_path else None
        
        # State
        self.raw_data = None
        self.filtered_data = None
        self.filter_summary = {}
        self.analyte_dec_pls = {}
        self.available_analytes = []
        self.thresholds_lookup = {}
        
        # Load everything with progress indicator
        self._load_all_with_progress()

    def _load_all_with_progress(self):
        """Load configs, filters, raw data, and aggregate with a progress dialog."""
        progress = QProgressDialog("Loading data...", None, 0, 0, self)
        progress.setWindowTitle("Loading")
        progress.setWindowModality(Qt.WindowModal)
        progress.setMinimumDuration(0)
        progress.setCancelButton(None)
        progress.setValue(0)
        progress.show()
        
        try:
            progress.setLabelText("Loading configuration...")
            QApplication.processEvents()
            self._load_configs()
            
            progress.setLabelText("Loading filters...")
            QApplication.processEvents()
            self._load_filter_summary()
            
            progress.setLabelText("Loading raw data...")
            QApplication.processEvents()
            self._load_raw_data()
            
            progress.setLabelText("Applying aggregation...")
            QApplication.processEvents()
            self._apply_aggregation()
        finally:
            progress.close()
            progress.deleteLater()

    def refresh(self):
        """Reload filter summary from disk and re-query DB with progress indicator."""
        progress = QProgressDialog("Refreshing data...", None, 0, 0, self)
        progress.setWindowTitle("Refreshing")
        progress.setWindowModality(Qt.WindowModal)
        progress.setMinimumDuration(0)
        progress.setCancelButton(None)
        progress.setValue(0)
        progress.show()
        
        try:
            progress.setLabelText("Loading filters...")
            QApplication.processEvents()
            self._load_filter_summary()
            
            progress.setLabelText("Querying database...")
            QApplication.processEvents()
            self._load_raw_data()
            
            progress.setLabelText("Applying aggregation...")
            QApplication.processEvents()
            self._apply_aggregation()
            
            progress.setLabelText("Rendering view...")
            QApplication.processEvents()
            self._render()
        finally:
            progress.close()
            progress.deleteLater()

    def set_filter_summary(self, filter_summary):
        """Called when the user applies new filters from the dialog."""
        self.filter_summary = filter_summary or {}
        if self.data_type == "spot":
            self.filter_summary["interval"] = "Raw"
        
        self._load_raw_data()
        self._apply_aggregation()

    # ─────────────────────────────────────────────────────────
    # CONFIG LOADING
    # ─────────────────────────────────────────────────────────
    def _load_configs(self):
        """Load analytes from the database and thresholds from JSON."""
        if self.db:
            try:
                analytes = self.db.get_analytes()
                for a in analytes:
                    label = a['label']
                    self.available_analytes.append(label)
                    self.analyte_dec_pls[label] = a.get('dec_pls', 2)
            except Exception as e:
                logger.error(f"Failed to load analytes from DB: {e}")
                
        if self.incident_path:
            thresholds_file = os.path.join(self.incident_path, "meta", "thresholds.json")
            if os.path.exists(thresholds_file):
                try:
                    with open(thresholds_file, 'r', encoding='utf-8') as f:
                        data = json.load(f)
                    for t in data.get("thresholds", []):
                        clean = {k.strip(): v for k, v in t.items()}
                        analyte_name = str(clean.get("analyte", "")).strip()
                        if analyte_name:
                            entry = {}
                            for key in ["hotzone_value", "warmzone_value",
                                        "fireground_value", "community_value"]:
                                raw = clean.get(key, "0")
                                try:
                                    entry[key] = float(str(raw).strip())
                                except (ValueError, TypeError):
                                    entry[key] = 0.0
                            self.thresholds_lookup[analyte_name.upper()] = entry
                except Exception as e:
                    logger.error(f"Failed to load thresholds: {e}")

    # ─────────────────────────────────────────────────────────
    # FILTER LOADING
    # ─────────────────────────────────────────────────────────
    def _load_filter_summary(self):
        """Load filter summary from meta/last_filters.json using FilterManager."""
        if not self.incident_path:
            self.filter_summary = {}
            return
        
        try:
            filter_manager = FilterManager(self.incident_path)
            raw = filter_manager.load_filters()
            
            # If file didn't exist, get defaults based on data type
            if not raw or not any(raw.values()):
                self.filter_summary = self._get_default_filters()
                return
            
            self.filter_summary = raw
        except Exception as e:
            logger.error(f"Failed to load filter summary: {e}")
            self.filter_summary = self._get_default_filters()

    def _get_default_filters(self):
        """Generate default filters using DB metadata."""
        now = pd.Timestamp.now().replace(second=0, microsecond=0)
        data_start = now - pd.Timedelta(days=1)
        data_stop = now
        
        if self.db:
            try:
                min_ts, max_ts = self.db.get_data_time_range(self.data_type)
                if min_ts and max_ts:
                    data_start = pd.to_datetime(min_ts)
                    data_stop = pd.to_datetime(max_ts)
            except Exception as e:
                logger.warning(f"Could not query time range from DB: {e}")
                
        device_key = DEVICE_KEY_MAP.get(self.data_type, "selected_area_devices")
        devices = self.db.get_devices(self.data_type) if self.db else []
        markers = self.db.get_markers() if self.db else []
        
        return {
            "start_time": data_start,
            "stop_time": data_stop,
            "interval": "Raw",
            "group_by": "Device",
            "only_valid": False,
            "selected_sites": ["Unassigned"] + markers,
            device_key: devices,
            "selected_analytes": list(self.available_analytes),
            "threshold_level": None,
            "data_type": self.data_type
        }

    # ─────────────────────────────────────────────────────────
    # DATA LOADING (DB queries with filters)
    # ─────────────────────────────────────────────────────────
    def _load_raw_data(self):
        """Load data from the database using filter_summary parameters."""
        print(f"\n{'='*20} DEBUG: _load_raw_data ({self.__class__.__name__}) {'='*20}")
        print(f"Data Type: {self.data_type}")
        
        if not self.incident_path:
            print("DEBUG: No incident_path!")
            return
            
        from datamanagement.reader import (
            read_area_data, read_spot_data,
            read_spectral_data, read_exposure_data
        )
        
        # Extract filter parameters
        start = self.filter_summary.get('start_time')
        stop = self.filter_summary.get('stop_time')
        device_key = DEVICE_KEY_MAP.get(self.data_type, "selected_area_devices")
        devices = self.filter_summary.get(device_key) or self.filter_summary.get('selected_devices')
        sites = self.filter_summary.get('selected_sites')
        analytes = self.filter_summary.get('selected_analytes')
        only_valid = self.filter_summary.get('only_valid', False)

        print(f"DEBUG: start={start} (type: {type(start)})")
        print(f"DEBUG: stop={stop} (type: {type(stop)})")
        print(f"DEBUG: devices={devices}")
        print(f"DEBUG: sites={sites}")
        print(f"DEBUG: analytes={analytes}")
        print(f"DEBUG: only_valid={only_valid}")

        if self.data_type == "area":
            self.raw_data = read_area_data(
                self.incident_path,
                start_time=start, stop_time=stop,
                devices=devices, sites=sites,
                analytes=analytes, only_valid=only_valid
            )
            print(f"DEBUG: read_area_data returned {len(self.raw_data) if self.raw_data is not None and not self.raw_data.empty else 0} rows")
        elif self.data_type == "spot":
            self.raw_data = read_spot_data(
                self.incident_path,
                start_time=start, stop_time=stop,
                devices=devices, sites=sites,
                analytes=analytes
            )
        elif self.data_type == "spectral":
            self.raw_data = read_spectral_data(
                self.incident_path,
                start_time=start, stop_time=stop,
                devices=devices, sites=sites
            )
        elif self.data_type == "exposure":
            self.raw_data = read_exposure_data(
                self.incident_path,
                start_time=start, stop_time=stop,
                devices=devices, analytes=analytes
            )
            
        # Explicitly clear data for plumes to prevent state leakage
        elif self.data_type == "plume":
            self.raw_data = pd.DataFrame()

        self.filtered_data = self.raw_data
        
        if self.raw_data is not None and not self.raw_data.empty:
            print(f"DEBUG: raw_data shape: {self.raw_data.shape}")
            print(f"DEBUG: raw_data columns: {list(self.raw_data.columns)}")
        else:
            print("DEBUG: raw_data is EMPTY or None!")

    def _apply_aggregation(self):
        """Apply time-interval aggregation to the already-filtered data."""
        if self.data_type == "plume":
            return
        if self.filtered_data is None or self.filtered_data.empty:
            return
            
        interval = self.filter_summary.get("interval", "Raw")
        if interval != "Raw" and self.data_type == "area":
            from datamanagement.grouping import aggregate_data
            self.filtered_data = aggregate_data(
                df=self.filtered_data,
                interval=interval,
                group_by=self.filter_summary.get('group_by', 'Device'),
                data_type=self.data_type
            )
            print(f"DEBUG: After aggregation, shape: {self.filtered_data.shape}")
            print(f"DEBUG: After aggregation, columns: {list(self.filtered_data.columns)}")

    def apply_filters(self):
        """Re-query DB and re-aggregate. Called by set_filter_summary."""
        self._load_raw_data()
        self._apply_aggregation()

    # ─────────────────────────────────────────────────────────
    # THRESHOLDS
    # ─────────────────────────────────────────────────────────
    def get_active_thresholds(self):
        """Get active thresholds based on filter_summary."""
        threshold_level = self.filter_summary.get("threshold_level")
        if not threshold_level:
            return {}
            
        result = {}
        for analyte in self.available_analytes:
            analyte_upper = analyte.upper()
            if analyte_upper in self.thresholds_lookup:
                val = self.thresholds_lookup[analyte_upper].get(threshold_level)
                if val is not None:
                    result[analyte] = val
        return result

    # ─────────────────────────────────────────────────────────
    # ABSTRACT METHODS
    # ─────────────────────────────────────────────────────────
    def _setup_ui(self):
        raise NotImplementedError("Subclasses must implement _setup_ui()")

    def _render(self):
        raise NotImplementedError("Subclasses must implement _render()")

    def update_data(self, *args, **kwargs):
        self._render()

    def export(self):
        raise NotImplementedError("Subclasses must implement export()")

    def clear_view(self):
        pass

    def render_to_figure(self):
        """Render widget to matplotlib figure for PDF export."""
        self.resize(1000, 800)
        self.setAttribute(Qt.WA_DontShowOnScreen, True)
        self.show()
        QApplication.processEvents()
        
        pixmap = self.grab()
        with tempfile.NamedTemporaryFile(suffix='.png', delete=False) as tmp:
            tmp_path = tmp.name
        pixmap.save(tmp_path, 'PNG')
        
        import matplotlib.pyplot as plt
        fig = plt.figure(figsize=(8, 6))
        img = plt.imread(tmp_path)
        ax = fig.add_axes([0.02, 0.02, 0.96, 0.83])
        ax.imshow(img)
        ax.axis('off')
        
        try:
            os.remove(tmp_path)
        except Exception:
            pass
        return fig
