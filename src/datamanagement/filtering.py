import pandas as pd
import numpy as np
import logging

logger = logging.getLogger(__name__)

# ==========================================
# 1. FILTER DATA
# ==========================================
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
        # Map empty or whitespace-only sites to 'Unassigned' to match the UI checkbox
        res.loc[res['SITE'].astype(str).str.strip() == '', 'SITE'] = 'Unassigned'

    if group_by == 'Site' and selected_sites:
        res = res[res['SITE'].isin(selected_sites)]
    elif group_by == 'Device' and selected_devices:
        # Include selected devices AND any readings with an empty/unassigned device
        device_mask = res['DEVICE'].isin(selected_devices)
        empty_device_mask = res['DEVICE'].astype(str).str.strip() == ''
        res = res[device_mask | empty_device_mask]

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
        # Support both raw columns and exposure summary columns (_min, _max, _mean)
        for suffix in ['', '_min', '_max', '_mean']:
            col_name = f"{analyte}{suffix}"
            if col_name in res.columns and col_name not in analyte_cols_to_keep:
                analyte_cols_to_keep.append(col_name)

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


# ==========================================
# 2. AGGREGATE DATA
# ==========================================
def aggregate_data(df, interval, group_by, start_dt=None, stop_dt=None, data_type="area"):
    """
    Aggregates data into time intervals and calculates INVALID flags
    based on 1-minute bin coverage (80% threshold).
    """
    if df is None or df.empty:
        return pd.DataFrame()

    # --- FIX: Spot readings should NEVER be aggregated ---
    # Also bypass if interval is explicitly "Raw"
    if data_type != "area" or str(interval).strip().lower() == "raw":
        return df

    interval_mins = int(interval)

    res = df.copy()

    # Identify analyte columns (exclude metadata and INVALID_ flags)
    metadata_cols = {'LOG TIME', 'SITE', 'DEVICE', 'Latitude', 'Longitude'}
    analyte_cols = [
        col for col in res.select_dtypes(include=[np.number]).columns 
        if col not in metadata_cols and not str(col).upper().startswith('INVALID_')
    ]

    res['LOG TIME'] = pd.to_datetime(res['LOG TIME'], errors='coerce')
    res = res.dropna(subset=['LOG TIME'])

    group_col = 'DEVICE' if group_by == 'Device' else 'SITE'

    # STEP 1: Extract validity mask BEFORE dropping INVALID_ cols
    valid_df = res[['LOG TIME', group_col]].copy()
    for analyte in analyte_cols:
        inv_col = f"INVALID_{analyte}"
        if inv_col in res.columns:
            valid_df[analyte] = (pd.to_numeric(res[inv_col], errors='coerce').fillna(1) == 0).astype(int)
        else:
            valid_df[analyte] = (~res[analyte].isna()).astype(int)

    # NOW drop INVALID_ columns for main aggregation
    inv_cols = [c for c in res.columns if str(c).upper().startswith('INVALID_')]
    if inv_cols:
        res = res.drop(columns=inv_cols, errors='ignore')

    # STEP 2: Main Aggregation (Mean, Min, Max, Count)
    agg_df = res.set_index('LOG TIME')
    agg_dict = {analyte: ['mean', 'min', 'max', 'count'] for analyte in analyte_cols}

    preserve_cols = ['SITE', 'DEVICE', 'Latitude', 'Longitude']
    for col in preserve_cols:
        if col in agg_df.columns and col != group_col and col not in agg_dict:
            agg_dict[col] = 'first'

    main_grouper = pd.Grouper(freq=f'{interval_mins}min', closed='left', label='right', origin='start_day')
    res_agg = agg_df.groupby([group_col, main_grouper]).agg(agg_dict)

    new_columns = []
    for col, stat in res_agg.columns:
        if col in analyte_cols:
            new_columns.append(col if stat == 'mean' else f"{col}_{stat}")
        else:
            new_columns.append(col)
    res_agg.columns = new_columns
    res_agg = res_agg.reset_index()

    if 'LOG TIME' not in res_agg.columns and len(res_agg.columns) > 1:
        res_agg = res_agg.rename(columns={res_agg.columns[1]: 'LOG TIME'})

    # STEP 3: 1-Minute Coverage Validation
    if analyte_cols and interval_mins > 0:
        # A. Assign each row to its 1-minute bin
        valid_df['min_bin'] = valid_df['LOG TIME'].dt.ceil('1min')

        # B. Count valid readings per 1-min bin per device
        min_counts = valid_df.groupby([group_col, 'min_bin'])[analyte_cols].sum().reset_index()

        # C. Convert to has_data: 1 if any valid reading in that minute, else 0
        for analyte in analyte_cols:
            min_counts[analyte] = (min_counts[analyte] > 0).astype(int)

        # D. Map each 1-min bin to its parent interval bin
        min_counts['interval_bin'] = min_counts['min_bin'].dt.ceil(f'{interval_mins}min')

        # E. Sum the has_data flags per interval bin
        bins_with_data = min_counts.groupby([group_col, 'interval_bin'])[analyte_cols].sum().reset_index()

        # F. Rename interval_bin to LOG TIME for merging
        bins_with_data = bins_with_data.rename(columns={'interval_bin': 'LOG TIME'})

        # G. Apply 80% threshold rule
        threshold = 0.8 * interval_mins
        for analyte in analyte_cols:
            inv_col = f"INVALID_{analyte}"
            flag_df = bins_with_data[[group_col, 'LOG TIME']].copy()
            flag_df[inv_col] = (bins_with_data[analyte] < threshold).astype(int)

            res_agg = res_agg.merge(flag_df, on=[group_col, 'LOG TIME'], how='left')
            res_agg[inv_col] = res_agg[inv_col].fillna(1).astype(int)
    else:
        for analyte in analyte_cols:
            res_agg[f"INVALID_{analyte}"] = 1

    # STEP 4: Filter to only include bins within the requested time range
    if stop_dt is not None:
        stop_ts = pd.Timestamp(stop_dt)
        if res_agg['LOG TIME'].dt.tz is not None and stop_ts.tz is None:
            stop_ts = stop_ts.tz_localize(res_agg['LOG TIME'].dt.tz)
        elif res_agg['LOG TIME'].dt.tz is None and stop_ts.tz is not None:
            stop_ts = stop_ts.tz_localize(None)

        res_agg = res_agg[res_agg['LOG TIME'] <= stop_ts]

    # ==========================================
    # CLEANUP: Drop unnecessary columns for aggregated area data
    # ==========================================
    # 1. Drop Lat/Lon as they are not meaningful for aggregated time bins
    res_agg = res_agg.drop(columns=['Latitude', 'Longitude'], errors='ignore')
    
    # 2. Drop the non-grouped location identifier to keep tables clean
    if group_by == 'Device':
        res_agg = res_agg.drop(columns=['SITE'], errors='ignore')
    elif group_by == 'Site':
        res_agg = res_agg.drop(columns=['DEVICE'], errors='ignore')

    return res_agg


# ==========================================
# 3. SUMMARISE DATA
# ==========================================
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
