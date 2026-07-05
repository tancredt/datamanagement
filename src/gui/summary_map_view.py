import os
import sys
import pandas as pd
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QComboBox, QPushButton,
    QMessageBox, QFileDialog, QScrollArea, QRadioButton, QButtonGroup
)
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QFont, QPixmap, QPainter, QPen

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
            
            painter.setPen(QPen(QColor("red"), 2))
            painter.setBrush(QColor("yellow"))
            painter.drawEllipse(x-8, y-8, 16, 16)
            
            painter.setPen(QPen(QColor("black"), 1))
            painter.setBrush(Qt.NoBrush)
            display_text = f"{label}: {text}" if text else f"{label}: N/A"
            painter.drawText(x+12, y+5, display_text)
            
        painter.end()

class SummaryMapView(QWidget):
    def __init__(self, map_filenames, available_analytes, analyte_dec_pls, mapping_dir, maps_data, parent=None):
        super().__init__(parent)
        self.map_filenames = map_filenames
        self.available_analytes = available_analytes
        self.analyte_dec_pls = analyte_dec_pls
        self.mapping_dir = mapping_dir
        self.maps_data = maps_data
        self.filtered_data = None
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        map_top_layout = QHBoxLayout()
        
        map_top_layout.addWidget(QLabel("<b>Map:</b>"))
        self.summary_map_combo = QComboBox()
        self.summary_map_combo.addItems(self.map_filenames)
        self.summary_map_combo.setMinimumWidth(150)
        self.summary_map_combo.currentTextChanged.connect(self._redraw)
        map_top_layout.addWidget(self.summary_map_combo)
        
        map_top_layout.addWidget(QLabel("<b>Analyte:</b>"))
        self.summary_map_analyte_combo = QComboBox()
        self.summary_map_analyte_combo.addItems(self.available_analytes)
        self.summary_map_analyte_combo.setMinimumWidth(120)
        self.summary_map_analyte_combo.currentTextChanged.connect(self._redraw)
        map_top_layout.addWidget(self.summary_map_analyte_combo)
        
        self.btn_export_summary_map = QPushButton("Export Map...")
        self.btn_export_summary_map.setMinimumHeight(28)
        map_top_layout.addWidget(self.btn_export_summary_map)
        
        map_top_layout.addStretch()
        
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
        
        layout.addLayout(map_top_layout)
        
        # Redraw automatically when the user changes map, analyte, or metric
        self.summary_map_metric_group.idClicked.connect(self._redraw)
        
        self.summary_map_canvas = SummaryMapCanvas()
        map_scroll = QScrollArea()
        map_scroll.setWidgetResizable(False)
        map_scroll.setAlignment(Qt.AlignCenter)
        map_scroll.setWidget(self.summary_map_canvas)
        layout.addWidget(map_scroll, stretch=1)

    def connect_signals(self, export_callback):
        self.btn_export_summary_map.clicked.connect(export_callback)

    def update_data(self, filtered_data):
        """Receives new filtered data and recalculates the map overlays."""
        self.filtered_data = filtered_data
        self._redraw()

    def _redraw(self):
        selected_map = self.summary_map_combo.currentText()
        selected_analyte = self.summary_map_analyte_combo.currentText()
        metric_id = self.summary_map_metric_group.checkedId()
         
        metric_map = {0: 'Mean', 1: 'Max', 2: 'Min', 3: 'Count'}
        metric_name = metric_map.get(metric_id, 'Mean')
        
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
        
        if self.filtered_data is not None and not self.filtered_data.empty and 'SITE' in self.filtered_data.columns and selected_analyte in self.filtered_data.columns:
            site_aggs = self.filtered_data.groupby('SITE')[selected_analyte].agg(['min', 'max', 'mean', 'count']).reset_index()
            site_aggs.columns = ['SITE', 'Min', 'Max', 'Mean', 'Count']
            
            for m in markers:
                label = m.get('label', '')
                x = m.get('x', 0)
                y = m.get('y', 0)
                
                site_row = site_aggs[site_aggs['SITE'] == label]
                if not site_row.empty:
                    val = site_row.iloc[0][metric_name]
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
                markers_data.append({'x': m.get('x', 0), 'y': m.get('y', 0), 'label': m.get('label', ''), 'text': 'N/A'})
                
        self.summary_map_canvas.set_markers(markers_data)

    def export_map(self):
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
