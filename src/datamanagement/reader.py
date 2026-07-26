import os
import json
import logging
import pandas as pd
import numpy as np
from datamanagement.db_manager import IncidentDatabase

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
    if voc_corr == 1.0 and lel_corr == 1.0:
        return df
        
    for col in df.columns:
        col_lower = str(col).lower()
        # Match exact column OR columns with suffixes (e.g., VOC(ppm)_min for exposure data)
        # Using startswith safely ignores 'INVALID_VOC(ppm)' columns
        if col_lower == 'voc(ppm)' or col_lower.startswith('voc(ppm)_'):
            df[col] = pd.to_numeric(df[col], errors='coerce') * voc_corr
        elif col_lower == 'lel(%lel)' or col_lower.startswith('lel(%lel)_'):
            df[col] = pd.to_numeric(df[col], errors='coerce') * lel_corr
            
    return df


# ==========================================
# 2. AREA DATA (Reads from DB with Filters)
# ==========================================
def read_area_data(incident_path, start_time=None, stop_time=None, devices=None, sites=None, analytes=None, only_valid=False):
    """
    Queries the area_reading tables and returns a standardized DataFrame.
    Supports pre-filtering by time, devices, sites, analytes, and validity.
    """
    db = IncidentDatabase(incident_path)
    
    query = """
        SELECT ar.timestamp AS logtime, ar.serial_number, d.label AS device, 
               ar.status, ar.battery, ar.latitude, ar.longitude,
               m.label AS site,
               a.label AS analyte, ara.value, 
               COALESCE(ai.invalid_flag, 0) AS invalid_flag
        FROM area_reading ar
        LEFT JOIN device d ON ar.device_id = d.id
        LEFT JOIN area_reading_analyte ara ON ar.id = ara.area_reading_id
        LEFT JOIN analyte a ON ara.analyte_id = a.id
        LEFT JOIN area_invalidations ai ON ara.invalidation_id = ai.id
        LEFT JOIN area_location al ON ar.device_id = al.device_id 
            AND ar.timestamp > al.start_dt 
            AND (al.stop_dt IS NULL OR ar.timestamp <= al.stop_dt)
        LEFT JOIN marker m ON al.marker_id = m.id
        WHERE 1=1
    """
    params = []
    
    if start_time:
        query += " AND ar.timestamp > ?"
        params.append(str(start_time))
    if stop_time:
        query += " AND ar.timestamp <= ?"
        params.append(str(stop_time))
    if devices:
        placeholders = ','.join(['?'] * len(devices))
        query += f" AND d.label IN ({placeholders})"
        params.extend(devices)
    if sites:
        placeholders = ','.join(['?'] * len(sites))
        query += f" AND m.label IN ({placeholders})"
        params.extend(sites)
    if analytes:
        placeholders = ','.join(['?'] * len(analytes))
        query += f" AND a.label IN ({placeholders})"
        params.extend(analytes)
        
    if only_valid:
        # Natively exclude readings that have an invalidation_id assigned
        query += " AND ara.invalidation_id IS NULL"
        
    query += " ORDER BY ar.timestamp DESC"
    
    with db.get_connection() as conn:
        rows = conn.execute(query, params).fetchall()
        
    readings_dict = {}
    for row in rows:
        key = (row['serial_number'], row['logtime'])
        if key not in readings_dict:
            readings_dict[key] = {
                "logtime": row['logtime'],
                "serial_number": row['serial_number'],
                "device": row['device'] or "",
                "site": row['site'] or "",
                "status": row['status'] or "",
                "battery": row['battery'],
                "latitude": row['latitude'],
                "longitude": row['longitude'],
            }
        if row['analyte']:
            readings_dict[key][row['analyte']] = row['value']
            # Set to 0 if invalidation_id is NULL, otherwise use the DB's invalid_flag
            readings_dict[key][f"INVALID_{row['analyte']}"] = row['invalid_flag']
            
    area_readings = list(readings_dict.values())
    if not area_readings:
        return pd.DataFrame()

    analytes_data = db.get_analytes()
    available_analytes = [a['label'] for a in analytes_data]
    if analytes:
        available_analytes = [a for a in available_analytes if a in analytes]

    rows_out = []
    for r in area_readings:
        row = {
            "LOG TIME": r.get("logtime"),
            "DEVICE": r.get("device", ""),
            "SERIAL NUMBER": r.get("serial_number", ""),
            "SITE": r.get("site", ""),
            "STATUS": r.get("status", ""),
            "BATTERY": r.get("battery"),
            "Latitude": r.get("latitude"),
            "Longitude": r.get("longitude"),
        }
        for analyte in available_analytes:
            row[analyte] = r.get(analyte)
            # Retrieve the INVALID flag from the dictionary, default to 0 if the analyte wasn't present
            row[f"INVALID_{analyte}"] = r.get(f"INVALID_{analyte}", 0)
            
        rows_out.append(row)

    df = pd.DataFrame(rows_out)
    if not df.empty and 'LOG TIME' in df.columns:
        df['LOG TIME'] = pd.to_datetime(df['LOG TIME'], errors='coerce')
        
    df = _apply_corrections(df, incident_path)
    return df


