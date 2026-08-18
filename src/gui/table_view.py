"""Table View Widget"""
import os
import logging
import pandas as pd
import numpy as np
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QTableWidget, QTableWidgetItem, QHeaderView, QAbstractItemView,
    QFileDialog, QMessageBox
)
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QFont

from base_view import DataView

logger = logging.getLogger(__name__)

THRESHOLD_EXCEEDED_COLOR = QColor(255, 0, 0)
INVALID_BG_COLOR = QColor(255, 235, 235)
INVALID_FG_COLOR = QColor(180, 60, 60)


class PaginatedTableModel:
    """Manages pagination over a DataFrame."""

    PAGE_SIZE = 500

    def __init__(self, df):
        self._full_df = df if df is not None else pd.DataFrame()
        self.current_page = 0
        self._current_df = pd.DataFrame()
        self._update_page()

    @property
    def total_pages(self):
        if self._full_df.empty:
            return 0
        return max(1, (len(self._full_df) + self.PAGE_SIZE - 1) // self.PAGE_SIZE)

    def _update_page(self):
        if self._full_df.empty:
            self._current_df = pd.DataFrame()
            return
        start = self.current_page * self.PAGE_SIZE
        end = start + self.PAGE_SIZE
        self._current_df = self._full_df.iloc[start:end].reset_index(drop=True)

    def next_page(self):
        if self.current_page < self.total_pages - 1:
            self.current_page += 1
            self._update_page()
            return True
        return False

    def prev_page(self):
        if self.current_page > 0:
            self.current_page -= 1
            self._update_page()
            return True
        return False


class TableView(DataView):
    """Self-contained table view with pagination and invalid-cell highlighting."""

    def __init__(self, incident_path, data_type, parent=None):
        super().__init__(incident_path, data_type, parent)
        self.model = None
        self._setup_ui()
        self._render()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        # Pagination controls
        nav_layout = QHBoxLayout()
        self.btn_prev_page = QPushButton("◀ Previous")
        self.btn_next_page = QPushButton("Next ▶")
        self.btn_prev_page.clicked.connect(self._on_prev_page)
        self.btn_next_page.clicked.connect(self._on_next_page)
        self.lbl_page_info = QLabel("Page 0 of 0")
        self.lbl_page_info.setAlignment(Qt.AlignCenter)

        nav_layout.addWidget(self.btn_prev_page)
        nav_layout.addStretch()
        nav_layout.addWidget(self.lbl_page_info)
        nav_layout.addStretch()
        nav_layout.addWidget(self.btn_next_page)
        layout.addLayout(nav_layout)

        # Table widget
        self.table_view = QTableWidget()
        self.table_view.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table_view.setAlternatingRowColors(True)
        self.table_view.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table_view.setSortingEnabled(True)
        self.table_view.verticalHeader().setVisible(False)
        self.table_view.horizontalHeader().setStretchLastSection(True)
        layout.addWidget(self.table_view)

    def _render(self):
        """Render the table from current filtered_data."""
        df = self.filtered_data
        if df is None or df.empty:
            self.model = PaginatedTableModel(pd.DataFrame())
            self._update_table()
            return

        self.model = PaginatedTableModel(df)
        self._update_table()

    def update_data(self, *args, **kwargs):
        """Alias for _render to satisfy the DataView interface."""
        self._render()

    def _build_invalid_cells(self):
        """
        Build a set of (row_index, analyte_name) tuples for cells that are
        flagged as invalid. This is used for background highlighting when
        'only_valid' is NOT selected.
        """
        invalid_cells = set()
        df = self.model._current_df
        if df is None or df.empty:
            return invalid_cells

        for col in df.columns:
            if not str(col).upper().startswith("INVALID_"):
                continue
            analyte = col[len("INVALID_"):]
            for row_idx in range(len(df)):
                val = pd.to_numeric(df.iloc[row_idx][col], errors="coerce")
                if pd.notna(val) and val > 0:
                    invalid_cells.add((row_idx, analyte))

        return invalid_cells

    def _is_cell_invalid(self, row, col_name):
        """Check if a cell should be highlighted as invalid."""
        # Resolve base analyte name for aggregated columns (e.g., O2_min -> O2)
        base_analyte = col_name
        for suffix in ('_min', '_max', '_count', '_mean'):
            if col_name.endswith(suffix):
                base_analyte = col_name[:-len(suffix)]
                break

        if base_analyte not in self.analyte_dec_pls:
            return False

        return (row, base_analyte) in self._invalid_cells

    def _update_table(self):
        """Populate the QTableWidget from the current page of data."""
        self.table_view.setSortingEnabled(False)

        if not hasattr(self.model, '_current_df') or self.model._current_df.empty:
            self.table_view.setRowCount(0)
            self.table_view.setColumnCount(0)
            self.lbl_page_info.setText("Page 0 of 0")
            self.btn_prev_page.setEnabled(False)
            self.btn_next_page.setEnabled(False)
            return

        df = self.model._current_df
        cols = list(df.columns)

        # Build invalid cell set for highlighting
        self._invalid_cells = self._build_invalid_cells()

        # Determine visible columns
        visible_cols = []
        for col in cols:
            if str(col).upper().startswith("INVALID_"):
                continue
            visible_cols.append(col)

        self.table_view.setColumnCount(len(visible_cols))
        self.table_view.setHorizontalHeaderLabels(visible_cols)
        self.table_view.setRowCount(len(df))

        for row_idx in range(len(df)):
            for col_idx, col_name in enumerate(visible_cols):
                value = df.iloc[row_idx][col_name]

                # Format the display text
                if pd.isna(value):
                    display = ""
                elif col_name in self.analyte_dec_pls:
                    dec_pls = self.analyte_dec_pls[col_name]
                    try:
                        display = f"{float(value):.{dec_pls}f}"
                    except (TypeError, ValueError):
                        display = str(value)
                elif col_name == 'LOG TIME':
                    try:
                        display = pd.to_datetime(value).strftime("%Y-%m-%d %H:%M:%S")
                    except Exception:
                        display = str(value)
                else:
                    display = str(value) if value is not None else ""

                item = QTableWidgetItem(display)

                # Highlight invalid cells with background color
                if self._is_cell_invalid(row_idx, col_name):
                    item.setBackground(INVALID_BG_COLOR)
                    item.setForeground(INVALID_FG_COLOR)

                # Right-align numeric columns
                if col_name in self.analyte_dec_pls:
                    item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)

                self.table_view.setItem(row_idx, col_idx, item)

        # Update pagination info
        self.lbl_page_info.setText(
            f"Page {self.model.current_page + 1} of {self.model.total_pages}"
        )
        self.btn_prev_page.setEnabled(self.model.current_page > 0)
        self.btn_next_page.setEnabled(
            self.model.current_page < self.model.total_pages - 1
        )

        # Column sizing and visibility
        header = self.table_view.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.Interactive)

        # Determine if we should hide the non-grouped column for aggregated data
        interval = str(self.filter_summary.get("interval", "Raw")).strip()
        is_aggregated = interval.lower() != "raw"
        group_by = str(self.filter_summary.get("group_by", "Device")).strip().lower()

        for i, col in enumerate(visible_cols):
            # Hide SITE if aggregated and grouping by DEVICE
            if is_aggregated and group_by == "device" and col.upper() == "SITE":
                self.table_view.setColumnHidden(i, True)
                continue

            # Hide DEVICE if aggregated and grouping by SITE
            if is_aggregated and group_by == "site" and col.upper() == "DEVICE":
                self.table_view.setColumnHidden(i, True)
                continue

            self.table_view.setColumnHidden(i, False)

            if col == 'LOG TIME':
                self.table_view.setColumnWidth(i, 190)
            elif col == 'DEVICE':
                self.table_view.setColumnWidth(i, 140)
            elif col == 'SITE':
                self.table_view.setColumnWidth(i, 80)
            elif col == 'observations':
                self.table_view.setColumnWidth(i, 250)
            elif col in self.analyte_dec_pls:
                self.table_view.setColumnWidth(i, 80)
            else:
                self.table_view.setColumnWidth(i, 100)

        header.setStretchLastSection(True)
        self.table_view.setSortingEnabled(True)

    def _on_next_page(self):
        """Handles the Next button click."""
        if self.model and self.model.next_page():
            self._update_table()

    def _on_prev_page(self):
        """Handles the Previous button click."""
        if self.model and self.model.prev_page():
            self._update_table()

    def export(self):
        """Export the current table data to CSV."""
        if self.model is None or self.model._full_df.empty:
            QMessageBox.warning(self, "No Data", "No data to export.")
            return

        file_path, _ = QFileDialog.getSaveFileName(
            self, "Export Table Data", "table_export.csv",
            "CSV Files (*.csv);;All Files (*)"
        )
        if file_path:
            try:
                export_df = self.model._full_df.copy()
                # Remove INVALID_ columns from export
                inv_cols = [
                    c for c in export_df.columns
                    if str(c).upper().startswith("INVALID_")
                ]
                export_df = export_df.drop(columns=inv_cols, errors="ignore")
                export_df.to_csv(file_path, index=False)
                QMessageBox.information(
                    self, "Success",
                    f"Table data exported to:\n{file_path}"
                )
            except Exception as e:
                QMessageBox.critical(
                    self, "Error", f"Failed to export table:\n{e}"
                )
