import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import urllib.request
import webbrowser
import zipfile
import traceback
from dataclasses import dataclass
from datetime import datetime

import numpy as np
import pandas as pd
import seaborn as sns
from FlowCytometryTools import FCMeasurement, PolyGate, QuadGate, ThresholdGate
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg, NavigationToolbar2Tk
from matplotlib.figure import Figure
from matplotlib.path import Path
from matplotlib.widgets import PolygonSelector
import tkinter as tk
from tkinter import colorchooser, filedialog, messagebox, ttk

from ._app_version import __version__


GITHUB_REPO = "siddharthriyer/FlowJitsu"
GITHUB_RELEASES_URL = f"https://github.com/{GITHUB_REPO}/releases"
GITHUB_LATEST_RELEASE_API = f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"
DOWNLOADS_SUBDIR = "FlowGateAppUpdates"


def _normalize_instrument_name(instrument):
    if instrument is None:
        return "cytoflex"
    normalized = instrument.strip().lower()
    if normalized == "symphopny":
        normalized = "symphony"
    return normalized


def _preferred_data_dir(start_path):
    current = os.path.abspath(start_path)
    candidates = []
    if os.path.isdir(current):
        candidates.extend([
            os.path.join(current, "Data"),
            os.path.join(current, "data"),
            os.path.join(current, "..", "Data"),
            os.path.join(current, "..", "data"),
        ])
    else:
        parent = os.path.dirname(current)
        candidates.extend([
            os.path.join(parent, "Data"),
            os.path.join(parent, "data"),
            os.path.join(parent, "..", "Data"),
            os.path.join(parent, "..", "data"),
        ])
    for path in candidates:
        path = os.path.abspath(path)
        if os.path.isdir(path):
            return path
    return current if os.path.isdir(current) else os.path.dirname(current)


def _list_fcs_files(datadir, instrument="Cytoflex"):
    instrument = _normalize_instrument_name(instrument)
    fcs_files = []
    for root, _, files in os.walk(datadir):
        for file in files:
            if file.lower().endswith(".fcs"):
                relpath = os.path.relpath(os.path.join(root, file), datadir)
                fcs_files.append(relpath)
        if instrument != "symphony" and fcs_files:
            break
    return sorted(fcs_files)


def _get_well_name(file, instrument="Cytoflex"):
    filename = os.path.basename(file)
    instrument = _normalize_instrument_name(instrument)
    if instrument in {"cytoflex", "symphony"}:
        match = re.search(r"([A-H])(0?[1-9]|1[0-2])(?=\.fcs|\b)", filename, re.IGNORECASE)
        if match:
            row, col = match.groups()
            return f"{row.upper()}{int(col)}"
    raise ValueError(f"Could not determine well name from file: {file}")


def _get_channel_names(sample):
    channels = sample.channels
    if hasattr(channels, "columns"):
        for column in ("$PnS", "$PnN"):
            if column in channels.columns:
                values = channels[column].dropna().astype(str)
                values = [value.strip() for value in values if value.strip()]
                if values:
                    return values
        return list(channels.index.astype(str))
    return [str(channel) for channel in channels]


def _transform_array(values, method, cofactor):
    arr = np.asarray(values, dtype=float)
    if method == "linear":
        return arr
    if method == "log10":
        return np.log10(np.clip(arr, 1, None))
    if method == "arcsinh":
        return np.arcsinh(arr / max(float(cofactor), 1e-9))
    raise ValueError(f"Unsupported transform: {method}")


def _apply_transform(df, x_channel, y_channel, method, cofactor):
    transformed = pd.DataFrame(index=df.index.copy())
    transformed[x_channel] = _transform_array(df[x_channel].to_numpy(), method, cofactor)
    transformed[y_channel] = _transform_array(df[y_channel].to_numpy(), method, cofactor)
    return transformed


def _gate_plot_y_channel(gate):
    return gate["y_channel"] if gate.get("y_channel") else gate["x_channel"]


def _is_count_axis(value):
    return str(value).strip().lower() in {"count", "__count__"}


def _event_adds_to_selection(event):
    state = int(getattr(event, "state", 0))
    return bool(state & 0x0001 or state & 0x0004 or state & 0x0008 or state & 0x0010)


def _normalize_version_tag(version):
    return str(version).strip().lstrip("vV")


def _version_key(version):
    parts = re.findall(r"\d+", _normalize_version_tag(version))
    return tuple(int(part) for part in parts) if parts else (0,)


def _gate_mask(transformed_df, gate_spec):
    gate_type = gate_spec["gate_type"]
    x_channel = gate_spec["x_channel"]
    x_values = transformed_df[x_channel].to_numpy()

    if gate_type == "polygon":
        y_channel = gate_spec["y_channel"]
        points = transformed_df[[x_channel, y_channel]].to_numpy()
        return Path(gate_spec["vertices"]).contains_points(points)

    if gate_type == "quad":
        y_channel = gate_spec["y_channel"]
        y_values = transformed_df[y_channel].to_numpy()
        x0 = gate_spec["x_threshold"]
        y0 = gate_spec["y_threshold"]
        region = gate_spec["region"]
        if region == "top right":
            return (x_values >= x0) & (y_values >= y0)
        if region == "top left":
            return (x_values < x0) & (y_values >= y0)
        if region == "bottom left":
            return (x_values < x0) & (y_values < y0)
        if region == "bottom right":
            return (x_values >= x0) & (y_values < y0)
        raise ValueError(f"Unsupported quad region: {region}")

    if gate_type == "vertical":
        threshold = gate_spec["x_threshold"]
        if gate_spec["region"] == "above":
            return x_values >= threshold
        if gate_spec["region"] == "below":
            return x_values < threshold
        raise ValueError(f"Unsupported threshold region: {gate_spec['region']}")

    if gate_type == "horizontal":
        y_channel = gate_spec["y_channel"]
        y_values = transformed_df[y_channel].to_numpy()
        threshold = gate_spec["y_threshold"]
        if gate_spec["region"] == "above":
            return y_values >= threshold
        if gate_spec["region"] == "below":
            return y_values < threshold
        raise ValueError(f"Unsupported threshold region: {gate_spec['region']}")

    raise ValueError(f"Unsupported gate type: {gate_type}")


def _render_gate(ax, gate_spec, selected=False):
    color = gate_spec.get("color", "crimson")
    linewidth = 2.5 if selected else 1.8
    if gate_spec["gate_type"] == "polygon":
        vertices = np.asarray(gate_spec["vertices"])
        closed = np.vstack([vertices, vertices[0]])
        ax.plot(closed[:, 0], closed[:, 1], color=color, linewidth=linewidth)
        return
    if gate_spec["gate_type"] == "quad":
        ax.axvline(gate_spec["x_threshold"], color=color, linewidth=linewidth)
        ax.axhline(gate_spec["y_threshold"], color=color, linewidth=linewidth)
        return
    if gate_spec["gate_type"] == "vertical":
        ax.axvline(gate_spec["x_threshold"], color=color, linewidth=linewidth)
        return

    if gate_spec["gate_type"] == "horizontal":
        ax.axhline(gate_spec["y_threshold"], color=color, linewidth=linewidth)


def _build_flow_gate(gate_spec):
    if gate_spec["gate_type"] == "polygon":
        return PolyGate(
            gate_spec["vertices"],
            channels=(gate_spec["x_channel"], gate_spec["y_channel"]),
            region="in",
            name=gate_spec["name"],
        )
    if gate_spec["gate_type"] == "quad":
        return QuadGate(
            (gate_spec["x_threshold"], gate_spec["y_threshold"]),
            channels=[gate_spec["x_channel"], gate_spec["y_channel"]],
            region=gate_spec["region"],
            name=gate_spec["name"],
        )
    if gate_spec["gate_type"] == "vertical":
        return ThresholdGate(
            gate_spec["x_threshold"],
            channels=[gate_spec["x_channel"]],
            region=gate_spec["region"],
            name=gate_spec["name"],
        )
    if gate_spec["gate_type"] == "horizontal":
        return ThresholdGate(
            gate_spec["y_threshold"],
            channels=[gate_spec["y_channel"]],
            region=gate_spec["region"],
            name=gate_spec["name"],
        )
    raise ValueError(f"Unsupported gate type: {gate_spec['gate_type']}")


@dataclass
class PendingGate:
    gate_type: str
    payload: dict


