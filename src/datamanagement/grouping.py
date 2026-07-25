import pandas as pd
import numpy as np
import logging

logger = logging.getLogger(__name__)

# ==========================================
# 1. AGGREGATE DATA
# ==========================================
def aggregate_data(df, interval, group_by, data_type="area"):
    """
    Aggregates area data into time intervals and calculates INVALID flags
    based on 1-minute bin coverage (80% threshold).
    Bypasses aggregation for non-area data or 'raw' interval.
    """
    if df is None or df.empty:
        return pd.DataFrame()
        
    # Bypass if not area data or interval is explicitly "Raw"
    if data_type != "area" or str(interval).strip().lower() == "raw":
        return df
        
    interval_mins = int(interval)
    if interval_mins <= 0:
        return df
        
    res = df.copy()
    res['LOG TIME'] = pd.to_datetime(res['LOG TIME'], errors='coerce')
    res = res.dropna(subset=['LOG TIME'])
    
    if res.empty:
        return pd.DataFrame()
        
    group_col = 'DEVICE' if group_by == 'Device' else 'SITE'
    if group_col not in res.columns:
        group_col = 'DEVICE' if 'DEVICE' in res.columns else 'SITE'
        
    # Identify analyte columns (exclude metadata and INVALID_ flags)
    metadata_cols = {'LOG TIME', 'SITE', 'DEVICE', 'Latitude', 'Longitude'}
    analyte_cols = [
        col for col in res.select_dtypes(include=[np.number]).columns 
        if col not in metadata_cols and not str(col).upper().startswith('INVALID_')
    ]
    
    if not analyte_cols:
        return res
        
    # STEP 1: Extract validity mask BEFORE dropping INVALID_ cols
    valid_df = res[['LOG TIME', group_col]].copy()
    for analyte in analyte_cols:
        inv_col = f"INVALID_{analyte}"
        if inv_col in res.columns:
            # 1 if valid (flag == 0), 0 if invalid
            valid_df[analyte] = (pd.to_numeric(res[inv_col], errors='coerce').fillna(1) == 0).astype(int)
        else:
            # 1 if not NaN, 0 if NaN
            valid_df[analyte] = (~res[analyte].isna()).astype(int)
            
    # STEP 2: Main Aggregation (Mean, Min, Max, Count)
    # Drop INVALID_ columns for main aggregation
    inv_cols = [c for c in res.columns if str(c).upper().startswith('INVALID_')]
    if inv_cols:
        res = res.drop(columns=inv_cols, errors='ignore')
        
    agg_df = res.set_index('LOG TIME')
    agg_dict = {analyte: ['mean', 'min', 'max', 'count'] for analyte in analyte_cols}
    
    preserve_cols = ['SITE', 'DEVICE', 'Latitude', 'Longitude']
    for col in preserve_cols:
        if col in agg_df.columns and col != group_col and col not in agg_dict:
            agg_dict[col] = 'first'
            
    main_grouper = pd.Grouper(freq=f'{interval_mins}min', closed='left', label='right', origin='start_day')
    res_agg = agg_df.groupby([group_col, main_grouper]).agg(agg_dict)
    
    # Flatten multi-index columns
    new_columns = []
    for col, stat in res_agg.columns:
        if col in analyte_cols:
            new_columns.append(col if stat == 'mean' else f"{col}_{stat}")
        else:
            new_columns.append(col)
    res_agg.columns = new_columns
    res_agg = res_agg.reset_index()
    
    # Ensure LOG TIME is correctly named
    if 'LOG TIME' not in res_agg.columns:
        res_agg = res_agg.rename(columns={res_agg.columns[1]: 'LOG TIME'})
        
    # STEP 3: 1-Minute Coverage Validation
    valid_df['min_bin'] = valid_df['LOG TIME'].dt.ceil('1min')
    valid_df['interval_bin'] = valid_df['min_bin'].dt.ceil(f'{interval_mins}min')
    
    # Count unique 1-min bins with data per interval bin
    min_counts = valid_df.groupby([group_col, 'interval_bin', 'min_bin'])[analyte_cols].sum().reset_index()
    for analyte in analyte_cols:
        min_counts[analyte] = (min_counts[analyte] > 0).astype(int)
        
    bins_with_data = min_counts.groupby([group_col, 'interval_bin'])[analyte_cols].sum().reset_index()
    bins_with_data = bins_with_data.rename(columns={'interval_bin': 'LOG TIME'})
    
    # Apply 80% threshold rule
    threshold = 0.8 * interval_mins
    for analyte in analyte_cols:
        inv_col = f"INVALID_{analyte}"
        flag_df = bins_with_data[[group_col, 'LOG TIME']].copy()
        flag_df[inv_col] = (bins_with_data[analyte] < threshold).astype(int)
        
        res_agg = res_agg.merge(flag_df, on=[group_col, 'LOG TIME'], how='left')
        # If no data at all in the bin, it's invalid (fillna(1))
        res_agg[inv_col] = res_agg[inv_col].fillna(1).astype(int)
        
    # STEP 4: Cleanup
    # Drop Lat/Lon as they are not meaningful for aggregated time bins
    res_agg = res_agg.drop(columns=['Latitude', 'Longitude'], errors='ignore')
    
    # Drop the non-grouped location identifier to keep tables clean
    if group_by == 'Device':
        res_agg = res_agg.drop(columns=['SITE'], errors='ignore')
    elif group_by == 'Site':
        res_agg = res_agg.drop(columns=['DEVICE'], errors='ignore')
        
    return res_agg


