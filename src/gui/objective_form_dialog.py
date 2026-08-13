import json
import os
import datetime
import logging
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QPushButton, QLabel,
    QComboBox, QTextEdit, QGroupBox, QMessageBox, QFormLayout, QWidget
)
from PySide6.QtCore import Qt, Signal
from filter_dialog import FilterDialog

logger = logging.getLogger(__name__)

class ObservationWidget(QWidget):
    filter_requested = Signal(object)
    delete_requested = Signal(object)

    def __init__(self, parent=None, obs_data=None):
        super().__init__(parent)
        self.filter_data = None
        
        # Load existing filter data if editing
        if obs_data and obs_data.get('filter'):
            try:
                self.filter_data = json.loads(obs_data['filter'])
            except Exception:
                self.filter_data = None
        
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 5, 0, 5)
        
        # Data Type
        layout.addWidget(QLabel("Type:"))
        self.data_type_combo = QComboBox()
        self.data_type_combo.addItems(["spot", "area", "spectral", "exposure", "plume"])

        if obs_data and obs_data.get('data_type'):
            self.data_type_combo.setCurrentText(obs_data['data_type'])

        self.data_type_combo.setMinimumWidth(100)
        self.data_type_combo.currentTextChanged.connect(self._on_data_type_changed)
        layout.addWidget(self.data_type_combo)

        # Form
        layout.addWidget(QLabel("Form:"))
        self.form_combo = QComboBox()
        self.form_combo.setMinimumWidth(130)

        self._update_form_for_data_type(self.data_type_combo.currentText())

        if obs_data and obs_data.get('form'):
            form = obs_data['form']
            if self.form_combo.findText(form) >= 0:
                self.form_combo.setCurrentText(form)

        layout.addWidget(self.form_combo)
        
        # Filter Button
        self.filter_button = QPushButton("Filter")
        self.filter_button.setMinimumWidth(100)
        self.filter_button.clicked.connect(lambda: self.filter_requested.emit(self))
        layout.addWidget(self.filter_button)
        
        layout.addStretch()
        
        # Delete Button
        self.btn_delete = QPushButton("Delete")
        self.btn_delete.setStyleSheet("color: #dc3545; font-weight: bold;")
        self.btn_delete.setCursor(Qt.PointingHandCursor)
        self.btn_delete.clicked.connect(lambda: self.delete_requested.emit(self))
        layout.addWidget(self.btn_delete)
        
        self._update_filter_button_text()

    def _update_filter_button_text(self):
        if self.filter_data:
            analyte_count = len(self.filter_data.get('selected_analytes', []))
            self.filter_button.setText(f"Filter ({analyte_count} analytes)")
            self.filter_button.setStyleSheet("background-color: #d4edda; border-color: #c3e6cb; color: #155724;")
        else:
            self.filter_button.setText("Filter")
            self.filter_button.setStyleSheet("")

    def _on_data_type_changed(self, text):
        self._update_form_for_data_type(text)

    def _update_form_for_data_type(self, data_type):
        self.form_combo.blockSignals(True)

        current_form = self.form_combo.currentText()
        self.form_combo.clear()

        if data_type == "spectral":
            self.form_combo.addItems(["Table", "Summary Map"])
            self.form_combo.setEnabled(True)

        elif data_type == "exposure":
            self.form_combo.addItems(["Summary Table", "Summary Chart"])
            self.form_combo.setEnabled(True)

        elif data_type == "plume":
            self.form_combo.addItems(["Summary Map"])
            self.form_combo.setEnabled(False)

        else:
            self.form_combo.addItems([
                "Table",
                "Chart",
                "Summary Table",
                "Summary Chart",
                "Summary Map"
            ])
            self.form_combo.setEnabled(True)

        if current_form and self.form_combo.findText(current_form) >= 0:
            self.form_combo.setCurrentText(current_form)
        else:
            self.form_combo.setCurrentIndex(0)

        self.form_combo.blockSignals(False)
            
    def set_filter_data(self, data):
        self.filter_data = data
        self._update_filter_button_text()

    def get_data(self):
        return {
            'data_type': self.data_type_combo.currentText(),
            'form': self.form_combo.currentText(),
            'filter': json.dumps(self.filter_data) if self.filter_data else None
        }

