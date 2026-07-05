import os
import json

def get_available_devices(incident_path, data_type="spot"):
    """
    Fetches unique device labels based on the data type.
    - Spot: reads from spot_locations.json
    - Area: reads from meta/devices.json
    - Spectral: reads from spectral_locations.json
    """
    devices = set()
    if not incident_path:
        return []

    if data_type == "spot":
        json_path = os.path.join(incident_path, "mapping", "spot_locations.json")
        if os.path.exists(json_path):
            try:
                with open(json_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                for loc in data.get("maps", {}).get("locations", []):
                    for marker in loc.get("markers", []):
                        for entry in marker.get("readings", []):
                            device = entry.get("device")
                            if device:
                                devices.add(str(device).strip())
            except Exception:
                pass
                
    elif data_type == "spectral":
        json_path = os.path.join(incident_path, "mapping", "spectral_locations.json")
        if os.path.exists(json_path):
            try:
                with open(json_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                for loc in data.get("maps", {}).get("locations", []):
                    for marker in loc.get("markers", []):
                        for entry in marker.get("readings", []):
                            device = entry.get("device")
                            if device:
                                devices.add(str(device).strip())
            except Exception:
                pass
                
    else: # Area
        json_path = os.path.join(incident_path, "meta", "devices.json")
        if os.path.exists(json_path):
            try:
                with open(json_path, 'r', encoding='utf-8') as f:
                    devices.update(json.load(f))
            except Exception:
                pass

    return sorted(list(devices))


def get_available_locations(incident_path, data_type="spot"):
    """
    Fetches unique marker labels from spot, area, or spectral location JSONs.
    """
    locations = set()
    if not incident_path:
        return []

    if data_type == "spot":
        filename = "spot_locations.json"
    elif data_type == "spectral":
        filename = "spectral_locations.json"
    else:
        filename = "area_locations.json"

    json_path = os.path.join(incident_path, "mapping", filename)
    if os.path.exists(json_path):
        try:
            with open(json_path, 'r', encoding='utf-8') as f:
                raw_data = json.load(f)
                data = _clean_json_keys(raw_data) if data_type == "spectral" else raw_data
                
            for loc in data.get("maps", {}).get("locations", []):
                for marker in loc.get("markers", []):
                    label = marker.get("label")
                    if label:
                        locations.add(str(label).strip())
        except Exception:
            pass

    return sorted(list(locations))
