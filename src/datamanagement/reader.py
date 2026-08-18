"""Module for reading incident data from database files."""

import os
import json
import logging

import pandas as pd
import numpy as np

from datamanagement.db_manager import IncidentDatabase

logger = logging.getLogger(__name__)


# ==========================================
# 1. HELPER FUNCTIONS
# ==========================================

def _load_preferences(incident_path):
    """Loads VOC and LEL correction factors from preferences.json."""
    prefs_file = os.path.join(incident_path, "meta", "preferences.json")

    voc_corr = 1.0
    lel_corr = 1.0

    if os.path.exists(prefs_file):
        try:
            with open(prefs_file, "r", encoding="utf-8") as f:
                data = json.load(f)

            prefs = data.get("preferences", {})
            voc_corr = float(prefs.get("voc_correction", 1.0))
            lel_corr = float(prefs.get("lel_correction", 1.0))

        except Exception as e:
            logger.error("Failed to load preferences: %s", e)

    return voc_corr, lel_corr


def _safe_float(value):
    """Convert a value to float where possible, returning NaN if not possible."""
    if value is None:
        return np.nan

    try:
        return float(value)
    except (TypeError, ValueError):
        return np.nan


def _apply_corrections(df, incident_path):
    """Applies VOC and LEL correction factors to the DataFrame."""
    if df is None or df.empty:
        return df

    voc_corr, lel_corr = _load_preferences(incident_path)

    if voc_corr == 1.0 and lel_corr == 1.0:
        return df

    corrections = {
        "voc(ppm)": voc_corr,
        "lel(%lel)": lel_corr,
    }

    suffixes = ("", "_min", "_max", "_mean")

    targets = {
        base + suffix: factor
        for base, factor in corrections.items()
        for suffix in suffixes
    }

    for col in df.columns:
        col_lower = str(col).lower()
        if col_lower in targets:
            df[col] = pd.to_numeric(df[col], errors="coerce") * targets[col_lower]

    return df


# ==========================================
# 2. AREA DATA
# ==========================================

def read_area_data(
    incident_path,
    start_time=None,
    stop_time=None,
    devices=None,
    sites=None,
    analytes=None,
    only_valid=False
):
    """Read area monitoring data from the database.

    Args:
        incident_path: Path to the incident folder.
        start_time: Optional filter for readings after this time.
        stop_time: Optional filter for readings before this time.
        devices: Required non-empty list of device labels to include.
        sites: Required non-empty list of site names to include.
        analytes: Required non-empty list of analyte labels to include.
        only_valid: If True, analyte values with INVALID_{analyte} > 0 are
            treated as invalid and set to NaN. The INVALID flag itself is
            preserved.

    Returns:
        pandas.DataFrame: Area reading data. Returns an empty DataFrame if
        devices, sites, or analytes are missing or empty.
    """
    db = IncidentDatabase(incident_path)

    query = """
    SELECT ar.timestamp AS logtime,
           d.label AS device,
           ar.status,
           ar.battery,
           ar.latitude,
           ar.longitude,
           m.label AS site,
           a.label AS analyte,
           ara.value,
           COALESCE(ara.invalidation_id, 0) AS invalid_flag
    FROM area_reading ar
    LEFT JOIN device d ON ar.device_id = d.id
    LEFT JOIN area_reading_analyte ara ON ar.id = ara.area_reading_id
    LEFT JOIN analyte a ON ara.analyte_id = a.id
    LEFT JOIN marker m ON ar.marker_id = m.id
    WHERE 1=1
    """

    params = []

    if start_time:
        query += " AND ar.timestamp > ?"
        params.append(str(start_time))

    if stop_time:
        query += " AND ar.timestamp <= ?"
        params.append(str(stop_time))

    if devices:
        placeholders = ",".join(["?"] * len(devices))
        query += f" AND d.label IN ({placeholders})"
        params.extend(devices)

    if sites:
        placeholders = ",".join(["?"] * len(sites))
        query += f" AND (m.label IN ({placeholders}))"
        params.extend(sites)

    if analytes:
        placeholders = ",".join(["?"] * len(analytes))
        query += f" AND a.label IN ({placeholders})"
        params.extend(analytes)

    query += " ORDER BY ar.timestamp ASC"

    with db.get_connection() as conn:
        conn.set_trace_callback(print)
        rows = conn.execute(query, params).fetchall()

    readings_dict = {}

    for row in rows:
        key = (row["device"], row["logtime"])

        if key not in readings_dict:
            readings_dict[key] = {
                "logtime": row["logtime"],
                "device": row["device"] or "",
                "site": row["site"],
                "status": row["status"] or "",
                "battery": row["battery"],
                "latitude": row["latitude"],
                "longitude": row["longitude"],
            }

        if row["analyte"]:
            readings_dict[key][row["analyte"]] = row["value"]
            readings_dict[key][f"INVALID_{row['analyte']}"] = row["invalid_flag"]

    area_readings = list(readings_dict.values())

    if not area_readings:
        return pd.DataFrame()

    analytes_data = db.get_analytes()
    available_analytes = [a["label"] for a in analytes_data]

    if analytes:
        available_analytes = [a for a in available_analytes if a in analytes]

    rows_out = []

    for r in area_readings:
        row = {
            "LOG TIME": r.get("logtime"),
            "DEVICE": r.get("device", ""),
            "SITE": r.get("site"),
            "STATUS": r.get("status", ""),
            "BATTERY": r.get("battery"),
            "Latitude": r.get("latitude"),
            "Longitude": r.get("longitude"),
        }

        for analyte in available_analytes:
            invalid_col = f"INVALID_{analyte}"
            invalid_value = r.get(invalid_col, 0)

            row[invalid_col] = invalid_value

            if only_valid:
                invalid_numeric = pd.to_numeric(invalid_value, errors="coerce")

                if pd.notna(invalid_numeric) and invalid_numeric > 0:
                    row[analyte] = np.nan
                else:
                    row[analyte] = r.get(analyte)
            else:
                row[analyte] = r.get(analyte)

        rows_out.append(row)

    df = pd.DataFrame(rows_out)

    if not df.empty and "LOG TIME" in df.columns:
        df["LOG TIME"] = pd.to_datetime(df["LOG TIME"], errors="coerce")

    df = _apply_corrections(df, incident_path)

    return df


