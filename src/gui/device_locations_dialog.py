import os
import json
import logging
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QComboBox,
    QTableWidget, QTableWidgetItem, QPushButton, QDialogButtonBox,
    QLabel, QMessageBox, QHeaderView, QFormLayout, QDateTimeEdit, QLineEdit,
    QWidget, QStyle, QCheckBox, QProgressDialog
)
from PySide6.QtCore import Qt, QDateTime, QSize, QThread, Signal
from PySide6.QtGui import QPixmap, QPainter, QPen, QFont, QColor
from gps_analysis_dialog import GPSAnalysisDialog
from datamanagement.choices import get_available_devices

logger = logging.getLogger(__name__)
DATE_FORMAT = "yyyy-MM-dd HH:mm:ss"
INFINITY_DATE = QDateTime(9999, 12, 31, 23, 59, 59)

class MapPreviewWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.pixmap = None
        self.markers = []
        self.setMinimumSize(350, 300)
        self.setStyleSheet("background-color: #f5f5f5; border: 1px solid #bbb;")

    def set_map(self, pixmap, markers):
        self.pixmap = pixmap
        self.markers = markers
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        rect = self.rect()
        if not self.pixmap or self.pixmap.isNull():
            painter.drawText(rect, Qt.AlignCenter, "No Map Available")
            return
        pw, ph = rect.width(), rect.height()
        img_w, img_h = self.pixmap.width(), self.pixmap.height()
        scale = min(pw / img_w, ph / img_h)
        sw, sh = img_w * scale, img_h * scale
        dx, dy = (pw - sw) / 2, (ph - sh) / 2
        painter.save()
        painter.translate(dx, dy)
        painter.scale(scale, scale)
        painter.drawPixmap(0, 0, self.pixmap)
        font = QFont("Arial", 12, QFont.Bold)
        painter.setFont(font)
        for m in self.markers:
            x, y, label = m.get("x"), m.get("y"), m.get("label")
            if x is None or y is None or not label:
                continue
            pen_width = max(1.0, 2.5 / scale)
            painter.setPen(QPen(QColor("red"), pen_width))
            painter.setBrush(QColor("yellow"))
            painter.drawEllipse(x - 9, y - 9, 18, 18)
            painter.setPen(QPen(QColor("black"), max(1.0, 1.2 / scale)))
            painter.drawText(x + 12, y + 5, label)
        painter.restore()

