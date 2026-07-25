import os
import logging
from datetime import datetime
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel,
    QTableWidget, QTableWidgetItem, QScrollArea, QFrame, QSizePolicy,
    QGraphicsDropShadowEffect
)
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor

# ✅ Use reader module for all data access
from datamanagement import reader

logger = logging.getLogger(__name__)

# ──────────────────────────────────────────────────────────
# LIGHT THEME COLORS
# ──────────────────────────────────────────────────────────
BG_COLOR = "#F3F4F6"
CARD_BG = "#FFFFFF"
CARD_BORDER = "#E5E7EB"
TEXT_PRIMARY = "#111827"
TEXT_SECONDARY = "#6B7280"
TABLE_HEADER_BG = "#F9FAFB"

# Clean, vibrant accent colors for light mode
COLORS = {
    "spot": "#3B82F6",       # Blue
    "area": "#8B5CF6",       # Purple
    "spectral": "#EC4899",   # Pink
    "exposure": "#F59E0B",   # Amber
    "plume": "#10B981"       # Emerald
}


class DashboardCard(QFrame):
    """A clean, modern card for the dashboard."""
    
    def __init__(self, title, icon, accent_color, parent=None):
        super().__init__(parent)
        self.accent_color = accent_color
        self.setStyleSheet(f"""
            DashboardCard {{
                background-color: {CARD_BG};
                border: 1px solid {CARD_BORDER};
                border-top: 4px solid {accent_color};
                border-radius: 8px;
            }}
        """)
        
        # Add a subtle drop shadow
        shadow = QGraphicsDropShadowEffect()
        shadow.setBlurRadius(15)
        shadow.setXOffset(0)
        shadow.setYOffset(4)
        shadow.setColor(QColor(0, 0, 0, 25))
        self.setGraphicsEffect(shadow)
        
        self.layout = QVBoxLayout(self)
        self.layout.setContentsMargins(20, 15, 20, 20)
        self.layout.setSpacing(12)
        
        # Header
        header = QHBoxLayout()
        title_lbl = QLabel(f"{icon}  {title}")
        title_lbl.setStyleSheet(f"""
            font-size: 15px; 
            font-weight: 700; 
            color: {TEXT_PRIMARY}; 
        """)
        header.addWidget(title_lbl)
        header.addStretch()
        self.layout.addLayout(header)
        
        # Divider
        divider = QFrame()
        divider.setFixedHeight(1)
        divider.setStyleSheet(f"background-color: {CARD_BORDER};")
        self.layout.addWidget(divider)
    
    def add_widget(self, widget):
        self.layout.addWidget(widget)
    
    def add_layout(self, layout):
        self.layout.addLayout(layout)


