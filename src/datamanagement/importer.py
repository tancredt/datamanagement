import os
import shutil
import logging
import pandas as pd
import numpy as np
import json
from pandas.errors import EmptyDataError

logger = logging.getLogger(__name__)

def copy_files_to_realtime(incident_path, selected_files):
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

def process_realtime_data(incident_path):
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
                analytes_list = analyte_config.get("analytes", [])
                for analyte in analytes_list:
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
                devices_list = devices_data.get("devices", [])
                for device in devices_list:
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
        #check it is a datalog file
        if not filename.lower().startswith('datalog'):
            continue
        
        csv_file = os.path.join(realtime_dir, filename)
        try:
            #check file is not 0 bytes
            if os.path.getsize(csv_file) == 0:
                continue
            
            df = pd.read_csv(csv_file)
            #check the dataframe is not empty
            if df.empty:
                continue
            
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

            #sometime get phantom serial numbers with '?' in them. 
            if 'SERIAL NUMBER' in df.columns:
                df = df[~df['SERIAL NUMBER'].astype(str).str.contains(r'\?', regex=True, na=False)]
            #only area rae plus data. Drop the MODEL NAME column
            if 'MODEL NAME' in df.columns:
                df = df[df['MODEL NAME'] == 'AreaRAE Plus'].drop(columns=['MODEL NAME'])
            #drop the  time zone column
            if 'TIME ZONE' in df.columns:
                df = df.drop(columns=['TIME ZONE'])
            #split the location into latitude and longitude then drop the location column
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

    #drop duplicates with the same LOG TIME and SERIAL NUMBER in case of overlapping raw files
    combined_df.drop_duplicates(subset=['SERIAL NUMBER', 'LOG TIME'], keep='first', inplace=True)
    combined_df.sort_values(by='LOG TIME', inplace=True)

    #add an empty site column
    combined_df['SITE'] = ""

    #finding unique analytes, exclude these columns and the rest are analytes
    exclude_cols = {'LOG TIME', 'SERIAL NUMBER', 'SITE', 'Latitude', 'Longitude', 'Count', 
                    'MODEL NAME', 'LOCATION', 'STATUS', 'BATTERY', 'TIME ZONE', 'TIME_BIN', 'DEVICE'}
        
    unique_analytes = sorted([col for col in combined_df.columns if col not in exclude_cols])
    
    # Create per-gas INVALID flag columns
    for analyte in unique_analytes:
        combined_df[f"INVALID_{analyte}"] = 0
    
    # ── 3. Add DEVICE column mapping SERIAL NUMBER to label ──
    if 'SERIAL NUMBER' in combined_df.columns:
        combined_df['DEVICE'] = combined_df['SERIAL NUMBER'].astype(str).str.strip().map(
            lambda s: serial_to_label.get(s, s)
        )

    #save file
    processed_file = os.path.join(processed_dir, "area_data.csv")
    combined_df.to_csv(processed_file, index=False)

    #save a list of unique devices and analytes to be used in combos
    meta_dir = os.path.join(incident_path, "meta")
    os.makedirs(meta_dir, exist_ok=True)
    
    unique_devices = sorted([str(d).strip() for d in combined_df['DEVICE'].dropna().unique() 
                             if str(d).strip() and str(d).strip().lower() not in ['nan', 'none', 'null', '']])
    
    with open(os.path.join(meta_dir, "devices.json"), 'w', encoding='utf-8') as f:
        json.dump(unique_devices, f, indent=2)    
    
    with open(os.path.join(meta_dir, "analytes.json"), 'w', encoding='utf-8') as f:
        json.dump(unique_analytes, f, indent=2)
    
    return processed_file

#This takes the log containing device locations and puts the site label in the SITE column
#if the device is at location between the start and stop times
def update_site_from_device_log(incident_path):
    processed_file = os.path.join(incident_path, "data", "processed", "area_data.csv")
    area_locations_file = os.path.join(incident_path, "mapping", "area_locations.json")
    
    if not os.path.exists(processed_file) or not os.path.exists(area_locations_file):
        return processed_file
    
    try:
        df = pd.read_csv(processed_file)
        #reset all sites to "" in the processed dataframe
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
            #if the stop_dt is empty, it means the device is still there, so set it to the far future
            stop_dt = pd.to_datetime(stop_time, errors='coerce') if stop_time else pd.Timestamp('9999-12-31 23:59:59')
            
            if pd.isna(start_dt) or pd.isna(stop_dt):
                continue
            #device is at a location if the start_dt is greater than the log time and less than or equal to stop time
            mask = (df['DEVICE'] == device_label) & (df['LOG TIME'] > start_dt) & (df['LOG TIME'] <= stop_dt)
            df.loc[mask, 'SITE'] = location
        
        df.to_csv(processed_file, index=False)
    
    except Exception as e:
        logger.error(f"Failed to update SITE: {e}")
    
    return processed_file

def update_validations(incident_path):
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
