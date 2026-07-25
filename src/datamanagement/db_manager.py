import os
import json
import shutil
import sqlite3
import logging
from contextlib import contextmanager

logger = logging.getLogger(__name__)

# Resolve project root assuming this file is inside the datamanagement/ directory
CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(CURRENT_DIR)

class IncidentDatabase:
    """
    Manages the SQLite database for a specific incident.
    Handles connection lifecycle, schema creation, and all data interactions.
    """
    def __init__(self, incident_path):
        self.incident_path = os.path.abspath(incident_path)
        self.meta_dir = os.path.join(self.incident_path, "meta")
        self.mapping_dir = os.path.join(self.incident_path, "mapping")
        self.db_path = os.path.join(self.meta_dir, "incident.db")
        
        # Ensure directories exist before attempting DB operations
        os.makedirs(self.meta_dir, exist_ok=True)
        os.makedirs(self.mapping_dir, exist_ok=True)

    @contextmanager
    def get_connection(self):
        """
        Context manager for safe database connections.
        Ensures PRAGMA foreign_keys is enabled and connections are properly closed.
        """
        conn = None
        try:
            conn = sqlite3.connect(self.db_path)
            conn.row_factory = sqlite3.Row  # Allows accessing columns by name
            conn.execute("PRAGMA foreign_keys = ON;")
            yield conn
        except sqlite3.Error as e:
            logger.error(f"Database error: {e}")
            raise
        finally:
            if conn:
                conn.close()

    # ==========================================
    # 1. INITIALIZATION
    # ==========================================
    def initialize_database(self):
        """Master method to create the schema and populate initial reference data."""
        self._create_schema()
        self._populate_analytes()
        self._populate_area_devices()
        logger.info(f"Database initialized successfully at {self.db_path}")

    def _create_schema(self):
        """Executes the creates.sql script to build tables and indexes."""
        sql_path = os.path.join(PROJECT_ROOT, 'sql', 'creates.sql')
        if not os.path.exists(sql_path):
            logger.error(f"SQL schema file not found: {sql_path}")
            raise FileNotFoundError(f"Schema file missing: {sql_path}")

        with self.get_connection() as conn:
            with open(sql_path, 'r', encoding='utf-8') as f:
                sql_script = f.read()
            conn.executescript(sql_script)

    def _populate_analytes(self):
        """Reads static/lists/analytes.json and inserts into the analyte table."""
        analytes_path = os.path.join(PROJECT_ROOT, 'static', 'lists', 'analytes.json')
        if not os.path.exists(analytes_path):
            logger.warning(f"Analytes JSON not found: {analytes_path}")
            return

        with open(analytes_path, 'r', encoding='utf-8') as f:
            data = json.load(f)

        if isinstance(data, list):
            analytes_list = data
        elif isinstance(data, dict):
            analytes_list = data.get("analytes") or data.get("analytes ") or []
        else:
            analytes_list = []

        with self.get_connection() as conn:
            cursor = conn.cursor()
            for analyte in analytes_list:
                label = (analyte.get("label") or analyte.get("label ") or "").strip()
                responder = (analyte.get("responder_name") or analyte.get("responder_name ") or "").strip()
                dec_pls = analyte.get("dec_pls") or analyte.get("dec_pls ") or 2
                
                hotzone = float(analyte.get("hotzone_threshold") or analyte.get("hotzone_threshold ") or 0.0)
                warmzone = float(analyte.get("warmzone_threshold") or analyte.get("warmzone_threshold ") or 0.0)
                fireground = float(analyte.get("fireground_threshold") or analyte.get("fireground_threshold ") or 0.0)
                community = float(analyte.get("community_threshold") or analyte.get("community_threshold ") or 0.0)
                
                if label:
                    cursor.execute("""
                        INSERT OR IGNORE INTO analyte 
                        (label, responder_name, dec_pls, hotzone_threshold, warmzone_threshold, fireground_threshold, community_threshold)
                        VALUES (?, ?, ?, ?, ?, ?, ?)
                    """, (label, responder, int(dec_pls), hotzone, warmzone, fireground, community))
            conn.commit()

    def _populate_area_devices(self):
        """Reads static/lists/area_devices.json and inserts into the device table."""
        devices_path = os.path.join(PROJECT_ROOT, 'static', 'lists', 'area_devices.json')
        if not os.path.exists(devices_path):
            logger.warning(f"Area devices JSON not found: {devices_path}")
            return

        with open(devices_path, 'r', encoding='utf-8') as f:
            data = json.load(f)

        if isinstance(data, list):
            devices_list = data
        elif isinstance(data, dict):
            devices_list = data.get("devices") or data.get("devices ") or []
        else:
            devices_list = []

        with self.get_connection() as conn:
            cursor = conn.cursor()
            for device in devices_list:
                label = (device.get("label") or device.get("label ") or "").strip()
                serial = (device.get("serial") or device.get("serial ") or "").strip()
                if label:
                    cursor.execute("""
                        INSERT OR IGNORE INTO device (label, serial, device_type)
                        VALUES (?, ?, ?)
                    """, (label, serial, "area"))
            conn.commit()

    # ==========================================
    # 2. UNIFIED DATA ACCESSORS
    # ==========================================
    def get_analytes(self):
        """Returns list of dicts: {id, label, dec_pls} for all analytes."""
        with self.get_connection() as conn:
            rows = conn.execute("SELECT id, label, dec_pls FROM analyte ORDER BY label").fetchall()
            return [dict(row) for row in rows]

    def get_devices(self, data_type):
        """
        Returns list of device labels filtered by data_type.
        - spot: device_type = 'spot'
        - area: device_type = 'area'
        - spectral: device_type = 'spectral'
        - exposure: device_type IN ('spot', 'personal')
        """
        with self.get_connection() as conn:
            if data_type == "exposure":
                query = "SELECT label FROM device WHERE device_type IN ('spot', 'personal') ORDER BY label"
                rows = conn.execute(query).fetchall()
            elif data_type in ["spot", "area", "spectral"]:
                query = "SELECT label FROM device WHERE device_type = ? ORDER BY label"
                rows = conn.execute(query, (data_type,)).fetchall()
            else:
                return []
            return [row['label'] for row in rows]

    def get_markers(self, data_type=None):
        """
        Returns list of all marker labels. 
        (data_type is accepted for interface consistency, but all data types share the same global markers).
        """
        with self.get_connection() as conn:
            rows = conn.execute("SELECT label FROM marker ORDER BY label").fetchall()
            return [row['label'] for row in rows]

    # ==========================================
    # 3. MAP & MARKER MANAGEMENT
    # ==========================================
    def add_map(self, image_path):
        """Copies an image to the mapping dir and registers it in the sitemap table."""
        fname = os.path.basename(image_path)
        dest_path = os.path.join(self.mapping_dir, fname)
        if not os.path.exists(dest_path):
            shutil.copy2(image_path, dest_path)
        
        with self.get_connection() as conn:
            conn.execute("INSERT OR IGNORE INTO sitemap (file_name) VALUES (?)", (fname,))
            conn.commit()
        return fname

    def delete_map(self, map_filename):
        """Deletes a map, its physical file, and all its marker placements."""
        file_path = os.path.join(self.mapping_dir, map_filename)
        if os.path.exists(file_path):
            try: os.remove(file_path)
            except Exception as e: logger.error(f"Failed to delete physical map file {file_path}: {e}")
                
        with self.get_connection() as conn:
            conn.execute("DELETE FROM sitemap WHERE file_name = ?", (map_filename,))
            conn.commit()

    def get_maps(self):
        """Returns a list of all map file names."""
        with self.get_connection() as conn:
            rows = conn.execute("SELECT file_name FROM sitemap ORDER BY file_name").fetchall()
            return [row["file_name"] for row in rows]

    def get_all_used_labels(self):
        """Returns a set of all marker labels in the database."""
        with self.get_connection() as conn:
            rows = conn.execute("SELECT label FROM marker").fetchall()
            return {row["label"] for row in rows}

    def get_next_label(self):
        """Generates the next alphabetical label (A, B, ... Z, AA, ... ZZ)."""
        used_labels = self.get_all_used_labels()
        max_idx = -1
        for label in used_labels:
            label_upper = str(label).strip().upper()
            if not label_upper.isalpha(): continue
            idx = 0
            for char in label_upper:
                idx = idx * 26 + (ord(char) - 64)
            idx -= 1
            if idx > max_idx: max_idx = idx
        
        next_idx = max_idx + 1
        idx = next_idx + 1
        result = []
        while idx > 0:
            idx, rem = divmod(idx - 1, 26)
            result.append(chr(65 + rem))
        return ''.join(reversed(result))

    def add_marker(self, label, description="", latitude=None, longitude=None):
        """Adds a new marker. If label exists, ignores insert. Returns marker ID."""
        with self.get_connection() as conn:
            conn.execute("""
                INSERT OR IGNORE INTO marker (label, description, latitude, longitude) 
                VALUES (?, ?, ?, ?)
            """, (label, description, latitude, longitude))
            conn.commit()
            row = conn.execute("SELECT id FROM marker WHERE label = ?", (label,)).fetchone()
            return row["id"] if row else None

    def update_marker(self, label, description=None, latitude=None, longitude=None):
        """Updates an existing marker's details."""
        with self.get_connection() as conn:
            updates, params = [], []
            if description is not None: updates.append("description = ?"); params.append(description)
            if latitude is not None: updates.append("latitude = ?"); params.append(latitude)
            if longitude is not None: updates.append("longitude = ?"); params.append(longitude)
            
            if updates:
                params.append(label)
                conn.execute(f"UPDATE marker SET {', '.join(updates)} WHERE label = ?", params)
                conn.commit()

    def delete_marker(self, label):
        """Deletes a marker. Cascades to sitemap_marker via DB constraints."""
        with self.get_connection() as conn:
            conn.execute("DELETE FROM marker WHERE label = ?", (label,))
            conn.commit()

    def place_marker_on_map(self, marker_label, map_filename, x_coord, y_coord):
        """Places a marker on a specific map with pixel coordinates (UPSERT)."""
        with self.get_connection() as conn:
            marker_row = conn.execute("SELECT id FROM marker WHERE label = ?", (marker_label,)).fetchone()
            map_row = conn.execute("SELECT id FROM sitemap WHERE file_name = ?", (map_filename,)).fetchone()
            
            if not marker_row or not map_row:
                raise ValueError(f"Marker '{marker_label}' or Map '{map_filename}' not found.")
                
            conn.execute("""
                INSERT INTO sitemap_marker (marker_id, sitemap_id, x_coord, y_coord)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(marker_id, sitemap_id) DO UPDATE SET
                    x_coord = excluded.x_coord, y_coord = excluded.y_coord
            """, (marker_row["id"], map_row["id"], x_coord, y_coord))
            conn.commit()

    def remove_marker_from_map(self, marker_label, map_filename):
        """Removes a marker's placement from a specific map."""
        with self.get_connection() as conn:
            conn.execute("""
                DELETE FROM sitemap_marker 
                WHERE marker_id = (SELECT id FROM marker WHERE label = ?)
                AND sitemap_id = (SELECT id FROM sitemap WHERE file_name = ?)
            """, (marker_label, map_filename))
            conn.commit()

    def get_markers_for_map(self, map_filename):
        """Returns a list of marker dicts placed on a specific map, including x/y coords."""
        with self.get_connection() as conn:
            query = """
                SELECT m.label, m.description, m.latitude, m.longitude, 
                       sm.x_coord, sm.y_coord
                FROM marker m
                JOIN sitemap_marker sm ON m.id = sm.marker_id
                JOIN sitemap s ON sm.sitemap_id = s.id
                WHERE s.file_name = ?
            """
            rows = conn.execute(query, (map_filename,)).fetchall()
            return [dict(row) for row in rows]

    def get_maps_data(self):
        """Returns a dict of {filename: [markers]} for compatibility with UI."""
        maps_data = {}
        for fname in self.get_maps():
            maps_data[fname] = self.get_markers_for_map(fname)
        return maps_data

    # ==========================================
    # 4. SPOT READINGS MANAGEMENT
    # ==========================================
    def get_spot_readings(self):
        """Returns a list of flat reading dicts for the UI."""
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
                        "location": row['location'], "device": row['device'] or "",
                        "logtime": row['logtime'], "observations": row['observations'] or ""
                    }
                readings_dict[key][row['analyte']] = row['value']
            return list(readings_dict.values())

    def add_spot_reading(self, reading_data, analyte_lookup):
        """Straight INSERT for a new spot reading event."""
        location, device_label = reading_data.get("location"), reading_data.get("device")
        logtime, observations = reading_data.get("logtime"), reading_data.get("observations")
        
        with self.get_connection() as conn:
            marker_id = conn.execute("SELECT id FROM marker WHERE label = ?", (location,)).fetchone()['id']
            
            device_id = None
            if device_label:
                dev_row = conn.execute("SELECT id FROM device WHERE label = ?", (device_label,)).fetchone()
                if dev_row: device_id = dev_row['id']
                else: device_id = conn.execute("INSERT INTO device (label, device_type) VALUES (?, ?)", (device_label, "spot")).lastrowid
                    
            try:
                for analyte_label, analyte_id in analyte_lookup.items():
                    val = reading_data.get(analyte_label)
                    if val is not None and str(val).strip() != "":
                        conn.execute("""
                            INSERT INTO spot_reading (value, timestamp, comment, device_id, analyte_id, marker_id)
                            VALUES (?, ?, ?, ?, ?, ?)
                        """, (float(val), logtime, observations, device_id, analyte_id, marker_id))
                conn.commit()
                return True, ""
            except sqlite3.IntegrityError:
                conn.rollback()
                return False, "A reading for this location, time, and analyte already exists."

    def edit_spot_reading(self, new_data, old_data, analyte_lookup):
        """Targeted UPDATE/INSERT for editing an existing spot reading event."""
        new_loc, new_dev, new_time, new_obs = new_data.get("location"), new_data.get("device"), new_data.get("logtime"), new_data.get("observations")
        old_loc, old_time = old_data.get("location"), old_data.get("logtime")
        
        with self.get_connection() as conn:
            new_marker_id = conn.execute("SELECT id FROM marker WHERE label = ?", (new_loc,)).fetchone()['id']
            old_marker_id = conn.execute("SELECT id FROM marker WHERE label = ?", (old_loc,)).fetchone()['id']
            
            new_device_id = None
            if new_dev:
                dev_row = conn.execute("SELECT id FROM device WHERE label = ?", (new_dev,)).fetchone()
                if dev_row: new_device_id = dev_row['id']
                else: new_device_id = conn.execute("INSERT INTO device (label, device_type) VALUES (?, ?)", (new_dev, "spot")).lastrowid
            
            new_analytes = {}
            for label, aid in analyte_lookup.items():
                val = new_data.get(label)
                if val is not None and str(val).strip() != "":
                    try: new_analytes[label] = {"id": aid, "value": float(val)}
                    except ValueError: pass
                        
            old_rows = conn.execute("SELECT id, analyte_id FROM spot_reading WHERE marker_id = ? AND timestamp = ?", (old_marker_id, old_time)).fetchall()
            id_to_label = {v: k for k, v in analyte_lookup.items()}
            handled_ids = set()
            
            try:
                for row in old_rows:
                    db_label = id_to_label.get(row['analyte_id'])
                    if db_label is None: continue
                    if db_label in new_analytes:
                        conn.execute("UPDATE spot_reading SET value=?, timestamp=?, comment=?, device_id=?, marker_id=? WHERE id=?",
                                     (new_analytes[db_label]["value"], new_time, new_obs, new_device_id, new_marker_id, row['id']))
                        handled_ids.add(row['analyte_id'])
                    else:
                        conn.execute("DELETE FROM spot_reading WHERE id = ?", (row['id'],))
                        
                for label, data in new_analytes.items():
                    if data["id"] not in handled_ids:
                        conn.execute("INSERT INTO spot_reading (value, timestamp, comment, device_id, analyte_id, marker_id) VALUES (?, ?, ?, ?, ?, ?)",
                                     (data["value"], new_time, new_obs, new_device_id, data["id"], new_marker_id))
                conn.commit()
                return True, ""
            except sqlite3.IntegrityError:
                conn.rollback()
                return False, "The updated reading conflicts with an existing reading."

    def delete_spot_reading(self, reading_data):
        """Deletes a spot reading event from the database."""
        location, device_label, logtime = reading_data.get("location"), reading_data.get("device"), reading_data.get("logtime")
        with self.get_connection() as conn:
            marker_id = conn.execute("SELECT id FROM marker WHERE label = ?", (location,)).fetchone()['id']
            device_id = None
            if device_label:
                dev_row = conn.execute("SELECT id FROM device WHERE label = ?", (device_label,)).fetchone()
                if dev_row: device_id = dev_row['id']
            
            if device_id: conn.execute("DELETE FROM spot_reading WHERE marker_id=? AND device_id=? AND timestamp=?", (marker_id, device_id, logtime))
            else: conn.execute("DELETE FROM spot_reading WHERE marker_id=? AND device_id IS NULL AND timestamp=?", (marker_id, logtime))
            conn.commit()

    # ==========================================
    # 5. AREA LOCATIONS MANAGEMENT
    # ==========================================
    def get_area_locations(self):
        """Returns a list of area location dicts."""
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
        """Adds a new area location."""
        with self.get_connection() as conn:
            marker_id = conn.execute("SELECT id FROM marker WHERE label = ?", (location,)).fetchone()['id']
            device_id = None
            if device_label:
                dev_row = conn.execute("SELECT id FROM device WHERE label = ?", (device_label,)).fetchone()
                if dev_row: device_id = dev_row['id']
                else: device_id = conn.execute("INSERT INTO device (label, device_type) VALUES (?, ?)", (device_label, "area")).lastrowid

            try:
                conn.execute("INSERT INTO area_location (start_dt, stop_dt, comment, device_id, marker_id) VALUES (?, ?, ?, ?, ?)",
                             (start_dt, stop_dt, comment, device_id, marker_id))
                conn.commit()
                return True, ""
            except sqlite3.IntegrityError as e:
                return False, f"Database error: {e}"

    def edit_area_location(self, old_data, new_data):
        """Edits an existing area location."""
        old_loc, old_dev, old_start = old_data.get("location"), old_data.get("device"), old_data.get("start")
        new_loc, new_dev, new_start, new_stop, new_comment = new_data.get("location"), new_data.get("device"), new_data.get("start"), new_data.get("stop"), new_data.get("comment")

        with self.get_connection() as conn:
            old_marker_id = conn.execute("SELECT id FROM marker WHERE label = ?", (old_loc,)).fetchone()['id']
            new_marker_id = conn.execute("SELECT id FROM marker WHERE label = ?", (new_loc,)).fetchone()['id']
            
            old_device_id = None
            if old_dev:
                row = conn.execute("SELECT id FROM device WHERE label = ?", (old_dev,)).fetchone()
                if row: old_device_id = row['id']
                
            new_device_id = None
            if new_dev:
                row = conn.execute("SELECT id FROM device WHERE label = ?", (new_dev,)).fetchone()
                if row: new_device_id = row['id']
                else: new_device_id = conn.execute("INSERT INTO device (label, device_type) VALUES (?, ?)", (new_dev, "area")).lastrowid

            try:
                if old_device_id:
                    conn.execute("UPDATE area_location SET start_dt=?, stop_dt=?, comment=?, device_id=?, marker_id=? WHERE marker_id=? AND device_id=? AND start_dt=?",
                                 (new_start, new_stop, new_comment, new_device_id, new_marker_id, old_marker_id, old_device_id, old_start))
                else:
                    conn.execute("UPDATE area_location SET start_dt=?, stop_dt=?, comment=?, device_id=?, marker_id=? WHERE marker_id=? AND device_id IS NULL AND start_dt=?",
                                 (new_start, new_stop, new_comment, new_device_id, new_marker_id, old_marker_id, old_start))
                conn.commit()
                return True, ""
            except sqlite3.IntegrityError as e:
                return False, f"Database error: {e}"

    def delete_area_location(self, data):
        """Deletes an area location."""
        location, device_label, start_dt = data.get("location"), data.get("device"), data.get("start")
        with self.get_connection() as conn:
            marker_id = conn.execute("SELECT id FROM marker WHERE label = ?", (location,)).fetchone()['id']
            device_id = None
            if device_label:
                row = conn.execute("SELECT id FROM device WHERE label = ?", (device_label,)).fetchone()
                if row: device_id = row['id']
                
            if device_id: conn.execute("DELETE FROM area_location WHERE marker_id=? AND device_id=? AND start_dt=?", (marker_id, device_id, start_dt))
            else: conn.execute("DELETE FROM area_location WHERE marker_id=? AND device_id IS NULL AND start_dt=?", (marker_id, start_dt))
            conn.commit()

    # ==========================================
    # 6. AREA INVALIDATIONS (DEVICE VALIDATIONS)
    # ==========================================
    def get_area_invalidations(self):
        """Returns a list of validation dicts."""
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
                key = (row['device'] or "", row['start'], row['stop'] or "", row['comment'] or "")
                if key not in validations_dict:
                    validations_dict[key] = {"device": row['device'] or "", "start": row['start'], "stop": row['stop'] or "", "comment": row['comment'] or "", "analytes": []}
                validations_dict[key]["analytes"].append(row['analyte'])
            return list(validations_dict.values())

    def add_area_invalidation(self, device_label, start_dt, stop_dt, comment, analyte_labels):
        """Adds new invalidation rows for the given analytes."""
        with self.get_connection() as conn:
            device_id = None
            if device_label:
                row = conn.execute("SELECT id FROM device WHERE label = ?", (device_label,)).fetchone()
                if row: device_id = row['id']
                else: device_id = conn.execute("INSERT INTO device (label, device_type) VALUES (?, ?)", (device_label, "area")).lastrowid
            
            for analyte_label in analyte_labels:
                analyte_row = conn.execute("SELECT id FROM analyte WHERE label = ?", (analyte_label,)).fetchone()
                if analyte_row:
                    conn.execute("INSERT INTO area_invalidations (start_dt, stop_dt, comment, device_id, analyte_id, invalid_flag) VALUES (?, ?, ?, ?, ?, 1)",
                                 (start_dt, stop_dt, comment, device_id, analyte_row['id']))
            conn.commit()

    def edit_area_invalidation(self, old_data, new_data):
        """Edits an existing invalidation by deleting old rows and inserting new ones."""
        old_device, old_start = old_data.get("device"), old_data.get("start")
        new_device, new_start, new_stop, new_comment, new_analytes = new_data.get("device"), new_data.get("start"), new_data.get("stop"), new_data.get("comment"), new_data.get("analytes", [])
        
        with self.get_connection() as conn:
            old_device_id = None
            if old_device:
                row = conn.execute("SELECT id FROM device WHERE label = ?", (old_device,)).fetchone()
                if row: old_device_id = row['id']
            
            if old_device_id: conn.execute("DELETE FROM area_invalidations WHERE device_id = ? AND start_dt = ?", (old_device_id, old_start))
            else: conn.execute("DELETE FROM area_invalidations WHERE device_id IS NULL AND start_dt = ?", (old_start,))
                
            new_device_id = None
            if new_device:
                row = conn.execute("SELECT id FROM device WHERE label = ?", (new_device,)).fetchone()
                if row: new_device_id = row['id']
                else: new_device_id = conn.execute("INSERT INTO device (label, device_type) VALUES (?, ?)", (new_device, "area")).lastrowid
                    
            for analyte_label in new_analytes:
                analyte_row = conn.execute("SELECT id FROM analyte WHERE label = ?", (analyte_label,)).fetchone()
                if analyte_row:
                    conn.execute("INSERT INTO area_invalidations (start_dt, stop_dt, comment, device_id, analyte_id, invalid_flag) VALUES (?, ?, ?, ?, ?, 1)",
                                 (new_start, new_stop, new_comment, new_device_id, analyte_row['id']))
            conn.commit()

    def delete_area_invalidation(self, data):
        """Deletes an invalidation entry."""
        device_label, start_dt = data.get("device"), data.get("start")
        with self.get_connection() as conn:
            device_id = None
            if device_label:
                row = conn.execute("SELECT id FROM device WHERE label = ?", (device_label,)).fetchone()
                if row: device_id = row['id']
                
            if device_id: conn.execute("DELETE FROM area_invalidations WHERE device_id = ? AND start_dt = ?", (device_id, start_dt))
            else: conn.execute("DELETE FROM area_invalidations WHERE device_id IS NULL AND start_dt = ?", (start_dt,))
            conn.commit()

    # ==========================================
    # 7. SPECTRAL RESULTS MANAGEMENT
    # ==========================================
    def get_spectral_results(self):
        """Returns a list of spectral result dicts."""
        with self.get_connection() as conn:
            query = """
                SELECT m.label AS location, d.label AS device, sr.timestamp AS logtime,
                       sr.chemicals AS chemicals_identified, sr.comment AS comments, sr.file_ref
                FROM spectral_result sr
                JOIN marker m ON sr.marker_id = m.id
                LEFT JOIN device d ON sr.device_id = d.id
                ORDER BY sr.timestamp DESC
            """
            return [dict(row) for row in conn.execute(query).fetchall()]

    def add_spectral_result(self, location, device_label, logtime, chemicals, comments, file_ref):
        """Adds a new spectral result."""
        with self.get_connection() as conn:
            marker_id = conn.execute("SELECT id FROM marker WHERE label = ?", (location,)).fetchone()['id']
            device_id = None
            if device_label:
                dev_row = conn.execute("SELECT id FROM device WHERE label = ?", (device_label,)).fetchone()
                if dev_row: device_id = dev_row['id']
                else: device_id = conn.execute("INSERT INTO device (label, device_type) VALUES (?, ?)", (device_label, "spectral")).lastrowid
            else:
                return False, "Device is mandatory for spectral results."

            try:
                conn.execute("INSERT INTO spectral_result (chemicals, timestamp, comment, file_ref, device_id, marker_id) VALUES (?, ?, ?, ?, ?, ?)",
                             (chemicals, logtime, comments, file_ref, device_id, marker_id))
                conn.commit()
                return True, ""
            except sqlite3.IntegrityError as e:
                return False, f"Database error: {e}"

    def edit_spectral_result(self, old_data, new_data):
        """Edits an existing spectral result."""
        old_loc, old_dev, old_time = old_data.get("location"), old_data.get("device"), old_data.get("logtime")
        new_loc, new_dev, new_time = new_data.get("location"), new_data.get("device"), new_data.get("logtime")
        new_chem, new_comm, new_ref = new_data.get("chemicals_identified"), new_data.get("comments"), new_data.get("file_ref")

        with self.get_connection() as conn:
            old_marker_id = conn.execute("SELECT id FROM marker WHERE label = ?", (old_loc,)).fetchone()['id']
            new_marker_id = conn.execute("SELECT id FROM marker WHERE label = ?", (new_loc,)).fetchone()['id']
            
            old_device_id = None
            if old_dev:
                row = conn.execute("SELECT id FROM device WHERE label = ?", (old_dev,)).fetchone()
                if row: old_device_id = row['id']
                
            new_device_id = None
            if new_dev:
                row = conn.execute("SELECT id FROM device WHERE label = ?", (new_dev,)).fetchone()
                if row: new_device_id = row['id']
                else: new_device_id = conn.execute("INSERT INTO device (label, device_type) VALUES (?, ?)", (new_dev, "spectral")).lastrowid
            else:
                return False, "Device is mandatory for spectral results."

            try:
                if old_device_id:
                    conn.execute("UPDATE spectral_result SET chemicals=?, timestamp=?, comment=?, file_ref=?, device_id=?, marker_id=? WHERE marker_id=? AND device_id=? AND timestamp=?",
                                 (new_chem, new_time, new_comm, new_ref, new_device_id, new_marker_id, old_marker_id, old_device_id, old_time))
                else:
                    conn.execute("UPDATE spectral_result SET chemicals=?, timestamp=?, comment=?, file_ref=?, device_id=?, marker_id=? WHERE marker_id=? AND device_id IS NULL AND timestamp=?",
                                 (new_chem, new_time, new_comm, new_ref, new_device_id, new_marker_id, old_marker_id, old_time))
                conn.commit()
                return True, ""
            except sqlite3.IntegrityError as e:
                return False, f"Database error: {e}"

    def delete_spectral_result(self, data):
        """Deletes a spectral result."""
        location, device_label, logtime = data.get("location"), data.get("device"), data.get("logtime")
        with self.get_connection() as conn:
            marker_id = conn.execute("SELECT id FROM marker WHERE label = ?", (location,)).fetchone()['id']
            device_id = None
            if device_label:
                row = conn.execute("SELECT id FROM device WHERE label = ?", (device_label,)).fetchone()
                if row: device_id = row['id']

            if device_id: conn.execute("DELETE FROM spectral_result WHERE marker_id=? AND device_id=? AND timestamp=?", (marker_id, device_id, logtime))
            else: conn.execute("DELETE FROM spectral_result WHERE marker_id=? AND device_id IS NULL AND timestamp=?", (marker_id, logtime))
            conn.commit()

    # ==========================================
    # 8. EXPOSURE MANAGEMENT
    # ==========================================
    def get_exposure_ids(self):
        """Returns list of distinct identifiers from the exposure table."""
        with self.get_connection() as conn:
            rows = conn.execute("SELECT DISTINCT identifier FROM exposure WHERE identifier IS NOT NULL AND identifier != '' ORDER BY identifier").fetchall()
            return [row['identifier'] for row in rows]

    def get_exposures(self):
        """Returns a list of exposure dicts, including nested analyte readings."""
        with self.get_connection() as conn:
            exp_rows = conn.execute("SELECT id, identifier, start_dt, stop_dt, area, activities, respiratory, clothing, footwear, device_id FROM exposure ORDER BY start_dt DESC").fetchall()
            
            exposures = []
            for exp in exp_rows:
                device_label = ""
                if exp['device_id']:
                    dev_row = conn.execute("SELECT label FROM device WHERE id = ?", (exp['device_id'],)).fetchone()
                    if dev_row: device_label = dev_row['label']
                
                exp_dict = {
                    "id": exp['identifier'], "device": device_label, "start": exp['start_dt'], "stop": exp['stop_dt'],
                    "area": exp['area'], "activities": exp['activities'], "resp_protection": exp['respiratory'],
                    "clothing": exp['clothing'], "footwear": exp['footwear'], "values": {}
                }
                
                reading_rows = conn.execute("""
                    SELECT a.label, er.min_value, er.max_value, er.mean_value
                    FROM exposure_reading er JOIN analyte a ON er.analyte_id = a.id WHERE er.exposure_id = ?
                """, (exp['id'],)).fetchall()
                
                for r in reading_rows:
                    exp_dict["values"][r['label']] = {"min": r['min_value'], "max": r['max_value'], "mean": r['mean_value']}
                exposures.append(exp_dict)
            return exposures

    def add_exposure(self, data, analyte_lookup):
        """Adds a new exposure and its readings."""
        identifier, device_label, start_dt, stop_dt = data.get("id"), data.get("device"), data.get("start"), data.get("stop")
        area, activities, respiratory, clothing, footwear = data.get("area"), data.get("activities"), data.get("resp_protection"), data.get("clothing"), data.get("footwear")
        values = data.get("values", {})
        
        with self.get_connection() as conn:
            device_id = None
            if device_label:
                dev_row = conn.execute("SELECT id FROM device WHERE label = ?", (device_label,)).fetchone()
                if dev_row: device_id = dev_row['id']
                else: device_id = conn.execute("INSERT INTO device (label, device_type) VALUES (?, ?)", (device_label, "personal")).lastrowid
            
            exposure_id = conn.execute("""
                INSERT INTO exposure (identifier, start_dt, stop_dt, area, activities, respiratory, clothing, footwear, device_id)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (identifier, start_dt, stop_dt, area, activities, respiratory, clothing, footwear, device_id)).lastrowid
            
            for analyte_label, stats in values.items():
                if analyte_label in analyte_lookup:
                    conn.execute("""
                        INSERT INTO exposure_reading (exposure_id, analyte_id, device_id, min_value, max_value, mean_value)
                        VALUES (?, ?, ?, ?, ?, ?)
                    """, (exposure_id, analyte_lookup[analyte_label], device_id, stats.get("min"), stats.get("max"), stats.get("mean")))
            conn.commit()

    def edit_exposure(self, old_data, new_data, analyte_lookup):
        """Edits an existing exposure."""
        old_identifier, old_start = old_data.get("id"), old_data.get("start")
        
        with self.get_connection() as conn:
            old_exp = conn.execute("SELECT id FROM exposure WHERE identifier = ? AND start_dt = ?", (old_identifier, old_start)).fetchone()
            if not old_exp: return False, "Could not find the original exposure to edit."
            old_exposure_id = old_exp['id']
            
            conn.execute("DELETE FROM exposure_reading WHERE exposure_id = ?", (old_exposure_id,))
            
            identifier, device_label, start_dt, stop_dt = new_data.get("id"), new_data.get("device"), new_data.get("start"), new_data.get("stop")
            area, activities, respiratory, clothing, footwear = new_data.get("area"), new_data.get("activities"), new_data.get("resp_protection"), new_data.get("clothing"), new_data.get("footwear")
            values = new_data.get("values", {})
            
            device_id = None
            if device_label:
                dev_row = conn.execute("SELECT id FROM device WHERE label = ?", (device_label,)).fetchone()
                if dev_row: device_id = dev_row['id']
                else: device_id = conn.execute("INSERT INTO device (label, device_type) VALUES (?, ?)", (device_label, "personal")).lastrowid
                    
            conn.execute("""
                UPDATE exposure SET identifier=?, start_dt=?, stop_dt=?, area=?, activities=?, respiratory=?, clothing=?, footwear=?, device_id=? WHERE id=?
            """, (identifier, start_dt, stop_dt, area, activities, respiratory, clothing, footwear, device_id, old_exposure_id))
            
            for analyte_label, stats in values.items():
                if analyte_label in analyte_lookup:
                    conn.execute("""
                        INSERT INTO exposure_reading (exposure_id, analyte_id, device_id, min_value, max_value, mean_value)
                        VALUES (?, ?, ?, ?, ?, ?)
                    """, (old_exposure_id, analyte_lookup[analyte_label], device_id, stats.get("min"), stats.get("max"), stats.get("mean")))
            conn.commit()
            return True, ""

    def delete_exposure(self, data):
        """Deletes an exposure and its readings."""
        identifier, start_dt = data.get("id"), data.get("start")
        with self.get_connection() as conn:
            exp = conn.execute("SELECT id FROM exposure WHERE identifier = ? AND start_dt = ?", (identifier, start_dt)).fetchone()
            if exp:
                conn.execute("DELETE FROM exposure_reading WHERE exposure_id = ?", (exp['id'],))
                conn.execute("DELETE FROM exposure WHERE id = ?", (exp['id'],))
                conn.commit()

    # ==========================================
    # 9. PLUME MANAGEMENT
    # ==========================================
    def get_plumes(self):
        """Returns a list of plume dicts."""
        with self.get_connection() as conn:
            rows = conn.execute("SELECT id, model_dt, file_name FROM plume ORDER BY model_dt DESC, file_name").fetchall()
            return [dict(row) for row in rows]

    def add_plume(self, file_name, model_dt):
        """Adds a new plume record."""
        with self.get_connection() as conn:
            try:
                conn.execute("INSERT INTO plume (model_dt, file_name) VALUES (?, ?)", (model_dt, file_name))
                conn.commit()
                return True, ""
            except sqlite3.IntegrityError:
                return False, "Plume already exists."
            except Exception as e:
                return False, str(e)

    def delete_plume(self, file_name):
        """Deletes a plume record."""
        with self.get_connection() as conn:
            conn.execute("DELETE FROM plume WHERE file_name = ?", (file_name,))
            conn.commit()

# ==========================================
# 10. OVERVIEW & STATISTICS
# ==========================================
def get_data_time_range(self, data_type):
    """
    Returns the min and max timestamps for a data type.
    
    Args:
        data_type: One of 'area', 'spot', 'spectral', 'exposure'
    
    Returns:
        tuple (min_timestamp, max_timestamp) or (None, None) if no data
    """
    with self.get_connection() as conn:
        if data_type == "area":
            row = conn.execute("SELECT MIN(timestamp), MAX(timestamp) FROM area_reading").fetchone()
        elif data_type == "spot":
            row = conn.execute("SELECT MIN(timestamp), MAX(timestamp) FROM spot_reading").fetchone()
        elif data_type == "exposure":
            row = conn.execute("SELECT MIN(start_dt), MAX(start_dt) FROM exposure").fetchone()
        elif data_type == "spectral":
            row = conn.execute("SELECT MIN(timestamp), MAX(timestamp) FROM spectral_result").fetchone()
        else:
            return None, None
        
        if row and row[0] and row[1]:
            return row[0], row[1]
        return None, None


# ==========================================
# 11. THRESHOLD MANAGEMENT
# ==========================================
def get_all_thresholds(self):
    """
    Returns a list of dicts with analyte thresholds.
    
    Returns:
        list of dicts: [{label, hotzone_threshold, warmzone_threshold, fireground_threshold, community_threshold}, ...]
    """
    with self.get_connection() as conn:
        rows = conn.execute("""
            SELECT label, hotzone_threshold, warmzone_threshold, 
                   fireground_threshold, community_threshold 
            FROM analyte 
            ORDER BY label
        """).fetchall()
        return [dict(row) for row in rows]

def update_thresholds(self, thresholds_list):
    """
    Updates thresholds for multiple analytes. Creates new analytes if they don't exist.
    
    Args:
        thresholds_list: list of dicts with keys: label, hotzone, warmzone, fireground, community
    """
    with self.get_connection() as conn:
        for t in thresholds_list:
            label = t.get('label', '').strip()
            if not label:
                continue
            
            hotzone = float(t.get('hotzone', 0.0))
            warmzone = float(t.get('warmzone', 0.0))
            fireground = float(t.get('fireground', 0.0))
            community = float(t.get('community', 0.0))
            
            # Check if analyte exists
            exists = conn.execute("SELECT 1 FROM analyte WHERE label = ?", (label,)).fetchone()
            
            if not exists:
                # Insert new analyte with default dec_pls=2
                conn.execute("""
                    INSERT INTO analyte (label, dec_pls, hotzone_threshold, warmzone_threshold, fireground_threshold, community_threshold)
                    VALUES (?, 2, ?, ?, ?, ?)
                """, (label, hotzone, warmzone, fireground, community))
            else:
                conn.execute("""
                    UPDATE analyte 
                    SET hotzone_threshold=?, warmzone_threshold=?, fireground_threshold=?, community_threshold=?
                    WHERE label=?
                """, (hotzone, warmzone, fireground, community, label))
        
        conn.commit()
