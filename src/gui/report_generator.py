import os
import sys
import json
import datetime
import tempfile
import pandas as pd
import logging
from PySide6.QtWidgets import QFileDialog
from PySide6.QtGui import QPixmap

# Matplotlib is ONLY used to render Chart/Map views to temporary PNGs.
# ReportLab handles ALL document layout, tables, and text.
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

# ReportLab imports
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.lib.utils import ImageReader
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle,
    PageBreak, Image
)

# Ensure parent directory is in sys.path for local imports
current_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.dirname(current_dir)
if parent_dir not in sys.path:
    sys.path.insert(0, parent_dir)

from datamanagement.db_manager import IncidentDatabase
from map_renderer import save_rendered_map_to_temp

# Import the modular views to eliminate rendering duplication
from table_view import TableView
from chart_view import ChartView
from summary_table_view import SummaryTableView
from summary_chart_view import SummaryChartView
from summary_map_view import SummaryMapView

logger = logging.getLogger(__name__)

# ── Cache stylesheets and styles at module level ──
_STYLES = getSampleStyleSheet()
_STYLE_NORMAL = _STYLES['Normal']
_STYLE_TITLE = _STYLES['Title']
_STYLE_HEADING1 = _STYLES['Heading1']
_STYLE_BIG_TITLE = ParagraphStyle('BigTitle', parent=_STYLE_TITLE, fontSize=28, alignment=1, spaceAfter=20)
_STYLE_SUB_TITLE = ParagraphStyle('SubTitle', parent=_STYLE_TITLE, fontSize=22, alignment=1, spaceAfter=40)
_STYLE_DETAIL = ParagraphStyle('Detail', parent=_STYLE_NORMAL, fontSize=16, alignment=1, spaceAfter=10)
_STYLE_DETAIL_SM = ParagraphStyle('DetailSm', parent=_STYLE_NORMAL, fontSize=14, alignment=1, spaceAfter=10)
_STYLE_ZONE = ParagraphStyle('ZoneTitle', parent=_STYLE_TITLE, fontSize=32, alignment=1, textColor=colors.HexColor('#2196F3'))
_STYLE_NO_DATA = ParagraphStyle('NoData', parent=_STYLE_NORMAL, fontSize=24, alignment=1, textColor=colors.gray)
_STYLE_HEADER_CELL = ParagraphStyle('HeaderCell', parent=_STYLE_NORMAL, fontSize=8, textColor=colors.whitesmoke, alignment=1)
_STYLE_SUMMARY_HEADER = ParagraphStyle('SummaryHeader', parent=_STYLE_NORMAL, fontSize=9, textColor=colors.whitesmoke, alignment=1)

def load_json(filepath):
    if os.path.exists(filepath):
        with open(filepath, 'r', encoding='utf-8') as f:
            return json.load(f)
    return {}

def format_table_header(col_name):
    """Splits long column names into multiple lines for ReportLab tables."""
    col_str = str(col_name)
    suffix = ""
    for s in ['_min', '_max', '_mean', '_count']:
        if col_str.endswith(s):
            suffix = s[1:]
            col_str = col_str[:-len(s)]
            break

    if '(' in col_str and ')' in col_str:
        base = col_str.split('(')[0]
        unit = col_str.split('(')[1].split(')')[0]
        parts = [base, unit]
    else:
        parts = [col_str]

    if suffix:
        parts.append(suffix)

    return "<br/>".join(parts)