class FlowDesktopApp:
    def __init__(self, base_dir=None, instrument="Cytoflex", max_points=15000):
        self.base_dir = base_dir or os.getcwd()
        self.max_points_default = int(max_points)
        self.root = tk.Tk()
        self.root.title(f"Flow Gate Desktop v{__version__}")
        self.root.geometry("1440x840")

        self.folder_var = tk.StringVar(value=self.base_dir)
        self.instrument_var = tk.StringVar(value=instrument)
        self.population_var = tk.StringVar(value="__all__")
        self.x_var = tk.StringVar()
        self.y_var = tk.StringVar()
        self.transform_var = tk.StringVar(value="arcsinh")
        self.cofactor_var = tk.DoubleVar(value=150.0)
        self.max_points_var = tk.IntVar(value=self.max_points_default)
        self.y_plot_mode_var = tk.StringVar(value="scatter")
        self.gate_type_var = tk.StringVar(value="polygon")
        self.gate_name_var = tk.StringVar(value="gate_1")
        self.quad_region_var = tk.StringVar(value="top right")
        self.threshold_region_var = tk.StringVar(value="above")
        self.mode_var = tk.StringVar(value="idle")
        self.status_var = tk.StringVar(value="Choose a folder and click Load Folder.")
        self.gate_status_var = tk.StringVar(value="")
        self.version_var = tk.StringVar(value=f"Version {__version__}")
        self.heatmap_mode_var = tk.StringVar(value="percent")
        self.heatmap_metric_var = tk.StringVar(value="")
        self.heatmap_population_var = tk.StringVar(value="__all__")
        self.heatmap_channel_var = tk.StringVar(value="")
        self.heatmap_channel_y_var = tk.StringVar(value="")

        self.file_map = {}
        self.sample_cache = {}
        self.channel_names = []
        self.gates = []
        self.plate_metadata = {}
        self.dose_curve_definitions = {}
        self.saved_gate_labels = {}
        self.population_labels = {"All Events": "__all__"}
        self.heatmap_population_labels = {"All Events": "__all__"}
        self.pending_gate = None
        self.selector = None
        self.canvas_click_cid = None
        self.drag_cid = None
        self.drag_move_cid = None
        self.drag_release_cid = None
        self.drag_state = None
        self.current_data = pd.DataFrame()
        self.current_transformed = pd.DataFrame()
        self.color_cycle = ["#1f77b4", "#d62728", "#2ca02c", "#ff7f0e", "#9467bd", "#8c564b"]
        self.gate_group_counter = 0
        self.last_session_path = self._last_session_path()

        self.figure = Figure(figsize=(8, 7), dpi=100)
        self.ax = self.figure.add_subplot(111)
        self.heatmap_figure = Figure(figsize=(8, 3.8), dpi=100)
        self.heatmap_ax = self.heatmap_figure.add_subplot(111)

        self._build_ui()
        self._bind_events()
        self._update_gate_mode_visibility()
        self._autoload_last_session_or_folder(base_dir)

    def _build_ui(self):
        self.root.columnconfigure(1, weight=1)
        self.root.rowconfigure(0, weight=1)

        left_outer = ttk.Frame(self.root, padding=10)
        left_outer.grid(row=0, column=0, sticky="nsw")
        left_outer.rowconfigure(0, weight=1)
        left_outer.columnconfigure(0, weight=1)

        left_canvas = tk.Canvas(left_outer, width=520, highlightthickness=0)
        left_scroll = ttk.Scrollbar(left_outer, orient="vertical", command=left_canvas.yview)
        left_canvas.configure(yscrollcommand=left_scroll.set)
        left_canvas.grid(row=0, column=0, sticky="nsw")
        left_scroll.grid(row=0, column=1, sticky="ns")

        left = ttk.Frame(left_canvas, padding=0)
        left_window = left_canvas.create_window((0, 0), window=left, anchor="nw")
        for col in range(3):
            left.columnconfigure(col, weight=1)

        def _sync_left_scroll(_event=None):
            left_canvas.configure(scrollregion=left_canvas.bbox("all"))
            left_canvas.itemconfigure(left_window, width=left_canvas.winfo_width())

        left.bind("<Configure>", _sync_left_scroll)
        left_canvas.bind("<Configure>", _sync_left_scroll)

        def _on_mousewheel(event):
            left_canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")

        left_canvas.bind_all("<MouseWheel>", _on_mousewheel)

        right = ttk.Frame(self.root, padding=10)
        right.grid(row=0, column=1, sticky="nsew")
        right.columnconfigure(0, weight=1)
        right.rowconfigure(1, weight=1)
        right.rowconfigure(3, weight=0)

        ttk.Label(left, text="Folder").grid(row=0, column=0, sticky="w")
        ttk.Entry(left, textvariable=self.folder_var, width=52).grid(row=1, column=0, columnspan=3, sticky="ew", pady=(0, 6))
        ttk.Button(left, text="Browse", command=self.browse_folder).grid(row=2, column=0, sticky="ew")
        ttk.Combobox(left, textvariable=self.instrument_var, values=["Cytoflex", "Symphony"], state="readonly", width=14).grid(row=2, column=1, sticky="ew", padx=4)
        ttk.Button(left, text="Load Folder", command=self.load_folder).grid(row=2, column=2, sticky="ew")

        ttk.Label(left, text="Wells").grid(row=3, column=0, sticky="w", pady=(10, 0))
        self.well_listbox = tk.Listbox(left, selectmode=tk.EXTENDED, width=48, height=18, exportselection=False)
        self.well_listbox.grid(row=4, column=0, columnspan=3, sticky="nsew")

        ttk.Label(left, text="Population").grid(row=5, column=0, sticky="w", pady=(10, 0))
        self.population_combo = ttk.Combobox(left, textvariable=self.population_var, state="readonly", width=22)
        self.population_combo.grid(row=6, column=0, sticky="ew")

        ttk.Label(left, text="Max Points").grid(row=5, column=1, sticky="w", pady=(10, 0))
        ttk.Spinbox(left, from_=1000, to=50000, increment=1000, textvariable=self.max_points_var, width=10).grid(row=6, column=1, sticky="ew", padx=4)
        self.plot_button = ttk.Button(left, text="Plot Population", command=self.plot_population)
        self.plot_button.grid(row=6, column=2, sticky="ew")

        ttk.Label(left, text="X Axis").grid(row=7, column=0, sticky="w", pady=(10, 0))
        self.x_combo = ttk.Combobox(left, textvariable=self.x_var, state="readonly", width=20)
        self.x_combo.grid(row=8, column=0, sticky="ew")

        ttk.Label(left, text="Y Axis").grid(row=7, column=1, sticky="w", pady=(10, 0))
        self.y_combo = ttk.Combobox(left, textvariable=self.y_var, state="readonly", width=20)
        self.y_combo.grid(row=8, column=1, sticky="ew", padx=4)
        ttk.Label(left, text="Plot Mode").grid(row=7, column=2, sticky="w", pady=(10, 0))
        ttk.Combobox(left, textvariable=self.y_plot_mode_var, values=["scatter", "count histogram"], state="readonly", width=16).grid(row=8, column=2, sticky="ew")

        ttk.Label(left, text="Transform").grid(row=9, column=0, sticky="w", pady=(10, 0))
        ttk.Combobox(left, textvariable=self.transform_var, values=["linear", "log10", "arcsinh"], state="readonly", width=15).grid(row=10, column=0, sticky="ew")

        ttk.Label(left, text="Cofactor").grid(row=9, column=1, sticky="w", pady=(10, 0))
        ttk.Spinbox(left, from_=1.0, to=10000.0, increment=10.0, textvariable=self.cofactor_var, width=12).grid(row=10, column=1, sticky="ew", padx=4)

        ttk.Label(left, text="Gate Type").grid(row=11, column=0, sticky="w", pady=(10, 0))
        ttk.Combobox(left, textvariable=self.gate_type_var, values=["polygon", "quad", "vertical", "horizontal"], state="readonly", width=15).grid(row=12, column=0, sticky="ew")

        ttk.Label(left, text="Gate Name").grid(row=11, column=1, sticky="w", pady=(10, 0))
        ttk.Entry(left, textvariable=self.gate_name_var, width=18).grid(row=12, column=1, sticky="ew", padx=4)

        self.quad_region_combo = ttk.Combobox(left, textvariable=self.quad_region_var, values=["top right", "top left", "bottom right", "bottom left"], state="readonly", width=15)
        self.quad_region_combo.grid(row=13, column=0, sticky="ew", pady=(6, 0))

        self.threshold_region_combo = ttk.Combobox(left, textvariable=self.threshold_region_var, values=["above", "below"], state="readonly", width=15)
        self.threshold_region_combo.grid(row=13, column=1, sticky="ew", padx=4, pady=(6, 0))

        self.start_draw_button = ttk.Button(left, text="Start Drawing", command=self.start_drawing)
        self.start_draw_button.grid(row=14, column=0, sticky="ew", pady=(8, 0))
        ttk.Button(left, text="Clear Pending", command=self.clear_pending).grid(row=14, column=1, sticky="ew", padx=4, pady=(8, 0))
        ttk.Button(left, text="Save Gate", command=self.save_gate).grid(row=14, column=2, sticky="ew", pady=(8, 0))

        ttk.Label(left, text="Saved Gates").grid(row=15, column=0, sticky="w", pady=(10, 0))
        self.saved_gate_listbox = tk.Listbox(left, selectmode=tk.SINGLE, width=48, height=10, exportselection=False)
        self.saved_gate_listbox.grid(row=16, column=0, columnspan=3, sticky="ew")
        ttk.Label(left, text="Gate Percentages By Well").grid(row=17, column=0, sticky="w", pady=(8, 0))
        self.gate_summary_text = tk.Text(left, width=52, height=5, wrap="word")
        self.gate_summary_text.grid(row=18, column=0, columnspan=3, sticky="ew")
        self.gate_summary_text.configure(state="disabled")

        ttk.Button(left, text="Delete Gate", command=self.delete_gate).grid(row=19, column=0, sticky="ew", pady=(8, 0))
        ttk.Button(left, text="Save Session", command=self.save_session).grid(row=19, column=1, sticky="ew", padx=4, pady=(8, 0))
        ttk.Button(left, text="Load Session", command=self.load_session).grid(row=19, column=2, sticky="ew", pady=(8, 0))

        ttk.Button(left, text="Plate Map", command=self.open_plate_map_editor).grid(row=20, column=0, sticky="ew", pady=(8, 0))
        ttk.Button(left, text="Excluded Wells", command=self.open_exclusion_editor).grid(row=20, column=1, sticky="ew", padx=4, pady=(8, 0))
        ttk.Button(left, text="Export Summary CSV", command=self.export_gate_summary_csv).grid(row=20, column=2, sticky="ew", pady=(8, 0))
        ttk.Button(left, text="Export Intensities CSV", command=self.export_intensity_csv).grid(row=21, column=0, sticky="ew", pady=(8, 0))
        ttk.Button(left, text="Analysis Preview", command=self.open_analysis_preview).grid(row=21, column=1, sticky="ew", padx=4, pady=(8, 0))
        ttk.Button(left, text="Open Analysis Notebook", command=self.create_and_open_analysis_notebook).grid(row=21, column=2, sticky="ew", pady=(8, 0))
        ttk.Button(left, text="Check for Updates", command=self.check_for_updates).grid(row=22, column=0, sticky="ew", pady=(8, 0))
        ttk.Label(left, textvariable=self.version_var).grid(row=22, column=1, columnspan=2, sticky="w", padx=4, pady=(8, 0))

        ttk.Label(left, textvariable=self.mode_var, wraplength=480).grid(row=23, column=0, columnspan=3, sticky="w", pady=(10, 0))
        ttk.Label(left, textvariable=self.status_var, wraplength=480).grid(row=24, column=0, columnspan=3, sticky="w", pady=(6, 0))
        ttk.Label(left, textvariable=self.gate_status_var, wraplength=480).grid(row=25, column=0, columnspan=3, sticky="w", pady=(6, 0))

        ttk.Label(right, text="Interactive Plot").grid(row=0, column=0, sticky="w")
        canvas_frame = ttk.Frame(right)
        canvas_frame.grid(row=1, column=0, sticky="nsew")
        canvas_frame.columnconfigure(0, weight=1)
        canvas_frame.rowconfigure(0, weight=1)

        self.canvas = FigureCanvasTkAgg(self.figure, master=canvas_frame)
        self.canvas.get_tk_widget().grid(row=0, column=0, sticky="nsew")
        toolbar = NavigationToolbar2Tk(self.canvas, canvas_frame, pack_toolbar=False)
        toolbar.update()
        toolbar.grid(row=1, column=0, sticky="ew")

        heatmap_controls = ttk.Frame(right)
        heatmap_controls.grid(row=2, column=0, sticky="ew", pady=(10, 4))
        ttk.Label(heatmap_controls, text="Well Heatmap").grid(row=0, column=0, sticky="w")
        ttk.Combobox(heatmap_controls, textvariable=self.heatmap_mode_var, values=["percent", "mfi", "correlation"], state="readonly", width=12).grid(row=0, column=1, sticky="w", padx=8)
        self.heatmap_mode_var.trace_add("write", lambda *_: (self._update_heatmap_control_visibility(), self.update_heatmap()))
        self.heatmap_combo = ttk.Combobox(heatmap_controls, textvariable=self.heatmap_metric_var, state="readonly", width=28)
        self.heatmap_combo.grid(row=0, column=2, sticky="w", padx=8)
        self.heatmap_combo.bind("<<ComboboxSelected>>", lambda _e: self.update_heatmap())
        self.heatmap_population_label = ttk.Label(heatmap_controls, text="Population")
        self.heatmap_population_label.grid(row=0, column=3, sticky="w", padx=(8, 0))
        self.heatmap_population_combo = ttk.Combobox(heatmap_controls, textvariable=self.heatmap_population_var, state="readonly", width=24)
        self.heatmap_population_combo.grid(row=0, column=4, sticky="w", padx=8)
        self.heatmap_population_combo.bind("<<ComboboxSelected>>", lambda _e: self.update_heatmap())
        self.heatmap_channel_label = ttk.Label(heatmap_controls, text="Channel")
        self.heatmap_channel_label.grid(row=0, column=5, sticky="w", padx=(8, 0))
        self.heatmap_channel_combo = ttk.Combobox(heatmap_controls, textvariable=self.heatmap_channel_var, state="readonly", width=20)
        self.heatmap_channel_combo.grid(row=0, column=6, sticky="w", padx=8)
        self.heatmap_channel_combo.bind("<<ComboboxSelected>>", lambda _e: self.update_heatmap())
        self.heatmap_channel_y_label = ttk.Label(heatmap_controls, text="Channel Y")
        self.heatmap_channel_y_label.grid(row=0, column=7, sticky="w", padx=(8, 0))
        self.heatmap_channel_y_combo = ttk.Combobox(heatmap_controls, textvariable=self.heatmap_channel_y_var, state="readonly", width=20)
        self.heatmap_channel_y_combo.grid(row=0, column=8, sticky="w", padx=8)
        self.heatmap_channel_y_combo.bind("<<ComboboxSelected>>", lambda _e: self.update_heatmap())
        self._update_heatmap_control_visibility()

        heatmap_frame = ttk.Frame(right)
        heatmap_frame.grid(row=3, column=0, sticky="ew")
        heatmap_frame.columnconfigure(0, weight=1)
        self.heatmap_canvas = FigureCanvasTkAgg(self.heatmap_figure, master=heatmap_frame)
        self.heatmap_canvas.get_tk_widget().grid(row=0, column=0, sticky="ew")

    def _bind_events(self):
        self.gate_type_var.trace_add("write", lambda *_: self._update_gate_mode_visibility())
        self.transform_var.trace_add("write", lambda *_: self._auto_plot_if_ready())
        self.cofactor_var.trace_add("write", lambda *_: self._auto_plot_if_ready())
        self.y_plot_mode_var.trace_add("write", lambda *_: self._on_plot_mode_changed())
        self.max_points_var.trace_add("write", lambda *_: self.redraw() if not self.current_transformed.empty else None)
        self.population_combo.bind("<<ComboboxSelected>>", lambda _e: self.plot_population())
        self.saved_gate_listbox.bind("<<ListboxSelect>>", self._on_saved_gate_selected)
        self.well_listbox.bind("<<ListboxSelect>>", lambda _e: self._auto_plot_if_ready())
        self.x_combo.bind("<<ComboboxSelected>>", lambda _e: self._auto_plot_if_ready())
        self.y_combo.bind("<<ComboboxSelected>>", self._on_y_axis_changed)
        self.canvas.mpl_connect("button_press_event", self._on_drag_press)
        self.canvas.mpl_connect("motion_notify_event", self._on_drag_motion)
        self.canvas.mpl_connect("button_release_event", self._on_drag_release)
        self.root.bind("<Return>", lambda _e: self.plot_population())

    def _auto_plot_if_ready(self):
        if self.file_map and self.x_var.get() and self.y_var.get():
            self.plot_population()

    def _population_display_parts(self, name):
        if name == "__all__":
            return ["All Events"]
        lineage = self._population_lineage(name)
        if not lineage:
            return [name]
        return [gate["name"] for gate in lineage]

    def _population_display_label(self, name):
        return " > ".join(self._population_display_parts(name))

    def _selected_population_name(self):
        return self.population_labels.get(self.population_var.get(), self.population_var.get())

    def _selected_heatmap_population_name(self):
        return self.heatmap_population_labels.get(self.heatmap_population_var.get(), self.heatmap_population_var.get())

    def _on_plot_mode_changed(self):
        if self.y_plot_mode_var.get() == "count histogram":
            self.y_var.set("Count")
        elif _is_count_axis(self.y_var.get()):
            if "SSC-A" in self.channel_names:
                self.y_var.set("SSC-A")
            elif len(self.channel_names) > 1:
                self.y_var.set(self.channel_names[1])
            elif self.channel_names:
                self.y_var.set(self.channel_names[0])
        self._auto_plot_if_ready()

    def _update_heatmap_control_visibility(self):
        mode = self.heatmap_mode_var.get()
        self.heatmap_combo.configure(state="readonly" if mode == "percent" else "disabled")
        if mode in {"mfi", "correlation"}:
            self.heatmap_population_label.grid()
            self.heatmap_population_combo.grid()
            self.heatmap_channel_label.grid()
            self.heatmap_channel_combo.grid()
        else:
            self.heatmap_population_label.grid_remove()
            self.heatmap_population_combo.grid_remove()
            self.heatmap_channel_label.grid_remove()
            self.heatmap_channel_combo.grid_remove()
        if mode == "correlation":
            self.heatmap_channel_label.configure(text="Channel X")
            self.heatmap_channel_y_label.grid()
            self.heatmap_channel_y_combo.grid()
        else:
            self.heatmap_channel_label.configure(text="Channel")
            self.heatmap_channel_y_label.grid_remove()
            self.heatmap_channel_y_combo.grid_remove()

    def _on_y_axis_changed(self, _event=None):
        if _is_count_axis(self.y_var.get()):
            self.y_plot_mode_var.set("count histogram")
        elif self.y_plot_mode_var.get() == "count histogram":
            self.y_plot_mode_var.set("scatter")
        else:
            self._auto_plot_if_ready()

    def _update_gate_mode_visibility(self):
        gate_type = self.gate_type_var.get()
        if gate_type == "quad":
            self.quad_region_combo.grid()
            self.threshold_region_combo.grid_remove()
        elif gate_type in {"vertical", "horizontal"}:
            self.quad_region_combo.grid_remove()
            self.threshold_region_combo.grid()
        else:
            self.quad_region_combo.grid_remove()
            self.threshold_region_combo.grid_remove()

    def browse_folder(self):
        folder = filedialog.askdirectory(initialdir=_preferred_data_dir(self.folder_var.get() or self.base_dir))
        if folder:
            self.folder_var.set(folder)

    def _app_home(self):
        if getattr(sys, "frozen", False):
            base = os.path.join(os.path.expanduser("~"), "Library", "Application Support", "FlowGateApp")
            os.makedirs(base, exist_ok=True)
            return base
        return os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))

    def _download_dir(self):
        download_dir = os.path.join(os.path.expanduser("~"), "Downloads", DOWNLOADS_SUBDIR)
        os.makedirs(download_dir, exist_ok=True)
        return download_dir

    def _latest_release_info(self):
        request = urllib.request.Request(
            GITHUB_LATEST_RELEASE_API,
            headers={
                "Accept": "application/vnd.github+json",
                "User-Agent": "FlowGateApp",
            },
        )
        with urllib.request.urlopen(request, timeout=10) as response:
            payload = json.loads(response.read().decode("utf-8"))
        return {
            "tag_name": payload.get("tag_name", ""),
            "html_url": payload.get("html_url", GITHUB_RELEASES_URL),
            "name": payload.get("name", ""),
            "assets": payload.get("assets", []),
        }

    def _select_release_asset(self, release_info):
        assets = release_info.get("assets", [])
        if not assets:
            return None

        names = {asset.get("name", ""): asset for asset in assets}
        if getattr(sys, "frozen", False):
            for suffix in ("FlowGateApp-macos.zip", ".app.zip", ".zip"):
                for name, asset in names.items():
                    if name.endswith(suffix):
                        return asset

        for name, asset in names.items():
            if name.endswith(".whl"):
                return asset
        for name, asset in names.items():
            if name.endswith((".tar.gz", ".zip")):
                return asset
        return assets[0]

    def _download_release_asset(self, asset):
        asset_name = asset.get("name", "release_asset")
        asset_url = asset.get("browser_download_url")
        if not asset_url:
            raise ValueError("Selected release asset does not have a download URL.")
        destination = os.path.join(self._download_dir(), asset_name)
        request = urllib.request.Request(
            asset_url,
            headers={"User-Agent": "FlowGateApp"},
        )
        with urllib.request.urlopen(request, timeout=60) as response, open(destination, "wb") as fh:
            fh.write(response.read())
        return destination

    def _current_app_bundle_path(self):
        if not getattr(sys, "frozen", False):
            return None
        executable = os.path.abspath(sys.executable)
        marker = ".app/Contents/MacOS/"
        if marker in executable:
            return executable.split(marker, 1)[0] + ".app"
        current = executable
        while current and current != os.path.dirname(current):
            if current.endswith(".app"):
                return current
            current = os.path.dirname(current)
        return None

    def _extract_app_bundle_from_zip(self, zip_path):
        extract_root = os.path.join(self._download_dir(), os.path.splitext(os.path.basename(zip_path))[0])
        if os.path.isdir(extract_root):
            shutil.rmtree(extract_root)
        os.makedirs(extract_root, exist_ok=True)
        with zipfile.ZipFile(zip_path, "r") as zf:
            zf.extractall(extract_root)
        for root, dirs, _files in os.walk(extract_root):
            for directory in dirs:
                if directory.endswith(".app"):
                    return os.path.join(root, directory)
        raise FileNotFoundError("No .app bundle found in the downloaded zip.")

    def _write_update_helper_script(self, source_app, target_app):
        helper_path = os.path.join(self._app_home(), "install_downloaded_update.sh")
        pid = os.getpid()
        source_q = shlex.quote(source_app)
        target_q = shlex.quote(target_app)
        parent_q = shlex.quote(os.path.dirname(target_app))
        script = f"""#!/usr/bin/env bash
set -euo pipefail

APP_PID={pid}
SOURCE_APP={source_q}
TARGET_APP={target_q}
TARGET_PARENT={parent_q}

while kill -0 "$APP_PID" >/dev/null 2>&1; do
  sleep 1
done

mkdir -p "$TARGET_PARENT"
if rm -rf "$TARGET_APP" 2>/dev/null && cp -R "$SOURCE_APP" "$TARGET_APP" 2>/dev/null; then
  open "$TARGET_APP"
  exit 0
fi

osascript -e 'do shell script '\"'\"'rm -rf '\"'\"'"$TARGET_APP"'\"'\"' && cp -R '\"'\"'"$SOURCE_APP"'\"'\"' '\"'\"'"$TARGET_APP"'\"'\"'' with administrator privileges'
open "$TARGET_APP"
"""
        with open(helper_path, "w") as fh:
            fh.write(script)
        os.chmod(helper_path, 0o755)
        return helper_path

    def _assist_install_downloaded_asset(self, asset, destination, latest_tag):
        asset_name = asset.get("name", "")
        if getattr(sys, "frozen", False) and asset_name.endswith(".zip"):
            try:
                extracted_app = self._extract_app_bundle_from_zip(destination)
                current_app = self._current_app_bundle_path()
                default_target_dir = os.path.dirname(current_app) if current_app else "/Applications"
                target_dir = filedialog.askdirectory(
                    title="Choose installation folder for updated app",
                    initialdir=default_target_dir,
                )
                if not target_dir:
                    self.status_var.set(f"Update downloaded to {destination}")
                    return
                target_app = os.path.join(target_dir, os.path.basename(extracted_app))
                helper_path = self._write_update_helper_script(extracted_app, target_app)
                proceed = messagebox.askyesno(
                    "Install Downloaded Update",
                    f"Ready to install {latest_tag}.\n\n"
                    f"Downloaded app:\n{extracted_app}\n\n"
                    f"Target location:\n{target_app}\n\n"
                    f"The app will close, replace the bundle, and relaunch the new version.\n\n"
                    f"Continue?",
                )
                if proceed:
                    subprocess.Popen(["/bin/bash", helper_path], start_new_session=True)
                    self.status_var.set(f"Installing update {latest_tag} into {target_app}")
                    self.root.after(300, self.root.destroy)
                else:
                    self.status_var.set(f"Update downloaded to {destination}")
            except Exception as exc:
                self.status_var.set(f"Downloaded update but install handoff failed: {type(exc).__name__}: {exc}")
                messagebox.showinfo(
                    "Update Downloaded",
                    f"Downloaded:\n{destination}\n\n"
                    f"The app could not complete install handoff automatically.\n"
                    f"You can install it manually from the downloaded file.",
                )
            return

        install_msg = (
            f"Downloaded:\n{destination}\n\n"
            f"Install this update manually.\n"
        )
        if asset_name.endswith(".whl"):
            install_msg += (
                "Recommended command:\n\n"
                f"python -m pip install --upgrade {destination}"
            )
        else:
            install_msg += "Open the containing folder now?"
        open_folder = messagebox.askyesno("Update Downloaded", install_msg)
        if open_folder:
            webbrowser.open(f"file://{os.path.dirname(destination)}")

    def check_for_updates(self):
        try:
            self.status_var.set("Checking GitHub for updates...")
            latest = self._latest_release_info()
            latest_tag = latest["tag_name"] or ""
            current_tag = f"v{_normalize_version_tag(__version__)}"
            self.version_var.set(f"Version {__version__} | Latest {latest_tag or 'unknown'}")
            if latest_tag and _version_key(latest_tag) > _version_key(current_tag):
                action = messagebox.askyesnocancel(
                    "Update Available",
                    f"A newer version is available.\n\n"
                    f"Current: {current_tag}\n"
                    f"Latest: {latest_tag}\n\n"
                    f"Yes: download the recommended update asset\n"
                    f"No: open the GitHub release page\n"
                    f"Cancel: do nothing",
                )
                self.status_var.set(f"Update available: {latest_tag}")
                if action is True:
                    asset = self._select_release_asset(latest)
                    if asset is None:
                        messagebox.showinfo(
                            "No Downloadable Asset",
                            "No downloadable release asset was found. Opening the release page instead.",
                        )
                        webbrowser.open(latest.get("html_url", GITHUB_RELEASES_URL))
                        return
                    self.status_var.set(f"Downloading update asset: {asset.get('name', '')}")
                    destination = self._download_release_asset(asset)
                    self.status_var.set(f"Downloaded update to {destination}")
                    self._assist_install_downloaded_asset(asset, destination, latest_tag)
                elif action is False:
                    webbrowser.open(latest.get("html_url", GITHUB_RELEASES_URL))
            else:
                messagebox.showinfo(
                    "Up To Date",
                    f"You are already on the latest available version.\n\n"
                    f"Current: {current_tag}\n"
                    f"Latest: {latest_tag or current_tag}",
                )
                self.status_var.set(f"Up to date: {current_tag}")
        except Exception as exc:
            self.status_var.set(f"Update check failed: {type(exc).__name__}: {exc}")

    def _session_dir(self):
        session_dir = os.path.join(self._app_home(), "sessions")
        os.makedirs(session_dir, exist_ok=True)
        return session_dir

    def _last_session_path(self):
        return os.path.join(self._session_dir(), "last_flow_session.json")

    def _autoload_last_session_or_folder(self, base_dir):
        if os.path.isfile(self.last_session_path):
            try:
                with open(self.last_session_path) as fh:
                    payload = json.load(fh)
                self._apply_session_payload(payload)
                self.gate_status_var.set(f"Loaded last session from {self.last_session_path}")
                return
            except Exception as exc:
                self.status_var.set(f"Could not auto-load last session: {type(exc).__name__}: {exc}")
        if base_dir:
            self.load_folder()

    def _apply_session_payload(self, payload):
        folder = payload.get("folder", "")
        instrument = payload.get("instrument", self.instrument_var.get())
        if folder:
            self.folder_var.set(folder)
        self.instrument_var.set(instrument)
        self.load_folder()
        self.gates = payload.get("gates", [])
        self.plate_metadata = payload.get("plate_metadata", {})
        self.dose_curve_definitions = payload.get("dose_curve_definitions", {})
        self._refresh_gate_lists()
        self._update_gate_summary_panel()
        self._refresh_heatmap_options()
        self.redraw()
        self.update_heatmap()

    def load_folder(self):
        folder = self.folder_var.get().strip()
        if not os.path.isdir(folder):
            self.status_var.set(f"Folder not found: {folder}")
            return

        try:
            self.file_map = {}
            self.sample_cache = {}
            self.gates = []
            self.plate_metadata = {}
            self.dose_curve_definitions = {}
            self.saved_gate_labels = {}
            self.pending_gate = None
            files = _list_fcs_files(folder, self.instrument_var.get())
            for relpath in files:
                well = _get_well_name(relpath, self.instrument_var.get())
                label = f"{well} | {relpath}"
                self.file_map[label] = relpath

            self.well_listbox.delete(0, tk.END)
            for label in self.file_map:
                self.well_listbox.insert(tk.END, label)

            if self.file_map:
                self.well_listbox.selection_set(0)
                self._prime_channels()
                self.status_var.set(f"Loaded {len(self.file_map)} wells. Click Plot Population to load events.")
            else:
                self.channel_names = []
                self.x_combo["values"] = []
                self.y_combo["values"] = []
                self.status_var.set("No FCS files found in the selected folder.")

            self._refresh_gate_lists()
            self._update_gate_summary_panel()
            self._refresh_heatmap_options()
            self.clear_axes()
        except Exception as exc:
            self.status_var.set(f"Load Folder failed: {type(exc).__name__}: {exc}")

    def _prime_channels(self):
        first_label = next(iter(self.file_map))
        sample = self._load_sample(self.file_map[first_label])
        self.channel_names = _get_channel_names(sample)
        self.x_combo["values"] = self.channel_names
        self.y_combo["values"] = list(self.channel_names) + ["Count"]
        self.x_var.set("FSC-A" if "FSC-A" in self.channel_names else self.channel_names[0])
        if _is_count_axis(self.y_var.get()):
            self.y_var.set("Count")
        elif "SSC-A" in self.channel_names:
            self.y_var.set("SSC-A")
        elif len(self.channel_names) > 1:
            self.y_var.set(self.channel_names[1])
        else:
            self.y_var.set("Count")

    def _load_sample(self, relpath):
        if relpath not in self.sample_cache:
            datafile = os.path.join(self.folder_var.get().strip(), relpath)
            well = _get_well_name(relpath, self.instrument_var.get())
            self.sample_cache[relpath] = FCMeasurement(ID=well, datafile=datafile)
        return self.sample_cache[relpath]

    def _metadata_for_well(self, well):
        return self.plate_metadata.get(well, {})

    def _annotate_sample_row(self, row, well):
        metadata = self._metadata_for_well(well)
        row["sample_name"] = metadata.get("sample_name", "")
        row["treatment_group"] = metadata.get("sample_name", "")
        row["dose_curve"] = metadata.get("dose_curve", "")
        row["dose"] = metadata.get("dose", "")
        row["replicate"] = metadata.get("replicate", "")
        row["sample_type"] = metadata.get("sample_type", "")
        row["dose_direction"] = metadata.get("dose_direction", "")
        row["excluded"] = bool(metadata.get("excluded", False))
        return row

    def _fluorescence_gates(self):
        fluorescence_tokens = ("FSC", "SSC", "Time")
        fluorescent = []
        for gate in self.gates:
            channels = [gate["x_channel"]]
            if gate.get("y_channel"):
                channels.append(gate["y_channel"])
            if any(not any(token in channel for token in fluorescence_tokens) for channel in channels):
                fluorescent.append(gate)
        return fluorescent

    def _sample_raw_dataframe(self, label):
        relpath = self.file_map[label]
        sample = self._load_sample(relpath)
        df = sample.data.copy()
        well = _get_well_name(relpath, self.instrument_var.get())
        df["__well__"] = well
        df["__source__"] = relpath
        return df

    def _selected_labels(self):
        return [self.well_listbox.get(i) for i in self.well_listbox.curselection()]

    def _included_file_items(self):
        items = []
        for label, relpath in self.file_map.items():
            well = _get_well_name(relpath, self.instrument_var.get())
            if not self._metadata_for_well(well).get("excluded", False):
                items.append((label, relpath, well))
        return items

    def _selected_raw_dataframe(self):
        labels = self._selected_labels()
        if not labels:
            return pd.DataFrame()
        frames = []
        for idx, label in enumerate(labels):
            relpath = self.file_map[label]
            sample = self._load_sample(relpath)
            df = sample.data.copy()
            df["__well__"] = _get_well_name(relpath, self.instrument_var.get())
            df["__source__"] = relpath
            df["__sample_idx__"] = idx
            frames.append(df)
        return pd.concat(frames, ignore_index=True)

    def _population_gate(self, name):
        if name == "__all__":
            return None
        for gate in self.gates:
            if gate["name"] == name:
                return gate
        return None

    def _population_lineage(self, name):
        lineage = []
        current = self._population_gate(name)
        while current is not None:
            lineage.append(current)
            current = self._population_gate(current["parent_population"])
        return list(reversed(lineage))

    def _population_raw_dataframe(self, population_name):
        df = self._selected_raw_dataframe()
        if df.empty:
            return df
        for gate in self._population_lineage(population_name):
            transformed = _apply_transform(
                df,
                gate["x_channel"],
                _gate_plot_y_channel(gate),
                gate["transform"],
                gate["cofactor"],
            )
            mask = _gate_mask(transformed, gate)
            df = df.loc[mask].copy()
        return df

    def _sample_population_raw_dataframe(self, label, population_name):
        df = self._sample_raw_dataframe(label)
        if df.empty:
            return df
        for gate in self._population_lineage(population_name):
            transformed = _apply_transform(
                df,
                gate["x_channel"],
                _gate_plot_y_channel(gate),
                gate["transform"],
                gate["cofactor"],
            )
            mask = _gate_mask(transformed, gate)
            df = df.loc[mask].copy()
        return df

    def _channel_correlation_for_label(self, label, population_name, x_channel, y_channel):
        df = self._sample_population_raw_dataframe(label, population_name)
        if df.empty or x_channel not in df.columns or y_channel not in df.columns:
            return np.nan
        corr_df = df[[x_channel, y_channel]].apply(pd.to_numeric, errors="coerce").dropna()
        if len(corr_df) < 2:
            return np.nan
        corr = corr_df[x_channel].corr(corr_df[y_channel])
        return float(corr) if pd.notna(corr) else np.nan

    def _display_dataframe(self):
        df = self._population_raw_dataframe(self._selected_population_name())
        if df.empty:
            return df, df
        if self.y_plot_mode_var.get() == "count histogram" or _is_count_axis(self.y_var.get()):
            transformed = pd.DataFrame(index=df.index.copy())
            transformed[self.x_var.get()] = _transform_array(
                df[self.x_var.get()].to_numpy(),
                self.transform_var.get(),
                self.cofactor_var.get(),
            )
            transformed["__well__"] = df["__well__"].to_numpy()
        else:
            transformed = _apply_transform(
                df,
                self.x_var.get(),
                self.y_var.get(),
                self.transform_var.get(),
                self.cofactor_var.get(),
            )
            transformed["__well__"] = df["__well__"].to_numpy()
        return df, transformed

    def _gate_fraction(self, gate_spec):
        parent_df = self._population_raw_dataframe(gate_spec["parent_population"])
        if parent_df.empty:
            return 0.0, 0, 0
        transformed = _apply_transform(
            parent_df,
            gate_spec["x_channel"],
            _gate_plot_y_channel(gate_spec),
            gate_spec["transform"],
            gate_spec["cofactor"],
        )
        mask = _gate_mask(transformed, gate_spec)
        count = int(mask.sum())
        total = len(parent_df)
        return count / max(total, 1), count, total

    def _gate_fraction_for_label(self, gate_spec, label):
        df = self._sample_raw_dataframe(label)
        parent_name = gate_spec["parent_population"]
        if parent_name != "__all__":
            for lineage_gate in self._population_lineage(parent_name):
                transformed_parent = _apply_transform(
                    df,
                    lineage_gate["x_channel"],
                    _gate_plot_y_channel(lineage_gate),
                    lineage_gate["transform"],
                    lineage_gate["cofactor"],
                )
                mask_parent = _gate_mask(transformed_parent, lineage_gate)
                df = df.loc[mask_parent].copy()
        if df.empty:
            return 0.0, 0, 0
        transformed = _apply_transform(
            df,
            gate_spec["x_channel"],
            _gate_plot_y_channel(gate_spec),
            gate_spec["transform"],
            gate_spec["cofactor"],
        )
        mask = _gate_mask(transformed, gate_spec)
        count = int(mask.sum())
        total = len(df)
        return count / max(total, 1), count, total

    def _update_gate_summary_panel(self):
        gate_name = self._selected_saved_gate_name()
        lines = []
        if gate_name:
            gate = next((g for g in self.gates if g["name"] == gate_name), None)
            if gate is not None:
                included_items = sorted(self._included_file_items(), key=lambda item: (item[2][0], int(item[2][1:])))
                for label, relpath, well in included_items:
                    frac, count, total = self._gate_fraction_for_label(gate, label)
                    lines.append(f"{well}: {100*frac:.1f}% ({count}/{total})")
        if not lines:
            lines = ["Select a saved gate to view per-well percentages."]
        self.gate_summary_text.configure(state="normal")
        self.gate_summary_text.delete("1.0", tk.END)
        self.gate_summary_text.insert("1.0", "\n".join(lines))
        self.gate_summary_text.configure(state="disabled")

    def _gate_label(self, gate):
        frac, count, total = self._gate_fraction(gate)
        hierarchy = self._population_display_label(gate["name"])
        if gate["gate_type"] == "vertical":
            axes_label = f"vertical @ {gate['x_channel']}"
        elif gate["gate_type"] == "horizontal":
            axes_label = f"horizontal @ {gate['y_channel']}"
        else:
            y_channel = gate["y_channel"] if gate.get("y_channel") else gate["x_channel"]
            axes_label = f"{gate['x_channel']} vs {y_channel}"
        return (
            f"{hierarchy} | {axes_label} | "
            f"{100*frac:.1f}% of parent ({count}/{total})"
        )

    def _downsample(self, transformed):
        if transformed.empty:
            return transformed
        max_points = self.max_points_var.get()
        if len(transformed) <= max_points:
            return transformed
        per_group = max(1, max_points // max(len(self._selected_labels()), 1))
        pieces = []
        for _, group in transformed.groupby("__well__", sort=False):
            pieces.append(group.sample(n=min(per_group, len(group)), random_state=0))
        return pd.concat(pieces, ignore_index=True)

    def clear_axes(self):
        self._disconnect_drawing()
        self.ax.clear()
        self.ax.set_title("No population plotted")
        self.canvas.draw_idle()
        self.update_heatmap()

    def _refresh_heatmap_options(self):
        metric_cols = [f"pct_{gate['name']}" for gate in self.gates]
        self.heatmap_combo["values"] = metric_cols
        if self.heatmap_metric_var.get() not in metric_cols:
            self.heatmap_metric_var.set(metric_cols[0] if metric_cols else "")
        population_labels = ["All Events"] + [self._population_display_label(gate["name"]) for gate in self.gates]
        self.heatmap_population_labels = {"All Events": "__all__"}
        for gate in self.gates:
            self.heatmap_population_labels[self._population_display_label(gate["name"])] = gate["name"]
        self.heatmap_population_combo["values"] = population_labels
        if self.heatmap_population_var.get() not in population_labels:
            self.heatmap_population_var.set("All Events")
        fluorescence_channels = [
            channel for channel in self.channel_names
            if not any(token in channel for token in ("FSC", "SSC", "Time"))
        ]
        self.heatmap_channel_combo["values"] = fluorescence_channels
        if self.heatmap_channel_var.get() not in fluorescence_channels:
            self.heatmap_channel_var.set(fluorescence_channels[0] if fluorescence_channels else "")
        self.heatmap_channel_y_combo["values"] = fluorescence_channels
        if self.heatmap_channel_y_var.get() not in fluorescence_channels:
            fallback = fluorescence_channels[1] if len(fluorescence_channels) > 1 else (fluorescence_channels[0] if fluorescence_channels else "")
            self.heatmap_channel_y_var.set(fallback)

    def update_heatmap(self):
        self.heatmap_figure.clear()
        self.heatmap_ax = self.heatmap_figure.add_subplot(111)
        if not self.file_map:
            self.heatmap_ax.set_title("No data loaded")
            self.heatmap_canvas.draw_idle()
            return
        try:
            plate = np.full((8, 12), np.nan)
            mode = self.heatmap_mode_var.get()
            if mode == "percent":
                metric = self.heatmap_metric_var.get()
                if not metric:
                    self.heatmap_ax.set_title("No % positive metric selected")
                    self.heatmap_canvas.draw_idle()
                    return
                summary = self._summary_dataframe()
                if metric not in summary.columns:
                    self.heatmap_ax.set_title("Metric not available")
                    self.heatmap_canvas.draw_idle()
                    return
                for _, row in summary.iterrows():
                    well = row["well"]
                    row_idx = ord(well[0]) - 65
                    col_idx = int(well[1:]) - 1
                    plate[row_idx, col_idx] = row[metric]
                sns.heatmap(
                    plate,
                    ax=self.heatmap_ax,
                    cmap="viridis",
                    vmin=0,
                    vmax=100,
                    annot=True,
                    fmt=".1f",
                    cbar_kws={"label": "% positive"},
                )
                self.heatmap_ax.set_title(metric.replace("pct_", "") + " well heatmap")
            elif mode == "mfi":
                population = self._selected_heatmap_population_name()
                channel = self.heatmap_channel_var.get()
                if not channel:
                    self.heatmap_ax.set_title("No fluorescence channel selected")
                    self.heatmap_canvas.draw_idle()
                    return
                for label, relpath, well in self._included_file_items():
                    df = self._sample_population_raw_dataframe(label, population)
                    value = float(np.mean(df[channel])) if (not df.empty and channel in df.columns) else np.nan
                    row_idx = ord(well[0]) - 65
                    col_idx = int(well[1:]) - 1
                    plate[row_idx, col_idx] = value
                sns.heatmap(
                    plate,
                    ax=self.heatmap_ax,
                    cmap="magma",
                    annot=True,
                    fmt=".1f",
                    cbar_kws={"label": f"MFI {channel}"},
                )
                pop_label = "all events" if population == "__all__" else self._population_display_label(population)
                self.heatmap_ax.set_title(f"MFI {channel} in {pop_label}")
            else:
                population = self._selected_heatmap_population_name()
                x_channel = self.heatmap_channel_var.get()
                y_channel = self.heatmap_channel_y_var.get()
                if not x_channel or not y_channel:
                    self.heatmap_ax.set_title("Select two fluorescence channels")
                    self.heatmap_canvas.draw_idle()
                    return
                if x_channel == y_channel:
                    self.heatmap_ax.set_title("Correlation requires two different channels")
                    self.heatmap_canvas.draw_idle()
                    return
                for label, relpath, well in self._included_file_items():
                    value = self._channel_correlation_for_label(label, population, x_channel, y_channel)
                    row_idx = ord(well[0]) - 65
                    col_idx = int(well[1:]) - 1
                    plate[row_idx, col_idx] = value
                sns.heatmap(
                    plate,
                    ax=self.heatmap_ax,
                    cmap="coolwarm",
                    vmin=-1,
                    vmax=1,
                    center=0,
                    annot=True,
                    fmt=".2f",
                    cbar_kws={"label": "Pearson r"},
                )
                pop_label = "all events" if population == "__all__" else self._population_display_label(population)
                self.heatmap_ax.set_title(f"Correlation: {x_channel} vs {y_channel} in {pop_label}")
            self.heatmap_ax.set_xlabel("Column")
            self.heatmap_ax.set_ylabel("Row")
            self.heatmap_ax.set_xticklabels([str(i) for i in range(1, 13)], rotation=0)
            self.heatmap_ax.set_yticklabels(list("ABCDEFGH"), rotation=0)
            self.heatmap_figure.tight_layout()
            self.heatmap_canvas.draw_idle()
        except Exception as exc:
            self.heatmap_ax.set_title(f"Heatmap failed: {type(exc).__name__}")
            self.heatmap_canvas.draw_idle()

    def redraw(self):
        self.ax.clear()
        raw_df = self.current_data
        transformed = self.current_transformed
        plotted = self._downsample(transformed)

        if plotted.empty:
            self.ax.set_title("No events in selected population")
            self.canvas.draw_idle()
            return

        labels = self._selected_labels()
        histogram_mode = self.y_plot_mode_var.get() == "count histogram" or _is_count_axis(self.y_var.get())
        if histogram_mode:
            if len(labels) <= 1:
                self.ax.hist(plotted[self.x_var.get()], bins=100, histtype="step", linewidth=1.8, color=self.color_cycle[0])
            else:
                for idx, (well, group) in enumerate(plotted.groupby("__well__", sort=False)):
                    self.ax.hist(
                        group[self.x_var.get()],
                        bins=100,
                        histtype="step",
                        linewidth=1.6,
                        label=well,
                        color=self.color_cycle[idx % len(self.color_cycle)],
                    )
                self.ax.legend(fontsize=8)
        elif len(labels) <= 1:
            self.ax.scatter(plotted[self.x_var.get()], plotted[self.y_var.get()], s=3, alpha=0.25, color=self.color_cycle[0], rasterized=True)
        else:
            for idx, (well, group) in enumerate(plotted.groupby("__well__", sort=False)):
                self.ax.scatter(group[self.x_var.get()], group[self.y_var.get()], s=3, alpha=0.25, label=well, color=self.color_cycle[idx % len(self.color_cycle)], rasterized=True)
            self.ax.legend(markerscale=3, fontsize=8)

        selected_gate = self._selected_saved_gate_name()
        for gate in self.gates:
            current_population = self._selected_population_name()
            if current_population in {gate["parent_population"], gate["name"]}:
                y_matches = gate.get("y_channel") in {None, self.y_var.get()}
                if histogram_mode:
                    y_matches = gate["gate_type"] == "vertical"
                if gate["x_channel"] == self.x_var.get() and y_matches:
                    if gate["transform"] == self.transform_var.get() and np.isclose(gate["cofactor"], self.cofactor_var.get()):
                        _render_gate(self.ax, gate, selected=(gate["name"] == selected_gate))

        if self.pending_gate is not None:
            spec = self._pending_to_gate_spec(preview=True)
            if spec is not None:
                _render_gate(self.ax, spec, selected=True)

        population_name = self._selected_population_name()
        title_name = self._population_display_label(population_name)
        self.ax.set_xlabel(f"{self.x_var.get()} ({self.transform_var.get()})")
        self.ax.set_ylabel("Count" if histogram_mode else f"{self.y_var.get()} ({self.transform_var.get()})")
        self.ax.set_title(f"{title_name} | {len(raw_df)} events")
        self.figure.tight_layout()
        self.canvas.draw_idle()

    def plot_population(self):
        try:
            self.status_var.set("Loading events and plotting population...")
            self._disconnect_drawing()
            raw_df, transformed = self._display_dataframe()
            self.current_data = raw_df
            self.current_transformed = transformed
            self.redraw()
            self.status_var.set("Population plotted.")
        except Exception as exc:
            self.status_var.set(f"Plot Population failed: {type(exc).__name__}: {exc}")

    def _pending_to_gate_spec(self, preview=False):
        if self.pending_gate is None:
            return None
        name = self.gate_name_var.get().strip() or f"gate_{len(self.gates) + 1}"
        spec = {
            "name": "__pending__" if preview else name,
            "parent_population": self._selected_population_name(),
            "gate_type": self.pending_gate.gate_type,
            "x_channel": self.x_var.get(),
            "y_channel": None if self.pending_gate.gate_type == "vertical" else self.y_var.get(),
            "transform": self.transform_var.get(),
            "cofactor": float(self.cofactor_var.get()),
            "color": self.color_cycle[len(self.gates) % len(self.color_cycle)],
            "gate_group": None,
        }
        spec.update(self.pending_gate.payload)
        return spec

    def start_drawing(self):
        if self.current_transformed.empty:
            self.gate_status_var.set("Plot a population before drawing.")
            return
        if self.y_plot_mode_var.get() == "count histogram" and self.gate_type_var.get() != "vertical":
            self.gate_status_var.set("Histogram mode only supports vertical gates.")
            return

        self._disconnect_drawing()
        self.drag_state = None
        gate_type = self.gate_type_var.get()
        if gate_type == "polygon":
            self.selector = PolygonSelector(self.ax, self._on_polygon_complete, useblit=False)
            self.mode_var.set("MODE: drawing polygon gate")
            self.canvas.get_tk_widget().configure(cursor="crosshair")
            self.start_draw_button.configure(text="Drawing...")
            self.gate_status_var.set("Polygon mode active. Click vertices and double-click to finish.")
        elif gate_type == "quad":
            self.canvas_click_cid = self.canvas.mpl_connect("button_press_event", self._on_quad_click)
            self.mode_var.set("MODE: drawing quad gate")
            self.canvas.get_tk_widget().configure(cursor="crosshair")
            self.start_draw_button.configure(text="Drawing...")
            self.gate_status_var.set("Quad mode active. Click once to set the quadrant intersection.")
        elif gate_type == "vertical":
            self.canvas_click_cid = self.canvas.mpl_connect("button_press_event", self._on_vertical_click)
            self.mode_var.set("MODE: drawing vertical gate")
            self.canvas.get_tk_widget().configure(cursor="crosshair")
            self.start_draw_button.configure(text="Drawing...")
            self.gate_status_var.set("Vertical mode active. Click once to place the threshold.")
        elif gate_type == "horizontal":
            self.canvas_click_cid = self.canvas.mpl_connect("button_press_event", self._on_horizontal_click)
            self.mode_var.set("MODE: drawing horizontal gate")
            self.canvas.get_tk_widget().configure(cursor="crosshair")
            self.start_draw_button.configure(text="Drawing...")
            self.gate_status_var.set("Horizontal mode active. Click once to place the threshold.")

    def _on_polygon_complete(self, vertices):
        self.pending_gate = PendingGate("polygon", {"vertices": [tuple(v) for v in vertices]})
        self.gate_status_var.set("Polygon captured. Click Save Gate to keep it.")
        self._disconnect_drawing()
        self.redraw()

    def _on_quad_click(self, event):
        if event.inaxes != self.ax or event.xdata is None or event.ydata is None:
            return
        self.pending_gate = PendingGate(
            "quad",
            {
                "x_threshold": float(event.xdata),
                "y_threshold": float(event.ydata),
                "region": self.quad_region_var.get(),
            },
        )
        self.gate_status_var.set("Quad gate captured. Click Save Gate to keep it.")
        self._disconnect_drawing()
        self.redraw()

    def _on_vertical_click(self, event):
        if event.inaxes != self.ax or event.xdata is None:
            return
        self.pending_gate = PendingGate(
            "vertical",
            {"x_threshold": float(event.xdata), "region": self.threshold_region_var.get()},
        )
        self.gate_status_var.set("Vertical gate captured. Click Save Gate to keep it.")
        self._disconnect_drawing()
        self.redraw()

    def _on_horizontal_click(self, event):
        if event.inaxes != self.ax or event.ydata is None:
            return
        self.pending_gate = PendingGate(
            "horizontal",
            {"y_threshold": float(event.ydata), "region": self.threshold_region_var.get()},
        )
        self.gate_status_var.set("Horizontal gate captured. Click Save Gate to keep it.")
        self._disconnect_drawing()
        self.redraw()

    def _disconnect_drawing(self):
        if self.selector is not None:
            self.selector.disconnect_events()
            self.selector = None
        if self.canvas_click_cid is not None:
            self.canvas.mpl_disconnect(self.canvas_click_cid)
            self.canvas_click_cid = None
        self.mode_var.set("MODE: idle")
        self.canvas.get_tk_widget().configure(cursor="")
        self.start_draw_button.configure(text="Start Drawing")

    def _visible_gate_for_drag(self):
        gate_name = self._selected_saved_gate_name()
        if not gate_name:
            return None
        histogram_mode = self.y_plot_mode_var.get() == "count histogram" or _is_count_axis(self.y_var.get())
        for gate in self.gates:
            if gate["name"] != gate_name:
                continue
            if gate["parent_population"] != self._selected_population_name():
                continue
            if gate["x_channel"] != self.x_var.get():
                continue
            if histogram_mode:
                if gate["gate_type"] != "vertical":
                    continue
            elif gate.get("y_channel") not in {None, self.y_var.get()}:
                continue
            if gate["transform"] != self.transform_var.get():
                continue
            if not np.isclose(gate["cofactor"], self.cofactor_var.get()):
                continue
            return gate
        return None

    def _gate_hit_test(self, gate, event):
        if event.inaxes != self.ax or event.xdata is None or event.ydata is None:
            return None
        if gate["gate_type"] == "vertical":
            if abs(event.xdata - gate["x_threshold"]) < 0.03 * max(self.ax.get_xlim()[1] - self.ax.get_xlim()[0], 1e-9):
                return {"mode": "vertical"}
            return None
        if gate["gate_type"] == "horizontal":
            if abs(event.ydata - gate["y_threshold"]) < 0.03 * max(self.ax.get_ylim()[1] - self.ax.get_ylim()[0], 1e-9):
                return {"mode": "horizontal"}
            return None
        if gate["gate_type"] == "quad":
            x_hit = abs(event.xdata - gate["x_threshold"]) < 0.03 * max(self.ax.get_xlim()[1] - self.ax.get_xlim()[0], 1e-9)
            y_hit = abs(event.ydata - gate["y_threshold"]) < 0.03 * max(self.ax.get_ylim()[1] - self.ax.get_ylim()[0], 1e-9)
            if x_hit or y_hit:
                return {"mode": "quad"}
            return None
        if gate["gate_type"] == "polygon":
            vertices = np.asarray(gate["vertices"])
            distances = np.sqrt(((vertices - np.array([[event.xdata, event.ydata]])) ** 2).sum(axis=1))
            if distances.min() < 0.03 * max(self.ax.get_xlim()[1] - self.ax.get_xlim()[0], 1e-9):
                return {"mode": "polygon_vertex", "vertex_index": int(distances.argmin())}
            if Path(vertices).contains_point((event.xdata, event.ydata)):
                return {"mode": "polygon_translate"}
            return None
        return None

    def _on_drag_press(self, event):
        if self.selector is not None or self.canvas_click_cid is not None:
            return
        gate = self._visible_gate_for_drag()
        if gate is None:
            return
        hit = self._gate_hit_test(gate, event)
        if hit is None:
            return
        self.drag_state = {
            "gate_name": gate["name"],
            "press_x": float(event.xdata),
            "press_y": float(event.ydata),
            "original": json.loads(json.dumps(gate)),
            "originals": [json.loads(json.dumps(g)) for g in self.gates if g.get("gate_group") == gate.get("gate_group")] if gate.get("gate_group") else [json.loads(json.dumps(gate))],
            **hit,
        }
        self.mode_var.set(f"MODE: dragging gate {gate['name']}")
        self.canvas.get_tk_widget().configure(cursor="fleur")

    def _on_drag_motion(self, event):
        if self.drag_state is None or event.inaxes != self.ax or event.xdata is None or event.ydata is None:
            return
        gate = next((g for g in self.gates if g["name"] == self.drag_state["gate_name"]), None)
        if gate is None:
            return
        gate_group = gate.get("gate_group")
        if gate_group:
            targets = [g for g in self.gates if g.get("gate_group") == gate_group]
            originals = {
                g["name"]: next(
                    (orig for orig in self.drag_state["originals"] if orig["name"] == g["name"]),
                    json.loads(json.dumps(g)),
                )
                for g in targets
            }
        else:
            targets = [gate]
            originals = {gate["name"]: self.drag_state["original"]}
        dx = float(event.xdata) - self.drag_state["press_x"]
        dy = float(event.ydata) - self.drag_state["press_y"]
        for target in targets:
            original = originals[target["name"]]
            if self.drag_state["mode"] == "vertical":
                target["x_threshold"] = original["x_threshold"] + dx
            elif self.drag_state["mode"] == "horizontal":
                target["y_threshold"] = original["y_threshold"] + dy
            elif self.drag_state["mode"] == "quad":
                target["x_threshold"] = original["x_threshold"] + dx
                target["y_threshold"] = original["y_threshold"] + dy
            elif self.drag_state["mode"] == "polygon_translate":
                target["vertices"] = [(x + dx, y + dy) for x, y in original["vertices"]]
            elif self.drag_state["mode"] == "polygon_vertex":
                vertices = list(original["vertices"])
                vertices[self.drag_state["vertex_index"]] = (float(event.xdata), float(event.ydata))
                target["vertices"] = vertices
        self.redraw()

    def _on_drag_release(self, _event):
        if self.drag_state is not None:
            gate_name = self.drag_state["gate_name"]
            self.drag_state = None
            self.mode_var.set("MODE: idle")
            self.canvas.get_tk_widget().configure(cursor="")
            self._update_gate_summary_panel()
            self.gate_status_var.set(f"Moved gate '{gate_name}'.")
            self._refresh_heatmap_options()
            self.update_heatmap()

    def clear_pending(self):
        self.pending_gate = None
        self._disconnect_drawing()
        self.redraw()
        self.gate_status_var.set("Pending gate cleared.")

    def save_gate(self):
        spec = self._pending_to_gate_spec(preview=False)
        if spec is None:
            self.gate_status_var.set("Draw a gate before saving.")
            return
        specs_to_add = []
        if spec["gate_type"] in {"vertical", "horizontal"}:
            self.gate_group_counter += 1
            gate_group = f"threshold_group_{self.gate_group_counter}"
            for region in ("above", "below"):
                threshold_spec = dict(spec)
                threshold_spec["region"] = region
                threshold_spec["name"] = f"{spec['name']}_{region}"
                threshold_spec["gate_group"] = gate_group
                specs_to_add.append(threshold_spec)
        else:
            self.gate_group_counter += 1
            spec["gate_group"] = f"gate_group_{self.gate_group_counter}"
            specs_to_add = [spec]

        existing = {g["name"] for g in self.gates}
        duplicate = next((g["name"] for g in specs_to_add if g["name"] in existing), None)
        if duplicate is not None:
            self.gate_status_var.set(f"Gate name '{duplicate}' already exists.")
            return

        self.gates.extend(specs_to_add)
        self.pending_gate = None
        selected_name = specs_to_add[0]["name"]
        self._refresh_gate_lists(selected_name=selected_name)
        self.gate_name_var.set(f"gate_{len(self.gates) + 1}")
        self.redraw()
        self._update_gate_summary_panel()
        self._refresh_heatmap_options()
        self.update_heatmap()
        summaries = []
        for gate in specs_to_add:
            frac, count, total = self._gate_fraction(gate)
            summaries.append(f"{gate['name']}: {100*frac:.1f}% ({count}/{total})")
        self.gate_status_var.set("Saved " + "; ".join(summaries))

    def _selected_saved_gate_name(self):
        sel = self.saved_gate_listbox.curselection()
        if not sel:
            return None
        label = self.saved_gate_listbox.get(sel[0])
        return self.saved_gate_labels.get(label, label.split(" | ")[0])

    def _on_saved_gate_selected(self, _event=None):
        gate_name = self._selected_saved_gate_name()
        if not gate_name:
            self.redraw()
            self._update_gate_summary_panel()
            return
        gate = next((g for g in self.gates if g["name"] == gate_name), None)
        if gate is None:
            self.redraw()
            self._update_gate_summary_panel()
            return
        if gate["x_channel"] in self.channel_names:
            self.x_var.set(gate["x_channel"])
        if gate.get("y_channel") and gate["y_channel"] in self.channel_names:
            self.y_var.set(gate["y_channel"])
        self.transform_var.set(gate["transform"])
        self.cofactor_var.set(gate["cofactor"])
        parent_population_label = self._population_display_label(gate["parent_population"])
        if parent_population_label in self.population_combo["values"]:
            self.population_var.set(parent_population_label)
        else:
            self.population_var.set("All Events")
        self.plot_population()
        self._update_gate_summary_panel()

    def delete_gate(self):
        gate_name = self._selected_saved_gate_name()
        if not gate_name:
            self.gate_status_var.set("Select a saved gate to delete.")
            return
        children = [gate["name"] for gate in self.gates if gate["parent_population"] == gate_name]
        if children:
            self.gate_status_var.set(f"Delete child gates first: {', '.join(children)}")
            return
        self.gates = [g for g in self.gates if g["name"] != gate_name]
        if self._selected_population_name() == gate_name:
            self.population_var.set("All Events")
        self._refresh_gate_lists()
        self.redraw()
        self._update_gate_summary_panel()
        self._refresh_heatmap_options()
        self.update_heatmap()
        self.gate_status_var.set(f"Deleted gate '{gate_name}'.")

    def _refresh_gate_lists(self, selected_name=None):
        labels = []
        self.saved_gate_labels = {}
        self.population_labels = {"All Events": "__all__"}
        self.saved_gate_listbox.delete(0, tk.END)
        names = []
        for gate in self.gates:
            names.append(gate["name"])
            label = self._gate_label(gate)
            labels.append(label)
            self.saved_gate_labels[label] = gate["name"]
            self.saved_gate_listbox.insert(tk.END, label)
            self.population_labels[self._population_display_label(gate["name"])] = gate["name"]
        if selected_name and selected_name in names:
            idx = names.index(selected_name)
            self.saved_gate_listbox.selection_set(idx)

        population_values = ["All Events"] + [self._population_display_label(name) for name in names]
        self.population_combo["values"] = population_values
        if self.population_var.get() not in population_values:
            self.population_var.set("All Events")

    def save_session(self):
        filename = filedialog.asksaveasfilename(
            defaultextension=".json",
            filetypes=[("JSON files", "*.json")],
            initialdir=self._session_dir(),
            initialfile="flow_session.json",
        )
        if not filename:
            return
        payload = {
            "folder": self.folder_var.get().strip(),
            "instrument": self.instrument_var.get(),
            "gates": self.gates,
            "plate_metadata": self.plate_metadata,
            "dose_curve_definitions": self.dose_curve_definitions,
        }
        with open(filename, "w") as fh:
            json.dump(payload, fh, indent=2)
        with open(self.last_session_path, "w") as fh:
            json.dump(payload, fh, indent=2)
        self.gate_status_var.set(f"Saved session to {filename} and updated last-session defaults")

    def load_session(self):
        filename = filedialog.askopenfilename(
            initialdir=self._session_dir(),
            filetypes=[("JSON files", "*.json")],
        )
        if not filename:
            return
        try:
            with open(filename) as fh:
                payload = json.load(fh)
            self._apply_session_payload(payload)
            with open(self.last_session_path, "w") as fh:
                json.dump(payload, fh, indent=2)
            self.gate_status_var.set(f"Loaded session from {filename}")
        except Exception as exc:
            self.gate_status_var.set(f"Failed to load session: {type(exc).__name__}: {exc}")

    def copy_gate_names(self):
        names = "\n".join(gate["name"] for gate in self.gates)
        self.root.clipboard_clear()
        self.root.clipboard_append(names)
        self.gate_status_var.set("Copied gate names to clipboard.")

    def open_plate_map_editor(self):
        if not self.file_map:
            messagebox.showinfo("Plate Map", "Load a folder first.")
            return

        top = tk.Toplevel(self.root)
        top.title("Plate Map Editor")
        top.geometry("980x700")
        top.rowconfigure(0, weight=1)
        top.columnconfigure(0, weight=1)

        selected_wells = set()
        available_wells = {_get_well_name(relpath, self.instrument_var.get()) for relpath in self.file_map.values()}
        sample_name_var = tk.StringVar()
        direction_var = tk.StringVar(value="horizontal")
        curve_points_var = tk.IntVar(value=8)
        top_dose_var = tk.DoubleVar(value=1.0)
        dilution_var = tk.DoubleVar(value=3.0)
        info_var = tk.StringVar(value="Click or drag across wells to select them. Hold Shift or Control to add discontinuous groups.")
        drag_rect = {"id": None, "start": None}
        well_items = {}
        row_names = "ABCDEFGH"

        outer = ttk.Frame(top)
        outer.grid(row=0, column=0, sticky="nsew")
        outer.rowconfigure(0, weight=1)
        outer.columnconfigure(0, weight=1)

        scroll_canvas = tk.Canvas(outer, highlightthickness=0)
        scroll_canvas.grid(row=0, column=0, sticky="nsew")
        scroll = ttk.Scrollbar(outer, orient="vertical", command=scroll_canvas.yview)
        scroll.grid(row=0, column=1, sticky="ns")
        scroll_canvas.configure(yscrollcommand=scroll.set)

        content = ttk.Frame(scroll_canvas, padding=10)
        content_window = scroll_canvas.create_window((0, 0), window=content, anchor="nw")

        def _sync_scroll(_event=None):
            scroll_canvas.configure(scrollregion=scroll_canvas.bbox("all"))
            scroll_canvas.itemconfigure(content_window, width=scroll_canvas.winfo_width())

        content.bind("<Configure>", _sync_scroll)
        scroll_canvas.bind("<Configure>", _sync_scroll)

        def _wheel(event):
            scroll_canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")

        scroll_canvas.bind_all("<MouseWheel>", _wheel)

        def default_well_fill(well):
            if well in selected_wells:
                return "#8dd3c7"
            if well in available_wells:
                meta = self.plate_metadata.get(well, {})
                if meta.get("excluded", False):
                    return "#d9d9d9"
                sample_name = meta.get("sample_name", "")
                if sample_name:
                    palette = ["#cfe8ff", "#ffe0c7", "#d9f2d9", "#ecd9ff", "#ffeaa7", "#ffd6e7"]
                    return palette[abs(hash(sample_name)) % len(palette)]
                return "#ffffff"
            return "#f3f3f3"

        def refresh_plate():
            for well, items in well_items.items():
                fill = default_well_fill(well)
                outline = "#1f77b4" if well in available_wells else "#b5b5b5"
                width = 3 if well in selected_wells else 1.5
                canvas.itemconfigure(items["oval"], fill=fill, outline=outline, width=width)

        def set_info():
            ordered = sorted(selected_wells, key=lambda w: (w[0], int(w[1:])))
            info_var.set(f"Selected wells ({len(ordered)}): {', '.join(ordered) if ordered else 'none'}")

        def toggle_well(well):
            if well in selected_wells:
                selected_wells.remove(well)
            else:
                selected_wells.add(well)
            refresh_plate()
            set_info()

        def wells_in_bbox(x0, y0, x1, y1):
            xmin, xmax = sorted((x0, x1))
            ymin, ymax = sorted((y0, y1))
            hits = []
            for well, items in well_items.items():
                cx, cy = items["center"]
                if xmin <= cx <= xmax and ymin <= cy <= ymax:
                    hits.append(well)
            return hits

        def on_canvas_press(event):
            drag_rect["start"] = (event.x, event.y)
            if drag_rect["id"] is not None:
                canvas.delete(drag_rect["id"])
            drag_rect["id"] = canvas.create_rectangle(event.x, event.y, event.x, event.y, dash=(4, 2), outline="#3366cc")

        def on_canvas_drag(event):
            if drag_rect["id"] is None or drag_rect["start"] is None:
                return
            x0, y0 = drag_rect["start"]
            canvas.coords(drag_rect["id"], x0, y0, event.x, event.y)

        def on_canvas_release(event):
            if drag_rect["start"] is None:
                return
            x0, y0 = drag_rect["start"]
            moved = abs(event.x - x0) + abs(event.y - y0) > 8
            if drag_rect["id"] is not None:
                canvas.delete(drag_rect["id"])
                drag_rect["id"] = None
            drag_rect["start"] = None
            if moved:
                hits = wells_in_bbox(x0, y0, event.x, event.y)
                if not _event_adds_to_selection(event):
                    selected_wells.clear()
                selected_wells.update(hits)
                refresh_plate()
                set_info()

        def on_well_click(well):
            def handler(_event):
                if not _event_adds_to_selection(_event):
                    selected_wells.clear()
                toggle_well(well)
                meta = self.plate_metadata.get(well)
                if meta:
                    messagebox.showinfo(
                        "Well Assignment",
                        f"Well {well}\n"
                        f"Sample: {meta.get('sample_name', '')}\n"
                        f"Dose curve: {meta.get('dose_curve', '')}\n"
                        f"Dose: {meta.get('dose', '')}\n"
                        f"Replicate: {meta.get('replicate', '')}\n"
                        f"Direction: {meta.get('dose_direction', '')}\n"
                        f"Excluded: {bool(meta.get('excluded', False))}",
                    )
                return "break"
            return handler

        def sorted_selected_wells():
            return sorted(selected_wells, key=lambda w: (w[0], int(w[1:])))

        def apply_metadata():
            if not selected_wells:
                info_var.set("No wells selected.")
                return
            for well in sorted_selected_wells():
                self.plate_metadata.setdefault(well, {})
                self.plate_metadata[well]["sample_name"] = sample_name_var.get().strip()
            refresh_plate()
            info_var.set(f"Applied metadata to {len(selected_wells)} wells.")

        def apply_dose_curve():
            wells = sorted_selected_wells()
            if not wells:
                info_var.set("No wells selected.")
                return
            sample_name = sample_name_var.get().strip()
            if not sample_name:
                info_var.set("Enter a sample name first.")
                return
            curve_name = sample_name
            direction = direction_var.get().strip().lower()
            if direction not in {"horizontal", "vertical"}:
                info_var.set("Direction must be horizontal or vertical.")
                return
            n_points = max(int(curve_points_var.get()), 1)
            top_dose = float(top_dose_var.get())
            dilution = float(dilution_var.get())
            if dilution <= 0:
                info_var.set("Dilution must be > 0.")
                return

            grouped = {}
            for well in wells:
                row = well[0]
                col = int(well[1:])
                key = row if direction == "horizontal" else col
                grouped.setdefault(key, []).append(well)

            sorted_groups = []
            for key, group_wells in grouped.items():
                if direction == "horizontal":
                    group_sorted = sorted(group_wells, key=lambda w: int(w[1:]))
                else:
                    group_sorted = sorted(group_wells, key=lambda w: w[0])
                sorted_groups.append((key, group_sorted))
            sorted_groups.sort(key=lambda item: item[0])

            for replicate_idx, (_key, group_wells) in enumerate(sorted_groups, start=1):
                for point_idx, well in enumerate(group_wells[:n_points]):
                    dose_value = top_dose / (dilution ** point_idx)
                    self.plate_metadata.setdefault(well, {})
                    self.plate_metadata[well]["sample_name"] = sample_name
                    self.plate_metadata[well]["dose_curve"] = curve_name
                    self.plate_metadata[well]["dose"] = dose_value
                    self.plate_metadata[well]["replicate"] = replicate_idx
                    self.plate_metadata[well]["dose_direction"] = direction
            self.dose_curve_definitions[sample_name] = {
                "sample_name": sample_name,
                "direction": direction,
                "points": n_points,
                "top_dose": top_dose,
                "dilution": dilution,
                "wells": wells,
            }
            refresh_plate()
            refresh_curve_panel()
            info_var.set(f"Assigned sample '{sample_name}' to {len(wells)} wells with {direction} dose progression.")

        def export_metadata():
            if not self.plate_metadata:
                messagebox.showinfo("Plate Map", "No metadata to export.")
                return
            filename = filedialog.asksaveasfilename(
                defaultextension=".csv",
                filetypes=[("CSV files", "*.csv")],
                initialfile="plate_map_metadata.csv",
            )
            if not filename:
                return
            rows = []
            for well, meta in sorted(self.plate_metadata.items(), key=lambda item: (item[0][0], int(item[0][1:]))):
                row = {"well": well}
                row.update(meta)
                rows.append(row)
            try:
                pd.DataFrame(rows).to_csv(filename, index=False)
                info_var.set(f"Saved plate metadata to {filename}")
            except Exception as exc:
                info_var.set(f"Failed to save plate metadata: {type(exc).__name__}: {exc}")

        def refresh_curve_panel():
            curve_text.configure(state="normal")
            curve_text.delete("1.0", tk.END)
            if not self.dose_curve_definitions:
                curve_text.insert("1.0", "No dose curves assigned yet.")
            else:
                for key, definition in sorted(self.dose_curve_definitions.items()):
                    wells_text = ", ".join(definition["wells"])
                    curve_text.insert(
                        tk.END,
                        f"{key}\n"
                        f"  direction: {definition['direction']}\n"
                        f"  points: {definition['points']}\n"
                        f"  top dose: {definition['top_dose']}\n"
                        f"  dilution: {definition['dilution']}\n"
                        f"  wells: {wells_text}\n\n",
                    )
            curve_text.configure(state="disabled")

        content.columnconfigure(0, weight=1)
        canvas = tk.Canvas(content, width=760, height=430, bg="white")
        canvas.grid(row=0, column=0, padx=0, pady=(0, 10), sticky="ew")
        control = ttk.Frame(content, padding=10)
        control.grid(row=1, column=0, sticky="ew")
        control.columnconfigure(0, weight=0)
        control.columnconfigure(1, weight=0)
        control.columnconfigure(2, weight=0)
        control.columnconfigure(3, weight=0)
        control.columnconfigure(4, weight=0)
        control.columnconfigure(5, weight=0)
        control.columnconfigure(6, weight=0)
        control.columnconfigure(7, weight=0)
        control.columnconfigure(8, weight=0)

        margin_x = 70
        margin_y = 55
        spacing_x = 54
        spacing_y = 42
        radius = 16

        for col in range(12):
            canvas.create_text(margin_x + col * spacing_x, 20, text=str(col + 1), font=("Helvetica", 11, "bold"))
        for row_idx, row_name in enumerate(row_names):
            canvas.create_text(26, margin_y + row_idx * spacing_y, text=row_name, font=("Helvetica", 11, "bold"))
            for col_idx in range(12):
                well = f"{row_name}{col_idx + 1}"
                cx = margin_x + col_idx * spacing_x
                cy = margin_y + row_idx * spacing_y
                oval = canvas.create_oval(cx - radius, cy - radius, cx + radius, cy + radius, fill=default_well_fill(well), outline="#888", width=1.5)
                label = canvas.create_text(cx, cy, text=well, font=("Helvetica", 8))
                canvas.tag_bind(oval, "<Button-1>", on_well_click(well))
                canvas.tag_bind(label, "<Button-1>", on_well_click(well))
                well_items[well] = {"oval": oval, "label": label, "center": (cx, cy)}

        canvas.bind("<ButtonPress-1>", on_canvas_press)
        canvas.bind("<B1-Motion>", on_canvas_drag)
        canvas.bind("<ButtonRelease-1>", on_canvas_release)
        refresh_plate()

        basic = ttk.LabelFrame(control, text="Sample Assignment", padding=10)
        basic.grid(row=0, column=0, sticky="ew", pady=(0, 10))
        ttk.Label(basic, text="Sample Name").grid(row=0, column=0, sticky="w")
        ttk.Entry(basic, textvariable=sample_name_var, width=24).grid(row=1, column=0, padx=4)
        ttk.Button(basic, text="Apply Sample Name", command=apply_metadata).grid(row=1, column=1, padx=6)

        dose_frame = ttk.LabelFrame(control, text="Dose Curve Parameters", padding=10)
        dose_frame.grid(row=1, column=0, sticky="ew")
        ttk.Label(dose_frame, text="Direction").grid(row=0, column=0, sticky="w")
        ttk.Combobox(dose_frame, textvariable=direction_var, values=["horizontal", "vertical"], state="readonly", width=12).grid(row=1, column=0, padx=4)
        ttk.Label(dose_frame, text="Number of Points").grid(row=0, column=1, sticky="w")
        ttk.Spinbox(dose_frame, from_=1, to=24, textvariable=curve_points_var, width=10).grid(row=1, column=1, padx=4)
        ttk.Label(dose_frame, text="Top Dose").grid(row=0, column=2, sticky="w")
        ttk.Entry(dose_frame, textvariable=top_dose_var, width=12).grid(row=1, column=2, padx=4)
        ttk.Label(dose_frame, text="Dilution Per Step").grid(row=0, column=3, sticky="w")
        ttk.Entry(dose_frame, textvariable=dilution_var, width=12).grid(row=1, column=3, padx=4)
        ttk.Button(dose_frame, text="Apply Dose Curve", command=apply_dose_curve).grid(row=1, column=4, padx=8)
        ttk.Button(dose_frame, text="Export Plate CSV", command=export_metadata).grid(row=1, column=5, padx=8)

        curve_frame = ttk.LabelFrame(content, text="Current Dose Curves", padding=10)
        curve_frame.grid(row=2, column=0, sticky="ew")
        curve_text = tk.Text(curve_frame, width=90, height=10, wrap="word")
        curve_text.grid(row=0, column=0, sticky="ew")
        curve_text.configure(state="disabled")
        refresh_curve_panel()

        ttk.Label(content, textvariable=info_var, wraplength=900).grid(row=3, column=0, sticky="w", pady=(10, 10))

    def open_exclusion_editor(self):
        if not self.file_map:
            messagebox.showinfo("Excluded Wells", "Load a folder first.")
            return

        top = tk.Toplevel(self.root)
        top.title("Excluded Wells Editor")
        top.geometry("920x620")
        top.rowconfigure(0, weight=1)
        top.columnconfigure(0, weight=1)

        selected_wells = set()
        available_wells = {_get_well_name(relpath, self.instrument_var.get()) for relpath in self.file_map.values()}
        info_var = tk.StringVar(value="Select wells to exclude. Hold Shift or Control to add discontinuous groups.")
        drag_rect = {"id": None, "start": None}
        well_items = {}
        row_names = "ABCDEFGH"

        outer = ttk.Frame(top, padding=10)
        outer.grid(row=0, column=0, sticky="nsew")
        outer.rowconfigure(0, weight=1)
        outer.columnconfigure(0, weight=1)

        canvas = tk.Canvas(outer, width=760, height=430, bg="white")
        canvas.grid(row=0, column=0, sticky="nsew")

        def default_well_fill(well):
            if well in selected_wells:
                return "#ffd166"
            if well not in available_wells:
                return "#f3f3f3"
            if self.plate_metadata.get(well, {}).get("excluded", False):
                return "#7f7f7f"
            if self.plate_metadata.get(well, {}).get("sample_name", ""):
                return "#cfe8ff"
            return "#ffffff"

        def refresh_plate():
            for well, items in well_items.items():
                canvas.itemconfigure(items["oval"], fill=default_well_fill(well))

        def set_info():
            ordered = sorted(selected_wells, key=lambda w: (w[0], int(w[1:])))
            info_var.set(f"Selected wells ({len(ordered)}): {', '.join(ordered) if ordered else 'none'}")

        def wells_in_bbox(x0, y0, x1, y1):
            xmin, xmax = sorted((x0, x1))
            ymin, ymax = sorted((y0, y1))
            hits = []
            for well, items in well_items.items():
                cx, cy = items["center"]
                if xmin <= cx <= xmax and ymin <= cy <= ymax and well in available_wells:
                    hits.append(well)
            return hits

        def on_canvas_press(event):
            drag_rect["start"] = (event.x, event.y)
            if drag_rect["id"] is not None:
                canvas.delete(drag_rect["id"])
            drag_rect["id"] = canvas.create_rectangle(event.x, event.y, event.x, event.y, dash=(4, 2), outline="#3366cc")

        def on_canvas_drag(event):
            if drag_rect["id"] is None or drag_rect["start"] is None:
                return
            x0, y0 = drag_rect["start"]
            canvas.coords(drag_rect["id"], x0, y0, event.x, event.y)

        def on_canvas_release(event):
            if drag_rect["start"] is None:
                return
            x0, y0 = drag_rect["start"]
            moved = abs(event.x - x0) + abs(event.y - y0) > 8
            if drag_rect["id"] is not None:
                canvas.delete(drag_rect["id"])
                drag_rect["id"] = None
            drag_rect["start"] = None
            if moved:
                hits = wells_in_bbox(x0, y0, event.x, event.y)
                if not _event_adds_to_selection(event):
                    selected_wells.clear()
                selected_wells.update(hits)
                refresh_plate()
                set_info()

        def on_well_click(well):
            def handler(event):
                if well not in available_wells:
                    return "break"
                if not _event_adds_to_selection(event):
                    selected_wells.clear()
                if well in selected_wells:
                    selected_wells.remove(well)
                else:
                    selected_wells.add(well)
                refresh_plate()
                set_info()
                meta = self.plate_metadata.get(well, {})
                messagebox.showinfo(
                    "Well Status",
                    f"Well {well}\n"
                    f"Sample: {meta.get('sample_name', '')}\n"
                    f"Excluded: {bool(meta.get('excluded', False))}",
                )
                return "break"
            return handler

        def apply_excluded(excluded_value):
            if not selected_wells:
                info_var.set("No wells selected.")
                return
            for well in selected_wells:
                self.plate_metadata.setdefault(well, {})
                self.plate_metadata[well]["excluded"] = bool(excluded_value)
            refresh_plate()
            self.update_heatmap()
            info_var.set(f"{'Excluded' if excluded_value else 'Included'} {len(selected_wells)} wells for downstream analysis.")

        margin_x = 70
        margin_y = 55
        spacing_x = 54
        spacing_y = 42
        radius = 16

        for col in range(12):
            canvas.create_text(margin_x + col * spacing_x, 20, text=str(col + 1), font=("Helvetica", 11, "bold"))
        for row_idx, row_name in enumerate(row_names):
            canvas.create_text(26, margin_y + row_idx * spacing_y, text=row_name, font=("Helvetica", 11, "bold"))
            for col_idx in range(12):
                well = f"{row_name}{col_idx + 1}"
                cx = margin_x + col_idx * spacing_x
                cy = margin_y + row_idx * spacing_y
                oval = canvas.create_oval(cx - radius, cy - radius, cx + radius, cy + radius, fill=default_well_fill(well), outline="#888", width=1.5)
                label = canvas.create_text(cx, cy, text=well, font=("Helvetica", 8))
                canvas.tag_bind(oval, "<Button-1>", on_well_click(well))
                canvas.tag_bind(label, "<Button-1>", on_well_click(well))
                well_items[well] = {"oval": oval, "label": label, "center": (cx, cy)}

        canvas.bind("<ButtonPress-1>", on_canvas_press)
        canvas.bind("<B1-Motion>", on_canvas_drag)
        canvas.bind("<ButtonRelease-1>", on_canvas_release)
        refresh_plate()

        controls = ttk.Frame(outer, padding=(0, 10, 0, 0))
        controls.grid(row=1, column=0, sticky="ew")
        ttk.Button(controls, text="Exclude Selected", command=lambda: apply_excluded(True)).grid(row=0, column=0, padx=(0, 8))
        ttk.Button(controls, text="Include Selected", command=lambda: apply_excluded(False)).grid(row=0, column=1, padx=(0, 8))
        ttk.Label(controls, textvariable=info_var, wraplength=820).grid(row=1, column=0, columnspan=2, sticky="w", pady=(10, 0))

    def _summary_dataframe(self):
        fluorescent_gates = self._fluorescence_gates()
        rows = []
        for label, relpath, well in self._included_file_items():
            df = self._sample_raw_dataframe(label)
            row = {"well": well, "source": relpath, "event_count": len(df)}
            row = self._annotate_sample_row(row, well)
            for gate in fluorescent_gates:
                frac, count, parent_total = self._gate_fraction_for_label(gate, label)
                row[f"pct_{gate['name']}"] = 100 * frac
                row[f"count_{gate['name']}"] = count
                row[f"parent_count_{gate['name']}"] = parent_total
            rows.append(row)
        return pd.DataFrame(rows)

    def export_gate_summary_csv(self):
        if not self.gates:
            messagebox.showinfo("Export Summary", "No gates saved.")
            return
        filename = filedialog.asksaveasfilename(
            defaultextension=".csv",
            filetypes=[("CSV files", "*.csv")],
            initialfile="flow_gate_summary.csv",
        )
        if not filename:
            return
        try:
            self._summary_dataframe().to_csv(filename, index=False)
            self.gate_status_var.set(f"Saved gate summary to {filename}")
        except Exception as exc:
            self.gate_status_var.set(f"Failed to save gate summary: {type(exc).__name__}: {exc}")

    def _intensity_distribution_dataframe(self):
        fluorescence_columns = [
            channel for channel in self.channel_names
            if not any(token in channel for token in ("FSC", "SSC", "Time"))
        ]
        frames = []
        for label, relpath, well in self._included_file_items():
            df = self._sample_raw_dataframe(label)
            keep_columns = ["__well__", "__source__"] + [col for col in fluorescence_columns if col in df.columns]
            out = df[keep_columns].copy()
            out.rename(columns={"__well__": "well", "__source__": "source"}, inplace=True)
            metadata = self._metadata_for_well(well)
            out["sample_name"] = metadata.get("sample_name", "")
            out["treatment_group"] = metadata.get("treatment_group", "")
            out["dose_curve"] = metadata.get("dose_curve", "")
            out["dose"] = metadata.get("dose", "")
            out["replicate"] = metadata.get("replicate", "")
            out["sample_type"] = metadata.get("sample_type", "")
            out["dose_direction"] = metadata.get("dose_direction", "")
            out["excluded"] = bool(metadata.get("excluded", False))
            for gate in self.gates:
                gated_df = df.copy()
                for lineage_gate in self._population_lineage(gate["name"]):
                    transformed = _apply_transform(
                        gated_df,
                        lineage_gate["x_channel"],
                        _gate_plot_y_channel(lineage_gate),
                        lineage_gate["transform"],
                        lineage_gate["cofactor"],
                    )
                    mask = _gate_mask(transformed, lineage_gate)
                    gated_df = gated_df.loc[mask].copy()
                out[f"in_{gate['name']}"] = df.index.isin(gated_df.index)
            frames.append(out)
        return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()

    def export_intensity_csv(self):
        filename = filedialog.asksaveasfilename(
            defaultextension=".csv",
            filetypes=[("CSV files", "*.csv")],
            initialfile="flow_intensity_distribution.csv",
        )
        if not filename:
            return
        try:
            self._intensity_distribution_dataframe().to_csv(filename, index=False)
            self.gate_status_var.set(f"Saved intensity distribution to {filename}")
        except Exception as exc:
            self.gate_status_var.set(f"Failed to save intensity distribution: {type(exc).__name__}: {exc}")

    def open_analysis_preview(self):
        summary = self._summary_dataframe()
        intensity = self._intensity_distribution_dataframe()
        if summary.empty and intensity.empty:
            messagebox.showinfo("Analysis Preview", "No data available yet.")
            return

        top = tk.Toplevel(self.root)
        top.title("Analysis Preview")
        top.geometry("1380x820")
        top.rowconfigure(1, weight=1)
        top.columnconfigure(0, weight=1)
        top.columnconfigure(1, weight=0)

        controls = ttk.Frame(top, padding=10)
        controls.grid(row=0, column=0, sticky="ew")

        plot_mode_var = tk.StringVar(value="bar")
        pct_cols = [c for c in summary.columns if c.startswith("pct_")]
        default_pct = pct_cols[0] if pct_cols else ""
        pct_col_var = tk.StringVar(value=default_pct)
        x_axis_var = tk.StringVar(value="sample_name" if "sample_name" in summary.columns else "well")
        hue_var = tk.StringVar(value="replicate" if "replicate" in summary.columns else "")

        metadata_cols = {"well", "source", "sample_name", "treatment_group", "dose_curve", "dose", "replicate", "sample_type", "dose_direction", "excluded"}
        bool_cols = [c for c in intensity.columns if c.startswith("in_")]
        channel_cols = [c for c in intensity.columns if c not in metadata_cols and c not in bool_cols]
        channel_var = tk.StringVar(value=channel_cols[0] if channel_cols else "")
        corr_channel_y_var = tk.StringVar(value=channel_cols[1] if len(channel_cols) > 1 else (channel_cols[0] if channel_cols else ""))
        gate_filter_var = tk.StringVar(value="")
        hue_dist_var = tk.StringVar(value="sample_name" if "sample_name" in intensity.columns else "well")
        sample_names = sorted({
            str(value).strip()
            for value in pd.concat(
                [
                    summary["sample_name"] if "sample_name" in summary.columns else pd.Series(dtype=object),
                    intensity["sample_name"] if "sample_name" in intensity.columns else pd.Series(dtype=object),
                ],
                ignore_index=True,
            ).dropna()
            if str(value).strip()
        })
        palette_options = ["deep", "muted", "bright", "pastel", "dark", "colorblind", "Set1", "Set2", "Set3", "tab10", "tab20", "husl", "hls", "Blues", "Greens", "Reds", "rocket", "mako", "flare", "crest", "viridis", "magma", "plasma", "cividis"]
        group_order = ["Group 1", "Group 2", "Group 3", "Group 4"]
        sample_group = {sample: "Ungrouped" for sample in sample_names}
        sample_selected = {sample: tk.BooleanVar(value=False) for sample in sample_names}
        group_palette_vars = {
            "Ungrouped": tk.StringVar(value="tab10"),
            "Group 1": tk.StringVar(value="deep"),
            "Group 2": tk.StringVar(value="Set2"),
            "Group 3": tk.StringVar(value="Set3"),
            "Group 4": tk.StringVar(value="colorblind"),
        }
        group_boxes = {}
        group_move_var = tk.StringVar(value="Group 1")
        drag_status_var = tk.StringVar(value="Check one or more samples, then move them into a target group.")

        ttk.Label(controls, text="Plot Type").grid(row=0, column=0, sticky="w")
        ttk.Combobox(controls, textvariable=plot_mode_var, values=["bar", "distribution", "correlation"], state="readonly", width=14).grid(row=1, column=0, padx=4)
        ttk.Label(controls, text="% Positive Column").grid(row=0, column=1, sticky="w")
        ttk.Combobox(controls, textvariable=pct_col_var, values=pct_cols, state="readonly", width=28).grid(row=1, column=1, padx=4)
        ttk.Label(controls, text="Bar X").grid(row=0, column=2, sticky="w")
        ttk.Combobox(controls, textvariable=x_axis_var, values=[c for c in ["sample_name", "well", "dose_curve", "dose"] if c in summary.columns], state="readonly", width=16).grid(row=1, column=2, padx=4)
        ttk.Label(controls, text="Bar Hue").grid(row=0, column=3, sticky="w")
        ttk.Combobox(controls, textvariable=hue_var, values=["", "replicate", "sample_name", "dose_curve"], state="readonly", width=14).grid(row=1, column=3, padx=4)
        ttk.Label(controls, text="Intensity / Corr X").grid(row=0, column=4, sticky="w")
        ttk.Combobox(controls, textvariable=channel_var, values=channel_cols, state="readonly", width=22).grid(row=1, column=4, padx=4)
        ttk.Label(controls, text="Gate Filter").grid(row=0, column=5, sticky="w")
        ttk.Combobox(controls, textvariable=gate_filter_var, values=[""] + bool_cols, state="readonly", width=22).grid(row=1, column=5, padx=4)
        ttk.Label(controls, text="Dist Hue").grid(row=0, column=6, sticky="w")
        ttk.Combobox(controls, textvariable=hue_dist_var, values=[c for c in ["sample_name", "well", "dose_curve"] if c in intensity.columns], state="readonly", width=16).grid(row=1, column=6, padx=4)
        ttk.Label(controls, text="Corr Y").grid(row=0, column=7, sticky="w")
        ttk.Combobox(controls, textvariable=corr_channel_y_var, values=channel_cols, state="readonly", width=22).grid(row=1, column=7, padx=4)

        fig = Figure(figsize=(10, 6), dpi=100)
        ax = fig.add_subplot(111)
        canvas_frame = ttk.Frame(top, padding=10)
        canvas_frame.grid(row=1, column=0, sticky="nsew")
        canvas_frame.rowconfigure(0, weight=1)
        canvas_frame.columnconfigure(0, weight=1)
        canvas = FigureCanvasTkAgg(fig, master=canvas_frame)
        canvas.get_tk_widget().grid(row=0, column=0, sticky="nsew")
        toolbar = NavigationToolbar2Tk(canvas, canvas_frame, pack_toolbar=False)
        toolbar.update()
        toolbar.grid(row=1, column=0, sticky="ew")

        palette_frame = ttk.LabelFrame(top, text="Sample Palette Groups", padding=10)
        palette_frame.grid(row=1, column=1, sticky="ns", padx=(0, 10), pady=10)
        palette_frame.columnconfigure(0, weight=1)

        ttk.Label(
            palette_frame,
            text="Check samples, move them into a target group, and assign any seaborn or matplotlib palette name to that group.",
            wraplength=300,
        ).grid(row=0, column=0, sticky="w", pady=(0, 8))
        ttk.Label(palette_frame, textvariable=drag_status_var, wraplength=300).grid(row=1, column=0, sticky="w", pady=(0, 8))

        move_row = ttk.Frame(palette_frame)
        move_row.grid(row=2, column=0, sticky="ew", pady=(0, 10))
        ttk.Label(move_row, text="Move Selected To").grid(row=0, column=0, sticky="w")
        ttk.Combobox(move_row, textvariable=group_move_var, values=["Ungrouped"] + group_order, state="readonly", width=14).grid(row=0, column=1, padx=6)

        def _group_samples(group_name):
            return sorted([sample for sample, assigned in sample_group.items() if assigned == group_name])

        def _refresh_group_boxes():
            for group_name, widgets in group_boxes.items():
                samples = _group_samples(group_name)
                widgets["count_var"].set(f"{len(samples)} samples")
                for child in widgets["sample_frame"].winfo_children():
                    child.destroy()
                if not samples:
                    ttk.Label(widgets["sample_frame"], text="No samples").grid(row=0, column=0, sticky="w")
                else:
                    for idx, sample in enumerate(samples):
                        ttk.Checkbutton(
                            widgets["sample_frame"],
                            text=sample,
                            variable=sample_selected[sample],
                            command=lambda s=sample, g=group_name: _update_selection_status(s, g),
                        ).grid(row=idx, column=0, sticky="w")
            if "redraw_preview" in locals():
                redraw_preview()

        def _selected_samples():
            return [sample for sample, selected in sample_selected.items() if selected.get()]

        def _update_selection_status(_sample=None, _group=None):
            samples = _selected_samples()
            if not samples:
                drag_status_var.set("Check one or more samples, then move them into a target group.")
            else:
                drag_status_var.set(f"Selected {len(samples)} sample(s). Move them to {group_move_var.get()}.")

        def _move_selected():
            samples = _selected_samples()
            if not samples:
                drag_status_var.set("No samples checked.")
                return
            target_group = group_move_var.get()
            for sample in samples:
                sample_group[sample] = target_group
                sample_selected[sample].set(False)
            drag_status_var.set(f"Moved {len(samples)} sample(s) into {target_group}.")
            _refresh_group_boxes()

        def _clear_grouping():
            for sample in sample_names:
                sample_group[sample] = "Ungrouped"
                sample_selected[sample].set(False)
            _refresh_group_boxes()

        def _resolve_palette(name, n_colors):
            palette_name = str(name).strip() or "tab10"
            try:
                return sns.color_palette(palette_name, max(n_colors, 1)).as_hex()
            except Exception:
                drag_status_var.set(f"Palette '{palette_name}' not found. Falling back to tab10.")
                return sns.color_palette("tab10", max(n_colors, 1)).as_hex()

        def _palette_for_hue(hue_values):
            if hue_values != "sample_name":
                return None
            palette = {}
            for group_name, widgets in group_boxes.items():
                samples = _group_samples(group_name)
                if not samples:
                    continue
                colors = _resolve_palette(group_palette_vars[group_name].get(), len(samples))
                for idx, sample in enumerate(samples):
                    palette[sample] = colors[idx % len(colors)]
            return palette or None

        def _add_group_box(parent, row, group_name):
            frame = ttk.LabelFrame(parent, text=group_name, padding=8)
            frame.grid(row=row, column=0, sticky="ew", pady=6)
            frame.columnconfigure(0, weight=1)
            count_var = tk.StringVar(value="0 samples")
            if group_name != "Ungrouped":
                ttk.Label(frame, text="Palette").grid(row=0, column=0, sticky="w")
                palette_combo = ttk.Combobox(
                    frame,
                    textvariable=group_palette_vars[group_name],
                    values=palette_options,
                    state="normal",
                    width=16,
                )
                palette_combo.grid(row=0, column=1, sticky="e")
                palette_combo.bind("<<ComboboxSelected>>", lambda _event: redraw_preview())
                palette_combo.bind("<Return>", lambda _event: redraw_preview())
                palette_combo.bind("<FocusOut>", lambda _event: redraw_preview())
            else:
                ttk.Label(frame, text="Default palette").grid(row=0, column=0, sticky="w")
                palette_combo = ttk.Combobox(
                    frame,
                    textvariable=group_palette_vars[group_name],
                    values=palette_options,
                    state="normal",
                    width=16,
                )
                palette_combo.grid(row=0, column=1, sticky="e")
                palette_combo.bind("<<ComboboxSelected>>", lambda _event: redraw_preview())
                palette_combo.bind("<Return>", lambda _event: redraw_preview())
                palette_combo.bind("<FocusOut>", lambda _event: redraw_preview())
            ttk.Label(frame, textvariable=count_var).grid(row=1, column=0, columnspan=2, sticky="w", pady=(4, 4))
            sample_frame = ttk.Frame(frame)
            sample_frame.grid(row=2, column=0, columnspan=2, sticky="ew")
            ttk.Label(frame, text="Check samples below, then use Move Selected To").grid(row=3, column=0, columnspan=2, sticky="w", pady=(4, 0))
            group_boxes[group_name] = {"frame": frame, "sample_frame": sample_frame, "count_var": count_var}

        ttk.Button(move_row, text="Move", command=_move_selected).grid(row=0, column=2, padx=6)

        _add_group_box(palette_frame, 3, "Ungrouped")
        for idx, group_name in enumerate(group_order, start=4):
            _add_group_box(palette_frame, idx, group_name)
        ttk.Button(palette_frame, text="Reset Grouping", command=_clear_grouping).grid(row=len(group_order) + 4, column=0, sticky="ew", pady=(8, 0))
        if not sample_names:
            ttk.Label(palette_frame, text="No sample names available yet.").grid(row=len(group_order) + 5, column=0, sticky="w", pady=(8, 0))
        def redraw_preview(*_args):
            ax.clear()
            mode = plot_mode_var.get()
            if mode == "bar":
                if not pct_col_var.get() or pct_col_var.get() not in summary.columns:
                    ax.set_title("No % positive column selected")
                    canvas.draw_idle()
                    return
                plot_df = summary.copy()
                xcol = x_axis_var.get() if x_axis_var.get() in plot_df.columns else "well"
                huecol = hue_var.get() if hue_var.get() in plot_df.columns and hue_var.get() else None
                if huecol == "sample_name":
                    sns.barplot(
                        data=plot_df,
                        x=xcol,
                        y=pct_col_var.get(),
                        hue=huecol,
                        palette=_palette_for_hue("sample_name"),
                        ax=ax,
                    )
                elif huecol is None and xcol == "sample_name":
                    sample_palette = _palette_for_hue("sample_name") or {}
                    order = list(plot_df[xcol].dropna().astype(str).unique())
                    colors = [sample_palette.get(name, "#4c72b0") for name in order]
                    sns.barplot(
                        data=plot_df,
                        x=xcol,
                        y=pct_col_var.get(),
                        order=order,
                        palette=colors,
                        ax=ax,
                    )
                else:
                    sns.barplot(
                        data=plot_df,
                        x=xcol,
                        y=pct_col_var.get(),
                        hue=huecol,
                        ax=ax,
                    )
                ax.set_ylabel("% positive")
                ax.tick_params(axis="x", rotation=45)
                fig.tight_layout()
                canvas.draw_idle()
                return

            if not channel_var.get() or channel_var.get() not in intensity.columns:
                ax.set_title("No intensity channel selected")
                canvas.draw_idle()
                return
            plot_df = intensity.copy()
            if gate_filter_var.get() and gate_filter_var.get() in plot_df.columns:
                plot_df = plot_df[plot_df[gate_filter_var.get()].astype(bool)]
            huecol = hue_dist_var.get() if hue_dist_var.get() in plot_df.columns else None
            plot_df = plot_df.copy()
            plot_df[channel_var.get()] = pd.to_numeric(plot_df[channel_var.get()], errors="coerce")
            plot_df = plot_df.dropna(subset=[channel_var.get()])
            plot_df = plot_df[plot_df[channel_var.get()] > 0]
            if plot_df.empty:
                ax.set_title("No intensity data after filtering")
                canvas.draw_idle()
                return
            if mode == "correlation":
                if not corr_channel_y_var.get() or corr_channel_y_var.get() not in intensity.columns:
                    ax.set_title("No correlation Y channel selected")
                    canvas.draw_idle()
                    return
                if channel_var.get() == corr_channel_y_var.get():
                    ax.set_title("Choose two different channels")
                    canvas.draw_idle()
                    return
                xcol = x_axis_var.get() if x_axis_var.get() in plot_df.columns else "well"
                huecol = hue_var.get() if hue_var.get() in plot_df.columns and hue_var.get() else None
                group_cols = [xcol] + ([huecol] if huecol and huecol != xcol else [])
                corr_rows = []
                for group_key, group in plot_df.groupby(group_cols, dropna=False):
                    corr_input = group[[channel_var.get(), corr_channel_y_var.get()]].apply(pd.to_numeric, errors="coerce").dropna()
                    if len(corr_input) < 2:
                        corr_value = np.nan
                    else:
                        corr_calc = corr_input[channel_var.get()].corr(corr_input[corr_channel_y_var.get()])
                        corr_value = float(corr_calc) if pd.notna(corr_calc) else np.nan
                    if not isinstance(group_key, tuple):
                        group_key = (group_key,)
                    row = {group_cols[idx]: group_key[idx] for idx in range(len(group_cols))}
                    row["correlation"] = corr_value
                    corr_rows.append(row)
                corr_df = pd.DataFrame(corr_rows).dropna(subset=["correlation"])
                if corr_df.empty:
                    ax.set_title("No valid correlations after filtering")
                    canvas.draw_idle()
                    return
                if huecol == "sample_name":
                    sns.barplot(
                        data=corr_df,
                        x=xcol,
                        y="correlation",
                        hue=huecol,
                        palette=_palette_for_hue("sample_name"),
                        ax=ax,
                    )
                else:
                    sns.barplot(data=corr_df, x=xcol, y="correlation", hue=huecol, ax=ax)
                ax.set_ylim(-1.05, 1.05)
                ax.axhline(0, color="#666666", linewidth=1, linestyle="--")
                ax.tick_params(axis="x", rotation=45)
                ax.set_title(f"Correlation: {channel_var.get()} vs {corr_channel_y_var.get()}")
                fig.tight_layout()
                canvas.draw_idle()
                return
            sns.kdeplot(
                data=plot_df,
                x=channel_var.get(),
                hue=huecol,
                common_norm=False,
                fill=False,
                palette=_palette_for_hue(huecol),
                ax=ax,
            )
            ax.set_xscale("log")
            ax.set_title("Fluorescence distribution")
            fig.tight_layout()
            canvas.draw_idle()

        for var in [plot_mode_var, pct_col_var, x_axis_var, hue_var, channel_var, corr_channel_y_var, gate_filter_var, hue_dist_var]:
            var.trace_add("write", redraw_preview)
        _refresh_group_boxes()
        redraw_preview()

    def _default_export_dir(self):
        return os.path.join(self._app_home(), "exports")

    def _plate_metadata_dataframe(self):
        rows = []
        for well, meta in sorted(self.plate_metadata.items(), key=lambda item: (item[0][0], int(item[0][1:]))):
            row = {"well": well}
            row.update(meta)
            rows.append(row)
        return pd.DataFrame(rows)

    def _analysis_notebook_dict(self, summary_relpath, intensity_relpath, plate_relpath, notebook_title):
        cells = [
            {
                "cell_type": "markdown",
                "metadata": {},
                "source": [
                    f"# {notebook_title}\n",
                    "\n",
                    "This notebook loads the CSVs exported from the desktop gating UI and provides example plots for downstream analysis.\n",
                ],
            },
            {
                "cell_type": "code",
                "execution_count": None,
                "metadata": {},
                "outputs": [],
                "source": [
                    "import pandas as pd\n",
                    "import numpy as np\n",
                    "import matplotlib.pyplot as plt\n",
                    "import seaborn as sns\n",
                    "from pathlib import Path\n",
                    "\n",
                    "sns.set_context('talk')\n",
                    "sns.set_style('whitegrid')\n",
                ],
            },
            {
                "cell_type": "code",
                "execution_count": None,
                "metadata": {},
                "outputs": [],
                "source": [
                    f"summary_path = Path('{summary_relpath}')\n",
                    f"intensity_path = Path('{intensity_relpath}')\n",
                    f"plate_path = Path('{plate_relpath}')\n",
                    "\n",
                    "summary = pd.read_csv(summary_path)\n",
                    "intensity = pd.read_csv(intensity_path)\n",
                    "plate = pd.read_csv(plate_path) if plate_path.exists() and plate_path.stat().st_size > 0 else pd.DataFrame()\n",
                    "\n",
                    "summary.head()\n",
                ],
            },
            {
                "cell_type": "code",
                "execution_count": None,
                "metadata": {},
                "outputs": [],
                "source": [
                    "pct_cols = [c for c in summary.columns if c.startswith('pct_')]\n",
                    "pct_cols\n",
                ],
            },
            {
                "cell_type": "code",
                "execution_count": None,
                "metadata": {},
                "outputs": [],
                "source": [
                    "def plot_percent_positive(df, pct_col, x='sample_name', hue=None, sort_by=None, figsize=(10, 5)):\n",
                    "    plot_df = df.copy()\n",
                    "    if x not in plot_df.columns:\n",
                    "        x = 'well'\n",
                    "    if sort_by is not None and sort_by in plot_df.columns:\n",
                    "        plot_df = plot_df.sort_values(sort_by)\n",
                    "    plt.figure(figsize=figsize)\n",
                    "    sns.barplot(data=plot_df, x=x, y=pct_col, hue=hue)\n",
                    "    plt.xticks(rotation=45, ha='right')\n",
                    "    plt.ylabel('% positive')\n",
                    "    plt.tight_layout()\n",
                    "\n",
                    "def plot_dose_curve(df, pct_col, sample_name=None, figsize=(7, 5)):\n",
                    "    plot_df = df.copy()\n",
                    "    if sample_name is not None and 'sample_name' in plot_df.columns:\n",
                    "        plot_df = plot_df[plot_df['sample_name'] == sample_name]\n",
                    "    plot_df = plot_df.dropna(subset=['dose'])\n",
                    "    plot_df['dose'] = pd.to_numeric(plot_df['dose'], errors='coerce')\n",
                    "    plot_df = plot_df.dropna(subset=['dose'])\n",
                    "    plt.figure(figsize=figsize)\n",
                    "    sns.lineplot(data=plot_df, x='dose', y=pct_col, hue='sample_name', style='replicate', markers=True, dashes=False)\n",
                    "    plt.xscale('log')\n",
                    "    plt.ylabel('% positive')\n",
                    "    plt.tight_layout()\n",
                    "\n",
                    "def plot_intensity_distribution(df, channel, sample_name=None, gate_col=None, figsize=(8, 5)):\n",
                    "    plot_df = df.copy()\n",
                    "    hue_col = 'sample_name' if 'sample_name' in plot_df.columns else ('well' if 'well' in plot_df.columns else None)\n",
                    "    if sample_name is not None and 'sample_name' in plot_df.columns:\n",
                    "        plot_df = plot_df[plot_df['sample_name'] == sample_name]\n",
                    "    if gate_col is not None and gate_col in plot_df.columns:\n",
                    "        plot_df = plot_df[plot_df[gate_col].astype(bool)]\n",
                    "    plot_df[channel] = pd.to_numeric(plot_df[channel], errors='coerce')\n",
                    "    plot_df = plot_df.dropna(subset=[channel])\n",
                    "    plot_df = plot_df[plot_df[channel] > 0]\n",
                    "    plt.figure(figsize=figsize)\n",
                    "    sns.kdeplot(data=plot_df, x=channel, hue=hue_col, common_norm=False, fill=False)\n",
                    "    plt.xscale('log')\n",
                    "    plt.tight_layout()\n",
                    "\n",
                    "def plot_channel_correlation(df, x_channel, y_channel, x='sample_name', hue=None, gate_col=None, figsize=(10, 5)):\n",
                    "    plot_df = df.copy()\n",
                    "    if gate_col is not None and gate_col in plot_df.columns:\n",
                    "        plot_df = plot_df[plot_df[gate_col].astype(bool)]\n",
                    "    group_cols = [x] + ([hue] if hue and hue in plot_df.columns and hue != x else [])\n",
                    "    rows = []\n",
                    "    for group_key, group in plot_df.groupby(group_cols, dropna=False):\n",
                    "        corr_input = group[[x_channel, y_channel]].apply(pd.to_numeric, errors='coerce').dropna()\n",
                    "        if len(corr_input) < 2:\n",
                    "            corr_value = np.nan\n",
                    "        else:\n",
                    "            corr_value = corr_input[x_channel].corr(corr_input[y_channel])\n",
                    "        if not isinstance(group_key, tuple):\n",
                    "            group_key = (group_key,)\n",
                    "        row = {group_cols[idx]: group_key[idx] for idx in range(len(group_cols))}\n",
                    "        row['correlation'] = corr_value\n",
                    "        rows.append(row)\n",
                    "    corr_df = pd.DataFrame(rows).dropna(subset=['correlation'])\n",
                    "    plt.figure(figsize=figsize)\n",
                    "    sns.barplot(data=corr_df, x=x, y='correlation', hue=hue)\n",
                    "    plt.ylim(-1.05, 1.05)\n",
                    "    plt.axhline(0, color='0.5', linestyle='--')\n",
                    "    plt.xticks(rotation=45, ha='right')\n",
                    "    plt.tight_layout()\n",
                ],
            },
            {
                "cell_type": "code",
                "execution_count": None,
                "metadata": {},
                "outputs": [],
                "source": [
                    "# Example: plot the first available percent-positive column\n",
                    "if pct_cols:\n",
                    "    plot_percent_positive(summary, pct_cols[0], x='sample_name')\n",
                ],
            },
            {
                "cell_type": "code",
                "execution_count": None,
                "metadata": {},
                "outputs": [],
                "source": [
                    "# Example: dose curve plot when dose metadata is assigned\n",
                    "if pct_cols and 'dose' in summary.columns:\n",
                    "    plot_dose_curve(summary, pct_cols[0])\n",
                ],
            },
            {
                "cell_type": "code",
                "execution_count": None,
                "metadata": {},
                "outputs": [],
                "source": [
                    "# Example: fluorescence intensity distribution for the first non-metadata channel\n",
                    "metadata_cols = {'well', 'source', 'sample_name', 'treatment_group', 'dose_curve', 'dose', 'replicate', 'sample_type', 'dose_direction', 'excluded'}\n",
                    "bool_cols = {c for c in intensity.columns if c.startswith('in_')}\n",
                    "channel_cols = [c for c in intensity.columns if c not in metadata_cols and c not in bool_cols]\n",
                    "channel_cols\n",
                ],
            },
            {
                "cell_type": "code",
                "execution_count": None,
                "metadata": {},
                "outputs": [],
                "source": [
                    "if channel_cols:\n",
                    "    plot_intensity_distribution(intensity, channel_cols[0])\n",
                ],
            },
            {
                "cell_type": "code",
                "execution_count": None,
                "metadata": {},
                "outputs": [],
                "source": [
                    "# Example: correlation between the first two fluorescence channels\n",
                    "if len(channel_cols) >= 2:\n",
                    "    plot_channel_correlation(intensity, channel_cols[0], channel_cols[1], x='sample_name')\n",
                ],
            },
        ]
        return {
            "cells": cells,
            "metadata": {
                "kernelspec": {
                    "display_name": "Python 3",
                    "language": "python",
                    "name": "python3",
                },
                "language_info": {"name": "python", "version": "3.10"},
            },
            "nbformat": 4,
            "nbformat_minor": 5,
        }

    def create_and_open_analysis_notebook(self):
        try:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            date_label = datetime.now().strftime("%Y-%m-%d")
            export_root = self._default_export_dir()
            export_dir = os.path.join(export_root, timestamp)
            os.makedirs(export_dir, exist_ok=True)

            summary_path = os.path.join(export_dir, "flow_gate_summary.csv")
            intensity_path = os.path.join(export_dir, "flow_intensity_distribution.csv")
            plate_path = os.path.join(export_dir, "plate_metadata.csv")
            notebook_filename = f"{date_label}_flow_desktop_analysis.ipynb"
            notebook_path = os.path.join(self._app_home(), notebook_filename)

            self._summary_dataframe().to_csv(summary_path, index=False)
            self._intensity_distribution_dataframe().to_csv(intensity_path, index=False)
            self._plate_metadata_dataframe().to_csv(plate_path, index=False)

            nb = self._analysis_notebook_dict(
                summary_relpath=os.path.relpath(summary_path, os.path.dirname(notebook_path)),
                intensity_relpath=os.path.relpath(intensity_path, os.path.dirname(notebook_path)),
                plate_relpath=os.path.relpath(plate_path, os.path.dirname(notebook_path)),
                notebook_title=f"{date_label} Flow Desktop Analysis",
            )
            with open(notebook_path, "w") as fh:
                json.dump(nb, fh, indent=1)

            self.gate_status_var.set(
                f"Saved notebook: {notebook_path} | "
                f"CSVs: {summary_path}, {intensity_path}, {plate_path}"
            )
        except Exception as exc:
            self.gate_status_var.set(f"Failed to create analysis notebook: {type(exc).__name__}: {exc}")

    def get_gate_specs(self):
        return list(self.gates)

    def get_flowjo_gates(self):
        return {gate["name"]: _build_flow_gate(gate) for gate in self.gates}

    def get_summary_dataframe(self):
        return self._summary_dataframe()

    def get_intensity_distribution_dataframe(self):
        return self._intensity_distribution_dataframe()

    def run(self):
        self.root.mainloop()


def launch_desktop_app(base_dir=None, instrument="Cytoflex", max_points=15000):
    app = FlowDesktopApp(base_dir=base_dir, instrument=instrument, max_points=max_points)
    app.run()
    return app


if __name__ == "__main__":
    launch_desktop_app()
