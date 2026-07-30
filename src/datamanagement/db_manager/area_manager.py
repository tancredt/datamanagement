import os
import shutil
import logging

logger = logging.getLogger(__name__)

class AreaMixin:
    def get_area_locations(self):
        """Returns all area location monitoring periods."""
        with self.get_connection() as conn:
            query = """
                SELECT m.label AS location, d.label AS device, al.start_dt AS start, 
                       al.stop_dt AS stop, al.comment
                FROM area_location al
                JOIN marker m ON al.marker_id = m.id
                LEFT JOIN device d ON al.device_id = d.id
                ORDER BY al.start_dt DESC
            """
            return [dict(row) for row in conn.execute(query).fetchall()]

    def add_area_location(self, location, device_label, start_dt, stop_dt, comment):
        """Adds a new area location monitoring period."""
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
                        (device_label, "area")
                    ).lastrowid
            
            # Convert empty strings to None so SQLite stores NULL
            stop_dt = stop_dt if stop_dt else None
            comment = comment if comment else None
            
            try:
                conn.execute("""
                    INSERT INTO area_location 
                    (start_dt, stop_dt, comment, device_id, marker_id) 
                    VALUES (?, ?, ?, ?, ?)
                """, (start_dt, stop_dt, comment, device_id, marker_id))
                conn.commit()
                self.sync_marker_ids()
                return True, ""
            except sqlite3.IntegrityError as e:
                return False, f"Database error: {e}"

    def edit_area_location(self, old_data, new_data):
        """Edits an existing area location monitoring period."""
        old_loc = old_data.get("location")
        old_dev = old_data.get("device")
        old_start = old_data.get("start")
        
        new_loc = new_data.get("location")
        new_dev = new_data.get("device")
        new_start = new_data.get("start")
        new_stop = new_data.get("stop")
        new_comment = new_data.get("comment")
        
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
                        (new_dev, "area")
                    ).lastrowid
            
            # Convert empty strings to None so SQLite stores NULL
            new_stop = new_stop if new_stop else None
            new_comment = new_comment if new_comment else None
            
            try:
                if old_device_id:
                    conn.execute("""
                        UPDATE area_location 
                        SET start_dt=?, stop_dt=?, comment=?, device_id=?, marker_id=? 
                        WHERE marker_id=? AND device_id=? AND start_dt=?
                    """, (new_start, new_stop, new_comment, new_device_id, 
                          new_marker_id, old_marker_id, old_device_id, old_start))
                else:
                    conn.execute("""
                        UPDATE area_location 
                        SET start_dt=?, stop_dt=?, comment=?, device_id=?, marker_id=? 
                        WHERE marker_id=? AND device_id IS NULL AND start_dt=?
                    """, (new_start, new_stop, new_comment, new_device_id, 
                          new_marker_id, old_marker_id, old_start))
                
                conn.commit()
                self.sync_marker_ids()
                return True, ""
            except sqlite3.IntegrityError as e:
                return False, f"Database error: {e}"

    def delete_area_location(self, data):
        """Deletes an area location monitoring period."""
        location = data.get("location")
        device_label = data.get("device")
        start_dt = data.get("start")
        
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
                    "DELETE FROM area_location WHERE marker_id=? AND device_id=? AND start_dt=?", 
                    (marker_id, device_id, start_dt)
                )
            else:
                conn.execute(
                    "DELETE FROM area_location WHERE marker_id=? AND device_id IS NULL AND start_dt=?", 
                    (marker_id, start_dt)
                )
            conn.commit()
            self.sync_marker_ids()

    # ==========================================
    # AREA INVALIDATIONS
    # ==========================================
    def get_area_invalidations(self):
        """Returns all area invalidation periods."""
        with self.get_connection() as conn:
            query = """
                SELECT d.label AS device, a.label AS analyte, ai.start_dt AS start, 
                       ai.stop_dt AS stop, ai.comment
                FROM area_invalidations ai
                LEFT JOIN device d ON ai.device_id = d.id
                JOIN analyte a ON ai.analyte_id = a.id
                ORDER BY ai.start_dt DESC
            """
            rows = conn.execute(query).fetchall()
            
            validations_dict = {}
            for row in rows:
                key = (row['device'] or "", row['start'], row['stop'] or "", 
                       row['comment'] or "")
                if key not in validations_dict:
                    validations_dict[key] = {
                        "device": row['device'] or "",
                        "start": row['start'],
                        "stop": row['stop'] or "",
                        "comment": row['comment'] or "",
                        "analytes": []
                    }
                validations_dict[key]["analytes"].append(row['analyte'])
            
            return list(validations_dict.values())

    def add_area_invalidation(self, device_label, start_dt, stop_dt, comment, analyte_labels):
        """Adds a new area invalidation period."""
        with self.get_connection() as conn:
            device_id = None
            if device_label:
                row = conn.execute(
                    "SELECT id FROM device WHERE label = ?", 
                    (device_label,)
                ).fetchone()
                if row:
                    device_id = row['id']
                else:
                    device_id = conn.execute(
                        "INSERT INTO device (label, device_type) VALUES (?, ?)", 
                        (device_label, "area")
                    ).lastrowid
            
            # Convert empty strings to None so SQLite stores NULL
            stop_dt = stop_dt if stop_dt else None
            comment = comment if comment else None
            
            for analyte_label in analyte_labels:
                analyte_row = conn.execute(
                    "SELECT id FROM analyte WHERE label = ?", 
                    (analyte_label,)
                ).fetchone()
                if analyte_row:
                    conn.execute("""
                        INSERT INTO area_invalidations 
                        (start_dt, stop_dt, comment, device_id, analyte_id) 
                        VALUES (?, ?, ?, ?, ?)
                    """, (start_dt, stop_dt, comment, device_id, analyte_row['id']))
            
            conn.commit()
            self.sync_invalidation_ids()

    def edit_area_invalidation(self, old_data, new_data):
        """Edits an existing area invalidation period."""
        old_device = old_data.get("device")
        old_start = old_data.get("start")
        
        new_device = new_data.get("device")
        new_start = new_data.get("start")
        new_stop = new_data.get("stop")
        new_comment = new_data.get("comment")
        new_analytes = new_data.get("analytes", [])
        
        with self.get_connection() as conn:
            old_device_id = None
            if old_device:
                row = conn.execute(
                    "SELECT id FROM device WHERE label = ?", 
                    (old_device,)
                ).fetchone()
                if row:
                    old_device_id = row['id']
            
            if old_device_id:
                conn.execute(
                    "DELETE FROM area_invalidations WHERE device_id = ? AND start_dt = ?", 
                    (old_device_id, old_start)
                )
            else:
                conn.execute(
                    "DELETE FROM area_invalidations WHERE device_id IS NULL AND start_dt = ?", 
                    (old_start,)
                )
            
            new_device_id = None
            if new_device:
                row = conn.execute(
                    "SELECT id FROM device WHERE label = ?", 
                    (new_device,)
                ).fetchone()
                if row:
                    new_device_id = row['id']
                else:
                    new_device_id = conn.execute(
                        "INSERT INTO device (label, device_type) VALUES (?, ?)", 
                        (new_device, "area")
                    ).lastrowid
            
            # Convert empty strings to None so SQLite stores NULL
            new_stop = new_stop if new_stop else None
            new_comment = new_comment if new_comment else None
            
            for analyte_label in new_analytes:
                analyte_row = conn.execute(
                    "SELECT id FROM analyte WHERE label = ?", 
                    (analyte_label,)
                ).fetchone()
                if analyte_row:
                    conn.execute("""
                        INSERT INTO area_invalidations 
                        (start_dt, stop_dt, comment, device_id, analyte_id) 
                        VALUES (?, ?, ?, ?, ?)
                    """, (new_start, new_stop, new_comment, new_device_id, 
                          analyte_row['id']))
            
            conn.commit()
            self.sync_invalidation_ids()

    def delete_area_invalidation(self, data):
        """Deletes an area invalidation period."""
        device_label = data.get("device")
        start_dt = data.get("start")
        
        with self.get_connection() as conn:
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
                    "DELETE FROM area_invalidations WHERE device_id = ? AND start_dt = ?", 
                    (device_id, start_dt)
                )
            else:
                conn.execute(
                    "DELETE FROM area_invalidations WHERE device_id IS NULL AND start_dt = ?", 
                    (start_dt,)
                )
            conn.commit()
            self.sync_invalidation_ids()

