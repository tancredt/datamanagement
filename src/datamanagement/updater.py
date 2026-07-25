import os
import logging
import pandas as pd
import sqlite3

logger = logging.getLogger(__name__)

# ==========================================
# 1. UPDATE SITE FROM DEVICE LOG
# ==========================================
def update_site_from_device_locations(incident_path):
    """
    Queries area_location table and updates the SITE column in area_data.csv
    based on the device's location between start and stop times.
    """
    processed_file = os.path.join(incident_path, "data", "processed", "area_data.csv")
    db_path = os.path.join(incident_path, "meta", "incident.db")
    
    if not os.path.exists(processed_file) or not os.path.exists(db_path):
        return processed_file
    
    try:
        df = pd.read_csv(processed_file)
        df['SITE'] = ""
        if 'DEVICE' in df.columns:
            df['DEVICE'] = df['DEVICE'].fillna("").astype(str).str.strip()
        else:
            df['DEVICE'] = ""
        df['LOG TIME'] = pd.to_datetime(df['LOG TIME'], errors='coerce')
        
        # Query device locations from database
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        
        query = """
            SELECT d.label AS device, m.label AS location, al.start_dt, al.stop_dt
            FROM area_location al
            LEFT JOIN device d ON al.device_id = d.id
            LEFT JOIN marker m ON al.marker_id = m.id
        """
        
        device_locations = pd.read_sql_query(query, conn)
        conn.close()
        
        for _, loc_entry in device_locations.iterrows():
            device_label = str(loc_entry.get("device", "")).strip()
            start_time = loc_entry.get("start_dt")
            stop_time = loc_entry.get("stop_dt")
            location = str(loc_entry.get("location", "")).strip()
            
            if not device_label or not start_time or not location:
                continue
            
            start_dt = pd.to_datetime(start_time, errors='coerce')
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
    Queries area_invalidations table and updates the INVALID_{analyte} columns
    in area_data.csv based on validation start/stop times.
    """
    processed_file = os.path.join(incident_path, "data", "processed", "area_data.csv")
    db_path = os.path.join(incident_path, "meta", "incident.db")
    
    if not os.path.exists(processed_file) or not os.path.exists(db_path):
        return processed_file
    
    try:
        df = pd.read_csv(processed_file)
        # Reset all INVALID_<gas> columns to 0
        invalid_cols = [c for c in df.columns if c.upper().startswith('INVALID_')]
        for col in invalid_cols:
            df[col] = 0
        df['LOG TIME'] = pd.to_datetime(df['LOG TIME'], errors='coerce')
        
        # Query validations from database
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        
        query = """
            SELECT d.label AS device, a.label AS analyte, ai.start_dt, ai.stop_dt
            FROM area_invalidations ai
            LEFT JOIN device d ON ai.device_id = d.id
            JOIN analyte a ON ai.analyte_id = a.id
            WHERE ai.invalid_flag = 1
        """
        
        validations = pd.read_sql_query(query, conn)
        conn.close()
        
        for _, val_entry in validations.iterrows():
            device_label = str(val_entry.get("device", "")).strip()
            start_time = val_entry.get("start_dt")
            stop_time = val_entry.get("stop_dt")
            analyte = str(val_entry.get("analyte", "")).strip()
            
            if not device_label or not start_time or not analyte:
                continue
            
            start_dt = pd.to_datetime(start_time, errors='coerce')
            stop_dt = pd.to_datetime(stop_time, errors='coerce') if stop_time else pd.Timestamp('9999-12-31 23:59:59')
            
            if pd.isna(start_dt) or pd.isna(stop_dt):
                continue
            
            mask = (df['DEVICE'] == device_label) & (df['LOG TIME'] > start_dt) & (df['LOG TIME'] <= stop_dt)
            
            inv_col = next((c for c in df.columns if c.upper() == f"INVALID_{analyte}".upper()), None)
            if inv_col:
                df.loc[mask, inv_col] = 1
        
        df.to_csv(processed_file, index=False)
    except Exception as e:
        logger.error(f"Failed to update INVALID flags: {e}")
    
    return processed_file
