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
# 2. LOAD & COMBINE CSVs
# ==========================================
def load_area_csvs(incident_path):
    """
    Reads raw AreaRAE CSV files, cleans them, and combines them into a single DataFrame.
    Returns: (combined_df, unique_analytes)
    """
    realtime_dir = os.path.join(incident_path, "data", "realtime")
    if not os.path.exists(realtime_dir):
        return pd.DataFrame(), []

    db = IncidentDatabase(incident_path)
    
    # Load responder name to analyte label mapping using the DB manager method
    responder_to_analyte = {}
    analytes = db.get_analytes()
    for ana in analytes:
        if ana.get('responder_name'):
            responder_to_analyte[ana['responder_name'].lower()] = ana['label']
                
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
                    new_cols.append(responder_to_analyte[col_lower])
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
        return pd.DataFrame(), []
        
    combined_df = pd.concat(all_dfs, ignore_index=True)
    combined_df.drop_duplicates(subset=['SERIAL NUMBER', 'LOG TIME'], keep='first', inplace=True)
    combined_df.sort_values(by='LOG TIME', inplace=True)
    
    # Clean SERIAL NUMBER column
    if 'SERIAL NUMBER' in combined_df.columns:
        combined_df['SERIAL NUMBER'] = combined_df['SERIAL NUMBER'].astype(str).str.strip()
        combined_df = combined_df[~combined_df['SERIAL NUMBER'].isin(['', 'nan', 'NaN', 'None', 'None '])]
    else:
        return pd.DataFrame(), []
        
    if combined_df.empty:
        return pd.DataFrame(), []

    # Identify analyte columns
    exclude_cols = {'LOG TIME', 'SERIAL NUMBER', 'Latitude', 'Longitude', 'Count', 
                    'MODEL NAME', 'LOCATION', 'STATUS', 'BATTERY', 'TIME ZONE', 'TIME_BIN', 'DEVICE', 'SITE'}
    unique_analytes = sorted([col for col in combined_df.columns if col not in exclude_cols])
    
    return combined_df, unique_analytes