# ==========================================
# 3. SPOT DATA
# ==========================================

def read_spot_data(
    incident_path,
    start_time=None,
    stop_time=None,
    devices=None,
    sites=None,
    analytes=None
):
    """Read spot monitoring data from the database.

    Args:
        incident_path: Path to the incident folder.
        start_time: Optional filter for readings after this time.
        stop_time: Optional filter for readings before this time.
        devices: Required non-empty list of device labels to include.
        sites: Required non-empty list of site names to include.
        analytes: Required non-empty list of analyte labels to include.

    Returns:
        pandas.DataFrame: Spot reading data. Returns an empty DataFrame if
        devices, sites, or analytes are missing or empty.
    """
    db = IncidentDatabase(incident_path)

    query = """
    SELECT m.label AS location,
           d.label AS device,
           sr.timestamp AS logtime,
           sr.comment AS observations,
           a.label AS analyte,
           sr.value
    FROM spot_reading sr
    JOIN marker m ON sr.marker_id = m.id
    LEFT JOIN device d ON sr.device_id = d.id
    JOIN analyte a ON sr.analyte_id = a.id
    WHERE 1=1
    """

    params = []

    if start_time:
        query += " AND sr.timestamp >= ?"
        params.append(str(start_time))

    if stop_time:
        query += " AND sr.timestamp <= ?"
        params.append(str(stop_time))

    if devices:
        placeholders = ",".join(["?"] * len(devices))
        query += f" AND d.label IN ({placeholders})"
        params.extend(devices)

    if sites:
        placeholders = ",".join(["?"] * len(sites))
        query += f" AND (m.label IN ({placeholders}))"
        params.extend(sites)

    if analytes:
        placeholders = ",".join(["?"] * len(analytes))
        query += f" AND a.label IN ({placeholders})"
        params.extend(analytes)

    query += " ORDER BY sr.timestamp ASC"

    with db.get_connection() as conn:
        rows = conn.execute(query, params).fetchall()

    readings_dict = {}

    for row in rows:
        key = (row["location"], row["device"] or "", row["logtime"])

        if key not in readings_dict:
            readings_dict[key] = {
                "location": row["location"],
                "device": row["device"] or "",
                "logtime": row["logtime"],
                "observations": row["observations"] or "",
            }

        readings_dict[key][row["analyte"]] = row["value"]

    spot_readings = list(readings_dict.values())

    if not spot_readings:
        return pd.DataFrame()

    analytes_data = db.get_analytes()
    available_analytes = [a["label"] for a in analytes_data]

    if analytes:
        available_analytes = [a for a in available_analytes if a in analytes]

    rows_out = []

    for r in spot_readings:
        row = {
            "LOG TIME": r.get("logtime"),
            "DEVICE": r.get("device", ""),
            "SITE": r.get("location"),
            "observations": r.get("observations", ""),
            "Latitude": np.nan,
            "Longitude": np.nan,
        }

        for analyte in available_analytes:
            row[analyte] = r.get(analyte)
            row[f"INVALID_{analyte}"] = 0

        rows_out.append(row)

    df = pd.DataFrame(rows_out)

    if not df.empty and "LOG TIME" in df.columns:
        df["LOG TIME"] = pd.to_datetime(df["LOG TIME"], errors="coerce")

    df = _apply_corrections(df, incident_path)

    return df


