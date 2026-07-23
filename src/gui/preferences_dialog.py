import os
import json
import logging
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QFormLayout, QLineEdit, 
    QDialogButtonBox, QMessageBox
)
from PySide6.QtGui import QDoubleValidator

logger = logging.getLogger(__name__)

class PreferencesDialog(QDialog):
    """Dialog for managing incident preferences."""
    def __init__(self, parent, incident_path):
        super().__init__(parent)
        self.incident_path = incident_path
        self.preferences_file = os.path.join(incident_path, "meta", "preferences.json")
        
        self.setWindowTitle("Preferences")
        self.resize(350, 150)
        
        # Default values
        self.voc_correction = 1.0
        self.lel_correction = 1.0
        
        self._load_preferences()
        self._setup_ui()
        
    def _load_preferences(self):
        """Load preferences from the JSON file if it exists."""
        if os.path.exists(self.preferences_file):
            try:
                with open(self.preferences_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    prefs = data.get("preferences", {})
                    self.voc_correction = float(prefs.get("voc_correction", 1))
                    self.lel_correction = float(prefs.get("lel_correction", 1))
            except Exception as e:
                logger.error(f"Failed to load preferences: {e}")

    def _setup_ui(self):
        """Set up the dialog UI."""
        layout = QVBoxLayout(self)
        
        form = QFormLayout()
        
        # Validator to ensure only numerical input is accepted
        double_validator = QDoubleValidator(0.0, 99999.0, 4, self)
        double_validator.setNotation(QDoubleValidator.StandardNotation)
        
        self.txt_voc = QLineEdit(str(self.voc_correction))
        self.txt_voc.setValidator(double_validator)
        form.addRow("VOC Correction:", self.txt_voc)
        
        self.txt_lel = QLineEdit(str(self.lel_correction))
        self.txt_lel.setValidator(double_validator)
        form.addRow("LEL Correction:", self.txt_lel)
        
        layout.addLayout(form)
        layout.addSpacing(10)
        
        self.btn_box = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        self.btn_box.accepted.connect(self._save_and_accept)
        self.btn_box.rejected.connect(self.reject)
        layout.addWidget(self.btn_box)

    def _save_and_accept(self):
        """Validate input and save to JSON."""
        voc_text = self.txt_voc.text().strip()
        lel_text = self.txt_lel.text().strip()
        
        try:
            voc_val = float(voc_text)
            lel_val = float(lel_text)
        except ValueError:
            QMessageBox.warning(self, "Invalid Input", "Please enter valid numerical values.")
            return
            
        data = {
            "preferences": {
                "voc_correction": voc_val,
                "lel_correction": lel_val
            }
        }
        
        try:
            os.makedirs(os.path.dirname(self.preferences_file), exist_ok=True)
            with open(self.preferences_file, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2)
            self.accept()
        except Exception as e:
            logger.error(f"Failed to save preferences: {e}")
            QMessageBox.critical(self, "Error", f"Failed to save preferences:\n{e}")
