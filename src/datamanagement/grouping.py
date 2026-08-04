"""Module for grouping and aggregating incident data."""
import logging

import numpy as np
import pandas as pd

from datamanagement.db_manager import IncidentDatabase

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
            valid_df[analyte] = (
                pd.to_numeric(res[inv_col], errors='coerce').fillna(1) == 0
            ).astype(int)
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

    main_grouper = pd.Grouper(
        freq=f'{interval_mins}min', closed='left',
        label='right', origin='start_day'
    )
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

    # Sort by group column and then by LOG TIME to ensure consistent ordering
    res_agg = res_agg.sort_values(by=[group_col, 'LOG TIME']).reset_index(drop=True)

    # STEP 3: 1-Minute Coverage Validation
    valid_df['min_bin'] = valid_df['LOG TIME'].dt.ceil('1min')
    valid_df['interval_bin'] = valid_df['min_bin'].dt.ceil(f'{interval_mins}min')

    # Count unique 1-min bins with data per interval bin
    min_counts = valid_df.groupby(
        [group_col, 'interval_bin', 'min_bin']
    )[analyte_cols].sum().reset_index()
    for analyte in analyte_cols:
        min_counts[analyte] = (min_counts[analyte] > 0).astype(int)

    bins_with_data = min_counts.groupby(
        [group_col, 'interval_bin']
    )[analyte_cols].sum().reset_index()
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

def get_spectral_chemicals(incident_path):
    """
    Returns a sorted list of unique individual chemical names identified in spectral results.
    Each spectral result's 'chemicals' field is a comma-delimited string, so we split,
    strip whitespace, and deduplicate to get the final unique list.

    Args:
        incident_path: Path to the incident directory

    Returns:
        sorted list of unique chemical name strings
    """
    db = IncidentDatabase(incident_path)
    with db.get_connection() as conn:
        chems = conn.execute("""
            SELECT DISTINCT chemicals
            FROM spectral_result
            WHERE chemicals IS NOT NULL AND chemicals != ''
        """).fetchall()

    unique_chemicals = set()
    for row in chems:
        chem_string = row[0]
        if not chem_string:
            continue
        # Split the comma-delimited string into individual chemicals
        for chem in chem_string.split(','):
            cleaned = chem.strip()
            if cleaned:
                unique_chemicals.add(cleaned)

    return sorted(unique_chemicals)


def get_plume_summary(incident_path):
    """
    Returns a list of plume records with file names and model datetimes.

    Args:
        incident_path: Path to the incident directory

    Returns:
        list of dicts with file_name and model_dt
    """
    db = IncidentDatabase(incident_path)

    with db.get_connection() as conn:
        plumes = conn.execute("""
            SELECT file_name, model_dt
            FROM plume
            ORDER BY model_dt DESC
        """).fetchall()

    return [dict(row) for row in plumes]
def get_recent_readings(incident_path, data_type, limit=5):
    """
    Returns the most recent readings for a data type.

    Args:
        incident_path: Path to the incident directory
        data_type: One of 'area', 'spot', 'spectral', 'exposure'
        limit: Number of recent readings to return

    Returns:
        list of dicts with reading data
    """
    db = IncidentDatabase(incident_path)

    with db.get_connection() as conn:
        if data_type == "spot":
            query = """
                SELECT m.label AS site, d.label AS device, sr.timestamp AS logtime,
                       a.label AS analyte, sr.value
                FROM spot_reading sr
                JOIN marker m ON sr.marker_id = m.id
                LEFT JOIN device d ON sr.device_id = d.id
                JOIN analyte a ON sr.analyte_id = a.id
                ORDER BY sr.timestamp DESC LIMIT ?
            """
            rows = conn.execute(query, (limit,)).fetchall()
            return [dict(row) for row in rows]

        if data_type == "area":
            query = """
                SELECT d.label AS device, ar.timestamp AS logtime,
                       a.label AS analyte, ara.value
                FROM area_reading ar
                LEFT JOIN device d ON ar.device_id = d.id
                JOIN area_reading_analyte ara ON ar.id = ara.area_reading_id
                JOIN analyte a ON ara.analyte_id = a.id
                ORDER BY ar.timestamp DESC LIMIT ?
            """
            rows = conn.execute(query, (limit,)).fetchall()
            return [dict(row) for row in rows]

        if data_type == "exposure":
            query = """
                SELECT identifier, start_dt, stop_dt, area
                FROM exposure
                ORDER BY start_dt DESC LIMIT ?
            """
            rows = conn.execute(query, (limit,)).fetchall()
            return [dict(row) for row in rows]

        return []

