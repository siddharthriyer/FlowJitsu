import base64
import io
import json
import os
import re
from datetime import datetime
from html import escape

import numpy as np
import pandas as pd
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg, NavigationToolbar2Tk
from matplotlib.figure import Figure
import tkinter as tk
from tkinter import colorchooser, messagebox, ttk


_SNS = None
PRISM_STYLE = {
    "axis_linewidth": 2.0,
    "bar_edge_linewidth": 3.0,
    "legend_linewidth": 1.8,
    "bar_fill": "#9ec9ff",
    "errorbar_capsize": 0.18,
}


def _sns():
    global _SNS
    if _SNS is None:
        import seaborn as sns
        _SNS = sns
    return _SNS


def _apply_prism_axis_style(ax):
    for side in ("left", "bottom"):
        if side in ax.spines:
            ax.spines[side].set_linewidth(PRISM_STYLE["axis_linewidth"])
            ax.spines[side].set_color("#111111")
    for side in ("top", "right"):
        if side in ax.spines:
            ax.spines[side].set_visible(False)
    ax.tick_params(axis="both", which="both", width=PRISM_STYLE["axis_linewidth"], length=6, color="#111111")


def _apply_prism_bar_style(ax):
    for patch in getattr(ax, "patches", []):
        patch.set_facecolor(PRISM_STYLE["bar_fill"])
        patch.set_linewidth(PRISM_STYLE["bar_edge_linewidth"])
        patch.set_edgecolor("#111111")


