import os
import sys
import pandas as pd
import matplotlib
matplotlib.use('QtAgg')
import matplotlib.pyplot as plt
from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.backends.backend_qt5agg import NavigationToolbar2QT as NavigationToolbar
from PySide6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QRadioButton, QButtonGroup, QFileDialog, QMessageBox
from base_view import DataView

class SummaryChartView(DataView):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.summary_data = []
        self.filter_summary = {}
        self.active_thresholds = {}
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
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
        
        self.summary_figure, self.summary_ax = plt.subplots(figsize=(8, 4))
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

    def update_data(self, summary_data, filter_summary, active_thresholds=None):
        """Receives data from the Table view and redraws the chart."""
        self.summary_data = summary_data
        self.filter_summary = filter_summary
        self.active_thresholds = active_thresholds or {}
        self._redraw()

    def _redraw(self):
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
            
        metric_id = self.metric_group.checkedId()
        metric_map = {0: ('Mean', 4), 1: ('Max', 3), 2: ('Min', 2), 3: ('Count', 5)}
        metric_name, metric_idx = metric_map.get(metric_id, ('Mean', 4))
        
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
        
        if metric_name != 'Count' and self.active_thresholds:
            for analyte, threshold_val in self.active_thresholds.items():
                if analyte in pivot_df.columns:
                    self.summary_ax.axhline(y=threshold_val, color='red', linestyle='--', 
                                            linewidth=1.5, alpha=0.8, label=f"{analyte} Threshold")
                                            
        max_val = 0
        if not pivot_df.empty:
            data_max = pivot_df.max().max()
            if pd.notna(data_max) and data_max > max_val:
                max_val = data_max
            if metric_name != 'Count' and self.active_thresholds:
                for analyte, threshold_val in self.active_thresholds.items():
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
            
        self.summary_figure.tight_layout()
        self.summary_canvas.draw()
