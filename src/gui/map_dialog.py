import os
import re
import logging
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QPushButton, QFileDialog,
    QScrollArea, QLabel, QMessageBox, QWidget, QSizePolicy, QMenu,
    QDialogButtonBox, QFormLayout, QLineEdit, QTextEdit, QRadioButton,
    QButtonGroup, QStackedWidget, QComboBox
)
from PySide6.QtGui import QPixmap, QPainter, QPen, QFont, QColor, QDoubleValidator, QDesktopServices
from PySide6.QtCore import Qt, Signal, QUrl
from datamanagement.locations import LocationManager, get_next_label_index, index_to_label

logger = logging.getLogger(__name__)

class MarkerInfoDialog(QDialog):
    """Dialog for marker metadata. Label must be globally unique across all maps and data types."""
    def __init__(self, parent=None, default_label="", edit_data=None, current_map_labels=None):
        super().__init__(parent)
        self.is_edit = edit_data is not None
        self.current_map_labels = current_map_labels or set()
        self._original_label = edit_data.get("label", "") if self.is_edit else None

        self.setWindowTitle("Edit Marker" if self.is_edit else "Place Marker")
        self.setMinimumWidth(420)
        self._lat = None
        self._lon = None
        self._setup_ui(default_label)
        if self.is_edit:
            self._populate(edit_data)

    def _setup_ui(self, default_label):
        layout = QVBoxLayout(self)
        form = QFormLayout()
        
        self.lbl_label = QLineEdit(default_label)
        self.lbl_label.setPlaceholderText("A-Z, numbers, underscores only")
        if self.is_edit:
            self.lbl_label.setReadOnly(True)
            self.lbl_label.setStyleSheet("background-color: #f0f0f0; color: #555;")
            
        self.txt_desc = QTextEdit()
        self.txt_desc.setMaximumHeight(60)
        self.txt_desc.setPlaceholderText("Optional description...")
        
        form.addRow("Label:", self.lbl_label)
        form.addRow("Description:", self.txt_desc)
        
        self.coord_group = QButtonGroup(self)
        self.rb_geo = QRadioButton("geo: URI")
        self.rb_latlon = QRadioButton("Latitude / Longitude")
        self.rb_geo.setChecked(True)
        self.coord_group.addButton(self.rb_geo, 0)
        self.coord_group.addButton(self.rb_latlon, 1)
        
        radio_layout = QHBoxLayout()
        radio_layout.addWidget(self.rb_geo)
        radio_layout.addWidget(self.rb_latlon)
        form.addRow("Coordinates:", radio_layout)
        
        self.stack = QStackedWidget()
        page_geo = QWidget()
        geo_layout = QHBoxLayout(page_geo)
        geo_layout.setContentsMargins(0, 0, 0, 0)
        self.txt_geo = QLineEdit()
        self.txt_geo.setPlaceholderText("geo:lat,lon?z=19 (Optional)")
        geo_layout.addWidget(self.txt_geo)
        self.stack.addWidget(page_geo)
        
        page_latlon = QWidget()
        latlon_layout = QHBoxLayout(page_latlon)
        latlon_layout.setContentsMargins(0, 0, 0, 0)
        self.txt_lat = QLineEdit()
        self.txt_lat.setPlaceholderText("-90.000000")
        self.txt_lat.setValidator(QDoubleValidator(-90.0, 90.0, 6))
        self.txt_lon = QLineEdit()
        self.txt_lon.setPlaceholderText("-180.000000")
        self.txt_lon.setValidator(QDoubleValidator(-180.0, 180.0, 6))
        latlon_layout.addWidget(QLabel("Lat:"))
        latlon_layout.addWidget(self.txt_lat)
        latlon_layout.addWidget(QLabel("Lon:"))
        latlon_layout.addWidget(self.txt_lon)
        self.stack.addWidget(page_latlon)
        
        form.addRow("", self.stack)
        layout.addLayout(form)
        
        self.btn_box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        layout.addWidget(self.btn_box)
        self.btn_box.accepted.connect(self._validate_and_accept)
        self.btn_box.rejected.connect(self.reject)
        self.coord_group.idClicked.connect(lambda idx: self.stack.setCurrentIndex(idx))

    def _populate(self, data):
        self.lbl_label.setText(data.get("label", ""))
        self.txt_desc.setPlainText(data.get("description", "") or "")
        coords = data.get("coordinates")
        if coords and coords.get("latitude") is not None and coords.get("longitude") is not None:
            lat, lon = coords["latitude"], coords["longitude"]
            self.txt_lat.setText(str(lat))
            self.txt_lon.setText(str(lon))
            self.txt_geo.setText(f"geo:{lat},{lon}")
            self.rb_latlon.setChecked(True)
            self.stack.setCurrentIndex(1)
        else:
            self.txt_lat.setText("")
            self.txt_lon.setText("")
            self.txt_geo.setText("")
            self.rb_geo.setChecked(True)
            self.stack.setCurrentIndex(0)

    def _validate_and_accept(self):
        new_label = self.lbl_label.text().strip()
        if not new_label:
            QMessageBox.warning(self, "Validation Error", "Label cannot be empty.")
            return
        if not re.match(r'^[A-Za-z0-9_]+$', new_label):
            QMessageBox.warning(self, "Validation Error", "Label must contain only letters, numbers, and underscores.")
            return
        if not self.is_edit and new_label in self.current_map_labels:
            QMessageBox.warning(self, "Duplicate Label", "This label has already been used globally across all maps and data types.")
            return
            
        mode = self.coord_group.checkedId()
        self._lat, self._lon = None, None
        try:
            if mode == 0:
                txt = self.txt_geo.text().strip()
                if txt:
                    match = re.match(r'geo:\s*(-?\d+(?:\.\d+)?)\s*,\s*(-?\d+(?:\.\d+)?)', txt)
                    if not match: raise ValueError("Invalid geo: format.")
                    self._lat, self._lon = float(match.group(1)), float(match.group(2))
            else:
                lat_s, lon_s = self.txt_lat.text().strip(), self.txt_lon.text().strip()
                if lat_s or lon_s:
                    self._lat, self._lon = float(lat_s), float(lon_s)
                    
            if self._lat is not None and not (-90 <= self._lat <= 90):
                raise ValueError("Latitude must be between -90 and 90.")
            if self._lon is not None and not (-180 <= self._lon <= 180):
                raise ValueError("Longitude must be between -180 and 180.")
            self.accept()
        except ValueError as e:
            QMessageBox.warning(self, "Validation Error", str(e))
        except Exception as e:
            QMessageBox.critical(self, "Error", str(e))

    def get_data(self, mode=None, existing_data=None):
        data = {
            "label": self.lbl_label.text().strip(),
            "description": self.txt_desc.toPlainText().strip(),
            "coordinates": {"latitude": self._lat, "longitude": self._lon}
        }
        if existing_data:
            if "readings" in existing_data: data["readings"] = existing_data["readings"]
            if "device_log" in existing_data: data["device_log"] = existing_data["device_log"]
        else:
            if mode in ("spot", "spectral"): data["readings"] = []
            elif mode == "area": data["device_log"] = []
        return data

