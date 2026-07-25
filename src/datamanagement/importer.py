import os
import shutil
import logging
import pandas as pd
import numpy as np
import json
from datamanagement.db_manager import IncidentDatabase

logger = logging.getLogger(__name__)

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
# 2. AREA DATA IMPORT (Raw CSVs to Database)
# ==========================================
def import_area_data(incident_path):
    """
    Processes raw AreaRAE CSV files from incident_path/data/realtime/
    Inserts data into area_reading and area_reading_analyte tables.
    Also generates processed CSV for backward compatibility.
    Returns the path to the processed file.
    """
    realtime_dir = os.path.join(incident_path, "data", "realtime")
    processed_dir = os.path.join(incident_path, "data", "processed")
    os.makedirs(processed_dir, exist_ok=True)
    
    if not os.path.exists(realtime_dir):
        return None
    
    db = IncidentDatabase(incident_path)
    
    # Load mappings from database
    with db.get_connection() as conn:
        # Get serial to device label mapping
        serial_to_label = {}
        devices = conn.execute("SELECT label, serial FROM device WHERE device_type = 'area'").fetchall()
        for dev in devices:
            if dev['serial']:
                serial_to_label[dev['serial']] = dev['label']
        
        # Get responder name to analyte label mapping
        responder_to_analyte = {}
        analytes = conn.execute("SELECT id, label, responder_name FROM analyte").fetchall()
        for ana in analytes:
            if ana['responder_name']:
                responder_to_analyte[ana['responder_name'].lower()] = {
                    'id': ana['id'],
                    'label': ana['label']
                }
    
    standard_cols = {
        'serial number': 'SERIAL NUMBER', 'log time': 'LOG TIME',
        'model name': 'MODEL NAME', 'location': 'LOCATION',
        'site': 'SITE', 'status': 'STATUS', 'battery': 'BATTERY',
        'time zone': 'TIME ZONE'
    }
    
    csv_files = [f for f in os.listdir(realtime_dir) if f.lower().endswith('.csv') and f.lower().startswith('datalog')]
    all_dfs = []
    
    for filename in csv_files:
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
                if col_lower in responder_to_analyte:
                    new_cols.append(responder_to_analyte[col_lower]['label'])
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
    
    # Add empty SITE and INVALID flags for CSV
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
    
    # ==========================================
    # INSERT INTO DATABASE
    # ==========================================
    with db.get_connection() as conn:
        # Clear existing area data for this incident
        conn.execute("DELETE FROM area_reading_analyte")
        conn.execute("DELETE FROM area_reading")
        
        # Get device_id mapping
        device_label_to_id = {}
        devices = conn.execute("SELECT id, label FROM device").fetchall()
        for dev in devices:
            device_label_to_id[dev['label']] = dev['id']
        
        # Get analyte mapping
        analyte_label_to_id = {}
        analytes = conn.execute("SELECT id, label FROM analyte").fetchall()
        for ana in analytes:
            analyte_label_to_id[ana['label']] = ana['id']
        
        # Insert rows
        for _, row in combined_df.iterrows():
            serial = str(row.get('SERIAL NUMBER', '')).strip()
            timestamp = str(row.get('LOG TIME', '')).strip()
            device_label = str(row.get('DEVICE', '')).strip()
            status = str(row.get('STATUS', '')).strip() if pd.notna(row.get('STATUS')) else None
            battery = float(row.get('BATTERY')) if pd.notna(row.get('BATTERY')) else None
            latitude = float(row.get('Latitude')) if pd.notna(row.get('Latitude')) else None
            longitude = float(row.get('Longitude')) if pd.notna(row.get('Longitude')) else None
            
            device_id = device_label_to_id.get(device_label)
            
            # Insert area_reading
            cursor = conn.execute("""
                INSERT INTO area_reading (timestamp, serial_number, status, battery, latitude, longitude, device_id)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (timestamp, serial, status, battery, latitude, longitude, device_id))
            
            area_reading_id = cursor.lastrowid
            
            # Insert area_reading_analyte for each analyte
            for analyte_label in unique_analytes:
                if analyte_label in row and pd.notna(row[analyte_label]):
                    try:
                        value = float(row[analyte_label])
                        analyte_id = analyte_label_to_id.get(analyte_label)
                        if analyte_id:
                            conn.execute("""
                                INSERT INTO area_reading_analyte (area_reading_id, analyte_id, value)
                                VALUES (?, ?, ?)
                            """, (area_reading_id, analyte_id, value))
                    except (ValueError, TypeError):
                        pass
        
        conn.commit()
        logger.info(f"✅ Inserted {len(combined_df)} area readings into database")
    
    # Save processed CSV for backward compatibility
    processed_file = os.path.join(processed_dir, "area_data.csv")
    combined_df.to_csv(processed_file, index=False)
    
    return processed_file