# ==========================================
# 3. SPOT DATA (Reads from DB with Filters)
# ==========================================
def read_spot_data(incident_path, start_time=None, stop_time=None, devices=None, sites=None, analytes=None):
    """
    Queries the spot_reading table and returns a standardized DataFrame.
    Supports pre-filtering by time, devices, sites, and analytes.
    """
    db = IncidentDatabase(incident_path)
    
    query = """
        SELECT m.label AS location, d.label AS device, sr.timestamp AS logtime, 
               sr.comment AS observations, a.label AS analyte, sr.value
        FROM spot_reading sr
        JOIN marker m ON sr.marker_id = m.id
        LEFT JOIN device d ON sr.device_id = d.id
        JOIN analyte a ON sr.analyte_id = a.id
        WHERE 1=1
    """
    params = []
    
    if start_time:
        query += " AND sr.timestamp >= ?"
        params.append(str(start_time))
    if stop_time:
        query += " AND sr.timestamp <= ?"
        params.append(str(stop_time))
    if devices:
        placeholders = ','.join(['?'] * len(devices))
        query += f" AND d.label IN ({placeholders})"
        params.extend(devices)
    if sites:
        placeholders = ','.join(['?'] * len(sites))
        query += f" AND m.label IN ({placeholders})"
        params.extend(sites)
    if analytes:
        placeholders = ','.join(['?'] * len(analytes))
        query += f" AND a.label IN ({placeholders})"
        params.extend(analytes)
        
    query += " ORDER BY sr.timestamp DESC"
    
    with db.get_connection() as conn:
        rows = conn.execute(query, params).fetchall()
        
    readings_dict = {}
    for row in rows:
        key = (row['location'], row['device'] or "", row['logtime'])
        if key not in readings_dict:
            readings_dict[key] = {
                "location": row['location'], "device": row['device'] or "",
                "logtime": row['logtime'], "observations": row['observations'] or ""
            }
        readings_dict[key][row['analyte']] = row['value']
        
    spot_readings = list(readings_dict.values())
    if not spot_readings:
        return pd.DataFrame()

    analytes_data = db.get_analytes()
    available_analytes = [a['label'] for a in analytes_data]
    if analytes:
        available_analytes = [a for a in available_analytes if a in analytes]

    rows_out = []
    for r in spot_readings:
        row = {
            "LOG TIME": r.get("logtime"),
            "DEVICE": r.get("device", ""),
            "SITE": r.get("location", "") or "Unassigned",
            "observations": r.get("observations", ""),
            "Latitude": np.nan,
            "Longitude": np.nan,
        }
        for analyte in available_analytes:
            row[analyte] = r.get(analyte)
            row[f"INVALID_{analyte}"] = 0
        rows_out.append(row)

    df = pd.DataFrame(rows_out)
    if not df.empty and 'LOG TIME' in df.columns:
        df['LOG TIME'] = pd.to_datetime(df['LOG TIME'], errors='coerce')
        
    df = _apply_corrections(df, incident_path)
    return df


# ==========================================
# 4. SPECTRAL DATA (Reads from DB with Filters)
# ==========================================
def read_spectral_data(incident_path, start_time=None, stop_time=None,
                       devices=None, sites=None):
    """
    Queries the spectral_result table and returns a standardized DataFrame.
    Supports pre-filtering by time, devices, and sites.
    """
    db = IncidentDatabase(incident_path)
    query = """
        SELECT m.label AS location, d.label AS device, sr.timestamp AS logtime,
               sr.chemicals AS chemicals_identified, sr.comment AS comments,
               sr.file_ref
        FROM spectral_result sr
        JOIN marker m ON sr.marker_id = m.id
        LEFT JOIN device d ON sr.device_id = d.id
        WHERE 1=1
    """
    params = []
    if start_time:
        query += " AND sr.timestamp >= ?"
        params.append(str(start_time))
    if stop_time:
        query += " AND sr.timestamp <= ?"
        params.append(str(stop_time))
    if devices:
        placeholders = ','.join(['?'] * len(devices))
        query += f" AND d.label IN ({placeholders})"
        params.extend(devices)
    if sites:
        placeholders = ','.join(['?'] * len(sites))
        query += f" AND m.label IN ({placeholders})"
        params.extend(sites)
    query += " ORDER BY sr.timestamp DESC"

    with db.get_connection() as conn:
        rows = conn.execute(query, params).fetchall()

    if not rows:
        return pd.DataFrame()

    rows_out = []
    for row in rows:
        r = dict(row)
        rows_out.append({
            "LOG TIME": r.get("logtime"),
            "DEVICE": r.get("device", ""),
            "SITE": r.get("location", "") or "Unassigned",
            "chemicals_identified": r.get("chemicals_identified", ""),
            "comments": r.get("comments", ""),
            "file_ref": r.get("file_ref", ""),
        })

    df = pd.DataFrame(rows_out)
    if not df.empty and 'LOG TIME' in df.columns:
        df['LOG TIME'] = pd.to_datetime(df['LOG TIME'], errors='coerce')
    return df


