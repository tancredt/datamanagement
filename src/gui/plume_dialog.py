import os
import shutil
import logging
import datetime
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QTableWidget, QTableWidgetItem,
    QPushButton, QFileDialog, QMessageBox, QHeaderView, QAbstractItemView,
    QStyle
)
from PySide6.QtCore import Qt, QSize
from datamanagement.db_manager import IncidentDatabase

logger = logging.getLogger(__name__)

class PlumeDialog(QDialog):
    def __init__(self, parent=None, incident_path=None):
        super().__init__(parent)
        self.incident_path = incident_path
        self.plumes_dir = os.path.join(incident_path, "plumes")
        os.makedirs(self.plumes_dir, exist_ok=True)
        
        self.db = IncidentDatabase(incident_path)
        self.all_plumes = self.db.get_plumes()
        
        self.setWindowTitle("Plume Manager")
        self.resize(600, 400)
        self._setup_ui()
        self._connect_signals()
        self._update_table()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(12)
        layout.setContentsMargins(16, 16, 16, 16)

        self.table = QTableWidget()
        self.table.setColumnCount(2)
        self.table.setHorizontalHeaderLabels(["File Name", "Model Date/Time (Local)"])
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setAlternatingRowColors(True)
        self.table.setStyleSheet("QTableWidget { font-size: 12px; }")
        layout.addWidget(self.table)

        btn_row = QHBoxLayout()
        self.btn_add = QPushButton("Add Plume(s)...")
        self.btn_add.setMinimumHeight(32)
        self.btn_add.setIcon(self.style().standardIcon(QStyle.SP_FileDialogNewFolder))
        self.btn_add.setIconSize(QSize(18, 18))
        btn_row.addWidget(self.btn_add)

        self.btn_delete = QPushButton("Delete Selected")
        self.btn_delete.setMinimumHeight(32)
        self.btn_delete.setIcon(self.style().standardIcon(QStyle.SP_TrashIcon))
        self.btn_delete.setIconSize(QSize(18, 18))
        self.btn_delete.setEnabled(False)
        btn_row.addWidget(self.btn_delete)
        
        btn_row.addStretch()
        
        self.btn_box = QPushButton("OK")
        self.btn_box.setMinimumHeight(32)
        self.btn_box.setMinimumWidth(100)
        self.btn_box.clicked.connect(self.accept)
        btn_row.addWidget(self.btn_box)
        
        layout.addLayout(btn_row)

    def _connect_signals(self):
        self.btn_add.clicked.connect(self._on_add)
        self.btn_delete.clicked.connect(self._on_delete)
        self.table.itemSelectionChanged.connect(self._update_button_states)

    def _update_button_states(self):
        has_selection = len(self.table.selectedItems()) > 0
        self.btn_delete.setEnabled(has_selection)

    def _update_table(self):
        self.table.setRowCount(len(self.all_plumes))
        for i, plume in enumerate(self.all_plumes):
            self.table.setItem(i, 0, QTableWidgetItem(plume.get("file_name", "")))
            self.table.setItem(i, 1, QTableWidgetItem(plume.get("model_dt", "") or "-"))
        self._update_button_states()

    def _on_add(self):
        files, _ = QFileDialog.getOpenFileNames(
            self, "Select Plume Images", "", "PNG Files (*.png);;All Files (*)"
        )
        if not files:
            return

        added_count = 0
        for src in files:
            fname = os.path.basename(src)
            dst = os.path.join(self.plumes_dir, fname)
            
            # Copy physical file to incident directory
            if not os.path.exists(dst):
                try:
                    shutil.copy2(src, dst)
                except Exception as e:
                    logger.error(f"Failed to copy {src}: {e}")
                    continue
            
            # Parse model_dt from filename (e.g., 202607241430.png -> 2026-07-24 14:30)
            model_dt = None
            dt_str = os.path.splitext(fname)[0]
            try:
                dt_utc = datetime.datetime.strptime(dt_str, "%Y%m%d%H%M")
                dt_local = dt_utc.replace(tzinfo=datetime.timezone.utc).astimezone().replace(tzinfo=None)
                model_dt = dt_local.strftime("%Y-%m-%d %H:%M")
            except ValueError:
                model_dt = dt_str  # Fallback to raw filename if parsing fails

            # Save to database
            success, msg = self.db.add_plume(fname, model_dt)
            if success:
                added_count += 1
            else:
                logger.warning(f"Failed to add plume {fname} to DB: {msg}")

        if added_count > 0:
            self.all_plumes = self.db.get_plumes()
            self._update_table()
            QMessageBox.information(self, "Added", f"Successfully added {added_count} plume(s).")

    def _on_delete(self):
        selected_rows = sorted(list(set(item.row() for item in self.table.selectedItems())), reverse=True)
        if not selected_rows:
            return

        reply = QMessageBox.question(
            self, "Confirm Deletion",
            f"Are you sure you want to delete {len(selected_rows)} selected plume(s)?\n\nThis will remove them from the database and delete the physical files.",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No
        )
        if reply == QMessageBox.Yes:
            deleted_count = 0
            for row in selected_rows:
                plume_data = self.all_plumes[row]
                fname = plume_data.get("file_name")
                
                # Delete physical file
                fpath = os.path.join(self.plumes_dir, fname)
                if os.path.exists(fpath):
                    try:
                        os.remove(fpath)
                    except Exception as e:
                        logger.error(f"Failed to delete physical file {fpath}: {e}")
                
                # Delete from database
                self.db.delete_plume(fname)
                deleted_count += 1
            
            self.all_plumes = self.db.get_plumes()
            self._update_table()
            QMessageBox.information(self, "Deleted", f"Successfully deleted {deleted_count} plume(s).")
