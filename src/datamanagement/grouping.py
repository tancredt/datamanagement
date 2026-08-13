"""Module for grouping and aggregating incident data."""

import logging

import numpy as np
import pandas as pd

from datamanagement.db_manager import IncidentDatabase

logger = logging.getLogger(__name__)


# ==========================================
# INTERNAL HELPERS
# ==========================================

def _numeric_series(series):
    """Convert a pandas Series to numeric values where possible."""
    return pd.to_numeric(series, errors="coerce")


def _invalid_mask(df, analyte):
    """
    Return a boolean mask where True means the row is invalid
    for the given analyte.

    A row is invalid when INVALID_{analyte} > 0.
    Missing or non-numeric invalid flags are treated as invalid.
    """
    inv_col = f"INVALID_{analyte}"

    if inv_col in df.columns:
        inv_values = _numeric_series(df[inv_col])
        return inv_values.fillna(1) > 0

    return pd.Series(False, index=df.index)


def _valid_mask(df, analyte):
    """Return a boolean mask where True means the row is valid."""
    return ~_invalid_mask(df, analyte)


def _weighted_mean(values, weights):
    """
    Calculate a weighted mean.

    This is mainly used for aggregated data where a column contains
    mean values and a corresponding _count column contains the number
    of readings that contributed to each mean.
    """
    values = _numeric_series(values)
    weights = _numeric_series(weights)

    mask = values.notna() & weights.notna() & (weights > 0)

    if not mask.any():
        return np.nan

    total_weight = weights[mask].sum()

    if total_weight == 0:
        return np.nan

    return float((values[mask] * weights[mask]).sum() / total_weight)


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

    res["LOG TIME"] = pd.to_datetime(res["LOG TIME"], errors="coerce")
    res = res.dropna(subset=["LOG TIME"])

    if res.empty:
        return pd.DataFrame()

    # Case-insensitive group_by handling.
    group_by_clean = str(group_by or "").strip().lower()
    group_col = "DEVICE" if group_by_clean == "device" else "SITE"

    if group_col not in res.columns:
        group_col = "DEVICE" if "DEVICE" in res.columns else "SITE"

    # Preserve null group values as empty strings so pandas groupby
    # does not silently drop them.
    if group_col in res.columns:
        res[group_col] = res[group_col].fillna("")

    # Identify analyte columns.
    #
    # BATTERY and STATUS are metadata, not analytes.
    metadata_cols = {
        "LOG TIME",
        "SITE",
        "DEVICE",
        "Latitude",
        "Longitude",
        "STATUS",
        "BATTERY",
    }

    analyte_cols = [
        col
        for col in res.select_dtypes(include=[np.number]).columns
        if col not in metadata_cols
        and not str(col).upper().startswith("INVALID_")
    ]

    if not analyte_cols:
        return res

    # STEP 1: Extract validity mask BEFORE dropping INVALID_ cols.
    valid_df = res[["LOG TIME", group_col]].copy()

    for analyte in analyte_cols:
        inv_col = f"INVALID_{analyte}"

        if inv_col in res.columns:
            # 1 if valid (flag == 0), 0 if invalid.
            valid_df[analyte] = (
                _numeric_series(res[inv_col]).fillna(1) == 0
            ).astype(int)
        else:
            # 1 if not NaN, 0 if NaN.
            valid_df[analyte] = (~res[analyte].isna()).astype(int)

    # STEP 2: Exclude invalid values from mean/min/max/count.
    #
    # Anything with INVALID_{analyte} > 0 is invalid.
    for analyte in analyte_cols:
        inv_col = f"INVALID_{analyte}"

        if inv_col in res.columns:
            invalid_mask = _numeric_series(res[inv_col]).fillna(1) > 0
            res.loc[invalid_mask, analyte] = np.nan

    # Drop INVALID_ columns for main aggregation.
    inv_cols = [
        c for c in res.columns
        if str(c).upper().startswith("INVALID_")
    ]

    if inv_cols:
        res = res.drop(columns=inv_cols, errors="ignore")

    agg_df = res.set_index("LOG TIME")

    agg_dict = {
        analyte: ["mean", "min", "max", "count"]
        for analyte in analyte_cols
    }

    preserve_cols = ["SITE", "DEVICE", "Latitude", "Longitude"]

    for col in preserve_cols:
        if col in agg_df.columns and col != group_col and col not in agg_dict:
            agg_dict[col] = "first"

    main_grouper = pd.Grouper(
        freq=f"{interval_mins}min",
        closed="right",
        label="right",
        origin="start_day",
    )

    res_agg = agg_df.groupby(
        [group_col, main_grouper],
        dropna=False
    ).agg(agg_dict)

    # Flatten multi-index columns.
    new_columns = []

    for col, stat in res_agg.columns:
        if col in analyte_cols:
            new_columns.append(col if stat == "mean" else f"{col}_{stat}")
        else:
            new_columns.append(col)

    res_agg.columns = new_columns
    res_agg = res_agg.reset_index()

    # Ensure LOG TIME is correctly named.
    if "LOG TIME" not in res_agg.columns:
        res_agg = res_agg.rename(columns={res_agg.columns[1]: "LOG TIME"})

    # Sort by group column and then by LOG TIME.
    res_agg = res_agg.sort_values(
        by=[group_col, "LOG TIME"]
    ).reset_index(drop=True)

    # STEP 3: 1-Minute Coverage Validation.
    valid_df["min_bin"] = valid_df["LOG TIME"].dt.ceil("1min")
    valid_df["interval_bin"] = valid_df["min_bin"].dt.ceil(f"{interval_mins}min")

    # Count unique 1-min bins with data per interval bin.
    min_counts = valid_df.groupby(
        [group_col, "interval_bin", "min_bin"],
        dropna=False
    )[analyte_cols].sum().reset_index()

    for analyte in analyte_cols:
        min_counts[analyte] = (min_counts[analyte] > 0).astype(int)

    bins_with_data = min_counts.groupby(
        [group_col, "interval_bin"],
        dropna=False
    )[analyte_cols].sum().reset_index()

    bins_with_data = bins_with_data.rename(columns={"interval_bin": "LOG TIME"})

    # Apply 80% threshold rule.
    threshold = 0.8 * interval_mins

    for analyte in analyte_cols:
        inv_col = f"INVALID_{analyte}"

        flag_df = bins_with_data[[group_col, "LOG TIME"]].copy()
        flag_df[inv_col] = (bins_with_data[analyte] < threshold).astype(int)

        res_agg = res_agg.merge(
            flag_df,
            on=[group_col, "LOG TIME"],
            how="left"
        )

        # If no data at all in the bin, it is invalid.
        res_agg[inv_col] = res_agg[inv_col].fillna(1).astype(int)

    # STEP 4: Cleanup.
    #
    # Drop Lat/Lon as they are not meaningful for aggregated time bins.
    res_agg = res_agg.drop(columns=["Latitude", "Longitude"], errors="ignore")

    return res_agg


