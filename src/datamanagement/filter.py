"""Filter management module for handling per-data-type filter files."""

import os
import json
import logging
from datetime import datetime
from typing import Dict, Any, Optional, List

logger = logging.getLogger(__name__)


VALID_DATA_TYPES = {
    "area",
    "spot",
    "spectral",
    "exposure",
    "plume",
}

DEFAULT_DATA_TYPE = "spot"

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
}


class FilterManager:
    """
    Manages filter operations including create, edit, read, and validation.

    Each data type has its own independent JSON filter file:

        meta/filters/area.json
        meta/filters/spot.json
        meta/filters/spectral.json
        meta/filters/exposure.json
        meta/filters/plume.json

    All JSON access is handled inside this class.
    """

    def __init__(
        self,
        incident_path: Optional[str] = None,
        data_type: Optional[str] = None,
    ):
        """
        Initialize the FilterManager.

        Args:
            incident_path: Path to the incident directory.
            data_type: One of area, spot, spectral, exposure, plume.
        """
        self.incident_path = incident_path
        self.data_type = self._normalize_data_type(data_type) or DEFAULT_DATA_TYPE
        self._filters_cache: Optional[Dict[str, Any]] = None

    # ─────────────────────────────────────────────────────────
    # INTERNAL HELPERS
    # ─────────────────────────────────────────────────────────

    @staticmethod
    def _normalize_data_type(data_type: Optional[str]) -> Optional[str]:
        """Normalize data type to a known lowercase value."""
        if data_type is None:
            return None

        normalized = str(data_type).strip().lower()

        if normalized in VALID_DATA_TYPES:
            return normalized

        logger.warning(
            "Unknown filter data_type '%s'. Defaulting to '%s'.",
            data_type,
            DEFAULT_DATA_TYPE,
        )

        return DEFAULT_DATA_TYPE

    def _default_filters_for(self, data_type: str) -> Dict[str, Any]:
        """Return default filters for a specific data type."""
        filters = DEFAULT_FILTERS.copy()
        filters["data_type"] = data_type

        # Non-area data types do not normally use aggregation intervals.
        if data_type in ("spot", "spectral", "exposure", "plume"):
            filters["interval"] = "Raw"

        # Exposure uses identifiers in the UI, but they are persisted under
        # the existing device/identifier key model.
        if data_type == "exposure":
            filters["group_by"] = "Device"

        return filters

    def _default_filters(self) -> Dict[str, Any]:
        """Return default filters for the current data type."""
        return self._default_filters_for(self.data_type)

    def _get_meta_dir(self) -> str:
        """Return the incident meta directory."""
        if not self.incident_path:
            raise ValueError("incident_path is not set")

        return os.path.join(self.incident_path, "meta")

    def _get_filters_dir(self) -> str:
        """Return the per-data-type filters directory."""
        return os.path.join(self._get_meta_dir(), "filters")

    def _ensure_filters_dir(self) -> None:
        """Ensure the filters directory exists."""
        os.makedirs(self._get_filters_dir(), exist_ok=True)

    def _get_filters_file_path(self) -> str:
        """
        Get the path to the filter file for the current data type.

        Example:
            meta/filters/area.json
        """
        if not self.incident_path:
            raise ValueError("incident_path is not set")

        if not self.data_type:
            raise ValueError("data_type is required for filter persistence")

        return os.path.join(self._get_filters_dir(), f"{self.data_type}.json")

    def _ensure_cache(self) -> None:
        """Ensure the filter cache has been loaded."""
        if self._filters_cache is None:
            self._filters_cache = self.load_filters()

    @staticmethod
    def _clean_data(obj: Any) -> Any:
        """Strip whitespace from keys and string values recursively."""
        if isinstance(obj, dict):
            return {
                k.strip(): FilterManager._clean_data(v)
                for k, v in obj.items()
            }

        if isinstance(obj, list):
            return [FilterManager._clean_data(elem) for elem in obj]

        if isinstance(obj, str):
            return obj.strip()

        return obj

    @staticmethod
    def _deserialize_datetimes(data: Dict[str, Any]) -> Dict[str, Any]:
        """Convert ISO datetime strings to datetime objects."""
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

    def _read_and_prepare_filters_file(self, file_path: str) -> Dict[str, Any]:
        """Read, clean, deserialize, and merge a filter file."""
        with open(file_path, "r", encoding="utf-8") as f:
            raw = json.load(f)

        raw = self._clean_data(raw)

        if not isinstance(raw, dict):
            raise ValueError("Filter file must contain a JSON object")

        raw = self._deserialize_datetimes(raw)

        merged = self._default_filters()
        merged.update(raw)

        # The manager's data type is authoritative for the file being read.
        merged["data_type"] = self.data_type

        return merged

    # ─────────────────────────────────────────────────────────
    # LOAD / SAVE
    # ─────────────────────────────────────────────────────────

    def load_filters(self) -> Dict[str, Any]:
        """
        Load filters for the current data type.

        Returns:
            Dictionary containing filter settings.
        """
        if not self.incident_path:
            self._filters_cache = self._default_filters()
            return self._filters_cache.copy()

        filters_file = self._get_filters_file_path()

        if not os.path.exists(filters_file):
            self._filters_cache = self._default_filters()
            return self._filters_cache.copy()

        try:
            self._filters_cache = self._read_and_prepare_filters_file(filters_file)
            return self._filters_cache.copy()
        except Exception as e:
            logger.error(
                "Failed to load filters from %s: %s",
                filters_file,
                e,
            )
            self._filters_cache = self._default_filters()
            return self._filters_cache.copy()

    def save_filters(self, filters: Optional[Dict[str, Any]] = None) -> bool:
        """
        Save filters for the current data type.

        Args:
            filters: Dictionary of filters to save. If None, uses cached filters.

        Returns:
            True if successful, False otherwise.
        """
        if not self.incident_path:
            logger.error("Cannot save filters: incident_path is not set")
            return False

        if filters is None:
            filters = self._filters_cache

        if filters is None:
            filters = self._default_filters()

        # Copy so callers do not accidentally mutate the saved dictionary.
        filters = dict(filters)

        # The manager's data type is authoritative.
        filters["data_type"] = self.data_type

        try:
            self._ensure_filters_dir()

            filters_file = self._get_filters_file_path()
            serializable_filters = self._serialize_datetimes(filters)

            with open(filters_file, "w", encoding="utf-8") as f:
                json.dump(serializable_filters, f, indent=2)

            self._filters_cache = filters
            return True

        except Exception as e:
            logger.error("Failed to save filters: %s", e)
            return False

    # ─────────────────────────────────────────────────────────
    # GENERIC GET/SET
    # ─────────────────────────────────────────────────────────

    def get_filter(self, key: str, default: Any = None) -> Any:
        """Get a specific filter value."""
        self._ensure_cache()
        return self._filters_cache.get(key, default)

    def set_filter(self, key: str, value: Any) -> None:
        """Set a specific filter value."""
        self._ensure_cache()
        self._filters_cache[key] = value

    def get_all_filters(self) -> Dict[str, Any]:
        """Get all filter settings."""
        self._ensure_cache()
        return self._filters_cache.copy()

    def set_all_filters(self, filters: Dict[str, Any]) -> None:
        """Set all filter settings at once."""
        self._ensure_cache()
        self._filters_cache.update(filters)

    def reset_to_defaults(self) -> None:
        """Reset in-memory filters to defaults for this data type."""
        self._filters_cache = self._default_filters()

    def create_default_filters(self, data_type: Optional[str] = None) -> Dict[str, Any]:
        """Create a new set of default filters."""
        normalized = self._normalize_data_type(data_type) or self.data_type
        return self._default_filters_for(normalized)

    # ─────────────────────────────────────────────────────────
    # TIME GETTERS/SETTERS
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
        stop_time: Optional[datetime],
    ) -> None:
        """Set both start and stop times."""
        self.set_start_time(start_time)
        self.set_stop_time(stop_time)

    # ─────────────────────────────────────────────────────────
    # DEVICE/IDENTIFIER GETTERS/SETTERS
    # ─────────────────────────────────────────────────────────

    def get_devices(self, data_type: Optional[str] = None) -> List[str]:
        """Get selected devices/identifiers for a data type."""
        target = self._normalize_data_type(data_type) or self.data_type
        device_key = DEVICE_KEY_MAP.get(target, "selected_area_devices")
        return self.get_filter(device_key, [])

    def set_devices(
        self,
        devices: List[str],
        data_type: Optional[str] = None,
    ) -> None:
        """Set selected devices/identifiers for a data type."""
        target = self._normalize_data_type(data_type) or self.data_type
        device_key = DEVICE_KEY_MAP.get(target, "selected_area_devices")
        self.set_filter(device_key, devices)

    # ─────────────────────────────────────────────────────────
    # SITE/LOCATION GETTERS/SETTERS
    # ─────────────────────────────────────────────────────────

    def get_locations(self) -> List[str]:
        """Get selected locations/sites."""
        return self.get_filter("selected_sites", [])

    def set_locations(self, locations: List[str]) -> None:
        """Set selected locations/sites."""
        self.set_filter("selected_sites", locations)

    # ─────────────────────────────────────────────────────────
    # ANALYTE GETTERS/SETTERS
    # ─────────────────────────────────────────────────────────

    def get_analytes(self) -> List[str]:
        """Get selected analytes."""
        return self.get_filter("selected_analytes", [])

    def set_analytes(self, analytes: List[str]) -> None:
        """Set selected analytes."""
        self.set_filter("selected_analytes", analytes)

    # ─────────────────────────────────────────────────────────
    # THRESHOLD GETTERS/SETTERS
    # ─────────────────────────────────────────────────────────

    def get_threshold_level(self) -> Optional[str]:
        """Get the threshold level."""
        return self.get_filter("threshold_level")

    def set_threshold_level(self, threshold_level: Optional[str]) -> None:
        """Set the threshold level."""
        self.set_filter("threshold_level", threshold_level)

    # ─────────────────────────────────────────────────────────
    # INTERVAL GETTERS/SETTERS
    # ─────────────────────────────────────────────────────────

    def get_interval(self) -> str:
        """Get the aggregation interval."""
        return self.get_filter("interval", "Raw")

    def set_interval(self, interval: str) -> None:
        """Set the aggregation interval."""
        self.set_filter("interval", interval)

    # ─────────────────────────────────────────────────────────
    # VALIDITY FLAGS
    # ─────────────────────────────────────────────────────────

    def get_only_valid(self) -> bool:
        """Get the only_valid flag."""
        return bool(self.get_filter("only_valid", False))

    def set_only_valid(self, only_valid: bool) -> None:
        """Set the only_valid flag."""
        self.set_filter("only_valid", bool(only_valid))

    # ─────────────────────────────────────────────────────────
    # FORM GETTERS/SETTERS
    # ─────────────────────────────────────────────────────────

    def get_form(self) -> Optional[str]:
        """Get the form type."""
        return self.get_filter("form")

    def set_form(self, form: Optional[str]) -> None:
        """Set the form type."""
        self.set_filter("form", form)

    # ─────────────────────────────────────────────────────────
    # OTHER GETTERS/SETTERS
    # ─────────────────────────────────────────────────────────

    def get_group_by(self) -> str:
        """Get the group-by setting."""
        return self.get_filter("group_by", "Device")

    def set_group_by(self, group_by: str) -> None:
        """Set the group-by setting."""
        self.set_filter("group_by", group_by)

    def get_data_type(self) -> Optional[str]:
        """Get the data type."""
        return self.data_type or self.get_filter("data_type")

    def set_data_type(self, data_type: str) -> None:
        """
        Set the data type value inside the filter dictionary.

        Note:
            With per-data-type filter files, the FilterManager's data_type
            determines which file is read/written. Changing this value here
            does not change the active filter file.
        """
        self.set_filter("data_type", data_type)

    def get_stats_pref(self) -> str:
        """Get the statistics preference."""
        return self.get_filter("stats_pref", "Mean")

    def set_stats_pref(self, stats_pref: str) -> None:
        """Set the statistics preference."""
        self.set_filter("stats_pref", stats_pref)

    # ─────────────────────────────────────────────────────────
    # VALIDATION
    # ─────────────────────────────────────────────────────────

    def validate_filters(self) -> bool:
        """Validate the current filter settings."""
        self._ensure_cache()

        required_fields = [
            "start_time",
            "stop_time",
            "interval",
            "group_by",
        ]

        for field in required_fields:
            if field not in self._filters_cache:
                logger.warning("Missing required filter field: %s", field)
                return False

        start_time = self._filters_cache.get("start_time")
        stop_time = self._filters_cache.get("stop_time")

        if start_time and stop_time:
            if isinstance(start_time, datetime) and isinstance(stop_time, datetime):
                if start_time > stop_time:
                    logger.warning("Start time is after stop time")
                    return False

        return True


# ─────────────────────────────────────────────────────────
# MODULE-LEVEL CONVENIENCE FUNCTIONS
# ─────────────────────────────────────────────────────────

def create_filter_manager(
    incident_path: Optional[str] = None,
    data_type: Optional[str] = None,
) -> FilterManager:
    """Factory function to create a FilterManager instance."""
    return FilterManager(incident_path, data_type)


def load_filters(
    incident_path: str,
    data_type: Optional[str] = None,
) -> Dict[str, Any]:
    """Convenience function to load filters from disk."""
    manager = FilterManager(incident_path, data_type)
    return manager.load_filters()


def save_filters(
    incident_path: str,
    filters: Dict[str, Any],
    data_type: Optional[str] = None,
) -> bool:
    """Convenience function to save filters to disk."""
    if data_type is None and isinstance(filters, dict):
        data_type = filters.get("data_type")

    manager = FilterManager(incident_path, data_type)
    return manager.save_filters(filters)
