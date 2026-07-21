import os
import sys
import json
import datetime
import pandas as pd
import numpy as np
import matplotlib
matplotlib.use('Agg')  # Use non-interactive backend for background PDF generation
import matplotlib.pyplot as plt
from matplotlib.backends.backend_pdf import PdfPages
import matplotlib.dates as mdates
from matplotlib.patches import Circle
import logging
from PySide6.QtWidgets import QFileDialog

# Ensure parent directory is in sys.path for local imports
current_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.dirname(current_dir)
if parent_dir not in sys.path:
    sys.path.insert(0, parent_dir)

from datamanagement.locations import LocationManager

# Import the modular views to eliminate rendering duplication
from table_view import TableView
from chart_view import ChartView
from summary_table_view import SummaryTableView
from summary_chart_view import SummaryChartView
from summary_map_view import SummaryMapView

logger = logging.getLogger(__name__)


def load_json(filepath):
    """Helper to safely load JSON files."""
    if os.path.exists(filepath):
        with open(filepath, 'r', encoding='utf-8') as f:
            return json.load(f)
    return {}


def generate_pdf_report(incident_path, parent_widget=None):
    """Generates a comprehensive PDF report for the incident."""
    try:
        # 1. Load Configs & Metadata
        incident_data = load_json(os.path.join(incident_path, "meta", "incident.json"))
        objectives_data = load_json(os.path.join(incident_path, "reports", "objectives.json"))

        # Load unified maps data using LocationManager
        manager = LocationManager(incident_path)
        maps_data = manager.get_maps_data()
        mapping_dir = os.path.join(incident_path, "mapping")

        # 2. Ask user where to save the PDF
        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        default_filename = f"Air_Monitoring_Report_{timestamp}.pdf"
        pdf_path, _ = QFileDialog.getSaveFileName(
            parent_widget,
            "Save PDF Report",
            default_filename,
            "PDF Files (*.pdf);;All Files (*)"
        )

        # User cancelled
        if not pdf_path:
            logger.info("PDF report generation cancelled by user.")
            return None

        # Ensure it has .pdf extension
        if not pdf_path.lower().endswith('.pdf'):
            pdf_path += '.pdf'

        # 3. Generate PDF
        with PdfPages(pdf_path) as pdf:
            page_num = 1

            def save_page(fig, zone_name, summary_text=None):
                """Adds standard footer and optional summary header, then saves the page."""
                nonlocal page_num
                # Footer
                fig.text(0.5, 0.015, "FRV Hazmat Air Monitoring Report",
                         fontsize=9, ha='center', va='bottom', style='italic', color='gray')
                fig.text(0.05, 0.015, zone_name,
                         fontsize=9, ha='left', va='bottom', style='italic', color='gray')
                fig.text(0.95, 0.015, f"Page {page_num}",
                         fontsize=9, ha='right', va='bottom', style='italic', color='gray')
                # Summary Box (Only on observation pages)
                if summary_text:
                    fig.text(0.5, 0.96, summary_text, fontsize=10, ha='center', va='top',
                             bbox=dict(facecolor='#f8f9fa', alpha=0.9, edgecolor='#dee2e6', boxstyle='round,pad=0.4'))
                pdf.savefig(fig)
                plt.close(fig)
                page_num += 1

            # --- PAGE 1: Title Page ---
            fig = plt.figure(figsize=(8.5, 11))
            fig.text(0.5, 0.7, "Fire Rescue Victoria", fontsize=28, fontweight='bold', ha='center')
            fig.text(0.5, 0.6, "Air Monitoring Report", fontsize=22, ha='center')
            fig.text(0.5, 0.45, f"Incident: {incident_data.get('label', 'N/A')}", fontsize=18, ha='center')
            fig.text(0.5, 0.4, f"Address: {incident_data.get('address', 'N/A')}", fontsize=16, ha='center')
            now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            fig.text(0.5, 0.3, f"Published: {now_str}", fontsize=16, ha='center')
            save_page(fig, "Title Page")

            # --- SECTION 2: Maps ---
            for filename, markers in maps_data.items():
                fig = plt.figure(figsize=(8.5, 11))
                fig.text(0.5, 0.92, f"Map: {filename}", fontsize=18, fontweight='bold', ha='center')

                img_path = os.path.join(mapping_dir, filename)
                if os.path.exists(img_path):
                    img = plt.imread(img_path)
                    ax_img = fig.add_axes([0.1, 0.25, 0.8, 0.60])
                    ax_img.imshow(img)
                    ax_img.axis('off')

                    for m in markers:
                        x, y, label = m.get('x', 0), m.get('y', 0), m.get('label', '')
                        circle = Circle((x, y), 8, color='yellow', ec='red', lw=2, zorder=5)
                        ax_img.add_patch(circle)
                        ax_img.text(x + 12, y + 5, label, color='black', fontsize=10, fontweight='bold', zorder=6)

                    details_text = "Marker Details:\n"
                    for m in markers:
                        label = m.get('label', 'N/A')
                        desc = m.get('description', 'N/A') or 'N/A'
                        coords = m.get('coordinates', {})
                        lat = coords.get('latitude', 'N/A')
                        lon = coords.get('longitude', 'N/A')
                        details_text += f"• {label}: {desc} | Coords: ({lat}, {lon})\n"

                    fig.text(0.1, 0.20, details_text, fontsize=10, verticalalignment='top', wrap=True, family='monospace')
                else:
                    fig.text(0.5, 0.5, f"Map image not found: {filename}", ha='center', va='center', fontsize=14)

                save_page(fig, "Site Maps")

            # --- SECTION 3+: Objectives ---
            for zone_name, zone_data in objectives_data.items():
                if zone_name == "General":
                    continue

                # Zone Title Page
                fig = plt.figure(figsize=(8.5, 11))
                fig.text(0.5, 0.5, zone_name, fontsize=32, fontweight='bold', ha='center', va='center', color='#2196F3')
                save_page(fig, zone_name)

                for obj in zone_data.get('objectives', []):
                    obj_num = obj.get('objective_number', 1)
                    status = obj.get('status', 'N/A')
                    objective_text = obj.get('objective', 'N/A')
                    conclusions = obj.get('conclusions', 'N/A')
                    created = obj.get('created', 'N/A')
                    updated = obj.get('updated', 'N/A')

                    # Objective Header Page
                    fig = plt.figure(figsize=(8.5, 11))
                    fig.text(0.5, 0.92, f"Objective {obj_num}", fontsize=20, fontweight='bold', ha='center')
                    fig.text(0.05, 0.87, f"Status: {status}", fontsize=14)
                    fig.text(0.05, 0.84, f"Created: {created}  |  Updated: {updated}",
                             fontsize=11, style='italic', color='gray')
                    fig.text(0.05, 0.79, "Objective:", fontsize=14, fontweight='bold')
                    fig.text(0.05, 0.74, objective_text, fontsize=12, wrap=True, va='top')
                    fig.text(0.05, 0.60, "Conclusions:", fontsize=14, fontweight='bold')
                    fig.text(0.05, 0.55, conclusions, fontsize=12, wrap=True, va='top')
                    save_page(fig, zone_name)

                    # Render Observations (Charts, Tables, Maps)
                    observations = obj.get('observations', [])
                    for obs_idx, obs in enumerate(observations):
                        form = obs.get('form', 'Table')
                        filter_data_dict = obs.get('filter_data') or {}
                        data_type = obs.get('data_type', 'spot')

                        # Extract filters for summary string
                        start_time = pd.to_datetime(filter_data_dict.get('start_time'))
                        stop_time = pd.to_datetime(filter_data_dict.get('stop_time'))
                        interval = filter_data_dict.get('interval', 'Raw')
                        selected_analytes = filter_data_dict.get('selected_analytes', [])

                        # Format summary string for the top of the page
                        start_t_str = start_time.strftime('%Y-%m-%d %H:%M') if hasattr(start_time, 'strftime') else str(start_time)
                        stop_t_str = stop_time.strftime('%Y-%m-%d %H:%M') if hasattr(stop_time, 'strftime') else str(stop_time)

                        if data_type == 'spectral':
                            summary_str = (
                                f"Data Type: Spectral Results | "
                                f"Time: {start_t_str} to {stop_t_str}"
                            )
                        elif data_type == 'exposure':
                            summary_str = (
                                f"Data Type: Exposures | "
                                f"Analytes: {', '.join(selected_analytes)} | "
                                f"Time: {start_t_str} to {stop_t_str}"
                            )
                        else:
                            summary_str = (
                                f"Data Type: {'Spot Readings' if data_type == 'spot' else 'Area Readings'} | "
                                f"Analytes: {', '.join(selected_analytes)} | "
                                f"Time: {start_t_str} to {stop_t_str} | "
                                f"Interval: {interval}"
                            )

                        # Helper to generate a "No Data" page
                        def create_no_data_page():
                            fig = plt.figure(figsize=(8.5, 11))
                            fig.text(0.05, 0.95, "Observations:", fontsize=14, fontweight='bold')
                            if summary_str:
                                fig.text(0.5, 0.90, summary_str, fontsize=10, ha='center', va='top',
                                         bbox=dict(facecolor='#f8f9fa', alpha=0.9, edgecolor='#dee2e6', boxstyle='round,pad=0.4'))
                            fig.text(0.5, 0.5, "No Data", fontsize=28, fontweight='bold', ha='center', va='center', color='gray')
                            save_page(fig, zone_name, summary_text=None)

                        # Skip unsupported forms
                        if data_type == 'exposure' and form not in ['Summary Table', 'Summary Chart', 'Table']:
                            continue
                        if data_type == 'spectral' and form != 'Table':
                            continue

                        # ==========================================
                        # NEW VIEW-BASED RENDERING LOGIC
                        # Views are self-contained and load their own data/filters
                        # We override the filters with the objective's filter_data
                        # ==========================================
                        fig = None

                        try:
                            if form == 'Table':
                                view = TableView(incident_path=incident_path, data_type=data_type)
                                view.set_filter_summary(filter_data_dict)
                                view._render()
                                fig = view.render_to_figure()

                            elif form == 'Chart' and data_type not in ['spectral', 'exposure']:
                                view = ChartView(incident_path=incident_path, data_type=data_type)
                                view.set_filter_summary(filter_data_dict)
                                view._render()
                                fig = view.render_to_figure()

                            elif form == 'Summary Chart' and data_type != 'spectral':
                                view = SummaryChartView(incident_path=incident_path, data_type=data_type)
                                view.set_filter_summary(filter_data_dict)
                                view._render()
                                fig = view.render_to_figure()

                            elif form == 'Summary Table' and data_type != 'spectral':
                                view = SummaryTableView(incident_path=incident_path, data_type=data_type)
                                view.set_filter_summary(filter_data_dict)
                                view._render()
                                fig = view.render_to_figure()

                            elif form == 'Summary Map' and data_type not in ['spectral', 'exposure']:
                                view = SummaryMapView(
                                    incident_path=incident_path,
                                    data_type=data_type,
                                    map_filenames=list(maps_data.keys()),
                                    mapping_dir=mapping_dir,
                                    maps_data=maps_data
                                )
                                view.set_filter_summary(filter_data_dict)
                                view._render()
                                fig = view.render_to_figure()

                        except Exception as e:
                            logger.error(f"Failed to render view for observation: {e}")
                            create_no_data_page()
                            continue

                        # Skip if no figure was generated
                        if fig is None:
                            continue

                        # Add standard report headers to the generated figure
                        fig.text(0.05, 0.95, "Observations:", fontsize=14, fontweight='bold')
                        if summary_str:
                            fig.text(0.5, 0.90, summary_str, fontsize=10, ha='center', va='top',
                                     bbox=dict(facecolor='#f8f9fa', alpha=0.9, edgecolor='#dee2e6', boxstyle='round,pad=0.4'))

                        save_page(fig, zone_name, summary_text=None)

        logger.info(f"✅ PDF Report generated: {pdf_path}")
        return pdf_path

    except Exception as e:
        logger.error(f"Failed to generate PDF report: {e}")
        raise e
