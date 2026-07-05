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

from datamanagement.filtering import filter_data

logger = logging.getLogger(__name__)


def load_json(filepath):
    """Helper to safely load JSON files."""
    if os.path.exists(filepath):
        with open(filepath, 'r', encoding='utf-8') as f:
            return json.load(f)
    return {}


def _load_spectral_df(incident_path):
    """Loads spectral data from spectral_locations.json into a DataFrame."""
    spectral_file = os.path.join(incident_path, "mapping", "spectral_locations.json")
    if not os.path.exists(spectral_file):
        return pd.DataFrame()

    try:
        with open(spectral_file, 'r', encoding='utf-8') as f:
            data = json.load(f)
    except Exception as e:
        logger.error(f"Failed to load spectral data: {e}")
        return pd.DataFrame()

    rows = []
    for loc in data.get("maps", {}).get("locations", []):
        for marker in loc.get("markers", []):
            label = marker.get("label", "")
            site = label if label else "Unassigned"
            for r in marker.get("readings", []):
                clean_r = {k.strip(): v for k, v in r.items()}
                row = {
                    "LOG TIME": clean_r.get("datetime"),
                    "DEVICE": clean_r.get("device", ""),
                    "SITE": site,
                    "chemicals_identified": clean_r.get("chemicals_identified", ""),
                    "comments": clean_r.get("comments", ""),
                    "file_ref": clean_r.get("file_ref", "")
                }
                rows.append(row)

    df = pd.DataFrame(rows)
    if not df.empty:
        df['LOG TIME'] = pd.to_datetime(df['LOG TIME'], errors='coerce')
        df = df.dropna(subset=['LOG TIME'])
    return df


