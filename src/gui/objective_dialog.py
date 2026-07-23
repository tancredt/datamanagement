import os
import sys
import json
import datetime
import logging
import pandas as pd
import numpy as np
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QPushButton, QLabel,
    QComboBox, QTextEdit, QGroupBox, QScrollArea, QWidget,
    QFrame, QMessageBox, QSizePolicy, QTabWidget, QTabBar,
    QInputDialog, QDialogButtonBox, QFormLayout,
    QButtonGroup, QRadioButton
)
from PySide6.QtCore import Qt, Signal

current_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.dirname(current_dir)
if parent_dir not in sys.path:
    sys.path.insert(0, parent_dir)

try:
    from filter_dialog import FilterDialog
except ImportError:
    FilterDialog = None
    print("Warning: filter_dialog.py not found. Filter buttons will show a placeholder.")

logger = logging.getLogger(__name__)

# ──────────────────────────────────────────────────────────
# Editable Tab Bar (double-click to rename)
# ──────────────────────────────────────────────────────────
class EditableTabBar(QTabBar):
    """A QTabBar that emits a signal when a tab is double-clicked."""
    tabRenameRequested = Signal(int)

    def mouseDoubleClickEvent(self, event):
        index = self.tabAt(event.pos())
        if index >= 0:
            self.tabRenameRequested.emit(index)
        else:
            super().mouseDoubleClickEvent(event)

# ──────────────────────────────────────────────────────────
# Observation Widget
# ──────────────────────────────────────────────────────────
class ObservationWidget(QWidget):
    """Widget for a single observation entry."""
    filter_requested = Signal(object)

    def __init__(self, data_type="spot", parent=None):
        super().__init__(parent)
        self.data_type = data_type
        self.filter_data = None
        
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 5, 0, 5)
        
        # ── Data Type Combo ──
        layout.addWidget(QLabel("Data Type: "))
        self.data_type_combo = QComboBox()
        self.data_type_combo.addItems(["Spot Readings", "Area Readings", "Spectral Results", "Exposures", "Plumes"])
        self.data_type_combo.setMinimumWidth(130)
        
        if data_type == "area":
            self.data_type_combo.setCurrentText("Area Readings")
        elif data_type == "spectral":
            self.data_type_combo.setCurrentText("Spectral Results")
        elif data_type == "exposure":
            self.data_type_combo.setCurrentText("Exposures")
        elif data_type == "plume":
            self.data_type_combo.setCurrentText("Plumes")
        else:
            self.data_type_combo.setCurrentText("Spot Readings")
            
        self.data_type_combo.currentTextChanged.connect(self._on_data_type_changed)
        layout.addWidget(self.data_type_combo)
        
        # ── Form Combo ──
        layout.addWidget(QLabel("Form: "))
        self.form_combo = QComboBox()
        self.form_combo.addItems(["Table", "Chart", "Summary Table", "Summary Chart", "Summary Map"])
        self.form_combo.setMinimumWidth(150)
        layout.addWidget(self.form_combo)
        
        # ── Filter Button ──
        self.filter_button = QPushButton("Filter")
        self.filter_button.setMinimumWidth(120)
        self.filter_button.clicked.connect(self._on_filter_clicked)
        layout.addWidget(self.filter_button)
        
        layout.addStretch()
        
        # Apply initial form state based on data type
        self._update_form_for_data_type(self.data_type)

    def _on_data_type_changed(self, text):
        """Keeps self.data_type in sync with the combo selection and updates form availability."""
        if "Spot" in text:
            self.data_type = "spot"
        elif "Area" in text:
            self.data_type = "area"
        elif "Exposures" in text:
            self.data_type = "exposure"
        elif "Plumes" in text:
            self.data_type = "plume"
        else:
            self.data_type = "spectral"
        self._update_form_for_data_type(self.data_type)

    def _update_form_for_data_type(self, data_type):
        """Forces Form combo to valid options based on data type."""
        self.form_combo.blockSignals(True)
        if data_type == "spectral":
            self.form_combo.clear()
            self.form_combo.addItem("Table")
            self.form_combo.setCurrentText("Table")
            self.form_combo.setEnabled(False)
        elif data_type == "exposure":
            # Exposures only support Summary Table, Summary Chart, and Table
            self.form_combo.clear()
            self.form_combo.addItems(["Summary Table", "Summary Chart", "Table"])
            self.form_combo.setCurrentText("Summary Table")
            self.form_combo.setEnabled(True)
        elif data_type == "plume":
            # ✅ Plumes only support Summary Map
            self.form_combo.clear()
            self.form_combo.addItem("Summary Map")
            self.form_combo.setCurrentText("Summary Map")
            self.form_combo.setEnabled(False)
        else:
            # Restore full options for Spot/Area
            current_text = self.form_combo.currentText()
            self.form_combo.clear()
            self.form_combo.addItems(["Table", "Chart", "Summary Table", "Summary Chart", "Summary Map"])
            if current_text in [self.form_combo.itemText(i) for i in range(self.form_combo.count())]:
                self.form_combo.setCurrentText(current_text)
            else:
                self.form_combo.setCurrentText("Table")
            self.form_combo.setEnabled(True)
        self.form_combo.blockSignals(False)

    def _on_filter_clicked(self):
        """Emits signal to request filter dialog."""
        self.filter_requested.emit(self)

    def get_data(self):
        return {
            'form': self.form_combo.currentText(),
            'data_type': self.data_type,
            'filter_data': self.filter_data
        }

    def set_filter_data(self, data):
        if data:
            data.pop('sites_count', None)
            data.pop('devices_count', None)
            data.pop('analytes_count', None)
            
            # Clean up 'Unassigned' from sites if present
            if 'selected_sites' in data and isinstance(data['selected_sites'], list):
                data['selected_sites'] = [s for s in data['selected_sites'] if s != "Unassigned"]
                
            # Ensure base keys exist for safety
            data.setdefault('selected_sites', [])
            data.setdefault('selected_analytes', [])
            
        self.filter_data = data
        
        if data:
            analyte_count = len(data.get('selected_analytes', []))
            if self.data_type == "spectral":
                self.filter_button.setText(f"Filter (Spectral)")
            elif self.data_type == "plume":
                self.filter_button.setText(f"Filter (Plumes)")
            else:
                self.filter_button.setText(f"Filter ({analyte_count} analytes)")
                
            self.filter_button.setStyleSheet(
                "background-color: #d4edda; border-color: #c3e6cb; color: #155724;"
            )
        else:
            self.filter_button.setText("Filter")
            self.filter_button.setStyleSheet("")