class AddDeviceLocationDialog(QDialog):
    def __init__(self, parent=None, available_labels=None, initial_data=None, existing_devices=None, exclude_index=None, incident_path=None):
        super().__init__(parent)
        self.incident_path = incident_path
        self.available_labels = available_labels or []
        self.initial_data = initial_data
        self.existing_devices = existing_devices or []
        self.exclude_index = exclude_index

        self.setWindowTitle("Edit Device Location" if initial_data else "Add Device Location")
        self.setMinimumWidth(450)
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(10)
        layout.setContentsMargins(16, 16, 16, 16)
        
        form = QFormLayout()
        form.setSpacing(8)
        form.setLabelAlignment(Qt.AlignRight)
        
        self.cmb_labels = QComboBox()
        self.cmb_labels.setMinimumHeight(28)
        self.cmb_labels.setEditable(False)
        self.cmb_labels.addItems(self.available_labels if self.available_labels else [])
        self.cmb_labels.setPlaceholderText("Select location...")
        form.addRow("Location (Marker Label) *: ", self.cmb_labels)
        
        self.cmb_device = QComboBox()
        self.cmb_device.setEditable(True)
        self.cmb_device.addItems(get_available_devices(self.incident_path, data_type="area"))
        form.addRow("Device *: ", self.cmb_device)
        
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
        self.txt_comment.setPlaceholderText("Optional note (e.g., swapped unit, battery died)")
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
            self.cmb_labels.setCurrentText(self.initial_data.get("location", ""))
            self.cmb_device.setCurrentText(self.initial_data.get("device", ""))
            dt_start = QDateTime.fromString(self.initial_data.get("start", ""), DATE_FORMAT)
            if dt_start.isValid():
                self.dt_start.setDateTime(dt_start)
            stop_val = self.initial_data.get("stop", "")
            if stop_val:
                self.chk_has_stop.setChecked(True)
                dt_stop = QDateTime.fromString(stop_val, DATE_FORMAT)
                if dt_stop.isValid():
                    self.dt_stop.setDateTime(dt_stop)
            self.txt_comment.setText(self.initial_data.get("comment", ""))
            
        layout.addLayout(form)
        layout.addSpacing(10)
        btn_box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        btn_box.setMinimumHeight(34)
        layout.addWidget(btn_box)
        btn_box.rejected.connect(self.reject)
        ok_button = btn_box.button(QDialogButtonBox.Ok)
        ok_button.clicked.connect(self._validate_and_accept)

    def _validate_and_accept(self):
        location = self.cmb_labels.currentText().strip()
        device_id = self.cmb_device.currentText().strip()
        
        if not location:
            QMessageBox.warning(self, "Validation Error", "Location (Marker Label) is mandatory.")
            self.cmb_labels.setFocus()
            return
        if not device_id:
            QMessageBox.warning(self, "Validation Error", "Device is mandatory.")
            self.cmb_device.setFocus()
            return
            
        start_dt = QDateTime.fromSecsSinceEpoch(self.dt_start.dateTime().toSecsSinceEpoch())
        if self.chk_has_stop.isChecked():
            stop_dt = QDateTime.fromSecsSinceEpoch(self.dt_stop.dateTime().toSecsSinceEpoch())
            if start_dt >= stop_dt:
                QMessageBox.warning(self, "Validation Error", "Start datetime cannot be after or equal to Stop datetime.")
                self.dt_stop.setFocus()
                return
        else:
            stop_dt = INFINITY_DATE
            
        for i, dev in enumerate(self.existing_devices):
            if self.exclude_index is not None and i == self.exclude_index:
                continue
            ex_start_str = dev.get("start", "")
            ex_stop_str = dev.get("stop", "")
            ex_device = dev.get("device", "")
            ex_location = dev.get("location", "")
            
            ex_start = QDateTime.fromSecsSinceEpoch(QDateTime.fromString(ex_start_str, DATE_FORMAT).toSecsSinceEpoch())
            ex_stop = QDateTime.fromSecsSinceEpoch(QDateTime.fromString(ex_stop_str, DATE_FORMAT).toSecsSinceEpoch()) if ex_stop_str else INFINITY_DATE
            
            if start_dt < ex_stop and ex_start < stop_dt:
                if device_id == ex_device:
                    QMessageBox.warning(self, "Validation Error",
                                        f"Device '{device_id}' is already assigned to location '{ex_location}' during this time period.")
                    return
                if location == ex_location:
                    QMessageBox.warning(self, "Validation Error",
                                        f"Location '{location}' is already occupied by device '{device_id}' during this time period.")
                    return
        self.accept()

    def get_data(self):
        return {
            "location": self.cmb_labels.currentText().strip(),
            "device": self.cmb_device.currentText().strip(),
            "start": self.dt_start.dateTime().toString(DATE_FORMAT),
            "stop": self.dt_stop.dateTime().toString(DATE_FORMAT) if self.chk_has_stop.isChecked() else "",
            "comment": self.txt_comment.text().strip() if self.chk_has_stop.isChecked() else ""
        }

