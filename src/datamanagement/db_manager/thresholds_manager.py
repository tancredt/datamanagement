import logging

logger = logging.getLogger(__name__)


class ThresholdsMixin:

    @staticmethod
    def _safe_float(value, default=0.0):
        """Convert a value to float where possible."""
        if value is None:
            return default

        try:
            return float(value)
        except (TypeError, ValueError):
            return default

    def get_all_thresholds(self):
        """Returns all analyte thresholds."""
        with self.get_connection() as conn:
            rows = conn.execute(
                """
                SELECT label,
                       hotzone_threshold,
                       warmzone_threshold,
                       fireground_threshold,
                       community_threshold
                FROM analyte
                ORDER BY label
                """
            ).fetchall()

            return [dict(row) for row in rows]

    def update_thresholds(self, thresholds_list):
        """Updates or inserts analyte thresholds."""
        thresholds_list = thresholds_list or []

        with self.get_connection() as conn:
            for t in thresholds_list:
                label = str(t.get("label", "")).strip()

                if not label:
                    continue

                hotzone = self._safe_float(t.get("hotzone"), 0.0)
                warmzone = self._safe_float(t.get("warmzone"), 0.0)
                fireground = self._safe_float(t.get("fireground"), 0.0)
                community = self._safe_float(t.get("community"), 0.0)

                exists = conn.execute(
                    "SELECT 1 FROM analyte WHERE label = ?",
                    (label,),
                ).fetchone()

                if not exists:
                    conn.execute(
                        """
                        INSERT INTO analyte
                        (label, dec_pls, hotzone_threshold, warmzone_threshold,
                         fireground_threshold, community_threshold)
                        VALUES (?, 2, ?, ?, ?, ?)
                        """,
                        (label, hotzone, warmzone, fireground, community),
                    )
                else:
                    conn.execute(
                        """
                        UPDATE analyte
                        SET hotzone_threshold=?,
                            warmzone_threshold=?,
                            fireground_threshold=?,
                            community_threshold=?
                        WHERE label=?
                        """,
                        (hotzone, warmzone, fireground, community, label),
                    )

            conn.commit()

        return True, ""

    def get_last_area_readings(self):
        """Returns the most recent reading timestamp for each area device."""
        with self.get_connection() as conn:
            rows = conn.execute(
                """
                SELECT d.label AS device,
                       MAX(ar.timestamp) AS last_reading
                FROM area_reading ar
                LEFT JOIN device d ON ar.device_id = d.id
                GROUP BY ar.device_id
                ORDER BY last_reading DESC
                """
            ).fetchall()

            return [dict(row) for row in rows]