# ──────────────────────────────────────────────────────────
# Objective Widget
# ──────────────────────────────────────────────────────────
class ObjectiveWidget(QWidget):
    """Widget representing a single objective with all its fields."""
    filter_requested = Signal(object)
    delete_requested = Signal(object)

    def __init__(self, objective_number=1, data_type="spot", parent=None):
        super().__init__(parent)
        self.objective_number = objective_number
        self.data_type = data_type
        self.observations = []
        
        # ── Timestamp Tracking ──
        self.created = None
        self.updated = None
        
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(10, 10, 10, 10)
        main_layout.setSpacing(10)
        
        # ── Status & Timestamps ──
        status_layout = QHBoxLayout()
        status_layout.addWidget(QLabel("Status: "))
        self.status_combo = QComboBox()
        self.status_combo.addItems(["Ongoing", "Complete"])
        self.status_combo.setMinimumWidth(120)
        status_layout.addWidget(self.status_combo)
        
        status_layout.addSpacing(20)
        self.lbl_created = QLabel("Created: --")
        self.lbl_created.setStyleSheet("color: gray; font-size: 11px;")
        status_layout.addWidget(self.lbl_created)
        
        status_layout.addSpacing(10)
        self.lbl_updated = QLabel("Updated: --")
        self.lbl_updated.setStyleSheet("color: gray; font-size: 11px;")
        status_layout.addWidget(self.lbl_updated)
        
        # ── Delete Objective Button ──
        status_layout.addStretch()
        self.btn_delete = QPushButton("Delete Objective")
        self.btn_delete.setStyleSheet("color: #dc3545; font-weight: bold;")
        self.btn_delete.setCursor(Qt.PointingHandCursor)
        self.btn_delete.clicked.connect(lambda: self.delete_requested.emit(self))
        status_layout.addWidget(self.btn_delete)
        
        main_layout.addLayout(status_layout)
        
        # Objective
        objective_group = QGroupBox("Objective")
        objective_layout = QVBoxLayout(objective_group)
        self.objective_text = QTextEdit()
        self.objective_text.setMaximumHeight(80)
        self.objective_text.setPlaceholderText("Enter the air monitoring objective...")
        objective_layout.addWidget(self.objective_text)
        main_layout.addWidget(objective_group)
        
        # Observations
        observations_group = QGroupBox("Observations")
        observations_layout = QVBoxLayout(observations_group)
        self.observations_container = QVBoxLayout()
        observations_layout.addLayout(self.observations_container)
        self.add_obs_button = QPushButton("Add Observation")
        self.add_obs_button.clicked.connect(self.add_observation)
        observations_layout.addWidget(self.add_obs_button)
        main_layout.addWidget(observations_group)
        
        # Conclusions
        conclusions_group = QGroupBox("Conclusions")
        conclusions_layout = QVBoxLayout(conclusions_group)
        self.conclusions_text = QTextEdit()
        self.conclusions_text.setMaximumHeight(80)
        self.conclusions_text.setPlaceholderText("Enter conclusions...")
        conclusions_layout.addWidget(self.conclusions_text)
        main_layout.addWidget(conclusions_group)

    def add_observation(self, form_text=None, filter_data=None, data_type=None):
        obs_data_type = data_type if data_type is not None else self.data_type
        obs_widget = ObservationWidget(data_type=obs_data_type, parent=self)
        obs_widget.filter_requested.connect(self._forward_filter_request)
        
        if form_text and form_text in [
            obs_widget.form_combo.itemText(i) 
            for i in range(obs_widget.form_combo.count())
        ]:
            obs_widget.form_combo.setCurrentText(form_text)
            
        if filter_data:
            obs_widget.set_filter_data(filter_data)
            
        self.observations.append(obs_widget)
        self.observations_container.addWidget(obs_widget)
        return obs_widget

    def _forward_filter_request(self, observation_widget):
        self.filter_requested.emit(observation_widget)

    def get_data(self):
        # Generate timestamps on save
        now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        if not self.created:
            self.created = now_str
        self.updated = now_str
        
        # Update UI labels to reflect the saved state
        self.lbl_created.setText(f"Created: {self.created}")
        self.lbl_updated.setText(f"Updated: {self.updated}")
        
        return {
            'objective_number': self.objective_number,
            'status': self.status_combo.currentText(),
            'objective': self.objective_text.toPlainText(),
            'observations': [obs.get_data() for obs in self.observations],
            'conclusions': self.conclusions_text.toPlainText(),
            'created': self.created,
            'updated': self.updated
        }

