import os
import sys
import datetime
import pandas as pd
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QComboBox, QPushButton,
    QMessageBox, QFileDialog, QScrollArea, QRadioButton, QButtonGroup, QStackedWidget, QSizePolicy
)
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QColor, QFont, QPixmap, QPainter, QPen

# Import the new self-contained base class
from base_view import DataView
from datamanagement.db_manager import IncidentDatabase


class SummaryMapCanvas(QWidget):
    """Custom widget to display a map image and overlay summary data at marker locations."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.pixmap = None
        self.markers_data = []

    def set_image(self, pixmap):
        self.pixmap = pixmap
        if self.pixmap and not self.pixmap.isNull():
            self.setFixedSize(self.pixmap.size())
        else:
            self.setFixedSize(800, 600)
        self.update()

    def set_markers(self, markers_data):
        self.markers_data = markers_data
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        
        if self.pixmap and not self.pixmap.isNull():
            painter.drawPixmap(0, 0, self.pixmap)
        else:
            painter.fillRect(self.rect(), QColor(240, 240, 240))
            painter.setPen(QColor(150, 150, 150))
            painter.drawText(self.rect(), Qt.AlignCenter, "No Map Selected or Available")
            painter.end()
            return

        font = QFont("Arial", 10, QFont.Bold)
        painter.setFont(font)

        for m in self.markers_data:
            x, y = m['x'], m['y']
            label = m['label']
            text = m['text']

            # Draw marker circle
            painter.setPen(QPen(QColor("red"), 2))
            painter.setBrush(QColor("yellow"))
            painter.drawEllipse(x-8, y-8, 16, 16)

            # Draw text next to the marker
            painter.setPen(QPen(QColor("black"), 1))
            painter.setBrush(Qt.NoBrush)
            display_text = f"{label}: {text}" if text else f"{label}: N/A"
            painter.drawText(x+12, y+5, display_text)
            
        painter.end()


class SummaryMapView(DataView):
    """
    Self-contained summary map view.
    Loads its own raw data, filters, configs, and map data from the database.
    """
    def __init__(self, incident_path, data_type, map_filenames=None, mapping_dir=None, maps_data=None, parent=None):
        super().__init__(incident_path, data_type, parent)
        
        # ✅ Initialize Database Manager and fetch map data directly
        self.db = IncidentDatabase(incident_path)
        self.mapping_dir = mapping_dir or os.path.join(incident_path, "mapping")
        self.map_filenames = self.db.get_maps()
        self.maps_data = self.db.get_maps_data()
        
        self.plume_data = []
        self.current_plume_index = 0
        
        self._setup_ui()
        self._render()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        # Create a stack to toggle between normal maps and plume animation
        self.stack = QStackedWidget()
        layout.addWidget(self.stack)

        # --- Page 0: Normal Map View ---
        self.normal_page = QWidget()
        normal_layout = QVBoxLayout(self.normal_page)
        normal_layout.setContentsMargins(0, 0, 0, 0)

        map_top_layout = QHBoxLayout()
        
        # Map Selector
        map_top_layout.addWidget(QLabel("<b>Map:</b>"))
        self.summary_map_combo = QComboBox()
        self.summary_map_combo.addItems(self.map_filenames)
        self.summary_map_combo.setMinimumWidth(150)
        self.summary_map_combo.currentTextChanged.connect(self._redraw)
        map_top_layout.addWidget(self.summary_map_combo)

        # ✅ Analyte Selector (Populated from last_filters.json)
        map_top_layout.addWidget(QLabel("<b>Analyte:</b>"))
        self.summary_map_analyte_combo = QComboBox()
        selected_analytes = self.filter_summary.get("selected_analytes", self.available_analytes)
        if not selected_analytes:
            selected_analytes = self.available_analytes
        
        # Ensure it's a list (safety net)
        if isinstance(selected_analytes, str):
            selected_analytes = [selected_analytes]
            
        self.summary_map_analyte_combo.addItems(selected_analytes)
        self.summary_map_analyte_combo.setMinimumWidth(120)
        self.summary_map_analyte_combo.currentTextChanged.connect(self._redraw)
        map_top_layout.addWidget(self.summary_map_analyte_combo)
        map_top_layout.addStretch()

        # Statistic Radio Buttons
        self.summary_map_metric_group = QButtonGroup(self)
        self.rb_map_mean = QRadioButton("Mean")
        self.rb_map_max = QRadioButton("Max")
        self.rb_map_min = QRadioButton("Min")
        self.rb_map_count = QRadioButton("Count")
        self.rb_map_mean.setChecked(True)
        self.summary_map_metric_group.addButton(self.rb_map_mean, 0)
        self.summary_map_metric_group.addButton(self.rb_map_max, 1)
        self.summary_map_metric_group.addButton(self.rb_map_min, 2)
        self.summary_map_metric_group.addButton(self.rb_map_count, 3)
        
        map_top_layout.addWidget(self.rb_map_mean)
        map_top_layout.addWidget(self.rb_map_max)
        map_top_layout.addWidget(self.rb_map_min)
        map_top_layout.addWidget(self.rb_map_count)
        normal_layout.addLayout(map_top_layout)
        self.summary_map_metric_group.idClicked.connect(self._redraw)

        # Canvas & Scroll Area
        self.summary_map_canvas = SummaryMapCanvas()
        map_scroll = QScrollArea()
        map_scroll.setWidgetResizable(False)
        map_scroll.setAlignment(Qt.AlignCenter)
        map_scroll.setWidget(self.summary_map_canvas)
        normal_layout.addWidget(map_scroll, stretch=1)
        
        self.stack.addWidget(self.normal_page)

        # --- Page 1: Plume Slideshow View ---
        self.plume_page = QWidget()
        plume_layout = QVBoxLayout(self.plume_page)
        
        self.plume_title_label = QLabel()
        self.plume_title_label.setAlignment(Qt.AlignCenter)
        self.plume_title_label.setStyleSheet("font-size: 18px; font-weight: bold; padding: 10px")
        plume_layout.addWidget(self.plume_title_label)

        self.plume_image_label = QLabel()
        self.plume_image_label.setAlignment(Qt.AlignCenter)
        self.plume_image_label.setStyleSheet("background-color: black;")
        plume_layout.addWidget(self.plume_image_label, stretch=1)

        # Slideshow Control Bar
        control_layout = QHBoxLayout()
        self.btn_prev_plume = QPushButton("◀ Previous")
        self.btn_next_plume = QPushButton("Next ▶")
        self.btn_play_plume = QPushButton("▶ Play")
        self.btn_stop_plume = QPushButton("⏹ Stop")
        
        btn_style = "QPushButton { padding: 6px 12px; font-weight: bold; }"
        for btn in [self.btn_prev_plume, self.btn_next_plume, self.btn_play_plume, self.btn_stop_plume]:
            btn.setStyleSheet(btn_style)
            
        self.btn_prev_plume.clicked.connect(self._plume_previous)
        self.btn_next_plume.clicked.connect(self._plume_next)
        self.btn_play_plume.clicked.connect(self._plume_play)
        self.btn_stop_plume.clicked.connect(self._plume_stop)
        self.btn_stop_plume.setEnabled(False)
        
        control_layout.addWidget(self.btn_prev_plume)
        control_layout.addWidget(self.btn_next_plume)
        control_layout.addStretch()
        control_layout.addWidget(self.btn_play_plume)
        control_layout.addWidget(self.btn_stop_plume)
        control_layout.addStretch()
        
        self.plume_info_label = QLabel("No plume images loaded.")
        self.plume_info_label.setAlignment(Qt.AlignCenter)
        self.plume_info_label.setStyleSheet("font-size: 14px; font-weight: bold; padding: 8px;")
        control_layout.addWidget(self.plume_info_label)
        
        plume_layout.addLayout(control_layout)
        self.stack.addWidget(self.plume_page)

        # Default to normal page
        self.stack.setCurrentIndex(0)

        # Animation timer (3000ms = 3 seconds)
        self.plume_timer = QTimer(self)
        self.plume_timer.timeout.connect(self._plume_next)

    def export(self):
        """Satisfies the DataView interface. Routes to the correct export method."""
        if self.stack.currentIndex() == 0:
            self._export_map()
        elif self.stack.currentIndex() == 1:
            self._export_plume()

    def _export_map(self):
        selected_map = self.summary_map_combo.currentText()
        if not selected_map:
            QMessageBox.warning(self, "No Map", "Please select a map to export.")
            return

        default_name = os.path.splitext(selected_map)[0] + "_summary.png"
        file_path, _ = QFileDialog.getSaveFileName(
            self, "Export Summary Map", default_name, "PNG Files (*.png);;JPEG Files (*.jpg);;All Files (*)"
        )
        if file_path:
            try:
                pixmap = self.summary_map_canvas.grab()
                if pixmap.save(file_path):
                    QMessageBox.information(self, "Success", f"Summary map exported successfully to:\n{file_path}")
                else:
                    QMessageBox.critical(self, "Error", "Failed to save the summary map image.")
            except Exception as e:
                QMessageBox.critical(self, "Error", f"Failed to export summary map:\n{e}")

    def _export_plume(self):
        if not self.plume_data:
            QMessageBox.warning(self, "No Data", "No plume images loaded.")
            return
            
        dt, filepath = self.plume_data[self.current_plume_index]
        
        # ✅ FIX: Safely get local time (handles both naive and aware datetimes correctly)
        try:
            local_dt = dt.astimezone()
        except Exception:
            local_dt = dt
            
        # ✅ Generate the default file name using the correct local time
        default_name = f"plume_{local_dt.strftime('%Y%m%d_%H%M')}.png"
        
        file_path, _ = QFileDialog.getSaveFileName(
            self, "Export Plume Image", default_name, "PNG Files (*.png);;All Files (*)"
        )
        if file_path:
            try:
                pixmap = self.plume_image_label.grab()
                if pixmap.save(file_path):
                    QMessageBox.information(self, "Success", f"Plume image exported successfully to:\n{file_path}")
                else:
                    QMessageBox.critical(self, "Error", "Failed to save the plume image.")
            except Exception as e:
                QMessageBox.critical(self, "Error", f"Failed to export plume image:\n{e}")
                
    def _load_plumes_for_animation(self):
        """Loads plume data from DB or directory for the slideshow."""
        self.plume_data = []
        plumes_dir = os.path.join(self.incident_path, "plumes")
        
        # Try DB first
        db_plumes = self.db.get_plumes()
        if db_plumes:
            for p in db_plumes:
                file_name = p.get("file_name")
                model_dt_str = p.get("model_dt")
                if not file_name or not model_dt_str:
                    continue
                filepath = os.path.join(plumes_dir, file_name)
                if not os.path.exists(filepath):
                    continue
                try:
                    clean_str = model_dt_str.replace('Z', '+00:00')
                    dt = datetime.datetime.fromisoformat(clean_str)
                    if dt.tzinfo:
                        dt = dt.astimezone()
                    self.plume_data.append((dt, filepath))
                except Exception as e:
                    logger.error(f"Failed to parse plume datetime {model_dt_str}: {e}")
        else:
            # Fallback: scan directory if DB is empty
            if os.path.exists(plumes_dir):
                for f in os.listdir(plumes_dir):
                    if f.lower().endswith(('.png', '.jpg', '.jpeg')):
                        filepath = os.path.join(plumes_dir, f)
                        try:
                            mtime = os.path.getmtime(filepath)
                            dt = datetime.datetime.fromtimestamp(mtime)
                            self.plume_data.append((dt, filepath))
                        except Exception:
                            pass
        
        # Sort chronologically for the slideshow
        self.plume_data.sort(key=lambda x: x[0])
                
    def _render(self):
        """Render the view with current filtered_data."""
        if self.data_type == "plume":
            # ✅ FIX: Load plumes and start the animation
            self._load_plumes_for_animation()
            self.show_plume_animation(self.plume_data)
            return
            
        self.map_filenames = self.db.get_maps()
        self.maps_data = self.db.get_maps_data()

        # Sync map combo box if filenames changed
        current_map = self.summary_map_combo.currentText()
        map_items = [self.summary_map_combo.itemText(i) for i in range(self.summary_map_combo.count())]
        if list(self.map_filenames) != map_items:
            self.summary_map_combo.blockSignals(True)
            self.summary_map_combo.clear()
            self.summary_map_combo.addItems(self.map_filenames)
            if current_map in self.map_filenames:
                self.summary_map_combo.setCurrentText(current_map)
            self.summary_map_combo.blockSignals(False)

        # ✅ Sync analyte combobox with current filter_summary (in case filters changed)
        current_analyte = self.summary_map_analyte_combo.currentText()
        selected_analytes = self.filter_summary.get("selected_analytes", self.available_analytes)
        if not selected_analytes:
            selected_analytes = self.available_analytes
        if isinstance(selected_analytes, str):
            selected_analytes = [selected_analytes]

        current_items = [self.summary_map_analyte_combo.itemText(i) for i in range(self.summary_map_analyte_combo.count())]
        if list(selected_analytes) != current_items:
            self.summary_map_analyte_combo.blockSignals(True)
            self.summary_map_analyte_combo.clear()
            self.summary_map_analyte_combo.addItems(selected_analytes)
            if current_analyte in selected_analytes:
                self.summary_map_analyte_combo.setCurrentText(current_analyte)
            self.summary_map_analyte_combo.blockSignals(False)

        self.show_normal_map()
        self._redraw()

    def update_data(self, *args, **kwargs):
        """Alias for _render to satisfy the DataView interface."""
        self._render()

    def show_normal_map(self):
        self.stack.setCurrentIndex(0)
        self._plume_stop()

    def show_plume_animation(self, plume_data):
        """Switches to the plume page and loads the chronological data."""
        self.stack.setCurrentIndex(1)
        self.plume_data = plume_data
        self.current_plume_index = 0
        self._plume_stop()

        if not self.plume_data:
            self.plume_title_label.setText("")
            self.plume_image_label.setText("No plume images found.")
            self.plume_image_label.setPixmap(QPixmap())
            self.plume_info_label.setText("No plume images loaded.")
            self.btn_prev_plume.setEnabled(False)
            self.btn_next_plume.setEnabled(False)
            self.btn_play_plume.setEnabled(False)
            return

        self.btn_prev_plume.setEnabled(True)
        self.btn_next_plume.setEnabled(True)
        self.btn_play_plume.setEnabled(True)
        self._show_current_plume_frame()

    def _show_current_plume_frame(self):
        if not self.plume_data:
            return

        dt, filepath = self.plume_data[self.current_plume_index]
        local_time_str = dt.strftime('%Y-%m-%d %H:%M')
        self.plume_title_label.setText(f"Air Dispersion Prediction for {local_time_str}")

        pixmap = QPixmap(filepath)
        if not pixmap.isNull():
            label_size = self.plume_image_label.size()
            if label_size.width() > 0 and label_size.height() > 0:
                scaled_pixmap = pixmap.scaled(label_size, Qt.KeepAspectRatio, Qt.SmoothTransformation)
                self.plume_image_label.setPixmap(scaled_pixmap)
            else:
                self.plume_image_label.setPixmap(pixmap)
        else:
            self.plume_image_label.setText("Failed to load image")

        self.plume_info_label.setText(
            f"Local Time: {dt.strftime('%Y-%m-%d %H:%M')} | Frame {self.current_plume_index + 1} of {len(self.plume_data)}"
        )

    def _plume_next(self):
        if not self.plume_data:
            return
        self.current_plume_index += 1
        if self.current_plume_index >= len(self.plume_data):
            self.current_plume_index = 0
        self._show_current_plume_frame()

    def _plume_previous(self):
        if not self.plume_data:
            return
        self.current_plume_index -= 1
        if self.current_plume_index < 0:
            self.current_plume_index = len(self.plume_data) - 1
        self._show_current_plume_frame()

    def _plume_play(self):
        if not self.plume_data:
            return
        self.plume_timer.start(3000)
        self.btn_play_plume.setEnabled(False)
        self.btn_stop_plume.setEnabled(True)

    def _plume_stop(self):
        self.plume_timer.stop()
        self.btn_play_plume.setEnabled(bool(self.plume_data))
        self.btn_stop_plume.setEnabled(False)

    def _redraw(self):
        """Redraws the map overlay based on current filtered_data."""
        selected_map = self.summary_map_combo.currentText()

        # Determine analyte and metric (Report vs Live UI)
        if hasattr(self, '_report_stats_pref'):
            selected_analytes = self.filter_summary.get("selected_analytes", self.available_analytes)
            selected_analyte = selected_analytes[0] if selected_analytes else None
            metric_name = str(self._report_stats_pref).capitalize()
        else:
            selected_analyte = self.summary_map_analyte_combo.currentText()
            metric_id = self.summary_map_metric_group.checkedId()
            metric_map = {0: 'Mean', 1: 'Max', 2: 'Min', 3: 'Count'}
            metric_name = metric_map.get(metric_id, 'Mean')

        if not selected_analyte:
            self.summary_map_canvas.set_markers([])
            return

        if selected_map and selected_map in self.maps_data:
            pixmap_path = os.path.join(self.mapping_dir, selected_map)
            if os.path.exists(pixmap_path):
                self.summary_map_canvas.set_image(QPixmap(pixmap_path))
            else:
                self.summary_map_canvas.set_image(QPixmap())
        else:
            self.summary_map_canvas.set_image(QPixmap())
            self.summary_map_canvas.set_markers([])
            return

        markers_data = []
        markers = self.maps_data.get(selected_map, [])
        
        if (self.filtered_data is not None and 
            not self.filtered_data.empty and 
            'SITE' in self.filtered_data.columns and 
            selected_analyte in self.filtered_data.columns):
            
            # ✅ FIX: Reverted to robust aggregation that works for BOTH raw and aggregated data
            site_aggs = self.filtered_data.groupby('SITE')[selected_analyte].agg(['min', 'max', 'mean', 'count']).reset_index()
            site_aggs.columns = ['SITE', 'Min', 'Max', 'Mean', 'Count']
            
            for m in markers:
                label = str(m.get('label', '')).strip()
                # ✅ Handle both DB keys (x_coord/y_coord) and legacy keys (x/y)
                x = m.get('x_coord', m.get('x', 0))
                y = m.get('y_coord', m.get('y', 0))
                
                # ✅ FIX: Strip whitespace from SITE column to ensure perfect matching with marker labels
                site_row = site_aggs[site_aggs['SITE'].astype(str).str.strip() == label]
                if not site_row.empty:
                    val = site_row.iloc[0][metric_name]
                    # Check for NaN before formatting to prevent "nan" strings
                    if pd.isna(val):
                        text = "N/A"
                    else:
                        dec_pls = self.analyte_dec_pls.get(selected_analyte, 2)
                        if metric_name == 'Count':
                            text = f"{int(val)}"
                        else:
                            text = f"{val:.{dec_pls}f}"
                else:
                    text = "N/A"
                markers_data.append({'x': x, 'y': y, 'label': label, 'text': text})
        else:
            for m in markers:
                label = str(m.get('label', '')).strip()
                # ✅ Handle both DB keys (x_coord/y_coord) and legacy keys (x/y)
                x = m.get('x_coord', m.get('x', 0))
                y = m.get('y_coord', m.get('y', 0))
                markers_data.append({
                    'x': x, 
                    'y': y, 
                    'label': label, 
                    'text': 'N/A'
                })

        self.summary_map_canvas.set_markers(markers_data)