# ==========================================
# 2. SUMMARISE DATA
# ==========================================

def summarise_data(df):
    """
    Calculates the mean, max, and min for each valid analyte in the dataframe.

    - If the df is raw, it calculates the standard mean, max, and min.
    - If the df is aggregated, it calculates the weighted mean of the means
      where a count column is available, the max of the maxs, and the min
      of the mins.
    - Exposure-style data with only {analyte}_min, {analyte}_max, and
      {analyte}_mean columns is also supported.

    Returns a list of dictionaries:

        [
            {
                "analyte": "O2",
                "stats": {
                    "mean": 20.5,
                    "max": 20.9,
                    "min": 20.1
                }
            },
            ...
        ]
    """
    if df is None or df.empty:
        return []

    metadata_cols = {
        "LOG TIME",
        "SITE",
        "DEVICE",
        "IDENTIFIER",
        "STATUS",
        "BATTERY",
        "Latitude",
        "Longitude",
        "observations",
        "chemicals_identified",
        "comments",
        "file_ref",
    }

    suffixes = ("_min", "_max", "_count", "_mean")

    # Identify analytes dynamically.
    #
    # This supports both normal analyte columns and exposure-style
    # suffix-only columns such as voc(ppm)_min / voc(ppm)_max / voc(ppm)_mean.
    analytes = []
    seen = set()

    for col in df.columns:
        col_str = str(col)

        if col in metadata_cols:
            continue

        if col_str.upper().startswith("INVALID_"):
            continue

        base = None
        matched_suffix = False

        for suffix in suffixes:
            if col_str.endswith(suffix):
                base = col_str[:-len(suffix)]
                matched_suffix = True
                break

        if not matched_suffix:
            if pd.api.types.is_numeric_dtype(df[col]):
                base = col_str

        if not base:
            continue

        if base in metadata_cols:
            continue

        if base in seen:
            continue

        candidate_cols = [
            base,
            f"{base}_min",
            f"{base}_max",
            f"{base}_mean",
        ]

        has_numeric_candidate = any(
            c in df.columns and pd.api.types.is_numeric_dtype(df[c])
            for c in candidate_cols
        )

        if has_numeric_candidate:
            analytes.append(base)
            seen.add(base)

    summary = []

    for analyte in analytes:
        valid_mask = _valid_mask(df, analyte)

        mean_col = f"{analyte}_mean"
        max_col = f"{analyte}_max"
        min_col = f"{analyte}_min"
        count_col = f"{analyte}_count"

        # MEAN
        if analyte in df.columns:
            if count_col in df.columns:
                mean_val = _weighted_mean(
                    df.loc[valid_mask, analyte],
                    df.loc[valid_mask, count_col],
                )
            else:
                col_data = _numeric_series(df.loc[valid_mask, analyte]).dropna()
                mean_val = float(col_data.mean()) if not col_data.empty else np.nan

        elif mean_col in df.columns:
            if count_col in df.columns:
                mean_val = _weighted_mean(
                    df.loc[valid_mask, mean_col],
                    df.loc[valid_mask, count_col],
                )
            else:
                col_data = _numeric_series(df.loc[valid_mask, mean_col]).dropna()
                mean_val = float(col_data.mean()) if not col_data.empty else np.nan

        else:
            mean_val = np.nan

        # MAX
        if max_col in df.columns:
            col_data = _numeric_series(df.loc[valid_mask, max_col]).dropna()
            max_val = float(col_data.max()) if not col_data.empty else np.nan

        elif analyte in df.columns:
            col_data = _numeric_series(df.loc[valid_mask, analyte]).dropna()
            max_val = float(col_data.max()) if not col_data.empty else np.nan

        else:
            max_val = np.nan

        # MIN
        if min_col in df.columns:
            col_data = _numeric_series(df.loc[valid_mask, min_col]).dropna()
            min_val = float(col_data.min()) if not col_data.empty else np.nan

        elif analyte in df.columns:
            col_data = _numeric_series(df.loc[valid_mask, analyte]).dropna()
            min_val = float(col_data.min()) if not col_data.empty else np.nan

        else:
            min_val = np.nan

        summary.append({
            "analyte": analyte,
            "stats": {
                "mean": mean_val,
                "max": max_val,
                "min": min_val,
            },
        })

    return summary