# ==========================================
# 2. SUMMARISE DATA
# ==========================================
def summarise_data(df):
    """
    Calculates the mean, max, and min for each valid analyte in the dataframe.
    - If the df is raw, it calculates the standard mean, max, and min.
    - If the df is aggregated, it calculates the mean of the means,
      the max of the maxs, and the min of the mins.
    Returns a list of dictionaries:
    [{ "analyte": "O2", "stats": {"mean": 20.5, "max": 20.9, "min": 20.1}}, ...]
    """
    if df is None or df.empty:
        return []
        
    metadata_cols = {
        'LOG TIME', 'SITE', 'DEVICE', 'Latitude', 'Longitude', 
        'observations', 'chemicals_identified', 'comments', 'file_ref'
    }
    
    # Identify base analyte columns dynamically
    analyte_cols = []
    for col in df.columns:
        if col in metadata_cols:
            continue
        if str(col).upper().startswith('INVALID_'):
            continue
        if any(str(col).endswith(suffix) for suffix in ['_min', '_max', '_count', '_mean']):
            continue
        if pd.api.types.is_numeric_dtype(df[col]):
            analyte_cols.append(col)
            
    summary = []
    for analyte in analyte_cols:
        stats = {}
        
        # 1. MEAN
        if analyte in df.columns:
            col_data = df[analyte].dropna()
            stats['mean'] = float(col_data.mean()) if not col_data.empty else np.nan
        else:
            stats['mean'] = np.nan
            
        # 2. MAX
        max_col = f"{analyte}_max"
        if max_col in df.columns:
            col_data = df[max_col].dropna()
            stats['max'] = float(col_data.max()) if not col_data.empty else np.nan
        elif analyte in df.columns:
            col_data = df[analyte].dropna()
            stats['max'] = float(col_data.max()) if not col_data.empty else np.nan
        else:
            stats['max'] = np.nan
            
        # 3. MIN
        min_col = f"{analyte}_min"
        if min_col in df.columns:
            col_data = df[min_col].dropna()
            stats['min'] = float(col_data.min()) if not col_data.empty else np.nan
        elif analyte in df.columns:
            col_data = df[analyte].dropna()
            stats['min'] = float(col_data.min()) if not col_data.empty else np.nan
        else:
            stats['min'] = np.nan
            
        summary.append({
            "analyte": analyte,
            "stats": stats
        })
        
    return summary
