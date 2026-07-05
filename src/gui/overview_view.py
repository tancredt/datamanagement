import os
import sys
import pandas as pd
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QTreeWidget, QTreeWidgetItem,
    QScrollArea, QFrame, QPushButton, QHeaderView
)
from PySide6.QtCore import Qt

class CollapsibleBox(QWidget):
    """A simple accordion-style collapsible container."""
    def __init__(self, title="", parent=None):
        super().__init__(parent)
        self.is_expanded = False  # Start collapsed to save space

        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        self.toggle_button = QPushButton(title)
        self.toggle_button.setCheckable(True)
        self.toggle_button.setChecked(self.is_expanded)
        self.toggle_button.setStyleSheet("""
            QPushButton {
                text-align: left; padding: 10px 12px;
                background-color: #e0e0e0; border: 1px solid #b0b0b0;
                border-radius: 4px; font-weight: bold; font-size: 13px;
            }
            QPushButton:hover { background-color: #d0d0d0; }
            QPushButton:checked { background-color: #c0c0c0; }
        """)
        self.toggle_button.clicked.connect(self.toggle)
        main_layout.addWidget(self.toggle_button)

        self.content_area = QFrame()
        self.content_area.setStyleSheet("""
            QFrame {
                background-color: #f8f9fa; border: 1px solid #b0b0b0;
                border-top: none; border-radius: 0 0 4px 4px;
            }
        """)
        self.content_layout = QVBoxLayout(self.content_area)
        self.content_layout.setContentsMargins(12, 12, 12, 12)
        self.content_layout.setAlignment(Qt.AlignTop)
        main_layout.addWidget(self.content_area)

        self.content_area.setVisible(self.is_expanded)

    def toggle(self):
        self.is_expanded = not self.is_expanded
        self.content_area.setVisible(self.is_expanded)