# ==========================================
# 3. SPECTRAL CHEMICALS
# ==========================================

def get_spectral_chemicals(incident_path):
    """
    Returns a sorted list of unique individual chemical names identified
    in spectral results.

    Each spectral result's 'chemicals' field is a comma-delimited string,
    so we split, strip whitespace, and deduplicate to get the final unique list.

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
            WHERE chemicals IS NOT NULL
              AND chemicals != ''
        """).fetchall()

    unique_chemicals = set()

    for row in chems:
        chem_string = row[0]

        if not chem_string:
            continue

        for chem in chem_string.split(","):
            cleaned = chem.strip()

            if cleaned:
                unique_chemicals.add(cleaned)

    return sorted(unique_chemicals)


# ==========================================
# 4. PLUME SUMMARY
# ==========================================

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


# ==========================================
# 5. RECENT READINGS
# ==========================================

def get_recent_readings(incident_path, data_type, limit=5):
    """
    Returns the most recent readings for a data type.

    Args:
        incident_path: Path to the incident directory
        data_type: One of 'area', 'spot', 'spectral', 'exposure'
        limit: Number of recent logical readings to return

    Returns:
        list of dicts with reading data
    """
    db = IncidentDatabase(incident_path)

    with db.get_connection() as conn:
        if data_type == "spot":
            query = """
                WITH latest_groups AS (
                    SELECT marker_id, device_id, timestamp
                    FROM spot_reading
                    GROUP BY marker_id, device_id, timestamp
                    ORDER BY timestamp DESC
                    LIMIT ?
                )
                SELECT m.label AS site,
                       d.label AS device,
                       sr.timestamp AS logtime,
                       a.label AS analyte,
                       sr.value
                FROM spot_reading sr
                JOIN latest_groups lg
                  ON sr.marker_id = lg.marker_id
                 AND sr.timestamp = lg.timestamp
                 AND sr.device_id IS lg.device_id
                JOIN marker m ON sr.marker_id = m.id
                LEFT JOIN device d ON sr.device_id = d.id
                JOIN analyte a ON sr.analyte_id = a.id
                ORDER BY sr.timestamp DESC
            """
            rows = conn.execute(query, (limit,)).fetchall()
            return [dict(row) for row in rows]

        if data_type == "area":
            query = """
                WITH latest_area AS (
                    SELECT ar.id
                    FROM area_reading ar
                    WHERE EXISTS (
                        SELECT 1
                        FROM area_reading_analyte ara
                        WHERE ara.area_reading_id = ar.id
                    )
                    ORDER BY ar.timestamp DESC
                    LIMIT ?
                )
                SELECT d.label AS device,
                       ar.timestamp AS logtime,
                       a.label AS analyte,
                       ara.value
                FROM area_reading ar
                JOIN latest_area la ON ar.id = la.id
                LEFT JOIN device d ON ar.device_id = d.id
                JOIN area_reading_analyte ara ON ar.id = ara.area_reading_id
                JOIN analyte a ON ara.analyte_id = a.id
                ORDER BY ar.timestamp DESC, ar.id
            """
            rows = conn.execute(query, (limit,)).fetchall()
            return [dict(row) for row in rows]

        if data_type == "exposure":
            query = """
                SELECT identifier, start_dt, stop_dt, area
                FROM exposure
                ORDER BY start_dt DESC
                LIMIT ?
            """
            rows = conn.execute(query, (limit,)).fetchall()
            return [dict(row) for row in rows]

        if data_type == "spectral":
            query = """
                SELECT m.label AS site,
                       d.label AS device,
                       sr.timestamp AS logtime,
                       sr.chemicals AS chemicals_identified,
                       sr.comment AS comments,
                       sr.file_ref
                FROM spectral_result sr
                JOIN marker m ON sr.marker_id = m.id
                LEFT JOIN device d ON sr.device_id = d.id
                ORDER BY sr.timestamp DESC
                LIMIT ?
            """
            rows = conn.execute(query, (limit,)).fetchall()
            return [dict(row) for row in rows]

        return []