# ==========================================
# 5. EXPOSURE DATA (Reads from DB with Filters)
# ==========================================
def read_exposure_data(incident_path, start_time=None, stop_time=None, devices=None, analytes=None):
    """
    Queries the exposure and exposure_reading tables, converts to a standardized
    summary DataFrame, and returns it. Supports pre-filtering.
    """
    db = IncidentDatabase(incident_path)
    
    query = """
        SELECT e.identifier, e.start_dt, e.stop_dt, e.area, e.activities, 
               e.respiratory, e.clothing, e.footwear, d.label AS device,
               a.label AS analyte, er.min_value, er.max_value, er.mean_value
        FROM exposure e
        LEFT JOIN device d ON e.device_id = d.id
        LEFT JOIN exposure_reading er ON e.id = er.exposure_id
        LEFT JOIN analyte a ON er.analyte_id = a.id
        WHERE 1=1
    """
    params = []
    
    if start_time:
        query += " AND e.start_dt >= ?"
        params.append(str(start_time))
    if stop_time:
        query += " AND e.start_dt <= ?"
        params.append(str(stop_time))
    if devices:
        placeholders = ','.join(['?'] * len(devices))
        query += f" AND d.label IN ({placeholders})"
        params.extend(devices)
    if analytes:
        placeholders = ','.join(['?'] * len(analytes))
        query += f" AND a.label IN ({placeholders})"
        params.extend(analytes)
        
    query += " ORDER BY e.start_dt DESC"
    
    with db.get_connection() as conn:
        rows = conn.execute(query, params).fetchall()
        
    exposures_dict = {}
    for row in rows:
        key = (row['identifier'], row['start_dt'])
        if key not in exposures_dict:
            exposures_dict[key] = {
                "id": row['identifier'],
                "device": row['device'] or "",
                "start": row['start_dt'],
                "stop": row['stop_dt'],
                "area": row['area'] or "",
                "activities": row['activities'] or "",
                "resp_protection": row['respiratory'] or "",
                "clothing": row['clothing'] or "",
                "footwear": row['footwear'] or "",
                "values": {}
            }
        if row['analyte']:
            exposures_dict[key]["values"][row['analyte']] = {
                "min": row['min_value'],
                "max": row['max_value'],
                "mean": row['mean_value']
            }
            
    exposures = list(exposures_dict.values())
    if not exposures:
        return pd.DataFrame()

    analytes_data = db.get_analytes()
    available_analytes = [a['label'] for a in analytes_data]
    if analytes:
        available_analytes = [a for a in available_analytes if a in analytes]

    rows_out = []
    for exp in exposures:
        row = {
            "LOG TIME": exp.get("start"),
            "DEVICE": exp.get("id", ""),
            "SITE": exp.get("area", ""),
        }
        values = exp.get("values", {})
        for analyte in available_analytes:
            if analyte in values:
                v = values[analyte]
                if isinstance(v, dict):
                    if v.get("min") is not None: row[f"{analyte}_min"] = float(v["min"])
                    if v.get("max") is not None: row[f"{analyte}_max"] = float(v["max"])
                    if v.get("mean") is not None: row[f"{analyte}_mean"] = float(v["mean"])
        rows_out.append(row)

    df = pd.DataFrame(rows_out)
    if not df.empty and 'LOG TIME' in df.columns:
        df['LOG TIME'] = pd.to_datetime(df['LOG TIME'], errors='coerce')
        
    df = _apply_corrections(df, incident_path)
    return df

# ==========================================
# 6. BATTERY DATA (Efficient query for battery analysis)
# ==========================================
def read_battery_data(incident_path, device_label=None):
    """
    Efficiently queries only battery and timestamp data for a specific device.
    Returns a minimal DataFrame with LOG TIME, DEVICE, and BATTERY columns.
    
    Args:
        incident_path: Path to the incident directory
        device_label: Optional device label to filter by. If None, returns all devices.
    
    Returns:
        DataFrame with columns: LOG TIME, DEVICE, BATTERY
    """
    db = IncidentDatabase(incident_path)
    
    query = """
        SELECT ar.timestamp AS logtime, d.label AS device, ar.battery
        FROM area_reading ar
        LEFT JOIN device d ON ar.device_id = d.id
        WHERE ar.battery IS NOT NULL
    """
    params = []
    
    if device_label:
        query += " AND d.label = ?"
        params.append(device_label)
    
    query += " ORDER BY ar.timestamp ASC"
    
    with db.get_connection() as conn:
        rows = conn.execute(query, params).fetchall()
    
    if not rows:
        return pd.DataFrame(columns=['LOG TIME', 'DEVICE', 'BATTERY'])
    
    data = []
    for row in rows:
        data.append({
            'LOG TIME': row['logtime'],
            'DEVICE': row['device'] or '',
            'BATTERY': row['battery']
        })
    
    df = pd.DataFrame(data)
    
    if not df.empty and 'LOG TIME' in df.columns:
        df['LOG TIME'] = pd.to_datetime(df['LOG TIME'], errors='coerce')
    
    return df

# ==========================================
# 6. OVERVIEW STATISTICS
# ==========================================


