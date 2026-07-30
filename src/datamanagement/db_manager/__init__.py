"""IncidentDatabase — composed from domain-specific mixins."""
from .base import DatabaseConnection
from .accessors import AccessorsMixin
from .map_marker_manager import MapMarkerMixin
from .spot_readings_manager import SpotReadingsMixin
from .area_manager import AreaMixin
from .spectral_manager import SpectralMixin
from .exposure_manager import ExposureMixin
from .plume_manager import PlumeMixin
from .thresholds_manager import ThresholdsMixin
from .objectives_manager import ObjectivesMixin
from .sync_manager import SyncMixin


class IncidentDatabase(
    DatabaseConnection,
    AccessorsMixin,
    MapMarkerMixin,
    SpotReadingsMixin,
    AreaMixin,
    SpectralMixin,
    ExposureMixin,
    PlumeMixin,
    ThresholdsMixin,
    ObjectivesMixin,
    SyncMixin,
):
    """
    Manages the SQLite database for a specific incident.
    All domain methods are inherited from mixins — see individual files.
    """
    pass


__all__ = ["IncidentDatabase"]
