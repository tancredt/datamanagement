import os
import logging
import sqlite3

logger = logging.getLogger(__name__)

class SpectralMixin:
    def get_spectral_results(self):
        """Returns all spectral analysis results."""
        with self.get_connection() as conn:
            query = """
                SELECT m.label AS location, d.label AS device, sr.timestamp AS logtime,
                       sr.chemicals AS chemicals_identified, sr.comment AS comments, 
                       sr.file_ref
                FROM spectral_result sr
                JOIN marker m ON sr.marker_id = m.id
                LEFT JOIN device d ON sr.device_id = d.id
                ORDER BY sr.timestamp ASC
            """
            return [dict(row) for row in conn.execute(query).fetchall()]

    def add_spectral_result(self, location, device_label, logtime, chemicals, comments, file_ref):
        """Adds a new spectral analysis result."""
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
                        (device_label, "spectral")
                    ).lastrowid
            else:
                return False, "Device is mandatory for spectral results."
            
            try:
                conn.execute("""
                    INSERT INTO spectral_result 
                    (chemicals, timestamp, comment, file_ref, device_id, marker_id) 
                    VALUES (?, ?, ?, ?, ?, ?)
                """, (chemicals, logtime, comments, file_ref, device_id, marker_id))
                conn.commit()
                return True, ""
            except sqlite3.IntegrityError as e:
                return False, f"Database error: {e}"

    def edit_spectral_result(self, old_data, new_data):
        """Edits an existing spectral analysis result."""
        old_loc = old_data.get("location")
        old_dev = old_data.get("device")
        old_time = old_data.get("logtime")
        
        new_loc = new_data.get("location")
        new_dev = new_data.get("device")
        new_time = new_data.get("logtime")
        new_chem = new_data.get("chemicals_identified")
        new_comm = new_data.get("comments")
        new_ref = new_data.get("file_ref")
        
        with self.get_connection() as conn:
            old_marker_id = conn.execute(
                "SELECT id FROM marker WHERE label = ?", 
                (old_loc,)
            ).fetchone()['id']
            new_marker_id = conn.execute(
                "SELECT id FROM marker WHERE label = ?", 
                (new_loc,)
            ).fetchone()['id']
            
            old_device_id = None
            if old_dev:
                row = conn.execute(
                    "SELECT id FROM device WHERE label = ?", 
                    (old_dev,)
                ).fetchone()
                if row:
                    old_device_id = row['id']
            
            new_device_id = None
            if new_dev:
                row = conn.execute(
                    "SELECT id FROM device WHERE label = ?", 
                    (new_dev,)
                ).fetchone()
                if row:
                    new_device_id = row['id']
                else:
                    new_device_id = conn.execute(
                        "INSERT INTO device (label, device_type) VALUES (?, ?)", 
                        (new_dev, "spectral")
                    ).lastrowid
            else:
                return False, "Device is mandatory for spectral results."
            
            try:
                if old_device_id:
                    conn.execute("""
                        UPDATE spectral_result 
                        SET chemicals=?, timestamp=?, comment=?, file_ref=?, 
                            device_id=?, marker_id=? 
                        WHERE marker_id=? AND device_id=? AND timestamp=?
                    """, (new_chem, new_time, new_comm, new_ref, new_device_id, 
                          new_marker_id, old_marker_id, old_device_id, old_time))
                else:
                    conn.execute("""
                        UPDATE spectral_result 
                        SET chemicals=?, timestamp=?, comment=?, file_ref=?, 
                            device_id=?, marker_id=? 
                        WHERE marker_id=? AND device_id IS NULL AND timestamp=?
                    """, (new_chem, new_time, new_comm, new_ref, new_device_id, 
                          new_marker_id, old_marker_id, old_time))
                
                conn.commit()
                return True, ""
            except sqlite3.IntegrityError as e:
                return False, f"Database error: {e}"

    def delete_spectral_result(self, data):
        """Deletes a spectral analysis result."""
        location = data.get("location")
        device_label = data.get("device")
        logtime = data.get("logtime")
        
        with self.get_connection() as conn:
            marker_id = conn.execute(
                "SELECT id FROM marker WHERE label = ?", 
                (location,)
            ).fetchone()['id']
            
            device_id = None
            if device_label:
                row = conn.execute(
                    "SELECT id FROM device WHERE label = ?", 
                    (device_label,)
                ).fetchone()
                if row:
                    device_id = row['id']
            
            if device_id:
                conn.execute(
                    "DELETE FROM spectral_result WHERE marker_id=? AND device_id=? AND timestamp=?", 
                    (marker_id, device_id, logtime)
                )
            else:
                conn.execute(
                    "DELETE FROM spectral_result WHERE marker_id=? AND device_id IS NULL AND timestamp=?", 
                    (marker_id, logtime)
                )
            conn.commit()
