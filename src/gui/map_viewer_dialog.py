import os
from PySide6.QtWidgets import QDialog, QVBoxLayout, QLabel, QComboBox, QWidget
from PySide6.QtGui import QPixmap, QPainter, QPen, QFont, QColor
from PySide6.QtCore import Qt

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
