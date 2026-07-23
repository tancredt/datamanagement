import os
import json
import logging
import pandas as pd
import numpy as np

logger = logging.getLogger(__name__)

# ==========================================
# 1. HELPER FUNCTIONS
# ==========================================
def _load_preferences(incident_path):
    """Loads VOC and LEL correction factors from preferences.json."""
    prefs_file = os.path.join(incident_path, "meta", "preferences.json")
    voc_corr = 1.0
    lel_corr = 1.0
    if os.path.exists(prefs_file):
        try:
            with open(prefs_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
                prefs = data.get("preferences", {})
                voc_corr = float(prefs.get("voc_correction", 1.0))
                lel_corr = float(prefs.get("lel_correction", 1.0))
        except Exception as e:
            logger.error(f"Failed to load preferences: {e}")
    return voc_corr, lel_corr

def _apply_corrections(df, incident_path):
    """Applies VOC and LEL correction factors to the DataFrame."""
    if df is None or df.empty:
        return df
        
    voc_corr, lel_corr = _load_preferences(incident_path)
    
    # If both are 1.0, no need to iterate
    if voc_corr == 1.0 and lel_corr == 1.0:
        return df
        
    for col in df.columns:
        col_lower = str(col).lower()
        if col_lower == 'voc(ppm)':
            df[col] = pd.to_numeric(df[col], errors='coerce') * voc_corr
        elif col_lower == 'lel(%lel)':
            df[col] = pd.to_numeric(df[col], errors='coerce') * lel_corr
            
    return df

# ==========================================
# 2. AREA DATA (Reads processed CSV)
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
        # ✅ FIX: Explicitly define string columns to prevent DtypeWarning
        df = pd.read_csv(file_path, dtype={
            'STATUS': str,
            'SITE': str,
            'DEVICE': str,
            'SERIAL NUMBER': str,
            'MODEL NAME': str,
            'TIME ZONE': str
        })
        if 'LOG TIME' in df.columns:
            df['LOG TIME'] = pd.to_datetime(df['LOG TIME'], errors='coerce')
            
        # Apply VOC/LEL corrections dynamically
        df = _apply_corrections(df, incident_path)
        
        return df
    except Exception as e:
        logger.error(f"Failed to read area data: {e}")
        return pd.DataFrame()

def read_spot_data(incident_path):
    """Reads unified locations.json, filters for spot readings, and returns a DataFrame."""
    from datamanagement.locations import LocationManager
    import json
    manager = LocationManager(incident_path)
    
    # Load available analytes from config
    current_dir = os.path.dirname(os.path.abspath(__file__))
    analyte_config_path = os.path.normpath(os.path.join(current_dir, '..', 'static', 'lists', 'analytes.json'))
    available_analytes = []
    if os.path.exists(analyte_config_path):
        try:
            with open(analyte_config_path, 'r', encoding='utf-8') as f:
                analyte_config = json.load(f)
                for analyte in analyte_config.get("analytes", []):
                    clean_analyte = {k.strip(): str(v).strip() for k, v in analyte.items()}
                    name = clean_analyte.get("name")
                    if name:
                        available_analytes.append(name)
        except Exception as e:
            logger.error(f"Failed to load analytes config: {e}")
            
    # Pass available_analytes to to_dataframe
    df = manager.to_dataframe(available_analytes=available_analytes, reading_type="spot")
    if df.empty:
        return pd.DataFrame()
        
    # Apply VOC/LEL corrections dynamically
    df = _apply_corrections(df, incident_path)
    
    processed_dir = os.path.join(incident_path, "data", "processed")
    os.makedirs(processed_dir, exist_ok=True)
    processed_file = os.path.join(processed_dir, "spot_data.csv")
    df.to_csv(processed_file, index=False)
    return df

def read_spectral_data(incident_path):
    """Reads unified locations.json, filters for spectral readings, and returns a DataFrame."""
    from datamanagement.locations import LocationManager
    manager = LocationManager(incident_path)
    
    # Spectral doesn't need analyte columns, just metadata
    df = manager.to_dataframe(reading_type="spectral")
    if df.empty:
        return pd.DataFrame()
        
    processed_dir = os.path.join(incident_path, "data", "processed")
    os.makedirs(processed_dir, exist_ok=True)
    processed_file = os.path.join(processed_dir, "spectral_data.csv")
    df.to_csv(processed_file, index=False)
    return df

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
