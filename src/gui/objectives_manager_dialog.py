import os
import logging
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QTableWidget, QTableWidgetItem,
    QPushButton, QMessageBox, QHeaderView, QAbstractItemView
)
from PySide6.QtCore import Qt
from datamanagement.db_manager import IncidentDatabase
from objective_form_dialog import ObjectiveFormDialog

logger = logging.getLogger(__name__)

class ObjectivesManagerDialog(QDialog):
    def __init__(self, parent=None, incident_path=None):
        super().__init__(parent)
        self.incident_path = incident_path
        self.db = IncidentDatabase(incident_path)
        self.objectives = []
        
        self.setWindowTitle("Manage Objectives")
        self.resize(800, 500)
        self._setup_ui()
        self._load_data()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        
        self.table = QTableWidget()
        self.table.setColumnCount(3)
        self.table.setHorizontalHeaderLabels(["Zone", "Objective", "Created At"])
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setAlternatingRowColors(True)
        self.table.doubleClicked.connect(self._on_edit)
        layout.addWidget(self.table)
        
        btn_layout = QHBoxLayout()
        self.btn_add = QPushButton("Add Objective...")
        self.btn_add.setMinimumHeight(32)
        self.btn_add.clicked.connect(self._on_add)
        btn_layout.addWidget(self.btn_add)
        
        self.btn_edit = QPushButton("Edit Selected...")
        self.btn_edit.setMinimumHeight(32)
        self.btn_edit.setEnabled(False)
        self.btn_edit.clicked.connect(self._on_edit)
        btn_layout.addWidget(self.btn_edit)
        
        self.btn_delete = QPushButton("Delete Selected")
        self.btn_delete.setMinimumHeight(32)
        self.btn_delete.setEnabled(False)
        self.btn_delete.setStyleSheet("color: #dc3545;")
        self.btn_delete.clicked.connect(self._on_delete)
        btn_layout.addWidget(self.btn_delete)
        
        btn_layout.addStretch()
        
        self.btn_close = QPushButton("Close")
        self.btn_close.setMinimumHeight(32)
        self.btn_close.setMinimumWidth(100)
        self.btn_close.clicked.connect(self.accept)
        btn_layout.addWidget(self.btn_close)
        
        layout.addLayout(btn_layout)
        
        self.table.currentCellChanged.connect(self._update_button_states)

    def _update_button_states(self):
        has_selection = self.table.currentRow() >= 0
        self.btn_edit.setEnabled(has_selection)
        self.btn_delete.setEnabled(has_selection)

    def _load_data(self):
        self.objectives = self.db.get_all_objectives()
        self.table.setRowCount(len(self.objectives))
        for i, obj in enumerate(self.objectives):
            self.table.setItem(i, 0, QTableWidgetItem(obj.get('zone', '')))
            
            # Truncate objective text for table view if it's too long
            obj_text = obj.get('objective', '')
            if len(obj_text) > 100:
                obj_text = obj_text[:100] + "..."
            self.table.setItem(i, 1, QTableWidgetItem(obj_text))
            
            self.table.setItem(i, 2, QTableWidgetItem(obj.get('created_at', '')))
        self._update_button_states()

    def _on_add(self):
        dialog = ObjectiveFormDialog(self, self.incident_path)
        if dialog.exec() == QDialog.Accepted:
            data = dialog.get_data()
            if data:
                obj_id = self.db.add_objective(data)
                if obj_id:
                    self._load_data()
                    QMessageBox.information(self, "Success", "Objective added successfully.")
                else:
                    QMessageBox.warning(self, "Add Fialed", "Could not add objective.")

    def _on_edit(self):
        row = self.table.currentRow()

        if row >= 0:
            obj_data = self.objectives[row]

            dialog = ObjectiveFormDialog(self, self.incident_path, obj_data=obj_data)

            if dialog.exec() == QDialog.Accepted:
                new_data = dialog.get_data()

                if new_data:
                    success, message = self.db.update_objective(obj_data["id"], new_data)

                    if success:
                        self._load_data()
                        QMessageBox.information(self, "Success", "Objective updated successfully.")
                    else:
                        QMessageBox.warning(self, "Update Failed", message or "Could not update objective.")
                        
    def _on_delete(self):
        row = self.table.currentRow()

        if row >= 0:
            obj_data = self.objectives[row]

            reply = QMessageBox.question(
                self,
                "Confirm Deletion",
                f"Are you sure you want to delete the objective for zone '{obj_data.get('zone')}'?\n\n"
                "This will also delete all associated observations.",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No,
            )

            if reply == QMessageBox.Yes:
                success, message = self.db.delete_objective(obj_data["id"])

                if success:
                    self._load_data()
                    QMessageBox.information(self, "Success", "Objective deleted successfully.")
                else:
                    QMessageBox.warning(self, "Delete Failed", message or "Could not delete objective.")