def create_pdf_table_from_df(df, dec_pls_dict=None):
    """Converts a pandas DataFrame to a ReportLab Table."""
    if df is None or df.empty:
        return [Paragraph("No Data", _STYLE_NORMAL)]

    if dec_pls_dict is None:
        dec_pls_dict = {}

    cols_to_show = [c for c in df.columns if not str(c).upper().startswith('INVALID_')]
    display_df = df[cols_to_show].copy()

    if 'LOG TIME' in display_df.columns:
        display_df['LOG TIME'] = display_df['LOG TIME'].dt.strftime('%Y-%m-%d %H:%M:%S')

    # Helper to resolve decimal places for base and aggregated columns
    def get_dec_pls(col_name):
        if col_name in dec_pls_dict:
            return dec_pls_dict[col_name]
        for suffix in ('_min', '_max', '_mean', '_count'):
            if col_name.endswith(suffix):
                base = col_name[:-len(suffix)]
                if base in dec_pls_dict:
                    return dec_pls_dict[base]
        return 2  # Default fallback

    for col in display_df.columns:
        if pd.api.types.is_numeric_dtype(display_df[col]):
            dec_pls = get_dec_pls(col)
            display_df[col] = display_df[col].apply(lambda x: f"{x:.{dec_pls}f}" if pd.notna(x) else "")
        else:
            display_df[col] = display_df[col].fillna("").astype(str)

    col_labels = [Paragraph(format_table_header(c), _STYLE_HEADER_CELL) for c in display_df.columns.tolist()]
    data = [col_labels]
    for _, row in display_df.iterrows():
        data.append([str(val) for val in row])

    # Calculate specific column widths
    col_widths = []
    for col in display_df.columns:
        if col == 'LOG TIME':
            col_widths.append(1.6 * inch)
        elif col == 'DEVICE':
            col_widths.append(1.2 * inch)
        elif col == 'SITE':
            col_widths.append(0.7 * inch)
        elif col == 'observations':
            col_widths.append(2.0 * inch)
        elif col in dec_pls_dict or any(col.endswith(s) for s in ('_min', '_max', '_mean', '_count')):
            col_widths.append(0.7 * inch)
        else:
            col_widths.append(0.9 * inch)

    # Scale down proportionally if total width exceeds available page width
    total_width = sum(col_widths)
    max_width = 9.5 * inch
    if total_width > max_width:
        scale = max_width / total_width
        col_widths = [w * scale for w in col_widths]

    table = Table(data, colWidths=col_widths, repeatRows=1)
    table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#2563eb')),
        ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('FONTNAME', (0, 1), (-1, -1), 'Helvetica'),
        ('FONTSIZE', (0, 1), (-1, -1), 7),
        ('BOTTOMPADDING', (0, 0), (-1, 0), 8),
        ('TOPPADDING', (0, 0), (-1, 0), 8),
        ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor('#f9fafb')]),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#d1d5db')),
    ]))
    return [table]

def create_pdf_summary_table(summary_data, group_by_label):
    """Converts summary data to a ReportLab Table."""
    if not summary_data:
        return [Paragraph("No Summary Data", _STYLE_NORMAL)]

    col_labels = [
        Paragraph(format_table_header(group_by_label), _STYLE_SUMMARY_HEADER),
        Paragraph("Analyte", _STYLE_SUMMARY_HEADER),
        Paragraph("Minimum", _STYLE_SUMMARY_HEADER),
        Paragraph("Maximum", _STYLE_SUMMARY_HEADER),
        Paragraph("Mean", _STYLE_SUMMARY_HEADER),
        Paragraph("Count", _STYLE_SUMMARY_HEADER),
    ]
    data = [col_labels]
    for row in summary_data:
        grp, analyte, min_v, max_v, mean_v, count_v, dec_pls = row
        data.append([
            str(grp), str(analyte),
            f"{min_v:.{dec_pls}f}" if pd.notna(min_v) else "",
            f"{max_v:.{dec_pls}f}" if pd.notna(max_v) else "",
            f"{mean_v:.{dec_pls}f}" if pd.notna(mean_v) else "",
            str(count_v),
        ])

    table = Table(data, colWidths=[1.5*inch, 1.5*inch, 1.2*inch, 1.2*inch, 1.2*inch, 0.9*inch], repeatRows=1)
    table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#10b981')),
        ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('FONTNAME', (0, 1), (-1, -1), 'Helvetica'),
        ('FONTSIZE', (0, 1), (-1, -1), 8),
        ('BOTTOMPADDING', (0, 0), (-1, 0), 8),
        ('TOPPADDING', (0, 0), (-1, 0), 8),
        ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor('#ecfdf5')]),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#d1d5db')),
    ]))
    return [table]

