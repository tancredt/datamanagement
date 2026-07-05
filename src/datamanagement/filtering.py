import pandas as pd
import numpy as np
import logging

logger = logging.getLogger(__name__)

def filter_data(df, start_dt, stop_dt, selected_sites, selected_devices, 
                selected_analytes, only_valid, group_by, data_type="area"):
    """
    Filters rows and selects columns based on time, site, device, and analyte.
    Returns a clean, filtered raw DataFrame.
    """
    if df is None or df.empty:
        return pd.DataFrame()

    res = df.copy()

    # ──────────────────────────────────────────────
    # 1. TIME FILTERING
    # ──────────────────────────────────────────────
    if 'LOG TIME' in res.columns:
        res['LOG TIME'] = pd.to_datetime(res['LOG TIME'], errors='coerce')
        res = res.dropna(subset=['LOG TIME'])
        
        start_ts = pd.Timestamp(start_dt)
        stop_ts = pd.Timestamp(stop_dt)
        
        if res['LOG TIME'].dt.tz is not None and start_ts.tz is None:
            start_ts = start_ts.tz_localize(res['LOG TIME'].dt.tz)
            stop_ts = stop_ts.tz_localize(res['LOG TIME'].dt.tz)
        elif res['LOG TIME'].dt.tz is None and start_ts.tz is not None:
            start_ts = start_ts.tz_localize(None)
            stop_ts = stop_ts.tz_localize(None)
            
        res = res[(res['LOG TIME'] > start_ts) & (res['LOG TIME'] <= stop_ts)]

    if 'SITE' in res.columns:
        res['SITE'] = res['SITE'].fillna('')
    if 'DEVICE' in res.columns:
        res['DEVICE'] = res['DEVICE'].fillna('')

    # ──────────────────────────────────────────────
    # 2. SITE & DEVICE FILTERING LOGIC (ALL DATA TYPES)
    # ──────────────────────────────────────────────
    if data_type in ["spot", "spectral"]:
        if 'SITE' in res.columns and selected_sites:
            res = res[res['SITE'].isin(selected_sites)]
        if 'DEVICE' in res.columns and selected_devices:
            res = res[res['DEVICE'].isin(selected_devices)]
    else:
        if group_by == 'Site':
            if 'SITE' in res.columns and selected_sites:
                res = res[res['SITE'].isin(selected_sites)]
        elif group_by == 'Device':
            if 'DEVICE' in res.columns and selected_devices:
                res = res[res['DEVICE'].isin(selected_devices)]

    if res.empty:
        return res

    # ──────────────────────────────────────────────
    # 3. COLUMN SELECTION (ALL DATA TYPES)
    # ──────────────────────────────────────────────
    keep_cols = [c for c in ['LOG TIME', 'SITE', 'DEVICE', 'Latitude', 'Longitude'] if c in res.columns]
    
    if data_type in ["spot", "spectral"]:
        keep_cols += [c for c in ['observations', 'chemicals_identified', 'comments', 'file_ref'] if c in res.columns]

    analyte_cols_to_keep = []
    invalid_cols_to_keep = []
    for analyte in selected_analytes:
        if analyte in res.columns:
            analyte_cols_to_keep.append(analyte)
        inv_col = f"INVALID_{analyte}"
        if inv_col in res.columns:
            invalid_cols_to_keep.append(inv_col)
            
    final_cols = list(dict.fromkeys(keep_cols + analyte_cols_to_keep + invalid_cols_to_keep))
    res = res[[c for c in final_cols if c in res.columns]]

    if res.empty:
        return res

    if data_type in ["spot", "spectral"]:
        return res

    # ──────────────────────────────────────────────
    # 4. "ONLY VALID" HANDLING (Raw Data)
    # ──────────────────────────────────────────────
    if only_valid and analyte_cols_to_keep:
        for analyte in analyte_cols_to_keep:
            inv_col = f"INVALID_{analyte}"
            if inv_col in res.columns:
                # If the INVALID flag is > 0, set ONLY this analyte's value to NaN
                invalid_mask = pd.to_numeric(res[inv_col], errors='coerce').fillna(0) > 0
                res.loc[invalid_mask, analyte] = np.nan

    return res

