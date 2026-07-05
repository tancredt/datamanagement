import os
import json
import pandas as pd
import numpy as np

def load_spot_to_df(json_path):
    """
    Reads spot_locations.json and converts it to a pandas DataFrame.
    Extracts marker labels into the 'SITE' column and reading devices into the 'DEVICE' column.
    Dynamically identifies analytes and creates INVALID_{analyte} columns initialized to 0.
    """
    if not os.path.exists(json_path):
        return pd.DataFrame()
        
    with open(json_path, 'r', encoding='utf-8') as f:
        data = json.load(f)
        
    rows = []
    analytes_found = set()
    
    # Known metadata keys in the spot readings that are NOT analytes
    base_keys = {'datetime', 'device', 'observations'}
    
    for loc in data.get("maps", {}).get("locations", []):
        for marker in loc.get("markers", []):
            site = marker.get("label", "")
            for r in marker.get("readings", []):
                # Base columns
                row = {
                    "LOG TIME": r.get("datetime"),
                    "DEVICE": r.get("device", ""),
                    "SITE": site,
                    "observations": r.get("observations", ""),
                    "Latitude": np.nan,
                    "Longitude": np.nan
                }
                
                # Dynamically capture any other keys (these are the analytes)
                for k, v in r.items():
                    if k not in base_keys and k not in row:
                        row[k] = v
                        analytes_found.add(k)
                rows.append(row)
                
    df = pd.DataFrame(rows)
    if not df.empty:
        df['LOG TIME'] = pd.to_datetime(df['LOG TIME'], errors='coerce')
        
        # Create INVALID_{analyte} columns for all discovered analytes
        for analyte in analytes_found:
            df[f"INVALID_{analyte}"] = 0
            
    return df


def load_spectral_to_df(json_path):
    """
    Reads spectral_locations.json and converts it to a pandas DataFrame.
    Extracts marker labels into the 'SITE' column and reading devices into the 'DEVICE' column.
    Dynamically identifies analytes and creates INVALID_{analyte} columns initialized to 0.
    """
    if not os.path.exists(json_path):
        return pd.DataFrame()
        
    with open(json_path, 'r', encoding='utf-8') as f:
        data = json.load(f)
        
    rows = []
    analytes_found = set()
    
    # Known metadata keys in the spectral readings that are NOT analytes
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
                
                # Dynamically capture any other keys (in case numeric analytes are present)
                for k, v in r.items():
                    if k not in base_keys and k not in row:
                        row[k] = v
                        analytes_found.add(k)
                rows.append(row)
                
    df = pd.DataFrame(rows)
    if not df.empty:
        df['LOG TIME'] = pd.to_datetime(df['LOG TIME'], errors='coerce')
        
        # Create INVALID_{analyte} columns for all discovered analytes
        for analyte in analytes_found:
            df[f"INVALID_{analyte}"] = 0
            
    return df
