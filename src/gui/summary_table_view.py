import os
import sys
import pandas as pd
import numpy as np
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QTableWidget, QTableWidgetItem,
    QPushButton, QMessageBox, QFileDialog, QHeaderView
)
from PySide6.QtGui import QColor

# Import the new self-contained base class
from base_view import DataView

THRESHOLD_EXCEEDED_COLOR = QColor(255, 0, 0)


class NumericTableWidgetItem(QTableWidgetItem):
    """Custom item that sorts numerically instead of alphabetically."""
    def lt(self, other):
        try:
            return float(self.text()) < float(other.text())
        except ValueError:
            return super().lt(other)


class SummaryTableView(DataView):
    """
    Self-contained summary table view.
    Loads its own raw data, filters, and configs from disk.
    """
    def __init__(self, incident_path, data_type, parent=None):
        super().__init__(incident_path, data_type, parent)
        self.summary_data = []
        self._setup_ui()
        self._render()

        
    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.summary_table = QTableWidget()
        self.summary_table.setColumnCount(6)
        self.summary_table.setHorizontalHeaderLabels(["Group", "Analyte", "Mean", "Maximum", "Minimum", "Count"])
        self.summary_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.summary_table.setAlternatingRowColors(True)
        self.summary_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.summary_table.setSelectionBehavior(QTableWidget.SelectRows)
        self.summary_table.setSortingEnabled(True)
        
        layout.addWidget(self.summary_table)

    def export(self):
        """Satisfies the DataView interface. Exports the summary data to CSV."""
        if not self.summary_data:
            QMessageBox.warning(self, "No Data", "There is no summary data to export.")
            return
            
        group_by_name = self.filter_summary.get("group_by", "Device")
        if self.filter_summary.get("data_type") == "exposure":
            group_by_name = "Identifier"
            
        file_path, _ = QFileDialog.getSaveFileName(
            self, "Export Summary to CSV", "summary_data.csv", "CSV Files (*.csv);;All Files (*)"
        )
        if file_path:
            try:
                df = pd.DataFrame(self.summary_data, columns=['Group', 'Analyte', 'Min', 'Max', 'Mean', 'Count', 'DecPls'])
                for col in ['Mean', 'Max', 'Min']:
                    df[col] = df.apply(lambda row: f"{row[col]:.{row['DecPls']}f}" if pd.notna(row[col]) else "", axis=1)
                df.drop(columns=['DecPls'], inplace=True)
                df.rename(columns={'Group': group_by_name}, inplace=True)
                df.to_csv(file_path, index=False)
                QMessageBox.information(self, "Success", f"Summary exported successfully to:\n{file_path}")
            except Exception as e:
                QMessageBox.critical(self, "Error", f"Failed to export summary:\n{e}")

    def get_summary_data(self):
        """Returns the calculated data so the Chart View or Report Generator can use it."""
        return self.summary_data

    def _render(self):
        """Calculates statistics and populates the table using the shared grouping function."""
        if self.filtered_data is None or self.filtered_data.empty:
            self.summary_table.setRowCount(0)
            self.summary_data = []
            return
        
        df = self.filtered_data.copy()
        is_exposure = self.filter_summary.get("data_type") == "exposure"
        
        # 1. Determine group column
        if is_exposure:
            group_col = 'IDENTIFIER'
            group_by_label = "Identifier"
        else:
            group_by = self.filter_summary.get("group_by", "Device")
            group_col = 'DEVICE' if group_by == "Device" else 'SITE'
            group_by_label = group_by

        # 2. Determine valid analytes
        if is_exposure:
            valid_analytes = [g for g in self.available_analytes 
                              if f"{g}_min" in df.columns or f"{g}_max" in df.columns or f"{g}_mean" in df.columns]
        else:
            selected_analytes = self.filter_summary.get("selected_analytes", self.available_analytes)
            valid_analytes = [g for g in selected_analytes if g in df.columns]

        # ✅ 3. CALL THE SHARED FUNCTION
        from datamanagement.grouping import calculate_summary_dataframe
        summary_df = calculate_summary_dataframe(df, group_col, valid_analytes, is_exposure)

        self.summary_table.setHorizontalHeaderLabels([group_by_label, "Analyte", "Minimum", "Maximum", "Mean", "Count"])
        
        # 4. Convert DataFrame to the tuple format expected by the UI rendering & export
        rows_data = []
        for _, row in summary_df.iterrows():
            dec_pls = self.analyte_dec_pls.get(row['Analyte'], 2)
            rows_data.append((
                row['Group'], row['Analyte'],
                row['Min'], row['Max'], row['Mean'],
                int(row['Count']), dec_pls
            ))
            
        self.summary_data = rows_data  # Keep for export/chart compatibility

        # --- UI Rendering Loop (Remains exactly the same) ---
        self.summary_table.setSortingEnabled(False)
        self.summary_table.setRowCount(len(rows_data))
        active_thresholds = self.get_active_thresholds()
        
        for row, (grp, analyte, min_v, max_v, mean_v, count_v, dec_pls) in enumerate(rows_data):
            self.summary_table.setItem(row, 0, QTableWidgetItem(grp))
            self.summary_table.setItem(row, 1, QTableWidgetItem(analyte))
            
            min_item = NumericTableWidgetItem(f"{min_v:.{dec_pls}f}" if pd.notna(min_v) else "")
            if pd.notna(min_v) and self._is_value_exceeding_threshold(analyte, min_v, active_thresholds):
                min_item.setForeground(THRESHOLD_EXCEEDED_COLOR)
            self.summary_table.setItem(row, 2, min_item)
            
            max_item = NumericTableWidgetItem(f"{max_v:.{dec_pls}f}" if pd.notna(max_v) else "")
            if pd.notna(max_v) and self._is_value_exceeding_threshold(analyte, max_v, active_thresholds):
                max_item.setForeground(THRESHOLD_EXCEEDED_COLOR)
            self.summary_table.setItem(row, 3, max_item)
            
            mean_item = NumericTableWidgetItem(f"{mean_v:.{dec_pls}f}" if pd.notna(mean_v) else "")
            if pd.notna(mean_v) and self._is_value_exceeding_threshold(analyte, mean_v, active_thresholds):
                mean_item.setForeground(THRESHOLD_EXCEEDED_COLOR)
            self.summary_table.setItem(row, 4, mean_item)
            
            self.summary_table.setItem(row, 5, NumericTableWidgetItem(str(count_v)))
            
        self.summary_table.setSortingEnabled(True)
        self.summary_table.setRowCount(len(rows_data))
        
        # Use base class method to get active thresholds
        active_thresholds = self.get_active_thresholds()
        for row, (grp, analyte, min_v, max_v, mean_v, count_v, dec_pls) in enumerate(rows_data):
            self.summary_table.setItem(row, 0, QTableWidgetItem(grp))
            self.summary_table.setItem(row, 1, QTableWidgetItem(analyte))
            
            mean_item = NumericTableWidgetItem(f"{mean_v:.{dec_pls}f}" if pd.notna(mean_v) else "")
            if pd.notna(mean_v) and self._is_value_exceeding_threshold(analyte, mean_v, active_thresholds):
                mean_item.setForeground(THRESHOLD_EXCEEDED_COLOR)
            self.summary_table.setItem(row, 2, mean_item)
            
            max_item = NumericTableWidgetItem(f"{max_v:.{dec_pls}f}" if pd.notna(max_v) else "")
            if pd.notna(max_v) and self._is_value_exceeding_threshold(analyte, max_v, active_thresholds):
                max_item.setForeground(THRESHOLD_EXCEEDED_COLOR)
            self.summary_table.setItem(row, 3, max_item)
            
            min_item = NumericTableWidgetItem(f"{min_v:.{dec_pls}f}" if pd.notna(min_v) else "")
            if pd.notna(min_v) and self._is_value_exceeding_threshold(analyte, min_v, active_thresholds):
                min_item.setForeground(THRESHOLD_EXCEEDED_COLOR)
            self.summary_table.setItem(row, 4, min_item)
            
            self.summary_table.setItem(row, 5, NumericTableWidgetItem(str(count_v)))
            
        self.summary_table.setSortingEnabled(True)
        self.summary_data = rows_data

    def update_data(self, *args, **kwargs):
        """Alias for _render to satisfy the DataView interface."""
        self._render()

    def _is_value_exceeding_threshold(self, analyte, value, active_thresholds):
        """Checks if a value exceeds the threshold (handling O2 inversion)."""
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