def _apply_prism_legend_style(ax):
    legend = ax.get_legend()
    if legend is None:
        return
    frame = legend.get_frame()
    frame.set_linewidth(PRISM_STYLE["legend_linewidth"])
    frame.set_edgecolor("#111111")
    frame.set_facecolor("white")
    frame.set_alpha(1)


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

    controls_outer = ttk.Frame(top, padding=(10, 10, 10, 0))
    controls_outer.grid(row=0, column=0, columnspan=2, sticky="ew")
    controls_outer.columnconfigure(0, weight=1)
    controls_outer.rowconfigure(0, weight=1)
    controls_canvas = tk.Canvas(controls_outer, highlightthickness=0, height=128)
    controls_canvas.grid(row=0, column=0, sticky="ew")
    controls_xscroll = ttk.Scrollbar(controls_outer, orient="horizontal", command=controls_canvas.xview)
    controls_xscroll.grid(row=1, column=0, sticky="ew")
    controls_canvas.configure(xscrollcommand=controls_xscroll.set)
    controls = ttk.Frame(controls_canvas, padding=10)
    controls_window = controls_canvas.create_window((0, 0), window=controls, anchor="nw")

    def _sync_controls_scroll(_event=None):
        controls_canvas.configure(scrollregion=controls_canvas.bbox("all"))

    def _resize_controls_window(event):
        min_width = max(event.width, controls.winfo_reqwidth())
        controls_canvas.itemconfigure(controls_window, width=min_width)

    controls.bind("<Configure>", _sync_controls_scroll)
    controls_canvas.bind("<Configure>", _resize_controls_window)

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
    plot_title_var = tk.StringVar(value="")
    x_title_var = tk.StringVar(value="")
    y_title_var = tk.StringVar(value="")
    x_min_var = tk.StringVar(value="")
    x_max_var = tk.StringVar(value="")
    y_min_var = tk.StringVar(value="")
    y_max_var = tk.StringVar(value="")
    normalization_mode_var = tk.StringVar(value="raw_percent")
    control_group_var = tk.StringVar(value="global")
    negative_control_var = tk.StringVar(value="negative_control")
    positive_control_var = tk.StringVar(value="positive_control")
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
    channel_label = ttk.Label(controls, text="Intensity Channel")
    channel_label.grid(row=0, column=4, sticky="w")
    channel_combo = ttk.Combobox(controls, textvariable=channel_var, values=channel_cols, state="readonly", width=22)
    channel_combo.grid(row=1, column=4, padx=4)
    ttk.Label(controls, text="Gate Filter").grid(row=0, column=5, sticky="w")
    ttk.Combobox(controls, textvariable=gate_filter_var, values=[""] + bool_cols, state="readonly", width=22).grid(row=1, column=5, padx=4)
    ttk.Label(controls, text="Dist Hue").grid(row=0, column=6, sticky="w")
    ttk.Combobox(controls, textvariable=hue_dist_var, values=[c for c in ["sample_name", "well", "dose_curve"] if c in intensity.columns], state="readonly", width=16).grid(row=1, column=6, padx=4)
    corr_y_label = ttk.Label(controls, text="Correlation Y")
    corr_y_label.grid(row=0, column=7, sticky="w")
    corr_y_combo = ttk.Combobox(controls, textvariable=corr_channel_y_var, values=channel_cols, state="readonly", width=22)
    corr_y_combo.grid(row=1, column=7, padx=4)
    ttk.Label(controls, text="Bar Metric").grid(row=0, column=8, sticky="w")
    ttk.Combobox(controls, textvariable=normalization_mode_var, values=["raw_percent", "delta_vs_negative", "fold_vs_negative", "percent_of_positive", "minmax_neg_to_pos"], state="readonly", width=20).grid(row=1, column=8, padx=4)
    ttk.Label(controls, text="Control Compare").grid(row=0, column=9, sticky="w")
    ttk.Combobox(controls, textvariable=control_group_var, values=["global", "x_axis", "sample_name", "dose_curve", "treatment_group", "replicate", "well"], state="readonly", width=18).grid(row=1, column=9, padx=4)
    ttk.Label(controls, text="Negative Label").grid(row=0, column=10, sticky="w")
    ttk.Entry(controls, textvariable=negative_control_var, width=18).grid(row=1, column=10, padx=4, sticky="ew")
    ttk.Label(controls, text="Positive Label").grid(row=0, column=11, sticky="w")
    ttk.Entry(controls, textvariable=positive_control_var, width=18).grid(row=1, column=11, padx=4, sticky="ew")
    ttk.Label(controls, text="Plot Title").grid(row=2, column=0, sticky="w", pady=(10, 0))
    ttk.Entry(controls, textvariable=plot_title_var, width=20).grid(row=3, column=0, padx=4, sticky="ew")
    ttk.Label(controls, text="X Title").grid(row=2, column=1, sticky="w", pady=(10, 0))
    ttk.Entry(controls, textvariable=x_title_var, width=20).grid(row=3, column=1, padx=4, sticky="ew")
    ttk.Label(controls, text="Y Title").grid(row=2, column=2, sticky="w", pady=(10, 0))
    ttk.Entry(controls, textvariable=y_title_var, width=20).grid(row=3, column=2, padx=4, sticky="ew")
    ttk.Label(controls, text="X Min").grid(row=2, column=3, sticky="w", pady=(10, 0))
    ttk.Entry(controls, textvariable=x_min_var, width=10).grid(row=3, column=3, padx=4, sticky="ew")
    ttk.Label(controls, text="X Max").grid(row=2, column=4, sticky="w", pady=(10, 0))
    ttk.Entry(controls, textvariable=x_max_var, width=10).grid(row=3, column=4, padx=4, sticky="ew")
    ttk.Label(controls, text="Y Min").grid(row=2, column=5, sticky="w", pady=(10, 0))
    ttk.Entry(controls, textvariable=y_min_var, width=10).grid(row=3, column=5, padx=4, sticky="ew")
    ttk.Label(controls, text="Y Max").grid(row=2, column=6, sticky="w", pady=(10, 0))
    ttk.Entry(controls, textvariable=y_max_var, width=10).grid(row=3, column=6, padx=4, sticky="ew")

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

    palette_outer = ttk.Frame(top, padding=(0, 10, 10, 10))
    palette_outer.grid(row=1, column=1, sticky="ns")
    palette_outer.columnconfigure(0, weight=1)
    palette_outer.rowconfigure(0, weight=1)
    palette_canvas = tk.Canvas(palette_outer, highlightthickness=0, width=360)
    palette_canvas.grid(row=0, column=0, sticky="ns")
    palette_scroll = ttk.Scrollbar(palette_outer, orient="vertical", command=palette_canvas.yview)
    palette_scroll.grid(row=0, column=1, sticky="ns")
    palette_canvas.configure(yscrollcommand=palette_scroll.set)
    palette_frame = ttk.LabelFrame(palette_canvas, text="Sample Palette Groups", padding=10)
    palette_window = palette_canvas.create_window((0, 0), window=palette_frame, anchor="nw")
    palette_frame.columnconfigure(0, weight=1)

    def _sync_palette_scroll(_event=None):
        palette_canvas.configure(scrollregion=palette_canvas.bbox("all"))

    def _resize_palette_window(_event=None):
        palette_canvas.itemconfigure(palette_window, width=palette_canvas.winfo_width())

    def _on_palette_mousewheel(event):
        palette_canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")

    palette_frame.bind("<Configure>", _sync_palette_scroll)
    palette_canvas.bind("<Configure>", _resize_palette_window)
    palette_canvas.bind("<MouseWheel>", _on_palette_mousewheel)
    palette_frame.bind("<MouseWheel>", _on_palette_mousewheel)

    ttk.Label(palette_frame, text="Check samples, move them into a target group, and assign any seaborn or matplotlib palette name to that group.", wraplength=300).grid(row=0, column=0, sticky="w", pady=(0, 8))
    ttk.Label(palette_frame, textvariable=drag_status_var, wraplength=300).grid(row=1, column=0, sticky="w", pady=(0, 8))

    move_row = ttk.Frame(palette_frame)
    move_row.grid(row=2, column=0, sticky="ew", pady=(0, 10))
    ttk.Label(move_row, text="Move Selected To").grid(row=0, column=0, sticky="w")
    ttk.Combobox(move_row, textvariable=group_move_var, values=["Ungrouped"] + group_order, state="readonly", width=14).grid(row=0, column=1, padx=6)

    def _group_samples(group_name):
        return sorted([sample for sample, assigned in sample_group.items() if assigned == group_name])

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
            return _sns().color_palette(palette_name, max(n_colors, 1)).as_hex()
        except Exception:
            drag_status_var.set(f"Palette '{palette_name}' not found. Falling back to tab10.")
            return _sns().color_palette("tab10", max(n_colors, 1)).as_hex()

    def _palette_for_hue(hue_values):
        if hue_values != "sample_name":
            return None
        palette = {}
        for group_name in group_boxes:
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
        ttk.Label(frame, text="Palette" if group_name != "Ungrouped" else "Default palette").grid(row=0, column=0, sticky="w")
        palette_combo = ttk.Combobox(frame, textvariable=group_palette_vars[group_name], values=palette_options, state="normal", width=16)
        palette_combo.grid(row=0, column=1, sticky="e")
        palette_combo.bind("<<ComboboxSelected>>", lambda _event: redraw_preview())
        palette_combo.bind("<Return>", lambda _event: redraw_preview())
        palette_combo.bind("<FocusOut>", lambda _event: redraw_preview())
        ttk.Label(frame, textvariable=count_var).grid(row=1, column=0, columnspan=2, sticky="w", pady=(4, 4))
        sample_frame = ttk.Frame(frame)
        sample_frame.grid(row=2, column=0, columnspan=2, sticky="ew")
        ttk.Label(frame, text="Check samples below, then use Move Selected To").grid(row=3, column=0, columnspan=2, sticky="w", pady=(4, 0))
        group_boxes[group_name] = {"frame": frame, "sample_frame": sample_frame, "count_var": count_var}

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
                    ttk.Checkbutton(widgets["sample_frame"], text=sample, variable=sample_selected[sample], command=lambda s=sample, g=group_name: _update_selection_status(s, g)).grid(row=idx, column=0, sticky="w")
        if "redraw_preview" in locals():
            redraw_preview()

    ttk.Button(move_row, text="Move", command=_move_selected).grid(row=0, column=2, padx=6)
    _add_group_box(palette_frame, 3, "Ungrouped")
    for idx, group_name in enumerate(group_order, start=4):
        _add_group_box(palette_frame, idx, group_name)
    ttk.Button(palette_frame, text="Reset Grouping", command=_clear_grouping).grid(row=len(group_order) + 4, column=0, sticky="ew", pady=(8, 0))
    if not sample_names:
        ttk.Label(palette_frame, text="No sample names available yet.").grid(row=len(group_order) + 5, column=0, sticky="w", pady=(8, 0))

    def _parse_limit(value):
        value = str(value).strip()
        if not value:
            return None
        return float(value)

    def _open_advanced_settings():
        dialog = tk.Toplevel(top)
        dialog.title("Advanced Settings")
        dialog.transient(top)
        dialog.grab_set()
        dialog.columnconfigure(1, weight=1)

        axis_var = tk.StringVar(value=str(PRISM_STYLE["axis_linewidth"]))
        bar_edge_var = tk.StringVar(value=str(PRISM_STYLE["bar_edge_linewidth"]))
        legend_var = tk.StringVar(value=str(PRISM_STYLE["legend_linewidth"]))
        fill_var = tk.StringVar(value=str(PRISM_STYLE["bar_fill"]))
        capsize_var = tk.StringVar(value=str(PRISM_STYLE["errorbar_capsize"]))

        ttk.Label(dialog, text="Axis line width").grid(row=0, column=0, sticky="w", padx=10, pady=(10, 6))
        ttk.Entry(dialog, textvariable=axis_var, width=12).grid(row=0, column=1, sticky="ew", padx=10, pady=(10, 6))
        ttk.Label(dialog, text="Bar outline width").grid(row=1, column=0, sticky="w", padx=10, pady=6)
        ttk.Entry(dialog, textvariable=bar_edge_var, width=12).grid(row=1, column=1, sticky="ew", padx=10, pady=6)
        ttk.Label(dialog, text="Legend outline width").grid(row=2, column=0, sticky="w", padx=10, pady=6)
        ttk.Entry(dialog, textvariable=legend_var, width=12).grid(row=2, column=1, sticky="ew", padx=10, pady=6)
        ttk.Label(dialog, text="Bar fill color").grid(row=3, column=0, sticky="w", padx=10, pady=6)
        color_row = ttk.Frame(dialog)
        color_row.grid(row=3, column=1, sticky="ew", padx=10, pady=6)
        color_row.columnconfigure(0, weight=1)
        ttk.Entry(color_row, textvariable=fill_var, width=14).grid(row=0, column=0, sticky="ew")
        ttk.Label(dialog, text="Error bar cap size").grid(row=4, column=0, sticky="w", padx=10, pady=6)
        ttk.Entry(dialog, textvariable=capsize_var, width=12).grid(row=4, column=1, sticky="ew", padx=10, pady=6)

        def _choose_fill():
            chosen = colorchooser.askcolor(color=fill_var.get(), parent=dialog, title="Choose bar fill color")
            if chosen and chosen[1]:
                fill_var.set(chosen[1])

        ttk.Button(color_row, text="Pick", command=_choose_fill).grid(row=0, column=1, padx=(6, 0))

        def _apply_settings():
            try:
                axis_width = float(axis_var.get())
                bar_edge_width = float(bar_edge_var.get())
                legend_width = float(legend_var.get())
                capsize = float(capsize_var.get())
            except ValueError:
                messagebox.showerror("Invalid Settings", "Line widths and cap size must be numeric.", parent=dialog)
                return
            if axis_width <= 0 or bar_edge_width <= 0 or legend_width <= 0:
                messagebox.showerror("Invalid Settings", "Line widths must be greater than zero.", parent=dialog)
                return
            if capsize < 0:
                messagebox.showerror("Invalid Settings", "Cap size must be zero or greater.", parent=dialog)
                return
            fill = fill_var.get().strip()
            if not fill:
                messagebox.showerror("Invalid Settings", "Bar fill color cannot be empty.", parent=dialog)
                return
            PRISM_STYLE["axis_linewidth"] = axis_width
            PRISM_STYLE["bar_edge_linewidth"] = bar_edge_width
            PRISM_STYLE["legend_linewidth"] = legend_width
            PRISM_STYLE["bar_fill"] = fill
            PRISM_STYLE["errorbar_capsize"] = capsize
            dialog.destroy()
            redraw_preview()

        button_row = ttk.Frame(dialog)
        button_row.grid(row=5, column=0, columnspan=2, sticky="e", padx=10, pady=(10, 10))
        ttk.Button(button_row, text="Apply", command=_apply_settings).grid(row=0, column=0)
        ttk.Button(button_row, text="Close", command=dialog.destroy).grid(row=0, column=1, padx=(6, 0))

    ttk.Button(controls, text="Advanced Settings", command=_open_advanced_settings).grid(row=1, column=8, padx=(10, 4), sticky="e")

    def _apply_plot_formatting(default_title=None, default_xlabel=None, default_ylabel=None):
        title = plot_title_var.get().strip() or default_title
        xlabel = x_title_var.get().strip() or default_xlabel
        ylabel = y_title_var.get().strip() or default_ylabel
        if title:
            ax.set_title(title)
        if xlabel:
            ax.set_xlabel(xlabel)
        if ylabel:
            ax.set_ylabel(ylabel)
        try:
            xmin = _parse_limit(x_min_var.get()); xmax = _parse_limit(x_max_var.get())
            if xmin is not None or xmax is not None:
                current_min, current_max = ax.get_xlim()
                ax.set_xlim(xmin if xmin is not None else current_min, xmax if xmax is not None else current_max)
            ymin = _parse_limit(y_min_var.get()); ymax = _parse_limit(y_max_var.get())
            if ymin is not None or ymax is not None:
                current_min, current_max = ax.get_ylim()
                ax.set_ylim(ymin if ymin is not None else current_min, ymax if ymax is not None else current_max)
        except ValueError:
            pass
        _apply_prism_axis_style(ax)
        _apply_prism_bar_style(ax)
        _apply_prism_legend_style(ax)

    def _update_plot_control_visibility(*_args):
        mode = plot_mode_var.get()
        if mode == "correlation":
            channel_label.configure(text="Correlation X")
            corr_y_label.grid()
            corr_y_combo.grid()
        else:
            channel_label.configure(text="Intensity Channel")
            corr_y_label.grid_remove()
            corr_y_combo.grid_remove()

    def _control_group_key(row, xcol):
        mode = control_group_var.get()
        if mode == "global":
            return "__global__"
        if mode == "x_axis":
            return row.get(xcol, "")
        return row.get(mode, "")

    def _normalized_bar_dataframe(plot_df, value_col, xcol):
        mode = normalization_mode_var.get()
        if mode == "raw_percent":
            return plot_df, value_col, "% positive", None

        normalized = plot_df.copy()
        normalized["_control_group"] = normalized.apply(lambda row: _control_group_key(row, xcol), axis=1)
        neg_label = negative_control_var.get().strip()
        pos_label = positive_control_var.get().strip()
        neg_means = {}
        pos_means = {}
        if neg_label:
            neg_rows = normalized[normalized["sample_type"].astype(str).str.strip() == neg_label]
            neg_means = neg_rows.groupby("_control_group")[value_col].mean().to_dict() if not neg_rows.empty else {}
        if pos_label:
            pos_rows = normalized[normalized["sample_type"].astype(str).str.strip() == pos_label]
            pos_means = pos_rows.groupby("_control_group")[value_col].mean().to_dict() if not pos_rows.empty else {}

        out_col = f"{value_col}__normalized"

        def _convert(row):
            value = row[value_col]
            group_key = row["_control_group"]
            neg = neg_means.get(group_key)
            pos = pos_means.get(group_key)
            if mode == "delta_vs_negative":
                return np.nan if neg is None else value - neg
            if mode == "fold_vs_negative":
                return np.nan if neg in (None, 0) else value / neg
            if mode == "percent_of_positive":
                return np.nan if pos in (None, 0) else 100.0 * value / pos
            if mode == "minmax_neg_to_pos":
                if neg is None or pos is None or np.isclose(pos, neg):
                    return np.nan
                return 100.0 * (value - neg) / (pos - neg)
            return value

        normalized[out_col] = normalized.apply(_convert, axis=1)
        normalized = normalized.dropna(subset=[out_col]).copy()

        labels = {
            "delta_vs_negative": ("% positive - negative control", "Delta vs negative control"),
            "fold_vs_negative": ("Fold vs negative control", "Fold vs negative control"),
            "percent_of_positive": ("% of positive control", "Percent of positive control"),
            "minmax_neg_to_pos": ("Normalized 0-100", "Normalized between negative and positive controls"),
        }
        ylabel, title = labels.get(mode, ("% positive", None))
        if normalized.empty:
            return normalized, out_col, ylabel, "No matching controls found for the selected normalization mode."
        return normalized, out_col, ylabel, title

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
            plot_df, ycol, y_label, normalization_title = _normalized_bar_dataframe(plot_df, pct_col_var.get(), xcol)
            if plot_df.empty:
                ax.set_title(normalization_title or "No bar data available")
                canvas.draw_idle()
                return
            if huecol == "sample_name":
                _sns().barplot(data=plot_df, x=xcol, y=ycol, hue=huecol, palette=_palette_for_hue("sample_name"), capsize=PRISM_STYLE["errorbar_capsize"], ax=ax)
            elif huecol is None and xcol == "sample_name":
                sample_palette = _palette_for_hue("sample_name") or {}
                order = list(plot_df[xcol].dropna().astype(str).unique())
                colors = [sample_palette.get(name, PRISM_STYLE["bar_fill"]) for name in order]
                _sns().barplot(data=plot_df, x=xcol, y=ycol, order=order, palette=colors, saturation=1, capsize=PRISM_STYLE["errorbar_capsize"], ax=ax)
            else:
                _sns().barplot(data=plot_df, x=xcol, y=ycol, hue=huecol, color=PRISM_STYLE["bar_fill"], saturation=1, capsize=PRISM_STYLE["errorbar_capsize"], ax=ax)
            default_title = normalization_title or (pct_col_var.get().replace("pct_", "") if pct_col_var.get() else "Percent Positive")
            _apply_plot_formatting(default_title=default_title, default_xlabel=xcol, default_ylabel=y_label)
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
                ax.set_title("No correlation Y channel selected"); canvas.draw_idle(); return
            if channel_var.get() == corr_channel_y_var.get():
                ax.set_title("Choose two different channels"); canvas.draw_idle(); return
            xcol = x_axis_var.get() if x_axis_var.get() in plot_df.columns else "well"
            huecol = hue_var.get() if hue_var.get() in plot_df.columns and hue_var.get() else None
            group_cols = [xcol] + ([huecol] if huecol and huecol != xcol else [])
            corr_rows = []
            for group_key, group in plot_df.groupby(group_cols, dropna=False):
                corr_input = group[[channel_var.get(), corr_channel_y_var.get()]].apply(pd.to_numeric, errors="coerce").dropna()
                corr_value = np.nan if len(corr_input) < 2 else corr_input[channel_var.get()].corr(corr_input[corr_channel_y_var.get()])
                if not isinstance(group_key, tuple):
                    group_key = (group_key,)
                row = {group_cols[idx]: group_key[idx] for idx in range(len(group_cols))}
                row["correlation"] = float(corr_value) if pd.notna(corr_value) else np.nan
                corr_rows.append(row)
            corr_df = pd.DataFrame(corr_rows).dropna(subset=["correlation"])
            if corr_df.empty:
                ax.set_title("No valid correlations after filtering"); canvas.draw_idle(); return
            if huecol == "sample_name":
                _sns().barplot(data=corr_df, x=xcol, y="correlation", hue=huecol, palette=_palette_for_hue("sample_name"), capsize=PRISM_STYLE["errorbar_capsize"], ax=ax)
            else:
                _sns().barplot(data=corr_df, x=xcol, y="correlation", hue=huecol, color=PRISM_STYLE["bar_fill"], saturation=1, capsize=PRISM_STYLE["errorbar_capsize"], ax=ax)
            ax.set_ylim(-1.05, 1.05); ax.axhline(0, color="#666666", linewidth=1.6, linestyle="--"); ax.tick_params(axis="x", rotation=45)
            _apply_plot_formatting(default_title=f"Correlation: {channel_var.get()} vs {corr_channel_y_var.get()}", default_xlabel=xcol, default_ylabel="correlation")
            fig.tight_layout(); canvas.draw_idle(); return
        group_col = huecol or "__distribution_group__"
        if group_col == "__distribution_group__":
            plot_df[group_col] = "All Events"
        palette = _palette_for_hue(group_col) if group_col == "sample_name" else None
        violin_kwargs = {
            "data": plot_df,
            "x": group_col,
            "y": channel_var.get(),
            "ax": ax,
            "cut": 0,
            "inner": "quart",
            "linewidth": 1.6,
        }
        if palette is not None:
            violin_kwargs["palette"] = palette
        else:
            violin_kwargs["color"] = PRISM_STYLE["bar_fill"]
        _sns().violinplot(**violin_kwargs)
        ax.set_yscale("log")
        ax.tick_params(axis="x", rotation=45)
        _apply_plot_formatting(default_title="Fluorescence distribution", default_xlabel=("" if group_col == "__distribution_group__" else group_col), default_ylabel=channel_var.get())
        fig.tight_layout()
        canvas.draw_idle()

    plot_mode_var.trace_add("write", _update_plot_control_visibility)
    _update_plot_control_visibility()

    for var in [plot_mode_var, pct_col_var, x_axis_var, hue_var, channel_var, corr_channel_y_var, gate_filter_var, hue_dist_var, plot_title_var, x_title_var, y_title_var, x_min_var, x_max_var, y_min_var, y_max_var, normalization_mode_var, control_group_var, negative_control_var, positive_control_var]:
        var.trace_add("write", redraw_preview)
    _refresh_group_boxes()
    redraw_preview()