# ==========================================
# 4. SPECTRAL DATA
# ==========================================

def read_spectral_data(
    incident_path,
    start_time=None,
    stop_time=None,
    devices=None,
    sites=None
):
    """Read spectral data from the database.

    Args:
        incident_path: Path to the incident folder.
        start_time: Optional filter for readings after this time.
        stop_time: Optional filter for readings before this time.
        devices: Required non-empty list of device labels to include.
        sites: Required non-empty list of site names to include.

    Returns:
        pandas.DataFrame: Spectral reading data. Returns an empty DataFrame if
        devices or sites are missing or empty.
    """
    db = IncidentDatabase(incident_path)

    query = """
    SELECT m.label AS location,
           d.label AS device,
           sr.timestamp AS logtime,
           sr.chemicals AS chemicals_identified,
           sr.comment AS comments,
           sr.file_ref
    FROM spectral_result sr
    JOIN marker m ON sr.marker_id = m.id
    LEFT JOIN device d ON sr.device_id = d.id
    WHERE 1=1
    """

    params = []

    if start_time:
        query += " AND sr.timestamp >= ?"
        params.append(str(start_time))

    if stop_time:
        query += " AND sr.timestamp <= ?"
        params.append(str(stop_time))

    if devices:
        placeholders = ",".join(["?"] * len(devices))
        query += f" AND d.label IN ({placeholders})"
        params.extend(devices)

    if sites:
        placeholders = ",".join(["?"] * len(sites))
        query += f" AND (m.label IN ({placeholders}))"
        params.extend(sites)

    query += " ORDER BY sr.timestamp ASC"

    with db.get_connection() as conn:
        rows = conn.execute(query, params).fetchall()

    if not rows:
        return pd.DataFrame()

    rows_out = []

    for row in rows:
        r = dict(row)

        rows_out.append({
            "LOG TIME": r.get("logtime"),
            "DEVICE": r.get("device", ""),
            "SITE": r.get("location"),
            "chemicals_identified": r.get("chemicals_identified", ""),
            "comments": r.get("comments", ""),
            "file_ref": r.get("file_ref", ""),
        })

    df = pd.DataFrame(rows_out)

    if not df.empty and "LOG TIME" in df.columns:
        df["LOG TIME"] = pd.to_datetime(df["LOG TIME"], errors="coerce")

    return df


# ==========================================
# 5. EXPOSURE DATA
# ==========================================

