import os
import json
import pandas as pd
import numpy as np
import matplotlib
matplotlib.use('QtAgg')
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.backends.backend_qt5agg import NavigationToolbar2QT as NavigationToolbar
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QTableWidget, QTableWidgetItem,
    QHeaderView, QMessageBox, QComboBox, QPushButton
)
from PySide6.QtCore import Qt
from datamanagement.db_manager import IncidentDatabase

class GPSAnalysisDialog(QDialog):
    def __init__(self, parent=None, incident_path=None):
        super().__init__(parent)
        self.incident_path = incident_path
        if incident_path:
            self.csv_path = os.path.join(incident_path, "data", "processed", "area_data.csv")
            self.area_locations_json = os.path.join(incident_path, "mapping", "area_locations.json")
        else:
            self.csv_path = "testdata.csv"
            self.area_locations_json = None
        
        # ✅ Initialize database manager for device lookups
        self.db = IncidentDatabase(incident_path) if incident_path else None
        
        self.setWindowTitle("GPS Analyzer")
        self.resize(1000, 800)
        self.init_ui()

    def init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)
        
        ctrl_layout = QHBoxLayout()
        ctrl_layout.addWidget(QLabel("<b>Select Device:</b>"))
        self.cmb_device = QComboBox()
        self.cmb_device.setEditable(True)
        if self.db:
            self.cmb_device.addItems(self.db.get_devices("area"))
        ctrl_layout.addWidget(self.cmb_device)
        
        self.btn_analyze = QPushButton("Analyze")
        self.btn_analyze.setMinimumWidth(100)
        self.btn_analyze.clicked.connect(self._on_analyze)
        ctrl_layout.addWidget(self.btn_analyze)
        ctrl_layout.addStretch()
        layout.addLayout(ctrl_layout)
        
        self.figure, self.ax1 = plt.subplots(figsize=(8, 4))
        self.ax2 = self.ax1.twinx()
         
        self.canvas = FigureCanvas(self.figure)
        self.canvas.setMinimumHeight(400)
        
        self.toolbar = NavigationToolbar(self.canvas, self)
        layout.addWidget(self.toolbar)
        layout.addWidget(self.canvas, stretch=2)
        
        layout.addWidget(QLabel("<b>Stable Locations</b> (> 30 mins, ≤ 20m consecutive drift):"))
        self.table = QTableWidget()
        self.table.setColumnCount(7)
        self.table.setHorizontalHeaderLabels([
            "Device", "Latitude", "Longitude", "Start Time", "End Time", "Duration (Min)", "Data Points"
        ])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.table.verticalHeader().setVisible(False)
        self.table.setAlternatingRowColors(True)
        layout.addWidget(self.table, stretch=1)

    def _on_analyze(self):
        target_device = self.cmb_device.currentText().strip()
        if not target_device:
            QMessageBox.warning(self, "Validation Error", "Please select or enter a Device.")
            return
        self._load_and_process_data(target_device)

    def _load_and_process_data(self, target_device):
        try:
            df = pd.read_csv(self.csv_path, dtype={'STATUS': str, 'SITE': str}, low_memory=False)
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to read CSV file:\n{e}")
            return
            
        required_cols = ['LOG TIME', 'DEVICE', 'Latitude', 'Longitude']
        for col in required_cols:
            if col not in df.columns:
                QMessageBox.critical(self, "Error", f"Column '{col}' not found in CSV.")
                return
                
        df = df[df['DEVICE'] == target_device].copy()
        if df.empty:
            QMessageBox.warning(self, "No Data", f"No data found for device: {target_device}")
            self._clear_ui()
            return
            
        df['LOG TIME'] = df['LOG TIME'].astype(str).str.extract(r'(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})')
        df['LOG TIME'] = pd.to_datetime(df['LOG TIME'], errors='coerce')
        df['Latitude'] = pd.to_numeric(df['Latitude'], errors='coerce')
        df['Longitude'] = pd.to_numeric(df['Longitude'], errors='coerce') 
        
        df = df.dropna(subset=['LOG TIME', 'Latitude', 'Longitude'])
        df = df.sort_values(by='LOG TIME').reset_index(drop=True)
        
        if len(df) > 2:
            lat = df['Latitude'].values
            lon = df['Longitude'].values
            
            dist_prev = np.full(len(lat), np.inf)
            dist_prev[1:] = self.haversine(lat[1:], lon[1:], lat[:-1], lon[:-1])
            
            dist_next = np.full(len(lat), np.inf)
            dist_next[:-1] = self.haversine(lat[:-1], lon[:-1], lat[1:], lon[1:])
            
            mask = (dist_prev <= 2000) | (dist_next <= 2000)
            df_clean = df[mask].copy()
        else:
            df_clean = df.copy()
            
        if df_clean.empty:
            QMessageBox.warning(self, "No Data", "No valid data remaining after outlier filtering.")
            self._clear_ui()
            return

        df_clean = self.assign_stable_clusters(df_clean)
        
        stable_groups = df_clean.groupby('cluster_id').agg(
            start_time=('LOG TIME', 'min'),
            end_time=('LOG TIME', 'max'),
            point_count=('LOG TIME', 'count'),
            avg_lat=('Latitude', 'mean'),
            avg_lon=('Longitude', 'mean')
        ).reset_index()
        
        stable_groups['duration'] = stable_groups['end_time'] - stable_groups['start_time']
        stable_locations = stable_groups[stable_groups['duration'] > pd.Timedelta(minutes=30)].copy()
        stable_locations['duration_minutes'] = stable_locations['duration'].dt.total_seconds() / 60
        
        result_table = stable_locations[[
            'avg_lat', 'avg_lon', 'start_time', 'end_time', 'duration_minutes', 'point_count'
        ]].copy()
        
        result_table.insert(0, 'Device', target_device)
        result_table.columns = [
            'Device', 'Latitude', 'Longitude', 'Start Time', 'End Time', 'Duration (Minutes)', 'Data Points'
        ]
        result_table = result_table.sort_values(by='Start Time')
        
        self.update_plot(df_clean, target_device)
        self.update_table(result_table)

    def _clear_ui(self):
        self.ax1.clear()
        self.ax2.clear()
        self.figure.tight_layout()
        self.canvas.draw()
        self.table.setRowCount(0)

    def haversine(self, lat1, lon1, lat2, lon2):
        R = 6371000
        lat1, lon1, lat2, lon2 = map(np.radians, [lat1, lon1, lat2, lon2])
        dlat = lat2 - lat1
        dlon = lon2 - lon1
        a = np.sin(dlat/2)**2 + np.cos(lat1) * np.cos(lat2) * np.sin(dlon/2)**2
        c = 2 * np.arctan2(np.sqrt(a), np.sqrt(1 - a))
        return R * c

    def assign_stable_clusters(self, group):
        lats = group['Latitude'].values
        lons = group['Longitude'].values
        n = len(lats)
        if n == 0:
            group = group.copy()
            group['cluster_id'] = []
            return group
            
        cluster_ids = np.zeros(n, dtype=int)
        current_cluster = 0
        
        for i in range(1, n):
            dist = self.haversine(lats[i-1], lons[i-1], lats[i], lons[i])
            if dist <= 20.0:
                cluster_ids[i] = current_cluster
            else:
                current_cluster += 1
                cluster_ids[i] = current_cluster
                
        group = group.copy()
        group['cluster_id'] = cluster_ids
        return group

    def update_plot(self, df_clean, target_device):
        self.ax1.clear()
        self.ax2.clear()
        
        self.ax1.scatter(df_clean['LOG TIME'], df_clean['Latitude'], color='blue', s=15, label='Latitude')
        self.ax1.set_ylabel('Latitude', color='blue', fontweight='bold')
        self.ax1.tick_params(axis='y', labelcolor='blue')
        
        self.ax2.scatter(df_clean['LOG TIME'], df_clean['Longitude'], color='red', s=15, label='Longitude')
        self.ax2.set_ylabel('Longitude', color='red', fontweight='bold')
        self.ax2.tick_params(axis='y', labelcolor='red')
        
        self.ax1.set_title(f'Latitude & Longitude vs Log Time for {target_device}')
        self.ax1.set_xlabel('Log Time')
        
        date_fmt = mdates.DateFormatter('%d %H:%M')
        self.ax1.format_xdata = date_fmt
        self.ax1.xaxis.set_major_formatter(date_fmt)
        self.figure.autofmt_xdate()
        
        lines1, labels1 = self.ax1.get_legend_handles_labels()
        lines2, labels2 = self.ax2.get_legend_handles_labels()
        self.ax1.legend(lines1 + lines2, labels1 + labels2, loc='upper left')
        
        self.figure.tight_layout()
        self.canvas.draw()

    def update_table(self, result_table):
        self.table.setRowCount(len(result_table))
        for row_idx, (_, row) in enumerate(result_table.iterrows()):
            self.table.setItem(row_idx, 0, QTableWidgetItem(str(row['Device'])))
            self.table.setItem(row_idx, 1, QTableWidgetItem(f"{row['Latitude']:.6f}"))
            self.table.setItem(row_idx, 2, QTableWidgetItem(f"{row['Longitude']:.6f}"))
            self.table.setItem(row_idx, 3, QTableWidgetItem(str(row['Start Time'])))
            self.table.setItem(row_idx, 4, QTableWidgetItem(str(row['End Time'])))
            self.table.setItem(row_idx, 5, QTableWidgetItem(f"{row['Duration (Minutes)']:.1f}"))
            self.table.setItem(row_idx, 6, QTableWidgetItem(str(row['Data Points'])))
