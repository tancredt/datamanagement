import os
import sys
import pandas as pd
import numpy as np
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QTableWidget, QTableWidgetItem,
    QPushButton, QMessageBox, QFileDialog, QHeaderView
)
from PySide6.QtGui import QColor

THRESHOLD_EXCEEDED_COLOR = QColor(255, 0, 0)

class NumericTableWidgetItem(QTableWidgetItem):
    def __lt__(self, other):
        try:
            return float(self.text()) < float(other.text())
        except ValueError:
            return super().__lt__(other)

class SummaryTableView(QWidget):
    def __init__(self, analyte_dec_pls, parent=None):
        super().__init__(parent)
        self.analyte_dec_pls = analyte_dec_pls
        self.summary_data = []
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self.summary_table = QTableWidget()
        self.summary_table.setColumnCount(6)
        self.summary_table.setHorizontalHeaderLabels(["Group", "Analyte", "Minimum", "Maximum", "Mean", "Count"])
        self.summary_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.summary_table.setAlternatingRowColors(True)
        self.summary_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.summary_table.setSelectionBehavior(QTableWidget.SelectRows)
        self.summary_table.setSortingEnabled(True)
        layout.addWidget(self.summary_table)

        bottom_layout = QHBoxLayout()
        self.btn_export_summary = QPushButton("Export Summary CSV")
        self.btn_export_summary.setMinimumHeight(32)
        bottom_layout.addWidget(self.btn_export_summary)
        bottom_layout.addStretch()
        layout.addLayout(bottom_layout)

    def connect_signals(self, export_callback):
        self.btn_export_summary.clicked.connect(export_callback)

    def update_data(self, filtered_data, filter_summary, available_analytes, get_active_thresholds_func):
        """Calculates statistics and populates the table."""
        if filtered_data is None or filtered_data.empty:
            self.summary_table.setRowCount(0)
            self.summary_data = []
            return

        df = filtered_data.copy()
        selected_analytes = filter_summary.get("selected_analytes", available_analytes)
        valid_analytes = [g for g in selected_analytes if g in df.columns]        

        group_by = filter_summary.get("group_by", "Device")
        group_col = 'DEVICE' if group_by == "Device" else 'SITE'

        self.summary_table.setHorizontalHeaderLabels([group_by, "Analyte", "Minimum", "Maximum", "Mean", "Count"])

        if group_col in df.columns:
            groups = df[group_col].dropna().unique()
            groups = sorted(groups, key=lambda x: str(x))
        else:
            groups = ["All"]

        rows_data = []
        for group_val in groups:
            if group_col in df.columns:
                group_df = df[df[group_col] == group_val]
            else:
                group_df = df

            for analyte in valid_analytes:
                if analyte in group_df.columns:
                    analyte_data = group_df[analyte].dropna()
                    count_val = len(analyte_data)

                    if count_val > 0:
                        min_val = analyte_data.min()
                        max_val = analyte_data.max()
                        mean_val = analyte_data.mean()
                        dec_pls = self.analyte_dec_pls.get(analyte, 2)

                        rows_data.append((
                            str(group_val), analyte,
                            float(min_val), float(max_val), float(mean_val),
                            int(count_val), dec_pls
                        ))

        self.summary_table.setSortingEnabled(False)
        self.summary_table.setRowCount(len(rows_data))

        active_thresholds = get_active_thresholds_func()

        for row, (grp, analyte, min_v, max_v, mean_v, count_v, dec_pls) in enumerate(rows_data):
            self.summary_table.setItem(row, 0, QTableWidgetItem(grp))
            self.summary_table.setItem(row, 1, QTableWidgetItem(analyte))

            min_item = NumericTableWidgetItem(f"{min_v:.{dec_pls}f}")
            if self._is_value_exceeding_threshold(analyte, min_v, active_thresholds):
                min_item.setForeground(THRESHOLD_EXCEEDED_COLOR)
            self.summary_table.setItem(row, 2, min_item)

            max_item = NumericTableWidgetItem(f"{max_v:.{dec_pls}f}")
            if self._is_value_exceeding_threshold(analyte, max_v, active_thresholds):
                max_item.setForeground(THRESHOLD_EXCEEDED_COLOR)
            self.summary_table.setItem(row, 3, max_item)

            mean_item = NumericTableWidgetItem(f"{mean_v:.{dec_pls}f}")
            if self._is_value_exceeding_threshold(analyte, mean_v, active_thresholds):
                mean_item.setForeground(THRESHOLD_EXCEEDED_COLOR)
            self.summary_table.setItem(row, 4, mean_item)

            self.summary_table.setItem(row, 5, NumericTableWidgetItem(str(count_v)))

        self.summary_table.setSortingEnabled(True)
        self.summary_data = rows_data

    def _is_value_exceeding_threshold(self, analyte, value, active_thresholds):
        if analyte not in active_thresholds:
            return False
        if not isinstance(value, (int, float, np.floating, np.integer)):
            return False
        if pd.isna(value):
            return False
        threshold = active_thresholds[analyte]
        if analyte.upper().startswith("O2"):
            return value < threshold
        else:
            return value > threshold

    def get_summary_data(self):
        """Returns the calculated data so the Chart View can use it."""
        return self.summary_data

    def export_csv(self, group_by_name="Device"):
        if not self.summary_data:
            QMessageBox.warning(self, "No Data", "There is no summary data to export.")
            return
            
        file_path, _ = QFileDialog.getSaveFileName(
            self, "Export Summary to CSV", "summary_data.csv", "CSV Files (*.csv);;All Files (*)"
        )
        
        if file_path:
            try:
                df = pd.DataFrame(self.summary_data, columns=['Group', 'Analyte', 'Min', 'Max', 'Mean', 'Count', 'DecPls'])
                
                for col in ['Min', 'Max', 'Mean']:
                    df[col] = df.apply(lambda row: f"{row[col]:.{row['DecPls']}f}", axis=1)
                
                df.drop(columns=['DecPls'], inplace=True)
                df.rename(columns={'Group': group_by_name}, inplace=True)
                
                df.to_csv(file_path, index=False)
                QMessageBox.information(self, "Success", f"Summary exported successfully to:\n{file_path}")
            except Exception as e:
                QMessageBox.critical(self, "Error", f"Failed to export summary:\n{e}")
