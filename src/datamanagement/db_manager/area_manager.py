import logging
import sqlite3

logger = logging.getLogger(__name__)


class AreaMixin:

    def get_area_locations(self):
        """Returns all area location monitoring periods."""
        with self.get_connection() as conn:
            query = """
                SELECT m.label AS location,
                       d.label AS device,
                       al.start_dt AS start,
                       al.stop_dt AS stop,
                       al.comment
                FROM area_location al
                JOIN marker m ON al.marker_id = m.id
                LEFT JOIN device d ON al.device_id = d.id
                ORDER BY al.start_dt ASC
            """
            return [dict(row) for row in conn.execute(query).fetchall()]

    def add_area_location(self, location, device_label, start_dt, stop_dt, comment):
        """Adds a new area location monitoring period."""
        if not device_label:
            return False, "Device is mandatory."

        if not start_dt:
            return False, "Start time is mandatory."

        stop_dt = stop_dt if stop_dt else None
        comment = comment if comment else None

        if stop_dt and stop_dt < start_dt:
            return False, "Stop time must be after start time."

        with self.get_connection() as conn:
            marker_id = self.get_marker_id_by_label(location, conn=conn)

            if marker_id is None:
                return False, "Location not found."

            device_id = self.get_or_create_device_id(device_label, "area", conn=conn)

            try:
                conn.execute(
                    """
                    INSERT INTO area_location
                    (start_dt, stop_dt, comment, device_id, marker_id)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (start_dt, stop_dt, comment, device_id, marker_id),
                )
                conn.commit()

            except sqlite3.IntegrityError as e:
                conn.rollback()
                return False, f"Database error: {e}"

        self.sync_marker_ids()
        return True, ""

    def edit_area_location(self, old_data, new_data):
        """Edits an existing area location monitoring period."""
        old_data = old_data or {}
        new_data = new_data or {}

        old_loc = old_data.get("location")
        old_dev = old_data.get("device")
        old_start = old_data.get("start")

        new_loc = new_data.get("location")
        new_dev = new_data.get("device")
        new_start = new_data.get("start")
        new_stop = new_data.get("stop")
        new_comment = new_data.get("comment")

        if not old_start:
            return False, "Original start time is mandatory."

        if not new_start:
            return False, "Start time is mandatory."

        if not new_dev:
            return False, "Device is mandatory."

        new_stop = new_stop if new_stop else None
        new_comment = new_comment if new_comment else None

        if new_stop and new_stop < new_start:
            return False, "Stop time must be after start time."

        with self.get_connection() as conn:
            old_marker_id = self.get_marker_id_by_label(old_loc, conn=conn)

            if old_marker_id is None:
                return False, "Old location not found."

            new_marker_id = self.get_marker_id_by_label(new_loc, conn=conn)

            if new_marker_id is None:
                return False, "New location not found."

            old_device_id = None

            if old_dev:
                old_device_id = self.get_device_id_by_label(old_dev, conn=conn)

                if old_device_id is None:
                    return False, "Old device not found."

            new_device_id = self.get_or_create_device_id(new_dev, "area", conn=conn)

            try:
                if old_device_id is None:
                    cursor = conn.execute(
                        """
                        UPDATE area_location
                        SET start_dt=?, stop_dt=?, comment=?, device_id=?, marker_id=?
                        WHERE marker_id=?
                          AND device_id IS NULL
                          AND start_dt=?
                        """,
                        (
                            new_start,
                            new_stop,
                            new_comment,
                            new_device_id,
                            new_marker_id,
                            old_marker_id,
                            old_start,
                        ),
                    )
                else:
                    cursor = conn.execute(
                        """
                        UPDATE area_location
                        SET start_dt=?, stop_dt=?, comment=?, device_id=?, marker_id=?
                        WHERE marker_id=?
                          AND device_id=?
                          AND start_dt=?
                        """,
                        (
                            new_start,
                            new_stop,
                            new_comment,
                            new_device_id,
                            new_marker_id,
                            old_marker_id,
                            old_device_id,
                            old_start,
                        ),
                    )

                if cursor.rowcount == 0:
                    return False, "Could not find the original area location."

                conn.commit()

            except sqlite3.IntegrityError as e:
                conn.rollback()
                return False, f"Database error: {e}"

        self.sync_marker_ids()
        return True, ""

    def delete_area_location(self, data):
        """Deletes an area location monitoring period."""
        data = data or {}

        location = data.get("location")
        device_label = data.get("device")
        start_dt = data.get("start")

        if not start_dt:
            return False, "Start time is mandatory."

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
                    DELETE FROM area_location
                    WHERE marker_id=?
                      AND device_id IS NULL
                      AND start_dt=?
                    """,
                    (marker_id, start_dt),
                )
            else:
                cursor = conn.execute(
                    """
                    DELETE FROM area_location
                    WHERE marker_id=?
                      AND device_id=?
                      AND start_dt=?
                    """,
                    (marker_id, device_id, start_dt),
                )

            if cursor.rowcount == 0:
                return False, "No matching area location found."

            conn.commit()

        self.sync_marker_ids()
        return True, ""

    # ==========================================
    # AREA INVALIDATIONS
    # ==========================================

    def get_area_invalidations(self):
        """Returns all area invalidation periods."""
        with self.get_connection() as conn:
            query = """
                SELECT d.label AS device,
                       a.label AS analyte,
                       ai.start_dt AS start,
                       ai.stop_dt AS stop,
                       ai.comment
                FROM area_invalidations ai
                LEFT JOIN device d ON ai.device_id = d.id
                JOIN analyte a ON ai.analyte_id = a.id
                ORDER BY ai.start_dt ASC
            """
            rows = conn.execute(query).fetchall()

            validations_dict = {}

            for row in rows:
                key = (
                    row["device"] or "",
                    row["start"],
                    row["stop"] or "",
                    row["comment"] or "",
                )

                if key not in validations_dict:
                    validations_dict[key] = {
                        "device": row["device"] or "",
                        "start": row["start"],
                        "stop": row["stop"] or "",
                        "comment": row["comment"] or "",
                        "analytes": [],
                    }

                validations_dict[key]["analytes"].append(row["analyte"])

            return list(validations_dict.values())

    def add_area_invalidation(
        self,
        device_label,
        start_dt,
        stop_dt,
        comment,
        analyte_labels
    ):
        """Adds a new area invalidation period."""
        if not start_dt:
            return False, "Start time is mandatory."

        analyte_labels = list(analyte_labels or [])

        if not analyte_labels:
            return False, "At least one analyte is required."

        stop_dt = stop_dt if stop_dt else None
        comment = comment if comment else None

        if stop_dt and stop_dt < start_dt:
            return False, "Stop time must be after start time."

        with self.get_connection() as conn:
            device_id = None

            if device_label:
                device_id = self.get_or_create_device_id(device_label, "area", conn=conn)

            for analyte_label in analyte_labels:
                analyte_row = conn.execute(
                    "SELECT id FROM analyte WHERE label = ?",
                    (analyte_label,),
                ).fetchone()

                if not analyte_row:
                    return False, f"Analyte not found: {analyte_label}"

                conn.execute(
                    """
                    INSERT INTO area_invalidations
                    (start_dt, stop_dt, comment, device_id, analyte_id)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (start_dt, stop_dt, comment, device_id, analyte_row["id"]),
                )

            conn.commit()

        self.sync_invalidation_ids()
        return True, ""

    def edit_area_invalidation(self, old_data, new_data):
        """Edits an existing area invalidation period."""
        old_data = old_data or {}
        new_data = new_data or {}

        old_device = old_data.get("device")
        old_start = old_data.get("start")
        old_stop = old_data.get("stop") or None
        old_comment = old_data.get("comment") or None

        new_device = new_data.get("device")
        new_start = new_data.get("start")
        new_stop = new_data.get("stop") or None
        new_comment = new_data.get("comment") or None
        new_analytes = list(new_data.get("analytes", []) or [])

        if not old_start:
            return False, "Original start time is mandatory."

        if not new_start:
            return False, "Start time is mandatory."

        if not new_analytes:
            return False, "At least one analyte is required."

        if new_stop and new_stop < new_start:
            return False, "Stop time must be after start time."

        with self.get_connection() as conn:
            old_device_id = None

            if old_device:
                old_device_id = self.get_device_id_by_label(old_device, conn=conn)

                if old_device_id is None:
                    return False, "Old device not found."

            cursor = conn.execute(
                """
                DELETE FROM area_invalidations
                WHERE device_id IS ?
                  AND start_dt = ?
                  AND stop_dt IS ?
                  AND comment IS ?
                """,
                (old_device_id, old_start, old_stop, old_comment),
            )

            if cursor.rowcount == 0:
                return False, "Could not find the original invalidation period."

            new_device_id = None

            if new_device:
                new_device_id = self.get_or_create_device_id(new_device, "area", conn=conn)

            for analyte_label in new_analytes:
                analyte_row = conn.execute(
                    "SELECT id FROM analyte WHERE label = ?",
                    (analyte_label,),
                ).fetchone()

                if not analyte_row:
                    return False, f"Analyte not found: {analyte_label}"

                conn.execute(
                    """
                    INSERT INTO area_invalidations
                    (start_dt, stop_dt, comment, device_id, analyte_id)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (new_start, new_stop, new_comment, new_device_id, analyte_row["id"]),
                )

            conn.commit()

        self.sync_invalidation_ids()
        return True, ""

    def delete_area_invalidation(self, data):
        """Deletes an area invalidation period."""
        data = data or {}

        device_label = data.get("device")
        start_dt = data.get("start")
        stop_dt = data.get("stop") or None
        comment = data.get("comment") or None

        if not start_dt:
            return False, "Start time is mandatory."

        with self.get_connection() as conn:
            device_id = None

            if device_label:
                device_id = self.get_device_id_by_label(device_label, conn=conn)

                if device_id is None:
                    return False, "Device not found."

            cursor = conn.execute(
                """
                DELETE FROM area_invalidations
                WHERE device_id IS ?
                  AND start_dt = ?
                  AND stop_dt IS ?
                  AND comment IS ?
                """,
                (device_id, start_dt, stop_dt, comment),
            )

            if cursor.rowcount == 0:
                return False, "No matching invalidation period found."

            conn.commit()

        self.sync_invalidation_ids()
        return True, ""
