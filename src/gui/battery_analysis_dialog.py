import os
import sys
import pandas as pd
import numpy as np
import matplotlib
matplotlib.use('QtAgg')
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.backends.backend_qt5agg import NavigationToolbar2QT as NavigationToolbar
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QMessageBox, QComboBox, QPushButton
)
from PySide6.QtCore import Qt, Slot

current_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.dirname(current_dir)
if parent_dir not in sys.path:
    sys.path.insert(0, parent_dir)

# ✅ Use the efficient battery data function and db_manager
from datamanagement.reader import read_battery_data
from datamanagement.db_manager import IncidentDatabase

class BatteryAnalysisDialog(QDialog):
    def __init__(self, parent=None, incident_path=None):
        super().__init__(parent)
        self.incident_path = incident_path
        self.db = IncidentDatabase(incident_path) if incident_path else None
        
        self.setWindowTitle("Battery Analyzer")
        self.resize(1000, 800)
        
        # Selection / regression state
        self._df = None
        self._target_device = None
        self._selection_mode = False
        self._selected_x = []          # matplotlib date numbers (floats)
        self._selection_artists = []   # artists to remove on reset
        
        self.init_ui()

    # ------------------------------------------------------------------ UI
    def init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        # --- Controls row
        ctrl_layout = QHBoxLayout()
        ctrl_layout.addWidget(QLabel("<b>Select Device:</b>"))
        
        self.cmb_device = QComboBox()
        self.cmb_device.setEditable(True)
        
        # ✅ FIXED: Get area devices directly from database
        if self.db:
            area_devices = self.db.get_devices("area")
            self.cmb_device.addItems(area_devices)
        
        ctrl_layout.addWidget(self.cmb_device)
        
        self.btn_analyze = QPushButton("Analyze")
        self.btn_analyze.clicked.connect(self._on_analyze)
        ctrl_layout.addWidget(self.btn_analyze)
        
        self.btn_select = QPushButton("Select Points")
        self.btn_select.setCheckable(True)
        self.btn_select.setToolTip(
            "Enable this, then click two points on the chart to define the "
            "regression window. The tool will predict when BATTERY reaches 0%."
        )
        self.btn_select.toggled.connect(self._on_toggle_selection)
        ctrl_layout.addWidget(self.btn_select)
        
        ctrl_layout.addStretch()
        layout.addLayout(ctrl_layout)

        # --- Status / result label
        self.lbl_status = QLabel(
            "<i>Click 'Analyze' to load data, then 'Select Points' to pick "
            "two points on the chart for regression.</i>"
        )
        self.lbl_status.setWordWrap(True)
        layout.addWidget(self.lbl_status)

        # --- Chart
        self.figure, self.ax = plt.subplots(figsize=(8, 4))
        self.canvas = FigureCanvas(self.figure)
        self.toolbar = NavigationToolbar(self.canvas, self)
        layout.addWidget(self.toolbar)
        layout.addWidget(self.canvas, stretch=1)

        # Mouse-click handler on the canvas
        self._pick_cid = self.canvas.mpl_connect('button_press_event', self._on_chart_click)

    # -------------------------------------------------------- Selection UI
    @Slot(bool)
    def _on_toggle_selection(self, checked):
        self._selection_mode = checked
        if checked:
            self._clear_selection()
            self.lbl_status.setText(
                "<b>Selection mode:</b> Click two points on the chart to "
                "define the regression range."
            )
            self.canvas.setCursor(Qt.CrossCursor)
        else:
            self.lbl_status.setText("<i>Selection mode off.</i>")
            self.canvas.setCursor(Qt.ArrowCursor)

    def _clear_selection(self):
        self._selected_x = []
        for artist in self._selection_artists:
            try:
                artist.remove()
            except Exception:
                pass
        self._selection_artists = []
        self.canvas.draw_idle()

    # -------------------------------------------------------- Click handler
    def _on_chart_click(self, event):
        if not self._selection_mode:
            return
        if event.inaxes != self.ax or event.xdata is None:
            return

        x = float(event.xdata)          # matplotlib date number
        self._selected_x.append(x)

        # Visual marker: vertical line at the clicked timestamp
        vline = self.ax.axvline(x=x, color='red', linestyle='--',
                                linewidth=1.2, alpha=0.8)
        self._selection_artists.append(vline)
        self.canvas.draw_idle()

        if len(self._selected_x) == 1:
            self.lbl_status.setText(
                "<b>Selection mode:</b> First point selected. Click a second point."
            )
        elif len(self._selected_x) >= 2:
            # Keep only the first two clicks
            self._selected_x = self._selected_x[:2]
            self.btn_select.setChecked(False)   # exits selection mode
            self._perform_regression()

    # -------------------------------------------------------- Regression
    def _perform_regression(self):
        if self._df is None or self._df.empty:
            self.lbl_status.setText("<i>No data loaded.</i>")
            return

        x1, x2 = sorted(self._selected_x)

        # Filter data between the two selected timestamps (inclusive)
        mask = (self._df['LOG_TIME_NUM'] >= x1) & (self._df['LOG_TIME_NUM'] <= x2)
        subset = self._df.loc[mask].copy()

        if len(subset) < 2:
            QMessageBox.warning(
                self, "Not Enough Data",
                f"Only {len(subset)} data point(s) found between the "
                f"selected timestamps. At least 2 are required for regression."
            )
            self._clear_selection()
            return

        x = subset['LOG_TIME_NUM'].values
        y = subset['BATTERY'].values

        # Linear regression: BATTERY = slope * t + intercept   (t in days)
        slope, intercept = np.polyfit(x, y, 1)

        # ---- Shaded selected range
        span = self.ax.axvspan(x1, x2, color='yellow', alpha=0.18,
                               label='Selected range')
        self._selection_artists.append(span)

        # ---- Regression fit line across the selected window
        x_fit = np.array([x1, x2])
        y_fit = slope * x_fit + intercept
        fit_line, = self.ax.plot(x_fit, y_fit, color='green', linestyle='-',
                                 linewidth=2,
                                 label=f'Fit (slope={slope:.4f} %/day)')
        self._selection_artists.append(fit_line)

        # ---- Predict time when BATTERY == 0
        if abs(slope) < 1e-12:
            self.lbl_status.setText(
                "<b>Result:</b> Battery level is constant — cannot predict "
                "when it will reach 0%."
            )
            QMessageBox.information(
                self, "Regression Result",
                "Battery level is constant within the selected range; "
                "cannot predict when it will reach 0%."
            )
            self.ax.legend(loc='best')
            self.figure.tight_layout()
            self.canvas.draw()
            return

        x_zero = -intercept / slope
        t_zero = mdates.num2date(x_zero).replace(tzinfo=None)

        # Extrapolation line (if prediction lies outside the selected window)
        if x_zero < x1 or x_zero > x2:
            x_ext = np.array([x2, x_zero]) if x_zero > x2 else np.array([x1, x_zero])
            y_ext = slope * x_ext + intercept
            ext_line, = self.ax.plot(x_ext, y_ext, color='green',
                                     linestyle=':', linewidth=1.5,
                                     label='Extrapolation')
            self._selection_artists.append(ext_line)

        # Prediction marker
        pred_marker, = self.ax.plot([x_zero], [0.0], marker='*', color='red',
                                    markersize=15, zorder=6,
                                    label='Predicted BATTERY=0%')
        self._selection_artists.append(pred_marker)

        # ---- Update status & report
        t_zero_str = t_zero.strftime('%Y-%m-%d %H:%M:%S')
        self.lbl_status.setText(
            f"<b>Prediction:</b> Battery reaches 0% at "
            f"<b>{t_zero_str}</b> &nbsp; "
            f"(slope = {slope:.4f} %/day, n = {len(subset)} points)"
        )

        QMessageBox.information(
            self, "Regression Result",
            f"Linear regression on {len(subset)} points between:\n"
            f"  {mdates.num2date(x1).replace(tzinfo=None):%Y-%m-%d %H:%M:%S}\n"
            f"  {mdates.num2date(x2).replace(tzinfo=None):%Y-%m-%d %H:%M:%S}\n\n"
            f"Slope:     {slope:.6f} %/day\n"
            f"Intercept: {intercept:.4f} %\n\n"
            f"Predicted time when BATTERY = 0%:\n"
            f"  {t_zero_str}"
        )

        self.ax.legend(loc='best')
        self.figure.tight_layout()
        self.canvas.draw()

    # -------------------------------------------------------- Analyze flow
    @Slot()
    def _on_analyze(self):
        target_device = self.cmb_device.currentText().strip()
        if not target_device:
            QMessageBox.warning(self, "Validation Error",
                                "Please select or enter a Device.")
            return
        self._load_and_process_data(target_device)

    def _load_and_process_data(self, target_device):
        try:
            # ✅ Use the efficient battery-specific query
            df = read_battery_data(self.incident_path, device_label=target_device)
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to read battery data from database:\n{e}")
            return

        required_cols = ['LOG TIME', 'DEVICE', 'BATTERY']
        if not all(col in df.columns for col in required_cols):
            QMessageBox.critical(self, "Error",
                                 "Required columns (LOG TIME, DEVICE, BATTERY) "
                                 "not found in database query.")
            return

        if df.empty:
            QMessageBox.warning(self, "No Data",
                                f"No battery data found for device: {target_device}")
            self._clear_ui()
            return

        df['BATTERY'] = pd.to_numeric(df['BATTERY'], errors='coerce')
        df = df.dropna(subset=['LOG TIME', 'BATTERY'])
        
        if df.empty:
            QMessageBox.warning(self, "No Data",
                                f"No valid battery data found for device: "
                                f"{target_device}")
            self._clear_ui()
            return

        # Pre-compute matplotlib date numbers (days) for fast regression
        df['LOG_TIME_NUM'] = mdates.date2num(df['LOG TIME'].dt.to_pydatetime())

        self._df = df
        self._target_device = target_device
        self._clear_selection()

        self.ax.clear()
        self.ax.plot(df['LOG TIME'], df['BATTERY'],
                     marker='.', linestyle='-', color='blue', label='Battery')
        self.ax.set_title(f'Battery vs Log Time for {target_device}')
        self.ax.set_xlabel('Log Time')
        self.ax.set_ylabel('Battery (%)')

        date_fmt = mdates.DateFormatter('%d %H:%M')
        self.ax.xaxis.set_major_formatter(date_fmt)
        self.figure.autofmt_xdate()
        self.ax.legend(loc='best')
        self.ax.grid(True, linestyle='--', alpha=0.6)
        self.figure.tight_layout()
        self.canvas.draw()

        self.lbl_status.setText(
            f"<i>Loaded {len(df)} points for <b>{target_device}</b>. "
            f"Click 'Select Points' to perform regression.</i>"
        )

    def _clear_ui(self):
        self._df = None
        self._target_device = None
        self._clear_selection()
        self.ax.clear()
        self.figure.tight_layout()
        self.canvas.draw()
