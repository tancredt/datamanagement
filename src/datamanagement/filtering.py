import pandas as pd
import numpy as np
import logging

logger = logging.getLogger(__name__)

def filter_data(df, start_dt, stop_dt, interval, selected_sites, selected_gases,
                selected_devices, only_valid, group_by):
    """
    Filters, cleans, and optionally aggregates sensor data.
    """
    if df is None or df.empty:
        return pd.DataFrame()

    res = df.copy()

    # ──────────────────────────────────────────────
    # 1. TIME & METADATA FILTERING
    # ──────────────────────────────────────────────
    if 'LOG TIME' in res.columns:
        res['LOG TIME'] = pd.to_datetime(res['LOG TIME'], errors='coerce')
        res = res.dropna(subset=['LOG TIME'])
        print(res)
        # FIX: Convert to pd.Timestamp to avoid tz-naive vs tz-aware comparison errors
        start_ts = pd.Timestamp(start_dt)
        stop_ts = pd.Timestamp(stop_dt)
        
        # Sync timezone awareness between data and filter bounds
        if res['LOG TIME'].dt.tz is not None and start_ts.tz is None:
            start_ts = start_ts.tz_localize(res['LOG TIME'].dt.tz)
            stop_ts = stop_ts.tz_localize(res['LOG TIME'].dt.tz)
        elif res['LOG TIME'].dt.tz is None and start_ts.tz is not None:
            start_ts = start_ts.tz_localize(None)
            stop_ts = stop_ts.tz_localize(None)
        print(start_ts)
        res = res[(res['LOG TIME'] > start_ts) & (res['LOG TIME'] <= stop_ts)]

    # Normalize SITE and DEVICE to handle missing/empty values from the CSV.
    if 'SITE' in res.columns:
        res['SITE'] = res['SITE'].fillna('Unassigned').astype(str).str.strip()
        res.loc[res['SITE'] == '', 'SITE'] = 'Unassigned'
        
    if 'DEVICE' in res.columns:
        res['DEVICE'] = res['DEVICE'].fillna('Unknown').astype(str).str.strip()
        res.loc[res['DEVICE'] == '', 'DEVICE'] = 'Unknown'

    # Only filter by the dimension that is actually being grouped.
    if group_by == 'Site':
        if 'DEVICE' in res.columns and selected_devices:
            res = res[res['DEVICE'].isin(selected_devices)]
    elif group_by == 'Device':
        if 'SITE' in res.columns and selected_sites:
            res = res[res['SITE'].isin(selected_sites)]

    if res.empty:
        return res 

    # ──────────────────────────────────────────────
    # 2. COLUMN SELECTION
    # ──────────────────────────────────────────────
    keep_cols = [c for c in ['LOG TIME', 'SITE', 'DEVICE'] if c in res.columns]

    gas_cols_to_keep = []
    invalid_cols_to_keep = []

    for gas in selected_gases:
        if gas in res.columns:
            gas_cols_to_keep.append(gas)
            inv_col = f"INVALID_{gas}"
            if inv_col in res.columns:
                invalid_cols_to_keep.append(inv_col)

    final_cols = list(dict.fromkeys(keep_cols + gas_cols_to_keep + invalid_cols_to_keep))
    res = res[[c for c in final_cols if c in res.columns]]

    # ──────────────────────────────────────────────
    # 3. "ONLY VALID" HANDLING (Raw Data)
    # ──────────────────────────────────────────────
    if only_valid and gas_cols_to_keep:
        for gas in gas_cols_to_keep:
            inv_col = f"INVALID_{gas}"
            if inv_col in res.columns:
                invalid_mask = pd.to_numeric(res[inv_col], errors='coerce').fillna(0) > 0
                res.loc[invalid_mask, gas] = np.nan

    if res.empty:
        return res

    # ──────────────────────────────────────────────
    # 4. AGGREGATION (If interval is not "Raw")
    # ──────────────────────────────────────────────
    if interval != "Raw" and interval is not None:
        try:
            interval_mins = int(interval)
        except (ValueError, TypeError):
            interval_mins = 0

        if interval_mins > 0:
            agg_df = res.copy()
            agg_df = agg_df.set_index('LOG TIME')
            group_col = 'DEVICE' if group_by == 'Device' else 'SITE'
            
            agg_dict = {gas: 'mean' for gas in gas_cols_to_keep}
            for col in ['SITE', 'DEVICE']:
                if col in agg_df.columns and col != group_col and col not in agg_dict:
                    agg_dict[col] = 'first'

            res_agg = agg_df.groupby(
                [group_col, pd.Grouper(freq=f'{interval_mins}min', closed='right', label='right')]
            ).agg(agg_dict).reset_index()

            # ──────────────────────────────────────────────
            # 5. DYNAMIC INVALID FLAG CALCULATION (1-Min Bin Coverage)
            # ──────────────────────────────────────────────
            if gas_cols_to_keep:
                time_index = pd.date_range(start=start_ts, end=stop_ts, freq='1min')
                groups = res[group_col].unique() if group_col in res.columns else [None]
                 
                all_1min_counts = []
                for g in groups:
                    if group_col in res.columns:
                        g_df = agg_df[agg_df[group_col] == g]
                    else:
                        g_df = agg_df
                        
                    valid_flags = pd.DataFrame(index=g_df.index)
                    for gas in gas_cols_to_keep:
                        inv_col = f"INVALID_{gas}"
                        if inv_col in g_df.columns:
                            is_valid = pd.to_numeric(g_df[inv_col], errors='coerce').fillna(0) == 0
                            valid_flags[gas] = is_valid.astype(int)
                        else:
                            valid_flags[gas] = (~g_df[gas].isna()).astype(int)
                            
                    g_counts = valid_flags.resample('1min', closed='right', label='right').sum()
                    
                    if not time_index.empty:
                        g_counts = g_counts.reindex(time_index, fill_value=0)
                    
                    g_counts[group_col] = g
                    all_1min_counts.append(g_counts)
                    
                if all_1min_counts and not time_index.empty:
                    counts_1min_df = pd.concat(all_1min_counts).reset_index().rename(columns={'index': 'LOG TIME'})
                    counts_1min_df = counts_1min_df.set_index('LOG TIME')
                    
                    has_data = (counts_1min_df[gas_cols_to_keep] > 0).astype(int)
                    has_data[group_col] = counts_1min_df[group_col]
                    
                    bins_with_data = has_data.groupby(group_col).resample(f'{interval_mins}min', closed='right', label='right')[gas_cols_to_keep].sum().reset_index()
                    
                    coverage = bins_with_data[gas_cols_to_keep] / interval_mins
                    
                    for gas in gas_cols_to_keep:
                        inv_col = f"INVALID_{gas}"
                        flag_df = bins_with_data[[group_col, 'LOG TIME']].copy()
                        
                        flag_df[inv_col] = (coverage[gas] < 0.8).astype(int)
                        
                        res_agg = res_agg.merge(flag_df, on=[group_col, 'LOG TIME'], how='left')
                        res_agg[inv_col] = res_agg[inv_col].fillna(0).astype(int)
                else:
                    for gas in gas_cols_to_keep:
                        res_agg[f"INVALID_{gas}"] = 0
            else:
                for inv_col in invalid_cols_to_keep:
                    if inv_col in res_agg.columns:
                        res_agg[inv_col] = 0

            # ──────────────────────────────────────────────
            # 6. APPLY "ONLY VALID" TO AGGREGATED INTERVALS
            # ──────────────────────────────────────────────
            if only_valid and gas_cols_to_keep:
                for gas in gas_cols_to_keep:
                    inv_col = f"INVALID_{gas}"
                    if inv_col in res_agg.columns:
                        invalid_mask = res_agg[inv_col] > 0
                        res_agg.loc[invalid_mask, gas] = np.nan

            return res_agg

    # ──────────────────────────────────────────────
    # 7. RAW MODE RETURN
    # ──────────────────────────────────────────────
    return res
