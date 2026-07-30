import os
import sys
import pandas as pd
import matplotlib
matplotlib.use('QtAgg')
import matplotlib.pyplot as plt
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.backends.backend_qtagg import NavigationToolbar2QT as NavigationToolbar
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QRadioButton, QButtonGroup, 
    QFileDialog, QMessageBox
)

# Import the new self-contained base class
from base_view import DataView
# Import the table view to reuse its calculation logic
from summary_table_view import SummaryTableView


class SummaryChartView(DataView):
    """
    Self-contained summary chart view.
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
        
        # Metric selection buttons
        metric_layout = QHBoxLayout()
        self.metric_group = QButtonGroup(self)
        
        self.rb_mean = QRadioButton("Mean")
        self.rb_max = QRadioButton("Max")
        self.rb_min = QRadioButton("Min")
        self.rb_count = QRadioButton("Count")
        self.rb_mean.setChecked(True)
        
        self.metric_group.addButton(self.rb_mean, 0)
        self.metric_group.addButton(self.rb_max, 1)
        self.metric_group.addButton(self.rb_min, 2)
        self.metric_group.addButton(self.rb_count, 3)
        
        metric_layout.addWidget(self.rb_mean)
        metric_layout.addWidget(self.rb_max)
        metric_layout.addWidget(self.rb_min)
        metric_layout.addWidget(self.rb_count)
        metric_layout.addStretch()
        layout.addLayout(metric_layout)
        
        # Matplotlib canvas
        self.summary_figure, self.summary_ax = plt.subplots(figsize=(8, 4))
        self.summary_figure.set_tight_layout(True)  # ✅ Handle tight layout automatically
        self.summary_canvas = FigureCanvas(self.summary_figure)
        self.summary_toolbar = NavigationToolbar(self.summary_canvas, self)
        layout.addWidget(self.summary_toolbar)
        layout.addWidget(self.summary_canvas, stretch=1)
        
        self.metric_group.idClicked.connect(self._redraw)

    def export(self):
        """Satisfies the DataView interface. Exports the Matplotlib figure."""
        file_path, _ = QFileDialog.getSaveFileName(
            self, "Export Summary Chart", "summary_chart.png", "PNG Files (*.png);;All Files (*)"
        )
        if file_path:
            try:
                self.summary_figure.savefig(file_path, bbox_inches='tight')
                QMessageBox.information(self, "Success", f"Summary chart exported successfully to:\n{file_path}")
            except Exception as e:
                QMessageBox.critical(self, "Error", f"Failed to export summary chart:\n{e}")

    def render_to_figure(self):
        """Returns the existing Matplotlib figure directly for PDF export."""
        return self.summary_figure

    def _render(self):
        """
        Calculates summary data using a temporary SummaryTableView.
        This ensures we use the exact same calculation logic and state as the table view
        without duplicating code.
        """
        temp_table = SummaryTableView(self.incident_path, self.data_type)
        
        # Override the temp table's state with our current base class state
        temp_table.filter_summary = self.filter_summary
        temp_table.filtered_data = self.filtered_data
        
        # Run the calculation
        temp_table._render()
        self.summary_data = temp_table.get_summary_data()
        
        # Draw the chart
        self._redraw()

    def update_data(self, *args, **kwargs):
        """Alias for _render to satisfy the DataView interface."""
        self._render()

    def _redraw(self):
        """Redraws the matplotlib chart based on the current summary_data and metric."""
        self.summary_ax.clear()
        
        if not self.filter_summary:
            self.summary_canvas.draw()
            return
            
        is_exposure = self.filter_summary.get("data_type") == "exposure"
        if is_exposure:
            group_by = "Identifier"
        else:
            group_by = self.filter_summary.get("group_by", "Device")
            
        if not self.summary_data:
            self.summary_ax.text(0.5, 0.5, "No summary data available.",
                                 horizontalalignment='center', verticalalignment='center',
                                 transform=self.summary_ax.transAxes)
            self.summary_canvas.draw()
            return
            
        # ✅ Determine metric preference (Report vs Live UI)
        if hasattr(self, '_report_stats_pref'):
            # Report mode: use the preference from the objective
            metric_name = str(self._report_stats_pref).capitalize()
            metric_map = {'Mean': 4, 'Max': 3, 'Min': 2, 'Count': 5}
            metric_idx = metric_map.get(metric_name, 4)
        else:
            # Live UI mode: use the radio buttons
            metric_id = self.metric_group.checkedId()
            metric_map_ui = {0: ('Mean', 4), 1: ('Max', 3), 2: ('Min', 2), 3: ('Count', 5)}
            metric_name, metric_idx = metric_map_ui.get(metric_id, ('Mean', 4))
            
        df = pd.DataFrame(self.summary_data, columns=['Group', 'Analyte', 'Min', 'Max', 'Mean', 'Count', 'DecPls'])
        df.replace("", pd.NA, inplace=True)
        pivot_df = df.pivot(index='Group', columns='Analyte', values=metric_name)
        pivot_df = pivot_df.apply(pd.to_numeric, errors='coerce')
        
        if pivot_df.dropna(how='all').empty:
            self.summary_ax.text(0.5, 0.5, "No plottable data for selected metric.",
                                 horizontalalignment='center', verticalalignment='center',
                                 transform=self.summary_ax.transAxes)
            self.summary_canvas.draw()
            return
            
        pivot_df.plot(kind='bar', ax=self.summary_ax, alpha=0.8)
        
        # Use base class method to get active thresholds
        active_thresholds = self.get_active_thresholds()
        if metric_name != 'Count' and active_thresholds:
            for analyte, threshold_val in active_thresholds.items():
                if analyte in pivot_df.columns:
                    self.summary_ax.axhline(y=threshold_val, color='red', linestyle='--', 
                                            linewidth=1.5, alpha=0.8, label=f"{analyte} Threshold")
                                            
        # Adjust Y-axis to ensure thresholds are visible
        max_val = 0
        if not pivot_df.empty:
            data_max = pivot_df.max().max()
            if pd.notna(data_max) and data_max > max_val:
                max_val = data_max
                
            if metric_name != 'Count' and active_thresholds:
                for analyte, threshold_val in active_thresholds.items():
                    if analyte in pivot_df.columns and threshold_val > max_val:
                        max_val = threshold_val
                        
        if max_val > 0:
            self.summary_ax.set_ylim(top=max_val * 1.1)
            
        self.summary_ax.set_title(f"Summary {metric_name} by {group_by} and Analyte")
        self.summary_ax.set_ylabel(metric_name)
        self.summary_ax.set_xlabel(group_by)
        
        handles, labels = self.summary_ax.get_legend_handles_labels()
        by_label = dict(zip(labels, handles))
        if len(by_label) > 5:
            self.summary_ax.legend(by_label.values(), by_label.keys(), fontsize='small', ncol=2)
        else:
            self.summary_ax.legend(by_label.values(), by_label.keys())
        
        self.summary_canvas.draw()

