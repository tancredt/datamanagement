import os
import re
import json
import shutil
import logging
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QFormLayout, QLineEdit, QCalendarWidget,
    QDialogButtonBox, QMessageBox, QTextEdit, QLabel
)
from PySide6.QtCore import Qt, QDate

logger = logging.getLogger(__name__)
DATE_FORMAT = "yyyy-MM-dd 00:00:00"
current_dir = os.path.dirname(os.path.abspath(__file__))


def setup_incident_logging(incident_path):
    """
    Creates a 'logs' directory inside the incident folder and configures 
    the root logger to write to a file within it.
    """
    if not incident_path:
        return

    logs_dir = os.path.join(incident_path, "logs")
    os.makedirs(logs_dir, exist_ok=True)

    log_file_path = os.path.join(logs_dir, "incident.log")
    abs_log_path = os.path.abspath(log_file_path)

    root_logger = logging.getLogger()
    root_logger.setLevel(logging.DEBUG)

    # Prevent adding duplicate file handlers if called multiple times
    for handler in root_logger.handlers:
        if isinstance(handler, logging.FileHandler) and os.path.abspath(handler.baseFilename) == abs_log_path:
            return

    fh = logging.FileHandler(log_file_path, mode='a', encoding='utf-8')
    fh.setLevel(logging.DEBUG)
    
    formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    fh.setFormatter(formatter)

    root_logger.addHandler(fh)

    # Ensure there's a console handler so you still see logs in the terminal
    if not any(isinstance(h, logging.StreamHandler) and not isinstance(h, logging.FileHandler) for h in root_logger.handlers):
        ch = logging.StreamHandler()
        ch.setLevel(logging.INFO)
        ch.setFormatter(formatter)
        root_logger.addHandler(ch)

    root_logger.info(f"Logging initialized for incident: {incident_path}")