class OverviewWidget(QWidget):
    """Clean, light-themed grid-based overview widget."""
    
    def __init__(self, incident_path, parent=None):
        super().__init__(parent)
        self.incident_path = incident_path
        
        # Apply global light theme
        self.setStyleSheet(f"""
            QWidget {{ background-color: {BG_COLOR}; color: {TEXT_PRIMARY}; }}
            QScrollArea {{ border: none; background-color: transparent; }}
            QScrollBar:vertical {{
                border: none; background: {BG_COLOR}; width: 10px; margin: 0px;
            }}
            QScrollBar::handle:vertical {{
                background: #D1D5DB; min-height: 20px; border-radius: 5px;
            }}
            QTableWidget {{ 
                background-color: {CARD_BG}; 
                color: {TEXT_PRIMARY}; 
                border: 1px solid {CARD_BORDER}; 
                border-radius: 4px;
                gridline-color: {CARD_BORDER};
                font-size: 12px;
            }}
            QTableWidget::item {{ padding: 4px; }}
            QTableWidget::item:alternate {{ background-color: #F9FAFB; }}
            QHeaderView::section {{ 
                background-color: {TABLE_HEADER_BG}; 
                color: {TEXT_SECONDARY}; 
                border: none; 
                border-bottom: 1px solid {CARD_BORDER};
                padding: 6px; 
                font-weight: 600;
                font-size: 11px;
            }}
        """)
        
        self._setup_ui()
        self._load_data()
    
    def refresh(self):
        self._load_data()
    
    def _setup_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(30, 30, 30, 30)
        
        # Dashboard Title
        title = QLabel(f"Incident Overview")
        title.setStyleSheet(f"font-size: 24px; font-weight: 800; color: {TEXT_PRIMARY};")
        main_layout.addWidget(title)
        
        subtitle = QLabel(os.path.basename(self.incident_path))
        subtitle.setStyleSheet(f"font-size: 14px; color: {TEXT_SECONDARY}; margin-bottom: 20px;")
        main_layout.addWidget(subtitle)
        
        # Grid Layout for the 5 cards (3 columns to ensure equal sizing)
        grid = QGridLayout()
        grid.setSpacing(20)
        
        # 1. Spot Readings
        self.spot_card = DashboardCard("Spot Readings", "📍", COLORS["spot"])
        self.spot_stats = self._create_stats_row(COLORS["spot"])
        self.spot_card.add_layout(self.spot_stats)
        self.spot_card.add_widget(self._create_section_header("Recent Activity", COLORS["spot"]))
        self.spot_table = self._create_styled_table()
        self.spot_card.add_widget(self.spot_table)
        
        # 2. Area Readings
        self.area_card = DashboardCard("Area Readings", "📡", COLORS["area"])
        self.area_stats = self._create_stats_row(COLORS["area"])
        self.area_card.add_layout(self.area_stats)
        self.area_card.add_widget(self._create_section_header("Recent Activity", COLORS["area"]))
        self.area_table = self._create_styled_table()
        self.area_card.add_widget(self.area_table)
        
        # 3. Spectral Results (No Sites, No Analytes in top row)
        self.spectral_card = DashboardCard("Spectral Results", "🔬", COLORS["spectral"])
        self.spectral_stats = self._create_stats_row(COLORS["spectral"], show_sites=False, show_analytes=False)
        self.spectral_card.add_layout(self.spectral_stats)
        self.spectral_card.add_widget(self._create_section_header("Chemicals Identified", COLORS["spectral"]))
        self.spectral_chems_lbl = QLabel("None")
        self.spectral_chems_lbl.setWordWrap(True)
        self.spectral_chems_lbl.setStyleSheet(f"color: {TEXT_SECONDARY}; font-size: 13px; padding: 5px;")
        self.spectral_card.add_widget(self.spectral_chems_lbl)
        
        # 4. Exposures (No Sites in top row)
        self.exposure_card = DashboardCard("Exposures", "🦺", COLORS["exposure"])
        self.exposure_stats = self._create_stats_row(COLORS["exposure"], show_sites=False)
        self.exposure_card.add_layout(self.exposure_stats)
        self.exposure_card.add_widget(self._create_section_header("Recent Activity", COLORS["exposure"]))
        self.exposure_table = self._create_styled_table()
        self.exposure_card.add_widget(self.exposure_table)
        
        # 5. Plumes (No Sites, No Analytes in top row)
        self.plume_card = DashboardCard("Plumes", "💨", COLORS["plume"])
        self.plume_stats = self._create_stats_row(COLORS["plume"], show_sites=False, show_analytes=False)
        self.plume_card.add_layout(self.plume_stats)
        self.plume_card.add_widget(self._create_section_header("Model Files", COLORS["plume"]))
        plume_scroll = QScrollArea()
        plume_scroll.setWidgetResizable(True)
        plume_scroll.setMaximumHeight(140)
        self.plume_table = self._create_styled_table()
        plume_scroll.setWidget(self.plume_table)
        self.plume_card.add_widget(plume_scroll)
        
        # Arrange in a 3-column grid for uniform sizing
        grid.addWidget(self.spot_card, 0, 0)
        grid.addWidget(self.area_card, 0, 1)
        grid.addWidget(self.spectral_card, 0, 2)
        grid.addWidget(self.exposure_card, 1, 0)
        grid.addWidget(self.plume_card, 1, 1)
        
        # Ensure columns and rows stretch equally to fill the space
        grid.setColumnStretch(0, 1)
        grid.setColumnStretch(1, 1)
        grid.setColumnStretch(2, 1)
        grid.setRowStretch(0, 1)
        grid.setRowStretch(1, 1)
        
        main_layout.addLayout(grid)
        main_layout.addStretch()
    
    def _create_stats_row(self, color, show_sites=True, show_analytes=True):
        """Creates a horizontal row of big stat numbers."""
        row = QHBoxLayout()
        row.setSpacing(15)
        
        # Count
        row.addLayout(self._create_stat_block("0", "Total", color, "count"))
        
        # Date Range (Special block)
        range_block = QVBoxLayout()
        range_block.setAlignment(Qt.AlignCenter)
        val_lbl = QLabel("N/A")
        val_lbl.setStyleSheet(f"font-size: 12px; font-weight: 600; color: {TEXT_PRIMARY};")
        val_lbl.setAlignment(Qt.AlignCenter)
        name_lbl = QLabel("DATE RANGE")
        name_lbl.setStyleSheet(f"font-size: 9px; font-weight: 700; color: {TEXT_SECONDARY};")
        name_lbl.setAlignment(Qt.AlignCenter)
        range_block.addWidget(val_lbl)
        range_block.addWidget(name_lbl)
        row.addLayout(range_block)
        setattr(self, f"_temp_range_lbl_{color}", val_lbl)
        
        if show_sites:
            row.addLayout(self._create_stat_block("0", "Sites", color, "sites"))
        if show_analytes:
            row.addLayout(self._create_stat_block("0", "Analytes", color, "analytes"))
        
        row.addStretch()
        return row
    
    def _create_stat_block(self, value, label, color, attr_name):
        """Creates a single big stat block."""
        block = QVBoxLayout()
        block.setAlignment(Qt.AlignCenter)
        
        val_lbl = QLabel(str(value))
        val_lbl.setStyleSheet(f"font-size: 28px; font-weight: 800; color: {color};")
        val_lbl.setAlignment(Qt.AlignCenter)
        
        name_lbl = QLabel(label.upper())
        name_lbl.setStyleSheet(f"font-size: 9px; font-weight: 700; color: {TEXT_SECONDARY}; letter-spacing: 0.5px;")
        name_lbl.setAlignment(Qt.AlignCenter)
        
        block.addWidget(val_lbl)
        block.addWidget(name_lbl)
        setattr(self, f"lbl_{attr_name}_{color}", val_lbl)
        return block
    
    def _create_section_header(self, text, color):
        lbl = QLabel(text.upper())
        lbl.setStyleSheet(f"font-size: 10px; font-weight: 700; color: {color}; letter-spacing: 0.5px; margin-top: 5px;")
        return lbl
    
    def _create_styled_table(self):
        table = QTableWidget()
        table.setEditTriggers(QTableWidget.NoEditTriggers)
        table.setAlternatingRowColors(True)
        table.verticalHeader().setVisible(False)
        table.horizontalHeader().setStretchLastSection(True)
        table.setMaximumHeight(120)
        table.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        return table
    
    # ─────────────────────────────────────────────────────────
    # DATA LOADING (via reader module)
    # ─────────────────────────────────────────────────────────
    
    def _load_data(self):
        try:
            self._load_spot()
            self._load_area()
            self._load_spectral()
            self._load_exposure()
            self._load_plume()
        except Exception as e:
            logger.error(f"Failed to load overview data: {e}")
    
    def _update_stats(self, color, count, date_range, sites=None, analytes=None):
        getattr(self, f"lbl_count_{color}").setText(str(count))
        getattr(self, f"_temp_range_lbl_{color}").setText(date_range)
        if sites is not None:
            getattr(self, f"lbl_sites_{color}").setText(str(sites))
        if analytes is not None:
            getattr(self, f"lbl_analytes_{color}").setText(str(analytes))
    
    def _load_spot(self):
        # ✅ Use reader module
        summary = reader.get_data_summary(self.incident_path, "spot")
        recent = reader.get_recent_readings(self.incident_path, "spot", limit=5)
        
        min_date = summary.get("min_date") or "-"
        max_date = summary.get("max_date") or "-"
        dr = f"{min_date} to {max_date}"
        
        self._update_stats(
            COLORS["spot"], 
            summary.get("count", 0), 
            dr, 
            summary.get("sites_count", 0), 
            summary.get("analytes_count", 0)
        )
        
        # Format recent readings for table
        table_data = []
        for r in recent:
            table_data.append([
                r.get("site", "-"),
                r.get("device", "-"),
                r.get("logtime", "-"),
                r.get("analyte", "-"),
                r.get("value", "-")
            ])
        
        self._populate_table(self.spot_table, ["Site", "Device", "Time", "Analyte", "Value"], table_data)
    
    def _load_area(self):
        # ✅ Use reader module
        summary = reader.get_data_summary(self.incident_path, "area")
        recent = reader.get_recent_readings(self.incident_path, "area", limit=5)
        
        min_date = summary.get("min_date") or "-"
        max_date = summary.get("max_date") or "-"
        dr = f"{min_date} to {max_date}"
        
        self._update_stats(
            COLORS["area"], 
            summary.get("count", 0), 
            dr, 
            summary.get("sites_count", 0), 
            summary.get("analytes_count", 0)
        )
        
        # Format recent readings for table
        table_data = []
        for r in recent:
            table_data.append([
                r.get("device", "-"),
                r.get("logtime", "-"),
                r.get("analyte", "-"),
                r.get("value", "-")
            ])
        
        self._populate_table(self.area_table, ["Device", "Time", "Analyte", "Value"], table_data)
    
    def _load_spectral(self):
        # ✅ Use reader module
        summary = reader.get_data_summary(self.incident_path, "spectral")
        chems = reader.get_spectral_chemicals(self.incident_path)
        
        min_date = summary.get("min_date") or "-"
        max_date = summary.get("max_date") or "-"
        dr = f"{min_date} to {max_date}"
        
        self._update_stats(COLORS["spectral"], summary.get("count", 0), dr)
        
        self.spectral_chems_lbl.setText(", ".join(chems) if chems else "None identified yet.")
    
    def _load_exposure(self):
        # ✅ Use reader module
        summary = reader.get_data_summary(self.incident_path, "exposure")
        recent = reader.get_recent_readings(self.incident_path, "exposure", limit=5)
        
        min_date = summary.get("min_date") or "-"
        max_date = summary.get("max_date") or "-"
        dr = f"{min_date} to {max_date}"
        
        self._update_stats(
            COLORS["exposure"], 
            summary.get("count", 0), 
            dr, 
            analytes=summary.get("analytes_count", 0)
        )
        
        # Format recent exposures for table
        table_data = []
        for r in recent:
            table_data.append([
                r.get("identifier", "-"),
                r.get("start_dt", "-"),
                r.get("stop_dt", "-"),
                r.get("area", "-")
            ])
        
        self._populate_table(self.exposure_table, ["ID", "Start", "Stop", "Area"], table_data)
    
    def _load_plume(self):
        # ✅ Use reader module
        summary = reader.get_data_summary(self.incident_path, "plume")
        plumes = reader.get_plume_summary(self.incident_path)
        
        min_date = summary.get("min_date") or "-"
        max_date = summary.get("max_date") or "-"
        dr = f"{min_date} to {max_date}"
        
        self._update_stats(COLORS["plume"], summary.get("count", 0), dr)
        
        # Format plumes for table with local time conversion
        table_data = []
        for p in plumes:
            file_name = p.get("file_name", "-")
            model_dt_str = p.get("model_dt", "")
            
            # Convert to local time
            local_time_str = model_dt_str or "-"
            if model_dt_str:
                try:
                    clean_str = model_dt_str.replace('Z', '+00:00')
                    dt = datetime.fromisoformat(clean_str)
                    local_time_str = dt.astimezone().strftime('%Y-%m-%d %H:%M:%S') if dt.tzinfo else dt.strftime('%Y-%m-%d %H:%M:%S')
                except Exception:
                    local_time_str = model_dt_str
            
            table_data.append([file_name, local_time_str])
        
        self._populate_table(self.plume_table, ["File Name", "Model Datetime (Local)"], table_data)
    
    def _populate_table(self, table, headers, rows):
        table.setColumnCount(len(headers))
        table.setHorizontalHeaderLabels(headers)
        table.setRowCount(len(rows))
        
        for r, row in enumerate(rows):
            for c, val in enumerate(row):
                item = QTableWidgetItem(str(val) if val is not None else "-")
                item.setForeground(QColor(TEXT_SECONDARY) if c > 0 else QColor(TEXT_PRIMARY))
                table.setItem(r, c, item)
        
        table.resizeColumnsToContents()
