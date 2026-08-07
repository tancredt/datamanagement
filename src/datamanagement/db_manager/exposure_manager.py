import os
import logging

logger = logging.getLogger(__name__)

class ExposureMixin:
    def get_exposure_ids(self):
        """Returns list of all unique exposure identifiers."""
        with self.get_connection() as conn:
            query = """
                SELECT DISTINCT identifier FROM exposure 
                WHERE identifier IS NOT NULL AND identifier != '' 
                ORDER BY identifier
            """
            rows = conn.execute(query).fetchall()
            return [row['identifier'] for row in rows]

    def get_exposures(self):
        """Returns all exposure monitoring sessions with their analyte readings."""
        with self.get_connection() as conn:
            exp_rows = conn.execute("""
                SELECT id, identifier, start_dt, stop_dt, area, activities, 
                       respiratory, clothing, footwear  
                FROM exposure 
                ORDER BY start_dt ASC
            """).fetchall()
            
            exposures = []
            for exp in exp_rows:
                device_label = ""
                if exp['device_id']:
                    dev_row = conn.execute(
                        "SELECT label FROM device WHERE id = ?", 
                        (exp['device_id'],)
                    ).fetchone()
                    if dev_row:
                        device_label = dev_row['label']
                
                exp_dict = {
                    "id": exp['identifier'],
                    "device": device_label,
                    "start": exp['start_dt'],
                    "stop": exp['stop_dt'],
                    "area": exp['area'],
                    "activities": exp['activities'],
                    "resp_protection": exp['respiratory'],
                    "clothing": exp['clothing'],
                    "footwear": exp['footwear'],
                    "values": {}
                }
                
                reading_rows = conn.execute("""
                    SELECT a.label, er.min_value, er.max_value, er.mean_value
                    FROM exposure_reading er 
                    JOIN analyte a ON er.analyte_id = a.id 
                    WHERE er.exposure_id = ?
                """, (exp['id'],)).fetchall()
                
                for r in reading_rows:
                    exp_dict["values"][r['label']] = {
                        "min": r['min_value'],
                        "max": r['max_value'],
                        "mean": r['mean_value']
                    }
                
                exposures.append(exp_dict)
            
        return exposures
        
    def add_exposure(self, data, analyte_lookup):
        """Adds a new exposure monitoring session."""
        identifier = data.get("id")
        device_label = data.get("device")
        start_dt = data.get("start")
        stop_dt = data.get("stop")
        area = data.get("area")
        activities = data.get("activities")
        respiratory = data.get("resp_protection")
        clothing = data.get("clothing")
        footwear = data.get("footwear")
        values = data.get("values", {})
        
        with self.get_connection() as conn:
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
                        (device_label, "personal")
                    ).lastrowid
            
            exposure_id = conn.execute("""
                INSERT INTO exposure 
                (identifier, start_dt, stop_dt, area, activities, respiratory, 
                 clothing, footwear, device_id)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (identifier, start_dt, stop_dt, area, activities, respiratory, 
                  clothing, footwear, device_id)).lastrowid
            
            for analyte_label, stats in values.items():
                if analyte_label in analyte_lookup:
                    conn.execute("""
                        INSERT INTO exposure_reading 
                        (exposure_id, analyte_id, device_id, min_value, max_value, mean_value)
                        VALUES (?, ?, ?, ?, ?, ?)
                    """, (exposure_id, analyte_lookup[analyte_label], device_id, 
                          stats.get("min"), stats.get("max"), stats.get("mean")))
            conn.commit()

    # pylint: disable=too-many-locals
    def edit_exposure(self, old_data, new_data, analyte_lookup):
        """Edits an existing exposure monitoring session."""
        old_identifier = old_data.get("id")
        old_start = old_data.get("start")
        
        with self.get_connection() as conn:
            old_exp = conn.execute(
                "SELECT id FROM exposure WHERE identifier = ? AND start_dt = ?", 
                (old_identifier, old_start)
            ).fetchone()
            
            if not old_exp:
                return False, "Could not find the original exposure to edit."
            
            old_exposure_id = old_exp['id']
            conn.execute(
                "DELETE FROM exposure_reading WHERE exposure_id = ?", 
                (old_exposure_id,)
            )
            
            identifier = new_data.get("id")
            device_label = new_data.get("device")
            start_dt = new_data.get("start")
            stop_dt = new_data.get("stop")
            area = new_data.get("area")
            activities = new_data.get("activities")
            respiratory = new_data.get("resp_protection")
            clothing = new_data.get("clothing")
            footwear = new_data.get("footwear")
            values = new_data.get("values", {})
            
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
                        (device_label, "personal")
                    ).lastrowid
            
            conn.execute("""
                UPDATE exposure 
                SET identifier=?, start_dt=?, stop_dt=?, area=?, activities=?, 
                    respiratory=?, clothing=?, footwear=? 
                WHERE id=?
            """, (identifier, start_dt, stop_dt, area, activities, respiratory, 
                  clothing, footwear, old_exposure_id))
            
            for analyte_label, stats in values.items():
                if analyte_label in analyte_lookup:
                    conn.execute("""
                        INSERT INTO exposure_reading 
                        (exposure_id, analyte_id, device_id, min_value, max_value, mean_value)
                        VALUES (?, ?, ?, ?, ?, ?)
                    """, (old_exposure_id, analyte_lookup[analyte_label], device_id, 
                          stats.get("min"), stats.get("max"), stats.get("mean")))
            conn.commit()
            return True, ""

    def delete_exposure(self, data):
        """Deletes an exposure monitoring session."""
        identifier = data.get("id")
        start_dt = data.get("start")
        
        with self.get_connection() as conn:
            exp = conn.execute(
                "SELECT id FROM exposure WHERE identifier = ? AND start_dt = ?", 
                (identifier, start_dt)
            ).fetchone()
            
            if exp:
                conn.execute(
                    "DELETE FROM exposure_reading WHERE exposure_id = ?", 
                    (exp['id'],)
                )
                conn.execute(
                    "DELETE FROM exposure WHERE id = ?", 
                    (exp['id'],)
                )
                conn.commit()