def analysis_bundle_paths(self):
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    date_label = datetime.now().strftime("%Y-%m-%d")
    export_root = self._default_export_dir()
    export_dir = os.path.join(export_root, timestamp)
    os.makedirs(export_dir, exist_ok=True)
    return {
        "timestamp": timestamp,
        "date_label": date_label,
        "export_dir": export_dir,
        "summary_path": os.path.join(export_dir, "flow_gate_summary.csv"),
        "intensity_path": os.path.join(export_dir, "flow_intensity_distribution.csv"),
        "plate_path": os.path.join(export_dir, "plate_metadata.csv"),
        "html_path": os.path.join(export_dir, f"{date_label}_flow_desktop_report.html"),
        "notebook_path": os.path.join(self._app_home(), f"{date_label}_flow_desktop_analysis.ipynb"),
    }


def write_analysis_bundle_csvs(self, bundle_paths):
    summary = self._summary_dataframe()
    intensity = self._intensity_distribution_dataframe()
    plate = self._plate_metadata_dataframe()
    summary.to_csv(bundle_paths["summary_path"], index=False)
    intensity.to_csv(bundle_paths["intensity_path"], index=False)
    plate.to_csv(bundle_paths["plate_path"], index=False)
    return summary, intensity, plate


def figure_to_base64(fig):
    buffer = io.BytesIO()
    fig.savefig(buffer, format="png", dpi=140, bbox_inches="tight")
    buffer.seek(0)
    return base64.b64encode(buffer.read()).decode("ascii")