class DeviceLocationsDialog(QDialog):
    def __init__(self, parent=None, incident_path=None):
        super().__init__(parent)
        self.incident_path = incident_path
        self.mapping_dir = os.path.join(incident_path, "mapping")
        self.area_locations_json = os.path.join(self.mapping_dir, "area_locations.json")
        self.all_devices = []
        self.available_markers = {}
        self.map_markers = {}
        self.worker = None
        self.progress = None

        self.setWindowTitle("Device Locations Manager")
        self.resize(950, 650)
        self._load_data()
        self._setup_ui()
        self._connect_signals()
        self._populate_filter()
        self._update_table()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(12)
        layout.setContentsMargins(16, 16, 16, 16)
        
        ctrl_row = QHBoxLayout()
        self.btn_show_maps = QPushButton("Show Map(s)")
        self.btn_show_maps.setMinimumHeight(32)
        self.btn_show_maps.setIcon(self.style().standardIcon(QStyle.SP_FileDialogListView))
        self.btn_show_maps.setIconSize(QSize(18, 18))
        ctrl_row.addWidget(self.btn_show_maps)
        ctrl_row.addWidget(QLabel("Filter: "))
        self.cmb_filter = QComboBox()
        self.cmb_filter.setMinimumWidth(150)
        ctrl_row.addWidget(self.cmb_filter)
        ctrl_row.addStretch()
        layout.addLayout(ctrl_row)
         
        self.table = QTableWidget()
        self.table.setColumnCount(5)
        self.table.setHorizontalHeaderLabels(["Location", "Device", "Start", "Stop", "Comment"])
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(4, QHeaderView.Stretch)
        self.table.setAlternatingRowColors(True)
        self.table.setStyleSheet("QTableWidget { font-size: 12px; }")
        layout.addWidget(self.table)
        
        btn_row = QHBoxLayout()
        self.btn_add = QPushButton("Add Device...")
        self.btn_add.setMinimumHeight(32)
        self.btn_add.setIcon(self.style().standardIcon(QStyle.SP_FileDialogNewFolder))
        self.btn_add.setIconSize(QSize(18, 18))
        btn_row.addWidget(self.btn_add)
        
        self.btn_edit = QPushButton("Edit Selected...")
        self.btn_edit.setMinimumHeight(32)
        self.btn_edit.setIcon(self.style().standardIcon(QStyle.SP_FileDialogDetailedView))
        self.btn_edit.setIconSize(QSize(18, 18))
        self.btn_edit.setEnabled(False)
        btn_row.addWidget(self.btn_edit)
        
        self.btn_remove = QPushButton("Remove Selected")
        self.btn_remove.setMinimumHeight(32)
        self.btn_remove.setIcon(self.style().standardIcon(QStyle.SP_TrashIcon))
        self.btn_remove.setIconSize(QSize(18, 18))
        self.btn_remove.setEnabled(False)
        btn_row.addWidget(self.btn_remove)
        
        self.btn_analyze_gps = QPushButton("Analyze GPS Data...")
        self.btn_analyze_gps.setMinimumHeight(32)
        self.btn_analyze_gps.setIcon(self.style().standardIcon(QStyle.SP_FileDialogInfoView))
        self.btn_analyze_gps.setIconSize(QSize(18, 18))
        btn_row.addWidget(self.btn_analyze_gps)
        
        btn_row.addStretch()
        layout.addLayout(btn_row)
        
        self.btn_box = QDialogButtonBox(QDialogButtonBox.Ok)
        self.btn_box.setMinimumHeight(34)
        layout.addWidget(self.btn_box)

    def _connect_signals(self):
        self.btn_show_maps.clicked.connect(self._on_show_maps)
        self.btn_add.clicked.connect(self._on_add_device)
        self.btn_edit.clicked.connect(self._on_edit_device)
        self.btn_remove.clicked.connect(self._on_remove_device)
        self.btn_analyze_gps.clicked.connect(self._on_analyze_gps)
        self.btn_box.accepted.connect(self.accept)
        self.cmb_filter.currentTextChanged.connect(self._update_table)
        self.table.currentCellChanged.connect(self._update_button_states)

    def _update_button_states(self):
        has_selection = self.table.currentRow() >= 0
        self.btn_edit.setEnabled(has_selection)
        self.btn_remove.setEnabled(has_selection)

    def _load_data(self):
        self.all_devices = []
        if os.path.exists(self.area_locations_json):
            try:
                with open(self.area_locations_json, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                maps_dict = data.get("maps", {})
                locations_list = maps_dict.get("locations", [])
                for loc in locations_list:
                    markers = loc.get("markers", [])
                    for marker in markers:
                        device_log = marker.get("device_log", [])
                        for entry in device_log:
                            self.all_devices.append(entry)
            except Exception as e:
                logger.error("Failed to load area locations: %s", e)
                
        if os.path.exists(self.area_locations_json):
            try:
                with open(self.area_locations_json, 'r', encoding='utf-8') as f:
                    map_data = json.load(f)
                self.available_markers = {}
                self.map_markers = {}
                maps_dict = map_data.get("maps", {})
                locations_list = maps_dict.get("locations", [])
                for loc in locations_list:
                    fname = loc.get("filename")
                    markers = loc.get("markers", [])
                    if fname:
                        self.available_markers[fname] = [m.get("label") for m in markers if m.get("label")]
                        self.map_markers[fname] = markers
            except Exception as e:
                logger.error("Failed to load map markers: %s", e)

    def _get_unique_labels(self):
        labels = set()
        for m_labels in self.available_markers.values():
            labels.update(m_labels)
        return sorted(labels)

    def _populate_filter(self):
        self.cmb_filter.blockSignals(True)
        self.cmb_filter.clear()
        self.cmb_filter.addItem("All")
        self.cmb_filter.addItems(self._get_unique_labels())
        self.cmb_filter.setCurrentText("All")
        self.cmb_filter.blockSignals(False)

    def _update_table(self):
        filter_val = self.cmb_filter.currentText()
        rows_data = []
        for i, dev_data in enumerate(self.all_devices):
            if filter_val == "All" or dev_data.get("location") == filter_val:
                rows_data.append((i, dev_data))
                
        self.table.setRowCount(len(rows_data))
        for i, (orig_idx, dev_data) in enumerate(rows_data):
            item = QTableWidgetItem(dev_data.get("location", ""))
            item.setData(Qt.UserRole, orig_idx)
            self.table.setItem(i, 0, item)
            self.table.setItem(i, 1, QTableWidgetItem(dev_data.get("device", "")))
            self.table.setItem(i, 2, QTableWidgetItem(dev_data.get("start", "")))
            self.table.setItem(i, 3, QTableWidgetItem(dev_data.get("stop", "") or "-"))
            self.table.setItem(i, 4, QTableWidgetItem(dev_data.get("comment", "") or "-"))
        self.table.resizeRowsToContents()
        self._update_button_states()

    def _on_show_maps(self):
        dialog = MapViewerDialog(self, self.available_markers, self.map_markers, self.mapping_dir)
        dialog.exec()

    def _on_add_device(self):
        dialog = AddDeviceLocationDialog(self, self._get_unique_labels(), existing_devices=self.all_devices, incident_path=self.incident_path)
        if dialog.exec() == QDialog.Accepted:
            data = dialog.get_data()
            self.all_devices.append(data)
            self._populate_filter()
            self._update_table()
            self._save_data()
            QMessageBox.information(self, "Added", f"Device '{data['device']}' added at location '{data['location']}'.")

    def _on_edit_device(self):
        selected_row = self.table.currentRow()
        if selected_row >= 0:
            item = self.table.item(selected_row, 0)
            orig_idx = item.data(Qt.UserRole)
            if orig_idx is not None and 0 <= orig_idx < len(self.all_devices):
                old_data = self.all_devices[orig_idx]
                dialog = AddDeviceLocationDialog(
                    self, self._get_unique_labels(),
                    initial_data=old_data,
                    existing_devices=self.all_devices,
                    exclude_index=orig_idx,
                    incident_path=self.incident_path
                )
                if dialog.exec() == QDialog.Accepted:
                    new_data = dialog.get_data()
                    self.all_devices[orig_idx] = new_data
                    self._populate_filter()
                    self._update_table()
                    self._save_data()
                    QMessageBox.information(self, "Updated", f"Device '{new_data['device']}' updated.")
        else:
            QMessageBox.information(self, "No Selection", "Please select a row in the table to edit.")

    def _on_remove_device(self):
        selected_row = self.table.currentRow()
        if selected_row >= 0:
            item = self.table.item(selected_row, 0)
            orig_idx = item.data(Qt.UserRole)
            if orig_idx is not None and 0 <= orig_idx < len(self.all_devices):
                dev_data = self.all_devices[orig_idx]
                reply = QMessageBox.question(
                    self, "Confirm Deletion",
                    f"Are you sure you want to remove device '{dev_data.get('device')}' from location '{dev_data.get('location')}'?",
                    QMessageBox.Yes | QMessageBox.No, QMessageBox.No
                )
                if reply == QMessageBox.Yes:
                    self.all_devices.pop(orig_idx)
                    self._populate_filter()
                    self._update_table()
                    self._save_data()
        else:
            QMessageBox.information(self, "No Selection", "Please select a row in the table to remove.")

    def _on_analyze_gps(self):
        dialog = GPSAnalysisDialog(parent=self, incident_path=self.incident_path)
        dialog.exec()

    def _save_data(self):
        try:
            os.makedirs(self.mapping_dir, exist_ok=True)
            if os.path.exists(self.area_locations_json):
                with open(self.area_locations_json, 'r', encoding='utf-8') as f:
                    data = json.load(f)
            else:
                data = {"maps": {"locations": []}}
                
            locations_list = data.get("maps", {}).get("locations", [])
            for loc in locations_list:
                for marker in loc.get("markers", []):
                    marker["device_log"] = []
                    
            for entry in self.all_devices:
                target_location = entry.get("location")
                found = False
                for loc in locations_list:
                    for marker in loc.get("markers", []):
                        if marker.get("label") == target_location:
                            if "device_log" not in marker:
                                marker["device_log"] = []
                            marker["device_log"].append(entry)
                            found = True
                            break
                    if found:
                        break
                        
            with open(self.area_locations_json, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2)
            logger.info("✅ Saved device locations to area_locations.json")
            self._start_processing()
        except Exception as e:
            QMessageBox.critical(self, "Save Error", f"Failed to save device locations:\n{e}")

    def _start_processing(self):
        self.progress = QProgressDialog("Processing data and updating site locations...", None, 0, 0, self)
        self.progress.setWindowTitle("Processing")
        self.progress.setWindowModality(Qt.WindowModal)
        self.progress.setMinimumDuration(0)
        self.progress.show()
        self.worker = ProcessingWorker(self.incident_path)
        self.worker.finished_signal.connect(self._on_processing_finished)
        self.worker.error_signal.connect(self._on_processing_error)
        self.worker.start()

    def _on_processing_finished(self):
        try:
            if self.progress:
                self.progress.close()
            logger.info("✅ Site column updated successfully.")
        except Exception as e:
            logger.error(f"Error in processing finished: {e}")

    def _on_processing_error(self, error_msg):
        if self.progress:
            self.progress.close()
        QMessageBox.critical(self, "Processing Error", f"Failed to update site locations:\n{error_msg}")

    def reject(self):
        super().reject()

class MapViewerDialog(QDialog):
    def __init__(self, parent=None, available_markers=None, map_markers=None, mapping_dir=None):
        super().__init__(parent)
        self.available_markers = available_markers or {}
        self.map_markers = map_markers or {}
        self.mapping_dir = mapping_dir

        self.setWindowTitle("Map Viewer")
        self.resize(850, 750)
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(12)
        layout.setContentsMargins(16, 16, 16, 16)
        
        layout.addWidget(QLabel("<b>Select Map:</b>"))
        self.cmb_maps = QComboBox()
        self.cmb_maps.setMinimumHeight(30)
        layout.addWidget(self.cmb_maps)
        
        self.map_preview = MapPreviewWidget()
        layout.addWidget(self.map_preview, stretch=1)
        
        layout.addWidget(QLabel("<b>Markers on this map:</b>"))
        self.lbl_markers = QLabel("None")
        self.lbl_markers.setWordWrap(True)
        self.lbl_markers.setStyleSheet("background: #fff; padding: 8px; border: 1px solid #ccc;")
        layout.addWidget(self.lbl_markers)
        
        self.cmb_maps.currentTextChanged.connect(self._on_map_changed)
        maps = list(self.available_markers.keys())
        if maps:
            self.cmb_maps.addItems(maps)
            self.cmb_maps.setCurrentIndex(0)
            self._on_map_changed(maps[0])
        else:
            self.cmb_maps.addItem("No maps available")

    def _on_map_changed(self, map_name):
        if not map_name or map_name == "No maps available":
            self.map_preview.set_map(QPixmap(), [])
            self.lbl_markers.setText("No markers available.")
            return
            
        img_path = os.path.join(self.mapping_dir, map_name) if self.mapping_dir else ""
        markers = self.map_markers.get(map_name, [])
        if os.path.exists(img_path):
            self.map_preview.set_map(QPixmap(img_path), markers)
        else:
            self.map_preview.set_map(QPixmap(), markers)
            
        labels = [m.get("label") for m in markers if m.get("label")]
        self.lbl_markers.setText(", ".join(labels) if labels else "No markers on this map.")

class ProcessingWorker(QThread):
    finished_signal = Signal()
    error_signal = Signal(str)
    def __init__(self, incident_path):
        super().__init__()
        self.incident_path = incident_path

    def run(self):
        try:
            from datamanagement.importer import update_site_from_device_log
            logger.info("Updating SITE column with new device locations...")
            update_site_from_device_log(self.incident_path)
            self.finished_signal.emit()
        except Exception as e:
            self.error_signal.emit(str(e))
