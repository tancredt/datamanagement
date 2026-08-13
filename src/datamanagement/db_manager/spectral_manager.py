import logging
import sqlite3

logger = logging.getLogger(__name__)


class SpectralMixin:

    def get_spectral_results(self):
        """Returns all spectral analysis results."""
        with self.get_connection() as conn:
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
                ORDER BY sr.timestamp ASC
            """
            return [dict(row) for row in conn.execute(query).fetchall()]

    def add_spectral_result(
        self,
        location,
        device_label,
        logtime,
        chemicals,
        comments,
        file_ref
    ):
        """Adds a new spectral analysis result."""
        if not logtime:
            return False, "Time is mandatory."

        if not device_label:
            return False, "Device is mandatory for spectral results."

        with self.get_connection() as conn:
            marker_id = self.get_marker_id_by_label(location, conn=conn)

            if marker_id is None:
                return False, "Location not found."

            device_id = self.get_or_create_device_id(device_label, "spectral", conn=conn)

            try:
                conn.execute(
                    """
                    INSERT INTO spectral_result
                    (chemicals, timestamp, comment, file_ref, device_id, marker_id)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (chemicals, logtime, comments, file_ref, device_id, marker_id),
                )
                conn.commit()
                return True, ""

            except sqlite3.IntegrityError as e:
                conn.rollback()
                return False, f"Database error: {e}"

    def edit_spectral_result(self, old_data, new_data):
        """Edits an existing spectral analysis result."""
        old_data = old_data or {}
        new_data = new_data or {}

        old_loc = old_data.get("location")
        old_dev = old_data.get("device")
        old_time = old_data.get("logtime")

        new_loc = new_data.get("location")
        new_dev = new_data.get("device")
        new_time = new_data.get("logtime")
        new_chem = new_data.get("chemicals_identified")
        new_comm = new_data.get("comments")
        new_ref = new_data.get("file_ref")

        if not old_time:
            return False, "Original time is mandatory."

        if not new_time:
            return False, "Time is mandatory."

        if not new_dev:
            return False, "Device is mandatory for spectral results."

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

            new_device_id = self.get_or_create_device_id(new_dev, "spectral", conn=conn)

            try:
                if old_device_id is None:
                    cursor = conn.execute(
                        """
                        UPDATE spectral_result
                        SET chemicals=?, timestamp=?, comment=?, file_ref=?,
                            device_id=?, marker_id=?
                        WHERE marker_id=?
                          AND device_id IS NULL
                          AND timestamp=?
                        """,
                        (
                            new_chem,
                            new_time,
                            new_comm,
                            new_ref,
                            new_device_id,
                            new_marker_id,
                            old_marker_id,
                            old_time,
                        ),
                    )
                else:
                    cursor = conn.execute(
                        """
                        UPDATE spectral_result
                        SET chemicals=?, timestamp=?, comment=?, file_ref=?,
                            device_id=?, marker_id=?
                        WHERE marker_id=?
                          AND device_id=?
                          AND timestamp=?
                        """,
                        (
                            new_chem,
                            new_time,
                            new_comm,
                            new_ref,
                            new_device_id,
                            new_marker_id,
                            old_marker_id,
                            old_device_id,
                            old_time,
                        ),
                    )

                if cursor.rowcount == 0:
                    return False, "Could not find the original spectral result."

                conn.commit()
                return True, ""

            except sqlite3.IntegrityError as e:
                conn.rollback()
                return False, f"Database error: {e}"

    def delete_spectral_result(self, data):
        """Deletes a spectral analysis result."""
        data = data or {}

        location = data.get("location")
        device_label = data.get("device")
        logtime = data.get("logtime")

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
                    DELETE FROM spectral_result
                    WHERE marker_id=?
                      AND device_id IS NULL
                      AND timestamp=?
                    """,
                    (marker_id, logtime),
                )
            else:
                cursor = conn.execute(
                    """
                    DELETE FROM spectral_result
                    WHERE marker_id=?
                      AND device_id=?
                      AND timestamp=?
                    """,
                    (marker_id, device_id, logtime),
                )

            if cursor.rowcount == 0:
                return False, "No matching spectral result found."

            conn.commit()
            return True, ""