# ==========================================
# 6. DATA OVERVIEW
# ==========================================

def get_data_overview(incident_path, data_type):
    """
    Returns summary statistics for a data type:
    count, date range, sites, analytes.

    Args:
        incident_path: Path to the incident directory
        data_type: One of 'area', 'spot', 'spectral', 'exposure', 'plume'

    Returns:
        dict with keys: count, min_date, max_date, sites_count, analytes_count
    """
    db = IncidentDatabase(incident_path)

    with db.get_connection() as conn:
        if data_type == "area":
            count = conn.execute(
                "SELECT COUNT(*) FROM area_reading"
            ).fetchone()[0]

            min_max = conn.execute(
                "SELECT MIN(timestamp), MAX(timestamp) FROM area_reading"
            ).fetchone()

            sites = conn.execute(
                """
                SELECT COUNT(DISTINCT marker_id)
                FROM area_reading
                WHERE marker_id IS NOT NULL
                """
            ).fetchone()[0]

            analytes = conn.execute(
                "SELECT COUNT(DISTINCT analyte_id) FROM area_reading_analyte"
            ).fetchone()[0]

        elif data_type == "spot":
            count = conn.execute(
                "SELECT COUNT(*) FROM spot_reading"
            ).fetchone()[0]

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
            count = conn.execute(
                "SELECT COUNT(*) FROM spectral_result"
            ).fetchone()[0]

            min_max = conn.execute(
                "SELECT MIN(timestamp), MAX(timestamp) FROM spectral_result"
            ).fetchone()

            sites = None
            analytes = None

        elif data_type == "exposure":
            count = conn.execute(
                "SELECT COUNT(*) FROM exposure"
            ).fetchone()[0]

            min_max = conn.execute(
                "SELECT MIN(start_dt), MAX(stop_dt) FROM exposure"
            ).fetchone()

            sites = None

            analytes = conn.execute(
                "SELECT COUNT(DISTINCT analyte_id) FROM exposure_reading"
            ).fetchone()[0]

        elif data_type == "plume":
            count = conn.execute(
                "SELECT COUNT(*) FROM plume"
            ).fetchone()[0]

            min_max = conn.execute(
                "SELECT MIN(model_dt), MAX(model_dt) FROM plume"
            ).fetchone()

            sites = None
            analytes = None

        else:
            return {}

    return {
        "count": count,
        "min_date": min_max[0] if min_max else None,
        "max_date": min_max[1] if min_max else None,
        "sites_count": sites,
        "analytes_count": analytes,
    }


