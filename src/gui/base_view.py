from PySide6.QtWidgets import QWidget

class DataView(QWidget):
    """
    Abstract base class for all data views.
    Ensures a consistent interface for UI setup, data updating, and exporting.
    """
    def __init__(self, parent=None):
        super().__init__(parent)
        
    def _setup_ui(self):
        """Must be implemented by subclasses to build the specific UI."""
        raise NotImplementedError("Subclasses must implement _setup_ui()")
        
    def update_data(self, *args, **kwargs):
        """Must be implemented by subclasses to receive and process new data."""
        raise NotImplementedError("Subclasses must implement update_data()")
        
    def export(self):
        """Must be implemented by subclasses to handle exporting the current view."""
        raise NotImplementedError("Subclasses must implement export()")
        
    def clear_view(self):
        """Optional: Override to reset the view to its initial empty state."""
        pass
