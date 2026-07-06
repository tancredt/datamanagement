import os
import json
import logging
import pandas as pd

logger = logging.getLogger(__name__)

# ==========================================
# 1. UPDATE SITE FROM DEVICE LOG
# ==========================================
def update_site_from_device_log(incident_path):
    """
    Reads area_locations.json and updates the SITE column in area_data.csv 
    based on the device's location between start and stop times.
    """
    processed_file = os.path.join(incident_path, "data", "processed", "area_data.csv")
    area_locations_file = os.path.join(incident_path, "mapping", "area_locations.json")
    
    if not os.path.exists(processed_file) or not os.path.exists(area_locations_file):
        return processed_file
        
    try:
        df = pd.read_csv(processed_file)
        # Reset all sites to "" in the processed dataframe
        df['SITE'] = ""
        
        # Clean up DEVICE column for matching
        if 'DEVICE' in df.columns:
            df['DEVICE'] = df['DEVICE'].fillna("").astype(str).str.strip()
        else:
            df['DEVICE'] = ""
            
        df['LOG TIME'] = pd.to_datetime(df['LOG TIME'], errors='coerce')
        
        with open(area_locations_file, 'r', encoding='utf-8') as f:
            data = json.load(f)
            
        device_logs = []
        for loc in data.get("maps", {}).get("locations", []):
            for marker in loc.get("markers", []):
                device_logs.extend(marker.get("device_log", []))
                
        for log_entry in device_logs:
            # Match against the DEVICE label instead of serial number
            device_label = str(log_entry.get("device", log_entry.get("serial", ""))).strip()
            start_time = log_entry.get("start")
            stop_time = log_entry.get("stop")
            location = str(log_entry.get("location", "")).strip()
            
            if not device_label or not start_time or not location:
                continue
                
            start_dt = pd.to_datetime(start_time, errors='coerce')
            # If the stop_dt is empty, it means the device is still there, so set it to the far future
            stop_dt = pd.to_datetime(stop_time, errors='coerce') if stop_time else pd.Timestamp('9999-12-31 23:59:59')
            
            if pd.isna(start_dt) or pd.isna(stop_dt):
                continue
                
            # Device is at a location if the log time is greater than start_dt and less than or equal to stop time
            mask = (df['DEVICE'] == device_label) & (df['LOG TIME'] > start_dt) & (df['LOG TIME'] <= stop_dt)
            df.loc[mask, 'SITE'] = location
            
        df.to_csv(processed_file, index=False)
    except Exception as e:
        logger.error(f"Failed to update SITE: {e}")
        
    return processed_file


# ==========================================
# 2. UPDATE VALIDATIONS
# ==========================================
def update_validations(incident_path):
    """
    Reads device_validations.json and updates the INVALID_{gas} columns 
    in area_data.csv based on validation start/stop times.
    """
    processed_file = os.path.join(incident_path, "data", "processed", "area_data.csv")
    validations_file = os.path.join(incident_path, "mapping", "device_validations.json")
    
    if not os.path.exists(processed_file) or not os.path.exists(validations_file):
        return processed_file
        
    try:
        df = pd.read_csv(processed_file)
        
        # Reset all INVALID_<gas> columns to 0
        invalid_cols = [c for c in df.columns if c.upper().startswith('INVALID_')]
        for col in invalid_cols:
            df[col] = 0
            
        df['LOG TIME'] = pd.to_datetime(df['LOG TIME'], errors='coerce')
        
        with open(validations_file, 'r', encoding='utf-8') as f:
            data = json.load(f)
            
        for val_entry in data.get("devices", []):
            # Match against the DEVICE label instead of serial number
            device_label = str(val_entry.get("device", val_entry.get("serial", ""))).strip()
            start_time = val_entry.get("start")
            stop_time = val_entry.get("stop")
            gases = val_entry.get("gases", [])
            
            if not device_label or not start_time or not gases:
                continue
                
            start_dt = pd.to_datetime(start_time, errors='coerce')
            stop_dt = pd.to_datetime(stop_time, errors='coerce') if stop_time else pd.Timestamp('9999-12-31 23:59:59')
            
            if pd.isna(start_dt) or pd.isna(stop_dt):
                continue
                
            mask = (df['DEVICE'] == device_label) & (df['LOG TIME'] > start_dt) & (df['LOG TIME'] <= stop_dt)
            
            for gas in gases:
                inv_col = next((c for c in df.columns if c.upper() == f"INVALID_{gas}".upper()), None)
                if inv_col:
                    df.loc[mask, inv_col] = 1
                    
        df.to_csv(processed_file, index=False)
    except Exception as e:
        logger.error(f"Failed to update INVALID flags: {e}")
        
    return processed_file
