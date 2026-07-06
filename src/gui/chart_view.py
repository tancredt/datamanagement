import os
import sys
import pandas as pd
import matplotlib
matplotlib.use('QtAgg')
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.backends.backend_qtagg import NavigationToolbar2QT as NavigationToolbar
from PySide6.QtWidgets import QWidget, QVBoxLayout
from PySide6.QtGui import QColor

THRESHOLD_EXCEEDED_COLOR = QColor(255, 0, 0)

class ChartView(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self.figure, self.ax = plt.subplots(figsize=(8, 4))
        self.canvas = FigureCanvas(self.figure)
        self.toolbar = NavigationToolbar(self.canvas, self)

        layout.addWidget(self.toolbar)
        layout.addWidget(self.canvas, stretch=1)

    def plot_data(self, filtered_data, filter_summary, available_analytes, get_active_thresholds_func):
        self.ax.clear()
        if filtered_data is None or filtered_data.empty:
            self.ax.text(0.5, 0.5, "No data matches the current filters.",
                         horizontalalignment='center', verticalalignment='center',
                         transform=self.ax.transAxes)
            self.canvas.draw()
            return

        df = filtered_data.copy()
        time_col = 'LOG TIME'
        if time_col not in df.columns:
            self.canvas.draw()
            return

        df[time_col] = pd.to_datetime(df[time_col], errors='coerce')
        df = df.dropna(subset=[time_col])
        df = df.sort_values(by=time_col)

        selected_analytes = filter_summary.get("selected_analytes", available_analytes)
        valid_analytes = [g for g in selected_analytes if g in df.columns]
        if not valid_analytes:
            self.canvas.draw()
            return

        # Fix: Use case-insensitive comparison and ensure uppercase column names
        group_by = str(filter_summary.get("group_by", "Device")).strip()
        if group_by.lower() == "device":
            group_col = 'DEVICE'
        elif group_by.lower() == "site":
            group_col = 'SITE'
        else:
            group_col = 'DEVICE'  # Default fallback

        # Verify the column exists
        if group_col not in df.columns:
            self.ax.text(0.5, 0.5, f"Column '{group_col}' not found in data.",
                         horizontalalignment='center', verticalalignment='center',
                         transform=self.ax.transAxes)
            self.canvas.draw()
            return

        if group_col == 'SITE':
            df = df[df['SITE'].notna()]
            df = df[df['SITE'].astype(str).str.strip() != '']
            df = df[df['SITE'].astype(str).str.strip().str.lower() != 'unassigned']

        if df.empty:
            self.ax.text(0.5, 0.5, "No data to display for the selected grouping.",
                         horizontalalignment='center', verticalalignment='center',
                         transform=self.ax.transAxes)
            self.canvas.draw()
            return

        groups = df[group_col].unique()
        for group_val in groups:
            group_df = df[df[group_col] == group_val]
            for analyte in valid_analytes:
                plot_df = group_df[[time_col, analyte]].dropna()
                if not plot_df.empty:
                    label = f"{group_val} - {analyte}"
                    self.ax.plot(plot_df[time_col], plot_df[analyte], marker='.', linestyle='-',
                                 label=label, markersize=4)

        active_thresholds = get_active_thresholds_func()
        if active_thresholds:
            for analyte, threshold_val in active_thresholds.items():
                if analyte in valid_analytes:
                    direction_label = " < " if analyte.upper().startswith("O2") else " > "
                    line_label = f"{analyte} threshold {direction_label} {threshold_val}"
                    self.ax.axhline(y=threshold_val, color='red', linestyle='--',
                                    linewidth=1.2, alpha=0.7, label=line_label)

        date_fmt = mdates.DateFormatter('%d %H:%M')
        self.ax.xaxis.set_major_formatter(date_fmt)
        self.ax.set_xlabel('Time')
        self.ax.set_ylabel('Concentration')
        self.ax.set_title('Filtered Analyte Readings Over Time')
        self.figure.autofmt_xdate()

        start_str = filter_summary.get("start_time", "")
        stop_str = filter_summary.get("stop_time", "")
        if start_str and start_str != "All":
            start_dt = pd.to_datetime(start_str)
            stop_dt = pd.to_datetime(stop_str)
            self.ax.set_xlim(start_dt, stop_dt)

        # ── Adjust Y-Axis Limit ──
        max_val = 0
        for analyte in valid_analytes:
            if analyte in df.columns:
                analyte_max = df[analyte].max()
                if pd.notna(analyte_max) and analyte_max > max_val:
                    max_val = analyte_max

        if active_thresholds:
            for analyte, threshold_val in active_thresholds.items():
                if analyte in valid_analytes and threshold_val > max_val:
                    max_val = threshold_val

        if max_val > 0:
            self.ax.set_ylim(top=max_val * 1.1)

        self.ax.legend(loc='best', fontsize='small')
        self.ax.grid(True, linestyle='--', alpha=0.6)
        self.figure.tight_layout()
        self.canvas.draw()
