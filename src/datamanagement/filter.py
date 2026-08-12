"""Filter management module for handling last_filters.json operations."""

import os
import json
import logging
from datetime import datetime
from typing import Dict, Any, Optional, List

logger = logging.getLogger(__name__)

# Mapping data types to their specific device/identifier keys in last_filters.json
DEVICE_KEY_MAP = {
    "area": "selected_area_devices",
    "spot": "selected_spot_devices",
    "spectral": "selected_spectral_devices",
    "exposure": "selected_exposure_identifiers",
}

DEFAULT_FILTERS = {
    "start_time": None,
    "stop_time": None,
    "interval": "Raw",
    "group_by": "Device",
    "only_valid": False,
    "selected_sites": [],
    "selected_area_devices": [],
    "selected_spot_devices": [],
    "selected_spectral_devices": [],
    "selected_exposure_identifiers": [],
    "selected_analytes": [],
    "threshold_level": None,
    "data_type": None,
    "stats_pref": "Mean",
    "form": None,
    "is_valid": True,
}


class FilterManager:
    """
    Manages filter operations including create, edit, read, and validation.

    Handles the last_filters.json file and provides getter/setter functions.
    """

    def __init__(self, incident_path: Optional[str] = None):
        """
        Initialize the FilterManager.

        Args:
            incident_path: Path to the incident directory containing meta/last_filters.json
        """
        self.incident_path = incident_path
        self._filters_cache: Optional[Dict[str, Any]] = None

    def _get_filters_file_path(self) -> str:
        """Get the path to the last_filters.json file."""
        if not self.incident_path:
            raise ValueError("incident_path is not set")

        meta_dir = os.path.join(self.incident_path, "meta")
        return os.path.join(meta_dir, "last_filters.json")

    def _ensure_meta_dir(self) -> None:
        """Ensure the meta directory exists."""
        if not self.incident_path:
            raise ValueError("incident_path is not set")

        meta_dir = os.path.join(self.incident_path, "meta")
        os.makedirs(meta_dir, exist_ok=True)

    @staticmethod
    def _clean_data(obj: Any) -> Any:
        """Strip whitespace from keys and string values recursively."""
        if isinstance(obj, dict):
            return {k.strip(): FilterManager._clean_data(v) for k, v in obj.items()}
        elif isinstance(obj, list):
            return [FilterManager._clean_data(elem) for elem in obj]
        elif isinstance(obj, str):
            return obj.strip()
        return obj

    @staticmethod
    def _deserialize_datetimes(data: Dict[str, Any]) -> Dict[str, Any]:
        """Convert ISO format datetime strings to datetime objects."""
        result = data.copy()

        for key in ("start_time", "stop_time"):
            val = result.get(key)
            if isinstance(val, str):
                try:
                    result[key] = datetime.fromisoformat(val)
                except (ValueError, TypeError):
                    result[key] = None

        return result

    @staticmethod
    def _serialize_datetimes(data: Dict[str, Any]) -> Dict[str, Any]:
        """Convert datetime objects to ISO format strings."""
        result = data.copy()

        for key in ("start_time", "stop_time"):
            val = result.get(key)
            if isinstance(val, datetime):
                result[key] = val.isoformat()

        return result

    def load_filters(self) -> Dict[str, Any]:
        """
        Load filters from last_filters.json file.

        Returns:
            Dictionary containing filter settings, or default filters if file doesn't exist
        """
        if not self.incident_path:
            self._filters_cache = DEFAULT_FILTERS.copy()
            return self._filters_cache.copy()

        filters_file = self._get_filters_file_path()

        if not os.path.exists(filters_file):
            self._filters_cache = DEFAULT_FILTERS.copy()
            return self._filters_cache.copy()

        try:
            with open(filters_file, "r", encoding="utf-8") as f:
                raw = json.load(f)

            raw = self._clean_data(raw)

            if not isinstance(raw, dict):
                raise ValueError("last_filters.json must contain a JSON object")

            raw = self._deserialize_datetimes(raw)

            merged = DEFAULT_FILTERS.copy()
            merged.update(raw)

            self._filters_cache = merged
            return self._filters_cache.copy()

        except Exception as e:
            logger.error(f"Failed to load filters from disk: {e}")
            self._filters_cache = DEFAULT_FILTERS.copy()
            return self._filters_cache.copy()

    def save_filters(self, filters: Optional[Dict[str, Any]] = None) -> bool:
        """
        Save filters to last_filters.json file.

        Args:
            filters: Dictionary of filters to save. If None, uses cached filters.

        Returns:
            True if successful, False otherwise
        """
        if not self.incident_path:
            logger.error("Cannot save filters: incident_path is not set")
            return False

        if filters is None:
            filters = self._filters_cache

        if filters is None:
            logger.error("No filters to save")
            return False

        try:
            self._ensure_meta_dir()
            filters_file = self._get_filters_file_path()

            serializable_filters = self._serialize_datetimes(filters)

            with open(filters_file, "w", encoding="utf-8") as f:
                json.dump(serializable_filters, f, indent=2)

            self._filters_cache = filters
            return True

        except Exception as e:
            logger.error(f"Failed to save filters: {e}")
            return False

    def get_filter(self, key: str, default: Any = None) -> Any:
        """
        Get a specific filter value.

        Args:
            key: The filter key to retrieve
            default: Default value if key doesn't exist

        Returns:
            The filter value or default
        """
        if self._filters_cache is None:
            self.load_filters()

        return self._filters_cache.get(key, default)

    def set_filter(self, key: str, value: Any) -> None:
        """
        Set a specific filter value.

        Args:
            key: The filter key to set
            value: The value to set
        """
        if self._filters_cache is None:
            self.load_filters()

        self._filters_cache[key] = value

    # ─────────────────────────────────────────────────────────
    # Time getters/setters
    # ─────────────────────────────────────────────────────────

    def get_start_time(self) -> Optional[datetime]:
        """Get the start time filter."""
        return self.get_filter("start_time")

    def set_start_time(self, start_time: Optional[datetime]) -> None:
        """Set the start time filter."""
        self.set_filter("start_time", start_time)

    def get_stop_time(self) -> Optional[datetime]:
        """Get the stop time filter."""
        return self.get_filter("stop_time")

    def set_stop_time(self, stop_time: Optional[datetime]) -> None:
        """Set the stop time filter."""
        self.set_filter("stop_time", stop_time)

    def get_time_range(self) -> tuple:
        """Get both start and stop times."""
        return self.get_start_time(), self.get_stop_time()

    def set_time_range(
        self,
        start_time: Optional[datetime],
        stop_time: Optional[datetime]
    ) -> None:
        """Set both start and stop times."""
        self.set_start_time(start_time)
        self.set_stop_time(stop_time)

    # ─────────────────────────────────────────────────────────
    # Device getters/setters
    # ─────────────────────────────────────────────────────────

    def get_devices(self, data_type: Optional[str] = None) -> List[str]:
        """
        Get selected devices for a specific data type.

        Args:
            data_type: The data type (area, spot, spectral, exposure)

        Returns:
            List of selected device identifiers
        """
        if data_type is None:
            data_type = self.get_data_type()

        device_key = DEVICE_KEY_MAP.get(data_type, "selected_area_devices")
        return self.get_filter(device_key, [])

    def set_devices(
        self,
        devices: List[str],
        data_type: Optional[str] = None
    ) -> None:
        """
        Set selected devices for a specific data type.

        Args:
            devices: List of device identifiers to select
            data_type: The data type (area, spot, spectral, exposure)
        """
        if data_type is None:
            data_type = self.get_data_type()

        device_key = DEVICE_KEY_MAP.get(data_type, "selected_area_devices")
        self.set_filter(device_key, devices)

    # ─────────────────────────────────────────────────────────
    # Location/Site getters/setters
    # ─────────────────────────────────────────────────────────

    def get_locations(self) -> List[str]:
        """Get selected locations/sites."""
        return self.get_filter("selected_sites", [])

    def set_locations(self, locations: List[str]) -> None:
        """Set selected locations/sites."""
        self.set_filter("selected_sites", locations)

    # ─────────────────────────────────────────────────────────
    # Analyte getters/setters
    # ─────────────────────────────────────────────────────────

    def get_analytes(self) -> List[str]:
        """Get selected analytes."""
        return self.get_filter("selected_analytes", [])

    def set_analytes(self, analytes: List[str]) -> None:
        """Set selected analytes."""
        self.set_filter("selected_analytes", analytes)

    # ─────────────────────────────────────────────────────────
    # Threshold getters/setters
    # ─────────────────────────────────────────────────────────

    def get_threshold_level(self) -> Optional[str]:
        """Get the threshold level."""
        return self.get_filter("threshold_level")

    def set_threshold_level(self, threshold_level: Optional[str]) -> None:
        """Set the threshold level."""
        self.set_filter("threshold_level", threshold_level)

    # ─────────────────────────────────────────────────────────
    # Interval getters/setters
    # ─────────────────────────────────────────────────────────

    def get_interval(self) -> str:
        """Get the aggregation interval."""
        return self.get_filter("interval", "Raw")

    def set_interval(self, interval: str) -> None:
        """Set the aggregation interval."""
        self.set_filter("interval", interval)

    # ─────────────────────────────────────────────────────────
    # Validity getters/setters
    # ─────────────────────────────────────────────────────────

    def get_only_valid(self) -> bool:
        """
        Get the only_valid flag.

        This flag controls whether only valid/non-invalidated readings
        should be shown or analyzed.
        """
        return bool(self.get_filter("only_valid", False))

    def set_only_valid(self, only_valid: bool) -> None:
        """
        Set the only_valid flag.

        Args:
            only_valid: True to show only valid readings, False otherwise.
        """
        self.set_filter("only_valid", bool(only_valid))

    def get_is_valid(self) -> bool:
        """
        Get the is_valid flag.

        This flag represents whether the current filter set itself is
        considered valid, not whether only valid readings should be shown.
        """
        return bool(self.get_filter("is_valid", True))

    def set_is_valid(self, is_valid: bool) -> None:
        """
        Set the is_valid flag.

        Args:
            is_valid: True if the current filter set is valid, False otherwise.
        """
        self.set_filter("is_valid", bool(is_valid))

    # Backward-compatible aliases.
    #
    # Older code may have used get_is_valid_flag()/set_is_valid_flag().
    # Those names are retained as aliases for the is_valid flag.
    def get_is_valid_flag(self) -> bool:
        """Deprecated alias for get_is_valid()."""
        return self.get_is_valid()

    def set_is_valid_flag(self, is_valid: bool) -> None:
        """Deprecated alias for set_is_valid()."""
        self.set_is_valid(is_valid)

    # ─────────────────────────────────────────────────────────
    # Form getters/setters (for plumes)
    # ─────────────────────────────────────────────────────────

    def get_form(self) -> Optional[str]:
        """Get the form type (e.g., Table, Summary Map)."""
        return self.get_filter("form")

    def set_form(self, form: Optional[str]) -> None:
        """Set the form type."""
        self.set_filter("form", form)

    # ─────────────────────────────────────────────────────────
    # Other getters/setters
    # ─────────────────────────────────────────────────────────

    def get_group_by(self) -> str:
        """Get the group by setting."""
        return self.get_filter("group_by", "Device")

    def set_group_by(self, group_by: str) -> None:
        """Set the group by setting."""
        self.set_filter("group_by", group_by)

    def get_data_type(self) -> Optional[str]:
        """Get the data type."""
        return self.get_filter("data_type")

    def set_data_type(self, data_type: str) -> None:
        """Set the data type."""
        self.set_filter("data_type", data_type)

    def get_stats_pref(self) -> str:
        """Get the statistics preference."""
        return self.get_filter("stats_pref", "Mean")

    def set_stats_pref(self, stats_pref: str) -> None:
        """Set the statistics preference."""
        self.set_filter("stats_pref", stats_pref)

    # ─────────────────────────────────────────────────────────
    # Convenience methods
    # ─────────────────────────────────────────────────────────

    def get_all_filters(self) -> Dict[str, Any]:
        """Get all filter settings."""
        if self._filters_cache is None:
            self.load_filters()

        return self._filters_cache.copy() if self._filters_cache else DEFAULT_FILTERS.copy()

    def set_all_filters(self, filters: Dict[str, Any]) -> None:
        """Set all filter settings at once."""
        if self._filters_cache is None:
            self.load_filters()

        self._filters_cache.update(filters)

    def reset_to_defaults(self) -> None:
        """Reset all filters to default values."""
        self._filters_cache = DEFAULT_FILTERS.copy()

    def validate_filters(self) -> bool:
        """
        Validate the current filter settings.

        Returns:
            True if filters are valid, False otherwise
        """
        if self._filters_cache is None:
            self.load_filters()

        required_fields = ["start_time", "stop_time", "interval", "group_by"]

        for field in required_fields:
            if field not in self._filters_cache:
                logger.warning(f"Missing required filter field: {field}")
                return False

        start_time = self._filters_cache.get("start_time")
        stop_time = self._filters_cache.get("stop_time")

        if start_time and stop_time:
            if isinstance(start_time, datetime) and isinstance(stop_time, datetime):
                if start_time > stop_time:
                    logger.warning("Start time is after stop time")
                    return False

        return True

    def create_default_filters(self, data_type: Optional[str] = None) -> Dict[str, Any]:
        """
        Create a new set of default filters.

        Args:
            data_type: Optional data type to set in the defaults

        Returns:
            Dictionary of default filters
        """
        filters = DEFAULT_FILTERS.copy()

        if data_type:
            filters["data_type"] = data_type

        return filters


def create_filter_manager(incident_path: Optional[str] = None) -> FilterManager:
    """
    Factory function to create a FilterManager instance.

    Args:
        incident_path: Path to the incident directory

    Returns:
        FilterManager instance
    """
    return FilterManager(incident_path)


def load_filters(incident_path: str) -> Dict[str, Any]:
    """
    Convenience function to load filters from disk.

    Args:
        incident_path: Path to the incident directory

    Returns:
        Dictionary of filter settings
    """
    manager = FilterManager(incident_path)
    return manager.load_filters()


def save_filters(incident_path: str, filters: Dict[str, Any]) -> bool:
    """
    Convenience function to save filters to disk.

    Args:
        incident_path: Path to the incident directory
        filters: Dictionary of filter settings to save

    Returns:
        True if successful, False otherwise
    """
    manager = FilterManager(incident_path)
    return manager.save_filters(filters)