def read_exposure_data(
    incident_path,
    start_time=None,
    stop_time=None,
    devices=None,
    analytes=None
):
    """Read exposure data from the database.

    Args:
        incident_path: Path to the incident folder.
        start_time: Optional filter for readings after this time.
        stop_time: Optional filter for readings before this time.
        devices: Required non-empty list of exposure identifiers to include.
        analytes: Required non-empty list of analyte labels to include.

    Returns:
        pandas.DataFrame: Exposure reading data. Returns an empty DataFrame if
        devices or analytes are missing or empty.
    """
    logger.info(
        "Exposure filters → devices=%s | analytes=%s | %s → %s",
        devices,
        analytes,
        start_time,
        stop_time
    )

    db = IncidentDatabase(incident_path)

    query = """
    SELECT e.identifier,
           e.start_dt,
           e.stop_dt,
           e.area,
           e.activities,
           e.respiratory,
           e.clothing,
           e.footwear,
           a.label AS analyte,
           er.min_value,
           er.max_value,
           er.mean_value
    FROM exposure e
    LEFT JOIN exposure_reading er ON e.id = er.exposure_id
    LEFT JOIN analyte a ON er.analyte_id = a.id
    WHERE 1=1
    """

    params = []

    if start_time:
        query += " AND e.start_dt >= ?"
        params.append(str(start_time))

    if stop_time:
        query += " AND e.start_dt <= ?"
        params.append(str(stop_time))

    if analytes:
        placeholders = ",".join(["?"] * len(analytes))
        query += f" AND a.label IN ({placeholders})"
        params.extend(analytes)

    if devices:
        placeholders = ",".join(["?"] * len(devices))
        query += f" AND e.identifier IN ({placeholders})"
        params.extend(devices)

    query += " ORDER BY e.start_dt ASC"

    with db.get_connection() as conn:
        rows = conn.execute(query, params).fetchall()

    exposures_dict = {}

    for row in rows:
        key = (row["identifier"], row["start_dt"])

        if key not in exposures_dict:
            exposures_dict[key] = {
                "identifier": row["identifier"],
                "start": row["start_dt"],
                "stop": row["stop_dt"],
                "area": row["area"] or "",
                "activities": row["activities"] or "",
                "resp_protection": row["respiratory"] or "",
                "clothing": row["clothing"] or "",
                "footwear": row["footwear"] or "",
                "values": {},
            }

        if row["analyte"]:
            exposures_dict[key]["values"][row["analyte"]] = {
                "min": row["min_value"],
                "max": row["max_value"],
                "mean": row["mean_value"],
            }

    exposures = list(exposures_dict.values())

    if not exposures:
        return pd.DataFrame()

    analytes_data = db.get_analytes()
    available_analytes = [a["label"] for a in analytes_data]

    if analytes:
        available_analytes = [a for a in available_analytes if a in analytes]

    rows_out = []

    for exp in exposures:
        row = {
            "LOG TIME": exp.get("start"),
            "IDENTIFIER": exp.get("identifier", ""),
            "SITE": exp.get("area", ""),
        }

        values = exp.get("values", {})

        for analyte in available_analytes:
            if analyte in values:
                v = values[analyte]

                if isinstance(v, dict):
                    min_value = _safe_float(v.get("min"))
                    max_value = _safe_float(v.get("max"))
                    mean_value = _safe_float(v.get("mean"))

                    if pd.notna(min_value):
                        row[f"{analyte}_min"] = min_value

                    if pd.notna(max_value):
                        row[f"{analyte}_max"] = max_value

                    if pd.notna(mean_value):
                        row[f"{analyte}_mean"] = mean_value

        rows_out.append(row)

    df = pd.DataFrame(rows_out)

    if not df.empty and "LOG TIME" in df.columns:
        df["LOG TIME"] = pd.to_datetime(df["LOG TIME"], errors="coerce")

    df = _apply_corrections(df, incident_path)

    return df


# ==========================================
# 6. BATTERY DATA
# ==========================================

def read_battery_data(incident_path, device_label=None):
    """Read battery data from the database with an optional device filter.

    Args:
        incident_path: Path to the incident folder.
        device_label: Optional device label to filter by.

    Returns:
        pandas.DataFrame: Battery reading data.
    """
    db = IncidentDatabase(incident_path)

    query = """
    SELECT ar.timestamp AS logtime,
           d.label AS device,
           ar.battery
    FROM area_reading ar
    LEFT JOIN device d ON ar.device_id = d.id
    WHERE ar.battery IS NOT NULL
    """

    params = []

    if device_label:
        query += " AND d.label = ?"
        params.append(device_label)

    query += " ORDER BY ar.timestamp ASC"

    with db.get_connection() as conn:
        rows = conn.execute(query, params).fetchall()

    if not rows:
        return pd.DataFrame(columns=["LOG TIME", "DEVICE", "BATTERY"])

    data = []

    for row in rows:
        data.append({
            "LOG TIME": row["logtime"],
            "DEVICE": row["device"] or "",
            "BATTERY": row["battery"],
        })

    df = pd.DataFrame(data)

    if not df.empty and "LOG TIME" in df.columns:
        df["LOG TIME"] = pd.to_datetime(df["LOG TIME"], errors="coerce")

    return df
