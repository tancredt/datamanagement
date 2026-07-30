import logging
from datamanagement.db_manager import IncidentDatabase

logger = logging.getLogger(__name__)

# ==========================================
# 1. SYNC AREA READING MARKERS
# ==========================================
def sync_area_reading_markers(incident_path):
    """
    Updates the marker_id in area_reading based on the device's location 
    between start and stop times defined in area_location.
    """
    db = IncidentDatabase(incident_path)
    db.sync_marker_ids()
    logger.info("✅ Synced marker_id in area_reading")

# ==========================================
# 2. SYNC AREA READING INVALIDATIONS
# ==========================================
def sync_area_reading_invalidations(incident_path):
    """
    Updates the invalidation_id in area_reading_analyte based on the 
    validation start/stop times defined in area_invalidations.
    """
    db = IncidentDatabase(incident_path)
    db.sync_invalidation_ids()
    logger.info("✅ Synced invalidation_id in area_reading_analyte")

# ==========================================
# 3. SYNC ALL
# ==========================================
def sync_all(incident_path):
    """Runs all synchronization updates."""
    sync_area_reading_markers(incident_path)
    sync_area_reading_invalidations(incident_path)
