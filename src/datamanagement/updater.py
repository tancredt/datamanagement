"""
Updater module - provides synchronization functions for area data processing.

This module re-exports sync functionality from db_manager/sync_manager.py
for backward compatibility with existing imports.
"""
import logging
from datamanagement.db_manager import IncidentDatabase

logger = logging.getLogger(__name__)


def sync_all(incident_path):
    """
    Perform all synchronization operations for an incident database.
    
    This includes:
    - Syncing marker IDs (area_reading.marker_id based on area_location)
    - Syncing invalidation IDs (area_reading_analyte.invalidation_id based on area_invalidations)
    
    Parameters
    ----------
    incident_path : str
        Path to the incident directory containing the database file.
    """
    try:
        db = IncidentDatabase(incident_path)
        
        # Sync marker IDs
        logger.info("Syncing marker IDs...")
        db.sync_marker_ids()
        
        # Sync invalidation IDs
        logger.info("Syncing invalidation IDs...")
        db.sync_invalidation_ids()
        
        logger.info("Synchronization complete.")
        
    except Exception as e:
        logger.error(f"Error during synchronization: {e}")
        raise
