import os
import sys
import pandas as pd
import numpy as np
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QTableView,
    QPushButton, QLabel, QHeaderView, QFileDialog, QMessageBox
)
from PySide6.QtCore import Qt, QAbstractTableModel, QModelIndex
from PySide6.QtGui import QColor

# Import the base class
from base_view import DataView

current_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.dirname(current_dir)
if parent_dir not in sys.path:
    sys.path.insert(0, parent_dir)

INVALID_BG_COLOR = QColor(255, 200, 200)
THRESHOLD_EXCEEDED_COLOR = QColor(255, 0, 0)

# ─────────────────────────────────────────────────────────
# Paginated Table Model
# ─────────────────────────────────────────────────────────
class PaginatedTableModel(QAbstractTableModel):
    def __init__(self, dec_pls_dict=None, page_size=100):
        super().__init__()
        self._full_df = pd.DataFrame()
        self._current_df = pd.DataFrame()
        self.dec_pls_dict = dec_pls_dict if dec_pls_dict is not None else {}
        self.page_size = page_size
        self.current_page = 0
        self.total_pages = 0
        self._invalid_cells = set()
        self._show_invalid_bg = True
        self._active_thresholds = {}
        self.update_page()

    def set_show_invalid_bg(self, show: bool):
        self._show_invalid_bg = show

    def set_active_thresholds(self, thresholds: dict):
        self._active_thresholds = thresholds

    def set_data(self, df):
        self.beginResetModel()
        self._full_df = df if df is not None and not df.empty else pd.DataFrame()
        self.current_page = 0
        self._rebuild_invalid_cache()
        self.update_page()
        self.endResetModel()

    def update_page(self):
        if len(self._full_df) == 0:
            self._current_df = pd.DataFrame()
            self.total_pages = 0
        else:
            self.total_pages = (len(self._full_df) + self.page_size - 1) // self.page_size
            start = self.current_page * self.page_size
            end = start + self.page_size
            self._current_df = self._full_df.iloc[start:end]

    def next_page(self):
        if self.current_page < self.total_pages - 1:
            self.beginResetModel()
            self.current_page += 1
            self.update_page()
            self.endResetModel()
            return True
        return False

    def prev_page(self):
        if self.current_page > 0:
            self.beginResetModel()
            self.current_page -= 1
            self.update_page()
            self.endResetModel()
            return True
        return False

    def rowCount(self, parent=QModelIndex()):
        return len(self._current_df)

    def columnCount(self, parent=QModelIndex()):
        return len(self._current_df.columns)

    def _rebuild_invalid_cache(self):
        self._invalid_cells = set()
        if self._full_df.empty:
            return
        analyte_cols = [c for c in self._full_df.columns if c in self.dec_pls_dict]
        for analyte in analyte_cols:
            inv_col = next((c for c in self._full_df.columns if c.upper() == f"INVALID_{analyte}".upper()), None)
            if inv_col:
                invalid_mask = pd.to_numeric(self._full_df[inv_col], errors='coerce').fillna(0) > 0
                for idx in self._full_df.index[invalid_mask]:
                    self._invalid_cells.add((idx, analyte))

    def _is_cell_invalid(self, row, col_name):
        if col_name not in self.dec_pls_dict:
            return False
        global_idx = self._current_df.index[row]
        return (global_idx, col_name) in self._invalid_cells

    def _is_threshold_exceeded(self, col_name, val):
        if col_name not in self._active_thresholds:
            return False
        if not isinstance(val, (int, float, np.floating, np.integer)):
            return False
        if pd.isna(val):
            return False
        threshold = self._active_thresholds[col_name]
        if col_name.upper().startswith("O2"):
            return val < threshold
        else:
            return val > threshold

    def _get_dec_pls_for_column(self, col_name):
        """Return decimal places for a column, handling _min/_max/_mean suffixes."""
        if col_name in self.dec_pls_dict:
            return self.dec_pls_dict[col_name]
        for suffix in ('_min', '_max', '_mean', '_count'):
            if col_name.endswith(suffix):
                base = col_name[:-len(suffix)]
                if base in self.dec_pls_dict:
                    return self.dec_pls_dict[base]
        return None

    def data(self, index, role=Qt.DisplayRole):
        if not index.isValid():
            return None
        row = index.row()
        col = index.column()
        col_name = self._current_df.columns[col]
        cell_invalid = self._is_cell_invalid(row, col_name)
        val = self._current_df.iloc[row, col]

        if role == Qt.BackgroundRole:
            if self._show_invalid_bg and cell_invalid:
                return INVALID_BG_COLOR
            return None

        if role == Qt.ForegroundRole:
            if self._is_threshold_exceeded(col_name, val):
                return THRESHOLD_EXCEEDED_COLOR
            return None

        if role != Qt.DisplayRole:
            return None

        if col_name.upper().startswith("INVALID_"):
            return ""
        if pd.isna(val):
            return ""

        # Use helper so aggregated cols (_min, _max, _mean) also format correctly
        dec_pls = self._get_dec_pls_for_column(col_name)
        if dec_pls is not None and isinstance(val, (int, float, np.floating, np.integer)):
            return f"{val:.{dec_pls}f}"
        elif isinstance(val, pd.Timestamp):
            return val.strftime("%Y-%m-%d %H:%M:%S")
        return str(val)

    def headerData(self, section, orientation, role=Qt.DisplayRole):
        if role == Qt.DisplayRole:
            if orientation == Qt.Horizontal:
                return str(self._current_df.columns[section])
            else:
                return str(section + 1 + self.current_page * self.page_size)
        return None


