import os
import shutil
import logging

logger = logging.getLogger(__name__)

class SpotReadingsMixin:
    def get_spot_readings(self):
        """Returns all spot readings with location, device, time, and analyte values."""
        
        with self.get_connection() as conn:
            query = """
                SELECT m.label AS location, d.label AS device, sr.timestamp AS logtime, 
                       sr.comment AS observations, a.label AS analyte, sr.value
                FROM spot_reading sr
                JOIN marker m ON sr.marker_id = m.id
                LEFT JOIN device d ON sr.device_id = d.id
                JOIN analyte a ON sr.analyte_id = a.id
                ORDER BY sr.timestamp DESC
            """
            rows = conn.execute(query).fetchall()
            
            readings_dict = {}
            for row in rows:
                key = (row['location'], row['device'] or "", row['logtime'])
                if key not in readings_dict:
                    readings_dict[key] = {
                        "location": row['location'],
                        "device": row['device'] or "",
                        "logtime": row['logtime'],
                        "observations": row['observations'] or ""
                    }
                readings_dict[key][row['analyte']] = row['value']
            
            return list(readings_dict.values())

    def add_spot_reading(self, reading_data, analyte_lookup):
        """Adds a new spot reading to the database."""
        location = reading_data.get("location")
        device_label = reading_data.get("device")
        logtime = reading_data.get("logtime")
        observations = reading_data.get("observations")
        
        with self.get_connection() as conn:
            marker_id = conn.execute(
                "SELECT id FROM marker WHERE label = ?", 
                (location,)
            ).fetchone()['id']
            
            device_id = None
            if device_label:
                dev_row = conn.execute(
                    "SELECT id FROM device WHERE label = ?", 
                    (device_label,)
                ).fetchone()
                if dev_row:
                    device_id = dev_row['id']
                else:
                    device_id = conn.execute(
                        "INSERT INTO device (label, device_type) VALUES (?, ?)", 
                        (device_label, "spot")
                    ).lastrowid
            
            try:
                for analyte_label, analyte_id in analyte_lookup.items():
                    val = reading_data.get(analyte_label)
                    if val is not None and str(val).strip() != "":
                        conn.execute("""
                            INSERT INTO spot_reading 
                            (value, timestamp, comment, device_id, analyte_id, marker_id)
                            VALUES (?, ?, ?, ?, ?, ?)
                        """, (float(val), logtime, observations, device_id, 
                              analyte_id, marker_id))
                conn.commit()
                return True, ""
            except sqlite3.IntegrityError:
                conn.rollback()
                return False, "A reading for this location, time, and analyte already exists."

    def edit_spot_reading(self, new_data, old_data, analyte_lookup):
        """Edits an existing spot reading in the database."""
        new_loc = new_data.get("location")
        new_dev = new_data.get("device")
        new_time = new_data.get("logtime")
        new_obs = new_data.get("observations")
        
        old_loc = old_data.get("location")
        old_time = old_data.get("logtime")
        
        with self.get_connection() as conn:
            new_marker_id = conn.execute(
                "SELECT id FROM marker WHERE label = ?", 
                (new_loc,)
            ).fetchone()['id']
            old_marker_id = conn.execute(
                "SELECT id FROM marker WHERE label = ?", 
                (old_loc,)
            ).fetchone()['id']
            
            new_device_id = None
            if new_dev:
                dev_row = conn.execute(
                    "SELECT id FROM device WHERE label = ?", 
                    (new_dev,)
                ).fetchone()
                if dev_row:
                    new_device_id = dev_row['id']
                else:
                    new_device_id = conn.execute(
                        "INSERT INTO device (label, device_type) VALUES (?, ?)", 
                        (new_dev, "spot")
                    ).lastrowid
            
            new_analytes = {}
            for label, aid in analyte_lookup.items():
                val = new_data.get(label)
                if val is not None and str(val).strip() != "":
                    try:
                        new_analytes[label] = {"id": aid, "value": float(val)}
                    except ValueError:
                        pass
            
            old_rows = conn.execute(
                "SELECT id, analyte_id FROM spot_reading WHERE marker_id = ? AND timestamp = ?", 
                (old_marker_id, old_time)
            ).fetchall()
            
            id_to_label = {v: k for k, v in analyte_lookup.items()}
            handled_ids = set()
            
            try:
                for row in old_rows:
                    db_label = id_to_label.get(row['analyte_id'])
                    if db_label is None:
                        continue
                    
                    if db_label in new_analytes:
                        conn.execute("""
                            UPDATE spot_reading 
                            SET value=?, timestamp=?, comment=?, device_id=?, marker_id=? 
                            WHERE id=?
                        """, (new_analytes[db_label]["value"], new_time, new_obs, 
                              new_device_id, new_marker_id, row['id']))
                        handled_ids.add(row['analyte_id'])
                    else:
                        conn.execute(
                            "DELETE FROM spot_reading WHERE id = ?", 
                            (row['id'],)
                        )
                
                for label, data in new_analytes.items():
                    if data["id"] not in handled_ids:
                        conn.execute("""
                            INSERT INTO spot_reading 
                            (value, timestamp, comment, device_id, analyte_id, marker_id) 
                            VALUES (?, ?, ?, ?, ?, ?)
                        """, (data["value"], new_time, new_obs, new_device_id, 
                              data["id"], new_marker_id))
                
                conn.commit()
                return True, ""
            except sqlite3.IntegrityError:
                conn.rollback()
                return False, "The updated reading conflicts with an existing reading."

    def delete_spot_reading(self, reading_data):
        """Deletes a spot reading from the database."""
        location = reading_data.get("location")
        device_label = reading_data.get("device")
        logtime = reading_data.get("logtime")
        
        with self.get_connection() as conn:
            marker_id = conn.execute(
                "SELECT id FROM marker WHERE label = ?", 
                (location,)
            ).fetchone()['id']
            
            device_id = None
            if device_label:
                dev_row = conn.execute(
                    "SELECT id FROM device WHERE label = ?", 
                    (device_label,)
                ).fetchone()
                if dev_row:
                    device_id = dev_row['id']
            
            if device_id:
                conn.execute(
                    "DELETE FROM spot_reading WHERE marker_id=? AND device_id=? AND timestamp=?", 
                    (marker_id, device_id, logtime)
                )
            else:
                conn.execute(
                    "DELETE FROM spot_reading WHERE marker_id=? AND device_id IS NULL AND timestamp=?", 
                    (marker_id, logtime)
                )
            conn.commit()

