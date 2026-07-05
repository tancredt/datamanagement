import os
import sys
import pandas as pd
import matplotlib
matplotlib.use('QtAgg')
import matplotlib.pyplot as plt
from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.backends.backend_qt5agg import NavigationToolbar2QT as NavigationToolbar
from PySide6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QRadioButton, QButtonGroup

class SummaryChartView(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.summary_data = []
        self.filter_summary = {}
        self.active_thresholds = {}  # Added to store thresholds
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
        
        # Redraw automatically when the user changes the metric radio button
        self.metric_group.idClicked.connect(self._redraw)

    def update_data(self, summary_data, filter_summary, active_thresholds=None):
        """Receives data from the Table view and redraws the chart."""
        self.summary_data = summary_data
        self.filter_summary = filter_summary
        self.active_thresholds = active_thresholds or {}  # Store thresholds
        self._redraw()

    def _redraw(self):
        self.summary_ax.clear()
        
        if not self.filter_summary:
            self.summary_canvas.draw()
            return

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
        
        pivot_df = df.pivot(index='Group', columns='Analyte', values=metric_name)
        
        pivot_df.plot(kind='bar', ax=self.summary_ax, alpha=0.8)
        
        # ── Adjust Y-Axis Limit ──
        max_val = 0
        if not pivot_df.empty:
            # 1. Find the highest data value plotted
            data_max = pivot_df.max().max()
            if pd.notna(data_max) and data_max > max_val:
                max_val = data_max
                
            # 2. Check if any active threshold is higher than the data
            # (Skip this if the metric is 'Count', as thresholds are concentrations, not counts)
            if metric_name != 'Count' and self.active_thresholds:
                for analyte, threshold_val in self.active_thresholds.items():
                    if analyte in pivot_df.columns:
                        if threshold_val > max_val:
                            max_val = threshold_val
                            
            # 3. Set the top limit to 10% higher than the maximum value
            if max_val > 0:
                self.summary_ax.set_ylim(top=max_val * 1.1)
        # ────────────────────────────────
        
        self.summary_ax.set_title(f"Summary {metric_name} by {group_by} and Analyte")
        self.summary_ax.set_ylabel(metric_name)
        self.summary_ax.set_xlabel(group_by)
        
        if len(pivot_df.columns) > 5:
            self.summary_ax.legend(title="Analyte", fontsize='small', ncol=2)
        else:
            self.summary_ax.legend(title="Analyte")
            
        self.summary_figure.tight_layout()
        self.summary_canvas.draw()