class MapCanvas(QWidget):
    """Custom widget for displaying a map and managing markers."""
    marker_placed = Signal()
    marker_edit_requested = Signal(int)
    marker_deleted = Signal(int)
    marker_moved = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.pixmap = None
        self.markers = []
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self._hit_threshold = 12
        self.setMouseTracking(True)
        self._pending_data = None
        self._dragging_idx = -1
        self._is_dragging = False

    def set_image(self, pixmap):
        self.pixmap = pixmap
        if self.pixmap and not self.pixmap.isNull():
            self.setFixedSize(pixmap.size())
            self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        if self.pixmap and not self.pixmap.isNull():
            painter.drawPixmap(0, 0, self.pixmap)
        font = QFont("Arial", 10, QFont.Bold)
        painter.setFont(font)
        for m in self.markers:
            x, y, label = m["x"], m["y"], m["label"]
            painter.setPen(QPen(QColor("red"), 2))
            painter.setBrush(QColor("yellow"))
            painter.drawEllipse(x-8, y-8, 16, 16)
            painter.setPen(QPen(QColor("black"), 1))
            painter.drawText(x+10, y+4, label)

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Escape and self._pending_data:
            self._pending_data = None
            self.setCursor(Qt.ArrowCursor)
            event.accept()

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton and self.pixmap and not self.pixmap.isNull():
            if self._pending_data and not self._is_dragging:
                if 0 <= event.x() <= self.pixmap.width() and 0 <= event.y() <= self.pixmap.height():
                    self.add_marker(event.x(), event.y(), self._pending_data)
                    self._pending_data = None
                    self.setCursor(Qt.ArrowCursor)
                    self.marker_placed.emit()
                    return
            if not self._is_dragging:
                for i, m in enumerate(self.markers):
                    if (event.x() - m["x"])**2 + (event.y() - m["y"])**2 <= self._hit_threshold**2:
                        self._dragging_idx = i
                        self._is_dragging = True
                        self.setCursor(Qt.ClosedHandCursor)
                        return
        elif event.button() == Qt.RightButton and self.pixmap and not self.pixmap.isNull() and not self._is_dragging:
            hit_idx = -1
            for i, m in enumerate(self.markers):
                if (event.x() - m["x"])**2 + (event.y() - m["y"])**2 <= self._hit_threshold**2:
                    hit_idx = i
                    break
            if hit_idx != -1:
                menu = QMenu(self)
                label = self.markers[hit_idx]["label"]
                menu.addAction(f"Edit '{label}'").triggered.connect(lambda: self.marker_edit_requested.emit(hit_idx))
                menu.addAction(f"Move '{label}'").triggered.connect(lambda: self._start_move(hit_idx))
                menu.addAction(f"Delete '{label}'").triggered.connect(lambda: self.marker_deleted.emit(hit_idx))
                menu.exec(event.globalPosition().toPoint())

    def mouseMoveEvent(self, event):
        if self._is_dragging and 0 <= self._dragging_idx < len(self.markers):
            self.markers[self._dragging_idx]["x"] = event.x()
            self.markers[self._dragging_idx]["y"] = event.y()
            self.update()

    def mouseReleaseEvent(self, event):
        if self._is_dragging:
            self._is_dragging = False
            self._dragging_idx = -1
            self.setCursor(Qt.ArrowCursor)
            self.marker_moved.emit()

    def add_marker(self, x, y, meta):
        marker = {**meta, "x": int(x), "y": int(y)}
        self.markers.append(marker)
        self.update()

    def _start_move(self, idx):
        self._dragging_idx = idx
        self._is_dragging = True
        self.setCursor(Qt.ClosedHandCursor)