class IncidentDialog(QDialog):
    def __init__(self, parent=None, incident_data=None):
        super().__init__(parent)
        self.is_editing = incident_data is not None
        self._incident_data = incident_data
        self._created_path = None

        self.setWindowTitle("Edit Incident" if self.is_editing else "New Incident")
        self.setMinimumWidth(480)

        self._setup_ui()
        if self.is_editing:
            self._populate_data(incident_data)
            self.lbl_label.setEnabled(False)
            self.lbl_label.setToolTip("Label cannot be changed after incident creation.")
        else:
            self.cal_date.setSelectedDate(QDate.currentDate())

        self._connect_signals()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        form = QFormLayout()

        self.lbl_label = QLineEdit()
        self.lbl_label.setPlaceholderText("Letters, numbers, underscores only")

        self.txt_call_no = QLineEdit()
        self.txt_call_no.setPlaceholderText("e.g., INC-2026-001 or Dispatch #")

        self.cal_date = QCalendarWidget()

        self.txt_company = QLineEdit()
        self.txt_company.setPlaceholderText("Operating company")

        self.txt_address = QLineEdit()
        self.txt_address.setPlaceholderText("Full site address")

        self.txt_coords = QLineEdit()
        self.txt_coords.setPlaceholderText("geo:lat,lon?z=19")

        form.addRow("Label:", self.lbl_label)
        form.addRow("Call No.:", self.txt_call_no)
        form.addRow("Commencement Date:", self.cal_date)
        form.addRow("Company:", self.txt_company)
        form.addRow("Address:", self.txt_address)
        form.addRow("Coordinates:", self.txt_coords)

        layout.addLayout(form)

        layout.addSpacing(10)
        lbl_comments = QLabel("Comments:")
        layout.addWidget(lbl_comments)
        
        self.txt_comments = QTextEdit()
        self.txt_comments.setPlaceholderText("Additional notes, hazards, or context...")
        self.txt_comments.setMaximumHeight(90)
        layout.addWidget(self.txt_comments)

        self.btn_box = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        layout.addWidget(self.btn_box)

    def _parse_coordinates(self, coord_str: str):
        coord_str = coord_str.strip()
        if not coord_str: return None, None
        match = re.match(r'geo:\s*(-?\d+(?:\.\d+)?)\s*,\s*(-?\d+(?:\.\d+)?)', coord_str)
        if not match: raise ValueError("Invalid format. Use: geo:lat,lon")
        lat, lon = float(match.group(1)), float(match.group(2))
        if not (-90 <= lat <= 90): raise ValueError("Latitude must be between -90 and 90.")
        if not (-180 <= lon <= 180): raise ValueError("Longitude must be between -180 and 180.")
        return lat, lon

    def _populate_data(self, data):
        self.lbl_label.setText(data.get("label", ""))
        self.txt_call_no.setText(data.get("call_no", ""))
        self.txt_company.setText(data.get("company", ""))
        self.txt_address.setText(data.get("address", ""))

        lat = data.get("latitude")
        lon = data.get("longitude")
        if lat is not None and lon is not None:
            self.txt_coords.setText(f"geo:{lat},{lon}")

        if "commencement_date" in data:
            date_str = str(data["commencement_date"])
            qdate = QDate.fromString(date_str.split(" ")[0], "yyyy-MM-dd")
            if qdate.isValid():
                self.cal_date.setSelectedDate(qdate)

        self.txt_comments.setPlainText(data.get("comments", ""))

    def _connect_signals(self):
        self.btn_box.accepted.connect(self._validate_and_accept)
        self.btn_box.rejected.connect(self.reject)

    def _validate_and_accept(self):
        label = self.lbl_label.text().strip()
        if not label:
            QMessageBox.warning(self, "Validation Error", "Incident Label is required.")
            return
        if not re.match(r'^[A-Za-z0-9_]+$', label):
            QMessageBox.warning(self, "Validation Error", "Label can only contain letters, numbers, and underscores.")
            return

        coords_str = self.txt_coords.text().strip()
        if coords_str:
            try: 
                self._parse_coordinates(coords_str)
            except ValueError as e:
                QMessageBox.warning(self, "Validation Error", str(e))
                return

        base_dir = "../../incidents"
        incident_dir = os.path.join(base_dir, label)

        if not self.is_editing:
            if os.path.exists(incident_dir):
                QMessageBox.warning(self, "Directory Exists", f"An incident folder for '{label}' already exists.")
                return
            try:
                # Added "logs" to the directory creation list
                dirs = [os.path.join(incident_dir, d) for d in ["meta", "mapping", 
                                                                  "validations",
                                                                  "data/export_csv",
                                                                  "data/realtime", "data/processed",
                                                                  "data/exposures", "reports", "logs", "plumes"]]
                os.makedirs(incident_dir, exist_ok=True)
                for d in dirs: 
                    os.makedirs(d, exist_ok=False)
                
                # Setup logging for the newly created incident
                setup_incident_logging(incident_dir)
                logger.info(f"Incident created: {label} at {os.path.abspath(incident_dir)}")
                
            except Exception as e:
                QMessageBox.critical(self, "File System Error", f"Failed to create directories:\n{e}")
                logger.error(f"Failed to create directories for incident '{label}': {e}")
                return
        else:
            self._created_path = self._incident_data.get("incident_path", incident_dir)
            if not os.path.exists(self._created_path):
                os.makedirs(self._created_path, exist_ok=True)
            logger.info(f"Incident edited: {label}")

        self._created_path = incident_dir
        meta_dir = os.path.join(self._created_path, "meta")
        try:
            os.makedirs(meta_dir, exist_ok=True)
            with open(os.path.join(meta_dir, "incident.json"), 'w', encoding='utf-8') as f:
                json.dump(self.get_data(), f, indent=2, ensure_ascii=False)
            logger.info(f"Incident metadata saved for: {label}")
            
            # Copy thresholds.json from static/lists to the incident's meta directory
            static_thresholds_file = os.path.normpath(os.path.join(current_dir, '..', 'static', 'lists', 'thresholds.json'))
            incident_thresholds_file = os.path.join(meta_dir, "thresholds.json")
            if os.path.exists(static_thresholds_file) and not os.path.exists(incident_thresholds_file):
                shutil.copy(static_thresholds_file, incident_thresholds_file)
                logger.info(f"Thresholds file copied to: {incident_thresholds_file}")
        except Exception as e:
            QMessageBox.critical(self, "File System Error", f"Failed to save incident.json:\n{e}")
            logger.error(f"Failed to save incident.json for '{label}': {e}")
            return
            
        self.accept()

    def get_data(self) -> dict:
        coords_str = self.txt_coords.text().strip()
        lat, lon = (None, None) if not coords_str else self._parse_coordinates(coords_str)
        
        data = {
            "label": self.lbl_label.text().strip(),
            "call_no": self.txt_call_no.text().strip(),
            "commencement_date": self.cal_date.selectedDate().toString("yyyy-MM-dd") + " 00:00:00",
            "company": self.txt_company.text().strip(),
            "address": self.txt_address.text().strip(),
            "latitude": lat,
            "longitude": lon,
            "comments": self.txt_comments.toPlainText().strip()
        }
        if self._created_path:
            data["incident_path"] = os.path.abspath(self._created_path)
        return data
