import os
import json
import shutil
import logging
import pandas as pd
import numpy as np

logger = logging.getLogger(__name__)

# ==========================================
# 1. HELPER FUNCTIONS FOR LABELS
# ==========================================
def get_next_label_index(all_labels):
    """Calculates the next alphabetical index based on a global set of labels."""
    max_idx = -1
    for label in all_labels:
        label_upper = label.strip().upper()
        if not label_upper.isalpha(): continue
        idx = 0
        for char in label_upper:
            idx = idx * 26 + (ord(char) - 64)
        idx -= 1
        if idx > max_idx: max_idx = idx
    return max_idx + 1

def index_to_label(idx):
    """Converts an integer index to an alphabetical label (e.g., 0 -> A, 25 -> Z, 26 -> AA)."""
    idx += 1
    result = []
    while idx > 0:
        idx, rem = divmod(idx - 1, 26)
        result.append(chr(65 + rem))
    return ''.join(reversed(result))

class LocationManager:
    """
    Unified manager for all map markers and their associated data.
    Reads and writes to a single 'locations.json' file in the mapping directory.
    """
    def __init__(self, incident_path):
        self.incident_path = incident_path
        self.mapping_dir = os.path.join(incident_path, "mapping")
        self.locations_file = os.path.join(self.mapping_dir, "locations.json")
        self.data = {"maps": {"locations": []}}
        self.ensure_structure()
        self.load()

    def ensure_structure(self):
        os.makedirs(self.mapping_dir, exist_ok=True)
        if not os.path.exists(self.locations_file):
            self._save_data({"maps": {"locations": []}})

    def load(self):
        if os.path.exists(self.locations_file):
            try:
                with open(self.locations_file, 'r', encoding='utf-8') as f:
                    self.data = json.load(f)
            except Exception as e:
                logger.error(f"Failed to load {self.locations_file}: {e}")
                self.data = {"maps": {"locations": []}}
        else:
            self.data = {"maps": {"locations": []}}

    def save(self):
        os.makedirs(self.mapping_dir, exist_ok=True)
        try:
            with open(self.locations_file, 'w', encoding='utf-8') as f:
                json.dump(self.data, f, indent=2)
        except Exception as e:
            logger.error(f"Failed to save {self.locations_file}: {e}")

    def _save_data(self, data):
        self.data = data
        self.save()

    def get_maps_data(self):
        """Returns a dict of {filename: [markers]}"""
        maps_data = {}
        for loc in self.data.get("maps", {}).get("locations", []):
            fname = loc.get("filename")
            if fname:
                maps_data[fname] = loc.get("markers", [])
        return maps_data

    def set_maps_data(self, maps_data):
        """Sets the maps data from a dict of {filename: [markers]} and saves to disk."""
        locations_list = []
        for fname, markers in maps_data.items():
            locations_list.append({"filename": fname, "markers": markers})
        self.data = {"maps": {"locations": locations_list}}
        self.save()

    def add_map(self, image_path):
        """Copies an image to the mapping dir and adds it to the JSON structure."""
        fname = os.path.basename(image_path)
        dest_path = os.path.join(self.mapping_dir, fname)
        if not os.path.exists(dest_path):
            shutil.copy2(image_path, dest_path)
            
        locations_list = self.data.get("maps", {}).get("locations", [])
        if not any(loc.get("filename") == fname for loc in locations_list):
            locations_list.append({"filename": fname, "markers": []})
            self.data["maps"]["locations"] = locations_list
            self.save()
        return fname

    def get_all_used_labels(self):
        """Gathers all used labels globally across all maps."""
        used_labels = set()
        for loc in self.data.get("maps", {}).get("locations", []):
            for m in loc.get("markers", []):
                lbl = m.get("label")
                if lbl: used_labels.add(lbl)
        return used_labels

    # ==========================================
    # 2. STRUCTURE HELPERS
    # ==========================================
    def _ensure_marker_structure(self, marker):
        """Ensures the marker has the correct explicit structure for readings and device_locations."""
        # Ensure 'readings' is a dict with explicit 'spot' and 'spectral' lists
        if "readings" not in marker or not isinstance(marker.get("readings"), dict):
            marker["readings"] = {"spot": [], "spectral": []}
        else:
            marker["readings"].setdefault("spot", [])
            marker["readings"].setdefault("spectral", [])
            
        # Ensure 'device_locations' exists for area data
        if "device_locations" not in marker or not isinstance(marker.get("device_locations"), list):
            marker["device_locations"] = []

    # ==========================================
    # 3. DEVICE & READING ACCESSORS
    # ==========================================
    def get_available_devices(self):
        """Loads unique device labels from spot, spectral, and device_locations."""
        devices = set()
        for loc in self.data.get("maps", {}).get("locations", []):
            for marker in loc.get("markers", []):
                self._ensure_marker_structure(marker)
                
                # Get devices from spot readings
                for r in marker["readings"]["spot"]:
                    device = r.get("device")
                    if device and str(device).strip():
                        devices.add(str(device).strip())
                        
                # Get devices from spectral readings
                for r in marker["readings"]["spectral"]:
                    device = r.get("device")
                    if device and str(device).strip():
                        devices.add(str(device).strip())
                        
                # Get devices from area device_locations
                for entry in marker["device_locations"]:
                    device = entry.get("device")
                    if device and str(device).strip():
                        devices.add(str(device).strip())
                        
        return sorted(list(devices))

    def get_available_labels(self):
        return sorted(list(self.get_all_used_labels()))

    def get_flat_readings(self, reading_type="all"):
        """
        Flattens readings for UI tables.
        reading_type: "spot", "spectral", or "all"
        """
        readings = []
        for loc in self.data.get("maps", {}).get("locations", []):
            for marker in loc.get("markers", []):
                self._ensure_marker_structure(marker)
                label = marker.get("label", "")
                spot_list = marker["readings"]["spot"]
                spectral_list = marker["readings"]["spectral"]

                if reading_type in ["spot", "all"]:
                    for r in spot_list:
                        clean_r = {k.strip(): v for k, v in r.items()}
                        row = {
                            "location": label,
                            "device": clean_r.get("device", ""),
                            "logtime": clean_r.get("datetime", ""),
                            "observations": clean_r.get("observations", ""),
                        }
                        for k, v in clean_r.items():
                            if k not in row and k not in ["datetime", "device", "observations"]:
                                row[k] = v
                        readings.append(row)

                if reading_type in ["spectral", "all"]:
                    for r in spectral_list:
                        clean_r = {k.strip(): v for k, v in r.items()}
                        row = {
                            "location": label,
                            "device": clean_r.get("device", ""),
                            "logtime": clean_r.get("datetime", ""),
                            "chemicals_identified": clean_r.get("chemicals_identified", ""),
                            "comments": clean_r.get("comments", ""),
                            "file_ref": clean_r.get("file_ref", ""),
                        }
                        readings.append(row)
        return readings

    def set_flat_readings(self, flat_readings, available_analytes=None, reading_type="spot"):
        """
        Reconstructs the nested JSON structure from a flat list of readings and saves it.
        reading_type: "spot" or "spectral"
        """
        locations_list = self.data.get("maps", {}).get("locations", [])
        
        # Ensure structure and clear existing readings for the specific type being updated
        for loc in locations_list:
            for marker in loc.get("markers", []):
                self._ensure_marker_structure(marker)
                if reading_type == "spectral":
                    marker["readings"]["spectral"] = []
                else:
                    marker["readings"]["spot"] = []

        # Rebuild readings
        for loc in locations_list:
            for marker in loc.get("markers", []):
                self._ensure_marker_structure(marker)
                label = marker.get("label", "")
                for r in flat_readings:
                    if r.get("location") == label:
                        reading_dict = {
                            "datetime": r.get("logtime", ""),
                            "device": r.get("device", ""),
                        }
                        if reading_type == "spectral":
                            reading_dict["chemicals_identified"] = r.get("chemicals_identified", "")
                            reading_dict["comments"] = r.get("comments", "")
                            reading_dict["file_ref"] = r.get("file_ref", "")
                            marker["readings"]["spectral"].append(reading_dict)
                        else:
                            reading_dict["observations"] = r.get("observations", "")
                            if available_analytes:
                                for analyte in available_analytes:
                                    if analyte in r and r[analyte] is not None:
                                        reading_dict[analyte] = r[analyte]
                            marker["readings"]["spot"].append(reading_dict)
        self.save()

    def to_dataframe(self, available_analytes=None, reading_type="all"):
        """
        Converts the location data to a pandas DataFrame.
        reading_type: "spot", "spectral", or "all"
        """
        rows = []
        for loc in self.data.get("maps", {}).get("locations", []):
            for marker in loc.get("markers", []):
                self._ensure_marker_structure(marker)
                site = marker.get("label", "") or "Unassigned"
                spot_list = marker["readings"]["spot"]
                spectral_list = marker["readings"]["spectral"]

                if reading_type in ["spot", "all"]:
                    for r in spot_list:
                        clean_r = {k.strip(): v for k, v in r.items()}
                        row = {
                            "LOG TIME": clean_r.get("datetime"),
                            "DEVICE": clean_r.get("device", ""),
                            "SITE": site,
                            "observations": clean_r.get("observations", ""),
                            "Latitude": np.nan,
                            "Longitude": np.nan,
                        }
                        if available_analytes:
                            for analyte in available_analytes:
                                row[analyte] = clean_r.get(analyte)
                                row[f"INVALID_{analyte}"] = 0
                        rows.append(row)

                if reading_type in ["spectral", "all"]:
                    for r in spectral_list:
                        clean_r = {k.strip(): v for k, v in r.items()}
                        row = {
                            "LOG TIME": clean_r.get("datetime"),
                            "DEVICE": clean_r.get("device", ""),
                            "SITE": site,
                            "chemicals_identified": clean_r.get("chemicals_identified", ""),
                            "comments": clean_r.get("comments", ""),
                            "file_ref": clean_r.get("file_ref", ""),
                        }
                        rows.append(row)
                        
        df = pd.DataFrame(rows)
        if not df.empty and 'LOG TIME' in df.columns:
            df['LOG TIME'] = pd.to_datetime(df['LOG TIME'], errors='coerce')
        return df
