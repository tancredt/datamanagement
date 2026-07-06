import os
import json
import logging
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QComboBox,
    QTableWidget, QTableWidgetItem, QPushButton, QDialogButtonBox,
    QMessageBox, QHeaderView, QFormLayout, QDateTimeEdit, QLineEdit,
    QCheckBox, QProgressDialog, QLabel, QScrollArea, QWidget
)
from PySide6.QtCore import Qt, QDateTime, QThread, Signal
from datamanagement.choices import get_available_devices

logger = logging.getLogger(__name__)
DATE_FORMAT = "yyyy-MM-dd HH:mm:ss"
INFINITY_DATE = QDateTime(9999, 12, 31, 23, 59, 59)

class AnalyteSelectionWidget(QWidget):
    def __init__(self, analytes, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(5)

        header = QHBoxLayout()
        header.addWidget(QLabel("<b>Invalidate Analytes *:</b>"))
        self.toggle_btn = QPushButton("Select All")
        self.toggle_btn.setFixedSize(90, 26)
        self.toggle_btn.clicked.connect(self._toggle_all)
        header.addWidget(self.toggle_btn)
        header.addStretch()
        layout.addLayout(header)
        
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setMaximumHeight(120)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        
        self.container = QWidget()
        self.container_layout = QVBoxLayout(self.container)
        self.container_layout.setContentsMargins(5, 5, 5, 5)
        self.container_layout.setSpacing(4)
        self.scroll.setWidget(self.container)
        layout.addWidget(self.scroll)
        
        self.checkboxes = []
        for analyte in analytes:
            cb = QCheckBox(analyte)
            cb.stateChanged.connect(self._update_toggle_button)
            self.container_layout.addWidget(cb)
            self.checkboxes.append(cb)
        self._update_toggle_button()
        
    def _toggle_all(self):
        all_checked = len(self.checkboxes) > 0 and all(cb.isChecked() for cb in self.checkboxes)
        for cb in self.checkboxes:
            cb.setChecked(not all_checked)
        self._update_toggle_button()
        
    def _update_toggle_button(self):
        all_checked = len(self.checkboxes) > 0 and all(cb.isChecked() for cb in self.checkboxes)
        self.toggle_btn.setText("Unselect All" if all_checked else "Select All")
        
    def get_selected_analytes(self):
        return [cb.text() for cb in self.checkboxes if cb.isChecked()]
        
    def set_selected_analytes(self, analytes):
        for cb in self.checkboxes:
            cb.setChecked(cb.text() in analytes)

class AddDeviceValidationDialog(QDialog):
    def __init__(self, parent=None, initial_data=None, existing_validations=None, exclude_index=None, incident_path=None):
        super().__init__(parent)
        self.incident_path = incident_path
        self.initial_data = initial_data
        self.existing_validations = existing_validations or []
        self.exclude_index = exclude_index

        self.setWindowTitle("Edit Validation" if initial_data else "Add Validation")
        self.setMinimumWidth(450)
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(10)
        layout.setContentsMargins(16, 16, 16, 16)
         
        form = QFormLayout()
        form.setSpacing(8)
        form.setLabelAlignment(Qt.AlignRight)
        self.cmb_device = QComboBox()
        self.cmb_device.setEditable(True)
        self.cmb_device.addItems(get_available_devices(self.incident_path, data_type="area"))
        form.addRow("Device *: ", self.cmb_device)
        
        self.analyte_selector = AnalyteSelectionWidget(self._load_available_analytes())
        form.addRow("Analytes *: ", self.analyte_selector)
        
        self.dt_start = QDateTimeEdit()
        self.dt_start.setCalendarPopup(True)
        self.dt_start.setDateTime(QDateTime.currentDateTime())
        self.dt_start.setDisplayFormat(DATE_FORMAT)
        self.dt_start.setMinimumHeight(28)
        form.addRow("Start *: ", self.dt_start)
        
        self.chk_has_stop = QCheckBox("Stopped")
        self.dt_stop = QDateTimeEdit()
        self.dt_stop.setCalendarPopup(True)
        self.dt_stop.setDateTime(QDateTime.currentDateTime())
        self.dt_stop.setDisplayFormat(DATE_FORMAT)
        self.dt_stop.setMinimumHeight(28)
        self.dt_stop.setEnabled(False)
        
        self.txt_comment = QLineEdit()
        self.txt_comment.setPlaceholderText("Optional note...")
        self.txt_comment.setMinimumHeight(28)
        self.txt_comment.setEnabled(False)
        
        self.chk_has_stop.toggled.connect(self.dt_stop.setEnabled)
        self.chk_has_stop.toggled.connect(self.txt_comment.setEnabled)
        
        stop_layout = QHBoxLayout()
        stop_layout.addWidget(self.chk_has_stop)
        stop_layout.addWidget(self.dt_stop)
        stop_layout.addStretch()
        form.addRow("Stop: ", stop_layout)
        form.addRow("Comment: ", self.txt_comment)
        
        if self.initial_data:
            self.cmb_device.setCurrentText(self.initial_data.get("device", ""))
            self.analyte_selector.set_selected_analytes(self.initial_data.get("analytes", []))
            dt_start = QDateTime.fromString(self.initial_data.get("start", ""), DATE_FORMAT)
            if dt_start.isValid(): self.dt_start.setDateTime(dt_start)
            stop_val = self.initial_data.get("stop", "")
            if stop_val:
                self.chk_has_stop.setChecked(True)
                dt_stop = QDateTime.fromString(stop_val, DATE_FORMAT)
                if dt_stop.isValid(): self.dt_stop.setDateTime(dt_stop)
            self.txt_comment.setText(self.initial_data.get("comment", ""))
            
        layout.addLayout(form)
        layout.addSpacing(10)
        btn_box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        btn_box.setMinimumHeight(34)
        layout.addWidget(btn_box)
        btn_box.rejected.connect(self.reject)
        btn_box.button(QDialogButtonBox.Ok).clicked.connect(self._validate_and_accept)

    def _load_available_devices(self):
        devices = []
        current_dir = os.path.dirname(os.path.abspath(__file__))
        json_path = os.path.normpath(os.path.join(current_dir, '..', 'static', 'lists', 'area_devices.json'))
        
        if os.path.exists(json_path):
            try:
                with open(json_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    devices_list = data.get("devices", [])
                    for dev in devices_list:
                        label = dev.get("label", "")
                        if label:
                            devices.append(str(label).strip())
            except Exception as e:
                logger.warning(f"Failed to load devices from {json_path}: {e}")
                
        return sorted(list(set(devices)))

    def _load_available_analytes(self):
        analytes = []
        if self.incident_path:
            current_dir = os.path.dirname(os.path.abspath(__file__))
            analyte_config_path = os.path.normpath(os.path.join(current_dir, '..', 'static', 'lists', 'analytes.json'))
            if os.path.exists(analyte_config_path):
                try:
                    with open(analyte_config_path, 'r', encoding='utf-8') as f:
                        analyte_config = json.load(f)
                        analytes_list = analyte_config.get("analytes", analyte_config.get("analytes ", []))
                        for analyte in analytes_list:
                            clean_analyte = {k.strip(): str(v).strip() for k, v in analyte.items()}
                            name = clean_analyte.get("name")
                            if name:
                                analytes.append(name)
                except Exception as e:
                    logger.warning(f"Failed to load analytes: {e}")
        return sorted(list(set(analytes)))

    def _validate_and_accept(self):
        device = self.cmb_device.currentText().strip()
        if not device:
            QMessageBox.warning(self, "Validation Error", "Device is mandatory.")
            return
            
        if not self.analyte_selector.get_selected_analytes():
            QMessageBox.warning(self, "Validation Error", "Please select at least one analyte to invalidate.")
            return
        
        start_dt = self.dt_start.dateTime()
        if self.chk_has_stop.isChecked():
            stop_dt = self.dt_stop.dateTime()
            if start_dt >= stop_dt:
                QMessageBox.warning(self, "Validation Error", "Start datetime cannot be after or equal to Stop datetime.")
                return
        self.accept()

    def get_data(self):
        return {
            "analytes": self.analyte_selector.get_selected_analytes(),
            "device": self.cmb_device.currentText().strip(),
            "start": self.dt_start.dateTime().toString(DATE_FORMAT),
            "stop": self.dt_stop.dateTime().toString(DATE_FORMAT) if self.chk_has_stop.isChecked() else "",
            "comment": self.txt_comment.text().strip() if self.chk_has_stop.isChecked() else ""
        }

class ProcessingWorker(QThread):
    finished_signal = Signal()
    error_signal = Signal(str)
    def __init__(self, incident_path):
        super().__init__()
        self.incident_path = incident_path
    def run(self):
        try:
            from datamanagement.importer import update_validations
            update_validations(self.incident_path)
            self.finished_signal.emit()
        except Exception as e:
            self.error_signal.emit(str(e))

class DeviceValidationsDialog(QDialog):
    def __init__(self, parent=None, incident_path=None):
        super().__init__(parent)
        self.incident_path = incident_path
        self.validations_dir = os.path.join(incident_path, "mapping")
        self.device_validations_json = os.path.join(self.validations_dir, "device_validations.json")
        self.all_validations = []
        self.worker = None
        self.progress = None

        self.setWindowTitle("Device Validations Manager")
        self.resize(850, 550)
        self._load_data()
        self._setup_ui()
        self._connect_signals()
        self._update_table()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(12)
        layout.setContentsMargins(16, 16, 16, 16)
        
        self.table = QTableWidget()
        self.table.setColumnCount(5)
        self.table.setHorizontalHeaderLabels(["Analytes", "Device", "Start", "Stop", "Comment"])
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(4, QHeaderView.Stretch)
        self.table.setAlternatingRowColors(True)
        layout.addWidget(self.table)
        
        btn_row = QHBoxLayout()
        self.btn_add = QPushButton("Add Validation...")
        self.btn_add.setMinimumHeight(32)
        btn_row.addWidget(self.btn_add)
        
        self.btn_edit = QPushButton("Edit Selected...")
        self.btn_edit.setMinimumHeight(32)
        self.btn_edit.setEnabled(False)
        btn_row.addWidget(self.btn_edit)
        
        self.btn_remove = QPushButton("Remove Selected")
        self.btn_remove.setMinimumHeight(32)
        self.btn_remove.setEnabled(False)
        btn_row.addWidget(self.btn_remove)
        
        btn_row.addStretch()
        layout.addLayout(btn_row)  
        
        self.btn_box = QDialogButtonBox(QDialogButtonBox.Ok)
        self.btn_box.setMinimumHeight(34)
        layout.addWidget(self.btn_box)

    def _connect_signals(self):
        self.btn_add.clicked.connect(self._on_add)
        self.btn_edit.clicked.connect(self._on_edit)
        self.btn_remove.clicked.connect(self._on_remove)
        self.btn_box.accepted.connect(self.accept) 
        self.table.currentCellChanged.connect(self._update_button_states)

    def _update_button_states(self):
        has_selection = self.table.currentRow() >= 0
        self.btn_edit.setEnabled(has_selection)
        self.btn_remove.setEnabled(has_selection)

    def _load_data(self):
        if os.path.exists(self.device_validations_json):
            try:
                with open(self.device_validations_json, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                if isinstance(data, dict) and 'devices' in data:
                    self.all_validations = data['devices']
                elif isinstance(data, list):
                    self.all_validations = data
            except Exception as e:
                logger.error(f"Failed to load validations: {e}")

    def _update_table(self):
        self.table.setRowCount(len(self.all_validations))
        for i, val_data in enumerate(self.all_validations):
            analytes_str = ", ".join(val_data.get("analytes", []))
            self.table.setItem(i, 0, QTableWidgetItem(analytes_str))
            self.table.setItem(i, 1, QTableWidgetItem(val_data.get("device", "")))
            self.table.setItem(i, 2, QTableWidgetItem(val_data.get("start", "")))
            self.table.setItem(i, 3, QTableWidgetItem(val_data.get("stop", "") or "-"))
            self.table.setItem(i, 4, QTableWidgetItem(val_data.get("comment", "") or "-"))
        self.table.resizeRowsToContents()
        self._update_button_states()

    def _on_add(self):
        dialog = AddDeviceValidationDialog(self, existing_validations=self.all_validations, incident_path=self.incident_path)
        if dialog.exec() == QDialog.Accepted:
            data = dialog.get_data()
            self.all_validations.append(data)
            self._update_table()
            self._save_data()

    def _on_edit(self):
        selected_row = self.table.currentRow()
        if selected_row >= 0:
            old_data = self.all_validations[selected_row]
            dialog = AddDeviceValidationDialog(
                self, initial_data=old_data, existing_validations=self.all_validations,
                exclude_index=selected_row, incident_path=self.incident_path
            )
            if dialog.exec() == QDialog.Accepted:
                new_data = dialog.get_data()
                self.all_validations[selected_row] = new_data
                self._update_table()
                self._save_data()

    def _on_remove(self):
        selected_row = self.table.currentRow()
        if selected_row >= 0:
            reply = QMessageBox.question(
                self, "Confirm Deletion", "Are you sure you want to remove this validation?",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No
            )
            if reply == QMessageBox.Yes:
                self.all_validations.pop(selected_row)
                self._update_table()
                self._save_data()

    def _save_data(self):
        try:
            os.makedirs(self.validations_dir, exist_ok=True)
            with open(self.device_validations_json, 'w', encoding='utf-8') as f:
                json.dump({"devices": self.all_validations}, f, indent=4)
            self._start_processing()
        except Exception as e:
            QMessageBox.critical(self, "Save Error", f"Failed to save:\n{e}")

    def _start_processing(self):
        self.progress = QProgressDialog("Processing data...", None, 0, 0, self)
        self.progress.setWindowTitle("Processing")
        self.progress.setWindowModality(Qt.WindowModal)
        self.progress.setMinimumDuration(0)
        self.progress.show()
        self.worker = ProcessingWorker(self.incident_path)
        self.worker.finished_signal.connect(self._on_processing_finished)
        self.worker.error_signal.connect(self._on_processing_error)
        self.worker.start()

    def _on_processing_finished(self):
        if self.progress: self.progress.close()

    def _on_processing_error(self, error_msg):
        if self.progress: self.progress.close()
        QMessageBox.critical(self, "Processing Error", f"Failed:\n{error_msg}")