# ─────────────────────────────────────────────────────────
# Table View Widget
# ─────────────────────────────────────────────────────────
class TableView(DataView):
    def __init__(self, incident_path, data_type, parent=None):
        super().__init__(incident_path, data_type, parent)
        self.model = None
        self._setup_ui()
        self._render()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self.table_view = QTableView()
        self.table_view.setAlternatingRowColors(True)
        self.table_view.horizontalHeader().setSectionResizeMode(QHeaderView.Interactive)
        self.table_view.verticalHeader().setVisible(False)
        layout.addWidget(self.table_view, stretch=1)

        # Bottom Controls
        bottom_layout = QHBoxLayout()
        self.btn_prev_page = QPushButton("Previous")
        self.lbl_page_info = QLabel("Page 0 of 0")
        self.btn_next_page = QPushButton("Next")

        bottom_layout.addStretch()
        bottom_layout.addWidget(self.btn_prev_page)
        bottom_layout.addWidget(self.lbl_page_info)
        bottom_layout.addWidget(self.btn_next_page)
        bottom_layout.addStretch()
        layout.addLayout(bottom_layout)

        self.btn_prev_page.clicked.connect(self._on_prev_page)
        self.btn_next_page.clicked.connect(self._on_next_page)

    def export(self):
        """Satisfies the DataView interface. Exports the full underlying dataframe to a CSV file."""
        if self.model is None or self.model._full_df.empty:
            QMessageBox.warning(self, "No Data", "There is no data to export.")
            return

        file_path, _ = QFileDialog.getSaveFileName(
            self, "Export Table to CSV", "filtered_data.csv",
            "CSV Files (*.csv);;All Files (*)"
        )
        if file_path:
            try:
                export_df = self.model._full_df.copy()
                inv_cols = [c for c in export_df.columns if c.upper().startswith('INVALID_')]
                export_df.drop(columns=inv_cols, inplace=True, errors='ignore')
                export_df.to_csv(file_path, index=False)
                QMessageBox.information(self, "Success", f"Table exported successfully to:\n{file_path}")
            except Exception as e:
                QMessageBox.critical(self, "Error", f"Failed to export table:\n{e}")

    def _reorder_columns(self, df):
        """Reorders columns to: LOG TIME, SITE, DEVICE, analytes, [aggregated stats], observations, Latitude, Longitude, others."""
        if df is None or df.empty:
            return df

        ordered = []

        # 1. Core metadata columns first
        for col in ['LOG TIME', 'SITE', 'DEVICE']:
            if col in df.columns:
                ordered.append(col)

        # 2. Base analyte columns (from self.analyte_dec_pls)
        for analyte in self.analyte_dec_pls.keys():
            if analyte in df.columns and analyte not in ordered:
                ordered.append(analyte)

        # 3. Aggregated stat columns (_min, _max, _count) - placed before Latitude/Longitude
        for analyte in self.analyte_dec_pls.keys():
            for suffix in ['_min', '_max', '_count']:
                col = f"{analyte}{suffix}"
                if col in df.columns and col not in ordered:
                    ordered.append(col)

        # 4. Observations
        if 'observations' in df.columns:
            ordered.append('observations')

        # 5. Coordinates
        for col in ['Latitude', 'Longitude']:
            if col in df.columns:
                ordered.append(col)

        # 6. INVALID_ columns
        for col in df.columns:
            if col.upper().startswith('INVALID_') and col not in ordered:
                ordered.append(col)

        # 7. Any remaining columns (catches anything we missed)
        for col in df.columns:
            if col not in ordered:
                ordered.append(col)

        return df[ordered]

    def _render(self):
        """Render the table with current filtered_data."""
        if self.model is None:
            self.model = PaginatedTableModel(dec_pls_dict=self.analyte_dec_pls, page_size=100)
            self.table_view.setModel(self.model)
        
        # Reorder columns before passing to model
        reordered_data = self._reorder_columns(self.filtered_data)
        
        # ✅ NEW: Drop columns that are completely empty (all NaN or empty strings)
        if reordered_data is not None and not reordered_data.empty:
            # Protect core metadata columns from being dropped
            protected_cols = ['LOG TIME', 'SITE', 'DEVICE']
            
            # Temporarily replace empty/whitespace-only strings with NaN
            temp_df = reordered_data.replace(r'^\s*$', np.nan, regex=True)
            
            # Find columns that have at least one non-NaN value
            valid_cols = temp_df.dropna(axis=1, how='all').columns
            
            # Ensure protected columns are kept even if they are somehow empty
            cols_to_keep = [col for col in reordered_data.columns if col in valid_cols or col in protected_cols]
            reordered_data = reordered_data[cols_to_keep]
        
        # Use base class state
        show_invalid_bg = not self.filter_summary.get("only_valid", False)
        self.model.set_show_invalid_bg(show_invalid_bg)
        self.model.set_active_thresholds(self.get_active_thresholds())
        self.model.set_data(reordered_data)
        self._update_table()

    def update_data(self, *args, **kwargs):
        """Alias for _render for compatibility."""
        self._render()

    def _update_table(self):
        if self.model.total_pages > 0:
            self.lbl_page_info.setText(f"Page {self.model.current_page + 1} of {self.model.total_pages}")
        else:
            self.lbl_page_info.setText("Page 0 of 0")

        self.btn_prev_page.setEnabled(self.model.current_page > 0)
        self.btn_next_page.setEnabled(self.model.current_page < self.model.total_pages - 1)

        header = self.table_view.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.Interactive)

        if not hasattr(self.model, '_current_df') or self.model._current_df.empty:
            return

        cols = list(self.model._current_df.columns)
        for i, col in enumerate(cols):
            if col.upper().startswith("INVALID_"):
                self.table_view.setColumnHidden(i, True)
                continue

            self.table_view.setColumnHidden(i, False)

            if col == 'LOG TIME':
                self.table_view.setColumnWidth(i, 190)      # Wider
            elif col == 'DEVICE':
                self.table_view.setColumnWidth(i, 140)
            elif col == 'SITE':
                self.table_view.setColumnWidth(i, 80)        # Narrower
            elif col == 'observations':
                self.table_view.setColumnWidth(i, 250)
            elif col in self.analyte_dec_pls:
                self.table_view.setColumnWidth(i, 80)
            else:
                self.table_view.setColumnWidth(i, 100)

        header.setStretchLastSection(True)

    def _on_next_page(self):
        """Handles the Next button click."""
        if self.model and self.model.next_page():
            self._update_table()

    def _on_prev_page(self):
        """Handles the Previous button click."""
        if self.model and self.model.prev_page():
            self._update_table()