# ──────────────────────────────────────────────────────────
# Objective Dialog (using QTabWidget)
# ──────────────────────────────────────────────────────────
class ObjectiveDialog(QDialog):
    """Main dialog for creating and managing air monitoring objectives."""
    
    def __init__(self, parent=None, incident_path=None, zone_name="", data_type="spot"):
        super().__init__(parent)
        self.incident_path = incident_path
        self.zone_name = zone_name if zone_name else "General"
        self.default_data_type = data_type
        self.objectives = []
        self.objective_count = 0
        
        self.reports_dir = os.path.join(incident_path, "reports") if incident_path else None
        if self.reports_dir:
            os.makedirs(self.reports_dir, exist_ok=True)
            
        self.objectives_file = (
            os.path.join(self.reports_dir, "objectives.json") if self.reports_dir else None
        )
        
        title = "Air Monitoring Objectives"
        if self.zone_name != "General":
            title += f" - {self.zone_name}"
            
        self.setWindowTitle(title)
        self.resize(950, 750)
        
        self._setup_ui()
        self._load_existing_data()

    def _setup_ui(self):
        main_layout = QVBoxLayout(self)
        
        self.tab_widget = QTabWidget()
        self.tab_widget.setTabsClosable(True)
        self.tab_widget.setMovable(True)
        
        editable_bar = EditableTabBar()
        self.tab_widget.setTabBar(editable_bar)
        self.tab_widget.tabCloseRequested.connect(self._on_tab_close_requested)
        editable_bar.tabRenameRequested.connect(self._on_tab_rename_requested)
        
        main_layout.addWidget(self.tab_widget)
        
        btn_layout = QHBoxLayout()
        add_obj_btn = QPushButton("+ Add Objective")
        add_obj_btn.setMinimumHeight(35)
        add_obj_btn.setStyleSheet("QPushButton { font-weight: bold; font-size: 13px; }")
        add_obj_btn.clicked.connect(lambda: self.add_objective())
        btn_layout.addWidget(add_obj_btn)
        
        btn_layout.addStretch()
        
        save_btn = QPushButton("Save")
        save_btn.setMinimumHeight(35)
        save_btn.setMinimumWidth(100)
        save_btn.clicked.connect(self._on_save)
        btn_layout.addWidget(save_btn)
        
        cancel_btn = QPushButton("Cancel")
        cancel_btn.setMinimumHeight(35)
        cancel_btn.setMinimumWidth(100)
        cancel_btn.clicked.connect(self.reject)
        btn_layout.addWidget(cancel_btn)
        
        main_layout.addLayout(btn_layout)

    def add_objective(self, tab_title=None, obj_data=None):
        if isinstance(tab_title, bool):
            tab_title = None
            
        self.objective_count += 1
        if tab_title is None:
            tab_title = f"Objective {self.objective_count}"
            
        obj_widget = ObjectiveWidget(self.objective_count, data_type=self.default_data_type, parent=self)
        obj_widget.filter_requested.connect(self._handle_filter_request)
        obj_widget.delete_requested.connect(self._handle_delete_request)
        
        if obj_data:
            obj_widget.status_combo.setCurrentText(obj_data.get('status', 'Ongoing'))
            
            # ── Restore Timestamps ──
            obj_widget.created = obj_data.get('created')
            obj_widget.updated = obj_data.get('updated')
            if obj_widget.created:
                obj_widget.lbl_created.setText(f"Created: {obj_widget.created}")
            if obj_widget.updated:
                obj_widget.lbl_updated.setText(f"Updated: {obj_widget.updated}")
            # ────────────────────────
            
            obj_widget.objective_text.setPlainText(obj_data.get('objective', ''))
            obj_widget.conclusions_text.setPlainText(obj_data.get('conclusions', ''))
            
            for obs_data in obj_data.get('observations', []):
                obj_widget.add_observation(
                    form_text=obs_data.get('form'),
                    filter_data=obs_data.get('filter_data'),
                    data_type=obs_data.get('data_type')
                )
        else:
            obj_widget.add_observation(data_type=self.default_data_type)
            
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setStyleSheet("QScrollArea { border: none; background: transparent; }")
        scroll.setWidget(obj_widget)
        
        index = self.tab_widget.addTab(scroll, tab_title)
        self.tab_widget.setCurrentIndex(index)

    def _on_tab_close_requested(self, index):
        tab_title = self.tab_widget.tabText(index)
        reply = QMessageBox.question(
            self, "Delete Objective",
            f"Are you sure you want to delete '{tab_title}'?\n\nThis cannot be undone.",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No
        )
        if reply == QMessageBox.Yes:
            self.tab_widget.removeTab(index)

    def _on_tab_rename_requested(self, index):
        current_name = self.tab_widget.tabText(index)
        new_name, ok = QInputDialog.getText(
            self, "Rename Objective", "Enter new name:", text=current_name
        )
        if ok and new_name.strip():
            self.tab_widget.setTabText(index, new_name.strip())

    def _handle_delete_request(self, objective_widget):
        """Find the tab containing this widget and trigger the close/delete logic."""
        for i in range(self.tab_widget.count()):
            scroll_area = self.tab_widget.widget(i)
            if scroll_area.widget() == objective_widget:
                self._on_tab_close_requested(i)
                return

    def _load_existing_data(self):
        if not self.objectives_file or not os.path.exists(self.objectives_file):
            self.add_objective()
            return
            
        try:
            with open(self.objectives_file, 'r', encoding='utf-8') as f:
                full_data = json.load(f)
                
            zone_data = full_data.get(self.zone_name, {})
            objectives_list = zone_data.get("objectives", [])
            
            if not objectives_list:
                self.add_objective()
                return
                
            for obj_data in objectives_list:
                obj_num = obj_data.get('objective_number', self.objective_count + 1)
                tab_title = f"Objective {obj_num}"
                self.add_objective(tab_title=tab_title, obj_data=obj_data)
                
        except Exception as e:
            print(f"Failed to load objectives: {e}")
            QMessageBox.warning(
                self, "Load Error",
                f"Could not load existing objectives:\n{e}\n\nStarting with a blank objective."
            )
            self.add_objective()

    def _on_save(self):
        if not self.objectives_file:
            QMessageBox.warning(self, "No Path", "Cannot save: incident path not set.")
            return
            
        all_data = []
        for i in range(self.tab_widget.count()):
            scroll_area = self.tab_widget.widget(i)
            obj_widget = scroll_area.widget()
            data = obj_widget.get_data()
            data['objective_number'] = i + 1
            all_data.append(data)
            
        try:
            full_data = {}
            if os.path.exists(self.objectives_file):
                with open(self.objectives_file, 'r', encoding='utf-8') as f:
                    full_data = json.load(f)
                    
            full_data[self.zone_name] = {"objectives": all_data}
            
            with open(self.objectives_file, 'w', encoding='utf-8') as f:
                json.dump(full_data, f, indent=2)
                
            QMessageBox.information(
                self, "Saved",
                f"Successfully saved {len(all_data)} objective(s) to:\n{self.objectives_file}"
            )
            self.accept()
        except Exception as e:
            QMessageBox.critical(self, "Save Error", f"Failed to save objectives:\n{e}")

    # ── Filter Handling ──────────────────────────────────
    def _handle_filter_request(self, observation_widget):
        """Opens the FilterDialog in 'objective' mode (doesn't save to disk)."""
        if FilterDialog is None:
            QMessageBox.warning(self, "Missing Module", "filter_dialog.py could not be imported.")
            return
            
        current_filters = observation_widget.filter_data or {}
        
        # ✅ Load plume data if the observation is for plumes
        plume_data = []
        if observation_widget.data_type == "plume":
            plumes_dir = os.path.join(self.incident_path, "plumes")
            if os.path.exists(plumes_dir):
                for f in os.listdir(plumes_dir):
                    if f.lower().endswith(".png"):
                        try:
                            dt_str = os.path.splitext(f)[0]
                            dt_utc = datetime.datetime.strptime(dt_str, "%Y%m%d%H%M")
                            dt_local = dt_utc.replace(tzinfo=datetime.timezone.utc).astimezone().replace(tzinfo=None)
                            plume_data.append((dt_local, os.path.join(plumes_dir, f)))
                        except ValueError:
                            continue
                plume_data.sort(key=lambda x: x[0])
                
        filter_dlg = FilterDialog(
            parent=self,
            incident_path=self.incident_path,
            data_type=observation_widget.data_type,
            mode="objective",  # Don't save to disk
            initial_filters=current_filters,
            plume_data=plume_data  # ✅ Pass plume data so FilterDialog can set the time range
        )
        
        if filter_dlg.exec() == QDialog.Accepted:
            new_filters = filter_dlg.get_filters()
            
            # Serialize for JSON storage in the objective
            json_filters = new_filters.copy()
            if hasattr(json_filters.get('start_time'), 'strftime'):
                json_filters['start_time'] = json_filters['start_time'].strftime("%Y-%m-%d %H:%M")
            if hasattr(json_filters.get('stop_time'), 'strftime'):
                json_filters['stop_time'] = json_filters['stop_time'].strftime("%Y-%m-%d %H:%M")
                
            json_filters.pop('sites_count', None)
            json_filters.pop('devices_count', None)
            json_filters.pop('analytes_count', None)
            
            observation_widget.set_filter_data(json_filters)