def generate_pdf_report(incident_path, parent_widget=None):
    """Generates a comprehensive PDF report for the incident."""
    try:
        # 1. Load Configs & Metadata
        incident_data = load_json(os.path.join(incident_path, "meta", "incident.json"))
        analytes_config = load_json(os.path.join(current_dir, '..', 'static', 'lists', 'analytes.json'))
        thresholds_config = load_json(os.path.join(incident_path, "meta", "thresholds.json"))
        objectives_data = load_json(os.path.join(incident_path, "reports", "objectives.json"))

        spot_locations = load_json(os.path.join(incident_path, "mapping", "spot_locations.json"))
        area_locations = load_json(os.path.join(incident_path, "mapping", "area_locations.json"))

        # Parse analytes config
        available_analytes = []
        analyte_dec_pls = {}
        for g in analytes_config.get("analytes", []):
            name = g.get("name")
            if name:
                available_analytes.append(name)
                analyte_dec_pls[name] = int(g.get("dec_pls", 2))

        # Parse thresholds config
        thresholds_lookup = {}
        for t in thresholds_config.get("thresholds", []):
            analyte_name = str(t.get("analyte", "")).strip().upper()
            if analyte_name:
                thresholds_lookup[analyte_name] = {
                    "hotzone_value": float(t.get("hotzone_value", 0)),
                    "warmzone_value": float(t.get("warmzone_value", 0)),
                    "fireground_value": float(t.get("fireground_value", 0)),
                    "community_value": float(t.get("community_value", 0))
                }

        # Parse map structures
        spot_maps_data = {}
        for loc in spot_locations.get("maps", {}).get("locations", []):
            fname = loc.get("filename")
            if fname:
                spot_maps_data[fname] = loc.get("markers", [])

        area_maps_data = {}
        for loc in area_locations.get("maps", {}).get("locations", []):
            fname = loc.get("filename")
            if fname:
                area_maps_data[fname] = loc.get("markers", [])

        # 2. Load Raw Data (Area, Spot, AND Spectral)
        area_df = pd.DataFrame()
        area_file = os.path.join(incident_path, "data", "processed", "area_data.csv")
        if os.path.exists(area_file):
            area_df = pd.read_csv(area_file)
            area_df['LOG TIME'] = pd.to_datetime(area_df['LOG TIME'], errors='coerce')

        spot_df = pd.DataFrame()
        if os.path.exists(os.path.join(incident_path, "mapping", "spot_locations.json")):
            rows = []
            for loc in spot_locations.get("maps", {}).get("locations", []):
                for marker in loc.get("markers", []):
                    label = marker.get("label", "")
                    site = label if label else "Unassigned"
                    for r in marker.get("readings", []):
                        clean_r = {k.strip(): v for k, v in r.items()}
                        row = {
                            "LOG TIME": clean_r.get("datetime"),
                            "DEVICE": clean_r.get("device", ""),
                            "SITE": site,
                            "observations": clean_r.get("observations", "")
                        }
                        for analyte in available_analytes:
                            row[analyte] = clean_r.get(analyte)
                            row[f"INVALID_{analyte}"] = 0
                        rows.append(row)
            spot_df = pd.DataFrame(rows)
            if not spot_df.empty:
                spot_df['LOG TIME'] = pd.to_datetime(spot_df['LOG TIME'], errors='coerce')

        # Load Spectral Data
        spectral_df = _load_spectral_df(incident_path)

        # 3. Ask user where to save the PDF
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

        # 4. Generate PDF
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
            for map_type, maps_data in [("Spot", spot_maps_data), ("Area", area_maps_data)]:
                for filename, markers in maps_data.items():
                    fig = plt.figure(figsize=(8.5, 11))
                    fig.text(0.5, 0.92, f"{map_type} Map: {filename}", fontsize=18, fontweight='bold', ha='center')
                    mapping_dir = os.path.join(incident_path, "mapping")
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

                    # Objective Header Page (NO "Observations:" header here anymore)
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
                        filter_data_dict = obs.get('filter_data', {})
                        data_type = obs.get('data_type', 'spot')

                        # Select the correct raw DataFrame based on data_type
                        if data_type == 'spectral':
                            raw_df = spectral_df
                        elif data_type == 'spot':
                            raw_df = spot_df
                        else:
                            raw_df = area_df

                        if raw_df.empty:
                            continue

                        # Extract filters
                        start_time = pd.to_datetime(filter_data_dict.get('start_time'))
                        stop_time = pd.to_datetime(filter_data_dict.get('stop_time'))
                        interval = filter_data_dict.get('interval', 'Raw')
                        group_by = filter_data_dict.get('group_by', 'Device')
                        only_valid = filter_data_dict.get('only_valid', False)
                        selected_sites = filter_data_dict.get('selected_sites', [])
                        selected_devices = filter_data_dict.get('selected_devices', [])
                        selected_analytes = filter_data_dict.get('selected_analytes', [])
                        threshold_level = filter_data_dict.get('threshold_level')

                        # Apply filtering - spectral uses simple filtering, spot/area use filter_data
                        if data_type == 'spectral':
                            mask = pd.Series([True] * len(raw_df))
                            if 'LOG TIME' in raw_df.columns:
                                mask &= (raw_df['LOG TIME'] >= start_time)
                                mask &= (raw_df['LOG TIME'] <= stop_time)
                            if selected_sites and 'SITE' in raw_df.columns:
                                mask &= raw_df['SITE'].isin(selected_sites)
                            if selected_devices and 'DEVICE' in raw_df.columns:
                                mask &= raw_df['DEVICE'].isin(selected_devices)
                            filtered_df = raw_df[mask].copy()
                            if not filtered_df.empty and 'LOG TIME' in filtered_df.columns:
                                filtered_df = filtered_df.sort_values(by='LOG TIME')
                        else:
                            filtered_df = filter_data(
                                raw_df, start_time, stop_time, interval,
                                selected_sites, selected_analytes, selected_devices,
                                only_valid, group_by
                            )

                        if filtered_df.empty:
                            continue

                        # Format summary string for the top of the page
                        start_t_str = start_time.strftime('%Y-%m-%d %H:%M') if hasattr(start_time, 'strftime') else str(start_time)
                        stop_t_str = stop_time.strftime('%Y-%m-%d %H:%M') if hasattr(stop_time, 'strftime') else str(stop_time)

                        if data_type == 'spectral':
                            summary_str = (
                                f"Data Type: Spectral Results | "
                                f"Time: {start_t_str} to {stop_t_str}"
                            )
                        else:
                            summary_str = (
                                f"Data Type: {'Spot Readings' if data_type == 'spot' else 'Area Readings'} | "
                                f"Analytes: {', '.join(selected_analytes)} | "
                                f"Time: {start_t_str} to {stop_t_str} | "
                                f"Interval: {interval}"
                            )

                        fig = plt.figure(figsize=(8.5, 11))

                        # ── Add "Observations:" header at the top of this page ──
                        fig.text(0.05, 0.92, "Observations:", fontsize=14, fontweight='bold')

                        if form == 'Table':
                            ax = fig.add_axes([0.05, 0.06, 0.9, 0.80])
                            df = filtered_df.copy()
                            df.drop(columns=[c for c in df.columns if c.upper().startswith('INVALID_')], inplace=True, errors='ignore')

                            if data_type == 'spectral':
                                cols_to_show = ['LOG TIME', 'SITE', 'DEVICE', 'chemicals_identified', 'comments']
                                if 'file_ref' in df.columns:
                                    cols_to_show.append('file_ref')
                                cols_to_show = [c for c in cols_to_show if c in df.columns]
                                df = df[cols_to_show]
                            else:
                                cols_to_show = ['LOG TIME']
                                if group_by == 'Site' and 'SITE' in df.columns:
                                    cols_to_show.append('SITE')
                                elif group_by == 'Device' and 'DEVICE' in df.columns:
                                    cols_to_show.append('DEVICE')
                                cols_to_show.extend([g for g in selected_analytes if g in df.columns])
                                if interval == 'Raw' and data_type == 'spot' and 'observations' in df.columns:
                                    cols_to_show.append('observations')
                                df = df[cols_to_show]

                            if 'LOG TIME' in df.columns:
                                df['LOG TIME'] = df['LOG TIME'].dt.strftime('%Y-%m-%d %H:%M:%S')

                            if data_type != 'spectral':
                                for analyte in selected_analytes:
                                    if analyte in df.columns:
                                        dec_pls = analyte_dec_pls.get(analyte, 2)
                                        df[analyte] = df[analyte].apply(lambda x: f"{x:.{dec_pls}f}" if pd.notnull(x) else "")

                            ax.axis('off')
                            display_df = df.head(40)
                            table = ax.table(cellText=display_df.values, colLabels=display_df.columns, cellLoc='center', loc='center')
                            table.auto_set_font_size(False)
                            table.set_fontsize(8)
                            table.scale(1, 1.2)
                            for j in range(len(display_df.columns)):
                                header_color = '#9C27B0' if data_type == 'spectral' else '#4CAF50'
                                table[0, j].set_facecolor(header_color)
                                table[0, j].set_text_props(weight='bold', color='white')

                        elif form == 'Chart' and data_type != 'spectral':
                            ax = fig.add_axes([0.1, 0.08, 0.8, 0.78])
                            df = filtered_df.copy().dropna(subset=['LOG TIME']).sort_values(by='LOG TIME')
                            valid_analytes = [g for g in selected_analytes if g in df.columns]
                            group_col = 'DEVICE' if group_by == 'Device' else 'SITE'
                            if group_col == 'SITE':
                                df = df[df['SITE'].notna() & (df['SITE'].astype(str).str.strip() != '') & (df['SITE'].astype(str).str.strip().str.lower() != 'unassigned')]
                            for group_val in df[group_col].unique():
                                group_df = df[df[group_col] == group_val]
                                for analyte in valid_analytes:
                                    plot_df = group_df[['LOG TIME', analyte]].dropna()
                                    if not plot_df.empty:
                                        ax.plot(plot_df['LOG TIME'], plot_df[analyte], marker='.', linestyle='-', label=f"{group_val} - {analyte}", markersize=4)

                            if threshold_level:
                                for analyte in valid_analytes:
                                    analyte_upper = analyte.upper()
                                    if analyte_upper in thresholds_lookup:
                                        val = thresholds_lookup[analyte_upper].get(threshold_level)
                                        if val is not None:
                                            direction_label = " < " if analyte_upper.startswith("O2") else " > "
                                            ax.axhline(y=val, color='red', linestyle='--', linewidth=1.2, alpha=0.7, label=f"{analyte} threshold {direction_label} {val}")

                            max_val = 0
                            for analyte in valid_analytes:
                                if analyte in df.columns:
                                    analyte_max = df[analyte].max()
                                    if pd.notna(analyte_max) and analyte_max > max_val:
                                        max_val = analyte_max
                            if threshold_level:
                                for analyte in valid_analytes:
                                    analyte_upper = analyte.upper()
                                    if analyte_upper in thresholds_lookup:
                                        val = thresholds_lookup[analyte_upper].get(threshold_level)
                                        if val is not None and val > max_val:
                                            max_val = val
                            if max_val > 0:
                                ax.set_ylim(top=max_val * 1.1)

                            ax.xaxis.set_major_formatter(mdates.DateFormatter('%d %H:%M'))
                            ax.set_xlabel('Time')
                            ax.set_ylabel('Concentration')
                            fig.autofmt_xdate()
                            ax.legend(loc='best', fontsize='small')
                            ax.grid(True, linestyle='--', alpha=0.6)

                        elif form == 'Summary Chart' and data_type != 'spectral':
                            ax = fig.add_axes([0.1, 0.08, 0.8, 0.78])
                            group_col = 'DEVICE' if group_by == 'Device' else 'SITE'
                            valid_analytes = [g for g in selected_analytes if g in filtered_df.columns]
                            rows_data = []
                            for group_val in filtered_df[group_col].dropna().unique():
                                group_df = filtered_df[filtered_df[group_col] == group_val]
                                for analyte in valid_analytes:
                                    analyte_data = group_df[analyte].dropna()
                                    if len(analyte_data) > 0:
                                        rows_data.append({'Group': str(group_val), 'Analyte': analyte, 'Mean': analyte_data.mean()})
                            if rows_data:
                                pivot_df = pd.DataFrame(rows_data).pivot(index='Group', columns='Analyte', values='Mean')
                                pivot_df.plot(kind='bar', ax=ax, alpha=0.8)
                                ax.set_ylabel('Mean')
                                ax.set_xlabel(group_by)
                                ax.legend(title='Analyte')
                                ax.grid(True, linestyle='--', alpha=0.6, axis='y')

                        elif form == 'Summary Table' and data_type != 'spectral':
                            ax = fig.add_axes([0.05, 0.06, 0.9, 0.80])
                            group_col = 'DEVICE' if group_by == 'Device' else 'SITE'
                            valid_analytes = [g for g in selected_analytes if g in filtered_df.columns]
                            rows_data = []
                            for group_val in filtered_df[group_col].dropna().unique():
                                group_df = filtered_df[filtered_df[group_col] == group_val]
                                for analyte in valid_analytes:
                                    analyte_data = group_df[analyte].dropna()
                                    if len(analyte_data) > 0:
                                        dec_pls = analyte_dec_pls.get(analyte, 2)
                                        rows_data.append([str(group_val), analyte, f"{analyte_data.min():.{dec_pls}f}", f"{analyte_data.max():.{dec_pls}f}", f"{analyte_data.mean():.{dec_pls}f}", len(analyte_data)])
                            if rows_data:
                                ax.axis('off')
                                table = ax.table(cellText=rows_data, colLabels=['Group', 'Analyte', 'Min', 'Max', 'Mean', 'Count'], cellLoc='center', loc='center')
                                table.auto_set_font_size(False)
                                table.set_fontsize(9)
                                table.scale(1, 1.5)
                                for j in range(6):
                                    table[0, j].set_facecolor('#2196F3')
                                    table[0, j].set_text_props(weight='bold', color='white')

                        elif form == 'Summary Map' and data_type != 'spectral':
                            ax = fig.add_axes([0.1, 0.08, 0.8, 0.78])
                            maps_data = spot_maps_data if data_type == 'spot' else area_maps_data
                            map_filenames = list(maps_data.keys())
                            if map_filenames:
                                selected_map = map_filenames[0]
                                selected_analyte = selected_analytes[0] if selected_analytes else None
                                img_path = os.path.join(incident_path, "mapping", selected_map)
                                if os.path.exists(img_path):
                                    img = plt.imread(img_path)
                                    ax.imshow(img)
                                    if selected_analyte and selected_analyte in filtered_df.columns and 'SITE' in filtered_df.columns:
                                        site_aggs = filtered_df.groupby('SITE')[selected_analyte].agg(['mean']).reset_index()
                                        site_aggs.columns = ['SITE', 'Mean']
                                        for m in maps_data.get(selected_map, []):
                                            label, x, y = m.get('label', ''), m.get('x', 0), m.get('y', 0)
                                            site_row = site_aggs[site_aggs['SITE'] == label]
                                            text = f"{site_row.iloc[0]['Mean']:.{analyte_dec_pls.get(selected_analyte, 2)}f}" if not site_row.empty else "N/A"
                                            circle = Circle((x, y), 8, color='yellow', ec='red', lw=2, zorder=5)
                                            ax.add_patch(circle)
                                            ax.text(x + 12, y + 5, f"{label}: {text}", color='black', fontsize=9, fontweight='bold', bbox=dict(facecolor='white', alpha=0.7, edgecolor='none', pad=1), zorder=6)
                                    ax.axis('off')
                                else:
                                    ax.text(0.5, 0.5, "Map image not found", ha='center', va='center')
                            else:
                                ax.text(0.5, 0.5, "No maps available", ha='center', va='center')

                        # Save the observation page with the summary string
                        save_page(fig, zone_name, summary_text=summary_str)

        logger.info(f"✅ PDF Report generated: {pdf_path}")
        return pdf_path

    except Exception as e:
        logger.error(f"Failed to generate PDF report: {e}")
        raise e
