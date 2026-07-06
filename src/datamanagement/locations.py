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


# ==========================================
# 2. LOCATION MANAGER CLASS
# ==========================================
class LocationManager:
    """
    Common interface for managing spot, area, and spectral location JSON files.
    Handles loading, saving, structure validation, and data extraction.
    """
    def __init__(self, incident_path, mode="spot"):
        self.incident_path = incident_path
        self.mode = mode  # "spot", "area", "spectral"
        self.mapping_dir = os.path.join(incident_path, "mapping")
        self.json_file = os.path.join(self.mapping_dir, f"{mode}_locations.json")
        self.data = {"maps": {"locations": []}}
        self.load()

    def load(self):
        """Loads the JSON file into memory."""
        if os.path.exists(self.json_file):
            try:
                with open(self.json_file, 'r', encoding='utf-8') as f:
                    self.data = json.load(f)
            except Exception as e:
                logger.error(f"Failed to load {self.json_file}: {e}")
                self.data = {"maps": {"locations": []}}
        else:
            self.data = {"maps": {"locations": []}}

    def save(self):
        """Saves the in-memory data structure back to the JSON file."""
        os.makedirs(self.mapping_dir, exist_ok=True)
        try:
            with open(self.json_file, 'w', encoding='utf-8') as f:
                json.dump(self.data, f, indent=2)
        except Exception as e:
            logger.error(f"Failed to save {self.json_file}: {e}")

    def ensure_structure(self):
        """Ensures that all markers have the required keys (readings or device_log)."""
        required_key = "device_log" if self.mode == "area" else "readings"
        for loc in self.data.get("maps", {}).get("locations", []):
            for marker in loc.get("markers", []):
                if required_key not in marker:
                    marker[required_key] = []

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
            locations_list.append({
                "filename": fname,
                "markers": markers
            })
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
            locations_list.append({
                "filename": fname,
                "markers": []
            })
            self.data["maps"]["locations"] = locations_list
            self.save()
        return fname

    def get_all_used_labels(self):
        """Gathers all used labels globally across all maps and all data types."""
        used_labels = set()
        for mode in ["spot", "area", "spectral"]:
            json_file = os.path.join(self.mapping_dir, f"{mode}_locations.json")
            if os.path.exists(json_file):
                try:
                    with open(json_file, 'r', encoding='utf-8') as f:
                        data = json.load(f)
                    for loc in data.get("maps", {}).get("locations", []):
                        for m in loc.get("markers", []):
                            lbl = m.get("label")
                            if lbl: used_labels.add(lbl)
                except Exception as e:
                    logger.error(f"Failed to load global labels from {json_file}: {e}")
        return used_labels

    def get_available_devices(self):
        """Loads unique device labels from the readings."""
        devices = set()
        for loc in self.data.get("maps", {}).get("locations", []):
            for marker in loc.get("markers", []):
                for r in marker.get("readings", []):
                    device = r.get("device")
                    if device and str(device).strip():
                        devices.add(str(device).strip())
        return sorted(list(devices))

    def get_available_labels(self):
        """Loads unique marker labels from the maps."""
        labels = set()
        for loc in self.data.get("maps", {}).get("locations", []):
            for marker in loc.get("markers", []):
                label = marker.get("label", "")
                if label:
                    labels.add(label)
        return sorted(list(labels))

    def get_flat_readings(self):
        """Flattens readings for UI tables (Spot/Spectral)."""
        readings = []
        for loc in self.data.get("maps", {}).get("locations", []):
            for marker in loc.get("markers", []):
                label = marker.get("label", "")
                for r in marker.get("readings", []):
                    clean_r = {k.strip(): v for k, v in r.items()}
                    row = {
                        "location": label,
                        "device": clean_r.get("device", ""),
                        "logtime": clean_r.get("datetime", ""),
                    }
                    if self.mode == "spot":
                        row["observations"] = clean_r.get("observations", "")
                    elif self.mode == "spectral":
                        row["chemicals_identified"] = clean_r.get("chemicals_identified", "")
                        row["comments"] = clean_r.get("comments", "")
                        row["file_ref"] = clean_r.get("file_ref", "")
                    
                    # Add any extra keys (like analytes for spot)
                    for k, v in clean_r.items():
                        if k not in row and k not in ["datetime", "device", "observations", "chemicals_identified", "comments", "file_ref"]:
                            row[k] = v
                    readings.append(row)
        return readings

    def set_flat_readings(self, flat_readings, available_analytes=None):
        """Reconstructs the nested JSON structure from a flat list of readings and saves it."""
        locations_list = self.data.get("maps", {}).get("locations", [])
        
        # Clear existing readings
        for loc in locations_list:
            for marker in loc.get("markers", []):
                marker["readings"] = []
                
        # Rebuild readings
        for loc in locations_list:
            for marker in loc.get("markers", []):
                label = marker.get("label", "")
                for r in flat_readings:
                    if r.get("location") == label:
                        reading_dict = {
                            "datetime": r.get("logtime", ""),
                            "device": r.get("device", ""),
                        }
                        if self.mode == "spot":
                            reading_dict["observations"] = r.get("observations", "")
                            if available_analytes:
                                for analyte in available_analytes:
                                    if analyte in r and r[analyte] is not None:
                                        reading_dict[analyte] = r[analyte]
                        elif self.mode == "spectral":
                            reading_dict["chemicals_identified"] = r.get("chemicals_identified", "")
                            reading_dict["comments"] = r.get("comments", "")
                            reading_dict["file_ref"] = r.get("file_ref", "")
                            
                        marker["readings"].append(reading_dict)
        self.save()

    def to_dataframe(self, available_analytes=None):
        """Converts the location data to a pandas DataFrame (used by main_window for overview/tables)."""
        rows = []
        for loc in self.data.get("maps", {}).get("locations", []):
            for marker in loc.get("markers", []):
                site = marker.get("label", "") or "Unassigned"
                for r in marker.get("readings", []):
                    clean_r = {k.strip(): v for k, v in r.items()}
                    row = {
                        "LOG TIME": clean_r.get("datetime"),
                        "DEVICE": clean_r.get("device", ""),
                        "SITE": site,
                    }
                    if self.mode == "spot":
                        row["observations"] = clean_r.get("observations", "")
                        row["Latitude"] = np.nan
                        row["Longitude"] = np.nan
                        if available_analytes:
                            for analyte in available_analytes:
                                row[analyte] = clean_r.get(analyte)
                                row[f"INVALID_{analyte}"] = 0
                    elif self.mode == "spectral":
                        row["chemicals_identified"] = clean_r.get("chemicals_identified", "")
                        row["comments"] = clean_r.get("comments", "")
                        row["file_ref"] = clean_r.get("file_ref", "")
                        
                    rows.append(row)
        
        df = pd.DataFrame(rows)
        if not df.empty and 'LOG TIME' in df.columns:
            df['LOG TIME'] = pd.to_datetime(df['LOG TIME'], errors='coerce')
        return df