class OverviewView(QWidget):
    """Displays a high-level summary of Area, Spot, and Spectral data using accordions."""
    def __init__(self, analyte_dec_pls, parent=None):
        super().__init__(parent)
        self.analyte_dec_pls = analyte_dec_pls
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        
        container = QWidget()
        self.container_layout = QVBoxLayout(container)
        self.container_layout.setAlignment(Qt.AlignTop)

        # Area Accordions
        self.box_area_site = CollapsibleBox("Area By Site")
        self.tree_area_site = self._create_tree()
        self.box_area_site.content_layout.addWidget(self.tree_area_site)
        self.container_layout.addWidget(self.box_area_site)

        self.box_area_device = CollapsibleBox("Area By Device")
        self.tree_area_device = self._create_tree()
        self.box_area_device.content_layout.addWidget(self.tree_area_device)
        self.container_layout.addWidget(self.box_area_device)

        # Spot Accordions
        self.box_spot_site = CollapsibleBox("Spot By Site")
        self.tree_spot_site = self._create_tree()
        self.box_spot_site.content_layout.addWidget(self.tree_spot_site)
        self.container_layout.addWidget(self.box_spot_site)

        self.box_spot_device = CollapsibleBox("Spot By Device")
        self.tree_spot_device = self._create_tree()
        self.box_spot_device.content_layout.addWidget(self.tree_spot_device)
        self.container_layout.addWidget(self.box_spot_device)

        # Spectral Accordions (NEW)
        self.box_spectral_site = CollapsibleBox("Spectral By Site")
        self.tree_spectral_site = self._create_tree()
        self.box_spectral_site.content_layout.addWidget(self.tree_spectral_site)
        self.container_layout.addWidget(self.box_spectral_site)

        self.box_spectral_device = CollapsibleBox("Spectral By Device")
        self.tree_spectral_device = self._create_tree()
        self.box_spectral_device.content_layout.addWidget(self.tree_spectral_device)
        self.container_layout.addWidget(self.box_spectral_device)

        self.container_layout.addStretch()
        scroll.setWidget(container)
        layout.addWidget(scroll)

    def _create_tree(self):
        tree = QTreeWidget()
        tree.setHeaderLabels(["Metric", "Value"])
        tree.header().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        tree.header().setSectionResizeMode(1, QHeaderView.Stretch)
        tree.setAlternatingRowColors(True)
        tree.setMaximumHeight(300)
        return tree

    def update_data(self, area_data, spot_data, spectral_data):
        self.box_area_site.setVisible(True)
        self.box_area_device.setVisible(True)
        self.box_spot_site.setVisible(True)
        self.box_spot_device.setVisible(True)
        self.box_spectral_site.setVisible(True)
        self.box_spectral_device.setVisible(True)
        
        # Populate Area trees (no longer passing available_analytes)
        self._populate_tree(self.tree_area_site, area_data, 'SITE', "Site")
        self._populate_tree(self.tree_area_device, area_data, 'DEVICE', "Device")
        
        # Populate Spot trees
        self._populate_tree(self.tree_spot_site, spot_data, 'SITE', "Site")
        self._populate_tree(self.tree_spot_device, spot_data, 'DEVICE', "Device")
        
        # Populate Spectral trees
        self._populate_spectral_tree(self.tree_spectral_site, spectral_data, 'SITE', "Site")
        self._populate_spectral_tree(self.tree_spectral_device, spectral_data, 'DEVICE', "Device")

    def _populate_tree(self, tree, df, group_col, label_prefix):
        """Helper to populate a QTreeWidget with grouped Area/Spot data."""
        tree.clear()
        if df is None or df.empty:
            item = QTreeWidgetItem(["No Data Available", ""])
            tree.addTopLevelItem(item)
            return

        df = df.copy()
        if 'LOG TIME' in df.columns:
            df['LOG TIME'] = pd.to_datetime(df['LOG TIME'], errors='coerce')
            df = df.dropna(subset=['LOG TIME'])

        if df.empty or group_col not in df.columns:
            item = QTreeWidgetItem(["No Data Available", ""])
            tree.addTopLevelItem(item)
            return

        groups = df[group_col].dropna().unique()
        groups = sorted([str(g) for g in groups if str(g).strip()])

        for group_name in groups:
            group_df = df[df[group_col] == group_name]
            total_readings = len(group_df)
            top_item = QTreeWidgetItem([f"{label_prefix}: {group_name}", f"Total Readings: {total_readings}"])
            top_item.setExpanded(False)

            if not group_df.empty:
                last_idx = group_df['LOG TIME'].idxmax()
                last_row = group_df.loc[last_idx]
                last_time = last_row['LOG TIME']
                time_str = last_time.strftime("%Y-%m-%d %H:%M:%S") if pd.notna(last_time) else "N/A"
                
                time_item = QTreeWidgetItem(["Last Reading Time", time_str])
                top_item.addChild(time_item)

                # ── GET ANALYTES DIRECTLY FROM SELF ──
                for analyte in self.analyte_dec_pls.keys():
                    if analyte in group_df.columns:
                        val = last_row.get(analyte)
                        if pd.notna(val):
                            dec_pls = self.analyte_dec_pls.get(analyte, 2)
                            val_str = f"{val:.{dec_pls}f}"
                        else:
                            val_str = "N/A"
                        analyte_item = QTreeWidgetItem([analyte, val_str])
                        top_item.addChild(analyte_item)
            tree.addTopLevelItem(top_item)

    def update_spectral_data(self, spectral_data):
        """Updates Spectral accordions. Hides Area and Spot."""
        # Toggle visibility
        self.box_area_site.setVisible(False)
        self.box_area_device.setVisible(False)
        self.box_spot_site.setVisible(False)
        self.box_spot_device.setVisible(False)
        self.box_spectral_site.setVisible(True)
        self.box_spectral_device.setVisible(True)

        self._populate_spectral_tree(self.tree_spectral_site, spectral_data, 'SITE', "Site")
        self._populate_spectral_tree(self.tree_spectral_device, spectral_data, 'DEVICE', "Device")

    def _populate_spectral_tree(self, tree, df, group_col, label_prefix):
        """Helper to populate a QTreeWidget with grouped Spectral data."""
        tree.clear()
        if df is None or df.empty:
            item = QTreeWidgetItem(["No Data Available", ""])
            tree.addTopLevelItem(item)
            return

        df = df.copy()
        if 'LOG TIME' in df.columns:
            df['LOG TIME'] = pd.to_datetime(df['LOG TIME'], errors='coerce')
            df = df.dropna(subset=['LOG TIME'])

        if df.empty or group_col not in df.columns:
            item = QTreeWidgetItem(["No Data Available", ""])
            tree.addTopLevelItem(item)
            return

        groups = df[group_col].dropna().unique()
        groups = sorted([str(g) for g in groups if str(g).strip()])

        for group_name in groups:
            group_df = df[df[group_col] == group_name]
            total_records = len(group_df)
            top_item = QTreeWidgetItem([f"{label_prefix}: {group_name}", f"Total Records: {total_records}"])
            top_item.setExpanded(False)

            if not group_df.empty:
                last_idx = group_df['LOG TIME'].idxmax()
                last_row = group_df.loc[last_idx]
                last_time = last_row['LOG TIME']
                time_str = last_time.strftime("%Y-%m-%d %H:%M:%S") if pd.notna(last_time) else "N/A"
                
                time_item = QTreeWidgetItem(["Last Record Time", time_str])
                top_item.addChild(time_item)

                chems = last_row.get('chemicals_identified', 'N/A')
                if pd.isna(chems) or not str(chems).strip(): 
                    chems = 'N/A'
                chem_item = QTreeWidgetItem(["Chemicals Identified", str(chems)])
                top_item.addChild(chem_item)

                comments = last_row.get('comments', '')
                if pd.notna(comments) and str(comments).strip():
                    comm_item = QTreeWidgetItem(["Comments", str(comments)])
                    top_item.addChild(comm_item)
                    
            tree.addTopLevelItem(top_item)
