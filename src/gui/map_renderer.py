import os
import tempfile
import logging
from PySide6.QtGui import QPixmap, QPainter, QPen, QFont, QColor
from PySide6.QtCore import Qt

logger = logging.getLogger(__name__)

# Default visual settings for map markers
DEFAULT_OPTIONS = {
    "circle_radius": 8,
    "font_family": "Arial",
    "font_size": 10,
    "font_bold": True,
    "border_color": QColor("red"),
    "fill_color": QColor("yellow"),
    "text_color": QColor("black"),
    "border_width": 2,
    "text_offset_x": 12,
    "text_offset_y": 5,
    "scale_factor": 1.0, # Used to keep marker sizes visually constant when image is scaled
}

def _get_opt(options, key):
    return options.get(key, DEFAULT_OPTIONS.get(key))

def draw_markers(painter: QPainter, markers: list, options: dict = None):
    """
    Core drawing function. Draws markers on the given QPainter.
    Markers should be a list of dicts with 'x', 'y', 'label', and optionally 'text'.
    """
    if options is None:
        options = {}
        
    radius = _get_opt(options, "circle_radius")
    scale = _get_opt(options, "scale_factor")
    
    # Adjust pen/font sizes based on scale factor (crucial for scaled previews)
    actual_border_width = max(1.0, _get_opt(options, "border_width") / scale)
    actual_font_size = max(8, int(_get_opt(options, "font_size") / scale))
    
    font = QFont(_get_opt(options, "font_family"), actual_font_size)
    if _get_opt(options, "font_bold"):
        font.setBold(True)
    painter.setFont(font)
    
    offset_x = _get_opt(options, "text_offset_x")
    offset_y = _get_opt(options, "text_offset_y")
    
    for m in markers:
        x = m.get("x")
        y = m.get("y")
        label = m.get("label", "")
        text = m.get("text", "") # Used by SummaryMapView for numerical values
        
        if x is None or y is None:
            continue
            
        # 1. Draw marker circle
        painter.setPen(QPen(_get_opt(options, "border_color"), actual_border_width))
        painter.setBrush(_get_opt(options, "fill_color"))
        painter.drawEllipse(int(x) - radius, int(y) - radius, radius * 2, radius * 2)
        
        # 2. Draw text (label + optional numerical value)
        painter.setPen(QPen(_get_opt(options, "text_color"), max(1.0, 1.0 / scale)))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        
        if text:
            display_text = f"{label}: {text}" if label else str(text)
        else:
            display_text = label
            
        if display_text:
            painter.drawText(int(x) + offset_x, int(y) + offset_y, display_text)

def render_markers_on_pixmap(pixmap: QPixmap, markers: list, options: dict = None) -> QPixmap:
    """
    Creates a copy of the pixmap, draws markers on it, and returns the new pixmap.
    Useful for exporting maps or generating PDFs.
    """
    if pixmap.isNull():
        return pixmap
        
    new_pixmap = pixmap.copy()
    painter = QPainter(new_pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    draw_markers(painter, markers, options)
    painter.end()
    return new_pixmap

def save_rendered_map_to_temp(pixmap: QPixmap, markers: list, options: dict = None, temp_files: list = None) -> str:
    """
    Renders markers on a pixmap and saves it to a temporary PNG file.
    Returns the path to the temporary file.
    Appends the path to temp_files list if provided, for later cleanup.
    """
    rendered_pixmap = render_markers_on_pixmap(pixmap, markers, options)
    if rendered_pixmap.isNull():
        return ""
        
    tmp = tempfile.NamedTemporaryFile(suffix='.png', delete=False)
    tmp_path = tmp.name
    tmp.close()
    
    if rendered_pixmap.save(tmp_path, 'PNG'):
        if temp_files is not None:
            temp_files.append(tmp_path)
        return tmp_path
    return ""