# ==========================================
# 7. SUMMARY DATAFRAME
# ==========================================

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
        A Pandas DataFrame with columns:
            ['Group', 'Analyte', 'Min', 'Max', 'Mean', 'Count']
    """
    columns = ["Group", "Analyte", "Min", "Max", "Mean", "Count"]

    if df is None or df.empty or not valid_analytes:
        return pd.DataFrame(columns=columns)

    df = df.copy()

    # Ensure the group column exists, fallback if necessary.
    if group_col not in df.columns:
        if "DEVICE" in df.columns:
            group_col = "DEVICE"
        elif "SITE" in df.columns:
            group_col = "SITE"
        else:
            return pd.DataFrame(columns=columns)

    # Preserve null group values as empty strings.
    df[group_col] = df[group_col].fillna("")

    rows = []

    groups = df[group_col].unique()
    groups = sorted(groups, key=str)

    for group_val in groups:
        group_df = df[df[group_col] == group_val]

        for analyte in valid_analytes:
            inv_col = f"INVALID_{analyte}"

            if inv_col in group_df.columns:
                valid_mask = _numeric_series(group_df[inv_col]).fillna(1) == 0
                analyte_df = group_df.loc[valid_mask]
            else:
                analyte_df = group_df

            if is_exposure:
                min_col = f"{analyte}_min"
                max_col = f"{analyte}_max"
                mean_col = f"{analyte}_mean"

                if min_col in analyte_df.columns:
                    min_data = _numeric_series(analyte_df[min_col]).dropna()
                    min_v = float(min_data.min()) if not min_data.empty else np.nan
                else:
                    min_v = np.nan

                if max_col in analyte_df.columns:
                    max_data = _numeric_series(analyte_df[max_col]).dropna()
                    max_v = float(max_data.max()) if not max_data.empty else np.nan
                else:
                    max_v = np.nan

                if mean_col in analyte_df.columns:
                    mean_data = _numeric_series(analyte_df[mean_col]).dropna()
                    mean_v = float(mean_data.mean()) if not mean_data.empty else np.nan
                else:
                    mean_v = np.nan

                count_cols = [
                    col
                    for col in [min_col, max_col, mean_col]
                    if col in analyte_df.columns
                ]

                if count_cols:
                    count_val = int(analyte_df[count_cols].notna().any(axis=1).sum())
                else:
                    count_val = 0

                if pd.notna(min_v) or pd.notna(max_v) or pd.notna(mean_v):
                    rows.append({
                        "Group": str(group_val),
                        "Analyte": analyte,
                        "Min": float(min_v) if pd.notna(min_v) else np.nan,
                        "Max": float(max_v) if pd.notna(max_v) else np.nan,
                        "Mean": float(mean_v) if pd.notna(mean_v) else np.nan,
                        "Count": int(count_val),
                    })

            else:
                min_col = f"{analyte}_min"
                max_col = f"{analyte}_max"
                count_col = f"{analyte}_count"

                analyte_data = pd.Series(dtype=float)

                if analyte in analyte_df.columns:
                    analyte_data = _numeric_series(analyte_df[analyte]).dropna()

                # Min
                if min_col in analyte_df.columns:
                    min_data = _numeric_series(analyte_df[min_col]).dropna()
                    min_v = float(min_data.min()) if not min_data.empty else np.nan
                elif not analyte_data.empty:
                    min_v = float(analyte_data.min())
                else:
                    min_v = np.nan

                # Max
                if max_col in analyte_df.columns:
                    max_data = _numeric_series(analyte_df[max_col]).dropna()
                    max_v = float(max_data.max()) if not max_data.empty else np.nan
                elif not analyte_data.empty:
                    max_v = float(analyte_data.max())
                else:
                    max_v = np.nan

                # Mean
                if count_col in analyte_df.columns and analyte in analyte_df.columns:
                    mean_v = _weighted_mean(
                        analyte_df[analyte],
                        analyte_df[count_col],
                    )
                elif not analyte_data.empty:
                    mean_v = float(analyte_data.mean())
                else:
                    mean_v = np.nan

                # Count
                if count_col in analyte_df.columns:
                    count_data = _numeric_series(analyte_df[count_col]).dropna()
                    count_val = int(count_data.sum()) if not count_data.empty else 0

                    if count_val == 0:
                        count_val = len(analyte_data)
                else:
                    count_val = len(analyte_data)

                if (
                    pd.notna(min_v)
                    or pd.notna(max_v)
                    or pd.notna(mean_v)
                    or count_val > 0
                ):
                    rows.append({
                        "Group": str(group_val),
                        "Analyte": analyte,
                        "Min": float(min_v) if pd.notna(min_v) else np.nan,
                        "Max": float(max_v) if pd.notna(max_v) else np.nan,
                        "Mean": float(mean_v) if pd.notna(mean_v) else np.nan,
                        "Count": int(count_val),
                    })

    return pd.DataFrame(rows, columns=columns)