def aggregate_data(df, interval, group_by, start_dt=None, stop_dt=None):
    """
    FUNCTION 2: TIME AGGREGATION & VALIDITY CHECK
    Takes an already filtered DataFrame and aggregates it into time intervals.
    Dynamically finds all numeric analyte columns, calculates stats, and 
    recalculates INVALID flags based on 1-minute bin coverage (80% threshold).
    """
    if df is None or df.empty:
        return pd.DataFrame()

    interval_mins = int(interval)
    
    res = df.copy()
    
    # Drop any existing INVALID_ columns since we are going to recalculate them
    inv_cols = [c for c in res.columns if str(c).startswith('INVALID_')]
    if inv_cols:
        res = res.drop(columns=inv_cols)

    # Identify analyte columns (all numeric columns except core metadata)
    metadata_cols = {'LOG TIME', 'SITE', 'DEVICE', 'Latitude', 'Longitude'}
    analyte_cols = [col for col in res.select_dtypes(include=[np.number]).columns if col not in metadata_cols]
    
    agg_df = res.set_index('LOG TIME')
    group_col = 'DEVICE' if group_by == 'Device' else 'SITE'
    
    # ──────────────────────────────────────────────
    # 1. AGGREGATE ANALYTES (Mean, Min, Max, Count)
    # ──────────────────────────────────────────────
    agg_dict = {analyte: ['mean', 'min', 'max', 'count'] for analyte in analyte_cols}
    
    preserve_cols = ['SITE', 'DEVICE', 'Latitude', 'Longitude']
    for col in preserve_cols:
        if col in agg_df.columns and col != group_col and col not in agg_dict:
            agg_dict[col] = 'first'
            
    res_agg = agg_df.groupby(
        [group_col, pd.Grouper(freq=f'{interval_mins}min', closed='right', label='right')]
    ).agg(agg_dict)
    
    # Flatten the MultiIndex columns
    new_columns = []
    for col, stat in res_agg.columns:
        if col in analyte_cols:
            if stat == 'mean':
                new_columns.append(col)
            else:
                new_columns.append(f"{col}_{stat}")
        else:
            new_columns.append(col)
            
    res_agg.columns = new_columns
    res_agg = res_agg.reset_index()

    # ──────────────────────────────────────────────
    # 2. DYNAMIC INVALID FLAG CALCULATION (1-Min Bin Coverage)
    # ──────────────────────────────────────────────
    if analyte_cols and interval_mins > 0:
        # We need the global start/stop to create a continuous 1-min timeline.
        # This ensures completely empty minutes are counted as 0 in the denominator.
        if start_dt is not None and stop_dt is not None:
            start_ts = pd.Timestamp(start_dt)
            stop_ts = pd.Timestamp(stop_dt)
            
            if agg_df.index.tz is not None and start_ts.tz is None:
                start_ts = start_ts.tz_localize(agg_df.index.tz)
                stop_ts = stop_ts.tz_localize(agg_df.index.tz)
            elif agg_df.index.tz is None and start_ts.tz is not None:
                start_ts = start_ts.tz_localize(None)
                stop_ts = stop_ts.tz_localize(None)
                
            time_index = pd.date_range(start=start_ts, end=stop_ts, freq='1min')
        else:
            time_index = None

        groups = res[group_col].unique() if group_col in res.columns else [None]
        all_1min_counts = []
        
        for g in groups:
            if group_col in res.columns:
                g_df = agg_df[agg_df[group_col] == g]
            else:
                g_df = agg_df
                
            # Since filter_data already removed invalid rows, we just check for non-NaN
            valid_flags = pd.DataFrame(index=g_df.index)
            for analyte in analyte_cols:
                valid_flags[analyte] = (~g_df[analyte].isna()).astype(int)
                
            # Count valid readings per 1-minute bin
            g_counts = valid_flags.resample('1min', closed='right', label='right').sum()
            if time_index is not None and not time_index.empty:
                g_counts = g_counts.reindex(time_index, fill_value=0)
            g_counts[group_col] = g
            all_1min_counts.append(g_counts)
            
        if all_1min_counts:
            counts_1min_df = pd.concat(all_1min_counts).reset_index().rename(columns={'index': 'LOG TIME'})
            counts_1min_df = counts_1min_df.set_index('LOG TIME')
            
            # Convert counts to 1 if there was ANY data in that 1-min bin, else 0
            has_data = (counts_1min_df[analyte_cols] > 0).astype(int)
            has_data[group_col] = counts_1min_df[group_col]
            
            # Sum the number of 1-min bins that had data, grouped by the target interval
            bins_with_data = has_data.groupby(group_col).resample(f'{interval_mins}min', closed='right', label='right')[analyte_cols].sum().reset_index()
            
            # Calculate coverage fraction (e.g., 12 out of 15 minutes = 0.80)
            coverage = bins_with_data[analyte_cols] / interval_mins
            
            # Apply 80% threshold rule
            for analyte in analyte_cols:
                inv_col = f"INVALID_{analyte}"
                flag_df = bins_with_data[[group_col, 'LOG TIME']].copy()
                
                # If coverage is < 0.8 (80%), it is INVALID (1). Otherwise valid (0).
                flag_df[inv_col] = (coverage[analyte] < 0.8).astype(int)
                
                res_agg = res_agg.merge(flag_df, on=[group_col, 'LOG TIME'], how='left')
                # Fill missing intervals with 1 (Invalid)
                res_agg[inv_col] = res_agg[inv_col].fillna(1).astype(int)
        else:
            for analyte in analyte_cols:
                res_agg[f"INVALID_{analyte}"] = 1

    return res_agg