class MapEditorDialog(QDialog):
    def __init__(self, parent=None, incident_path=None, mode="spot"):
        super().__init__(parent)
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowCloseButtonHint)
        self.incident_path = incident_path
        self.mode = mode
        self.mapping_dir = os.path.join(incident_path, "mapping") if incident_path else None
        
        # Use LocationManager for all JSON operations
        self.manager = LocationManager(incident_path, mode=mode)
        self.manager.ensure_structure()
        self.maps_data = self.manager.get_maps_data()
        self.current_map_file = None
        
        self.setWindowTitle(f"Map Editor - {mode.title()} Locations")
        self.resize(900, 700)
        self._setup_ui()
        self._populate_maps_combo()
        self._connect_signals()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        top_toolbar = QHBoxLayout()
        
        self.combo_maps = QComboBox()
        self.combo_maps.setMinimumWidth(200)
        self.combo_maps.currentTextChanged.connect(self._on_map_selected)
        
        self.btn_create_map = QPushButton("Create Map")
        self.btn_create_map.setToolTip("Open OpenStreetMap in your browser to create a new map")
        self.btn_create_map.clicked.connect(self._open_create_map_url)
        
        self.btn_add_map = QPushButton("Add Map to Project...")
        self.btn_export_map = QPushButton("Export Map...")
        self.btn_export_map.clicked.connect(self._on_export_map)
        self.btn_place = QPushButton("Place Marker...")
        
        top_toolbar.addWidget(QLabel("Active Map:"))
        top_toolbar.addWidget(self.combo_maps)
        top_toolbar.addWidget(self.btn_create_map)
        top_toolbar.addWidget(self.btn_add_map)
        top_toolbar.addWidget(self.btn_export_map)
        top_toolbar.addStretch()
        top_toolbar.addWidget(self.btn_place)
        layout.addLayout(top_toolbar)
        
        scroll = QScrollArea()
        scroll.setWidgetResizable(False)
        scroll.setAlignment(Qt.AlignCenter)
        self.canvas = MapCanvas()
        scroll.setWidget(self.canvas)
        layout.addWidget(scroll)
        
        self.btn_box = QDialogButtonBox(QDialogButtonBox.Ok)
        layout.addWidget(self.btn_box)

    def _open_create_map_url(self):
        QDesktopServices.openUrl(QUrl("https://www.openstreetmap.org"))
        instructions = (
            "<ul style='margin-left: -20px; padding-left: 20px;'>"
            "<li>Zoom in to desired location.</li>"
            "<li>Click the Share button on the right of the page</li>"
            "<li>Click the Set custom dimensions checkbox</li>"
            "<li>Outline the desired area</li>"
            "<li>Click the Download button</li>"
            "<li>The map will then be saved and you can add it to your incident</li>"
            "</ul>"
        )
        QMessageBox.information(self, "How to Create a Map", instructions)

    def _populate_maps_combo(self):
        self.combo_maps.clear()
        for fname in sorted(self.maps_data.keys()):
            fpath = os.path.join(self.mapping_dir, fname)
            if os.path.exists(fpath):
                self.combo_maps.addItem(fname)
            else:
                del self.maps_data[fname]
        
        if self.combo_maps.count() > 0:
            self.combo_maps.setCurrentIndex(0)
        else:
            self.canvas.pixmap = None
            self.canvas.markers = []
            self.canvas.update()

    def _on_map_selected(self, filename):
        if not filename or filename not in self.maps_data:
            self.canvas.set_image(QPixmap())
            self.canvas.markers = []
            self.canvas.update()
            return
        
        if self.current_map_file and self.current_map_file in self.maps_data:
            self.maps_data[self.current_map_file] = list(self.canvas.markers)
            
        self.current_map_file = filename
        self.canvas.markers = list(self.maps_data.get(filename, []))
        pixmap_path = os.path.join(self.mapping_dir, filename)
        self.canvas.set_image(QPixmap(pixmap_path))

    def _connect_signals(self):
        self.btn_place.clicked.connect(self._on_place_marker)
        self.btn_add_map.clicked.connect(self._on_add_map)
        self.btn_box.accepted.connect(self.accept)
        self.canvas.marker_edit_requested.connect(self._on_edit_marker)
        self.canvas.marker_deleted.connect(self._on_delete_marker)
        self.canvas.marker_placed.connect(self._save_data)
        self.canvas.marker_moved.connect(self._save_data)

    def _on_place_marker(self):
        if not self.current_map_file:
            QMessageBox.warning(self, "No Map", "Please add and select a map first.")
            return
        
        all_used_labels = self.manager.get_all_used_labels()
        next_label = index_to_label(get_next_label_index(all_used_labels))
        
        dialog = MarkerInfoDialog(self, default_label=next_label, current_map_labels=all_used_labels)
        if dialog.exec() == QDialog.Accepted:
            self.canvas._pending_data = dialog.get_data(mode=self.mode)
            self.canvas.setCursor(Qt.CrossCursor)

    def _on_edit_marker(self, idx):
        all_used_labels = self.manager.get_all_used_labels()
        marker = self.canvas.markers[idx]
        dialog = MarkerInfoDialog(self, edit_data=marker, current_map_labels=all_used_labels)
        
        if dialog.exec() == QDialog.Accepted:
            new_data = dialog.get_data(mode=self.mode, existing_data=marker)
            new_label = new_data["label"]
            old_label = marker.get("label")
            
            for fname, markers in self.maps_data.items():
                for m in markers:
                    if m.get("label") == old_label:
                        m["label"] = new_label
                        m["description"] = new_data["description"]
                        m["coordinates"] = new_data["coordinates"]
                        if "device_log" in new_data:
                            for log_entry in new_data["device_log"]:
                                log_entry["location"] = new_label
                            m["device_log"] = new_data["device_log"]
                        if "readings" in new_data:
                            m["readings"] = new_data["readings"]
                            
            self.canvas.markers = list(self.maps_data.get(self.current_map_file, []))
            self.canvas.update()
            self._save_data()

    def _on_add_map(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Select Map Image", "",
            "PNG Files (*.png);;Images (*.png *.jpg *.jpeg *.bmp)"
        )
        if not path: return
        
        fname = self.manager.add_map(path)
        self.maps_data = self.manager.get_maps_data()
        self.combo_maps.addItem(fname)
        self.combo_maps.setCurrentText(fname)
        self.canvas.markers = []
        self.canvas.update()

    def _on_delete_marker(self, idx):
        reply = QMessageBox.warning(
            self, "Confirm Deletion",
            f"Delete marker '{self.canvas.markers[idx]['label']}'?\nThis will erase all data associated with this location.",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No
        )
        if reply == QMessageBox.Yes:
            del self.canvas.markers[idx]
            self.canvas.update()
            self._save_data()

    def _on_export_map(self):
        if not self.current_map_file:
            QMessageBox.warning(self, "No Map", "Please select a map to export.")
            return
        default_name = os.path.splitext(self.current_map_file)[0] + "_marked.png"
        file_path, _ = QFileDialog.getSaveFileName(
            self, "Export Map", default_name, "PNG Files (*.png);;JPEG Files (*.jpg);;All Files (*)"
        )
        if file_path:
            try:
                pixmap = self.canvas.grab()
                if pixmap.save(file_path):
                    QMessageBox.information(self, "Success", f"Map exported successfully to:\n{file_path}")
                else:
                    QMessageBox.critical(self, "Error", "Failed to save the map image.")
            except Exception as e:
                QMessageBox.critical(self, "Error", f"Failed to export map:\n{e}")

    def _save_data(self):
        if self.current_map_file:
            self.maps_data[self.current_map_file] = list(self.canvas.markers)
        self.manager.set_maps_data(self.maps_data)