# ==========================================
# 3. INSERT INTO DATABASE
# ==========================================
def insert_area_data(incident_path, combined_df, unique_analytes):
    """
    Inserts the combined DataFrame into the database.
    Handles dynamic device creation, deduplication against existing DB records 
    (to respect the UNIQUE(timestamp, device_id) constraint), and bulk insertion.
    Returns the number of new rows inserted.
    """
    if combined_df.empty:
        return 0
        
    db = IncidentDatabase(incident_path)
    
    with db.get_connection() as conn:
        # 1. Dynamic Device Creation (Fallback for unknown serials)
        unique_serials = combined_df['SERIAL NUMBER'].unique()
        existing_serials = {
            row['serial'] for row in conn.execute(
                "SELECT serial FROM device WHERE device_type = 'area' AND serial IS NOT NULL"
            ).fetchall()
        }
        
        new_serials = [s for s in unique_serials if s not in existing_serials]
        if new_serials:
            conn.executemany(
                "INSERT OR IGNORE INTO device (label, serial, device_type) VALUES (?, ?, 'area')",
                [(s, s) for s in new_serials]
            )
            conn.commit()
            logger.info(f"✅ Created {len(new_serials)} new area devices from imported data.")
            
        # Reload mappings
        serial_to_label = {
            dev['serial']: dev['label'] 
            for dev in conn.execute("SELECT label, serial FROM device WHERE device_type = 'area' AND serial IS NOT NULL").fetchall()
        }
        device_label_to_id = {dev['label']: dev['id'] for dev in conn.execute("SELECT id, label FROM device").fetchall()}
        analyte_label_to_id = {ana['label']: ana['id'] for ana in conn.execute("SELECT id, label FROM analyte").fetchall()}
        
        combined_df['DEVICE'] = combined_df['SERIAL NUMBER'].map(serial_to_label)
        combined_df['device_id'] = combined_df['DEVICE'].map(device_label_to_id)
        
        # Drop rows where device_id is null (safety check)
        combined_df = combined_df.dropna(subset=['device_id'])
        if combined_df.empty:
            return 0
            
        combined_df['device_id'] = combined_df['device_id'].astype(int)
        
        # 2. Deduplication against existing DB records 
        # (Respects the new UNIQUE(timestamp, device_id) constraint)
        existing_pairs = {
            (str(row['timestamp']).strip(), row['device_id']) 
            for row in conn.execute("SELECT timestamp, device_id FROM area_reading").fetchall()
        }
        
        combined_df['_dedup_key'] = list(zip(
            combined_df['LOG TIME'].astype(str).str.strip(),
            combined_df['device_id']
        ))
        
        before_count = len(combined_df)
        combined_df = combined_df[~combined_df['_dedup_key'].isin(existing_pairs)].copy()
        combined_df.drop(columns=['_dedup_key'], inplace=True)
        
        skipped = before_count - len(combined_df)
        if skipped > 0:
            logger.info(f"⏭️ Skipped {skipped} duplicate rows already in database.")
            
        if combined_df.empty:
            return 0
            
        # 3. Bulk Insert area_reading
        for col in ['STATUS', 'BATTERY', 'Latitude', 'Longitude']:
            if col not in combined_df.columns:
                combined_df[col] = None
                
        combined_df['LOG TIME'] = combined_df['LOG TIME'].astype(str)
        combined_df['SERIAL NUMBER'] = combined_df['SERIAL NUMBER'].astype(str)
        combined_df['STATUS'] = combined_df['STATUS'].astype(str).where(combined_df['STATUS'].notna(), None)
        
        # Record max ID before inserting so we can retrieve the new IDs after
        max_id_before = conn.execute("SELECT COALESCE(MAX(id), 0) FROM area_reading").fetchone()[0]
        
        area_reading_cols = ['LOG TIME', 'STATUS', 'BATTERY', 'Latitude', 'Longitude', 'device_id']
        area_reading_data = combined_df[area_reading_cols].itertuples(index=False, name=None)
        
        conn.executemany("""
            INSERT INTO area_reading (timestamp, status, battery, latitude, longitude, device_id)
            VALUES (?, ?, ?, ?, ?, ?)
        """, area_reading_data)
        
        # 4. Retrieve newly inserted IDs
        new_ids_rows = conn.execute(
            "SELECT id, timestamp, device_id FROM area_reading WHERE id > ? ORDER BY id",
            (max_id_before,)
        ).fetchall()
        
        # Build a lookup: (timestamp, device_id) -> area_reading.id
        new_id_map = {
            (str(row['timestamp']).strip(), row['device_id']): row['id']
            for row in new_ids_rows
        }
        
        combined_df['_db_key'] = list(zip(
            combined_df['LOG TIME'].astype(str).str.strip(),
            combined_df['device_id']
        ))
        combined_df['area_reading_id'] = combined_df['_db_key'].map(new_id_map)
        combined_df.drop(columns=['_db_key'], inplace=True)
        
        # 5. Bulk Insert area_reading_analyte via melt
        # (Uses INSERT OR IGNORE to respect the UNIQUE(area_reading_id, analyte_id) constraint)
        value_vars = [col for col in unique_analytes if col in combined_df.columns]
        if value_vars:
            melted = combined_df.melt(
                id_vars=['area_reading_id'], 
                value_vars=value_vars, 
                var_name='analyte_label', 
                value_name='value'
            )
            melted = melted.dropna(subset=['value', 'area_reading_id'])
            
            melted['analyte_id'] = melted['analyte_label'].map(analyte_label_to_id)
            melted = melted.dropna(subset=['analyte_id'])
            
            melted['value'] = pd.to_numeric(melted['value'], errors='coerce')
            melted = melted.dropna(subset=['value'])
            
            analyte_data = melted[['area_reading_id', 'analyte_id', 'value']].itertuples(index=False, name=None)
            conn.executemany("""
                INSERT OR IGNORE INTO area_reading_analyte (area_reading_id, analyte_id, value)
                VALUES (?, ?, ?)
            """, analyte_data)
            
        conn.commit()
        row_count = len(combined_df)
        logger.info(f"✅ Appended {row_count} new area readings into database.")
        return row_count

def import_area_data(incident_path):
    """
    Wrapper function that loads CSVs and inserts them into the database.
    Called from main_window
    """
    combined_df, unique_analytes = load_area_csvs(incident_path)
    return insert_area_data(incident_path, combined_df, unique_analytes)
