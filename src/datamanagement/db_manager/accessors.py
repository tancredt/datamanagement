import logging

logger = logging.getLogger(__name__)


class AccessorsMixin:
    """
    Mixin providing common database accessor methods.

    This class expects self.get_connection() to be provided by the
    DatabaseConnection base class.
    """

    # ─────────────────────────────────────────────────────────
    # INTERNAL HELPERS
    # ─────────────────────────────────────────────────────────
    def _get_device_id_by_label(self, conn, label):
        """Internal helper to get a device ID using an existing connection."""
        row = conn.execute(
            "SELECT id FROM device WHERE label = ?",
            (label,)
        ).fetchone()

        return row["id"] if row else None

    def _get_marker_id_by_label(self, conn, label):
        """Internal helper to get a marker ID using an existing connection."""
        row = conn.execute(
            "SELECT id FROM marker WHERE label = ?",
            (label,)
        ).fetchone()

        return row["id"] if row else None

    def _get_or_create_device_id(self, conn, label, device_type):
        """
        Internal helper to get or create a device ID using an existing connection.

        This does NOT commit. The caller owns the transaction.
        """
        row = conn.execute(
            "SELECT id FROM device WHERE label = ?",
            (label,)
        ).fetchone()

        if row:
            return row["id"]

        row_id = conn.execute(
            "INSERT INTO device (label, device_type) VALUES (?, ?)",
            (label, device_type)
        ).lastrowid

        return row_id

    # ─────────────────────────────────────────────────────────
    # ANALYTES
    # ─────────────────────────────────────────────────────────
    def get_analytes(self):
        """
        Returns list of dicts for all analytes.

        Each dict contains:
            id
            label
            responder_name
            dec_pls
        """
        with self.get_connection() as conn:
            query = """
                SELECT id, label, responder_name, dec_pls
                FROM analyte
                ORDER BY label
            """
            rows = conn.execute(query).fetchall()
            return [dict(row) for row in rows]

    # ─────────────────────────────────────────────────────────
    # DEVICES
    # ─────────────────────────────────────────────────────────
    def get_device_id_by_label(self, label, conn=None):
        """
        Returns the device ID for a given device label.

        Args:
            label: The device label string.
            conn: Optional existing SQLite connection.

        Returns:
            int: The device ID if found, None otherwise.
        """
        if not label:
            return None

        if conn is not None:
            return self._get_device_id_by_label(conn, label)

        with self.get_connection() as new_conn:
            return self._get_device_id_by_label(new_conn, label)

    def get_or_create_device_id(self, label, device_type, conn=None):
        """
        Returns the device ID for a given device label, creating it if needed.

        Args:
            label: The device label string.
            device_type: The device type to use when creating the device.
            conn: Optional existing SQLite connection.

        If conn is provided, this method participates in the caller's
        transaction and does not commit independently.

        Returns:
            int: The device ID.
        """
        if not label:
            return None

        if conn is not None:
            return self._get_or_create_device_id(conn, label, device_type)

        with self.get_connection() as new_conn:
            device_id = self._get_or_create_device_id(
                new_conn,
                label,
                device_type
            )
            new_conn.commit()
            return device_id

    def get_devices(self, data_type):
        """
        Returns list of device labels filtered by data_type.

        Supported data_type values:
            spot
            area
            spectral
            personal
            exposure

        Notes:
            - area returns only devices that have data in area_reading
            - exposure returns spot and personal devices
        """
        with self.get_connection() as conn:
            if data_type == "exposure":
                query = """
                    SELECT DISTINCT label
                    FROM device
                    WHERE device_type IN ('spot', 'personal')
                    ORDER BY label
                """
                rows = conn.execute(query).fetchall()

            elif data_type == "area":
                query = """
                    SELECT DISTINCT d.label
                    FROM device d
                    JOIN area_reading ar ON d.id = ar.device_id
                    WHERE d.device_type = 'area'
                    ORDER BY d.label
                """
                rows = conn.execute(query).fetchall()

            elif data_type in ["spot", "spectral", "personal"]:
                query = """
                    SELECT DISTINCT label
                    FROM device
                    WHERE device_type = ?
                    ORDER BY label
                """
                rows = conn.execute(query, (data_type,)).fetchall()

            else:
                return []

            return [row["label"] for row in rows]

    # ─────────────────────────────────────────────────────────
    # MARKERS / SITES
    # ─────────────────────────────────────────────────────────
    def get_marker_id_by_label(self, label, conn=None):
        """
        Returns the marker ID for a given marker label.

        Args:
            label: The marker label string.
            conn: Optional existing SQLite connection.

        Returns:
            int: The marker ID if found, None otherwise.
        """
        if not label:
            return None

        if conn is not None:
            return self._get_marker_id_by_label(conn, label)

        with self.get_connection() as new_conn:
            return self._get_marker_id_by_label(new_conn, label)

    def get_markers(self):
        """
        Returns list of marker labels.

        This is useful for site/location filter dialogs.
        """
        with self.get_connection() as conn:
            query = """
                SELECT label
                FROM marker
                WHERE label IS NOT NULL
                  AND label != ''
                ORDER BY label
            """
            rows = conn.execute(query).fetchall()
            return [row["label"] for row in rows]

    # ─────────────────────────────────────────────────────────
    # TIME RANGE
    # ─────────────────────────────────────────────────────────
    def get_data_time_range(self, data_type):
        """
        Returns the minimum and maximum timestamps for a data type.

        Args:
            data_type: One of area, spot, spectral, exposure.

        Returns:
            tuple: (min_timestamp, max_timestamp)
        """
        with self.get_connection() as conn:
            if data_type == "area":
                row = conn.execute(
                    "SELECT MIN(timestamp), MAX(timestamp) FROM area_reading"
                ).fetchone()

            elif data_type == "spot":
                row = conn.execute(
                    "SELECT MIN(timestamp), MAX(timestamp) FROM spot_reading"
                ).fetchone()

            elif data_type == "exposure":
                row = conn.execute(
                    "SELECT MIN(start_dt), MAX(start_dt) FROM exposure"
                ).fetchone()

            elif data_type == "spectral":
                row = conn.execute(
                    "SELECT MIN(timestamp), MAX(timestamp) FROM spectral_result"
                ).fetchone()

            else:
                return None, None

            if row and row[0] and row[1]:
                return row[0], row[1]

        return None, None
