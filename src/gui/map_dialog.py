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
from datamanagement.db_manager import IncidentDatabase
from map_renderer import draw_markers

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
        self.lbl_label.setMaxLength(2)
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
        
        lat = data.get("latitude")
        lon = data.get("longitude")
        
        if lat is not None and lon is not None:
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
            reply = QMessageBox.warning(
                self, 
                "Duplicate Label", 
                "A marker with this label already exists. If you do reuse this label, make sure it is in the same spot.",
                QMessageBox.Ok | QMessageBox.Cancel, 
                QMessageBox.Cancel
            )
            if reply != QMessageBox.Ok:
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

    def get_data(self, existing_data=None):
        return {
            "label": self.lbl_label.text().strip(),
            "description": self.txt_desc.toPlainText().strip(),
            "latitude": self._lat,
            "longitude": self._lon
        }

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
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        if self.pixmap and not self.pixmap.isNull():
            painter.drawPixmap(0, 0, self.pixmap)
        draw_markers(painter, self.markers)

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Escape and self._pending_data:
            self._pending_data = None
            self.setCursor(Qt.ArrowCursor)
            event.accept()

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton and self.pixmap and not self.pixmap.isNull():
            if self._pending_data and not self._is_dragging:
                if 0 <= event.x() <= self.pixmap.width() and 0 <= event.y() <= self.pixmap.height():
                    x, y = int(event.x()), int(event.y())
                    # Check if this is an existing marker being repositioned
                    is_existing = getattr(self, '_pending_is_existing', False)
                    
                    if is_existing:
                        # Update only the sitemap_marker table (position on map), skip marker table
                        self.parent().update_existing_marker_position(self._pending_data['label'], x, y)
                    else:
                        # New marker - add to canvas and trigger save
                        self.add_marker(x, y, self._pending_data)
                    
                    self._pending_data = None
                    self._pending_is_existing = False
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
    def __init__(self, parent=None, incident_path=None):
        super().__init__(parent)
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowCloseButtonHint)
        self.incident_path = incident_path
        self.mapping_dir = os.path.join(incident_path, "mapping") if incident_path else None
        
        # Initialize the Database Manager
        self.db = IncidentDatabase(incident_path)
        self.maps_data = self._load_maps_data()
        
        self.current_map_file = None
        self.setWindowTitle("Map Editor")
        self.resize(900, 700)
        self._setup_ui()
        self._populate_maps_combo()
        self._connect_signals()

    def _load_maps_data(self):
        """Fetches maps and markers from the DB and translates x_coord/y_coord to x/y for the canvas."""
        maps_data = self.db.get_maps_data()
        for fname, markers in maps_data.items():
            for m in markers:
                m['x'] = m.pop('x_coord', 0)
                m['y'] = m.pop('y_coord', 0)
        return maps_data

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
        
        # ✅ NEW: Delete Map Button
        self.btn_delete_map = QPushButton("Delete Map")
        self.btn_delete_map.setStyleSheet("color: #dc3545;") # Optional: make it red
        
        self.btn_export_map = QPushButton("Export Map...")
        self.btn_export_map.clicked.connect(self._on_export_map)

        self.btn_place = QPushButton("Place Marker...")

        top_toolbar.addWidget(QLabel("Active Map:"))
        top_toolbar.addWidget(self.combo_maps)
        top_toolbar.addWidget(self.btn_create_map)
        top_toolbar.addWidget(self.btn_add_map)
        top_toolbar.addWidget(self.btn_delete_map) # ✅ Add to layout
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
                # Clean up DB if the physical file was deleted externally
                self.db.delete_map(fname)
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

        self.current_map_file = filename
        self.canvas.markers = list(self.maps_data.get(filename, []))
        pixmap_path = os.path.join(self.mapping_dir, filename)
        self.canvas.set_image(QPixmap(pixmap_path))

    def _connect_signals(self):
        self.btn_place.clicked.connect(self._on_place_marker)
        self.btn_add_map.clicked.connect(self._on_add_map)
        self.btn_delete_map.clicked.connect(self._on_delete_map)
        self.btn_box.accepted.connect(self.accept)
        self.canvas.marker_edit_requested.connect(self._on_edit_marker)
        self.canvas.marker_deleted.connect(self._on_delete_marker)
        self.canvas.marker_placed.connect(self._save_data)
        self.canvas.marker_moved.connect(self._save_data)

    def _on_place_marker(self):
        if not self.current_map_file:
            QMessageBox.warning(self, "No Map", "Please add and select a map first.")
            return
        
        # Query the DB for labels specifically on the CURRENT map
        db_markers = self.db.get_markers_for_map(self.current_map_file)
        current_map_labels = {m['label'] for m in db_markers}
        
        # Get the next available global label for the default suggestion
        next_label = self.db.get_next_marker_label()
        
        dialog = MarkerInfoDialog(self, default_label=next_label, current_map_labels=current_map_labels)
        if dialog.exec() == QDialog.Accepted:
            new_data = dialog.get_data()
            new_label = new_data["label"]
            
            # Check if marker already exists on this map
            if new_label in current_map_labels:
                reply = QMessageBox.question(
                    self,
                    "Marker Already Exists",
                    f"A marker with label '{new_label}' already exists on this map.\n\n"
                    "Are you placing it in the same location? Click 'Yes' to confirm and update the position, "
                    "or 'No' to cancel and choose a different label.",
                    QMessageBox.Yes | QMessageBox.No,
                    QMessageBox.No
                )
                if reply != QMessageBox.Yes:
                    return
                
                # User confirmed - set pending data and wait for click
                self.canvas._pending_data = new_data
                self.canvas._pending_is_existing = True
                self.canvas.setCursor(Qt.CrossCursor)
                return
            
            # Insert the new marker into the database (INSERT OR IGNORE handles cross-map reuse)
            self.db.add_marker(
                label=new_label,
                description=new_data.get("description", ""),
                latitude=new_data.get("latitude"),
                longitude=new_data.get("longitude")
            )
            
            self.canvas._pending_data = new_data
            self.canvas._pending_is_existing = False
            self.canvas.setCursor(Qt.CrossCursor)

    def _on_edit_marker(self, idx):
        # ✅ Query the DB for labels specifically on the CURRENT map
        db_markers = self.db.get_markers_for_map(self.current_map_file)
        current_map_labels = {m['label'] for m in db_markers}
        
        marker = self.canvas.markers[idx]
        
        # Note: MarkerInfoDialog ignores the duplicate warning if self.is_edit is True,
        # but passing the accurate list is good practice.
        dialog = MarkerInfoDialog(self, edit_data=marker, current_map_labels=current_map_labels)
        if dialog.exec() == QDialog.Accepted:
            new_data = dialog.get_data()
            
            # Update the marker details in the database
            self.db.update_marker(
                label=new_data["label"],
                description=new_data["description"],
                latitude=new_data["latitude"],
                longitude=new_data["longitude"]
            )
            
            # Update local canvas data
            marker["description"] = new_data["description"]
            marker["latitude"] = new_data["latitude"]
            marker["longitude"] = new_data["longitude"]
            
            self.canvas.update()
            self._save_data()

    def _on_add_map(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Select Map Image", "",
            "PNG Files (*.png);;Images (*.png *.jpg *.jpeg *.bmp)"
        )
        if not path: 
            return
            
        fname = os.path.basename(path)
        
        # ✅ Query the database to check if the map already exists
        existing_maps = self.db.get_maps()
        if fname in existing_maps:
            QMessageBox.critical(
                self, 
                "Duplicate Map", 
                f"A map with the name '{fname}' already exists in this incident.\n\n"
                "Please rename the image file and try again.",
                QMessageBox.Ok
            )
            return

        # If it passes the check, add to database and copy the physical file
        self.db.add_map(path)
        
        # Update local cache and UI
        self.maps_data[fname] = []
        self.combo_maps.addItem(fname)
        self.combo_maps.setCurrentText(fname)
        self.canvas.markers = []
        self.canvas.update()

    def _on_delete_map(self):
        if not self.current_map_file:
            QMessageBox.warning(self, "No Map", "Please select a map to delete.")
            return
        
        # ✅ The exact confirmation message requested
        msg = (
            "Deleting the map will not delete the markers. "
            "If you wish to delete the markers, make sure you do so before you delete this map. "
            "If you wish to transfer the markers to another map, make sure you do so before deleting this map. "
            "Are you sure you want to delete this map?"
        )
        
        reply = QMessageBox.question(
            self, 
            "Confirm Map Deletion", 
            msg, 
            QMessageBox.Yes | QMessageBox.No, 
            QMessageBox.No
        )
        
        if reply == QMessageBox.Yes:
            map_to_delete = self.current_map_file
            
            # 1. Delete from database and physical disk
            self.db.delete_map(map_to_delete)
            
            # 2. Update local cache
            if map_to_delete in self.maps_data:
                del self.maps_data[map_to_delete]
            
            # 3. Update UI combo box safely
            self.combo_maps.blockSignals(True)
            idx = self.combo_maps.findText(map_to_delete)
            if idx != -1:
                self.combo_maps.removeItem(idx)
            
            # 4. Select the next available map, or clear the canvas if none are left
            if self.combo_maps.count() > 0:
                self.combo_maps.setCurrentIndex(0)
            else:
                self.current_map_file = None
                self.canvas.set_image(QPixmap())
                self.canvas.markers = []
                self.canvas.update()
                
            self.combo_maps.blockSignals(False)
            
            # Trigger the map selection logic to load the newly selected map (if any)
            self._on_map_selected(self.combo_maps.currentText())
    
    def _on_delete_marker(self, idx):
        reply = QMessageBox.warning(
            self, "Confirm Deletion",
            f"Delete marker '{self.canvas.markers[idx]['label']}'?\nThis will erase all data associated with this location.",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No
        )
        if reply == QMessageBox.Yes:
            label_to_delete = self.canvas.markers[idx]['label']
            del self.canvas.markers[idx]
            self.canvas.update()
            
            # Delete from DB (cascades to all map placements)
            self.db.delete_marker(label_to_delete)
            
            # Update local cache
            if self.current_map_file:
                self.maps_data[self.current_map_file] = list(self.canvas.markers)

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
        """Syncs the current canvas marker positions to the database."""
        if not self.current_map_file:
            return
        
        # Update local cache
        self.maps_data[self.current_map_file] = list(self.canvas.markers)
        
        # Sync placements to DB (UPSERT logic handles moves and new placements)
        for m in self.canvas.markers:
            self.db.place_marker_on_map(
                marker_label=m['label'],
                map_filename=self.current_map_file,
                x_coord=m['x'],
                y_coord=m['y']
            )

    def update_existing_marker_position(self, label, x, y):
        """Updates only the sitemap_marker table for an existing marker (no changes to marker table)."""
        if not self.current_map_file:
            return
        
        # Find the marker in the current canvas markers
        marker_found = None
        for m in self.canvas.markers:
            if m['label'] == label:
                marker_found = m
                break
        
        if marker_found:
            # Update existing marker position on canvas
            marker_found['x'] = x
            marker_found['y'] = y
        else:
            # Add marker to canvas if not already there
            db_markers = self.db.get_markers_for_map(self.current_map_file)
            marker_data = next((m for m in db_markers if m['label'] == label), None)
            if marker_data:
                self.canvas.markers.append({
                    'label': label,
                    'description': marker_data.get('description', ''),
                    'latitude': marker_data.get('latitude'),
                    'longitude': marker_data.get('longitude'),
                    'x': x,
                    'y': y
                })
        
        # Update local cache
        self.maps_data[self.current_map_file] = list(self.canvas.markers)
        
        # Update only the sitemap_marker table (position on map)
        self.db.place_marker_on_map(
            marker_label=label,
            map_filename=self.current_map_file,
            x_coord=x,
            y_coord=y
        )
