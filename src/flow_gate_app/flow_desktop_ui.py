import io
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import threading
from urllib.error import HTTPError
import urllib.request
import webbrowser
import zipfile
import traceback
from datetime import datetime

import numpy as np
import pandas as pd
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg, NavigationToolbar2Tk
from matplotlib.figure import Figure
from matplotlib.widgets import PolygonSelector
import tkinter as tk
from tkinter import colorchooser, filedialog, messagebox, simpledialog, ttk

try:
    from tkinterdnd2 import DND_FILES, TkinterDnD
except Exception:
    DND_FILES = None
    TkinterDnD = None

from ._app_version import __version__
from .analysis_views import (
    analysis_bundle_paths as _analysis_bundle_paths_impl,
    analysis_html_document as _analysis_html_document_impl,
    analysis_notebook_dict as _analysis_notebook_dict_impl,
    build_html_report_sections as _build_html_report_sections_impl,
    create_and_open_analysis_notebook as _create_and_open_analysis_notebook_impl,
    export_html_report as _export_html_report_impl,
    figure_to_base64 as _figure_to_base64_impl,
    html_error_section as _html_error_section_impl,
    html_img_tag as _html_img_tag_impl,
    open_analysis_preview as _open_analysis_preview_impl,
    write_analysis_bundle_csvs as _write_analysis_bundle_csvs_impl,
)
from .helpers import (
    APP_BRAND,
    DOWNLOADS_SUBDIR,
    GITHUB_LATEST_RELEASE_API,
    GITHUB_RELEASES_URL,
    PendingGate,
    apply_transform as _apply_transform,
    build_flow_gate as _build_flow_gate,
    event_adds_to_selection as _event_adds_to_selection,
    flow_tools as _flow_tools,
    gate_mask as _gate_mask,
    gate_plot_y_channel as _gate_plot_y_channel,
    get_channel_names as _get_channel_names,
    get_well_name as _get_well_name,
    is_count_axis as _is_count_axis,
    list_fcs_files as _list_fcs_files,
    normalize_version_tag as _normalize_version_tag,
    open_path as _open_path,
    platform_key as _platform_key,
    preferred_data_dir as _preferred_data_dir,
    render_gate as _render_gate,
    transform_array as _transform_array,
    version_key as _version_key,
)
from .plate_views import open_exclusion_editor as _open_exclusion_editor_impl
from .plate_views import open_plate_map_editor as _open_plate_map_editor_impl


_SNS = None
PRISM_AXIS_LINEWIDTH = 2.0
PRISM_LEGEND_LINEWIDTH = 1.8
ROBUST_AXIS_LOWER_Q = 0.01
ROBUST_AXIS_UPPER_Q = 0.99


def _sns():
    global _SNS
    if _SNS is None:
        import seaborn as sns
        _SNS = sns
    return _SNS


def _apply_prism_axis_style(ax):
    for side in ("left", "bottom"):
        if side in ax.spines:
            ax.spines[side].set_linewidth(PRISM_AXIS_LINEWIDTH)
            ax.spines[side].set_color("#111111")
    for side in ("top", "right"):
        if side in ax.spines:
            ax.spines[side].set_visible(False)
    ax.tick_params(axis="both", which="both", width=PRISM_AXIS_LINEWIDTH, length=6, color="#111111")


def _apply_prism_legend_style(ax):
    legend = ax.get_legend()
    if legend is None:
        return
    frame = legend.get_frame()
    frame.set_linewidth(PRISM_LEGEND_LINEWIDTH)
    frame.set_edgecolor("#111111")
    frame.set_facecolor("white")
    frame.set_alpha(1)


