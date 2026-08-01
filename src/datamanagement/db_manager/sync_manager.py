import os
import logging

logger = logging.getLogger(__name__)

class SyncMixin:
    def sync_marker_ids(self):
        """
        Updates marker_id in area_reading based on area_location.
        
        Uses COALESCE to treat NULL stop_dt as the far future ('9999-12-31').
        """
        with self.get_connection() as conn:
            conn.execute("""
                UPDATE area_reading
                SET marker_id = (
                    SELECT al.marker_id 
                    FROM area_location al 
                    WHERE al.device_id = area_reading.device_id 
                      AND area_reading.timestamp > al.start_dt 
                      AND area_reading.timestamp <= COALESCE(al.stop_dt, '9999-12-31 23:59:59')
                    ORDER BY al.id DESC
                    LIMIT 1
                )
            """)
            conn.commit()

    def sync_invalidation_ids(self):
        """
        Updates invalidation_id in area_reading_analyte based on area_invalidations.
        
        Uses COALESCE to treat NULL stop_dt as the far future ('9999-12-31').
        """
        with self.get_connection() as conn:
            conn.execute("""
                UPDATE area_reading_analyte
                SET invalidation_id = (
                    SELECT ai.id
                    FROM area_invalidations ai
                    JOIN area_reading ar ON ar.id = area_reading_analyte.area_reading_id
                    WHERE ai.device_id = ar.device_id
                      AND ai.analyte_id = area_reading_analyte.analyte_id
                      AND ar.timestamp > ai.start_dt
                      AND ar.timestamp <= COALESCE(ai.stop_dt, '9999-12-31 23:59:59')
                    ORDER BY ai.id DESC
                    LIMIT 1
                )
            """)
            conn.commit()
