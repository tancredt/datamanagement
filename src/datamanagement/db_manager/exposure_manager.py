import logging
import sqlite3
from datetime import datetime

logger = logging.getLogger(__name__)


class ExposureMixin:
    """Mixin providing exposure-related database operations."""

    # ─────────────────────────────────────────────────────────
    # INTERNAL HELPERS
    # ─────────────────────────────────────────────────────────

    def _parse_datetime(self, value):
        """
        Parse a datetime value from either a datetime object or string.
        """
        if isinstance(value, datetime):
            return value

        if value is None:
            return None

        text = str(value).strip().replace("T", " ")

        if not text:
            return None

        formats = [
            "%Y-%m-%d %H:%M:%S",
            "%Y-%m-%d %H:%M",
        ]

        for fmt in formats:
            try:
                return datetime.strptime(text, fmt)
            except ValueError:
                continue

        try:
            return datetime.fromisoformat(text)
        except ValueError:
            return None

    def _normalize_datetime(self, value):
        """
        Convert a datetime-like value into the canonical storage string:
        YYYY-MM-DD HH:MM:SS
        """
        dt = self._parse_datetime(value)

        if not dt:
            return ""

        return dt.strftime("%Y-%m-%d %H:%M:%S")

    def _clean_numeric_value(self, value):
        """Convert a value to float where possible, returning None if not possible."""
        if value is None:
            return None

        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    def _exposure_exists(self, conn, identifier, start_dt, exclude_id=None):
        """
        Check whether an exposure already exists with the same identifier
        and start_dt.
        """
        identifier = str(identifier or "").strip()
        start_dt = str(start_dt or "").strip()

        if not identifier or not start_dt:
            return None

        query = """
            SELECT id
            FROM exposure
            WHERE identifier = ?
              AND start_dt = ?
        """
        params = [identifier, start_dt]

        if exclude_id is not None:
            query += " AND id != ?"
            params.append(exclude_id)

        return conn.execute(query, tuple(params)).fetchone()

    def _get_or_create_device_id_on_connection(self, conn, label, device_type):
        """
        Get or create a device ID using the same SQLite connection.
        """
        label = str(label or "").strip()

        if not label:
            return None

        row = conn.execute(
            "SELECT id FROM device WHERE label = ?",
            (label,),
        ).fetchone()

        if row:
            return row["id"]

        try:
            cursor = conn.execute(
                "INSERT INTO device (label, device_type) VALUES (?, ?)",
                (label, device_type),
            )
            return cursor.lastrowid
        except sqlite3.IntegrityError:
            row = conn.execute(
                "SELECT id FROM device WHERE label = ?",
                (label,),
            ).fetchone()
            return row["id"] if row else None

    def _get_valid_exposure_values(self, values, analyte_lookup):
        """
        Return only analyte value entries that are usable for database insert.
        """
        valid_values = {}
        values = values or {}
        analyte_lookup = analyte_lookup or {}

        for analyte_label, stats in values.items():
            if not isinstance(stats, dict):
                continue

            if analyte_lookup.get(analyte_label) is None:
                continue

            valid_values[analyte_label] = stats

        return valid_values

    def _insert_exposure_readings(
        self,
        conn,
        exposure_id,
        valid_values,
        analyte_lookup,
        device_id
    ):
        """
        Insert exposure readings for an exposure ID.
        """
        for analyte_label, stats in valid_values.items():
            analyte_id = analyte_lookup[analyte_label]

            conn.execute(
                """
                INSERT INTO exposure_reading
                (
                    exposure_id,
                    analyte_id,
                    device_id,
                    min_value,
                    max_value,
                    mean_value
                )
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    exposure_id,
                    analyte_id,
                    device_id,
                    self._clean_numeric_value(stats.get("min")),
                    self._clean_numeric_value(stats.get("max")),
                    self._clean_numeric_value(stats.get("mean")),
                ),
            )

    # ─────────────────────────────────────────────────────────
    # READ OPERATIONS
    # ─────────────────────────────────────────────────────────

    def get_exposure_ids(self):
        """Returns list of all unique exposure identifiers."""
        with self.get_connection() as conn:
            query = """
                SELECT DISTINCT identifier
                FROM exposure
                WHERE identifier IS NOT NULL
                  AND identifier != ''
                ORDER BY identifier
            """
            rows = conn.execute(query).fetchall()
            return [row["identifier"] for row in rows]

    def get_exposures(self):
        """
        Returns all exposure monitoring sessions with their analyte readings.
        """
        with self.get_connection() as conn:
            exp_rows = conn.execute(
                """
                SELECT id, identifier, start_dt, stop_dt, area, activities,
                       respiratory, clothing, footwear
                FROM exposure
                ORDER BY start_dt ASC
                """
            ).fetchall()

            if not exp_rows:
                return []

            exposure_ids = [row["id"] for row in exp_rows]
            placeholders = ",".join(["?"] * len(exposure_ids))

            reading_rows = conn.execute(
                f"""
                SELECT er.exposure_id,
                       a.label,
                       er.min_value,
                       er.max_value,
                       er.mean_value,
                       d.label AS device_label
                FROM exposure_reading er
                JOIN analyte a ON er.analyte_id = a.id
                LEFT JOIN device d ON er.device_id = d.id
                WHERE er.exposure_id IN ({placeholders})
                """,
                tuple(exposure_ids),
            ).fetchall()

            readings_by_exposure = {}
            device_by_exposure = {}

            for r in reading_rows:
                exp_id = r["exposure_id"]

                if exp_id not in readings_by_exposure:
                    readings_by_exposure[exp_id] = {}

                if exp_id not in device_by_exposure and r["device_label"]:
                    device_by_exposure[exp_id] = r["device_label"]

                readings_by_exposure[exp_id][r["label"]] = {
                    "min": r["min_value"],
                    "max": r["max_value"],
                    "mean": r["mean_value"],
                }

            exposures = []

            for exp in exp_rows:
                exposures.append({
                    "db_id": exp["id"],
                    "id": exp["identifier"],
                    "device": device_by_exposure.get(exp["id"], ""),
                    "start": exp["start_dt"],
                    "stop": exp["stop_dt"],
                    "area": exp["area"],
                    "activities": exp["activities"],
                    "resp_protection": exp["respiratory"],
                    "clothing": exp["clothing"],
                    "footwear": exp["footwear"],
                    "values": readings_by_exposure.get(exp["id"], {}),
                })

        return exposures

    # ─────────────────────────────────────────────────────────
    # CREATE
    # ─────────────────────────────────────────────────────────

    def add_exposure(self, data, analyte_lookup):
        """
        Adds a new exposure monitoring session.
        """
        data = data or {}
        analyte_lookup = analyte_lookup or {}

        identifier = str(data.get("id", "")).strip()
        device_label = str(data.get("device", "")).strip()
        area = str(data.get("area", "")).strip()
        activities = str(data.get("activities", "")).strip()
        respiratory = str(data.get("resp_protection", "")).strip()
        clothing = str(data.get("clothing", "")).strip()
        footwear = str(data.get("footwear", "")).strip()

        values = data.get("values", {}) or {}
        valid_values = self._get_valid_exposure_values(values, analyte_lookup)

        start_obj = self._parse_datetime(data.get("start"))
        stop_obj = self._parse_datetime(data.get("stop"))

        if not identifier:
            return False, "Id is mandatory."

        if not start_obj or not stop_obj:
            return False, "Start and Stop times are mandatory."

        if start_obj >= stop_obj:
            return False, "Start time must be before Stop time."

        start_dt = start_obj.strftime("%Y-%m-%d %H:%M:%S")
        stop_dt = stop_obj.strftime("%Y-%m-%d %H:%M:%S")

        with self.get_connection() as conn:
            duplicate = self._exposure_exists(conn, identifier, start_dt)

            if duplicate:
                return False, (
                    f"An exposure with Id '{identifier}' already exists "
                    f"at {start_dt}."
                )

            device_id = None

            if device_label:
                device_id = self._get_or_create_device_id_on_connection(
                    conn,
                    device_label,
                    "personal",
                )

            if valid_values and device_id is None:
                return False, "Device is mandatory when analyte readings are provided."

            try:
                exposure_id = conn.execute(
                    """
                    INSERT INTO exposure
                    (
                        identifier,
                        start_dt,
                        stop_dt,
                        area,
                        activities,
                        respiratory,
                        clothing,
                        footwear
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        identifier,
                        start_dt,
                        stop_dt,
                        area,
                        activities,
                        respiratory,
                        clothing,
                        footwear,
                    ),
                ).lastrowid

            except sqlite3.IntegrityError:
                return False, (
                    f"An exposure with Id '{identifier}' already exists "
                    f"at {start_dt}."
                )

            self._insert_exposure_readings(
                conn=conn,
                exposure_id=exposure_id,
                valid_values=valid_values,
                analyte_lookup=analyte_lookup,
                device_id=device_id,
            )

            conn.commit()

        return True, ""

    # ─────────────────────────────────────────────────────────
    # UPDATE
    # ─────────────────────────────────────────────────────────

    def edit_exposure(self, old_data, new_data, analyte_lookup):
        """
        Edits an existing exposure monitoring session.
        """
        old_data = old_data or {}
        new_data = new_data or {}
        analyte_lookup = analyte_lookup or {}

        identifier = str(new_data.get("id", "")).strip()
        device_label = str(new_data.get("device", "")).strip()
        area = str(new_data.get("area", "")).strip()
        activities = str(new_data.get("activities", "")).strip()
        respiratory = str(new_data.get("resp_protection", "")).strip()
        clothing = str(new_data.get("clothing", "")).strip()
        footwear = str(new_data.get("footwear", "")).strip()

        values = new_data.get("values", {}) or {}
        valid_values = self._get_valid_exposure_values(values, analyte_lookup)

        start_obj = self._parse_datetime(new_data.get("start"))
        stop_obj = self._parse_datetime(new_data.get("stop"))

        if not identifier:
            return False, "Id is mandatory."

        if not start_obj or not stop_obj:
            return False, "Start and Stop times are mandatory."

        if start_obj >= stop_obj:
            return False, "Start time must be before Stop time."

        start_dt = start_obj.strftime("%Y-%m-%d %H:%M:%S")
        stop_dt = stop_obj.strftime("%Y-%m-%d %H:%M:%S")

        with self.get_connection() as conn:
            old_exposure_id = None

            old_db_id = old_data.get("db_id")

            if old_db_id is not None:
                row = conn.execute(
                    "SELECT id FROM exposure WHERE id = ?",
                    (old_db_id,),
                ).fetchone()

                if row:
                    old_exposure_id = row["id"]

            if old_exposure_id is None:
                old_identifier = str(old_data.get("id", "")).strip()
                old_start_dt = self._normalize_datetime(old_data.get("start"))

                row = self._exposure_exists(
                    conn,
                    old_identifier,
                    old_start_dt,
                )

                if not row:
                    return False, "Could not find the original exposure to edit."

                old_exposure_id = row["id"]

            duplicate = self._exposure_exists(
                conn,
                identifier,
                start_dt,
                exclude_id=old_exposure_id,
            )

            if duplicate:
                return False, (
                    f"Another exposure with Id '{identifier}' already exists "
                    f"at {start_dt}."
                )

            device_id = None

            if device_label:
                device_id = self._get_or_create_device_id_on_connection(
                    conn,
                    device_label,
                    "personal",
                )

            if valid_values and device_id is None:
                return False, "Device is mandatory when analyte readings are provided."

            try:
                conn.execute(
                    "DELETE FROM exposure_reading WHERE exposure_id = ?",
                    (old_exposure_id,),
                )

                conn.execute(
                    """
                    UPDATE exposure
                    SET identifier = ?,
                        start_dt = ?,
                        stop_dt = ?,
                        area = ?,
                        activities = ?,
                        respiratory = ?,
                        clothing = ?,
                        footwear = ?
                    WHERE id = ?
                    """,
                    (
                        identifier,
                        start_dt,
                        stop_dt,
                        area,
                        activities,
                        respiratory,
                        clothing,
                        footwear,
                        old_exposure_id,
                    ),
                )

            except sqlite3.IntegrityError:
                conn.rollback()
                return False, (
                    f"Another exposure with Id '{identifier}' already exists "
                    f"at {start_dt}."
                )

            self._insert_exposure_readings(
                conn=conn,
                exposure_id=old_exposure_id,
                valid_values=valid_values,
                analyte_lookup=analyte_lookup,
                device_id=device_id,
            )

            conn.commit()

        return True, ""

    # ─────────────────────────────────────────────────────────
    # DELETE
    # ─────────────────────────────────────────────────────────

    def delete_exposure(self, data):
        """
        Deletes an exposure monitoring session.
        """
        data = data or {}

        with self.get_connection() as conn:
            row = None

            exposure_db_id = data.get("db_id")

            if exposure_db_id is not None:
                row = conn.execute(
                    "SELECT id FROM exposure WHERE id = ?",
                    (exposure_db_id,),
                ).fetchone()

            if not row:
                identifier = str(data.get("id", "")).strip()
                start_dt = self._normalize_datetime(data.get("start"))

                row = self._exposure_exists(
                    conn,
                    identifier,
                    start_dt,
                )

            if not row:
                return False, "Could not find exposure to delete."

            exposure_id = row["id"]

            conn.execute(
                "DELETE FROM exposure_reading WHERE exposure_id = ?",
                (exposure_id,),
            )

            conn.execute(
                "DELETE FROM exposure WHERE id = ?",
                (exposure_id,),
            )

            conn.commit()

        return True, ""