class FlowDesktopApp:
    def __init__(self, base_dir=None, instrument="Cytoflex", max_points=15000):
        self.base_dir = base_dir or os.getcwd()
        self.max_points_default = int(max_points)
        self.root = TkinterDnD.Tk() if TkinterDnD is not None else tk.Tk()
        self.root.title(f"{APP_BRAND} v{__version__}")
        self.root.geometry("1440x840")

        self.home_folder = self._load_home_folder()
        initial_folder = self.home_folder or self.base_dir

        self.folder_var = tk.StringVar(value=initial_folder)
        self.instrument_var = tk.StringVar(value=instrument)
        self.population_var = tk.StringVar(value="__all__")
        self.x_var = tk.StringVar()
        self.y_var = tk.StringVar()
        self.x_transform_var = tk.StringVar(value="arcsinh")
        self.x_cofactor_var = tk.DoubleVar(value=150.0)
        self.y_transform_var = tk.StringVar(value="arcsinh")
        self.y_cofactor_var = tk.DoubleVar(value=150.0)
        self.max_points_var = tk.IntVar(value=self.max_points_default)
        self.hist_bins_var = tk.IntVar(value=100)
        self.y_plot_mode_var = tk.StringVar(value="scatter")
        self.compensation_enabled = tk.BooleanVar(value=False)
        self.compensation_source_channels = []
        self.compensation_channels = []
        self.compensation_matrix = None
        self.compensation_text = ""
        self.scatter_xmin_override = None
        self.scatter_xmax_override = None
        self.scatter_ymin_override = None
        self.scatter_ymax_override = None
        self.gate_type_var = tk.StringVar(value="polygon")
        self.gate_name_var = tk.StringVar(value="gate_1")
        self.quad_region_var = tk.StringVar(value="top right")
        self.threshold_region_var = tk.StringVar(value="above")
        self.mode_var = tk.StringVar(value="idle")
        self.status_var = tk.StringVar(value="Choose a folder and click Load Folder.")
        self.gate_status_var = tk.StringVar(value="")
        self.version_var = tk.StringVar(value=f"Version {__version__}")
        self.autosave_var = tk.StringVar(value="Autosave: idle")
        self.heatmap_mode_var = tk.StringVar(value="percent")
        self.heatmap_metric_var = tk.StringVar(value="")
        self.heatmap_population_var = tk.StringVar(value="__all__")
        self.heatmap_channel_var = tk.StringVar(value="")
        self.heatmap_channel_y_var = tk.StringVar(value="")
        self.heatmap_title_var = tk.StringVar(value="")
        self.recent_session_var = tk.StringVar(value="")
        self.drop_status_var = tk.StringVar(value="")

        self.file_map = {}
        self.sample_cache = {}
        self._selected_raw_cache = {}
        self._population_raw_cache = {}
        self._sample_population_cache = {}
        self._display_cache = {}
        self._summary_cache = None
        self._intensity_cache = None
        self.channel_names = []
        self.gates = []
        self.plate_metadata = {}
        self.dose_curve_definitions = {}
        self.saved_gate_labels = {}
        self.population_labels = {"All Events": "__all__"}
        self.heatmap_population_labels = {"All Events": "__all__"}
        self.plate_overview_hitboxes = {}
        self.plate_tooltip = None
        self.plate_tooltip_label = None
        self.plate_hovered_well = None
        self.pending_gate = None
        self.rectangle_start_point = None
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
        self.undo_stack = []
        self.redo_stack = []
        self.history_limit = 40
        self.suspend_history = False
        self.autosave_after_id = None
        self.last_session_path = self._last_session_path()
        self._load_request_id = 0

        self.figure = Figure(figsize=(8, 7), dpi=100)
        self.ax = self.figure.add_subplot(111)
        self.heatmap_figure = Figure(figsize=(8, 3.8), dpi=100)
        self.heatmap_ax = self.heatmap_figure.add_subplot(111)

        self._init_styles()
        self._build_ui()
        self._update_compensation_status()
        self.root.after_idle(self._set_initial_pane_sizes)
        self._refresh_recent_sessions()
        self._bind_events()
        self.root.protocol("WM_DELETE_WINDOW", self._on_close_request)
        self._update_gate_mode_visibility()
        self._autoload_last_session_or_folder(base_dir)

    def _init_styles(self):
        self.style = ttk.Style(self.root)
        self.style.configure("Section.TLabelframe.Label", font=("TkDefaultFont", 10, "bold"))

    def _set_initial_pane_sizes(self):
        try:
            total_height = max(self.right_pane.winfo_height(), 600)
            self.right_pane.sashpos(0, int(total_height * 0.52))
            self.right_pane.sashpos(1, int(total_height * 0.78))
        except Exception:
            pass

    def _panel_button(self, parent, text, command, bg, fg="#1d1d1f", **grid_kwargs):
        if _platform_key() == "windows":
            button = ttk.Button(parent, text=text, command=command)
            if grid_kwargs:
                button.grid(**grid_kwargs)
            return button
        button = tk.Button(
            parent,
            text=text,
            command=command,
            bg=bg,
            fg=fg,
            activebackground=bg,
            activeforeground=fg,
            relief="flat",
            borderwidth=0,
            highlightthickness=0,
            padx=10,
            pady=6,
        )
        if grid_kwargs:
            button.grid(**grid_kwargs)
        return button

    def _accent_button(self, parent, text, command, bg, fg="#1d1d1f", **grid_kwargs):
        return self._panel_button(parent, text, command, bg=bg, fg=fg, **grid_kwargs)

    def _secondary_button(self, parent, text, command, **grid_kwargs):
        return self._panel_button(parent, text, command, bg="#3c4353", fg="#1d1d1f", **grid_kwargs)

    def _build_ui(self):
        self.root.columnconfigure(1, weight=1)
        self.root.rowconfigure(0, weight=1)

        left_outer = ttk.Frame(self.root, padding=10)
        left_outer.grid(row=0, column=0, sticky="nsw")
        left_outer.rowconfigure(0, weight=1)
        left_outer.columnconfigure(0, weight=1)

        left_canvas = tk.Canvas(left_outer, width=560, highlightthickness=0)
        left_scroll = ttk.Scrollbar(left_outer, orient="vertical", command=left_canvas.yview)
        left_canvas.configure(yscrollcommand=left_scroll.set)
        left_canvas.grid(row=0, column=0, sticky="nsw")
        left_scroll.grid(row=0, column=1, sticky="ns")

        left = ttk.Frame(left_canvas, padding=0)
        left_window = left_canvas.create_window((0, 0), window=left, anchor="nw")
        left.columnconfigure(0, weight=1)

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
        right.rowconfigure(0, weight=1)
        right_canvas = tk.Canvas(right, highlightthickness=0)
        right_scroll = ttk.Scrollbar(right, orient="vertical", command=right_canvas.yview)
        right_canvas.configure(yscrollcommand=right_scroll.set)
        right_canvas.grid(row=0, column=0, sticky="nsew")
        right_scroll.grid(row=0, column=1, sticky="ns")

        right_inner = ttk.Frame(right_canvas)
        right_window = right_canvas.create_window((0, 0), window=right_inner, anchor="nw")
        right_inner.columnconfigure(0, weight=1)
        right_inner.rowconfigure(0, weight=1)

        def _sync_right_scroll(_event=None):
            right_canvas.configure(scrollregion=right_canvas.bbox("all"))
            right_canvas.itemconfigure(right_window, width=right_canvas.winfo_width())

        right_inner.bind("<Configure>", _sync_right_scroll)
        right_canvas.bind("<Configure>", _sync_right_scroll)

        def _on_right_mousewheel(event):
            right_canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")

        right_canvas.bind("<MouseWheel>", _on_right_mousewheel)

        self.right_pane = ttk.Panedwindow(right_inner, orient=tk.VERTICAL)
        self.right_pane.grid(row=0, column=0, sticky="nsew")

        def section(parent, title):
            frame = ttk.LabelFrame(parent, text=title, padding=(10, 8), style="Section.TLabelframe")
            frame.pack(fill="x", expand=True, pady=(0, 10))
            return frame

        def config_grid(frame, cols):
            for idx in range(cols):
                frame.columnconfigure(idx, weight=1)

        data_frame = section(left, "Data")
        config_grid(data_frame, 3)
        ttk.Label(data_frame, text="Folder").grid(row=0, column=0, columnspan=3, sticky="w")
        ttk.Entry(data_frame, textvariable=self.folder_var, width=52).grid(row=1, column=0, columnspan=3, sticky="ew", pady=(0, 6))
        self._secondary_button(data_frame, "Browse", self.browse_folder, row=2, column=0, sticky="ew")
        ttk.Combobox(data_frame, textvariable=self.instrument_var, values=["Cytoflex", "Symphony"], state="readonly", width=14).grid(row=2, column=1, sticky="ew", padx=4)
        self._accent_button(data_frame, "Load Folder", self.load_folder, bg="#4869d6", fg="#1d1d1f", row=2, column=2, sticky="ew")
        self._secondary_button(data_frame, "Set Home", self.set_home_folder, row=3, column=0, sticky="ew", pady=(6, 0))
        ttk.Label(data_frame, textvariable=self._home_folder_label_textvar(), wraplength=470).grid(row=3, column=1, columnspan=2, sticky="w", padx=(8, 0), pady=(8, 0))
        self.drop_target_label = tk.Label(
            data_frame,
            text="Drop folders, sessions, or gate templates here",
            bg="#e8eefc" if DND_FILES is not None else "#eff1f5",
            fg="#1d1d1f",
            relief="groove",
            borderwidth=1,
            padx=10,
            pady=10,
            anchor="center",
        )
        self.drop_target_label.grid(row=4, column=0, columnspan=3, sticky="ew", pady=(10, 0))
        ttk.Label(data_frame, textvariable=self.drop_status_var, wraplength=470).grid(row=5, column=0, columnspan=3, sticky="w", pady=(6, 0))
        ttk.Label(data_frame, text="Wells").grid(row=6, column=0, columnspan=3, sticky="w", pady=(10, 0))
        self.well_listbox = tk.Listbox(data_frame, selectmode=tk.EXTENDED, width=48, height=12, exportselection=False)
        self.well_listbox.grid(row=7, column=0, columnspan=3, sticky="ew")
        self._secondary_button(data_frame, "Compensation", self.open_compensation_editor, row=8, column=0, sticky="ew", pady=(8, 0))
        self.compensation_status_var = tk.StringVar(value="Compensation: off")
        ttk.Label(data_frame, textvariable=self.compensation_status_var, wraplength=470).grid(row=8, column=1, columnspan=2, sticky="w", padx=(8, 0), pady=(10, 0))

        plot_frame = section(left, "Plot")
        config_grid(plot_frame, 4)
        ttk.Label(plot_frame, text="Population").grid(row=0, column=0, sticky="w")
        ttk.Label(plot_frame, text="Max Points").grid(row=0, column=1, sticky="w")
        ttk.Label(plot_frame, text="").grid(row=0, column=2, sticky="w")
        ttk.Label(plot_frame, text="").grid(row=0, column=3, sticky="w")
        self.population_combo = ttk.Combobox(plot_frame, textvariable=self.population_var, state="readonly", width=22)
        self.population_combo.grid(row=1, column=0, sticky="ew")
        ttk.Spinbox(plot_frame, from_=1000, to=50000, increment=1000, textvariable=self.max_points_var, width=10).grid(row=1, column=1, sticky="ew", padx=4)
        self.plot_button = self._accent_button(plot_frame, "Plot Population", self.plot_population, bg="#4869d6", fg="#1d1d1f", row=1, column=2, sticky="ew")
        ttk.Label(plot_frame, text="X Axis").grid(row=2, column=0, sticky="w", pady=(10, 0))
        ttk.Label(plot_frame, text="Y Axis").grid(row=2, column=1, sticky="w", pady=(10, 0))
        ttk.Label(plot_frame, text="Plot Mode").grid(row=2, column=2, sticky="w", pady=(10, 0))
        self.x_combo = ttk.Combobox(plot_frame, textvariable=self.x_var, state="readonly", width=20)
        self.x_combo.grid(row=3, column=0, sticky="ew")
        self.y_combo = ttk.Combobox(plot_frame, textvariable=self.y_var, state="readonly", width=20)
        self.y_combo.grid(row=3, column=1, sticky="ew", padx=4)
        ttk.Combobox(plot_frame, textvariable=self.y_plot_mode_var, values=["scatter", "count histogram"], state="readonly", width=16).grid(row=3, column=2, sticky="ew")
        ttk.Label(plot_frame, text="X Transform").grid(row=4, column=0, sticky="w", pady=(10, 0))
        ttk.Label(plot_frame, text="X Cofactor").grid(row=4, column=1, sticky="w", pady=(10, 0))
        ttk.Label(plot_frame, text="Y Transform").grid(row=4, column=2, sticky="w", pady=(10, 0))
        ttk.Label(plot_frame, text="Y Cofactor").grid(row=4, column=3, sticky="w", pady=(10, 0))
        ttk.Combobox(plot_frame, textvariable=self.x_transform_var, values=["linear", "log10", "arcsinh"], state="readonly", width=15).grid(row=5, column=0, sticky="ew")
        ttk.Spinbox(plot_frame, from_=1.0, to=10000.0, increment=10.0, textvariable=self.x_cofactor_var, width=12).grid(row=5, column=1, sticky="ew", padx=4)
        ttk.Combobox(plot_frame, textvariable=self.y_transform_var, values=["linear", "log10", "arcsinh"], state="readonly", width=15).grid(row=5, column=2, sticky="ew")
        ttk.Spinbox(plot_frame, from_=1.0, to=10000.0, increment=10.0, textvariable=self.y_cofactor_var, width=12).grid(row=5, column=3, sticky="ew", padx=4)
        self._secondary_button(plot_frame, "Graph Options", self.open_graph_options_dialog, row=6, column=2, columnspan=2, sticky="ew", pady=(8, 0))

        gate_frame = section(left, "Gating")
        config_grid(gate_frame, 3)
        ttk.Label(gate_frame, text="Gate Type").grid(row=0, column=0, sticky="w")
        ttk.Label(gate_frame, text="Gate Name").grid(row=0, column=1, sticky="w")
        ttk.Label(gate_frame, text="Threshold / Region").grid(row=0, column=2, sticky="w")
        ttk.Combobox(gate_frame, textvariable=self.gate_type_var, values=["polygon", "rectangle", "quad", "vertical", "horizontal"], state="readonly", width=15).grid(row=1, column=0, sticky="ew")
        ttk.Entry(gate_frame, textvariable=self.gate_name_var, width=18).grid(row=1, column=1, sticky="ew", padx=4)
        mode_detail = ttk.Frame(gate_frame)
        mode_detail.grid(row=1, column=2, sticky="ew")
        mode_detail.columnconfigure(0, weight=1)
        self.quad_region_combo = ttk.Combobox(mode_detail, textvariable=self.quad_region_var, values=["top right", "top left", "bottom right", "bottom left"], state="readonly", width=15)
        self.quad_region_combo.grid(row=0, column=0, sticky="ew")
        self.threshold_region_combo = ttk.Combobox(mode_detail, textvariable=self.threshold_region_var, values=["above", "below"], state="readonly", width=15)
        self.threshold_region_combo.grid(row=0, column=0, sticky="ew")
        self.start_draw_button = self._accent_button(gate_frame, "Start Drawing", self.start_drawing, bg="#3f7f4d", fg="#1d1d1f", row=2, column=0, sticky="ew", pady=(8, 0))
        self._secondary_button(gate_frame, "Clear Pending", self.clear_pending, row=2, column=1, sticky="ew", padx=4, pady=(8, 0))
        self._accent_button(gate_frame, "Save Gate", self.save_gate, bg="#2f8c74", fg="#1d1d1f", row=2, column=2, sticky="ew", pady=(8, 0))
        ttk.Label(gate_frame, text="Saved Gates").grid(row=3, column=0, columnspan=3, sticky="w", pady=(10, 0))
        self.saved_gate_listbox = tk.Listbox(gate_frame, selectmode=tk.SINGLE, width=48, height=8, exportselection=False)
        self.saved_gate_listbox.grid(row=4, column=0, columnspan=3, sticky="ew")
        ttk.Label(gate_frame, text="Gate Percentages By Well").grid(row=5, column=0, columnspan=3, sticky="w", pady=(8, 0))
        self.gate_summary_text = tk.Text(gate_frame, width=52, height=5, wrap="word")
        self.gate_summary_text.grid(row=6, column=0, columnspan=3, sticky="ew")
        self.gate_summary_text.configure(state="disabled")
        ttk.Label(gate_frame, text="Gate Statistics").grid(row=7, column=0, columnspan=3, sticky="w", pady=(8, 0))
        self.gate_stats_text = tk.Text(gate_frame, width=52, height=6, wrap="word")
        self.gate_stats_text.grid(row=8, column=0, columnspan=3, sticky="ew")
        self.gate_stats_text.configure(state="disabled")
        gate_actions = ttk.Frame(gate_frame)
        gate_actions.grid(row=9, column=0, columnspan=3, sticky="ew", pady=(8, 0))
        for idx in range(3):
            gate_actions.columnconfigure(idx, weight=1)
        self._secondary_button(gate_actions, "Delete Gate", self.delete_gate, row=0, column=0, sticky="ew")
        self._secondary_button(gate_actions, "Rename Gate", self.rename_selected_gate, row=0, column=1, sticky="ew", padx=(6, 0))
        self._secondary_button(gate_actions, "Set Color", self.recolor_selected_gate, row=0, column=2, sticky="ew", padx=(6, 0))
        self._secondary_button(gate_actions, "Save Template", self.save_gate_template, row=1, column=0, columnspan=2, sticky="ew", pady=(6, 0))
        self._secondary_button(gate_actions, "Load Template", self.load_gate_template, row=1, column=2, sticky="ew", padx=(6, 0), pady=(6, 0))

        analysis_frame = section(left, "Analysis And Export")
        config_grid(analysis_frame, 2)
        self._secondary_button(analysis_frame, "Analysis Preview", self.open_analysis_preview, row=0, column=0, sticky="ew")
        self._accent_button(analysis_frame, "Export HTML Report", self.export_html_report, bg="#8c6a2f", fg="#1d1d1f", row=0, column=1, sticky="ew", padx=(6, 0))
        self._secondary_button(analysis_frame, "Open Analysis Notebook", self.create_and_open_analysis_notebook, row=1, column=0, sticky="ew", pady=(6, 0))
        self._secondary_button(analysis_frame, "Plate Map", self.open_plate_map_editor, row=1, column=1, sticky="ew", padx=(6, 0), pady=(6, 0))
        self._secondary_button(analysis_frame, "Excluded Wells", self.open_exclusion_editor, row=2, column=0, sticky="ew", pady=(6, 0))
        self._secondary_button(analysis_frame, "Export Summary CSV", self.export_gate_summary_csv, row=2, column=1, sticky="ew", padx=(6, 0), pady=(6, 0))
        self._secondary_button(analysis_frame, "Export Intensities CSV", self.export_intensity_csv, row=3, column=0, sticky="ew", pady=(6, 0))

        session_frame = section(left, "Session")
        config_grid(session_frame, 2)
        self._secondary_button(session_frame, "Undo", self.undo_last_change, row=0, column=0, sticky="ew")
        self._secondary_button(session_frame, "Redo", self.redo_last_change, row=0, column=1, sticky="ew", padx=(6, 0))
        self._secondary_button(session_frame, "Save Session", self.save_session, row=1, column=0, sticky="ew", pady=(6, 0))
        self._secondary_button(session_frame, "Load Session", self.load_session, row=1, column=1, sticky="ew", padx=(6, 0), pady=(6, 0))
        self.recent_session_combo = ttk.Combobox(session_frame, textvariable=self.recent_session_var, state="readonly", width=40)
        self.recent_session_combo.grid(row=2, column=0, sticky="ew", pady=(6, 0))
        self._secondary_button(session_frame, "Open Recent", self.load_recent_session, row=2, column=1, sticky="ew", padx=(6, 0), pady=(6, 0))
        self._secondary_button(session_frame, "Check for Updates", self.check_for_updates, row=3, column=0, sticky="ew", pady=(6, 0))
        ttk.Label(session_frame, textvariable=self.version_var).grid(row=3, column=1, sticky="w", padx=(8, 0), pady=(6, 0))
        ttk.Label(session_frame, textvariable=self.autosave_var, wraplength=470).grid(row=4, column=0, columnspan=2, sticky="w", pady=(6, 0))

        status_frame = section(left, "Status")
        ttk.Label(status_frame, textvariable=self.mode_var, wraplength=470).pack(anchor="w")
        ttk.Label(status_frame, textvariable=self.status_var, wraplength=470).pack(anchor="w", pady=(6, 0))
        ttk.Label(status_frame, textvariable=self.gate_status_var, wraplength=470).pack(anchor="w", pady=(6, 0))

        plot_panel = ttk.Frame(self.right_pane, padding=(0, 0, 0, 6))
        plot_panel.columnconfigure(0, weight=1)
        plot_panel.rowconfigure(1, weight=1)
        ttk.Label(plot_panel, text="Interactive Plot").grid(row=0, column=0, sticky="w")
        canvas_frame = ttk.Frame(plot_panel)
        canvas_frame.grid(row=1, column=0, sticky="nsew")
        canvas_frame.columnconfigure(0, weight=1)
        canvas_frame.rowconfigure(0, weight=1)

        self.canvas = FigureCanvasTkAgg(self.figure, master=canvas_frame)
        self.canvas.get_tk_widget().grid(row=0, column=0, sticky="nsew")
        toolbar = NavigationToolbar2Tk(self.canvas, canvas_frame, pack_toolbar=False)
        toolbar.update()
        toolbar.grid(row=1, column=0, sticky="ew")

        heatmap_panel = ttk.Frame(self.right_pane, padding=(0, 0, 0, 6))
        heatmap_panel.columnconfigure(0, weight=1)
        heatmap_panel.rowconfigure(1, weight=1)
        heatmap_controls = ttk.Frame(heatmap_panel)
        heatmap_controls.grid(row=0, column=0, sticky="ew", pady=(0, 4))
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
        ttk.Label(heatmap_controls, text="Title").grid(row=1, column=0, sticky="w", pady=(8, 0))
        ttk.Entry(heatmap_controls, textvariable=self.heatmap_title_var, width=40).grid(row=1, column=1, columnspan=3, sticky="ew", padx=8, pady=(8, 0))
        self._secondary_button(heatmap_controls, "Save Heatmap", self.save_heatmap, row=1, column=4, sticky="w", padx=8, pady=(8, 0))
        self.heatmap_title_var.trace_add("write", lambda *_: self.update_heatmap())
        self._update_heatmap_control_visibility()

        heatmap_frame = ttk.Frame(heatmap_panel)
        heatmap_frame.grid(row=1, column=0, sticky="nsew")
        heatmap_frame.columnconfigure(0, weight=1)
        heatmap_frame.rowconfigure(0, weight=1)
        self.heatmap_canvas = FigureCanvasTkAgg(self.heatmap_figure, master=heatmap_frame)
        self.heatmap_canvas.get_tk_widget().grid(row=0, column=0, sticky="nsew")

        plate_panel = ttk.Frame(self.right_pane, padding=(0, 0, 0, 0))
        plate_panel.columnconfigure(0, weight=1)
        plate_panel.rowconfigure(1, weight=1)
        ttk.Label(plate_panel, text="Plate Layout").grid(row=0, column=0, sticky="w", pady=(0, 4))
        plate_frame = ttk.Frame(plate_panel)
        plate_frame.grid(row=1, column=0, sticky="nsew")
        plate_frame.columnconfigure(0, weight=1)
        plate_frame.rowconfigure(0, weight=1)
        self.plate_overview_canvas = tk.Canvas(
            plate_frame,
            width=860,
            height=270,
            bg="#11151e",
            highlightthickness=0,
        )
        self.plate_overview_canvas.grid(row=0, column=0, sticky="nsew")
        self.plate_overview_canvas.bind("<Motion>", self._on_plate_overview_motion)
        self.plate_overview_canvas.bind("<Leave>", self._on_plate_overview_leave)
        self.plate_overview_canvas.bind("<Configure>", lambda _e: self.update_plate_overview())
        self.right_pane.add(plot_panel, weight=6)
        self.right_pane.add(heatmap_panel, weight=3)
        self.right_pane.add(plate_panel, weight=2)
        self.update_plate_overview()
        self._init_drop_target()

    def _bind_events(self):
        self.gate_type_var.trace_add("write", lambda *_: self._update_gate_mode_visibility())
        self.x_transform_var.trace_add("write", lambda *_: self._auto_plot_if_ready())
        self.x_cofactor_var.trace_add("write", lambda *_: self._auto_plot_if_ready())
        self.y_transform_var.trace_add("write", lambda *_: self._auto_plot_if_ready())
        self.y_cofactor_var.trace_add("write", lambda *_: self._auto_plot_if_ready())
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

    def _init_drop_target(self):
        if DND_FILES is None or TkinterDnD is None:
            self.drop_status_var.set("Install tkinterdnd2 to enable drag and drop.")
            return
        try:
            self.drop_target_label.drop_target_register(DND_FILES)
            self.drop_target_label.dnd_bind("<<DropEnter>>", self._on_drop_enter)
            self.drop_target_label.dnd_bind("<<DropLeave>>", self._on_drop_leave)
            self.drop_target_label.dnd_bind("<<Drop>>", self._on_drop_files)
            self.drop_status_var.set("Drag a folder, session JSON, or gate template JSON into this box.")
        except Exception as exc:
            self.drop_status_var.set(f"Drag and drop unavailable: {type(exc).__name__}: {exc}")

    def _drop_target_style(self, active=False):
        self.drop_target_label.configure(bg="#cfe0ff" if active else "#e8eefc")

    def _on_drop_enter(self, _event):
        self._drop_target_style(active=True)
        return "copy"

    def _on_drop_leave(self, _event):
        self._drop_target_style(active=False)
        return "copy"

    def _parse_drop_paths(self, data):
        if not data:
            return []
        try:
            paths = list(self.root.tk.splitlist(data))
        except Exception:
            paths = shlex.split(data)
        out = []
        for path in paths:
            cleaned = str(path).strip().strip("{}").strip()
            if cleaned:
                out.append(cleaned)
        return out

    def _load_dropped_path(self, path):
        if os.path.isdir(path):
            self.folder_var.set(path)
            self.drop_status_var.set(f"Dropped folder: {path}")
            self.load_folder()
            return True
        if not os.path.isfile(path):
            raise ValueError(f"Path not found: {path}")
        if not path.lower().endswith(".json"):
            raise ValueError("Drop a folder, session JSON, or gate template JSON.")
        with open(path) as fh:
            payload = json.load(fh)
        if payload.get("template_type") == "flow_gate_template":
            self._load_gate_template_from_path(path, payload=payload)
            self.drop_status_var.set(f"Loaded gate template: {os.path.basename(path)}")
            return True
        self._load_session_from_path(path, payload=payload)
        self.drop_status_var.set(f"Loaded session: {os.path.basename(path)}")
        return True

    def _on_drop_files(self, event):
        self._drop_target_style(active=False)
        paths = self._parse_drop_paths(getattr(event, "data", ""))
        if not paths:
            self.drop_status_var.set("Nothing was dropped.")
            return "copy"
        try:
            self._load_dropped_path(paths[0])
            if len(paths) > 1:
                self.drop_status_var.set(f"Loaded first dropped item and ignored {len(paths) - 1} extra item(s).")
        except Exception as exc:
            self.drop_status_var.set(f"Drop failed: {type(exc).__name__}: {exc}")
        return "copy"

    def _auto_plot_if_ready(self):
        if self.file_map and self.x_var.get() and self.y_var.get():
            self.plot_population()

    def _plot_x_transform(self):
        return self.x_transform_var.get()

    def _plot_x_cofactor(self):
        return float(self.x_cofactor_var.get())

    def _plot_y_transform(self):
        return self.y_transform_var.get()

    def _plot_y_cofactor(self):
        return float(self.y_cofactor_var.get())

    def _gate_x_transform(self, gate):
        return gate.get("x_transform", gate.get("transform", "arcsinh"))

    def _gate_x_cofactor(self, gate):
        return float(gate.get("x_cofactor", gate.get("cofactor", 150.0)))

    def _gate_y_transform(self, gate):
        return gate.get("y_transform", gate.get("transform", "arcsinh"))

    def _gate_y_cofactor(self, gate):
        return float(gate.get("y_cofactor", gate.get("cofactor", 150.0)))

    def _population_display_parts(self, name):
        if name == "__all__":
            return ["All Events"]
        if self._is_boolean_population(name):
            parent_name, gate_names = self._boolean_population_spec(name)
            parent_parts = self._population_display_parts(parent_name)
            return parent_parts + [" AND ".join(gate_names)]
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

    def _plate_badge_text(self, sample_name):
        text = str(sample_name or "").strip()
        if not text:
            return ""
        parts = [part for part in re.split(r"[\s_\-]+", text) if part]
        if len(parts) >= 2:
            token = "".join(part[0] for part in parts[:3]).upper()
            if len(token) >= 2:
                return token[:4]
        compact = re.sub(r"[^A-Za-z0-9]", "", text)
        if compact:
            return compact[:4].upper()
        return text[:4].upper()

    def _plate_badge_color(self, sample_name):
        text = str(sample_name or "").strip()
        if not text:
            return "#2a3140"
        palette = [
            "#4f7cff",
            "#2f8c74",
            "#a56ad8",
            "#c77d2b",
            "#cc5f7a",
            "#3d97b8",
            "#7a9c34",
            "#b85c2e",
        ]
        return palette[abs(hash(text)) % len(palette)]

    def _plate_overview_tooltip_text(self, well, has_fcs, metadata):
        lines = [well]
        sample_name = str(metadata.get("sample_name", "")).strip()
        if sample_name:
            lines.append(f"Sample: {sample_name}")
        if metadata.get("dose_curve"):
            lines.append(f"Dose curve: {metadata.get('dose_curve')}")
        if metadata.get("dose") not in (None, ""):
            lines.append(f"Dose: {metadata.get('dose')}")
        if metadata.get("replicate") not in (None, ""):
            lines.append(f"Replicate: {metadata.get('replicate')}")
        if metadata.get("dose_direction"):
            lines.append(f"Direction: {metadata.get('dose_direction')}")
        lines.append(f"FCS file: {'yes' if has_fcs else 'no'}")
        if metadata.get("excluded", False):
            lines.append("Excluded from downstream analysis")
        return "\n".join(lines)

    def _show_plate_tooltip(self, x_root, y_root, text):
        if self.plate_tooltip is None or not self.plate_tooltip.winfo_exists():
            tooltip = tk.Toplevel(self.root)
            tooltip.withdraw()
            tooltip.overrideredirect(True)
            tooltip.attributes("-topmost", True)
            label = tk.Label(
                tooltip,
                text=text,
                justify="left",
                bg="#1c2230",
                fg="#f3f6fb",
                relief="solid",
                borderwidth=1,
                padx=8,
                pady=6,
            )
            label.pack()
            self.plate_tooltip = tooltip
            self.plate_tooltip_label = label
        else:
            self.plate_tooltip_label.configure(text=text)
        self.plate_tooltip.geometry(f"+{x_root + 14}+{y_root + 14}")
        self.plate_tooltip.deiconify()

    def _hide_plate_tooltip(self):
        if self.plate_tooltip is not None and self.plate_tooltip.winfo_exists():
            self.plate_tooltip.withdraw()
        self.plate_hovered_well = None

    def _on_plate_overview_motion(self, event):
        canvas = getattr(self, "plate_overview_canvas", None)
        if canvas is None:
            return
        hit = None
        for well, payload in self.plate_overview_hitboxes.items():
            x0, y0, x1, y1 = payload["bbox"]
            if x0 <= event.x <= x1 and y0 <= event.y <= y1:
                hit = (well, payload)
                break
        if hit is None:
            self._hide_plate_tooltip()
            return
        well, payload = hit
        text = self._plate_overview_tooltip_text(well, payload["has_fcs"], payload["metadata"])
        if self.plate_hovered_well != well:
            self.plate_hovered_well = well
            self._show_plate_tooltip(event.x_root, event.y_root, text)
        else:
            self._show_plate_tooltip(event.x_root, event.y_root, text)

    def _on_plate_overview_leave(self, _event):
        self._hide_plate_tooltip()

    def update_plate_overview(self):
        canvas = getattr(self, "plate_overview_canvas", None)
        if canvas is None:
            return

        canvas.delete("all")
        self.plate_overview_hitboxes = {}
        self._hide_plate_tooltip()
        width = max(canvas.winfo_width(), int(canvas.cget("width")))
        height = max(canvas.winfo_height(), int(canvas.cget("height")))
        margin_x = 34
        margin_y = 28
        step_x = max((width - margin_x - 24) / 12.0, 32)
        step_y = max((height - margin_y - 44) / 8.0, 22)
        radius = max(min(step_x, step_y) * 0.28, 8)
        row_names = "ABCDEFGH"
        available_wells = {_get_well_name(relpath, self.instrument_var.get()) for relpath in self.file_map.values()}

        canvas.create_text(
            12,
            10,
            anchor="nw",
            text="Live sample layout",
            fill="#d9dee8",
            font=("TkDefaultFont", 10, "bold"),
        )
        canvas.create_text(
            width - 12,
            10,
            anchor="ne",
            text="filled = assigned sample, outline = FCS present, X = excluded",
            fill="#9aa4b2",
            font=("TkDefaultFont", 9),
        )

        for col in range(12):
            x = margin_x + (col + 0.5) * step_x
            canvas.create_text(x, margin_y, text=str(col + 1), fill="#c4ccd8", font=("TkDefaultFont", 9, "bold"))
        for row_idx, row_name in enumerate(row_names):
            y = margin_y + 22 + (row_idx + 0.5) * step_y
            canvas.create_text(18, y, text=row_name, fill="#c4ccd8", font=("TkDefaultFont", 9, "bold"))
            for col_idx in range(12):
                well = f"{row_name}{col_idx + 1}"
                x = margin_x + (col_idx + 0.5) * step_x
                metadata = self.plate_metadata.get(well, {})
                sample_name = metadata.get("sample_name", "")
                excluded = bool(metadata.get("excluded", False))
                has_fcs = well in available_wells
                fill = "#1a1f2b"
                outline = "#515d73"
                text_fill = "#dbe4f1"
                if has_fcs:
                    outline = "#d5dde9"
                    fill = "#242c39"
                if sample_name:
                    fill = self._plate_badge_color(sample_name)
                    outline = "#eff4fb"
                    text_fill = "#f7fbff"
                if excluded:
                    fill = "#5a6679" if has_fcs else "#394354"
                    outline = "#ffb1b1"
                    text_fill = "#fff5f5"

                canvas.create_oval(
                    x - radius,
                    y - radius,
                    x + radius,
                    y + radius,
                    fill=fill,
                    outline=outline,
                    width=2 if has_fcs else 1,
                )
                badge = self._plate_badge_text(sample_name)
                if badge:
                    canvas.create_text(x, y, text=badge, fill=text_fill, font=("TkDefaultFont", max(int(radius * 0.65), 7), "bold"))
                elif has_fcs:
                    canvas.create_text(x, y, text=well, fill="#dbe4f1", font=("TkDefaultFont", max(int(radius * 0.55), 6)))
                else:
                    canvas.create_text(x, y, text=".", fill="#617087", font=("TkDefaultFont", max(int(radius * 0.6), 7)))
                if excluded:
                    canvas.create_line(x - 6, y - 6, x + 6, y + 6, fill="#ffd5d5", width=2)
                    canvas.create_line(x - 6, y + 6, x + 6, y - 6, fill="#ffd5d5", width=2)
                self.plate_overview_hitboxes[well] = {
                    "bbox": (x - radius - 4, y - radius - 4, x + radius + 4, y + radius + 4),
                    "metadata": dict(metadata),
                    "has_fcs": has_fcs,
                }

        assigned = sum(1 for meta in self.plate_metadata.values() if meta.get("sample_name"))
        excluded = sum(1 for meta in self.plate_metadata.values() if meta.get("excluded"))
        available = len(available_wells)
        canvas.create_text(
            12,
            height - 10,
            anchor="sw",
            text=f"FCS wells: {available}    assigned: {assigned}    excluded: {excluded}",
            fill="#9aa4b2",
            font=("TkDefaultFont", 9),
        )

    def _boolean_population_name(self, parent_name, gate_names):
        return f"__bool__::{parent_name}::{'&&'.join(gate_names)}"

    def _is_boolean_population(self, name):
        return isinstance(name, str) and name.startswith("__bool__::")

    def _boolean_population_spec(self, name):
        if not self._is_boolean_population(name):
            return None, []
        remainder = name[len("__bool__::"):]
        parent_name, gates_part = remainder.split("::", 1)
        gate_names = [item for item in gates_part.split("&&") if item]
        return parent_name, gate_names

    def _boolean_population_defs(self):
        defs = []
        sibling_groups = {}
        fluorescent = {gate["name"]: gate for gate in self._fluorescence_gates()}
        for gate in self.gates:
            if gate["name"] not in fluorescent:
                continue
            sibling_groups.setdefault(gate["parent_population"], []).append(gate)
        for parent_name, group in sibling_groups.items():
            group = sorted(group, key=lambda g: g["name"])
            for idx in range(len(group)):
                for jdx in range(idx + 1, len(group)):
                    first = group[idx]
                    second = group[jdx]
                    if first["name"] == second["name"]:
                        continue
                    if first["x_channel"] == second["x_channel"] and first.get("y_channel") == second.get("y_channel"):
                        continue
                    gate_names = [first["name"], second["name"]]
                    defs.append({
                        "name": self._boolean_population_name(parent_name, gate_names),
                        "parent_population": parent_name,
                        "gate_names": gate_names,
                    })
        return defs

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

    def _effective_heatmap_title(self, default_title):
        custom = self.heatmap_title_var.get().strip()
        return custom or default_title

    def save_heatmap(self):
        filename = filedialog.asksaveasfilename(
            defaultextension=".png",
            filetypes=[("PNG files", "*.png"), ("PDF files", "*.pdf"), ("SVG files", "*.svg")],
            initialfile="flow_well_heatmap.png",
        )
        if not filename:
            return
        try:
            self.heatmap_figure.savefig(filename, dpi=200, bbox_inches="tight")
            self.status_var.set(f"Saved heatmap to {filename}")
        except Exception as exc:
            self.status_var.set(f"Failed to save heatmap: {type(exc).__name__}: {exc}")

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
        initial_dir = self.folder_var.get() or self.home_folder or self.base_dir
        folder = filedialog.askdirectory(initialdir=_preferred_data_dir(initial_dir))
        if folder:
            self.folder_var.set(folder)

    def _app_home(self):
        if getattr(sys, "frozen", False):
            if _platform_key() == "windows":
                base_root = os.environ.get("LOCALAPPDATA") or os.environ.get("APPDATA") or os.path.expanduser("~")
                base = os.path.join(base_root, APP_BRAND)
            elif _platform_key() == "macos":
                base = os.path.join(os.path.expanduser("~"), "Library", "Application Support", APP_BRAND)
            else:
                base = os.path.join(os.path.expanduser("~"), ".flowjitsu")
            os.makedirs(base, exist_ok=True)
            return base
        return os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))

    def _download_dir(self):
        download_dir = os.path.join(os.path.expanduser("~"), "Downloads", DOWNLOADS_SUBDIR)
        os.makedirs(download_dir, exist_ok=True)
        return download_dir

    def _update_compensation_status(self):
        if self.compensation_enabled.get() and self.compensation_matrix is not None and self.compensation_channels:
            self.compensation_status_var.set(f"Compensation: on ({len(self.compensation_channels)} channels)")
        elif self.compensation_text.strip():
            self.compensation_status_var.set("Compensation: configured but disabled")
        else:
            self.compensation_status_var.set("Compensation: off")

    def _compensation_payload(self):
        return {
            "enabled": bool(self.compensation_enabled.get()),
            "source_channels": list(self.compensation_source_channels),
            "channels": list(self.compensation_channels),
            "matrix": self.compensation_matrix.tolist() if isinstance(self.compensation_matrix, np.ndarray) else None,
            "text": self.compensation_text,
        }

    def _load_compensation_payload(self, payload):
        payload = payload or {}
        self.compensation_enabled.set(bool(payload.get("enabled", False)))
        self.compensation_source_channels = list(payload.get("source_channels", []) or [])
        self.compensation_channels = list(payload.get("channels", []) or [])
        matrix = payload.get("matrix")
        self.compensation_matrix = np.asarray(matrix, dtype=float) if matrix is not None else None
        self.compensation_text = str(payload.get("text", "") or "")
        if self.compensation_matrix is not None and (
            self.compensation_matrix.ndim != 2
            or self.compensation_matrix.shape[0] != self.compensation_matrix.shape[1]
            or self.compensation_matrix.shape[0] != len(self.compensation_channels)
        ):
            self.compensation_matrix = None
            self.compensation_source_channels = []
            self.compensation_channels = []
            self.compensation_enabled.set(False)
        self._update_compensation_status()

    def _parse_compensation_text(self, text):
        text = str(text or "").strip()
        if not text:
            raise ValueError("Compensation matrix text is empty.")
        frame = pd.read_csv(io.StringIO(text), sep=None, engine="python", index_col=0)
        if frame.empty:
            raise ValueError("Compensation matrix could not be parsed.")
        frame.columns = [str(col).strip() for col in frame.columns]
        frame.index = [str(idx).strip() for idx in frame.index]
        if frame.shape[0] != frame.shape[1]:
            raise ValueError("Compensation matrix must be square.")
        if list(frame.index) != list(frame.columns):
            raise ValueError("Compensation matrix row and column labels must match.")
        matrix = frame.apply(pd.to_numeric, errors="raise").to_numpy(dtype=float)
        return list(frame.columns), matrix

    def _parse_spill_string(self, raw_value):
        if raw_value is None:
            raise ValueError("Compensation metadata field is empty.")
        text = str(raw_value).strip()
        if not text:
            raise ValueError("Compensation metadata field is empty.")
        parts = [part.strip() for part in text.replace("\n", ",").split(",") if part.strip()]
        if not parts:
            raise ValueError("Compensation metadata field is empty.")
        size = int(float(parts[0]))
        expected = 1 + size + size * size
        if len(parts) < expected:
            raise ValueError("Compensation metadata is incomplete.")
        channels = parts[1:1 + size]
        values = [float(part) for part in parts[1 + size:1 + size + size * size]]
        matrix = np.asarray(values, dtype=float).reshape(size, size)
        return channels, matrix

    def _extract_compensation_from_sample_meta(self, sample):
        meta = getattr(sample, "meta", None)
        if not isinstance(meta, dict):
            raise ValueError("Sample metadata is unavailable.")
        for key in ("SPILL", "$SPILL", "SPILLOVER", "$SPILLOVER"):
            if key in meta and meta.get(key):
                return self._parse_spill_string(meta.get(key))
        raise ValueError("No SPILL/SPILLOVER compensation metadata was found in the sample.")

    def _normalize_channel_token(self, value):
        return re.sub(r"[^a-z0-9]+", "", str(value or "").strip().lower())

    def _default_compensation_mapping(self, source_channels):
        used = set()
        mapping = []
        normalized_targets = {self._normalize_channel_token(channel): channel for channel in self.channel_names}
        for source in source_channels:
            direct = source if source in self.channel_names and source not in used else None
            if direct is None:
                direct = normalized_targets.get(self._normalize_channel_token(source))
                if direct in used:
                    direct = None
            if direct is None:
                source_norm = self._normalize_channel_token(source)
                for channel in self.channel_names:
                    channel_norm = self._normalize_channel_token(channel)
                    if channel not in used and (source_norm in channel_norm or channel_norm in source_norm):
                        direct = channel
                        break
            if direct is None:
                direct = ""
            else:
                used.add(direct)
            mapping.append(direct)
        return mapping

    def _open_compensation_channel_mapping_dialog(self, source_channels, initial_mapping=None, parent=None):
        if not self.channel_names:
            raise ValueError("Load a folder before mapping compensation channels.")
        dialog = tk.Toplevel(parent or self.root)
        dialog.title("Match Compensation Channels")
        dialog.transient(parent or self.root)
        dialog.grab_set()
        dialog.columnconfigure(1, weight=1)
        selected = []
        defaults = initial_mapping or self._default_compensation_mapping(source_channels)
        for idx, source in enumerate(source_channels):
            ttk.Label(dialog, text=source).grid(row=idx, column=0, sticky="w", padx=10, pady=4)
            var = tk.StringVar(value=defaults[idx] if idx < len(defaults) else "")
            combo = ttk.Combobox(dialog, textvariable=var, values=self.channel_names, state="readonly", width=28)
            combo.grid(row=idx, column=1, sticky="ew", padx=10, pady=4)
            selected.append(var)

        result = {"mapping": None}

        def _apply_mapping():
            mapping = [var.get().strip() for var in selected]
            if any(not value for value in mapping):
                messagebox.showerror("Channel Mapping", "Every compensation source channel must be matched.", parent=dialog)
                return
            if len(set(mapping)) != len(mapping):
                messagebox.showerror("Channel Mapping", "Each compensation source channel must map to a unique app channel.", parent=dialog)
                return
            result["mapping"] = mapping
            dialog.destroy()

        button_row = ttk.Frame(dialog)
        button_row.grid(row=len(source_channels), column=0, columnspan=2, sticky="e", padx=10, pady=(10, 10))
        ttk.Button(button_row, text="Apply", command=_apply_mapping).grid(row=0, column=0)
        ttk.Button(button_row, text="Cancel", command=dialog.destroy).grid(row=0, column=1, padx=(6, 0))
        dialog.wait_window()
        return result["mapping"]

    def _apply_compensation(self, df):
        if not self.compensation_enabled.get() or self.compensation_matrix is None or not self.compensation_channels:
            return df
        channels = [channel for channel in self.compensation_channels if channel in df.columns]
        if len(channels) != len(self.compensation_channels):
            return df
        try:
            inverse = np.linalg.pinv(self.compensation_matrix)
        except Exception as exc:
            self.status_var.set(f"Compensation failed: {type(exc).__name__}: {exc}")
            return df
        compensated = df.copy()
        values = compensated[channels].to_numpy(dtype=float)
        compensated_values = values @ inverse.T
        compensated.loc[:, channels] = compensated_values
        return compensated

    def open_compensation_editor(self):
        dialog = tk.Toplevel(self.root)
        dialog.title("Compensation")
        dialog.geometry("980x680")
        dialog.transient(self.root)
        dialog.grab_set()
        dialog.rowconfigure(2, weight=1)
        dialog.rowconfigure(3, weight=1)
        dialog.columnconfigure(0, weight=1)
        dialog.columnconfigure(1, weight=1)

        enabled_var = tk.BooleanVar(value=self.compensation_enabled.get())
        mapped_channels = list(self.compensation_channels)
        source_channels = list(self.compensation_source_channels or self.compensation_channels)
        text_widget = tk.Text(dialog, wrap="none", height=18)
        text_widget.grid(row=2, column=0, sticky="nsew", padx=(10, 5), pady=(0, 10))
        if self.compensation_text.strip():
            text_widget.insert("1.0", self.compensation_text)
        elif self.channel_names:
            channels = [ch for ch in self.channel_names if not any(token in ch for token in ("FSC", "SSC", "Time"))]
            if channels:
                header = "," + ",".join(channels)
                rows = [f"{channel}," + ",".join("1" if i == j else "0" for j in range(len(channels))) for i, channel in enumerate(channels)]
                text_widget.insert("1.0", "\n".join([header] + rows))
        ttk.Checkbutton(dialog, text="Enable compensation", variable=enabled_var).grid(row=0, column=0, sticky="w", padx=10, pady=(10, 6))
        ttk.Label(
            dialog,
            text="Paste a square spillover matrix with matching row/column channel labels. CSV or TSV works. Compensation is applied before transform and gating.",
            wraplength=720,
            justify="left",
        ).grid(row=1, column=0, sticky="w", padx=10, pady=(0, 10))

        preview_frame = ttk.LabelFrame(dialog, text="Preview", padding=10)
        preview_frame.grid(row=2, column=1, rowspan=2, sticky="nsew", padx=(5, 10), pady=(0, 10))
        preview_frame.columnconfigure(0, weight=1)
        preview_frame.rowconfigure(1, weight=1)

        preview_controls = ttk.Frame(preview_frame)
        preview_controls.grid(row=0, column=0, sticky="ew", pady=(0, 8))
        preview_sample_var = tk.StringVar(value=next(iter(self.file_map.keys()), ""))
        preview_x_var = tk.StringVar(value="")
        preview_y_var = tk.StringVar(value="")
        ttk.Label(preview_controls, text="Sample").grid(row=0, column=0, sticky="w")
        ttk.Combobox(preview_controls, textvariable=preview_sample_var, values=list(self.file_map.keys()), state="readonly", width=14).grid(row=1, column=0, padx=(0, 6))
        ttk.Label(preview_controls, text="X").grid(row=0, column=1, sticky="w")
        ttk.Label(preview_controls, text="Y").grid(row=0, column=2, sticky="w")

        compensation_preview_figure = Figure(figsize=(5.2, 4.2), dpi=100)
        before_ax = compensation_preview_figure.add_subplot(121)
        after_ax = compensation_preview_figure.add_subplot(122)
        preview_canvas = FigureCanvasTkAgg(compensation_preview_figure, master=preview_frame)
        preview_canvas.get_tk_widget().grid(row=1, column=0, sticky="nsew")

        def _effective_preview_channels():
            channels = [ch for ch in (mapped_channels or self.compensation_channels or self.channel_names) if ch in self.channel_names]
            fluorescence = [ch for ch in channels if not any(token in ch for token in ("FSC", "SSC", "Time"))]
            return fluorescence or channels

        preview_channel_values = _effective_preview_channels()
        if preview_channel_values:
            preview_x_var.set(preview_channel_values[0])
            preview_y_var.set(preview_channel_values[1] if len(preview_channel_values) > 1 else preview_channel_values[0])
        preview_x_combo = ttk.Combobox(preview_controls, textvariable=preview_x_var, values=preview_channel_values, state="readonly", width=18)
        preview_x_combo.grid(row=1, column=1, padx=(0, 6))
        preview_y_combo = ttk.Combobox(preview_controls, textvariable=preview_y_var, values=preview_channel_values, state="readonly", width=18)
        preview_y_combo.grid(row=1, column=2, padx=(0, 6))

        def _refresh_preview_channel_choices():
            values = _effective_preview_channels()
            preview_x_combo["values"] = values
            preview_y_combo["values"] = values
            if values:
                if preview_x_var.get() not in values:
                    preview_x_var.set(values[0])
                if preview_y_var.get() not in values:
                    preview_y_var.set(values[1] if len(values) > 1 else values[0])

        def _preview_dataframes():
            label = preview_sample_var.get().strip()
            if not label or label not in self.file_map:
                return None, None
            sample = self._load_sample(self.file_map[label])
            raw_df = sample.data.copy()
            x_channel = preview_x_var.get().strip()
            y_channel = preview_y_var.get().strip()
            if not x_channel or not y_channel or x_channel not in raw_df.columns or y_channel not in raw_df.columns:
                return raw_df, None
            if not mapped_channels or self.compensation_matrix is None:
                return raw_df, None
            temp_df = raw_df.copy()
            original_enabled = self.compensation_enabled.get()
            original_channels = list(self.compensation_channels)
            try:
                self.compensation_channels = list(mapped_channels)
                self.compensation_enabled.set(True)
                compensated_df = self._apply_compensation(temp_df)
            finally:
                self.compensation_channels = original_channels
                self.compensation_enabled.set(original_enabled)
            return raw_df, compensated_df

        def _update_preview(*_args):
            before_ax.clear()
            after_ax.clear()
            raw_df, compensated_df = _preview_dataframes()
            x_channel = preview_x_var.get().strip()
            y_channel = preview_y_var.get().strip()
            if raw_df is None or not x_channel or not y_channel or x_channel not in raw_df.columns or y_channel not in raw_df.columns:
                before_ax.set_title("No preview")
                after_ax.set_title("No preview")
                preview_canvas.draw_idle()
                return
            raw_plot = raw_df[[x_channel, y_channel]].dropna().sample(n=min(len(raw_df), 3000), random_state=0) if not raw_df.empty else raw_df
            before_ax.scatter(raw_plot[x_channel], raw_plot[y_channel], s=2, alpha=0.2, color="#5b8fd1", rasterized=True)
            before_ax.set_title("Before")
            before_ax.set_xlabel(x_channel)
            before_ax.set_ylabel(y_channel)
            _apply_prism_axis_style(before_ax)
            if compensated_df is not None and x_channel in compensated_df.columns and y_channel in compensated_df.columns:
                comp_plot = compensated_df[[x_channel, y_channel]].dropna().sample(n=min(len(compensated_df), 3000), random_state=0) if not compensated_df.empty else compensated_df
                after_ax.scatter(comp_plot[x_channel], comp_plot[y_channel], s=2, alpha=0.2, color="#d46a6a", rasterized=True)
                after_ax.set_title("After")
                after_ax.set_xlabel(x_channel)
                after_ax.set_ylabel(y_channel)
                _apply_prism_axis_style(after_ax)
            else:
                after_ax.set_title("After")
                after_ax.text(0.5, 0.5, "No active compensation", ha="center", va="center", transform=after_ax.transAxes)
            compensation_preview_figure.tight_layout()
            preview_canvas.draw_idle()

        def _load_file():
            filename = filedialog.askopenfilename(parent=dialog, filetypes=[("CSV/TSV files", "*.csv *.tsv *.txt"), ("All files", "*.*")])
            if not filename:
                return
            try:
                with open(filename) as fh:
                    text = fh.read()
                text_widget.delete("1.0", tk.END)
                text_widget.insert("1.0", text)
            except Exception as exc:
                messagebox.showerror("Compensation", f"Failed to load matrix file:\n{exc}", parent=dialog)

        def _match_channels():
            nonlocal mapped_channels, source_channels
            text = text_widget.get("1.0", tk.END).strip()
            if not text:
                messagebox.showinfo("Compensation", "Load or paste a compensation matrix first.", parent=dialog)
                return
            try:
                source_channels, _matrix = self._parse_compensation_text(text)
            except Exception as exc:
                messagebox.showerror("Compensation", f"Invalid compensation matrix:\n{exc}", parent=dialog)
                return
            mapping = self._open_compensation_channel_mapping_dialog(source_channels, initial_mapping=mapped_channels, parent=dialog)
            if mapping:
                mapped_channels = mapping
                _refresh_preview_channel_choices()
                _update_preview()

        def _auto_detect():
            nonlocal source_channels, mapped_channels
            if not self.file_map:
                messagebox.showinfo("Compensation", "Load a folder first.", parent=dialog)
                return
            sample = self._load_sample(next(iter(self.file_map.values())))
            try:
                detected_source_channels, detected_matrix = self._extract_compensation_from_sample_meta(sample)
            except Exception as exc:
                messagebox.showerror("Compensation", f"Automatic detection failed:\n{exc}", parent=dialog)
                return
            header = "," + ",".join(detected_source_channels)
            rows = [
                f"{channel}," + ",".join(f"{value:.10g}" for value in detected_matrix[idx])
                for idx, channel in enumerate(detected_source_channels)
            ]
            text_widget.delete("1.0", tk.END)
            text_widget.insert("1.0", "\n".join([header] + rows))
            source_channels = list(detected_source_channels)
            mapped_channels = self._default_compensation_mapping(source_channels)
            if any(not item for item in mapped_channels) or any(item not in self.channel_names for item in mapped_channels):
                mapping = self._open_compensation_channel_mapping_dialog(source_channels, initial_mapping=mapped_channels, parent=dialog)
                if mapping is None:
                    mapped_channels = []
                    return
                mapped_channels = mapping
            _refresh_preview_channel_choices()
            _update_preview()

        def _apply_editor():
            text = text_widget.get("1.0", tk.END).strip()
            if text:
                try:
                    source_channels_local, matrix = self._parse_compensation_text(text)
                except Exception as exc:
                    messagebox.showerror("Compensation", f"Invalid compensation matrix:\n{exc}", parent=dialog)
                    return
                self.compensation_source_channels = list(source_channels_local)
                channel_mapping = mapped_channels if mapped_channels and len(mapped_channels) == len(source_channels_local) else self._default_compensation_mapping(source_channels_local)
                if any(not item for item in channel_mapping) or len(set(channel_mapping)) != len(channel_mapping):
                    channel_mapping = self._open_compensation_channel_mapping_dialog(source_channels_local, initial_mapping=channel_mapping, parent=dialog)
                    if channel_mapping is None:
                        return
                self.compensation_channels = list(channel_mapping)
                self.compensation_matrix = matrix
                self.compensation_text = text
            else:
                self.compensation_source_channels = []
                self.compensation_channels = []
                self.compensation_matrix = None
                self.compensation_text = ""
            self.compensation_enabled.set(bool(enabled_var.get()) and self.compensation_matrix is not None)
            self.sample_cache = {}
            self._invalidate_computation_cache()
            self._update_compensation_status()
            dialog.destroy()
            if not self.current_data.empty or self.file_map:
                self._update_gate_summary_panel()
                self._refresh_heatmap_options()
                self.update_heatmap()
                self.update_plate_overview()
                if self._selected_labels():
                    self.plot_population()

        button_row = ttk.Frame(dialog)
        button_row.grid(row=3, column=0, sticky="e", padx=10, pady=(0, 10))
        ttk.Button(button_row, text="Auto Detect", command=_auto_detect).grid(row=0, column=0)
        ttk.Button(button_row, text="Load File", command=_load_file).grid(row=0, column=1, padx=(6, 0))
        ttk.Button(button_row, text="Match Channels", command=_match_channels).grid(row=0, column=2, padx=(6, 0))
        ttk.Button(button_row, text="Clear", command=lambda: text_widget.delete("1.0", tk.END)).grid(row=0, column=3, padx=(6, 0))
        ttk.Button(button_row, text="Apply", command=_apply_editor).grid(row=0, column=4, padx=(6, 0))
        ttk.Button(button_row, text="Close", command=dialog.destroy).grid(row=0, column=5, padx=(6, 0))

        preview_sample_var.trace_add("write", _update_preview)
        preview_x_var.trace_add("write", _update_preview)
        preview_y_var.trace_add("write", _update_preview)
        _refresh_preview_channel_choices()
        _update_preview()

    def _median_scatter_axis_limits(self, transformed):
        if self.y_plot_mode_var.get() != "scatter" or _is_count_axis(self.y_var.get()):
            return None
        x_channel = self.x_var.get()
        y_channel = self.y_var.get()
        if not self.file_map:
            return None
        bounds = []
        population_name = self._selected_population_name()
        for label in self.file_map:
            try:
                group = self._sample_population_raw_dataframe(label, population_name)
            except Exception:
                continue
            if group.empty:
                continue
            try:
                transformed_group = _apply_transform(
                    group,
                    x_channel,
                    y_channel,
                    self._plot_x_transform(),
                    self._plot_x_cofactor(),
                    y_method=self._plot_y_transform(),
                    y_cofactor=self._plot_y_cofactor(),
                )
            except Exception:
                continue
            if x_channel not in transformed_group.columns or y_channel not in transformed_group.columns:
                continue
            x_values = pd.to_numeric(transformed_group[x_channel], errors="coerce").replace([np.inf, -np.inf], np.nan).dropna().to_numpy()
            y_values = pd.to_numeric(transformed_group[y_channel], errors="coerce").replace([np.inf, -np.inf], np.nan).dropna().to_numpy()
            if len(x_values) == 0 or len(y_values) == 0:
                continue
            bounds.append((
                float(np.quantile(x_values, ROBUST_AXIS_LOWER_Q)),
                float(np.quantile(x_values, ROBUST_AXIS_UPPER_Q)),
                float(np.quantile(y_values, ROBUST_AXIS_LOWER_Q)),
                float(np.quantile(y_values, ROBUST_AXIS_UPPER_Q)),
            ))
        if not bounds:
            return None
        medians = np.median(np.asarray(bounds, dtype=float), axis=0)
        xmin, xmax, ymin, ymax = [float(value) for value in medians]
        if np.isclose(xmin, xmax):
            pad = max(abs(xmin) * 0.05, 1.0)
            xmin -= pad
            xmax += pad
        else:
            pad = (xmax - xmin) * 0.05
            xmin -= pad
            xmax += pad
        if np.isclose(ymin, ymax):
            pad = max(abs(ymin) * 0.05, 1.0)
            ymin -= pad
            ymax += pad
        else:
            pad = (ymax - ymin) * 0.05
            ymin -= pad
            ymax += pad
        return xmin, xmax, ymin, ymax

    def _global_scatter_axis_extent(self):
        if self.y_plot_mode_var.get() != "scatter" or _is_count_axis(self.y_var.get()):
            return None
        x_channel = self.x_var.get()
        y_channel = self.y_var.get()
        if not self.file_map:
            return None
        xmin = xmax = ymin = ymax = None
        population_name = self._selected_population_name()
        for label in self.file_map:
            try:
                group = self._sample_population_raw_dataframe(label, population_name)
            except Exception:
                continue
            if group.empty:
                continue
            try:
                transformed_group = _apply_transform(
                    group,
                    x_channel,
                    y_channel,
                    self._plot_x_transform(),
                    self._plot_x_cofactor(),
                    y_method=self._plot_y_transform(),
                    y_cofactor=self._plot_y_cofactor(),
                )
            except Exception:
                continue
            if x_channel not in transformed_group.columns or y_channel not in transformed_group.columns:
                continue
            x_values = pd.to_numeric(transformed_group[x_channel], errors="coerce").replace([np.inf, -np.inf], np.nan).dropna().to_numpy()
            y_values = pd.to_numeric(transformed_group[y_channel], errors="coerce").replace([np.inf, -np.inf], np.nan).dropna().to_numpy()
            if len(x_values) == 0 or len(y_values) == 0:
                continue
            group_xmin = float(np.quantile(x_values, ROBUST_AXIS_LOWER_Q))
            group_xmax = float(np.quantile(x_values, ROBUST_AXIS_UPPER_Q))
            group_ymin = float(np.quantile(y_values, ROBUST_AXIS_LOWER_Q))
            group_ymax = float(np.quantile(y_values, ROBUST_AXIS_UPPER_Q))
            xmin = group_xmin if xmin is None else min(xmin, group_xmin)
            xmax = group_xmax if xmax is None else max(xmax, group_xmax)
            ymin = group_ymin if ymin is None else min(ymin, group_ymin)
            ymax = group_ymax if ymax is None else max(ymax, group_ymax)
        if xmin is None or xmax is None or ymin is None or ymax is None:
            return None
        if np.isclose(xmin, xmax):
            pad = max(abs(xmin) * 0.05, 1.0)
            xmin -= pad
            xmax += pad
        if np.isclose(ymin, ymax):
            pad = max(abs(ymin) * 0.05, 1.0)
            ymin -= pad
            ymax += pad
        return xmin, xmax, ymin, ymax

    def _effective_scatter_axis_limits(self, transformed):
        base_limits = self._median_scatter_axis_limits(transformed)
        if base_limits is None:
            return None
        xmin, xmax, ymin, ymax = base_limits
        if self.scatter_xmin_override is not None:
            xmin = self.scatter_xmin_override
        if self.scatter_xmax_override is not None:
            xmax = self.scatter_xmax_override
        if self.scatter_ymin_override is not None:
            ymin = self.scatter_ymin_override
        if self.scatter_ymax_override is not None:
            ymax = self.scatter_ymax_override
        return xmin, xmax, ymin, ymax

    def _median_histogram_axis_limits(self, transformed):
        histogram_mode = self.y_plot_mode_var.get() == "count histogram" or _is_count_axis(self.y_var.get())
        if not histogram_mode or not self.file_map:
            return None
        x_channel = self.x_var.get()
        population_name = self._selected_population_name()
        x_bounds = []
        global_xmin = None
        global_xmax = None
        for label in self.file_map:
            try:
                group = self._sample_population_raw_dataframe(label, population_name)
            except Exception:
                continue
            if group.empty or x_channel not in group.columns:
                continue
            x_values = _transform_array(group[x_channel].to_numpy(), self._plot_x_transform(), self._plot_x_cofactor())
            x_values = pd.to_numeric(pd.Series(x_values), errors="coerce").replace([np.inf, -np.inf], np.nan).dropna().to_numpy()
            if len(x_values) == 0:
                continue
            group_xmin = float(np.quantile(x_values, ROBUST_AXIS_LOWER_Q))
            group_xmax = float(np.quantile(x_values, ROBUST_AXIS_UPPER_Q))
            x_bounds.append((group_xmin, group_xmax))
            global_xmin = group_xmin if global_xmin is None else min(global_xmin, group_xmin)
            global_xmax = group_xmax if global_xmax is None else max(global_xmax, group_xmax)
        if not x_bounds or global_xmin is None or global_xmax is None:
            return None
        median_xmin, median_xmax = np.median(np.asarray(x_bounds, dtype=float), axis=0)
        xmin = float(median_xmin)
        xmax = float(median_xmax)
        if np.isclose(xmin, xmax):
            pad = max(abs(xmin) * 0.05, 1.0)
            xmin -= pad
            xmax += pad
        else:
            pad = (xmax - xmin) * 0.05
            xmin -= pad
            xmax += pad
        max_count = 0
        bins = max(int(self.hist_bins_var.get()), 1)
        edges = np.linspace(xmin, xmax, bins + 1)
        for label in self.file_map:
            try:
                group = self._sample_population_raw_dataframe(label, population_name)
            except Exception:
                continue
            if group.empty or x_channel not in group.columns:
                continue
            x_values = _transform_array(group[x_channel].to_numpy(), self._plot_x_transform(), self._plot_x_cofactor())
            x_values = pd.to_numeric(pd.Series(x_values), errors="coerce").replace([np.inf, -np.inf], np.nan).dropna().to_numpy()
            if len(x_values) == 0:
                continue
            counts, _ = np.histogram(x_values, bins=edges)
            if len(counts):
                max_count = max(max_count, int(counts.max()))
        ymax = max(float(max_count) * 1.05, 1.0)
        return xmin, xmax, 0.0, ymax

    def open_graph_options_dialog(self):
        auto_limits = self._median_scatter_axis_limits(self.current_transformed)
        slider_extent = self._global_scatter_axis_extent()
        histogram_mode = self.y_plot_mode_var.get() == "count histogram" or _is_count_axis(self.y_var.get())
        dialog = tk.Toplevel(self.root)
        dialog.title("Graph Options")
        dialog.transient(self.root)
        dialog.grab_set()
        dialog.columnconfigure(1, weight=1)
        next_row = 0

        def _fmt(value):
            return "" if value is None else f"{value:.4g}"

        ttk.Label(dialog, text="Histogram Bins").grid(row=next_row, column=0, sticky="w", padx=10, pady=(10, 2))
        bins_var = tk.IntVar(value=max(int(self.hist_bins_var.get()), 1))
        ttk.Spinbox(dialog, from_=5, to=500, increment=5, textvariable=bins_var, width=10).grid(row=next_row, column=1, sticky="e", padx=10, pady=(10, 2))
        next_row += 1

        current_limits = self._effective_scatter_axis_limits(self.current_transformed) or auto_limits
        if slider_extent is None or current_limits is None:
            message = "Scatter limits are unavailable until a scatter plot is loaded."
            if histogram_mode:
                hist_limits = self._median_histogram_axis_limits(self.current_transformed)
                if hist_limits is not None:
                    message = (
                        "Histogram axes are shared across all loaded FCS files.\n"
                        f"Auto X: {_fmt(hist_limits[0])} to {_fmt(hist_limits[1])}\n"
                        f"Auto Y: {_fmt(hist_limits[2])} to {_fmt(hist_limits[3])}"
                    )
                else:
                    message = "Histogram axes will be shared automatically once a histogram is loaded."
            ttk.Label(dialog, text=message, wraplength=340, justify="left").grid(row=next_row, column=0, columnspan=2, sticky="w", padx=10, pady=(10, 10))

            def _apply_hist_only():
                self.hist_bins_var.set(max(int(bins_var.get()), 1))
                if not self.current_transformed.empty:
                    self.redraw()
                dialog.destroy()

            button_row = ttk.Frame(dialog)
            button_row.grid(row=next_row + 1, column=0, columnspan=2, sticky="e", padx=10, pady=(0, 10))
            ttk.Button(button_row, text="Apply", command=_apply_hist_only).grid(row=0, column=0)
            ttk.Button(button_row, text="Close", command=dialog.destroy).grid(row=0, column=1, padx=(6, 0))
            return

        xmin_limit, xmax_limit, ymin_limit, ymax_limit = slider_extent
        xmin_current, xmax_current, ymin_current, ymax_current = current_limits
        xmin_var = tk.StringVar(value=_fmt(xmin_current))
        xmax_var = tk.StringVar(value=_fmt(xmax_current))
        ymin_var = tk.StringVar(value=_fmt(ymin_current))
        ymax_var = tk.StringVar(value=_fmt(ymax_current))
        xmin_scale = tk.DoubleVar(value=xmin_current)
        xmax_scale = tk.DoubleVar(value=xmax_current)
        ymin_scale = tk.DoubleVar(value=ymin_current)
        ymax_scale = tk.DoubleVar(value=ymax_current)

        def _sync_labels():
            xmin_var.set(_fmt(xmin_scale.get()))
            xmax_var.set(_fmt(xmax_scale.get()))
            ymin_var.set(_fmt(ymin_scale.get()))
            ymax_var.set(_fmt(ymax_scale.get()))

        def _clamp_xmin(_value=None):
            if xmin_scale.get() > xmax_scale.get():
                xmax_scale.set(xmin_scale.get())
            _sync_labels()

        def _clamp_xmax(_value=None):
            if xmax_scale.get() < xmin_scale.get():
                xmin_scale.set(xmax_scale.get())
            _sync_labels()

        def _clamp_ymin(_value=None):
            if ymin_scale.get() > ymax_scale.get():
                ymax_scale.set(ymin_scale.get())
            _sync_labels()

        def _clamp_ymax(_value=None):
            if ymax_scale.get() < ymin_scale.get():
                ymin_scale.set(ymax_scale.get())
            _sync_labels()

        ttk.Label(dialog, text="X Min").grid(row=next_row, column=0, sticky="w", padx=10, pady=(10, 2))
        ttk.Label(dialog, textvariable=xmin_var).grid(row=next_row, column=1, sticky="e", padx=10, pady=(10, 2))
        next_row += 1
        ttk.Scale(dialog, from_=xmin_limit, to=xmax_limit, variable=xmin_scale, orient=tk.HORIZONTAL, command=_clamp_xmin).grid(row=next_row, column=0, columnspan=2, sticky="ew", padx=10)
        next_row += 1
        ttk.Label(dialog, text="X Max").grid(row=next_row, column=0, sticky="w", padx=10, pady=(10, 2))
        ttk.Label(dialog, textvariable=xmax_var).grid(row=next_row, column=1, sticky="e", padx=10, pady=(10, 2))
        next_row += 1
        ttk.Scale(dialog, from_=xmin_limit, to=xmax_limit, variable=xmax_scale, orient=tk.HORIZONTAL, command=_clamp_xmax).grid(row=next_row, column=0, columnspan=2, sticky="ew", padx=10)
        next_row += 1
        ttk.Label(dialog, text="Y Min").grid(row=next_row, column=0, sticky="w", padx=10, pady=(10, 2))
        ttk.Label(dialog, textvariable=ymin_var).grid(row=next_row, column=1, sticky="e", padx=10, pady=(10, 2))
        next_row += 1
        ttk.Scale(dialog, from_=ymin_limit, to=ymax_limit, variable=ymin_scale, orient=tk.HORIZONTAL, command=_clamp_ymin).grid(row=next_row, column=0, columnspan=2, sticky="ew", padx=10)
        next_row += 1
        ttk.Label(dialog, text="Y Max").grid(row=next_row, column=0, sticky="w", padx=10, pady=(10, 2))
        ttk.Label(dialog, textvariable=ymax_var).grid(row=next_row, column=1, sticky="e", padx=10, pady=(10, 2))
        next_row += 1
        ttk.Scale(dialog, from_=ymin_limit, to=ymax_limit, variable=ymax_scale, orient=tk.HORIZONTAL, command=_clamp_ymax).grid(row=next_row, column=0, columnspan=2, sticky="ew", padx=10)

        auto_label = "Automatic scatter limits unavailable until a scatter plot is loaded."
        if auto_limits is not None:
            auto_label = (
                f"Automatic limits use the median bounds across all loaded FCS files.\n"
                f"Auto X: {_fmt(auto_limits[0])} to {_fmt(auto_limits[1])}\n"
                f"Auto Y: {_fmt(auto_limits[2])} to {_fmt(auto_limits[3])}"
            )
        extent_label = (
            f"Slider range uses the full global extent across all loaded FCS files.\n"
            f"Range X: {_fmt(xmin_limit)} to {_fmt(xmax_limit)}\n"
            f"Range Y: {_fmt(ymin_limit)} to {_fmt(ymax_limit)}"
        )
        next_row += 1
        ttk.Label(dialog, text=auto_label, wraplength=320, justify="left").grid(row=next_row, column=0, columnspan=2, sticky="w", padx=10, pady=(8, 4))
        next_row += 1
        ttk.Label(dialog, text=extent_label, wraplength=320, justify="left").grid(row=next_row, column=0, columnspan=2, sticky="w", padx=10, pady=(0, 10))

        def _apply_limits():
            self.hist_bins_var.set(max(int(bins_var.get()), 1))
            xmin = float(xmin_scale.get())
            xmax = float(xmax_scale.get())
            ymin = float(ymin_scale.get())
            ymax = float(ymax_scale.get())
            if xmin is not None and xmax is not None and xmin >= xmax:
                messagebox.showerror("Invalid Limits", "X Min must be less than X Max.", parent=dialog)
                return
            if ymin is not None and ymax is not None and ymin >= ymax:
                messagebox.showerror("Invalid Limits", "Y Min must be less than Y Max.", parent=dialog)
                return
            self.scatter_xmin_override = xmin
            self.scatter_xmax_override = xmax
            self.scatter_ymin_override = ymin
            self.scatter_ymax_override = ymax
            dialog.destroy()
            if not self.current_transformed.empty:
                self.redraw()

        def _reset_auto():
            self.hist_bins_var.set(max(int(bins_var.get()), 1))
            self.scatter_xmin_override = None
            self.scatter_xmax_override = None
            self.scatter_ymin_override = None
            self.scatter_ymax_override = None
            dialog.destroy()
            if not self.current_transformed.empty:
                self.redraw()

        button_row = ttk.Frame(dialog)
        next_row += 1
        button_row.grid(row=next_row, column=0, columnspan=2, sticky="e", padx=10, pady=(0, 10))
        ttk.Button(button_row, text="Use Auto", command=_reset_auto).grid(row=0, column=0)
        ttk.Button(button_row, text="Apply", command=_apply_limits).grid(row=0, column=1, padx=(6, 0))
        ttk.Button(button_row, text="Close", command=dialog.destroy).grid(row=0, column=2, padx=(6, 0))

    def _latest_release_info(self):
        request = urllib.request.Request(
            GITHUB_LATEST_RELEASE_API,
            headers={
                "Accept": "application/vnd.github+json",
                "User-Agent": APP_BRAND,
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
            suffixes = ()
            if _platform_key() == "macos":
                suffixes = ("FlowJitsu-macos.zip", ".app.zip")
            elif _platform_key() == "windows":
                suffixes = ("FlowJitsu-windows.zip",)
            for suffix in suffixes:
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
            headers={"User-Agent": APP_BRAND},
        )
        with urllib.request.urlopen(request, timeout=60) as response, open(destination, "wb") as fh:
            fh.write(response.read())
        return destination

    def _current_app_bundle_path(self):
        if not getattr(sys, "frozen", False) or _platform_key() != "macos":
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

    def _extract_windows_app_from_zip(self, zip_path):
        extract_root = os.path.join(self._download_dir(), os.path.splitext(os.path.basename(zip_path))[0])
        if os.path.isdir(extract_root):
            shutil.rmtree(extract_root)
        os.makedirs(extract_root, exist_ok=True)
        with zipfile.ZipFile(zip_path, "r") as zf:
            zf.extractall(extract_root)
        for root, _dirs, files in os.walk(extract_root):
            if "FlowJitsu.exe" in files:
                return root, os.path.join(root, "FlowJitsu.exe")
        raise FileNotFoundError("No FlowJitsu.exe found in the downloaded zip.")

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
        if getattr(sys, "frozen", False) and _platform_key() == "macos" and asset_name.endswith(".zip"):
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
        if getattr(sys, "frozen", False) and _platform_key() == "windows" and asset_name.endswith(".zip"):
            try:
                extracted_dir, _extracted_exe = self._extract_windows_app_from_zip(destination)
                messagebox.showinfo(
                    "Update Downloaded",
                    f"Downloaded and extracted {latest_tag}.\n\n"
                    f"Folder:\n{extracted_dir}\n\n"
                    f"For now, Windows updates are install-by-replacement:\n"
                    f"1. Close the running app\n"
                    f"2. Replace your current FlowJitsu folder with the extracted one\n"
                    f"3. Launch FlowJitsu.exe\n",
                )
                _open_path(extracted_dir)
                self.status_var.set(f"Downloaded Windows update to {extracted_dir}")
            except Exception as exc:
                self.status_var.set(f"Downloaded update but Windows handoff failed: {type(exc).__name__}: {exc}")
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
            _open_path(os.path.dirname(destination))

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
        except HTTPError as exc:
            if exc.code == 404:
                self.status_var.set("Update check failed: GitHub returned 404")
                messagebox.showerror(
                    "Update Check Failed",
                    "Update check failed with HTTP 404.\n\n"
                    "This usually means the GitHub repo or release assets are not publicly accessible from this machine. "
                    "GitHub returns 404 for private release endpoints when accessed without authentication.\n\n"
                    "For labmates to use in-app update checks, the release assets need to be publicly reachable or hosted "
                    "through a different update endpoint.",
                )
                return
            self.status_var.set(f"Update check failed: HTTPError {exc.code}")
        except Exception as exc:
            self.status_var.set(f"Update check failed: {type(exc).__name__}: {exc}")

    def _session_dir(self):
        session_dir = os.path.join(self._app_home(), "sessions")
        os.makedirs(session_dir, exist_ok=True)
        return session_dir

    def _settings_path(self):
        return os.path.join(self._app_home(), "settings.json")

    def _load_settings(self):
        settings_path = self._settings_path()
        if os.path.isfile(settings_path):
            try:
                with open(settings_path) as fh:
                    data = json.load(fh)
                return data if isinstance(data, dict) else {}
            except Exception:
                return {}
        return {}

    def _save_settings(self, settings):
        with open(self._settings_path(), "w") as fh:
            json.dump(settings, fh, indent=2)

    def _load_home_folder(self):
        home_folder = self._load_settings().get("home_folder", "")
        if home_folder and os.path.isdir(home_folder):
            return home_folder
        return ""

    def _recent_sessions(self):
        settings = self._load_settings()
        recent = settings.get("recent_sessions", [])
        return [path for path in recent if isinstance(path, str) and os.path.isfile(path)]

    def _remember_recent_session(self, path):
        if not path:
            return
        path = os.path.abspath(path)
        recent = [item for item in self._recent_sessions() if os.path.abspath(item) != path]
        recent.insert(0, path)
        settings = self._load_settings()
        settings["recent_sessions"] = recent[:12]
        self._save_settings(settings)
        self._refresh_recent_sessions()

    def _refresh_recent_sessions(self):
        recent = self._recent_sessions()
        if hasattr(self, "recent_session_var"):
            combo = getattr(self, "recent_session_combo", None)
            if combo is not None:
                combo["values"] = recent
            if self.recent_session_var.get() not in recent:
                self.recent_session_var.set(recent[0] if recent else "")

    def _persist_home_folder(self, folder):
        settings = self._load_settings()
        settings["home_folder"] = folder
        self._save_settings(settings)
        self.home_folder = folder
        if hasattr(self, "_home_folder_label_var_obj"):
            label = os.path.basename(folder.rstrip(os.sep)) or folder
            self._home_folder_label_var_obj.set(f"Home: {label}")

    def _home_folder_label_textvar(self):
        if not hasattr(self, "_home_folder_label_var_obj"):
            label = "Home: not set"
            if self.home_folder:
                name = os.path.basename(self.home_folder.rstrip(os.sep)) or self.home_folder
                label = f"Home: {name}"
            self._home_folder_label_var_obj = tk.StringVar(value=label)
        return self._home_folder_label_var_obj

    def set_home_folder(self):
        folder = self.folder_var.get().strip()
        if not folder or not os.path.isdir(folder):
            messagebox.showinfo("Set Home Folder", "Choose or load a valid folder first.")
            return
        self._persist_home_folder(folder)
        self.status_var.set(f"Home folder set to {folder}")

    def _last_session_path(self):
        return os.path.join(self._session_dir(), "last_flow_session.json")

    def _autosave_dir(self):
        autosave_dir = os.path.join(self._app_home(), "autosave")
        os.makedirs(autosave_dir, exist_ok=True)
        return autosave_dir

    def _autosave_path(self):
        return os.path.join(self._autosave_dir(), "latest_autosave.json")

    def _state_snapshot(self):
        return json.loads(json.dumps(self._session_payload()))

    def _restore_state_snapshot(self, snapshot):
        self.suspend_history = True
        try:
            self._apply_session_payload(json.loads(json.dumps(snapshot)))
        finally:
            self.suspend_history = False
        self._invalidate_computation_cache()

    def _push_undo_state(self):
        if self.suspend_history:
            return
        self.undo_stack.append(self._state_snapshot())
        if len(self.undo_stack) > self.history_limit:
            self.undo_stack = self.undo_stack[-self.history_limit:]
        self.redo_stack.clear()

    def _mark_state_changed(self, message="State updated"):
        if self.suspend_history:
            return
        self._invalidate_computation_cache()
        self.update_plate_overview()
        self._schedule_autosave()
        self._refresh_recent_sessions()
        self.gate_status_var.set(message)

    def _invalidate_computation_cache(self):
        self._selected_raw_cache.clear()
        self._population_raw_cache.clear()
        self._sample_population_cache.clear()
        self._display_cache.clear()
        self._summary_cache = None
        self._intensity_cache = None

    def _selected_labels_key(self):
        return tuple(self._selected_labels())

    def _schedule_autosave(self):
        if self.autosave_after_id is not None:
            try:
                self.root.after_cancel(self.autosave_after_id)
            except Exception:
                pass
        self.autosave_after_id = self.root.after(1500, self._write_autosave)
        self.autosave_var.set("Autosave: pending")

    def _write_autosave(self):
        self.autosave_after_id = None
        try:
            payload = self._session_payload()
            path = self._autosave_path()
            with open(path, "w") as fh:
                json.dump(payload, fh, indent=2)
            self.autosave_var.set(f"Autosave: {datetime.now().strftime('%H:%M:%S')}")
        except Exception as exc:
            self.autosave_var.set(f"Autosave failed: {type(exc).__name__}")

    def undo_last_change(self):
        if not self.undo_stack:
            self.gate_status_var.set("Nothing to undo.")
            return
        current = self._state_snapshot()
        snapshot = self.undo_stack.pop()
        self.redo_stack.append(current)
        self._restore_state_snapshot(snapshot)
        self._refresh_recent_sessions()
        self.gate_status_var.set("Undid last change.")

    def redo_last_change(self):
        if not self.redo_stack:
            self.gate_status_var.set("Nothing to redo.")
            return
        current = self._state_snapshot()
        snapshot = self.redo_stack.pop()
        self.undo_stack.append(current)
        self._restore_state_snapshot(snapshot)
        self._refresh_recent_sessions()
        self.gate_status_var.set("Redid last change.")

    def load_recent_session(self):
        filename = self.recent_session_var.get().strip()
        if not filename:
            self.gate_status_var.set("No recent session selected.")
            return
        if not os.path.isfile(filename):
            self.gate_status_var.set(f"Recent session not found: {filename}")
            self._refresh_recent_sessions()
            return
        try:
            with open(filename) as fh:
                payload = json.load(fh)
            self._push_undo_state()
            self._apply_session_payload(payload)
            with open(self.last_session_path, "w") as fh:
                json.dump(payload, fh, indent=2)
            self._remember_recent_session(filename)
            self.gate_status_var.set(f"Loaded recent session from {filename}")
        except Exception as exc:
            self.gate_status_var.set(f"Failed to load recent session: {type(exc).__name__}: {exc}")

    def _session_payload(self):
        return {
            "folder": self.folder_var.get().strip(),
            "instrument": self.instrument_var.get(),
            "gates": self.gates,
            "plate_metadata": self.plate_metadata,
            "dose_curve_definitions": self.dose_curve_definitions,
            "compensation": self._compensation_payload(),
        }

    def _gate_template_payload(self):
        gate_channels = sorted({
            channel
            for gate in self.gates
            for channel in [gate.get("x_channel"), gate.get("y_channel")]
            if channel
        })
        return {
            "template_type": "flow_gate_template",
            "version": 1,
            "instrument": self.instrument_var.get(),
            "channels": gate_channels,
            "gates": self.gates,
            "exported_at": datetime.now().isoformat(timespec="seconds"),
        }

    def _save_session_to_path(self, filename):
        payload = self._session_payload()
        with open(filename, "w") as fh:
            json.dump(payload, fh, indent=2)
        with open(self.last_session_path, "w") as fh:
            json.dump(payload, fh, indent=2)
        self._remember_recent_session(filename)

    def save_gate_template(self):
        if not self.gates:
            self.gate_status_var.set("No gates to save as a template.")
            return
        filename = filedialog.asksaveasfilename(
            defaultextension=".json",
            filetypes=[("JSON files", "*.json")],
            initialdir=self._session_dir(),
            initialfile="gate_template.json",
        )
        if not filename:
            return
        try:
            with open(filename, "w") as fh:
                json.dump(self._gate_template_payload(), fh, indent=2)
            self.gate_status_var.set(f"Saved gate template to {filename}")
        except Exception as exc:
            self.gate_status_var.set(f"Failed to save gate template: {type(exc).__name__}: {exc}")

    def _load_gate_template_from_path(self, filename, payload=None):
        try:
            if payload is None:
                with open(filename) as fh:
                    payload = json.load(fh)
            if payload.get("template_type") != "flow_gate_template":
                raise ValueError("Selected file is not a gate template.")
            template_gates = payload.get("gates", [])
            if not isinstance(template_gates, list) or not template_gates:
                raise ValueError("Gate template does not contain any gates.")
            template_channels = sorted({
                channel
                for gate in template_gates
                for channel in [gate.get("x_channel"), gate.get("y_channel")]
                if channel
            })
            missing_channels = [channel for channel in template_channels if channel not in self.channel_names]
            if self.channel_names and missing_channels:
                raise ValueError(f"Template channels not found in current experiment: {', '.join(missing_channels)}")
            new_names = {gate["name"] for gate in template_gates}
            existing_names = {gate["name"] for gate in self.gates}
            duplicates = sorted(new_names & existing_names)
            if duplicates:
                raise ValueError(f"Template gate names already exist: {', '.join(duplicates)}")
            self._push_undo_state()
            self.gates.extend(template_gates)
            if self.gates:
                max_group = 0
                for gate in self.gates:
                    group_name = gate.get("gate_group", "")
                    match = re.search(r"(\d+)$", str(group_name))
                    if match:
                        max_group = max(max_group, int(match.group(1)))
                self.gate_group_counter = max(self.gate_group_counter, max_group)
            selected_name = template_gates[0]["name"]
            self._refresh_gate_lists(selected_name=selected_name)
            self.redraw()
            self._update_gate_summary_panel()
            self._refresh_heatmap_options()
            self.update_heatmap()
            self._mark_state_changed(f"Loaded gate template from {filename}")
        except Exception as exc:
            self.gate_status_var.set(f"Failed to load gate template: {type(exc).__name__}: {exc}")

    def load_gate_template(self):
        filename = filedialog.askopenfilename(
            initialdir=self._session_dir(),
            filetypes=[("JSON files", "*.json")],
        )
        if not filename:
            return
        self._load_gate_template_from_path(filename)

    def _on_close_request(self):
        choice = messagebox.askyesnocancel(
            "Save Session Before Closing",
            "Do you want to save your session before closing?",
        )
        if choice is None:
            return
        if choice:
            filename = filedialog.asksaveasfilename(
                defaultextension=".json",
                filetypes=[("JSON files", "*.json")],
                initialdir=self._session_dir(),
                initialfile="flow_session.json",
            )
            if not filename:
                return
            try:
                self._save_session_to_path(filename)
                self.gate_status_var.set(f"Saved session to {filename} and updated last-session defaults")
            except Exception as exc:
                self.gate_status_var.set(f"Failed to save session: {type(exc).__name__}: {exc}")
                messagebox.showerror("Save Session Failed", f"Could not save session:\n{exc}")
                return
        self.root.destroy()

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
        if self.home_folder and os.path.isdir(self.home_folder):
            self.folder_var.set(self.home_folder)
            self.load_folder()
            return
        if base_dir:
            self.load_folder()

    def _apply_session_payload(self, payload):
        folder = payload.get("folder", "")
        instrument = payload.get("instrument", self.instrument_var.get())
        if folder:
            self.folder_var.set(folder)
        self.instrument_var.set(instrument)
        self._load_request_id += 1
        request_id = self._load_request_id
        file_map, channel_names = self._scan_folder_contents(folder, instrument)
        self._finish_load_folder(request_id, folder, file_map, channel_names, None)
        self.gates = payload.get("gates", [])
        self.plate_metadata = payload.get("plate_metadata", {})
        self.dose_curve_definitions = payload.get("dose_curve_definitions", {})
        self._load_compensation_payload(payload.get("compensation", {}))
        self._invalidate_computation_cache()
        self._refresh_gate_lists()
        self._update_gate_summary_panel()
        self._refresh_heatmap_options()
        self.redraw()
        self.update_heatmap()
        self.update_plate_overview()

    def load_folder(self):
        folder = self.folder_var.get().strip()
        if not os.path.isdir(folder):
            self.status_var.set(f"Folder not found: {folder}")
            return

        if not self.suspend_history and (self.file_map or self.gates or self.plate_metadata or self.dose_curve_definitions):
            self._push_undo_state()
        self._load_request_id += 1
        request_id = self._load_request_id
        instrument = self.instrument_var.get()
        self.status_var.set("Scanning folder and reading channels...")

        def worker():
            try:
                file_map, channel_names = self._scan_folder_contents(folder, instrument)
                self.root.after(0, lambda: self._finish_load_folder(request_id, folder, file_map, channel_names, None))
            except Exception as exc:
                self.root.after(0, lambda: self._finish_load_folder(request_id, folder, None, None, exc))

        threading.Thread(target=worker, daemon=True).start()

    def _scan_folder_contents(self, folder, instrument):
        files = _list_fcs_files(folder, instrument)
        file_map = {}
        for relpath in files:
            well = _get_well_name(relpath, instrument)
            label = f"{well} | {relpath}"
            file_map[label] = relpath
        channel_names = []
        if file_map:
            first_label = next(iter(file_map))
            first_relpath = file_map[first_label]
            datafile = os.path.join(folder, first_relpath)
            well = _get_well_name(first_relpath, instrument)
            FCMeasurement = _flow_tools()["FCMeasurement"]
            sample = FCMeasurement(ID=well, datafile=datafile)
            channel_names = _get_channel_names(sample)
        return file_map, channel_names

    def _finish_load_folder(self, request_id, folder, file_map, channel_names, error):
        if request_id != self._load_request_id:
            return
        if error is not None:
            self.status_var.set(f"Load Folder failed: {type(error).__name__}: {error}")
            return

        self.file_map = file_map or {}
        self.sample_cache = {}
        self.gates = []
        self.plate_metadata = {}
        self.dose_curve_definitions = {}
        self._load_compensation_payload({})
        self.saved_gate_labels = {}
        self.pending_gate = None
        self._invalidate_computation_cache()

        self.well_listbox.delete(0, tk.END)
        for label in self.file_map:
            self.well_listbox.insert(tk.END, label)

        if self.file_map:
            self.well_listbox.selection_set(0)
            self.channel_names = channel_names or []
            self.x_combo["values"] = self.channel_names
            self.y_combo["values"] = list(self.channel_names) + ["Count"]
            if self.channel_names:
                self.x_var.set("FSC-A" if "FSC-A" in self.channel_names else self.channel_names[0])
                if _is_count_axis(self.y_var.get()):
                    self.y_var.set("Count")
                elif "SSC-A" in self.channel_names:
                    self.y_var.set("SSC-A")
                elif len(self.channel_names) > 1:
                    self.y_var.set(self.channel_names[1])
                else:
                    self.y_var.set("Count")
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
        self.update_plate_overview()

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
            FCMeasurement = _flow_tools()["FCMeasurement"]
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
        df = self._apply_compensation(sample.data.copy())
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
        cache_key = tuple(labels)
        cached = self._selected_raw_cache.get(cache_key)
        if cached is not None:
            return cached.copy()
        frames = []
        for idx, label in enumerate(labels):
            relpath = self.file_map[label]
            sample = self._load_sample(relpath)
            df = self._apply_compensation(sample.data.copy())
            df["__well__"] = _get_well_name(relpath, self.instrument_var.get())
            df["__source__"] = relpath
            df["__sample_idx__"] = idx
            frames.append(df)
        combined = pd.concat(frames, ignore_index=True)
        self._selected_raw_cache[cache_key] = combined
        return combined.copy()

    def _population_gate(self, name):
        if name == "__all__":
            return None
        for gate in self.gates:
            if gate["name"] == name:
                return gate
        return None

    def _population_lineage(self, name):
        if self._is_boolean_population(name):
            parent_name, gate_names = self._boolean_population_spec(name)
            return [self._population_gate(gate_name) for gate_name in gate_names if self._population_gate(gate_name) is not None]
        lineage = []
        current = self._population_gate(name)
        while current is not None:
            lineage.append(current)
            current = self._population_gate(current["parent_population"])
        return list(reversed(lineage))

    def _population_raw_dataframe(self, population_name):
        cache_key = (self._selected_labels_key(), population_name)
        cached = self._population_raw_cache.get(cache_key)
        if cached is not None:
            return cached.copy()
        df = self._selected_raw_dataframe()
        if df.empty:
            return df
        if self._is_boolean_population(population_name):
            parent_name, gate_names = self._boolean_population_spec(population_name)
            df = self._population_raw_dataframe(parent_name)
            for gate_name in gate_names:
                gate = self._population_gate(gate_name)
                if gate is None:
                    continue
                transformed = _apply_transform(
                    df,
                    gate["x_channel"],
                    _gate_plot_y_channel(gate),
                    self._gate_x_transform(gate),
                    self._gate_x_cofactor(gate),
                    y_method=self._gate_y_transform(gate),
                    y_cofactor=self._gate_y_cofactor(gate),
                )
                mask = _gate_mask(transformed, gate)
                df = df.loc[mask].copy()
            self._population_raw_cache[cache_key] = df
            return df.copy()
        for gate in self._population_lineage(population_name):
            transformed = _apply_transform(
                df,
                gate["x_channel"],
                _gate_plot_y_channel(gate),
                self._gate_x_transform(gate),
                self._gate_x_cofactor(gate),
                y_method=self._gate_y_transform(gate),
                y_cofactor=self._gate_y_cofactor(gate),
            )
            mask = _gate_mask(transformed, gate)
            df = df.loc[mask].copy()
        self._population_raw_cache[cache_key] = df
        return df.copy()

    def _sample_population_raw_dataframe(self, label, population_name):
        cache_key = (label, population_name)
        cached = self._sample_population_cache.get(cache_key)
        if cached is not None:
            return cached.copy()
        df = self._sample_raw_dataframe(label)
        if df.empty:
            return df
        if self._is_boolean_population(population_name):
            parent_name, gate_names = self._boolean_population_spec(population_name)
            df = self._sample_population_raw_dataframe(label, parent_name)
            for gate_name in gate_names:
                gate = self._population_gate(gate_name)
                if gate is None:
                    continue
                transformed = _apply_transform(
                    df,
                    gate["x_channel"],
                    _gate_plot_y_channel(gate),
                    self._gate_x_transform(gate),
                    self._gate_x_cofactor(gate),
                    y_method=self._gate_y_transform(gate),
                    y_cofactor=self._gate_y_cofactor(gate),
                )
                mask = _gate_mask(transformed, gate)
                df = df.loc[mask].copy()
            self._sample_population_cache[cache_key] = df
            return df.copy()
        for gate in self._population_lineage(population_name):
            transformed = _apply_transform(
                df,
                gate["x_channel"],
                _gate_plot_y_channel(gate),
                self._gate_x_transform(gate),
                self._gate_x_cofactor(gate),
                y_method=self._gate_y_transform(gate),
                y_cofactor=self._gate_y_cofactor(gate),
            )
            mask = _gate_mask(transformed, gate)
            df = df.loc[mask].copy()
        self._sample_population_cache[cache_key] = df
        return df.copy()

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
        cache_key = (
            self._selected_labels_key(),
            self._selected_population_name(),
            self.x_var.get(),
            self.y_var.get(),
            self._plot_x_transform(),
            self._plot_x_cofactor(),
            self._plot_y_transform(),
            self._plot_y_cofactor(),
            self.y_plot_mode_var.get(),
        )
        cached = self._display_cache.get(cache_key)
        if cached is not None:
            raw_df, transformed = cached
            return raw_df.copy(), transformed.copy()

        df = self._population_raw_dataframe(self._selected_population_name())
        if df.empty:
            return df, df
        if self.y_plot_mode_var.get() == "count histogram" or _is_count_axis(self.y_var.get()):
            transformed = pd.DataFrame(index=df.index.copy())
            transformed[self.x_var.get()] = _transform_array(
                df[self.x_var.get()].to_numpy(),
                self._plot_x_transform(),
                self._plot_x_cofactor(),
            )
            transformed["__well__"] = df["__well__"].to_numpy()
        else:
            transformed = _apply_transform(
                df,
                self.x_var.get(),
                self.y_var.get(),
                self._plot_x_transform(),
                self._plot_x_cofactor(),
                y_method=self._plot_y_transform(),
                y_cofactor=self._plot_y_cofactor(),
            )
            transformed["__well__"] = df["__well__"].to_numpy()
        self._display_cache[cache_key] = (df, transformed)
        return df.copy(), transformed.copy()

    def _gate_fraction(self, gate_spec):
        parent_df = self._population_raw_dataframe(gate_spec["parent_population"])
        if parent_df.empty:
            return 0.0, 0, 0
        transformed = _apply_transform(
            parent_df,
            gate_spec["x_channel"],
            _gate_plot_y_channel(gate_spec),
            self._gate_x_transform(gate_spec),
            self._gate_x_cofactor(gate_spec),
            y_method=self._gate_y_transform(gate_spec),
            y_cofactor=self._gate_y_cofactor(gate_spec),
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
                    self._gate_x_transform(lineage_gate),
                    self._gate_x_cofactor(lineage_gate),
                    y_method=self._gate_y_transform(lineage_gate),
                    y_cofactor=self._gate_y_cofactor(lineage_gate),
                )
                mask_parent = _gate_mask(transformed_parent, lineage_gate)
                df = df.loc[mask_parent].copy()
        if df.empty:
            return 0.0, 0, 0
        transformed = _apply_transform(
            df,
            gate_spec["x_channel"],
            _gate_plot_y_channel(gate_spec),
            self._gate_x_transform(gate_spec),
            self._gate_x_cofactor(gate_spec),
            y_method=self._gate_y_transform(gate_spec),
            y_cofactor=self._gate_y_cofactor(gate_spec),
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
        self._update_gate_statistics_panel(gate_name)

    def _update_gate_statistics_panel(self, gate_name):
        lines = []
        if gate_name:
            gate = next((g for g in self.gates if g["name"] == gate_name), None)
            if gate is not None:
                frac, count, total = self._gate_fraction(gate)
                gated_df = self._population_raw_dataframe(gate_name)
                full_df = self._selected_raw_dataframe()
                lines.append(f"Population: {self._population_display_label(gate_name)}")
                lines.append(f"Count: {count} / {total} parent ({100 * frac:.1f}%)")
                lines.append(f"% of all selected events: {100 * count / max(len(full_df), 1):.1f}%")
                fluorescence_channels = [
                    channel for channel in self.channel_names
                    if not any(token in channel for token in ("FSC", "SSC", "Time")) and channel in gated_df.columns
                ]
                for channel in fluorescence_channels[:6]:
                    values = pd.to_numeric(gated_df[channel], errors="coerce").dropna()
                    if values.empty:
                        continue
                    lines.append(
                        f"{channel}: mean {values.mean():.1f}, median {values.median():.1f}, "
                        f"p90 {values.quantile(0.9):.1f}"
                    )
        if not lines:
            lines = ["Select a saved gate to view statistics."]
        self.gate_stats_text.configure(state="normal")
        self.gate_stats_text.delete("1.0", tk.END)
        self.gate_stats_text.insert("1.0", "\n".join(lines))
        self.gate_stats_text.configure(state="disabled")

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
        boolean_defs = self._boolean_population_defs()
        population_names = [gate["name"] for gate in self.gates] + [item["name"] for item in boolean_defs]
        population_labels = ["All Events"] + [self._population_display_label(name) for name in population_names]
        self.heatmap_population_labels = {"All Events": "__all__"}
        for name in population_names:
            self.heatmap_population_labels[self._population_display_label(name)] = name
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
                _sns().heatmap(
                    plate,
                    ax=self.heatmap_ax,
                    cmap="viridis",
                    vmin=0,
                    vmax=100,
                    annot=True,
                    fmt=".1f",
                    cbar_kws={"label": "% positive"},
                )
                self.heatmap_ax.set_title(self._effective_heatmap_title(metric.replace("pct_", "") + " well heatmap"))
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
                _sns().heatmap(
                    plate,
                    ax=self.heatmap_ax,
                    cmap="magma",
                    annot=True,
                    fmt=".1f",
                    cbar_kws={"label": f"MFI {channel}"},
                )
                pop_label = "all events" if population == "__all__" else self._population_display_label(population)
                self.heatmap_ax.set_title(self._effective_heatmap_title(f"MFI {channel} in {pop_label}"))
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
                _sns().heatmap(
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
                self.heatmap_ax.set_title(self._effective_heatmap_title(f"Correlation: {x_channel} vs {y_channel} in {pop_label}"))
            self.heatmap_ax.set_xlabel("Column")
            self.heatmap_ax.set_ylabel("Row")
            self.heatmap_ax.set_xticklabels([str(i) for i in range(1, 13)], rotation=0)
            self.heatmap_ax.set_yticklabels(list("ABCDEFGH"), rotation=0)
            _apply_prism_axis_style(self.heatmap_ax)
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
        hist_bins = max(int(self.hist_bins_var.get()), 1)
        if histogram_mode:
            if len(labels) <= 1:
                self.ax.hist(plotted[self.x_var.get()], bins=hist_bins, histtype="step", linewidth=1.8, color=self.color_cycle[0])
            else:
                for idx, (well, group) in enumerate(plotted.groupby("__well__", sort=False)):
                    self.ax.hist(
                        group[self.x_var.get()],
                        bins=hist_bins,
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
                    if self._gate_x_transform(gate) == self._plot_x_transform() and np.isclose(self._gate_x_cofactor(gate), self._plot_x_cofactor()):
                        if histogram_mode or (
                            self._gate_y_transform(gate) == self._plot_y_transform()
                            and np.isclose(self._gate_y_cofactor(gate), self._plot_y_cofactor())
                        ):
                            _render_gate(self.ax, gate, selected=(gate["name"] == selected_gate))

        if self.pending_gate is not None:
            spec = self._pending_to_gate_spec(preview=True)
            if spec is not None:
                _render_gate(self.ax, spec, selected=True)

        population_name = self._selected_population_name()
        title_name = self._population_display_label(population_name)
        if histogram_mode:
            hist_limits = self._median_histogram_axis_limits(transformed)
            if hist_limits is not None:
                self.ax.set_xlim(hist_limits[0], hist_limits[1])
                self.ax.set_ylim(hist_limits[2], hist_limits[3])
        else:
            scatter_limits = self._effective_scatter_axis_limits(transformed)
            if scatter_limits is not None:
                self.ax.set_xlim(scatter_limits[0], scatter_limits[1])
                self.ax.set_ylim(scatter_limits[2], scatter_limits[3])
        self.ax.set_xlabel(f"{self.x_var.get()} ({self._plot_x_transform()})")
        self.ax.set_ylabel("Count" if histogram_mode else f"{self.y_var.get()} ({self._plot_y_transform()})")
        self.ax.set_title(f"{title_name} | {len(raw_df)} events")
        _apply_prism_axis_style(self.ax)
        _apply_prism_legend_style(self.ax)
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
            "transform": self._plot_x_transform(),
            "cofactor": self._plot_x_cofactor(),
            "x_transform": self._plot_x_transform(),
            "x_cofactor": self._plot_x_cofactor(),
            "y_transform": self._plot_y_transform(),
            "y_cofactor": self._plot_y_cofactor(),
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
        self.rectangle_start_point = None
        gate_type = self.gate_type_var.get()
        if gate_type == "polygon":
            self.selector = PolygonSelector(self.ax, self._on_polygon_complete, useblit=False)
            self.mode_var.set("MODE: drawing polygon gate")
            self.canvas.get_tk_widget().configure(cursor="crosshair")
            self.start_draw_button.configure(text="Drawing...")
            self.gate_status_var.set("Polygon mode active. Click vertices and double-click to finish.")
        elif gate_type == "rectangle":
            self.canvas_click_cid = self.canvas.mpl_connect("button_press_event", self._on_rectangle_click)
            self.mode_var.set("MODE: drawing rectangle gate")
            self.canvas.get_tk_widget().configure(cursor="crosshair")
            self.start_draw_button.configure(text="Drawing...")
            self.gate_status_var.set("Rectangle mode active. Click one corner, then click the opposite corner.")
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

    def _rectangle_vertices(self, start_x, start_y, end_x, end_y):
        x0, x1 = sorted([float(start_x), float(end_x)])
        y0, y1 = sorted([float(start_y), float(end_y)])
        return [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]

    def _on_rectangle_click(self, event):
        if event.inaxes != self.ax or event.xdata is None or event.ydata is None:
            return
        point = (float(event.xdata), float(event.ydata))
        if self.rectangle_start_point is None:
            self.rectangle_start_point = point
            self.gate_status_var.set("Rectangle first corner set. Click the opposite corner to finish.")
            return
        vertices = self._rectangle_vertices(self.rectangle_start_point[0], self.rectangle_start_point[1], point[0], point[1])
        self.pending_gate = PendingGate("rectangle", {"vertices": vertices})
        self.rectangle_start_point = None
        self.gate_status_var.set("Rectangle gate captured. Click Save Gate to keep it.")
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
        self.rectangle_start_point = None
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
            if self._gate_x_transform(gate) != self._plot_x_transform():
                continue
            if not np.isclose(self._gate_x_cofactor(gate), self._plot_x_cofactor()):
                continue
            if not histogram_mode and self._gate_y_transform(gate) != self._plot_y_transform():
                continue
            if not histogram_mode and not np.isclose(self._gate_y_cofactor(gate), self._plot_y_cofactor()):
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
        if gate["gate_type"] in {"polygon", "rectangle"}:
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
            "state_before_drag": self._state_snapshot(),
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
            changed = any(
                current != original
                for current, original in zip(
                    [g for g in self.gates if g.get("gate_group") == next((x.get("gate_group") for x in self.gates if x["name"] == gate_name), None)] or [next((g for g in self.gates if g["name"] == gate_name), {})],
                    self.drag_state.get("originals", [self.drag_state.get("original", {})]),
                )
            )
            if changed:
                self.undo_stack.append(self.drag_state["state_before_drag"])
                if len(self.undo_stack) > self.history_limit:
                    self.undo_stack = self.undo_stack[-self.history_limit:]
            self.drag_state = None
            self.mode_var.set("MODE: idle")
            self.canvas.get_tk_widget().configure(cursor="")
            if changed:
                self._invalidate_computation_cache()
            self._update_gate_summary_panel()
            if changed:
                self.redo_stack.clear()
                self._schedule_autosave()
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

        self._push_undo_state()
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
        self._mark_state_changed("Saved " + "; ".join(summaries))

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
        self.x_transform_var.set(self._gate_x_transform(gate))
        self.x_cofactor_var.set(self._gate_x_cofactor(gate))
        self.y_transform_var.set(self._gate_y_transform(gate))
        self.y_cofactor_var.set(self._gate_y_cofactor(gate))
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
        self._push_undo_state()
        self.gates = [g for g in self.gates if g["name"] != gate_name]
        if self._selected_population_name() == gate_name:
            self.population_var.set("All Events")
        self._refresh_gate_lists()
        self.redraw()
        self._update_gate_summary_panel()
        self._refresh_heatmap_options()
        self.update_heatmap()
        self._mark_state_changed(f"Deleted gate '{gate_name}'.")

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
        for boolean_def in self._boolean_population_defs():
            self.population_labels[self._population_display_label(boolean_def["name"])] = boolean_def["name"]
        if selected_name and selected_name in names:
            idx = names.index(selected_name)
            self.saved_gate_listbox.selection_set(idx)

        population_values = ["All Events"] + list(self.population_labels.keys())[1:]
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
        self._save_session_to_path(filename)
        self._remember_recent_session(filename)
        self.gate_status_var.set(f"Saved session to {filename} and updated last-session defaults")

    def _load_session_from_path(self, filename, payload=None):
        try:
            if payload is None:
                with open(filename) as fh:
                    payload = json.load(fh)
            self._push_undo_state()
            self._apply_session_payload(payload)
            with open(self.last_session_path, "w") as fh:
                json.dump(payload, fh, indent=2)
            self._remember_recent_session(filename)
            self.gate_status_var.set(f"Loaded session from {filename}")
        except Exception as exc:
            self.gate_status_var.set(f"Failed to load session: {type(exc).__name__}: {exc}")

    def load_session(self):
        filename = filedialog.askopenfilename(
            initialdir=self._session_dir(),
            filetypes=[("JSON files", "*.json")],
        )
        if not filename:
            return
        self._load_session_from_path(filename)

    def rename_selected_gate(self):
        gate_name = self._selected_saved_gate_name()
        if not gate_name:
            self.gate_status_var.set("Select a saved gate to rename.")
            return
        gate = next((g for g in self.gates if g["name"] == gate_name), None)
        if gate is None:
            self.gate_status_var.set("Selected gate not found.")
            return
        group = [g for g in self.gates if g.get("gate_group") == gate.get("gate_group")] if gate.get("gate_group") else [gate]
        suffix_regions = {g.get("region") for g in group if g["gate_type"] in {"vertical", "horizontal"}}
        if len(group) == 2 and suffix_regions == {"above", "below"}:
            current_base = gate_name.rsplit("_", 1)[0] if gate_name.endswith(("_above", "_below")) else gate_name
            new_base = simpledialog.askstring("Rename Gate Group", "New base gate name:", initialvalue=current_base, parent=self.root)
            if not new_base:
                return
            new_names = {g["name"]: f"{new_base}_{g['region']}" for g in group}
        else:
            new_name = simpledialog.askstring("Rename Gate", "New gate name:", initialvalue=gate_name, parent=self.root)
            if not new_name:
                return
            new_names = {gate_name: new_name}

        existing = {g["name"] for g in self.gates if g["name"] not in new_names}
        duplicates = [name for name in new_names.values() if name in existing]
        if duplicates:
            self.gate_status_var.set(f"Gate name already exists: {duplicates[0]}")
            return

        self._push_undo_state()
        for g in self.gates:
            old = g["name"]
            if old in new_names:
                g["name"] = new_names[old]
            if g["parent_population"] in new_names:
                g["parent_population"] = new_names[g["parent_population"]]
        selected_name = next(iter(new_names.values()))
        self._refresh_gate_lists(selected_name=selected_name)
        self.redraw()
        self._update_gate_summary_panel()
        self._refresh_heatmap_options()
        self.update_heatmap()
        self._mark_state_changed(f"Renamed gate to {selected_name}.")

    def recolor_selected_gate(self):
        gate_name = self._selected_saved_gate_name()
        if not gate_name:
            self.gate_status_var.set("Select a saved gate to recolor.")
            return
        gate = next((g for g in self.gates if g["name"] == gate_name), None)
        if gate is None:
            self.gate_status_var.set("Selected gate not found.")
            return
        chosen = colorchooser.askcolor(color=gate.get("color", "#1f77b4"), parent=self.root, title="Choose gate color")
        if not chosen or not chosen[1]:
            return
        group = [g for g in self.gates if g.get("gate_group") == gate.get("gate_group")] if gate.get("gate_group") else [gate]
        self._push_undo_state()
        for g in group:
            g["color"] = chosen[1]
        self.redraw()
        self._refresh_gate_lists(selected_name=gate_name)
        self._update_gate_summary_panel()
        self._mark_state_changed(f"Updated gate color for {gate_name}.")

    def copy_gate_names(self):
        names = "\n".join(gate["name"] for gate in self.gates)
        self.root.clipboard_clear()
        self.root.clipboard_append(names)
        self.gate_status_var.set("Copied gate names to clipboard.")

    def open_plate_map_editor(self):
        return _open_plate_map_editor_impl(self)

    def open_exclusion_editor(self):
        return _open_exclusion_editor_impl(self)

    def _summary_dataframe(self):
        if self._summary_cache is not None:
            return self._summary_cache.copy()
        rows = []
        for label, relpath, well in self._included_file_items():
            df = self._sample_raw_dataframe(label)
            row = {"well": well, "source": relpath, "event_count": len(df)}
            row = self._annotate_sample_row(row, well)
            for gate in self.gates:
                frac, count, parent_total = self._gate_fraction_for_label(gate, label)
                row[f"pct_{gate['name']}"] = 100 * frac
                row[f"count_{gate['name']}"] = count
                row[f"parent_count_{gate['name']}"] = parent_total
            rows.append(row)
        summary = pd.DataFrame(rows)
        self._summary_cache = summary
        return summary.copy()

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
        if self._intensity_cache is not None:
            return self._intensity_cache.copy()
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
                        self._gate_x_transform(lineage_gate),
                        self._gate_x_cofactor(lineage_gate),
                        y_method=self._gate_y_transform(lineage_gate),
                        y_cofactor=self._gate_y_cofactor(lineage_gate),
                    )
                    mask = _gate_mask(transformed, lineage_gate)
                    gated_df = gated_df.loc[mask].copy()
                out[f"in_{gate['name']}"] = df.index.isin(gated_df.index)
            frames.append(out)
        intensity = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
        self._intensity_cache = intensity
        return intensity.copy()

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
        return _open_analysis_preview_impl(self)

    def _default_export_dir(self):
        return os.path.join(self._app_home(), "exports")

    def _plate_metadata_dataframe(self):
        rows = []
        for well, meta in sorted(self.plate_metadata.items(), key=lambda item: (item[0][0], int(item[0][1:]))):
            row = {"well": well}
            row.update(meta)
            rows.append(row)
        return pd.DataFrame(rows)

    def _analysis_bundle_paths(self):
        return _analysis_bundle_paths_impl(self)

    def _write_analysis_bundle_csvs(self, bundle_paths):
        return _write_analysis_bundle_csvs_impl(self, bundle_paths)

    def _figure_to_base64(self, fig):
        return _figure_to_base64_impl(fig)

    def _html_img_tag(self, fig, alt_text):
        return _html_img_tag_impl(fig, alt_text)

    def _html_error_section(self, title, exc):
        return _html_error_section_impl(title, exc)

    def _build_html_report_sections(self, summary, intensity, plate):
        return _build_html_report_sections_impl(self, summary, intensity, plate)

    def _analysis_html_document(self, summary, intensity, plate, bundle_paths):
        return _analysis_html_document_impl(self, summary, intensity, plate, bundle_paths)

    def _analysis_notebook_dict(self, summary_relpath, intensity_relpath, plate_relpath, notebook_title):
        return _analysis_notebook_dict_impl(summary_relpath, intensity_relpath, plate_relpath, notebook_title)

    def create_and_open_analysis_notebook(self):
        return _create_and_open_analysis_notebook_impl(self)

    def export_html_report(self):
        return _export_html_report_impl(self)

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