def html_img_tag(fig, alt_text):
    encoded = figure_to_base64(fig)
    return f'<img alt="{escape(alt_text)}" src="data:image/png;base64,{encoded}" style="max-width: 100%; height: auto; border: 1px solid #ddd; border-radius: 6px;" />'


def html_error_section(title, exc):
    return f"<section><h2>{escape(title)}</h2><p>Skipped this section: {escape(type(exc).__name__)}: {escape(str(exc))}</p></section>"


def build_html_report_sections(self, summary, intensity, plate):
    sections = []
    sections.append("<section><h2>Summary</h2>" f"<p>Samples: {len(summary)} | Gates: {len([c for c in summary.columns if c.startswith('pct_')])} | Events rows: {len(intensity)}</p></section>")
    if not summary.empty:
        sections.append(f"<section><h2>Gate Summary Table</h2>{summary.head(24).to_html(index=False, classes='dataframe', border=0)}</section>")
    if not plate.empty:
        sections.append(f"<section><h2>Plate Metadata</h2>{plate.head(96).to_html(index=False, classes='dataframe', border=0)}</section>")
    pct_cols = [c for c in summary.columns if c.startswith("pct_")]
    if pct_cols:
        pct_col = pct_cols[0]
        try:
            fig = Figure(figsize=(10, 4.8), dpi=100); ax = fig.add_subplot(111)
            xcol = "sample_name" if "sample_name" in summary.columns else "well"
            _sns().barplot(data=summary, x=xcol, y=pct_col, color=PRISM_STYLE["bar_fill"], saturation=1, capsize=PRISM_STYLE["errorbar_capsize"], ax=ax)
            _apply_prism_axis_style(ax)
            _apply_prism_bar_style(ax)
            ax.set_ylabel("% positive"); ax.tick_params(axis="x", rotation=45); ax.set_title(f"{pct_col.replace('pct_', '')} % positive"); fig.tight_layout()
            sections.append(f"<section><h2>Percent Positive</h2>{html_img_tag(fig, pct_col)}</section>")
        except Exception as exc:
            sections.append(html_error_section("Percent Positive", exc))
    return "\n".join(sections)


