import logging
import sqlite3

logger = logging.getLogger(__name__)


class SpotReadingsMixin:

    def get_spot_readings(self):
        """Returns all spot readings with location, device, time, and analyte values."""
        with self.get_connection() as conn:
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
                ORDER BY sr.timestamp ASC
            """
            rows = conn.execute(query).fetchall()

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

            return list(readings_dict.values())

    def add_spot_reading(self, reading_data, analyte_lookup):
        """Adds a new spot reading to the database."""
        reading_data = reading_data or {}
        analyte_lookup = analyte_lookup or {}

        location = reading_data.get("location")
        device_label = reading_data.get("device")
        logtime = reading_data.get("logtime")
        observations = reading_data.get("observations")

        if not logtime:
            return False, "Time is mandatory."

        with self.get_connection() as conn:
            marker_id = self.get_marker_id_by_label(location, conn=conn)

            if marker_id is None:
                return False, "Location not found."

            device_id = None

            if device_label:
                device_id = self.get_or_create_device_id(device_label, "spot", conn=conn)

            inserted_count = 0
            invalid_values = []

            try:
                for analyte_label, analyte_id in analyte_lookup.items():
                    val = reading_data.get(analyte_label)

                    if val is None or str(val).strip() == "":
                        continue

                    try:
                        value = float(val)
                    except (TypeError, ValueError):
                        invalid_values.append(analyte_label)
                        continue

                    conn.execute(
                        """
                        INSERT INTO spot_reading
                        (value, timestamp, comment, device_id, analyte_id, marker_id)
                        VALUES (?, ?, ?, ?, ?, ?)
                        """,
                        (value, logtime, observations, device_id, analyte_id, marker_id),
                    )

                    inserted_count += 1

                if invalid_values:
                    conn.rollback()
                    return False, "Invalid numeric value(s): " + ", ".join(invalid_values)

                if inserted_count == 0:
                    conn.rollback()
                    return False, "At least one analyte value is required."

                conn.commit()
                return True, ""

            except sqlite3.IntegrityError:
                conn.rollback()
                return False, "A reading for this location, time, and analyte already exists."

    def edit_spot_reading(self, new_data, old_data, analyte_lookup):
        """Edits an existing spot reading in the database."""
        new_data = new_data or {}
        old_data = old_data or {}
        analyte_lookup = analyte_lookup or {}

        new_loc = new_data.get("location")
        new_dev = new_data.get("device")
        new_time = new_data.get("logtime")
        new_obs = new_data.get("observations")

        old_loc = old_data.get("location")
        old_dev = old_data.get("device")
        old_time = old_data.get("logtime")

        if not new_time:
            return False, "Time is mandatory."

        if not old_time:
            return False, "Original time is mandatory."

        with self.get_connection() as conn:
            new_marker_id = self.get_marker_id_by_label(new_loc, conn=conn)

            if new_marker_id is None:
                return False, "New location not found."

            old_marker_id = self.get_marker_id_by_label(old_loc, conn=conn)

            if old_marker_id is None:
                return False, "Old location not found."

            new_device_id = None

            if new_dev:
                new_device_id = self.get_or_create_device_id(new_dev, "spot", conn=conn)

            old_device_id = None

            if old_dev:
                old_device_id = self.get_device_id_by_label(old_dev, conn=conn)

                if old_device_id is None:
                    return False, "Old device not found."

            new_analytes = {}
            invalid_values = []

            for label, aid in analyte_lookup.items():
                val = new_data.get(label)

                if val is None or str(val).strip() == "":
                    continue

                try:
                    new_analytes[label] = {
                        "id": aid,
                        "value": float(val),
                    }
                except (TypeError, ValueError):
                    invalid_values.append(label)

            if invalid_values:
                return False, "Invalid numeric value(s): " + ", ".join(invalid_values)

            if old_device_id is None:
                old_rows = conn.execute(
                    """
                    SELECT id, analyte_id
                    FROM spot_reading
                    WHERE marker_id = ?
                      AND timestamp = ?
                      AND device_id IS NULL
                    """,
                    (old_marker_id, old_time),
                ).fetchall()
            else:
                old_rows = conn.execute(
                    """
                    SELECT id, analyte_id
                    FROM spot_reading
                    WHERE marker_id = ?
                      AND timestamp = ?
                      AND device_id = ?
                    """,
                    (old_marker_id, old_time, old_device_id),
                ).fetchall()

            if not old_rows:
                return False, "Could not find the original spot reading."

            id_to_label = {v: k for k, v in analyte_lookup.items()}
            handled_ids = set()

            try:
                for row in old_rows:
                    db_label = id_to_label.get(row["analyte_id"])

                    if db_label is None:
                        continue

                    if db_label in new_analytes:
                        conn.execute(
                            """
                            UPDATE spot_reading
                            SET value=?, timestamp=?, comment=?, device_id=?, marker_id=?
                            WHERE id=?
                            """,
                            (
                                new_analytes[db_label]["value"],
                                new_time,
                                new_obs,
                                new_device_id,
                                new_marker_id,
                                row["id"],
                            ),
                        )
                        handled_ids.add(row["analyte_id"])
                    else:
                        conn.execute(
                            "DELETE FROM spot_reading WHERE id = ?",
                            (row["id"],),
                        )

                for label, data in new_analytes.items():
                    if data["id"] not in handled_ids:
                        conn.execute(
                            """
                            INSERT INTO spot_reading
                            (value, timestamp, comment, device_id, analyte_id, marker_id)
                            VALUES (?, ?, ?, ?, ?, ?)
                            """,
                            (
                                data["value"],
                                new_time,
                                new_obs,
                                new_device_id,
                                data["id"],
                                new_marker_id,
                            ),
                        )

                conn.commit()
                return True, ""

            except sqlite3.IntegrityError:
                conn.rollback()
                return False, "The updated reading conflicts with an existing reading."

    def delete_spot_reading(self, reading_data):
        """Deletes a spot reading from the database."""
        reading_data = reading_data or {}

        location = reading_data.get("location")
        device_label = reading_data.get("device")
        logtime = reading_data.get("logtime")

        if not logtime:
            return False, "Time is mandatory."

        with self.get_connection() as conn:
            marker_id = self.get_marker_id_by_label(location, conn=conn)

            if marker_id is None:
                return False, "Location not found."

            device_id = None

            if device_label:
                device_id = self.get_device_id_by_label(device_label, conn=conn)

                if device_id is None:
                    return False, "Device not found."

            if device_id is None:
                cursor = conn.execute(
                    """
                    DELETE FROM spot_reading
                    WHERE marker_id=?
                      AND device_id IS NULL
                      AND timestamp=?
                    """,
                    (marker_id, logtime),
                )
            else:
                cursor = conn.execute(
                    """
                    DELETE FROM spot_reading
                    WHERE marker_id=?
                      AND device_id=?
                      AND timestamp=?
                    """,
                    (marker_id, device_id, logtime),
                )

            if cursor.rowcount == 0:
                return False, "No matching spot reading found."

            conn.commit()
            return True, ""
