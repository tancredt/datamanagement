import os
import shutil
import logging

logger = logging.getLogger(__name__)

class ThresholdsMixin:
    def get_all_thresholds(self):
        """Returns all analyte thresholds."""
        with self.get_connection() as conn:
            rows = conn.execute("""
                SELECT label, hotzone_threshold, warmzone_threshold, 
                       fireground_threshold, community_threshold 
                FROM analyte 
                ORDER BY label
            """).fetchall()
            return [dict(row) for row in rows]

    def update_thresholds(self, thresholds_list):
        """Updates or inserts analyte thresholds."""
        with self.get_connection() as conn:
            for t in thresholds_list:
                label = t.get('label', '').strip()
                if not label:
                    continue
                
                hotzone = float(t.get('hotzone', 0.0))
                warmzone = float(t.get('warmzone', 0.0))
                fireground = float(t.get('fireground', 0.0))
                community = float(t.get('community', 0.0))
                
                exists = conn.execute(
                    "SELECT 1 FROM analyte WHERE label = ?", 
                    (label,)
                ).fetchone()
                
                if not exists:
                    conn.execute("""
                        INSERT INTO analyte 
                        (label, dec_pls, hotzone_threshold, warmzone_threshold, 
                         fireground_threshold, community_threshold)
                        VALUES (?, 2, ?, ?, ?, ?)
                    """, (label, hotzone, warmzone, fireground, community))
                else:
                    conn.execute("""
                        UPDATE analyte 
                        SET hotzone_threshold=?, warmzone_threshold=?, 
                            fireground_threshold=?, community_threshold=?
                        WHERE label=?
                    """, (hotzone, warmzone, fireground, community, label))
            conn.commit()

    def get_last_area_readings(self):
        """Returns the most recent reading timestamp for each area device."""
        with self.get_connection() as conn:
            rows = conn.execute("""
                SELECT d.label AS device, MAX(ar.timestamp) AS last_reading
                FROM area_reading ar
                LEFT JOIN device d ON ar.device_id = d.id
                GROUP BY ar.device_id
                ORDER BY last_reading DESC
            """).fetchall()
            return [dict(row) for row in rows]
