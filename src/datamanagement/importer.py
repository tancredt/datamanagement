import os
import shutil
import logging
import pandas as pd
import numpy as np
import json

logger = logging.getLogger(__name__)

#This file is generally for importing raw area data

# ==========================================
# 1. UTILITIES
# ==========================================
def copy_files_to_realtime(incident_path, selected_files):
    """Copies selected raw CSV files into the incident's realtime directory."""
    realtime_dir = os.path.join(incident_path, "data", "realtime")
    os.makedirs(realtime_dir, exist_ok=True)
    if not selected_files:
        return 0
        
    copied_count = 0
    for csv_file in selected_files:
        if not os.path.exists(csv_file) or os.path.getsize(csv_file) == 0:
            continue
        dest_file = os.path.join(realtime_dir, os.path.basename(csv_file))
        try:
            shutil.copy2(csv_file, dest_file)
            copied_count += 1
        except Exception as e:
            logger.error(f"Failed to copy {csv_file}: {e}")
    return copied_count


# ==========================================
# 2. AREA DATA IMPORT (Raw CSVs)
# ==========================================
def _save_area_meta(incident_path, devices, analytes):
    """Helper to save unique area devices and analytes to the meta directory."""
    meta_dir = os.path.join(incident_path, "meta")
    os.makedirs(meta_dir, exist_ok=True)
    
    valid_devices = sorted([
        str(d).strip() for d in devices 
        if str(d).strip() and str(d).strip().lower() not in ['nan', 'none', 'null', '']
    ])
    
    with open(os.path.join(meta_dir, "devices.json"), 'w', encoding='utf-8') as f:
        json.dump(valid_devices, f, indent=2)    
        
    with open(os.path.join(meta_dir, "analytes.json"), 'w', encoding='utf-8') as f:
        json.dump(sorted(list(analytes)), f, indent=2)


def import_area_data(incident_path):
    """
    Processes raw AreaRAE CSV files from incident_path/data/realtime/
    Maps serial numbers to device labels, standardizes columns, 
    initializes INVALID flags, and saves to data/processed/area_data.csv.
    Returns the path to the processed file.
    """
    realtime_dir = os.path.join(incident_path, "data", "realtime")
    processed_dir = os.path.join(incident_path, "data", "processed")
    os.makedirs(processed_dir, exist_ok=True)

    if not os.path.exists(realtime_dir):
        return None

    current_dir = os.path.dirname(os.path.abspath(__file__))
    
    # ── 1. Load analytes.json for column renaming ──
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
            logger.error(f"Failed to load analytes config: {e}")

    # ── 2. Load area_devices.json for DEVICE label mapping ──
    area_devices_path = os.path.normpath(os.path.join(current_dir, '..', 'static', 'lists', 'area_devices.json'))
    serial_to_label = {}
    if os.path.exists(area_devices_path):
        try:
            with open(area_devices_path, 'r', encoding='utf-8') as f:
                devices_data = json.load(f)
                for device in devices_data.get("devices", []):
                    serial = device.get("serial", "")
                    label = device.get("label", "")
                    if serial and label:
                        serial_to_label[serial] = label
        except Exception as e:
            logger.error(f"Failed to load area devices config: {e}")

    standard_cols = {
        'serial number': 'SERIAL NUMBER', 'log time': 'LOG TIME',
        'model name': 'MODEL NAME', 'location': 'LOCATION',
        'site': 'SITE', 'status': 'STATUS', 'battery': 'BATTERY',
        'time zone': 'TIME ZONE'
    }

    csv_files = [f for f in os.listdir(realtime_dir) if f.lower().endswith('.csv')]
    all_dfs = []
    
    for filename in csv_files:
        if not filename.lower().startswith('datalog'):
            continue
            
        csv_file = os.path.join(realtime_dir, filename)
        try:
            if os.path.getsize(csv_file) == 0:
                continue
                
            df = pd.read_csv(csv_file)
            if df.empty:
                continue

            # Rename columns
            new_cols = []
            for col in df.columns: 
                col_str = str(col).strip()
                col_lower = col_str.lower()
                if col_lower in responder_to_name:
                    new_cols.append(responder_to_name[col_lower])
                elif col_lower in standard_cols:
                    new_cols.append(standard_cols[col_lower])
                else:
                    new_cols.append(col_str.upper())
            df.columns = new_cols

            # Clean data
            if 'SERIAL NUMBER' in df.columns:
                df = df[~df['SERIAL NUMBER'].astype(str).str.contains(r'\?', regex=True, na=False)]
            if 'MODEL NAME' in df.columns:
                df = df[df['MODEL NAME'] == 'AreaRAE Plus'].drop(columns=['MODEL NAME'])
            if 'TIME ZONE' in df.columns:
                df = df.drop(columns=['TIME ZONE'])
            if 'LOCATION' in df.columns:
                df['Latitude'] = df['LOCATION'].str.extract(r'(?i)Lat:\s*([-\d\.]+)')
                df['Longitude'] = df['LOCATION'].str.extract(r'(?i)Lng:\s*([-\d\.]+)')
                df = df.drop(columns=['LOCATION'])

            if not df.empty:
                all_dfs.append(df)
        except Exception as e:
            logger.error(f"Error reading {csv_file}: {e}")

    if not all_dfs:
        return None

    combined_df = pd.concat(all_dfs, ignore_index=True)
    combined_df.drop_duplicates(subset=['SERIAL NUMBER', 'LOG TIME'], keep='first', inplace=True)
    combined_df.sort_values(by='LOG TIME', inplace=True)

    # Add empty SITE and INVALID flags
    combined_df['SITE'] = ""
    exclude_cols = {'LOG TIME', 'SERIAL NUMBER', 'SITE', 'Latitude', 'Longitude', 'Count', 
                    'MODEL NAME', 'LOCATION', 'STATUS', 'BATTERY', 'TIME ZONE', 'TIME_BIN', 'DEVICE'}
    unique_analytes = sorted([col for col in combined_df.columns if col not in exclude_cols])

    for analyte in unique_analytes:
        combined_df[f"INVALID_{analyte}"] = 0

    # Map SERIAL NUMBER to DEVICE label
    if 'SERIAL NUMBER' in combined_df.columns:
        combined_df['DEVICE'] = combined_df['SERIAL NUMBER'].astype(str).str.strip().map(
            lambda s: serial_to_label.get(s, s)
        )

    # Save processed file
    processed_file = os.path.join(processed_dir, "area_data.csv")
    combined_df.to_csv(processed_file, index=False)

    # Save meta files for Area
    _save_area_meta(incident_path, combined_df['DEVICE'].dropna().unique(), unique_analytes)

    return processed_file