def summarise_data(df):
    """
    Calculates the mean, max, and min for each valid analyte in the dataframe.
    - If the df is raw (from filter_data), it calculates the standard mean, max, and min.
    - If the df is aggregated (from aggregate_data), it calculates the mean of the means, 
      the max of the maxs, and the min of the mins.
      
    Returns a list of dictionaries: 
    [{"analyte": "O2", "stats": {"mean": 20.5, "max": 20.9, "min": 20.1}}, ...]
    """
    if df is None or df.empty:
        return []

    # Columns to ignore when identifying base analytes
    metadata_cols = {
        'LOG TIME', 'SITE', 'DEVICE', 'Latitude', 'Longitude', 
        'observations', 'chemicals_identified', 'comments', 'file_ref'
    }

    # Identify base analyte columns dynamically
    analyte_cols = []
    for col in df.select_dtypes(include=[np.number]).columns:
        if col in metadata_cols:
            continue
        if col.startswith('INVALID_'):
            continue
        # Ignore the aggregated stat columns so we only process the base analyte
        if any(col.endswith(suffix) for suffix in ['_min', '_max', '_count']):
            continue
        analyte_cols.append(col)

    summary = []
    for analyte in analyte_cols:
        stats = {}
        
        # 1. MEAN (Mean of the means, or mean of raw data)
        # The base column holds the interval means (if aggregated) or raw values
        if analyte in df.columns:
            col_data = df[analyte].dropna()
            stats['mean'] = float(col_data.mean()) if not col_data.empty else np.nan
        else:
            stats['mean'] = np.nan

        # 2. MAX (Max of the maxs, or max of raw data)
        max_col = f"{analyte}_max"
        if max_col in df.columns:
            # Aggregated data: get the max of the interval maximums
            col_data = df[max_col].dropna()
            stats['max'] = float(col_data.max()) if not col_data.empty else np.nan
        elif analyte in df.columns:
            # Raw data: get the max of the raw values
            col_data = df[analyte].dropna()
            stats['max'] = float(col_data.max()) if not col_data.empty else np.nan
        else:
            stats['max'] = np.nan

        # 3. MIN (Min of the mins, or min of raw data)
        min_col = f"{analyte}_min"
        if min_col in df.columns:
            # Aggregated data: get the min of the interval minimums
            col_data = df[min_col].dropna()
            stats['min'] = float(col_data.min()) if not col_data.empty else np.nan
        elif analyte in df.columns:
            # Raw data: get the min of the raw values
            col_data = df[analyte].dropna()
            stats['min'] = float(col_data.min()) if not col_data.empty else np.nan
        else:
            stats['min'] = np.nan

        summary.append({
            "analyte": analyte,
            "stats": stats
        })

    return summary
