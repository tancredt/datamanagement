"""Database connection, setup, and schema initialization."""
import os
import json
import sqlite3
import logging

from contextlib import contextmanager

logger = logging.getLogger(__name__)

CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(os.path.dirname(CURRENT_DIR))


class DatabaseConnection:
    """Base class providing connection management and schema setup."""

    def __init__(self, incident_path):
        self.incident_path = os.path.abspath(incident_path)
        self.meta_dir = os.path.join(self.incident_path, "meta")
        self.mapping_dir = os.path.join(self.incident_path, "mapping")
        self.data_dir = os.path.join(self.incident_path, "data")
        self.db_path = os.path.join(self.data_dir, "incident.db")
        os.makedirs(self.meta_dir, exist_ok=True)
        os.makedirs(self.mapping_dir, exist_ok=True)
        os.makedirs(self.data_dir, exist_ok=True)

    @contextmanager
    def get_connection(self):
        conn = None
        try:
            conn = sqlite3.connect(self.db_path)
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA foreign_keys = ON;")
            yield conn
        except sqlite3.Error as e:
            logger.error("Database error: %s", e)
            raise
        finally:
            if conn:
                conn.close()

    def setup_database(self):
        self.initialize_database()

    def initialize_database(self):
        self._create_schema()
        self._populate_analytes()
        self._populate_area_devices()
        logger.info("Database initialized successfully at %s", self.db_path)

    def _create_schema(self):
        sql_path = os.path.join(PROJECT_ROOT, 'sql', 'creates.sql')
        if not os.path.exists(sql_path):
            raise FileNotFoundError(f"Schema file missing: {sql_path}")
        with self.get_connection() as conn:
            with open(sql_path, 'r', encoding='utf-8') as f:
                conn.executescript(f.read())

    def _populate_analytes(self):
        """Reads static/lists/analytes.json and inserts into the analyte table."""
        analytes_path = os.path.join(PROJECT_ROOT, 'static', 'lists', 'analytes.json')
        if not os.path.exists(analytes_path):
            logger.warning("Analytes JSON not found: %s", analytes_path)
            return
        
        with open(analytes_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        analytes_list = data.get("analytes")
        
        with self.get_connection() as conn:
            cursor = conn.cursor()
            for analyte in analytes_list:
                label = analyte.get("label")
                responder = analyte.get("responder_name")
                dec_pls = analyte.get("dec_pls") or 2
                hotzone = float(
                    analyte.get("hotzone_threshold")
                )
                warmzone = float(
                    analyte.get("warmzone_threshold")
                )
                fireground = float(
                    analyte.get("fireground_threshold")
                )
                community = float(
                    analyte.get("community_threshold")
                )
                
                cursor.execute("""
                INSERT OR IGNORE INTO analyte 
                (label, responder_name, dec_pls, hotzone_threshold, 
                warmzone_threshold, fireground_threshold, community_threshold)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """, (label, responder, int(dec_pls), hotzone, warmzone, 
                      fireground, community))
            conn.commit()

    def _populate_area_devices(self):
        """Reads static/lists/area_devices.json and inserts into the device table."""
        devices_path = os.path.join(PROJECT_ROOT, 'static', 'lists', 'area_devices.json')
        if not os.path.exists(devices_path):
            logger.warning("Area devices JSON not found: %s", devices_path)
            return
        
        with open(devices_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        devices_list = data.get("devices") or []
                
        with self.get_connection() as conn:
            cursor = conn.cursor()
            for device in devices_list:
                label = device.get("label")
                serial = device.get("serial") or ""
                
                cursor.execute("""
                INSERT OR IGNORE INTO device (label, serial, device_type)
                VALUES (?, ?, ?)
                """, (label, serial, "area"))
            conn.commit()

