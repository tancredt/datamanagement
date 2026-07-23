"""
Shared metadata helpers.
All device / location lookups now read from the unified
`mapping/locations.json` file. Exposure identifiers and areas are read
from `data/exposures/exposures.json`.
"""
import os
import json
import logging
from datetime import datetime

logger = logging.getLogger(__name__)

UNIFIED_LOCATIONS_FILE = "locations.json"
LAST_FILTERS_PREFIX = "last_filters_"

# ─────────────────────────────────────────────
# Unified locations.json loader
# ─────────────────────────────────────────────
def _load_unified_data(incident_path):
    """Return the parsed contents of mapping/locations.json."""
    if not incident_path:
        return {"maps": {"locations": []}}
    json_path = os.path.join(incident_path, "mapping", UNIFIED_LOCATIONS_FILE)
    if not os.path.exists(json_path):
        return {"maps": {"locations": []}}
    try:
        with open(json_path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        logger.error("Failed to load unified locations: %s", e)
        return {"maps": {"locations": []}}


def _ensure_marker_structure(marker):
    """
    Ensures the marker has the new explicit readings structure.
    Migrates old flat-list format in memory if needed.
    """
    if "readings" not in marker or not isinstance(marker.get("readings"), dict):
        old_readings = marker.get("readings", [])
        marker["readings"] = {"spot": [], "spectral": []}
        if isinstance(old_readings, list):
            for r in old_readings:
                if isinstance(r, dict) and "chemicals_identified" in r:
                    marker["readings"]["spectral"].append(r)
                elif isinstance(r, dict):
                    marker["readings"]["spot"].append(r)
    else:
        marker["readings"].setdefault("spot", [])
        marker["readings"].setdefault("spectral", [])

    if "device_locations" not in marker or not isinstance(marker.get("device_locations"), list):
        marker["device_locations"] = []


# ─────────────────────────────────────────────
# Devices
# ─────────────────────────────────────────────
def _get_area_devices(incident_path):
    """Pull device list from meta/devices.json for area data type."""
    json_path = os.path.join(incident_path, "meta", "devices.json")
    if not os.path.exists(json_path):
        return []
    try:
        with open(json_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, list):
            return sorted([str(d).strip() for d in data if str(d).strip()])
        return []
    except Exception as e:
        logger.error("Failed to load area devices: %s", e)
        return []


def get_available_devices(incident_path, data_type="spot"):
    devices = set()
    if not incident_path:
        return []

    # ── Exposure uses a completely different source ──
    if data_type == "exposure":
        return _get_exposure_devices(incident_path)

    # ── Area reads from meta/devices.json ──
    if data_type == "area":
        return _get_area_devices(incident_path)

    # ── Spot / Spectral read from the explicit sub-lists in readings ──
    data = _load_unified_data(incident_path)
    for loc in data.get("maps", {}).get("locations", []):
        for marker in loc.get("markers", []):
            _ensure_marker_structure(marker)

            if data_type == "spectral":
                for r in marker["readings"]["spectral"]:
                    device = r.get("device", "")
                    if device and str(device).strip():
                        devices.add(str(device).strip())
            else:  # spot
                for r in marker["readings"]["spot"]:
                    device = r.get("device", "")
                    if device and str(device).strip():
                        devices.add(str(device).strip())

    return sorted(devices)


def _get_exposure_devices(incident_path):
    """Pull unique identifiers from exposures.json."""
    devices = set()
    json_path = os.path.join(incident_path, "data", "exposures", "exposures.json")
    if not os.path.exists(json_path):
        return []
    try:
        with open(json_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        for exp in data.get("exposures", []):
            ident = exp.get("id", "")
            if ident and str(ident).strip():
                devices.add(str(ident).strip())
    except Exception as e:
        logger.error("Failed to load exposure devices: %s", e)
    return sorted(devices)


# ─────────────────────────────────────────────
# Locations / Sites / Areas
# ─────────────────────────────────────────────
def get_available_locations(incident_path, data_type="spot"):
    """
    Return a sorted list of unique marker labels relevant to the data type.
    - spot / spectral: labels that have at least one matching reading
    - area:            labels that have at least one device_locations entry
    - exposure:        areas from data/exposures/exposures.json
    """
    locations = set()
    if not incident_path:
        return []

    if data_type == "exposure":
        return _get_exposure_areas(incident_path)

    data = _load_unified_data(incident_path)
    for loc in data.get("maps", {}).get("locations", []):
        for marker in loc.get("markers", []):
            _ensure_marker_structure(marker)
            label = marker.get("label", "")
            if not label or not str(label).strip():
                continue
            label = str(label).strip()

            if data_type == "area":
                if marker["device_locations"]:
                    locations.add(label)
            elif data_type == "spectral":
                if marker["readings"]["spectral"]:
                    locations.add(label)
            else:  # spot
                if marker["readings"]["spot"]:
                    locations.add(label)

    return sorted(locations)


def _get_exposure_areas(incident_path):
    """Pull unique areas from exposures.json."""
    areas = set()
    json_path = os.path.join(incident_path, "data", "exposures", "exposures.json")
    if not os.path.exists(json_path):
        return []
    try:
        with open(json_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        for exp in data.get("exposures", []):
            area = exp.get("area", "")
            if area and str(area).strip():
                areas.add(str(area).strip())
    except Exception as e:
        logger.error("Failed to load exposure areas: %s", e)
    return sorted(areas)


# ─────────────────────────────────────────────
# Last-used filter persistence (per data type)
# ─────────────────────────────────────────────
def _filters_path(incident_path, data_type):
    meta_dir = os.path.join(incident_path, "meta")
    os.makedirs(meta_dir, exist_ok=True)
    return os.path.join(meta_dir, f"{LAST_FILTERS_PREFIX}{data_type}.json")


def _serialize_filters(filters):
    """Convert a filter dict to a JSON-safe version (datetimes → ISO)."""
    if not filters:
        return {}
    out = dict(filters)
    for key in ("start_time", "stop_time"):
        val = out.get(key)
        if isinstance(val, datetime):
            out[key] = val.isoformat()
    return out


def _deserialize_filters(raw):
    """Parse ISO datetime strings back into datetime objects."""
    if not raw:
        return {}
    out = dict(raw)
    for key in ("start_time", "stop_time"):
        val = out.get(key)
        if isinstance(val, str):
            try:
                out[key] = datetime.fromisoformat(val)
            except (ValueError, TypeError):
                out[key] = None
    return out


def load_last_filters(incident_path, data_type):
    """Load the last-used filters for a given data type (or {} if none)."""
    path = _filters_path(incident_path, data_type)
    if not os.path.exists(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            raw = json.load(f)
        return _deserialize_filters(raw)
    except Exception as e:
        logger.error("Failed to load last filters: %s", e)
        return {}


def save_last_filters(incident_path, data_type, filters):
    """Persist the current filters for a given data type."""
    path = _filters_path(incident_path, data_type)
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(_serialize_filters(filters), f, indent=2)
    except Exception as e:
        logger.error("Failed to save last filters: %s", e)
