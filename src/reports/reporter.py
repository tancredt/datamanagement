import os
import json
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from datetime import datetime
from tzlocal import get_localzone

def plot_sensor_timeseries(df, start_time, end_time, sensor_column, 
                          group_by_serial=True, figsize=(12, 6), title=None):
    start_dt = ensure_local_tz(start_time)
    end_dt = ensure_local_tz(end_time)
    
    if df['LOG TIME'].dt.tz != LOCAL_TZ:
        df['LOG TIME'] = df['LOG TIME'].dt.tz_convert(LOCAL_TZ)
    
    mask = (df['LOG TIME'] >= start_dt) & (df['LOG TIME'] <= end_dt)
    df_filtered = df[mask]
    
    if df_filtered.empty:
        print(f"⚠️  No data found between {start_time} and {end_time}")
        return None, None
        
    if sensor_column not in df_filtered.columns:
        print(f"❌ Column '{sensor_column}' not found. Available: {list(df_filtered.columns)}")
        return None, None
    
    fig, ax = plt.subplots(figsize=figsize)
    
    if group_by_serial and 'SERIAL NUMBER' in df_filtered.columns:
        for serial, group in df_filtered.groupby('SERIAL NUMBER'):
            ax.plot(group['LOG TIME'], group[sensor_column], 
                   label=f"Device: {serial}", marker='o', markersize=3, linewidth=1)
        ax.legend(loc='best', fontsize=8)
    else:
        ax.plot(df_filtered['LOG TIME'], df_filtered[sensor_column], 
               marker='o', markersize=3, linewidth=1)
    
    ax.set_xlabel('Time', fontsize=10)
    ax.set_ylabel(sensor_column, fontsize=10)
    ax.set_title(title or f"{sensor_column} Readings ({start_time} to {end_time})", 
                fontsize=12, fontweight='bold')
    ax.grid(True, alpha=0.3, linestyle='--')
    
    ax.xaxis.set_major_formatter(mdates.DateFormatter('%m/%d %H:%M'))
    ax.xaxis.set_major_locator(mdates.AutoDateLocator())
    plt.setp(ax.xaxis.get_majorticklabels(), rotation=45, ha='right')
    plt.tight_layout()
    
    return fig, ax

#if __name__ == "__main__":
    #fig, ax = plot_sensor_timeseries(df, "2026-05-17 17:00:00", "2026-05-17 20:30:00", "H2S(ppm)")
    #if fig:
        #fig.savefig("h2s_plot.png", dpi=300, bbox_inches='tight')
        #print("✅ Plot saved to h2s_plot.png")