def get_data_overview(incident_path, data_type):
    """
    Returns summary statistics for a data type: count, date range, sites, analytes.

    Args:
        incident_path: Path to the incident directory
        data_type: One of 'area', 'spot', 'spectral', 'exposure', 'plume'

    Returns:
        dict with keys: count, min_date, max_date, sites_count, analytes_count
    """
    db = IncidentDatabase(incident_path)

    with db.get_connection() as conn:
        if data_type == "area":
            count = conn.execute("SELECT COUNT(*) FROM area_reading").fetchone()[0]
            min_max = conn.execute(
                "SELECT MIN(timestamp), MAX(timestamp) FROM area_reading"
            ).fetchone()
            sites = conn.execute(
                "SELECT COUNT(DISTINCT marker_id) FROM area_location"
            ).fetchone()[0]
            analytes = conn.execute(
                "SELECT COUNT(DISTINCT analyte_id) FROM area_reading_analyte"
            ).fetchone()[0]

        elif data_type == "spot":
            count = conn.execute("SELECT COUNT(*) FROM spot_reading").fetchone()[0]
            min_max = conn.execute(
                "SELECT MIN(timestamp), MAX(timestamp) FROM spot_reading"
            ).fetchone()
            sites = conn.execute(
                "SELECT COUNT(DISTINCT marker_id) FROM spot_reading"
            ).fetchone()[0]
            analytes = conn.execute(
                "SELECT COUNT(DISTINCT analyte_id) FROM spot_reading"
            ).fetchone()[0]

        elif data_type == "spectral":
            count = conn.execute("SELECT COUNT(*) FROM spectral_result").fetchone()[0]
            min_max = conn.execute(
                "SELECT MIN(timestamp), MAX(timestamp) FROM spectral_result"
            ).fetchone()
            sites = None  # Not applicable
            analytes = None  # Not applicable

        elif data_type == "exposure":
            count = conn.execute("SELECT COUNT(*) FROM exposure").fetchone()[0]
            min_max = conn.execute(
                "SELECT MIN(start_dt), MAX(stop_dt) FROM exposure"
            ).fetchone()
            sites = None  # Not applicable
            analytes = conn.execute(
                "SELECT COUNT(DISTINCT analyte_id) FROM exposure_reading"
            ).fetchone()[0]

        elif data_type == "plume":
            count = conn.execute("SELECT COUNT(*) FROM plume").fetchone()[0]
            min_max = conn.execute(
                "SELECT MIN(model_dt), MAX(model_dt) FROM plume"
            ).fetchone()
            sites = None  # Not applicable
            analytes = None  # Not applicable

        else:
            return {}

    return {
        "count": count,
        "min_date": min_max[0] if min_max else None,
        "max_date": min_max[1] if min_max else None,
        "sites_count": sites,
        "analytes_count": analytes
    }

# Add this to the bottom of grouping.py

def calculate_summary_dataframe(df, group_col, valid_analytes, is_exposure=False):
    """
    Calculates summary statistics (Min, Max, Mean, Count) for each analyte,
    grouped by the specified column.

    Args:
        df: The filtered (and optionally time-aggregated) Pandas DataFrame.
        group_col: The column to group by ('SITE', 'DEVICE', or 'IDENTIFIER').
        valid_analytes: List of analyte labels to calculate stats for.
        is_exposure: Boolean indicating if the data is exposure type.

    Returns:
        A Pandas DataFrame with columns: ['Group', 'Analyte', 'Min', 'Max', 'Mean', 'Count']
    """
    if df is None or df.empty or not valid_analytes:
        return pd.DataFrame(columns=['Group', 'Analyte', 'Min', 'Max', 'Mean', 'Count'])

    # Ensure the group column exists, fallback if necessary
    if group_col not in df.columns:
        group_col = 'DEVICE' if 'DEVICE' in df.columns else 'SITE'

    rows = []
    groups = df[group_col].dropna().unique()
    groups = sorted(groups, key=str)

    for group_val in groups:
        group_df = df[df[group_col] == group_val]

        for analyte in valid_analytes:
            if is_exposure:
                min_col = f"{analyte}_min"
                max_col = f"{analyte}_max"
                mean_col = f"{analyte}_mean"

                min_v = (
                    group_df[min_col].iloc[0]
                    if min_col in group_df.columns and not group_df[min_col].empty
                    else np.nan
                )
                max_v = (
                    group_df[max_col].iloc[0]
                    if max_col in group_df.columns and not group_df[max_col].empty
                    else np.nan
                )
                mean_v = (
                    group_df[mean_col].iloc[0]
                    if mean_col in group_df.columns and not group_df[mean_col].empty
                    else np.nan
                )
                count_val = len(group_df)

                if pd.notna(min_v) or pd.notna(max_v) or pd.notna(mean_v):
                    rows.append({
                        'Group': str(group_val),
                        'Analyte': analyte,
                        'Min': float(min_v) if pd.notna(min_v) else np.nan,
                        'Max': float(max_v) if pd.notna(max_v) else np.nan,
                        'Mean': float(mean_v) if pd.notna(mean_v) else np.nan,
                        'Count': int(count_val)
                    })
            else:
                if analyte in group_df.columns:
                    analyte_data = group_df[analyte].dropna()
                    count_val = len(analyte_data)
                    if count_val > 0:
                        rows.append({
                            'Group': str(group_val),
                            'Analyte': analyte,
                            'Min': float(analyte_data.min()),
                            'Max': float(analyte_data.max()),
                            'Mean': float(analyte_data.mean()),
                            'Count': int(count_val)
                        })

    return pd.DataFrame(rows, columns=['Group', 'Analyte', 'Min', 'Max', 'Mean', 'Count'])
