import os
import logging
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QComboBox,
    QTableWidget, QTableWidgetItem, QPushButton, QDialogButtonBox,
    QMessageBox, QHeaderView, QFormLayout, QDateTimeEdit, QLineEdit,
    QCheckBox, QLabel, QScrollArea, QWidget
)
from PySide6.QtCore import Qt, QDateTime
from datamanagement.db_manager import IncidentDatabase

logger = logging.getLogger(__name__)
DATE_FORMAT = "yyyy-MM-dd HH:mm:ss"


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
    def __init__(self, parent=None, incident_path=None, initial_data=None, existing_validations=None, exclude_index=None):
        super().__init__(parent)
        self.incident_path = incident_path
        self.db = IncidentDatabase(incident_path)

        # Populate choices directly from the database
        self.available_devices = self.db.get_devices("area")
        self.available_analytes = [a['label'] for a in self.db.get_analytes()]
        
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
        self.cmb_device.setMinimumHeight(28)
        self.cmb_device.addItems(self.available_devices)
        form.addRow("Device *: ", self.cmb_device)

        self.analyte_selector = AnalyteSelectionWidget(self.available_analytes)
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


class DeviceValidationsDialog(QDialog):
    def __init__(self, parent=None, incident_path=None):
        super().__init__(parent)
        self.incident_path = incident_path
        self.validations_dir = os.path.join(incident_path, "validations")

        # Initialize Database Manager
        self.db = IncidentDatabase(incident_path)
        
        # Load data directly from the DB
        self.all_validations = self.db.get_area_invalidations()

        self.setWindowTitle("Device Validations Manager")
        self.resize(850, 550)
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
        dialog = AddDeviceValidationDialog(self, incident_path=self.incident_path, existing_validations=self.all_validations)
        if dialog.exec() == QDialog.Accepted:
            data = dialog.get_data()
            self.db.add_area_invalidation(
                device_label=data["device"],
                start_dt=data["start"],
                stop_dt=data["stop"],
                comment=data["comment"],
                analyte_labels=data["analytes"]
            )
            self.all_validations = self.db.get_area_invalidations()
            self._update_table()

    def _on_edit(self):
        selected_row = self.table.currentRow()
        if selected_row >= 0:
            old_data = self.all_validations[selected_row]
            dialog = AddDeviceValidationDialog(
                self, 
                incident_path=self.incident_path,
                initial_data=old_data,
                existing_validations=self.all_validations,
                exclude_index=selected_row
            )
            if dialog.exec() == QDialog.Accepted:
                new_data = dialog.get_data()
                self.db.edit_area_invalidation(old_data, new_data)
                self.all_validations = self.db.get_area_invalidations()
                self._update_table()
        else:
            QMessageBox.information(self, "No Selection", "Please select a row in the table to edit.")

    def _on_remove(self):
        selected_row = self.table.currentRow()
        if selected_row >= 0:
            reply = QMessageBox.question(
                self, "Confirm Deletion", "Are you sure you want to remove this validation?",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No
            )
            if reply == QMessageBox.Yes:
                data = self.all_validations[selected_row]
                self.db.delete_area_invalidation(data)
                self.all_validations = self.db.get_area_invalidations()
                self._update_table()
        else:
            QMessageBox.information(self, "No Selection", "Please select a row in the table to remove.")
