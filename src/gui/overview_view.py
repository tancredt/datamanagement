import os
import logging
from datetime import datetime
import pandas as pd
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel,
    QTableWidget, QTableWidgetItem, QScrollArea, QFrame, QSizePolicy,
    QGraphicsDropShadowEffect
)
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor

from datamanagement.filter import FilterManager, DEVICE_KEY_MAP
from datamanagement.reader import (
    read_area_data, read_spot_data,
    read_spectral_data, read_exposure_data
)
from datamanagement.db_manager import IncidentDatabase

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

COLORS = {
    "spot":     "#3B82F6",
    "area":     "#8B5CF6",
    "spectral": "#EC4899",
    "exposure": "#F59E0B",
    "plume":    "#10B981",
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
        shadow = QGraphicsDropShadowEffect()
        shadow.setBlurRadius(15)
        shadow.setXOffset(0)
        shadow.setYOffset(4)
        shadow.setColor(QColor(0, 0, 0, 25))
        self.setGraphicsEffect(shadow)

        self.layout = QVBoxLayout(self)
        self.layout.setContentsMargins(20, 15, 20, 20)
        self.layout.setSpacing(12)

        header = QHBoxLayout()
        title_lbl = QLabel(f"{icon}  {title}")
        title_lbl.setStyleSheet(f"font-size: 15px; font-weight: 700; color: {TEXT_PRIMARY};")
        header.addWidget(title_lbl)
        header.addStretch()
        self.layout.addLayout(header)

        divider = QFrame()
        divider.setFixedHeight(1)
        divider.setStyleSheet(f"background-color: {CARD_BORDER};")
        self.layout.addWidget(divider)

    def add_widget(self, widget):
        self.layout.addWidget(widget)

    def add_layout(self, layout):
        self.layout.addLayout(layout)


class OverviewWidget(QWidget):
    """Clean, light-themed grid-based overview widget using FilterManager."""

    def __init__(self, incident_path, parent=None):
        super().__init__(parent)
        self.incident_path = incident_path
        self.db = IncidentDatabase(incident_path) if incident_path else None

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

    # ─────────────────────────────────────────────────────────
    # FILTER LOADING VIA FilterManager
    # ─────────────────────────────────────────────────────────
    def _load_filters(self, data_type):
        """Load filters for a data type using FilterManager."""
        try:
            filter_manager = FilterManager(self.incident_path, data_type)
            filters = filter_manager.load_filters()
            if (
                not filters
                or filters.get("start_time") is None
                or filters.get("stop_time") is None
            ):
                return self._get_default_filters(data_type)
            return filters
        except Exception as e:
            logger.error(f"Failed to load filters for {data_type}: {e}")
            return self._get_default_filters(data_type)

    def _get_default_filters(self, data_type):
        """Generate default filters using DB metadata."""
        now = pd.Timestamp.now().replace(second=0, microsecond=0)
        data_start = now - pd.Timedelta(days=1)
        data_stop = now

        if self.db:
            try:
                min_ts, max_ts = self.db.get_data_time_range(data_type)
                if min_ts and max_ts:
                    data_start = pd.to_datetime(min_ts)
                    data_stop = pd.to_datetime(max_ts)
            except Exception as e:
                logger.warning(f"Could not query time range from DB: {e}")

        device_key = DEVICE_KEY_MAP.get(data_type, "selected_area_devices")
        devices = self.db.get_devices(data_type) if self.db else []
        markers = self.db.get_markers() if self.db else []
        analytes_data = self.db.get_analytes() if self.db else []
        analytes = [a["label"] for a in analytes_data]

        return {
            "start_time": data_start,
            "stop_time": data_stop,
            "interval": "Raw",
            "group_by": "Device",
            "only_valid": False,
            "selected_sites": ["Unassigned"] + markers,
            device_key: devices,
            "selected_analytes": analytes,
            "threshold_level": None,
            "data_type": data_type,
        }

    # ─────────────────────────────────────────────────────────
    # UI SETUP
    # ─────────────────────────────────────────────────────────
    def _setup_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(30, 30, 30, 30)

        title = QLabel("Incident Overview")
        title.setStyleSheet("font-size: 24px; font-weight: 800; color: #111827;")
        main_layout.addWidget(title)

        subtitle = QLabel(os.path.basename(self.incident_path))
        subtitle.setStyleSheet("font-size: 14px; color: #6B7280; margin-bottom: 20px;")
        main_layout.addWidget(subtitle)

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

        # 3. Spectral Results
        self.spectral_card = DashboardCard("Spectral Results", "🔬", COLORS["spectral"])
        self.spectral_stats = self._create_stats_row(COLORS["spectral"], show_sites=False, show_analytes=False)
        self.spectral_card.add_layout(self.spectral_stats)
        self.spectral_card.add_widget(self._create_section_header("Chemicals Identified", COLORS["spectral"]))
        self.spectral_chems_lbl = QLabel("None")
        self.spectral_chems_lbl.setWordWrap(True)
        self.spectral_chems_lbl.setStyleSheet(f"color: {TEXT_SECONDARY}; font-size: 13px; padding: 5px;")
        self.spectral_card.add_widget(self.spectral_chems_lbl)

        # 4. Exposures
        self.exposure_card = DashboardCard("Exposures", "🦺", COLORS["exposure"])
        self.exposure_stats = self._create_stats_row(COLORS["exposure"], show_sites=False)
        self.exposure_card.add_layout(self.exposure_stats)
        self.exposure_card.add_widget(self._create_section_header("Recent Activity", COLORS["exposure"]))
        self.exposure_table = self._create_styled_table()
        self.exposure_card.add_widget(self.exposure_table)

        # 5. Plumes
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

        grid.addWidget(self.spot_card, 0, 0)
        grid.addWidget(self.area_card, 0, 1)
        grid.addWidget(self.spectral_card, 0, 2)
        grid.addWidget(self.exposure_card, 1, 0)
        grid.addWidget(self.plume_card, 1, 1)
        grid.setColumnStretch(0, 1)
        grid.setColumnStretch(1, 1)
        grid.setColumnStretch(2, 1)
        grid.setRowStretch(0, 1)
        grid.setRowStretch(1, 1)

        main_layout.addLayout(grid)
        main_layout.addStretch()

    def _create_stats_row(self, color, show_sites=True, show_analytes=True):
        row = QHBoxLayout()
        row.setSpacing(15)
        row.addLayout(self._create_stat_block("0", "Total", color, "count"))

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
    # DATA LOADING (via FilterManager + reader)
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
        filters = self._load_filters("spot")
        device_key = DEVICE_KEY_MAP.get("spot", "selected_spot_devices")

        df = read_spot_data(
            self.incident_path,
            start_time=filters.get("start_time"),
            stop_time=filters.get("stop_time"),
            devices=filters.get(device_key),
            sites=filters.get("selected_sites"),
            analytes=filters.get("selected_analytes"),
        )

        if df is None or df.empty:
            self._update_stats(COLORS["spot"], 0, "N/A", 0, 0)
            self._populate_table(self.spot_table, ["Site", "Device", "Time", "Analyte", "Value"], [])
            return

        count = len(df)
        min_date = df["LOG TIME"].min()
        max_date = df["LOG TIME"].max()
        sites_count = df["SITE"].nunique()
        analyte_cols = [c for c in df.columns if c in (filters.get("selected_analytes") or [])]
        analytes_count = len([c for c in analyte_cols if df[c].notna().any()])

        dr = f"{min_date.strftime('%Y-%m-%d')} to {max_date.strftime('%Y-%m-%d')}"
        self._update_stats(COLORS["spot"], count, dr, sites_count, analytes_count)

        # Recent activity: last 5 rows
        recent = df.tail(5).sort_values("LOG TIME", ascending=False)
        table_data = []
        for _, r in recent.iterrows():
            # Find the first non-null analyte value
            analyte_val = "-"
            analyte_name = "-"
            for col in analyte_cols:
                if pd.notna(r.get(col)):
                    analyte_name = col
                    analyte_val = r[col]
                    break
            table_data.append([
                r.get("SITE", "-"),
                r.get("DEVICE", "-"),
                r["LOG TIME"].strftime("%Y-%m-%d %H:%M") if pd.notna(r.get("LOG TIME")) else "-",
                analyte_name,
                analyte_val,
            ])
        self._populate_table(self.spot_table, ["Site", "Device", "Time", "Analyte", "Value"], table_data)

    def _load_area(self):
        filters = self._load_filters("area")
        device_key = DEVICE_KEY_MAP.get("area", "selected_area_devices")

        df = read_area_data(
            self.incident_path,
            start_time=filters.get("start_time"),
            stop_time=filters.get("stop_time"),
            devices=filters.get(device_key),
            sites=filters.get("selected_sites"),
            analytes=filters.get("selected_analytes"),
            only_valid=filters.get("only_valid", False),
        )

        if df is None or df.empty:
            self._update_stats(COLORS["area"], 0, "N/A", 0, 0)
            self._populate_table(self.area_table, ["Device", "Time", "Analyte", "Value"], [])
            return

        count = len(df)
        min_date = df["LOG TIME"].min()
        max_date = df["LOG TIME"].max()
        sites_count = df["SITE"].nunique() if "SITE" in df.columns else 0
        analyte_cols = [c for c in df.columns if c in (filters.get("selected_analytes") or [])]
        analytes_count = len([c for c in analyte_cols if df[c].notna().any()])

        dr = f"{min_date.strftime('%Y-%m-%d')} to {max_date.strftime('%Y-%m-%d')}"
        self._update_stats(COLORS["area"], count, dr, sites_count, analytes_count)

        # Recent activity: last 5 rows
        recent = df.tail(5).sort_values("LOG TIME", ascending=False)
        table_data = []
        for _, r in recent.iterrows():
            analyte_val = "-"
            analyte_name = "-"
            for col in analyte_cols:
                if pd.notna(r.get(col)):
                    analyte_name = col
                    analyte_val = r[col]
                    break
            table_data.append([
                r.get("DEVICE", "-"),
                r["LOG TIME"].strftime("%Y-%m-%d %H:%M") if pd.notna(r.get("LOG TIME")) else "-",
                analyte_name,
                analyte_val,
            ])
        self._populate_table(self.area_table, ["Device", "Time", "Analyte", "Value"], table_data)

    def _load_spectral(self):
        filters = self._load_filters("spectral")
        device_key = DEVICE_KEY_MAP.get("spectral", "selected_spectral_devices")

        df = read_spectral_data(
            self.incident_path,
            start_time=filters.get("start_time"),
            stop_time=filters.get("stop_time"),
            devices=filters.get(device_key),
            sites=filters.get("selected_sites"),
        )

        if df is None or df.empty:
            self._update_stats(COLORS["spectral"], 0, "N/A")
            self.spectral_chems_lbl.setText("None identified yet.")
            return

        count = len(df)
        min_date = df["LOG TIME"].min()
        max_date = df["LOG TIME"].max()
        dr = f"{min_date.strftime('%Y-%m-%d')} to {max_date.strftime('%Y-%m-%d')}"
        self._update_stats(COLORS["spectral"], count, dr)

        # Aggregate unique chemicals
        unique_chemicals = set()
        for chem_str in df.get("chemicals_identified", []):
            if chem_str and pd.notna(chem_str):
                for chem in str(chem_str).split(","):
                    cleaned = chem.strip()
                    if cleaned:
                        unique_chemicals.add(cleaned)

        if unique_chemicals:
            self.spectral_chems_lbl.setText(", ".join(sorted(unique_chemicals)))
        else:
            self.spectral_chems_lbl.setText("None identified yet.")

    def _load_exposure(self):
        filters = self._load_filters("exposure")
        device_key = DEVICE_KEY_MAP.get("exposure", "selected_exposure_identifiers")

        df = read_exposure_data(
            self.incident_path,
            start_time=filters.get("start_time"),
            stop_time=filters.get("stop_time"),
            devices=filters.get(device_key),
            analytes=filters.get("selected_analytes"),
        )

        if df is None or df.empty:
            self._update_stats(COLORS["exposure"], 0, "N/A", analytes=0)
            self._populate_table(self.exposure_table, ["ID", "Start", "Stop", "Area"], [])
            return

        count = len(df)
        min_date = df["LOG TIME"].min()
        max_date = df["LOG TIME"].max()
        analyte_cols = [c for c in df.columns if any(
            c.endswith(s) for s in ("_min", "_max", "_mean")
        )]
        analytes_count = len(set(c.rsplit("_", 1)[0] for c in analyte_cols if df[c].notna().any()))

        dr = f"{min_date.strftime('%Y-%m-%d')} to {max_date.strftime('%Y-%m-%d')}"
        self._update_stats(COLORS["exposure"], count, dr, analytes=analytes_count)

        # Recent activity: last 5 rows
        recent = df.tail(5).sort_values("LOG TIME", ascending=False)
        table_data = []
        for _, r in recent.iterrows():
            table_data.append([
                r.get("IDENTIFIER", "-"),
                r["LOG TIME"].strftime("%Y-%m-%d %H:%M") if pd.notna(r.get("LOG TIME")) else "-",
                "-",
                r.get("SITE", "-"),
            ])
        self._populate_table(self.exposure_table, ["ID", "Start", "Stop", "Area"], table_data)

    def _load_plume(self):
        filters = self._load_filters("plume")

        # Plumes use time range from filters
        start_time = filters.get("start_time")
        stop_time = filters.get("stop_time")

        # Get plumes from DB
        if not self.db:
            self._update_stats(COLORS["plume"], 0, "N/A")
            self._populate_table(self.plume_table, ["File Name", "Model Datetime (Local)"], [])
            return

        plumes = self.db.get_plumes()

        # Filter plumes by time range
        filtered_plumes = []
        for p in plumes:
            model_dt_str = p.get("model_dt", "")
            if not model_dt_str:
                continue
            try:
                clean_str = model_dt_str.replace('Z', '+00:00')
                dt = datetime.fromisoformat(clean_str)
                if dt.tzinfo:
                    dt = dt.astimezone().replace(tzinfo=None)
                # Apply time filter
                if start_time and dt < start_time:
                    continue
                if stop_time and dt > stop_time:
                    continue
                filtered_plumes.append((p.get("file_name", "-"), dt))
            except Exception:
                filtered_plumes.append((p.get("file_name", "-"), None))

        count = len(filtered_plumes)
        if filtered_plumes:
            dates = [dt for _, dt in filtered_plumes if dt is not None]
            if dates:
                min_date = min(dates)
                max_date = max(dates)
                dr = f"{min_date.strftime('%Y-%m-%d')} to {max_date.strftime('%Y-%m-%d')}"
            else:
                dr = "N/A"
        else:
            dr = "N/A"

        self._update_stats(COLORS["plume"], count, dr)

        table_data = []
        for file_name, dt in filtered_plumes:
            local_time_str = dt.strftime('%Y-%m-%d %H:%M:%S') if dt else "-"
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