def analysis_html_document(self, summary, intensity, plate, bundle_paths):
    body = build_html_report_sections(self, summary, intensity, plate)
    summary_relpath = os.path.relpath(bundle_paths["summary_path"], os.path.dirname(bundle_paths["html_path"]))
    intensity_relpath = os.path.relpath(bundle_paths["intensity_path"], os.path.dirname(bundle_paths["html_path"]))
    plate_relpath = os.path.relpath(bundle_paths["plate_path"], os.path.dirname(bundle_paths["html_path"]))
    title = f"{bundle_paths['date_label']} Flow Desktop Report"
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8" /><meta name="viewport" content="width=device-width, initial-scale=1" /><title>{escape(title)}</title>
<style>body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; margin: 24px; line-height: 1.4; color: #1d1d1f; }} h1, h2 {{ margin-bottom: 0.4rem; }} section {{ margin: 28px 0; }} .paths code {{ background: #f4f4f4; padding: 2px 6px; border-radius: 4px; }} table.dataframe {{ border-collapse: collapse; font-size: 0.92rem; }} table.dataframe th, table.dataframe td {{ border: 1px solid #ddd; padding: 6px 8px; }} table.dataframe th {{ background: #f7f7f7; }}</style>
</head><body><h1>{escape(title)}</h1><p>Static analysis report exported from FlowJitsu. The raw data tables for this run are saved alongside this report.</p><div class="paths"><p><strong>CSV exports:</strong> <code>{escape(summary_relpath)}</code>, <code>{escape(intensity_relpath)}</code>, <code>{escape(plate_relpath)}</code></p></div>{body}</body></html>"""


def analysis_notebook_dict(summary_relpath, intensity_relpath, plate_relpath, notebook_title):
    cells = [
        {"cell_type": "markdown", "metadata": {}, "source": [f"# {notebook_title}\n", "\n", "This notebook loads the CSVs exported from the desktop gating UI and provides example plots for downstream analysis.\n"]},
        {"cell_type": "code", "execution_count": None, "metadata": {}, "outputs": [], "source": ["import pandas as pd\n", "import numpy as np\n", "import matplotlib.pyplot as plt\n", "import seaborn as sns\n", "from pathlib import Path\n", "\n", "sns.set_context('talk')\n", "sns.set_style('whitegrid')\n", "plt.rcParams['axes.linewidth'] = 2.0\n", "plt.rcParams['xtick.major.width'] = 2.0\n", "plt.rcParams['ytick.major.width'] = 2.0\n", "plt.rcParams['legend.framealpha'] = 1.0\n", "plt.rcParams['legend.edgecolor'] = '#111111'\n", "DEFAULT_BAR_FILL = '#9ec9ff'\n"]},
        {"cell_type": "code", "execution_count": None, "metadata": {}, "outputs": [], "source": [f"summary_path = Path('{summary_relpath}')\n", f"intensity_path = Path('{intensity_relpath}')\n", f"plate_path = Path('{plate_relpath}')\n", "\n", "summary = pd.read_csv(summary_path)\n", "intensity = pd.read_csv(intensity_path)\n", "plate = pd.read_csv(plate_path) if plate_path.exists() and plate_path.stat().st_size > 0 else pd.DataFrame()\n", "\n", "summary.head()\n"]},
    ]
    return {"cells": cells, "metadata": {"kernelspec": {"display_name": "Python 3", "language": "python", "name": "python3"}, "language_info": {"name": "python", "version": "3.10"}}, "nbformat": 4, "nbformat_minor": 5}


def create_and_open_analysis_notebook(self):
    try:
        bundle_paths = analysis_bundle_paths(self)
        write_analysis_bundle_csvs(self, bundle_paths)
        nb = analysis_notebook_dict(
            summary_relpath=os.path.relpath(bundle_paths["summary_path"], os.path.dirname(bundle_paths["notebook_path"])),
            intensity_relpath=os.path.relpath(bundle_paths["intensity_path"], os.path.dirname(bundle_paths["notebook_path"])),
            plate_relpath=os.path.relpath(bundle_paths["plate_path"], os.path.dirname(bundle_paths["notebook_path"])),
            notebook_title=f"{bundle_paths['date_label']} Flow Desktop Analysis",
        )
        with open(bundle_paths["notebook_path"], "w") as fh:
            json.dump(nb, fh, indent=1)
        self.gate_status_var.set(f"Saved notebook: {bundle_paths['notebook_path']} | CSVs: {bundle_paths['summary_path']}, {bundle_paths['intensity_path']}, {bundle_paths['plate_path']}")
    except Exception as exc:
        self.gate_status_var.set(f"Failed to create analysis notebook: {type(exc).__name__}: {exc}")


def export_html_report(self):
    try:
        bundle_paths = analysis_bundle_paths(self)
        summary, intensity, plate = write_analysis_bundle_csvs(self, bundle_paths)
        html_document = analysis_html_document(self, summary, intensity, plate, bundle_paths)
        with open(bundle_paths["html_path"], "w", encoding="utf-8") as fh:
            fh.write(html_document)
        self.gate_status_var.set(f"Saved HTML report: {bundle_paths['html_path']} | CSVs: {bundle_paths['summary_path']}, {bundle_paths['intensity_path']}, {bundle_paths['plate_path']}")
    except Exception as exc:
        self.gate_status_var.set(f"Failed to export HTML report: {type(exc).__name__}: {exc}")
