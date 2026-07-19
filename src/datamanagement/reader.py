import os
import json
import logging
import pandas as pd
import numpy as np

logger = logging.getLogger(__name__)

# ==========================================
# 1. AREA DATA (Reads processed CSV)
# ==========================================
def read_area_data(incident_path):
    """
    Reads the processed area_data.csv and returns a DataFrame.
    Automatically parses the 'LOG TIME' column to datetime objects.
    """
    file_path = os.path.join(incident_path, "data", "processed", "area_data.csv")
    if not os.path.exists(file_path):
        return pd.DataFrame()
    try:
        df = pd.read_csv(file_path)
        if 'LOG TIME' in df.columns:
            df['LOG TIME'] = pd.to_datetime(df['LOG TIME'], errors='coerce')
        return df
    except Exception as e:
        logger.error(f"Failed to read area data: {e}")
        return pd.DataFrame()


# ==========================================
# 2. SPOT DATA (Reads raw JSON -> Saves CSV -> Returns DF)
# ==========================================
def read_spot_data(incident_path):
    """
    Reads spot_locations.json, converts it to a standardized DataFrame,
    initializes INVALID flags, saves to data/processed/spot_data.csv, 
    and returns the DataFrame.
    """
    json_path = os.path.join(incident_path, "mapping", "spot_locations.json")
    processed_dir = os.path.join(incident_path, "data", "processed")
    os.makedirs(processed_dir, exist_ok=True)

    if not os.path.exists(json_path):
        return pd.DataFrame()

    try:
        with open(json_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
    except Exception as e:
        logger.error(f"Failed to load spot locations JSON: {e}")
        return pd.DataFrame()

    rows = []
    analytes_found = set()
    base_keys = {'datetime', 'device', 'observations'}

    for loc in data.get("maps", {}).get("locations", []):
        for marker in loc.get("markers", []):
            site = marker.get("label", "")
            for r in marker.get("readings", []):
                row = {
                    "LOG TIME": r.get("datetime"),
                    "DEVICE": r.get("device", ""),
                    "SITE": site,
                    "observations": r.get("observations", ""),
                    "Latitude": np.nan,
                    "Longitude": np.nan
                }
                for k, v in r.items():
                    if k not in base_keys and k not in row:
                        row[k] = v
                        analytes_found.add(k)
                rows.append(row)

    if not rows:
        return pd.DataFrame()

    df = pd.DataFrame(rows)
    df['LOG TIME'] = pd.to_datetime(df['LOG TIME'], errors='coerce')
    
    for analyte in analytes_found:
        df[f"INVALID_{analyte}"] = 0

    # Save the processed file
    processed_file = os.path.join(processed_dir, "spot_data.csv")
    df.to_csv(processed_file, index=False)
    
    return df


# ==========================================
# 3. SPECTRAL DATA (Reads raw JSON -> Saves CSV -> Returns DF)
# ==========================================
def read_spectral_data(incident_path):
    """
    Reads spectral_locations.json, converts it to a standardized DataFrame,
    initializes INVALID flags, saves to data/processed/spectral_data.csv,
    and returns the DataFrame.
    """
    json_path = os.path.join(incident_path, "mapping", "spectral_locations.json")
    processed_dir = os.path.join(incident_path, "data", "processed")
    os.makedirs(processed_dir, exist_ok=True)

    if not os.path.exists(json_path):
        logger.warning(f"Spectral locations JSON not found at {json_path}")
        return pd.DataFrame()

    try:
        with open(json_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
    except Exception as e:
        logger.error(f"Failed to load spectral locations JSON: {e}")
        return pd.DataFrame()

    rows = []
    analytes_found = set()
    base_keys = {'datetime', 'device', 'chemicals_identified', 'comments', 'file_ref'}

    for loc in data.get("maps", {}).get("locations", []):
        for marker in loc.get("markers", []):
            site = marker.get("label", "")
            for r in marker.get("readings", []):
                row = {
                    "LOG TIME": r.get("datetime"),
                    "DEVICE": r.get("device", ""),
                    "SITE": site,
                    "chemicals_identified": r.get("chemicals_identified", ""),
                    "comments": r.get("comments", ""),
                    "file_ref": r.get("file_ref", "")
                }
                for k, v in r.items():
                    if k not in base_keys and k not in row:
                        row[k] = v
                        analytes_found.add(k)
                rows.append(row)

    if not rows:
        return pd.DataFrame()

    df = pd.DataFrame(rows)
    df['LOG TIME'] = pd.to_datetime(df['LOG TIME'], errors='coerce')
    
    for analyte in analytes_found:
        df[f"INVALID_{analyte}"] = 0

    # Save the processed file
    processed_file = os.path.join(processed_dir, "spectral_data.csv")
    df.to_csv(processed_file, index=False)
    
    return df

# Add this to the bottom of reader.py

#==========================================
#4. EXPOSURE DATA (Reads raw JSON -> Returns Summary DF)
#==========================================
def read_exposure_data(incident_path):
    """
    Reads exposures.json, converts it to a standardized summary DataFrame,
    and returns it. Formats analytes into {analyte}_min, {analyte}_max, 
    and {analyte}_mean columns for direct use in summary views.
    """
    json_path = os.path.join(incident_path, "data", "exposures", "exposures.json")
    if not os.path.exists(json_path):
        return pd.DataFrame()

    try:
        with open(json_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
    except Exception as e:
        logger.error(f"Failed to load exposures JSON: {e}")
        return pd.DataFrame()

    # Helper to recursively strip whitespace from keys and string values
    def clean(obj):
        if isinstance(obj, dict):
            return {k.strip(): clean(v) for k, v in obj.items()}
        elif isinstance(obj, list):
            return [clean(elem) for elem in obj]
        elif isinstance(obj, str):
            return obj.strip()
        return obj

    data = clean(data)

    # Load analytes.json to map raw responder names (e.g., "CO(ppm)") to standard names ("CO")
    current_dir = os.path.dirname(os.path.abspath(__file__))
    analyte_config_path = os.path.normpath(os.path.join(current_dir, '..', 'static', 'lists', 'analytes.json'))
    responder_to_name = {}
    if os.path.exists(analyte_config_path):
        try:
            with open(analyte_config_path, 'r', encoding='utf-8') as f:
                analyte_config = json.load(f)
                for analyte in analyte_config.get("analytes", []):
                    resp_name = analyte.get("responder_name")
                    std_name = analyte.get("name")
                    if resp_name and std_name:
                        responder_to_name[resp_name.lower()] = std_name
        except Exception as e:
            logger.error(f"Failed to load analytes config for exposures: {e}")

    rows = []
    for exp in data.get("exposures", []):
        row = {
            "LOG TIME": exp.get("start"),
            "DEVICE": exp.get("id", ""),  # Map 'id' to 'DEVICE' (Identifier)
            "SITE": exp.get("area", ""),  # Map 'area' to 'SITE'
        }
        
        values = exp.get("values", {})
        for k, v in values.items():
            # Map raw key to standard analyte name, fallback to stripped raw key
            base_name = responder_to_name.get(k.lower(), k)
            
            if isinstance(v, dict):
                if "min" in v and v["min"] is not None:
                    row[f"{base_name}_min"] = float(v["min"])
                if "max" in v and v["max"] is not None:
                    row[f"{base_name}_max"] = float(v["max"])
                if "mean" in v and v["mean"] is not None:
                    row[f"{base_name}_mean"] = float(v["mean"])
            else:
                # Fallback if it's just a single value instead of a dict
                try:
                    row[base_name] = float(v)
                except (ValueError, TypeError):
                    pass
        rows.append(row)

    if not rows:
        return pd.DataFrame()

    df = pd.DataFrame(rows)
    if 'LOG TIME' in df.columns:
        df['LOG TIME'] = pd.to_datetime(df['LOG TIME'], errors='coerce')
        
    return df
