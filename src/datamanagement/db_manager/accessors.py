import os
import logging

logger = logging.getLogger(__name__)

class AccessorsMixin:
    def get_analytes(self):
        """Returns list of dicts: {id, label, dec_pls} for all analytes."""
        with self.get_connection() as conn:
            query = "SELECT id, label, responder_name, dec_pls FROM analyte ORDER BY label"
            rows = conn.execute(query).fetchall()
            return [dict(row) for row in rows]

    def get_devices(self, data_type):
        """
        Returns list of device labels filtered by data_type.
        
        - spot: device_type = 'spot'
        - area: device_type = 'area' (ONLY those with data in area_reading)
        - spectral: device_type = 'spectral'
        - personal: device_type = 'personal'
        - exposure: device_type IN ('spot', 'personal')
        """
        with self.get_connection() as conn:
            if data_type == "exposure":
                query = """
                    SELECT DISTINCT label FROM device 
                    WHERE device_type IN ('spot', 'personal') 
                    ORDER BY label
                """
                rows = conn.execute(query).fetchall()
            elif data_type == "area":
                # Uses DISTINCT and JOIN to only return area devices with actual data
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
                    SELECT DISTINCT label FROM device 
                    WHERE device_type = ? 
                    ORDER BY label
                """
                rows = conn.execute(query, (data_type,)).fetchall()
            else:
                return []
            return [row['label'] for row in rows]

    def get_data_time_range(self, data_type):
        """Returns the minimum and maximum timestamps for a data type."""
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