def _make_image_flowable(filepath, max_width=10*inch):
    """Creates a ReportLab Image that scales proportionally to max_width."""
    try:
        reader = ImageReader(filepath)
        iw, ih = reader.getSize()
        aspect = ih / iw if iw > 0 else 0.75
        draw_width = max_width
        draw_height = draw_width * aspect
        max_height = 5.5 * inch
        if draw_height > max_height:
            draw_height = max_height
            draw_width = draw_height / aspect
        return Image(filepath, width=draw_width, height=draw_height)
    except Exception:
        return Image(filepath, width=max_width, height=5*inch)

def add_page_number(canvas, doc, footer_text):
    """Draws the footer on every page using correct landscape dimensions."""
    canvas.saveState()
    canvas.setFont('Helvetica-Oblique', 9)
    canvas.setFillColor(colors.gray)
    width, _ = landscape(A4)
    canvas.drawCentredString(width / 2, 0.4 * inch, "FRV Hazmat Air Monitoring Report")
    canvas.drawString(0.5 * inch, 0.4 * inch, footer_text)
    canvas.drawRightString(width - 0.5 * inch, 0.4 * inch, f"Page {doc.page}")
    canvas.restoreState()

def generate_pdf_report(incident_path, parent_widget=None):
    temp_files = []
    try:
        # 1. Load Configs & Metadata
        incident_data = load_json(os.path.join(incident_path, "meta", "incident.json"))
        objectives_data = load_json(os.path.join(incident_path, "reports", "objectives.json"))

        # ✅ USE DB MANAGER FOR MAPS
        db = IncidentDatabase(incident_path)
        raw_maps_data = db.get_maps_data()
        mapping_dir = os.path.join(incident_path, "mapping")
        
        # ✅ FIX: Transform flat DB markers to include nested 'coordinates' and flat 'x'/'y' 
        # This ensures compatibility with map_renderer.py and the Location Directory
        maps_data = {}
        for fname, markers in raw_maps_data.items():
            formatted_markers = []
            for m in markers:
                fm = dict(m)
                fm['coordinates'] = {
                    'x': m.get('x_coord'),
                    'y': m.get('y_coord'),
                    'latitude': m.get('latitude'),
                    'longitude': m.get('longitude')
                }
                fm['x'] = m.get('x_coord')
                fm['y'] = m.get('y_coord')
                formatted_markers.append(fm)
            maps_data[fname] = formatted_markers

        # ✅ USE DB MANAGER FOR PLUMES
        plume_data = []
        db_plumes = db.get_plumes()
        for p in db_plumes:
            file_name = p.get("file_name")
            model_dt_str = p.get("model_dt")
            if not file_name or not model_dt_str:
                continue
            filepath = os.path.join(incident_path, "plumes", file_name)
            if not os.path.exists(filepath):
                continue
            try:
                clean_str = model_dt_str.replace('Z', '+00:00')
                dt = datetime.datetime.fromisoformat(clean_str)
                if dt.tzinfo:
                    dt = dt.astimezone().replace(tzinfo=None)
                plume_data.append((dt, filepath))
            except Exception:
                continue
        plume_data.sort(key=lambda x: x[0])

        # 2. Ask user where to save the PDF
        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        default_filename = f"Air_Monitoring_Report_{timestamp}.pdf"
        pdf_path, _ = QFileDialog.getSaveFileName(parent_widget, "Save PDF Report", default_filename, "PDF Files (*.pdf);;All Files (*)")
        if not pdf_path:
            logger.info("PDF report generation cancelled by user.")
            return None
        if not pdf_path.lower().endswith('.pdf'):
            pdf_path += '.pdf'

        # 3. Generate PDF
        doc = SimpleDocTemplate(pdf_path, pagesize=landscape(A4), rightMargin=0.5*inch, leftMargin=0.5*inch, topMargin=0.8*inch, bottomMargin=0.6*inch)
        story = []
        footer_label = incident_data.get('label', 'Air Monitoring Report')

        def add_observation_header(data_type, summary_str):
            story.append(Paragraph("<b>Observations:</b>", _STYLE_HEADING1))
            type_display_map = {"area": "Area Data", "spot": "Spot Data", "spectral": "Spectral Data", "exposure": "Exposure Data", "plume": "Plume Data"}
            type_display = type_display_map.get(data_type, "Unknown Data")
            story.append(Paragraph(f"<i>{type_display}</i>", _STYLE_NORMAL))
            story.append(Spacer(1, 0.1*inch))
            if summary_str:
                story.append(Paragraph(summary_str, _STYLE_NORMAL))
                story.append(Spacer(1, 0.2*inch))

        # ── PAGE 1: Title Page ──
        story.append(Spacer(1, 2*inch))
        story.append(Paragraph("Fire Rescue Victoria", _STYLE_BIG_TITLE))
        story.append(Paragraph("Air Monitoring Report", _STYLE_SUB_TITLE))
        story.append(Paragraph(f"Incident: {incident_data.get('label', 'N/A')}", _STYLE_DETAIL))
        story.append(Paragraph(f"Address: {incident_data.get('address', 'N/A')}", _STYLE_DETAIL_SM))
        now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        story.append(Paragraph(f"Published: {now_str}", _STYLE_DETAIL_SM))
        story.append(PageBreak())

        # ── SECTION 2: Initial Maps (Images Only) ──
        for filename, markers in maps_data.items():
            story.append(Paragraph(f"Map: {filename}", _STYLE_HEADING1))
            story.append(Spacer(1, 0.2*inch))
            img_path = os.path.join(mapping_dir, filename)
            if os.path.exists(img_path):
                pixmap = QPixmap(img_path)
                rendered_path = save_rendered_map_to_temp(pixmap, markers, options={"font_size": 12, "circle_radius": 10}, temp_files=temp_files)
                final_img_path = rendered_path if rendered_path else img_path
                story.append(_make_image_flowable(final_img_path))
            else:
                story.append(Paragraph(f"Map image not found: {filename}", _STYLE_NORMAL))
            story.append(Spacer(1, 0.3*inch))
            story.append(PageBreak())

        # ── SECTION 2B: Combined Location Directory ──
        story.append(Paragraph("Location Directory", _STYLE_HEADING1))
        story.append(Spacer(1, 0.2*inch))
        unique_markers = {}
        for filename, markers in maps_data.items():
            for m in markers:
                label = m.get('label', 'N/A')
                if label and label not in unique_markers:
                    unique_markers[label] = m

        loc_table_data = [[Paragraph("<b>Label</b>", _STYLE_HEADER_CELL), Paragraph("<b>Description</b>", _STYLE_HEADER_CELL), Paragraph("<b>Latitude</b>", _STYLE_HEADER_CELL), Paragraph("<b>Longitude</b>", _STYLE_HEADER_CELL)]]
        for label in sorted(unique_markers.keys()):
            m = unique_markers[label]
            desc = m.get('description', '') or 'N/A'
            
            # ✅ FIX: Handle both flat DB structure and nested structure for Lat/Lon
            lat = m.get('latitude')
            lon = m.get('longitude')
            if lat is None or lon is None:
                coords = m.get('coordinates', {})
                if lat is None: lat = coords.get('latitude')
                if lon is None: lon = coords.get('longitude')
                
            lat_str = f"{lat:.6f}" if lat is not None else "N/A"
            lon_str = f"{lon:.6f}" if lon is not None else "N/A"
            loc_table_data.append([label, desc, lat_str, lon_str])

        if len(loc_table_data) > 1:
            col_widths = [1.0*inch, 4.5*inch, 1.5*inch, 1.5*inch]
            loc_table = Table(loc_table_data, colWidths=col_widths, repeatRows=1)
            loc_table.setStyle(TableStyle([
                ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#2563eb')),
                ('ALIGN', (0, 0), (1, -1), 'LEFT'), ('ALIGN', (2, 0), (3, -1), 'CENTER'),
                ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'), ('FONTNAME', (0, 1), (-1, -1), 'Helvetica'),
                ('FONTSIZE', (0, 1), (-1, -1), 9), ('BOTTOMPADDING', (0, 0), (-1, 0), 8),
                ('TOPPADDING', (0, 0), (-1, 0), 8), ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor('#f9fafb')]),
                ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#d1d5db')),
            ]))
            story.append(loc_table)
        else:
            story.append(Paragraph("No markers defined.", _STYLE_NORMAL))
        story.append(Spacer(1, 0.3*inch))
        story.append(PageBreak())

        # ── SECTION 3+: Objectives ──
        for zone_name, zone_data in objectives_data.items():
            if zone_name == "General": continue
            story.append(Spacer(1, 3*inch))
            story.append(Paragraph(zone_name, _STYLE_ZONE))
            story.append(PageBreak())

            for obj in zone_data.get('objectives', []):
                obj_num = obj.get('objective_number', 1)
                status = obj.get('status', 'N/A')
                objective_text = obj.get('objective', 'N/A')
                strategy_text = obj.get('strategy', 'N/A')
                conclusions = obj.get('conclusions', 'N/A')
                created = obj.get('created', 'N/A')
                updated = obj.get('updated', 'N/A')

                story.append(Paragraph(f"Objective {obj_num}", _STYLE_HEADING1))
                story.append(Paragraph(f"<b>Status:</b> {status} | <b>Created:</b> {created} | <b>Updated:</b> {updated}", _STYLE_NORMAL))
                story.append(Spacer(1, 0.2*inch))
                story.append(Paragraph("<b>Objective:</b>", _STYLE_NORMAL))
                story.append(Paragraph(objective_text, _STYLE_NORMAL))
                story.append(Spacer(1, 0.1*inch))
                story.append(Paragraph("<b>Strategy:</b>", _STYLE_NORMAL))
                story.append(Paragraph(strategy_text, _STYLE_NORMAL))
                story.append(Spacer(1, 0.2*inch))
                story.append(Paragraph("<b>Conclusions:</b>", _STYLE_NORMAL))
                story.append(Paragraph(conclusions, _STYLE_NORMAL))
                story.append(Spacer(1, 0.3*inch))
                story.append(PageBreak())

                observations = obj.get('observations', [])
                for obs in observations:
                    form = obs.get('form', 'Table')
                    filter_data_dict = obs.get('filter_data') or {}
                    data_type = obs.get('data_type', 'spot')
                    
                    start_time = pd.to_datetime(filter_data_dict.get('start_time'))
                    stop_time = pd.to_datetime(filter_data_dict.get('stop_time'))
                    interval = filter_data_dict.get('interval', 'Raw')
                    if data_type == 'spot': interval = 'Raw'
                    
                    selected_analytes = filter_data_dict.get('selected_analytes', [])
                    
                    start_t_str = start_time.strftime('%Y-%m-%d %H:%M') if hasattr(start_time, 'strftime') else str(start_time)
                    stop_t_str = stop_time.strftime('%Y-%m-%d %H:%M') if hasattr(stop_time, 'strftime') else str(stop_time)
                    
                    summary_parts = []
                    if data_type != 'spectral' and selected_analytes:
                        summary_parts.append(f"<b>Analytes:</b> {', '.join(selected_analytes)}")
                    if data_type not in ['spectral', 'exposure', 'spot', 'plume']:
                        summary_parts.append(f"<b>Interval:</b> {interval}")
                    summary_parts.append(f"<b>Time:</b> {start_t_str} to {stop_t_str}")
                    summary_str = " | ".join(summary_parts)

                    if data_type == 'exposure' and form not in ['Summary Table', 'Summary Chart', 'Table']: continue
                    if data_type == 'spectral' and form != 'Table': continue
                    if data_type == 'plume' and form != 'Summary Map': continue

                    try:
                        add_observation_header(data_type, summary_str)
                        
                        if form == 'Table':
                            view = TableView(incident_path=incident_path, data_type=data_type)
                            view.set_filter_summary(filter_data_dict)
                            view._render()
                            story.extend(create_pdf_table_from_df(view.filtered_data, dec_pls_dict=view.analyte_dec_pls))
                            
                        elif form == 'Chart' and data_type not in ['spectral', 'exposure', 'plume']:
                            view = ChartView(incident_path=incident_path, data_type=data_type)
                            view.set_filter_summary(filter_data_dict)
                            view._render()
                            fig = view.render_to_figure()
                            tmp = tempfile.NamedTemporaryFile(suffix='.png', delete=False)
                            tmp_path = tmp.name
                            tmp.close()
                            fig.savefig(tmp_path, bbox_inches='tight', dpi=150)
                            plt.close(fig)
                            story.append(_make_image_flowable(tmp_path))
                            temp_files.append(tmp_path)
                            
                        elif form == 'Summary Chart' and data_type not in ['spectral', 'plume']:
                            view = SummaryChartView(incident_path=incident_path, data_type=data_type)
                            view.set_filter_summary(filter_data_dict)
                            view._report_stats_pref = filter_data_dict.get("stats_pref", "Mean")
                            view._render()
                            fig = view.render_to_figure()
                            tmp = tempfile.NamedTemporaryFile(suffix='.png', delete=False)
                            tmp_path = tmp.name
                            tmp.close()
                            fig.savefig(tmp_path, bbox_inches='tight', dpi=150)
                            plt.close(fig)
                            story.append(_make_image_flowable(tmp_path))
                            temp_files.append(tmp_path)
                            
                        elif form == 'Summary Table' and data_type not in ['spectral', 'plume']:
                            view = SummaryTableView(incident_path=incident_path, data_type=data_type)
                            view.set_filter_summary(filter_data_dict)
                            view._render()
                            group_by_label = "Identifier" if data_type == "exposure" else view.filter_summary.get("group_by", "Device")
                            story.extend(create_pdf_summary_table(view.summary_data, group_by_label))
                            
                        elif form == 'Summary Map':
                            if data_type == 'plume':
                                start_t = filter_data_dict.get('start_time')
                                stop_t = filter_data_dict.get('stop_time')
                                if isinstance(start_t, str): start_t = pd.to_datetime(start_t)
                                if isinstance(stop_t, str): stop_t = pd.to_datetime(stop_t)
                                filtered_plumes = []
                                for dt, filepath in plume_data:
                                    if start_t and pd.notna(start_t) and dt < start_t: continue
                                    if stop_t and pd.notna(stop_t) and dt > stop_t: continue
                                    filtered_plumes.append((dt, filepath))
                                if not filtered_plumes:
                                    story.append(Paragraph("No plume images found in the selected time range.", _STYLE_NORMAL))
                                else:
                                    for i, (dt, filepath) in enumerate(filtered_plumes):
                                        if i > 0: story.append(PageBreak())
                                        local_time_str = dt.strftime('%Y-%m-%d %H:%M')
                                        story.append(Paragraph(f"<b>Air Dispersion Prediction for {local_time_str}</b>", _STYLE_NORMAL))
                                        story.append(Spacer(1, 0.1*inch))
                                        story.append(_make_image_flowable(filepath))
                                        story.append(Spacer(1, 0.2*inch))
                            elif data_type not in ['spectral', 'exposure']:
                                view = SummaryMapView(incident_path=incident_path, data_type=data_type, map_filenames=list(maps_data.keys()), mapping_dir=mapping_dir, maps_data=maps_data)
                                view.set_filter_summary(filter_data_dict)
                                view._report_stats_pref = filter_data_dict.get("stats_pref", "Mean")
                                view._render()
                                fig = view.render_to_figure()
                                tmp = tempfile.NamedTemporaryFile(suffix='.png', delete=False)
                                tmp_path = tmp.name
                                tmp.close()
                                fig.savefig(tmp_path, bbox_inches='tight', dpi=150)
                                plt.close(fig)
                                story.append(_make_image_flowable(tmp_path))
                                temp_files.append(tmp_path)
                    except Exception as e:
                        logger.error(f"Failed to render view for observation: {e}")
                        add_observation_header(data_type, summary_str)
                        story.append(Paragraph("No Data", _STYLE_NO_DATA))
                    story.append(Spacer(1, 0.3*inch))
                    story.append(PageBreak())

        doc.build(story, onFirstPage=lambda c, d: add_page_number(c, d, "Title Page"), onLaterPages=lambda c, d: add_page_number(c, d, footer_label))
        logger.info(f"✅ PDF Report generated: {pdf_path}")
        return pdf_path

    except Exception as e:
        logger.error(f"Failed to generate PDF report: {e}")
        raise e
    finally:
        for tmp_path in temp_files:
            try: os.remove(tmp_path)
            except Exception: pass