class ObjectiveFormDialog(QDialog):
    def __init__(self, parent=None, incident_path=None, obj_data=None):
        super().__init__(parent)
        self.incident_path = incident_path
        self.obj_data = obj_data
        self.observations = []
        
        self.setWindowTitle("Edit Objective" if obj_data else "Add Objective")
        self.resize(800, 600)
        self._setup_ui()
        
        if obj_data:
            self._populate(obj_data)

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        
        form = QFormLayout()
        self.cmb_zone = QComboBox()
        self.cmb_zone.addItems(["Hotzone", "Warmzone", "Fireground", "Community"])
        form.addRow("Zone:", self.cmb_zone)
        
        self.txt_objective = QTextEdit()
        self.txt_objective.setMaximumHeight(80)
        form.addRow("Objective:", self.txt_objective)
        
        self.txt_strategy = QTextEdit()
        self.txt_strategy.setMaximumHeight(80)
        form.addRow("Strategy:", self.txt_strategy)
        
        self.txt_conclusion = QTextEdit()
        self.txt_conclusion.setMaximumHeight(80)
        form.addRow("Conclusion:", self.txt_conclusion)
        
        layout.addLayout(form)
        
        # Observations Group
        obs_group = QGroupBox("Observations")
        obs_layout = QVBoxLayout(obs_group)
        
        self.observations_container = QVBoxLayout()
        obs_layout.addLayout(self.observations_container)
        
        self.btn_add_obs = QPushButton("+ Add Observation")
        self.btn_add_obs.clicked.connect(self._add_observation)
        obs_layout.addWidget(self.btn_add_obs)
        
        layout.addWidget(obs_group)
        
        # Buttons
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()
        self.btn_save = QPushButton("Save")
        self.btn_save.setMinimumWidth(100)
        self.btn_save.clicked.connect(self._on_save)
        btn_layout.addWidget(self.btn_save)
        
        self.btn_cancel = QPushButton("Cancel")
        self.btn_cancel.setMinimumWidth(100)
        self.btn_cancel.clicked.connect(self.reject)
        btn_layout.addWidget(self.btn_cancel)
        
        layout.addLayout(btn_layout)

    def _populate(self, data):
        self.cmb_zone.setCurrentText(data.get('zone', 'Hotzone'))
        self.txt_objective.setPlainText(data.get('objective', ''))
        self.txt_strategy.setPlainText(data.get('strategy', ''))
        self.txt_conclusion.setPlainText(data.get('conclusion', ''))
        
        for obs in data.get('observations', []):
            self._add_observation(obs_data=obs)

    def _add_observation(self, checked=False, obs_data=None):
        obs_widget = ObservationWidget(parent=self, obs_data=obs_data)
        obs_widget.filter_requested.connect(self._handle_filter_request)
        obs_widget.delete_requested.connect(self._handle_delete_request)
        self.observations.append(obs_widget)
        self.observations_container.addWidget(obs_widget)

    def _handle_delete_request(self, obs_widget):
        reply = QMessageBox.question(
            self, "Delete Observation", 
            "Are you sure you want to delete this observation?",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No
        )
        if reply == QMessageBox.Yes:
            self.observations_container.removeWidget(obs_widget)
            self.observations.remove(obs_widget)
            obs_widget.deleteLater()

    def _handle_filter_request(self, obs_widget):
        current_filters = obs_widget.filter_data or {}
        data_type = obs_widget.data_type_combo.currentText()
        
        dialog = FilterDialog(
            parent=self, 
            incident_path=self.incident_path, 
            data_type=data_type,
            mode="objective", 
            initial_filters=current_filters
        )
        if dialog.exec() == QDialog.Accepted:
            new_filters = dialog.get_filters()
            # Clean up and convert datetimes to strings for JSON serialization
            json_filters = new_filters.copy()
            json_filters.pop('sites_count', None)
            json_filters.pop('devices_count', None)
            json_filters.pop('analytes_count', None)
            for key in ('start_time', 'stop_time'):
                if hasattr(json_filters.get(key), 'strftime'):
                    json_filters[key] = json_filters[key].strftime("%Y-%m-%d %H:%M")
                    
            obs_widget.set_filter_data(json_filters)

    def _on_save(self):
        zone = self.cmb_zone.currentText()
        objective = self.txt_objective.toPlainText().strip()
        strategy = self.txt_strategy.toPlainText().strip()
        conclusion = self.txt_conclusion.toPlainText().strip()
        
        if not objective:
            QMessageBox.warning(self, "Validation Error", "Objective text cannot be empty.")
            return
            
        observations = [obs.get_data() for obs in self.observations]
        
        self.result_data = {
            'zone': zone,
            'objective': objective,
            'strategy': strategy,
            'conclusion': conclusion,
            'observations': observations
        }
        self.accept()

    def get_data(self):
        return getattr(self, 'result_data', None)
