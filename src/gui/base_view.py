import os
import json
import logging
import tempfile
import pandas as pd
from datetime import datetime
from PySide6.QtWidgets import QWidget, QApplication, QProgressDialog
from PySide6.QtCore import Qt

logger = logging.getLogger(__name__)

# Mapping data types to their specific device/identifier keys in last_filters.json
DEVICE_KEY_MAP = {
    "area": "selected_area_devices",
    "spot": "selected_spot_devices",
    "spectral": "selected_spectral_devices",
    "exposure": "selected_exposure_identifiers"
}

class DataView(QWidget):
    """
    Abstract base class for all data views.
    Views are self-contained: they load their own data, filters, and configs.
    """
    def __init__(self, incident_path, data_type, parent=None):
        super().__init__(parent)
        self.incident_path = incident_path
        self.data_type = data_type

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
        """Load configs, raw data, and filters with a progress dialog."""
        progress = QProgressDialog("Loading data...", None, 0, 0, self)
        progress.setWindowTitle("Loading")
        progress.setWindowModality(Qt.WindowModal)
        progress.setMinimumDuration(0)
        progress.setCancelButton(None)
        progress.setValue(0)
        progress.show()
        try:
            # Step 1: Load configs
            progress.setLabelText("Loading configuration...")
            QApplication.processEvents()
            self._load_configs()

            # Step 2: Load raw data
            progress.setLabelText("Loading raw data...")
            QApplication.processEvents()
            self._load_raw_data()

            # Step 3: Load filters
            progress.setLabelText("Loading filters...")
            QApplication.processEvents()
            self._load_filter_summary()

            # Step 4: Apply filters
            progress.setLabelText("Applying filters...")
            QApplication.processEvents()
            self.apply_filters()
        finally:
            progress.close()
            progress.deleteLater()

    def refresh(self):
        """Reload filter summary from disk and re-apply filters with progress indicator."""
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

            progress.setLabelText("Applying filters...")
            QApplication.processEvents()
            self.apply_filters()

            progress.setLabelText("Rendering view...")
            QApplication.processEvents()
            self._render()
        finally:
            progress.close()
            progress.deleteLater()

    def set_filter_summary(self, filter_summary):
        self.filter_summary = filter_summary or {}
        if self.data_type == "spot":
            self.filter_summary["interval"] = "Raw"
        self.apply_filters()

    def _load_configs(self):
        """Load analytes and thresholds from config files."""
        # Load analytes
        current_dir = os.path.dirname(os.path.abspath(__file__))
        analyte_config_path = os.path.normpath(
            os.path.join(current_dir, '..', 'static', 'lists', 'analytes.json')
        )
        if os.path.exists(analyte_config_path):
            try:
                with open(analyte_config_path, 'r', encoding='utf-8') as f:
                    analyte_config = json.load(f)
                for analyte in analyte_config.get("analytes", []):
                    clean = {k.strip(): str(v).strip() for k, v in analyte.items()}
                    name = clean.get("name")
                    if name:
                        self.available_analytes.append(name)
                        try:
                            self.analyte_dec_pls[name] = int(clean.get("dec_pls", 2))
                        except (ValueError, TypeError):
                            self.analyte_dec_pls[name] = 2
            except Exception as e:
                logger.error(f"Failed to load analytes config: {e}")

        # Load thresholds
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
                            for key in ["hotzone_value", "warmzone_value", "fireground_value", "community_value"]:
                                raw = clean.get(key, "0")
                                try:
                                    entry[key] = float(str(raw).strip())
                                except (ValueError, TypeError):
                                    entry[key] = 0.0
                            self.thresholds_lookup[analyte_name.upper()] = entry
                except Exception as e:
                    logger.error(f"Failed to load thresholds: {e}")

    def _load_raw_data(self):
        """Load raw data using reader.py based on data_type."""
        if not self.incident_path:
            return
        from datamanagement.reader import (
            read_area_data, read_spot_data, 
            read_spectral_data, read_exposure_data
        )

        if self.data_type == "area":
            self.raw_data = read_area_data(self.incident_path)
        elif self.data_type == "spot":
            self.raw_data = read_spot_data(self.incident_path)
        elif self.data_type == "spectral":
            self.raw_data = read_spectral_data(self.incident_path)
        elif self.data_type == "exposure":
            self.raw_data = read_exposure_data(self.incident_path)
        # plume doesn't use raw_data

    def _load_filter_summary(self):
        """Load filter summary from meta/last_filters.json."""
        if not self.incident_path:
            self.filter_summary = {}
            return

        filters_file = os.path.join(
            self.incident_path, "meta", "last_filters.json"
        )
        if not os.path.exists(filters_file):
            # Initialize with default filters
            self.filter_summary = self._get_default_filters()
            return

        try:
            with open(filters_file, 'r', encoding='utf-8') as f:
                raw = json.load(f)

            # Strip whitespace from keys and string values (safety net)
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
                        raw[key] = datetime.fromisoformat(val)
                    except (ValueError, TypeError):
                        raw[key] = None

            self.filter_summary = raw
        except Exception as e:
            logger.error(f"Failed to load filter summary: {e}")
            self.filter_summary = self._get_default_filters()

    def _get_default_filters(self):
        """Generate default filters based on raw data."""
        if self.raw_data is None or self.raw_data.empty:
            return {"data_type": self.data_type}

        if 'LOG TIME' in self.raw_data.columns and not self.raw_data['LOG TIME'].dropna().empty:
            data_start = self.raw_data['LOG TIME'].min()
            data_stop = self.raw_data['LOG TIME'].max()
        else:
            data_start = pd.Timestamp.now()
            data_stop = pd.Timestamp.now()

        # ✅ Resolve the correct device key for this data type
        device_key = DEVICE_KEY_MAP.get(self.data_type, "selected_area_devices")

        return {
            "start_time": data_start,
            "stop_time": data_stop,
            "interval": "Raw",
            "group_by": "Device",
            "only_valid": False,
            "selected_sites": ["Unassigned"] + (
                self.raw_data['SITE'].dropna().unique().tolist() 
                if 'SITE' in self.raw_data.columns else []
            ),
            device_key: (  # ✅ Dynamically assigned key
                self.raw_data['DEVICE'].dropna().unique().tolist() 
                if 'DEVICE' in self.raw_data.columns else []
            ),
            "selected_analytes": list(self.available_analytes),
            "threshold_level": None,
            "data_type": self.data_type
        }

    def apply_filters(self):
        """Apply filters to raw_data and store in filtered_data."""
        if self.data_type == "plume":
            # Plume doesn't use filter_data
            return
        if self.raw_data is None or self.raw_data.empty:
            self.filtered_data = pd.DataFrame()
            return

        from datamanagement.filtering import filter_data, aggregate_data

        # ✅ Resolve the correct device key for this data type
        device_key = DEVICE_KEY_MAP.get(self.data_type, "selected_area_devices")
        devices = self.filter_summary.get(device_key)
        if devices is None:
            # Fallback for older last_filters.json files
            devices = self.filter_summary.get('selected_devices', [])

        # Filter
        self.filtered_data = filter_data(
            df=self.raw_data,
            start_dt=self.filter_summary.get('start_time'),
            stop_dt=self.filter_summary.get('stop_time'),
            selected_sites=self.filter_summary.get('selected_sites', []),
            selected_devices=devices,
            selected_analytes=self.filter_summary.get('selected_analytes', []),
            only_valid=self.filter_summary.get('only_valid', False),
            group_by=self.filter_summary.get('group_by', 'Device'),
            data_type=self.data_type
        )

        # ==========================================
        # AGGREGATION SAFEGUARD
        # ==========================================
        # ONLY aggregate area data. 
        # Spot, spectral, and exposure must ALWAYS remain raw.
        if self.filtered_data is not None and not self.filtered_data.empty:
            interval = self.filter_summary.get("interval", "Raw")
            
            # --- FIX: Changed from `!= "exposure"` to `== "area"` ---
            if interval != "Raw" and self.data_type == "area":
                self.filtered_data = aggregate_data(
                    df=self.filtered_data,
                    interval=interval,
                    group_by=self.filter_summary.get('group_by', 'Device'),
                    start_dt=self.filter_summary.get('start_time'),
                    stop_dt=self.filter_summary.get('stop_time')
                )
        print(self.filtered_data["CO(ppm)"])

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

    def _setup_ui(self):
        raise NotImplementedError("Subclasses must implement _setup_ui()")

    def _render(self):
        """Render the view with current filtered_data. Subclasses must implement."""
        raise NotImplementedError("Subclasses must implement _render()")

    def update_data(self, *args, **kwargs):
        """Alias for _render for compatibility."""
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
