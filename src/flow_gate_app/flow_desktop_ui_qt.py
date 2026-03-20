import io
import json
import os
import re
import sys
import urllib.request
import webbrowser
from urllib.error import HTTPError

import matplotlib
import numpy as np
import pandas as pd

matplotlib.use("QtAgg")

from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg, NavigationToolbar2QT
from matplotlib.figure import Figure
from matplotlib.path import Path
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QApplication,
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QColorDialog,
    QDoubleSpinBox,
    QDialog,
    QFileDialog,
    QFrame,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QRadioButton,
    QScrollArea,
    QSlider,
    QSpinBox,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from ._app_version import __version__
from .analysis_views import (
    analysis_bundle_paths as _analysis_bundle_paths_impl,
    analysis_html_document as _analysis_html_document_impl,
    analysis_notebook_dict as _analysis_notebook_dict_impl,
    write_analysis_bundle_csvs as _write_analysis_bundle_csvs_impl,
)
from .helpers import (
    APP_BRAND,
    GITHUB_LATEST_RELEASE_API,
    GITHUB_RELEASES_URL,
    PendingGate,
    apply_transform as _apply_transform,
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
    render_gate as _render_gate,
    transform_array as _transform_array,
    version_key as _version_key,
)


class AnalysisPreviewDialog(QDialog):
    def __init__(self, parent, summary, intensity):
        super().__init__(parent)
        self.summary = summary.copy()
        self.intensity = intensity.copy()
        self.sample_names = sorted({
            str(value).strip()
            for value in pd.concat(
                [
                    self.summary["sample_name"] if "sample_name" in self.summary.columns else pd.Series(dtype=object),
                    self.intensity["sample_name"] if "sample_name" in self.intensity.columns else pd.Series(dtype=object),
                ],
                ignore_index=True,
            ).dropna()
            if str(value).strip()
        })
        self.group_order = ["Ungrouped", "Group 1", "Group 2", "Group 3", "Group 4"]
        self.sample_group = {sample: "Ungrouped" for sample in self.sample_names}
        self.group_palette = {
            "Ungrouped": "tab10",
            "Group 1": "deep",
            "Group 2": "Set2",
            "Group 3": "Set3",
            "Group 4": "colorblind",
        }
        self.group_palette_widgets = {}
        self.setWindowTitle("Analysis Preview")
        self.resize(1280, 860)
        self._build_ui()
        self.redraw()

    def _build_ui(self):
        layout = QVBoxLayout(self)

        controls = QGridLayout()
        layout.addLayout(controls)

        pct_cols = [col for col in self.summary.columns if col.startswith("pct_")]
        metadata_cols = {"well", "source", "sample_name", "treatment_group", "dose_curve", "dose", "replicate", "sample_type", "dose_direction", "excluded"}
        bool_cols = [col for col in self.intensity.columns if col.startswith("in_")]
        channel_cols = [col for col in self.intensity.columns if col not in metadata_cols and col not in bool_cols]
        x_axis_values = [col for col in ["sample_name", "well", "dose_curve", "dose"] if col in self.summary.columns]
        hue_values = [""] + [col for col in ["sample_name", "replicate", "dose_curve"] if col in self.summary.columns or col in self.intensity.columns]
        dist_hue_values = [""] + [col for col in ["sample_name", "well", "dose_curve"] if col in self.intensity.columns]

        controls.addWidget(QLabel("Mode"), 0, 0)
        self.mode_combo = QComboBox()
        self.mode_combo.addItems(["bar", "line", "distribution", "correlation"])
        self.mode_combo.currentIndexChanged.connect(self._on_mode_changed)
        controls.addWidget(self.mode_combo, 1, 0)

        controls.addWidget(QLabel("% Column"), 0, 1)
        self.pct_combo = QComboBox()
        self.pct_combo.addItems(pct_cols)
        self.pct_combo.currentIndexChanged.connect(self.redraw)
        controls.addWidget(self.pct_combo, 1, 1)

        controls.addWidget(QLabel("Bar X"), 0, 2)
        self.x_axis_combo = QComboBox()
        self.x_axis_combo.addItems(x_axis_values)
        self.x_axis_combo.currentIndexChanged.connect(self.redraw)
        controls.addWidget(self.x_axis_combo, 1, 2)

        controls.addWidget(QLabel("Hue"), 0, 3)
        self.hue_combo = QComboBox()
        self.hue_combo.addItems(hue_values)
        self.hue_combo.currentIndexChanged.connect(self.redraw)
        controls.addWidget(self.hue_combo, 1, 3)

        controls.addWidget(QLabel("Channel"), 0, 4)
        self.channel_combo = QComboBox()
        self.channel_combo.addItems(channel_cols)
        self.channel_combo.currentIndexChanged.connect(self.redraw)
        controls.addWidget(self.channel_combo, 1, 4)

        controls.addWidget(QLabel("Gate Filter"), 0, 5)
        self.gate_filter_combo = QComboBox()
        self.gate_filter_combo.addItems([""] + bool_cols)
        self.gate_filter_combo.currentIndexChanged.connect(self.redraw)
        controls.addWidget(self.gate_filter_combo, 1, 5)

        controls.addWidget(QLabel("Dist Hue"), 0, 6)
        self.hue_dist_combo = QComboBox()
        self.hue_dist_combo.addItems(dist_hue_values)
        self.hue_dist_combo.currentIndexChanged.connect(self.redraw)
        controls.addWidget(self.hue_dist_combo, 1, 6)

        controls.addWidget(QLabel("Correlation Y"), 0, 7)
        self.corr_y_combo = QComboBox()
        self.corr_y_combo.addItems(channel_cols)
        if len(channel_cols) > 1:
            self.corr_y_combo.setCurrentIndex(1)
        self.corr_y_combo.currentIndexChanged.connect(self.redraw)
        controls.addWidget(self.corr_y_combo, 1, 7)

        controls.addWidget(QLabel("Bar Metric"), 2, 0)
        self.normalization_combo = QComboBox()
        self.normalization_combo.addItems(["raw_percent", "delta_vs_negative", "fold_vs_negative", "percent_of_positive", "minmax_neg_to_pos"])
        self.normalization_combo.currentIndexChanged.connect(self.redraw)
        controls.addWidget(self.normalization_combo, 3, 0)

        controls.addWidget(QLabel("Control Compare"), 2, 1)
        self.control_group_combo = QComboBox()
        self.control_group_combo.addItems(["global", "x_axis", "sample_name", "dose_curve", "treatment_group", "replicate", "well"])
        self.control_group_combo.currentIndexChanged.connect(self.redraw)
        controls.addWidget(self.control_group_combo, 3, 1)

        controls.addWidget(QLabel("Negative Label"), 2, 2)
        self.negative_control_edit = QLineEdit("negative_control")
        self.negative_control_edit.editingFinished.connect(self.redraw)
        controls.addWidget(self.negative_control_edit, 3, 2)

        controls.addWidget(QLabel("Positive Label"), 2, 3)
        self.positive_control_edit = QLineEdit("positive_control")
        self.positive_control_edit.editingFinished.connect(self.redraw)
        controls.addWidget(self.positive_control_edit, 3, 3)

        controls.addWidget(QLabel("Plot Title"), 2, 4)
        self.plot_title_edit = QLineEdit("")
        self.plot_title_edit.editingFinished.connect(self.redraw)
        controls.addWidget(self.plot_title_edit, 3, 4)

        controls.addWidget(QLabel("X Title"), 2, 5)
        self.x_title_edit = QLineEdit("")
        self.x_title_edit.editingFinished.connect(self.redraw)
        controls.addWidget(self.x_title_edit, 3, 5)

        controls.addWidget(QLabel("Y Title"), 2, 6)
        self.y_title_edit = QLineEdit("")
        self.y_title_edit.editingFinished.connect(self.redraw)
        controls.addWidget(self.y_title_edit, 3, 6)

        controls.addWidget(QLabel("X Min"), 4, 0)
        self.x_min_edit = QLineEdit("")
        self.x_min_edit.editingFinished.connect(self.redraw)
        controls.addWidget(self.x_min_edit, 5, 0)

        controls.addWidget(QLabel("X Max"), 4, 1)
        self.x_max_edit = QLineEdit("")
        self.x_max_edit.editingFinished.connect(self.redraw)
        controls.addWidget(self.x_max_edit, 5, 1)

        controls.addWidget(QLabel("Y Min"), 4, 2)
        self.y_min_edit = QLineEdit("")
        self.y_min_edit.editingFinished.connect(self.redraw)
        controls.addWidget(self.y_min_edit, 5, 2)

        controls.addWidget(QLabel("Y Max"), 4, 3)
        self.y_max_edit = QLineEdit("")
        self.y_max_edit.editingFinished.connect(self.redraw)
        controls.addWidget(self.y_max_edit, 5, 3)

        controls.addWidget(QLabel("X Scale"), 4, 4)
        self.x_scale_combo = QComboBox()
        self.x_scale_combo.addItems(["linear", "log"])
        self.x_scale_combo.currentIndexChanged.connect(self.redraw)
        controls.addWidget(self.x_scale_combo, 5, 4)

        controls.addWidget(QLabel("Y Scale"), 4, 5)
        self.y_scale_combo = QComboBox()
        self.y_scale_combo.addItems(["linear", "log"])
        self.y_scale_combo.currentIndexChanged.connect(self.redraw)
        controls.addWidget(self.y_scale_combo, 5, 5)

        self.redraw_button = QPushButton("Redraw")
        self.redraw_button.clicked.connect(self.redraw)
        controls.addWidget(self.redraw_button, 5, 7)

        body = QHBoxLayout()
        layout.addLayout(body, stretch=1)

        plot_column = QVBoxLayout()
        body.addLayout(plot_column, stretch=4)
        self.figure = Figure(figsize=(9, 6), dpi=100)
        self.ax = self.figure.add_subplot(111)
        self.canvas = FigureCanvasQTAgg(self.figure)
        self.toolbar = NavigationToolbar2QT(self.canvas, self)
        plot_column.addWidget(self.canvas)
        plot_column.addWidget(self.toolbar)

        palette_box = QGroupBox("Sample Palette Groups")
        palette_box.setLayout(QVBoxLayout())
        body.addWidget(palette_box, stretch=2)
        palette_box.layout().addWidget(QLabel("Select sample names, move them into a group, and assign palettes for sample-colored plots."))
        self.palette_sample_list = QListWidget()
        self.palette_sample_list.setSelectionMode(QAbstractItemView.ExtendedSelection)
        for sample in self.sample_names:
            self.palette_sample_list.addItem(sample)
        palette_box.layout().addWidget(self.palette_sample_list)
        move_row = QHBoxLayout()
        self.group_move_combo = QComboBox()
        self.group_move_combo.addItems(self.group_order)
        move_row.addWidget(QLabel("Move To"))
        move_row.addWidget(self.group_move_combo)
        move_button = QPushButton("Move")
        move_button.clicked.connect(self._move_selected_samples_to_group)
        move_row.addWidget(move_button)
        reset_button = QPushButton("Reset")
        reset_button.clicked.connect(self._reset_sample_grouping)
        move_row.addWidget(reset_button)
        palette_box.layout().addLayout(move_row)
        for group_name in self.group_order:
            frame = QGroupBox(group_name)
            frame.setLayout(QGridLayout())
            frame.layout().addWidget(QLabel("Palette"), 0, 0)
            palette_edit = QLineEdit(self.group_palette[group_name])
            palette_edit.editingFinished.connect(self.redraw)
            frame.layout().addWidget(palette_edit, 0, 1)
            count_label = QLabel("0 samples")
            frame.layout().addWidget(count_label, 1, 0, 1, 2)
            sample_label = QLabel("No samples")
            sample_label.setWordWrap(True)
            frame.layout().addWidget(sample_label, 2, 0, 1, 2)
            self.group_palette_widgets[group_name] = {
                "palette": palette_edit,
                "count": count_label,
                "samples": sample_label,
            }
            palette_box.layout().addWidget(frame)
        self.palette_status_label = QLabel("")
        self.palette_status_label.setWordWrap(True)
        palette_box.layout().addWidget(self.palette_status_label)
        palette_box.layout().addStretch(1)
        self._refresh_group_boxes()

        self.status_label = QLabel("")
        self.status_label.setWordWrap(True)
        layout.addWidget(self.status_label)

    def _on_mode_changed(self):
        if self.mode_combo.currentText() == "line":
            x_values = [self.x_axis_combo.itemText(idx) for idx in range(self.x_axis_combo.count())]
            if "dose" in x_values:
                self.x_axis_combo.setCurrentText("dose")
            hue_values = [self.hue_combo.itemText(idx) for idx in range(self.hue_combo.count())]
            if "sample_name" in hue_values:
                self.hue_combo.setCurrentText("sample_name")
        self.redraw()

    def _apply_prism_axis_style(self):
        for side in ("left", "bottom"):
            if side in self.ax.spines:
                self.ax.spines[side].set_linewidth(2.0)
                self.ax.spines[side].set_color("#111111")
        for side in ("top", "right"):
            if side in self.ax.spines:
                self.ax.spines[side].set_visible(False)
        self.ax.tick_params(axis="both", which="both", width=2.0, length=6, color="#111111")

    def _resolve_palette(self, name, n_colors):
        palette_name = str(name).strip() or "tab10"
        try:
            import seaborn as sns
            return sns.color_palette(palette_name, max(n_colors, 1)).as_hex()
        except Exception:
            self.palette_status_label.setText(f"Palette '{palette_name}' not found. Falling back to tab10.")
            import seaborn as sns
            return sns.color_palette("tab10", max(n_colors, 1)).as_hex()

    def _palette_for_hue(self, huecol):
        if huecol != "sample_name":
            return None
        palette = {}
        for group_name in self.group_order:
            self.group_palette[group_name] = self.group_palette_widgets[group_name]["palette"].text().strip() or self.group_palette[group_name]
            samples = sorted([sample for sample, assigned in self.sample_group.items() if assigned == group_name])
            if not samples:
                continue
            colors = self._resolve_palette(self.group_palette[group_name], len(samples))
            for idx, sample in enumerate(samples):
                palette[sample] = colors[idx % len(colors)]
        return palette or None

    def _refresh_group_boxes(self):
        for group_name in self.group_order:
            samples = sorted([sample for sample, assigned in self.sample_group.items() if assigned == group_name])
            widgets = self.group_palette_widgets[group_name]
            widgets["count"].setText(f"{len(samples)} samples")
            widgets["samples"].setText(", ".join(samples) if samples else "No samples")

    def _move_selected_samples_to_group(self):
        items = self.palette_sample_list.selectedItems()
        if not items:
            self.palette_status_label.setText("No samples selected.")
            return
        target = self.group_move_combo.currentText()
        for item in items:
            self.sample_group[item.text()] = target
        self.palette_status_label.setText(f"Moved {len(items)} sample(s) into {target}.")
        self._refresh_group_boxes()
        self.redraw()

    def _reset_sample_grouping(self):
        for sample in self.sample_names:
            self.sample_group[sample] = "Ungrouped"
        self.palette_status_label.setText("Reset sample palette grouping.")
        self._refresh_group_boxes()
        self.redraw()

    def _parse_limit(self, text):
        text = str(text).strip()
        if not text:
            return None
        return float(text)

    def _control_group_key(self, row, xcol):
        mode = self.control_group_combo.currentText()
        if mode == "global":
            return "__global__"
        if mode == "x_axis":
            return row.get(xcol)
        return row.get(mode)

    def _normalized_bar_dataframe(self, plot_df, value_col, xcol):
        mode = self.normalization_combo.currentText()
        if mode == "raw_percent" or value_col not in plot_df.columns:
            return plot_df.copy(), value_col, "% positive", ""
        normalized = plot_df.copy()
        normalized["_control_group"] = normalized.apply(lambda row: self._control_group_key(row, xcol), axis=1)
        neg_label = self.negative_control_edit.text().strip()
        pos_label = self.positive_control_edit.text().strip()
        out_col = f"{value_col}__normalized"
        descriptions = {
            "delta_vs_negative": "Delta vs negative",
            "fold_vs_negative": "Fold vs negative",
            "percent_of_positive": "Percent of positive",
            "minmax_neg_to_pos": "Min-max normalized",
        }

        def _convert(group):
            neg_rows = group[group["sample_type"].astype(str).str.strip() == neg_label]
            pos_rows = group[group["sample_type"].astype(str).str.strip() == pos_label]
            neg_mean = float(neg_rows[value_col].mean()) if not neg_rows.empty else np.nan
            pos_mean = float(pos_rows[value_col].mean()) if not pos_rows.empty else np.nan
            values = pd.to_numeric(group[value_col], errors="coerce")
            if mode == "delta_vs_negative":
                result = values - neg_mean
                ylabel = "Delta vs negative"
            elif mode == "fold_vs_negative":
                result = values / neg_mean if pd.notna(neg_mean) and not np.isclose(neg_mean, 0.0) else np.nan
                ylabel = "Fold vs negative"
            elif mode == "percent_of_positive":
                result = 100.0 * values / pos_mean if pd.notna(pos_mean) and not np.isclose(pos_mean, 0.0) else np.nan
                ylabel = "% of positive"
            else:
                denom = pos_mean - neg_mean
                result = 100.0 * (values - neg_mean) / denom if pd.notna(denom) and not np.isclose(denom, 0.0) else np.nan
                ylabel = "Min-max normalized (%)"
            group[out_col] = result
            return group, ylabel

        pieces = []
        ylabel = "% positive"
        for _key, group in normalized.groupby("_control_group", dropna=False):
            converted, ylabel = _convert(group.copy())
            pieces.append(converted)
        normalized = pd.concat(pieces, ignore_index=True) if pieces else normalized.iloc[0:0].copy()
        normalized = normalized.dropna(subset=[out_col]).copy()
        title = "" if not normalized.empty else f"No matching controls found for {descriptions.get(mode, mode)}"
        return normalized, out_col, ylabel, title

    def _apply_plot_formatting(self, default_title="", default_xlabel="", default_ylabel=""):
        title = self.plot_title_edit.text().strip() or default_title
        x_title = self.x_title_edit.text().strip() or default_xlabel
        y_title = self.y_title_edit.text().strip() or default_ylabel
        self.ax.set_title(title)
        self.ax.set_xlabel(x_title)
        self.ax.set_ylabel(y_title)
        self.ax.set_xscale(self.x_scale_combo.currentText())
        self.ax.set_yscale(self.y_scale_combo.currentText())
        try:
            xmin = self._parse_limit(self.x_min_edit.text())
            xmax = self._parse_limit(self.x_max_edit.text())
            if xmin is not None and xmax is not None and xmin < xmax:
                self.ax.set_xlim(xmin, xmax)
        except Exception:
            pass

    def _series_color(self, idx):
        return plt_col(idx)

    def _barplot_with_error(self, plot_df, xcol, ycol, huecol=None):
        palette = self._palette_for_hue(huecol)
        if huecol and huecol in plot_df.columns:
            grouped = plot_df.groupby([xcol, huecol], dropna=False)[ycol].agg(["mean", "std"]).reset_index()
            x_labels = list(pd.Index(grouped[xcol].astype(str).unique()))
            hue_labels = list(pd.Index(grouped[huecol].astype(str).unique()))
            x_pos = np.arange(len(x_labels), dtype=float)
            n_series = max(len(hue_labels), 1)
            width = 0.8 / n_series
            x_lookup = {label: idx for idx, label in enumerate(x_labels)}
            hue_lookup = {label: idx for idx, label in enumerate(hue_labels)}
            for hue_name in hue_labels:
                sub = grouped[grouped[huecol].astype(str) == hue_name]
                color = palette.get(hue_name, self._series_color(hue_lookup[hue_name])) if palette else self._series_color(hue_lookup[hue_name])
                xs = []
                means = []
                errs = []
                for _, row in sub.iterrows():
                    offset = (hue_lookup[hue_name] - (n_series - 1) / 2.0) * width
                    xs.append(x_lookup[str(row[xcol])] + offset)
                    means.append(float(row["mean"]))
                    errs.append(0.0 if pd.isna(row["std"]) else float(row["std"]))
                self.ax.bar(xs, means, width=width, color=color, edgecolor="#111111", linewidth=2.0, label=str(hue_name), zorder=2)
                self.ax.errorbar(xs, means, yerr=errs, fmt="none", ecolor="#111111", elinewidth=1.6, capsize=3, zorder=3)
            for _, row in plot_df.iterrows():
                x_label = str(row[xcol])
                hue_label = str(row[huecol])
                offset = (hue_lookup[hue_label] - (n_series - 1) / 2.0) * width
                jitter = (np.random.RandomState(abs(hash((x_label, hue_label, row.name))) % (2**32)).rand() - 0.5) * width * 0.35
                xpos = x_lookup[x_label] + offset + jitter
                self.ax.scatter(xpos, float(row[ycol]), s=18, color="#111111", alpha=0.65, zorder=4)
            self.ax.set_xticks(x_pos)
            self.ax.set_xticklabels(x_labels, rotation=45, ha="right")
            self.ax.legend(fontsize=8)
            return

        grouped = plot_df.groupby(xcol, dropna=False)[ycol].agg(["mean", "std"]).reset_index()
        x_labels = list(grouped[xcol].astype(str))
        x_pos = np.arange(len(x_labels), dtype=float)
        means = grouped["mean"].astype(float).to_numpy()
        errs = grouped["std"].fillna(0.0).astype(float).to_numpy()
        self.ax.bar(x_pos, means, width=0.72, color="#9ec9ff", edgecolor="#111111", linewidth=2.0, zorder=2)
        self.ax.errorbar(x_pos, means, yerr=errs, fmt="none", ecolor="#111111", elinewidth=1.6, capsize=3, zorder=3)
        x_lookup = {label: idx for idx, label in enumerate(x_labels)}
        for _, row in plot_df.iterrows():
            x_label = str(row[xcol])
            jitter = (np.random.RandomState(abs(hash((x_label, row.name))) % (2**32)).rand() - 0.5) * 0.22
            xpos = x_lookup[x_label] + jitter
            self.ax.scatter(xpos, float(row[ycol]), s=18, color="#111111", alpha=0.65, zorder=4)
        self.ax.set_xticks(x_pos)
        self.ax.set_xticklabels(x_labels, rotation=45, ha="right")

    def _lineplot_with_error(self, plot_df, xcol, ycol, huecol=None):
        line_hue = huecol or ("sample_name" if "sample_name" in plot_df.columns else None)
        palette = self._palette_for_hue(line_hue)
        if line_hue and line_hue in plot_df.columns:
            grouped = plot_df.groupby([xcol, line_hue], dropna=False)[ycol].agg(["mean", "std"]).reset_index()
            for idx, (series_name, sub) in enumerate(grouped.groupby(line_hue, dropna=False)):
                sub = sub.sort_values(xcol)
                color = palette.get(str(series_name), self._series_color(idx)) if palette else self._series_color(idx)
                x_values = pd.to_numeric(sub[xcol], errors="coerce").to_numpy() if xcol == "dose" else sub[xcol].astype(str).to_numpy()
                means = sub["mean"].astype(float).to_numpy()
                errs = sub["std"].fillna(0.0).astype(float).to_numpy()
                self.ax.errorbar(
                    x_values,
                    means,
                    yerr=errs,
                    color=color,
                    linewidth=2.2,
                    marker="o",
                    markersize=5,
                    capsize=3,
                    label=str(series_name),
                    zorder=3,
                )
                raw = plot_df[plot_df[line_hue].astype(str) == str(series_name)].copy()
                raw = raw.sort_values(xcol)
                for _, row in raw.iterrows():
                    x_val = float(row[xcol]) if xcol == "dose" else str(row[xcol])
                    self.ax.scatter(x_val, float(row[ycol]), s=18, color=color, alpha=0.45, zorder=2)
            self.ax.legend(fontsize=8)
            return

        grouped = plot_df.groupby(xcol, dropna=False)[ycol].agg(["mean", "std"]).reset_index().sort_values(xcol)
        x_values = pd.to_numeric(grouped[xcol], errors="coerce").to_numpy() if xcol == "dose" else grouped[xcol].astype(str).to_numpy()
        means = grouped["mean"].astype(float).to_numpy()
        errs = grouped["std"].fillna(0.0).astype(float).to_numpy()
        self.ax.errorbar(
            x_values,
            means,
            yerr=errs,
            color="#4f7cff",
            linewidth=2.2,
            marker="o",
            markersize=5,
            capsize=3,
            zorder=3,
        )
        for _, row in plot_df.iterrows():
            x_val = float(row[xcol]) if xcol == "dose" else str(row[xcol])
            self.ax.scatter(x_val, float(row[ycol]), s=18, color="#4f7cff", alpha=0.45, zorder=2)
        try:
            ymin = self._parse_limit(self.y_min_edit.text())
            ymax = self._parse_limit(self.y_max_edit.text())
            if ymin is not None and ymax is not None and ymin < ymax:
                self.ax.set_ylim(ymin, ymax)
        except Exception:
            pass

    def redraw(self):
        self.ax.clear()
        try:
            mode = self.mode_combo.currentText()
            if mode in {"bar", "line"}:
                pct_col = self.pct_combo.currentText()
                if not pct_col or pct_col not in self.summary.columns:
                    self.ax.set_title("No % positive column selected")
                else:
                    xcol = self.x_axis_combo.currentText() or "well"
                    huecol = self.hue_combo.currentText().strip() or None
                    plot_df = self.summary.copy()
                    plot_df = plot_df.dropna(subset=[xcol, pct_col])
                    plot_df, ycol, ylabel, normalization_title = self._normalized_bar_dataframe(plot_df, pct_col, xcol)
                    if plot_df.empty:
                        self.ax.set_title(normalization_title or "No summary data available")
                    elif mode == "line":
                        if xcol == "dose":
                            plot_df[xcol] = pd.to_numeric(plot_df[xcol], errors="coerce")
                            plot_df = plot_df.dropna(subset=[xcol]).sort_values([huecol or "sample_name", xcol] if (huecol or "sample_name") in plot_df.columns else [xcol])
                        self._lineplot_with_error(plot_df, xcol, ycol, huecol=huecol)
                        self._apply_plot_formatting(
                            default_title=normalization_title or pct_col.replace("pct_", ""),
                            default_xlabel=xcol,
                            default_ylabel=ylabel,
                        )
                    else:
                        self._barplot_with_error(plot_df, xcol, ycol, huecol=huecol)
                        self._apply_plot_formatting(
                            default_title=normalization_title or pct_col.replace("pct_", ""),
                            default_xlabel=xcol,
                            default_ylabel=ylabel,
                        )
            elif mode == "distribution":
                channel = self.channel_combo.currentText()
                if not channel or channel not in self.intensity.columns:
                    self.ax.set_title("No intensity channel selected")
                else:
                    plot_df = self.intensity.copy()
                    gate_filter = self.gate_filter_combo.currentText().strip()
                    if gate_filter and gate_filter in plot_df.columns:
                        plot_df = plot_df[plot_df[gate_filter].astype(bool)]
                    plot_df[channel] = pd.to_numeric(plot_df[channel], errors="coerce")
                    plot_df = plot_df.dropna(subset=[channel])
                    plot_df = plot_df[plot_df[channel] > 0]
                    huecol = self.hue_dist_combo.currentText().strip()
                    if huecol and huecol in plot_df.columns:
                        for name, group in plot_df.groupby(huecol, dropna=False):
                            self.ax.hist(group[channel], bins=80, histtype="step", linewidth=1.8, label=str(name))
                        self.ax.legend(fontsize=8)
                    else:
                        self.ax.hist(plot_df[channel], bins=80, histtype="step", linewidth=1.8, color="#4f7cff")
                    self.ax.set_xscale("log")
                    self._apply_plot_formatting(
                        default_title="Fluorescence distribution",
                        default_xlabel=channel,
                        default_ylabel="Count",
                    )
            else:
                channel_x = self.channel_combo.currentText()
                channel_y = self.corr_y_combo.currentText()
                if not channel_x or not channel_y or channel_x == channel_y:
                    self.ax.set_title("Choose two different channels")
                else:
                    plot_df = self.intensity.copy()
                    gate_filter = self.gate_filter_combo.currentText().strip()
                    if gate_filter and gate_filter in plot_df.columns:
                        plot_df = plot_df[plot_df[gate_filter].astype(bool)]
                    plot_df[channel_x] = pd.to_numeric(plot_df[channel_x], errors="coerce")
                    plot_df[channel_y] = pd.to_numeric(plot_df[channel_y], errors="coerce")
                    plot_df = plot_df.dropna(subset=[channel_x, channel_y])
                    xcol = self.x_axis_combo.currentText() or "sample_name"
                    huecol = self.hue_combo.currentText().strip() or None
                    group_cols = [col for col in [xcol, huecol] if col and col in plot_df.columns]
                    corr_rows = []
                    for key, group in plot_df.groupby(group_cols or ["well"], dropna=False):
                        corr_value = group[channel_x].corr(group[channel_y])
                        if pd.notna(corr_value):
                            row = {}
                            if isinstance(key, tuple):
                                for idx, col in enumerate(group_cols):
                                    row[col] = key[idx]
                            elif group_cols:
                                row[group_cols[0]] = key
                            row["correlation"] = float(corr_value)
                            corr_rows.append(row)
                    corr_df = pd.DataFrame(corr_rows)
                    if corr_df.empty:
                        self.ax.set_title("No valid correlations after filtering")
                    elif huecol and huecol in corr_df.columns:
                        grouped = corr_df.groupby([xcol, huecol], dropna=False)["correlation"].mean().unstack(fill_value=np.nan)
                        x_labels = list(grouped.index.astype(str))
                        x_positions = np.arange(len(x_labels))
                        n_series = max(len(grouped.columns), 1)
                        width = 0.8 / n_series
                        for idx, series_name in enumerate(grouped.columns):
                            offset = (idx - (n_series - 1) / 2.0) * width
                            self.ax.bar(x_positions + offset, grouped[series_name].to_numpy(), width=width, label=str(series_name), color=plt_col(idx))
                        self.ax.set_xticks(x_positions)
                        self.ax.set_xticklabels(x_labels, rotation=45, ha="right")
                        self.ax.legend(fontsize=8)
                        self.ax.axhline(0.0, color="#666666", linewidth=1.6, linestyle="--")
                    else:
                        grouped = corr_df.groupby(xcol, dropna=False)["correlation"].mean()
                        x_labels = list(grouped.index.astype(str))
                        self.ax.bar(x_labels, grouped.values, color="#9ec9ff", edgecolor="#111111", linewidth=2.0)
                        self.ax.tick_params(axis="x", rotation=45)
                        self.ax.axhline(0.0, color="#666666", linewidth=1.6, linestyle="--")
                    self._apply_plot_formatting(
                        default_title=f"Correlation: {channel_x} vs {channel_y}",
                        default_xlabel=xcol,
                        default_ylabel="correlation",
                    )
                    self.ax.set_ylim(-1.05, 1.05)
            self._apply_prism_axis_style()
            self.figure.tight_layout()
            self.canvas.draw_idle()
            self.status_label.setText(f"Summary rows: {len(self.summary)} | Intensity rows: {len(self.intensity)}")
        except Exception as exc:
            self.ax.clear()
            self.ax.set_title(f"Preview failed: {type(exc).__name__}")
            self.figure.tight_layout()
            self.canvas.draw_idle()
            self.status_label.setText(f"Preview failed: {type(exc).__name__}: {exc}")


def plt_col(index):
    palette = ["#4f7cff", "#2f8c74", "#a56ad8", "#c77d2b", "#cc5f7a", "#3d97b8", "#7a9c34", "#b85c2e"]
    return palette[index % len(palette)]


ROBUST_AXIS_LOWER_Q = 0.01
ROBUST_AXIS_UPPER_Q = 0.99


class NonSelectingWheelListWidget(QListWidget):
    def wheelEvent(self, event):
        selected_rows = [self.row(item) for item in self.selectedItems()]
        current_row = self.currentRow()
        super().wheelEvent(event)
        self.blockSignals(True)
        self.clearSelection()
        for row in selected_rows:
            item = self.item(row)
            if item is not None:
                item.setSelected(True)
        if current_row >= 0:
            current_item = self.item(current_row)
            if current_item is not None:
                self.setCurrentItem(current_item)
        self.blockSignals(False)


class FlowDesktopQtWindow(QMainWindow):
    def __init__(self, base_dir=None, instrument="Cytoflex", max_points=15000):
        super().__init__()
        self.base_dir = base_dir or os.getcwd()
        self.file_map = {}
        self.channel_names_by_label = {}
        self.channel_names = []
        self.sample_cache = {}
        self.compensation_enabled = False
        self.compensation_source_channels = []
        self.compensation_channels = []
        self.compensation_matrix = None
        self.compensation_text = ""
        self.plate_metadata = {}
        self.plate_buttons = {}
        self.population_labels = {"All Events": "__all__"}
        self.current_data = pd.DataFrame()
        self.current_transformed = pd.DataFrame()
        self.gates = []
        self.pending_gate = None
        self.saved_gate_lookup = {}
        self.selected_gate_name = None
        self._summary_cache = None
        self._intensity_cache = None
        self.rectangle_start_point = None
        self.rectangle_current_point = None
        self.zoom_start_point = None
        self.zoom_current_point = None
        self.vertical_preview_x = None
        self.horizontal_preview_y = None
        self.polygon_vertices = []
        self.polygon_cursor_point = None
        self.canvas_click_cid = None
        self.canvas_motion_cid = None
        self.canvas_release_cid = None
        self.canvas_press_drag_cid = None
        self.scatter_x_axis_overrides = {}
        self.scatter_y_axis_overrides = {}
        self.hist_axis_overrides = {}
        self.edit_gate_mode = False
        self.translate_gate_mode = False
        self.drag_state = None
        self._suspend_auto_plot = False
        self.auto_plot_enabled = True
        self._gate_group_counter = 0
        self._heatmap_update_pending = False
        self._heatmap_timer = QTimer(self)
        self._heatmap_timer.setSingleShot(True)
        self._heatmap_timer.timeout.connect(self._update_heatmap)
        self._redraw_timer = QTimer(self)
        self._redraw_timer.setSingleShot(True)
        self._redraw_timer.timeout.connect(self.redraw)
        self._plot_timer = QTimer(self)
        self._plot_timer.setSingleShot(True)
        self._plot_timer.timeout.connect(self.plot_population)

        self.setWindowTitle(f"{APP_BRAND} v{__version__} [Qt Preview]")
        self.resize(1440, 840)
        self._build_ui(instrument=instrument, max_points=max_points)
        self._update_compensation_status()
        self._autoload_last_session_or_folder(base_dir)

    def _section(self, title):
        box = QGroupBox(title)
        box.setLayout(QVBoxLayout())
        return box

    def _build_ui(self, instrument, max_points):
        root = QWidget()
        root_layout = QHBoxLayout(root)
        root_layout.setContentsMargins(10, 10, 10, 10)

        splitter = QSplitter(Qt.Horizontal)
        root_layout.addWidget(splitter)
        self.setCentralWidget(root)

        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(10)

        data_box = self._section("Data")
        data_grid = QGridLayout()
        data_box.layout().addLayout(data_grid)
        data_grid.addWidget(QLabel("Folder"), 0, 0, 1, 3)
        self.folder_edit = QLineEdit(self.base_dir)
        data_grid.addWidget(self.folder_edit, 1, 0, 1, 3)
        self.browse_button = QPushButton("Browse")
        self.browse_button.clicked.connect(self._browse_folder)
        data_grid.addWidget(self.browse_button, 2, 0)
        self.instrument_combo = QComboBox()
        self.instrument_combo.addItems(["Cytoflex", "Symphony"])
        self.instrument_combo.setCurrentText(instrument)
        data_grid.addWidget(self.instrument_combo, 2, 1)
        self.load_button = QPushButton("Load Folder")
        self.load_button.clicked.connect(self.load_folder)
        data_grid.addWidget(self.load_button, 2, 2)
        self.compensation_button = QPushButton("Compensation")
        self.compensation_button.clicked.connect(self.open_compensation_editor)
        data_grid.addWidget(self.compensation_button, 3, 0)
        self.compensation_status_label = QLabel("Compensation: off")
        self.compensation_status_label.setWordWrap(True)
        data_grid.addWidget(self.compensation_status_label, 3, 1, 1, 2)
        data_grid.addWidget(QLabel("Wells"), 4, 0, 1, 3)
        self.well_list = NonSelectingWheelListWidget()
        self.well_list.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.well_list.itemSelectionChanged.connect(self._on_well_selection_changed)
        data_grid.addWidget(self.well_list, 5, 0, 1, 3)
        data_grid.addWidget(QLabel("Selected Sample"), 6, 0)
        self.sample_name_edit = QLineEdit("")
        data_grid.addWidget(self.sample_name_edit, 7, 0, 1, 3)
        self.assign_sample_button = QPushButton("Apply Sample")
        self.assign_sample_button.clicked.connect(self._assign_sample_name_to_selected_wells)
        data_grid.addWidget(self.assign_sample_button, 8, 0)
        self.exclude_toggle_button = QPushButton("Toggle Exclude")
        self.exclude_toggle_button.clicked.connect(self._toggle_exclude_selected_wells)
        data_grid.addWidget(self.exclude_toggle_button, 8, 1)
        self.clear_metadata_button = QPushButton("Clear Metadata")
        self.clear_metadata_button.clicked.connect(self._clear_selected_metadata)
        data_grid.addWidget(self.clear_metadata_button, 8, 2)
        self.plate_editor_button = QPushButton("Plate Map Editor")
        self.plate_editor_button.clicked.connect(self.open_plate_map_editor)
        data_grid.addWidget(self.plate_editor_button, 9, 0)
        self.save_session_button = QPushButton("Save Session")
        self.save_session_button.clicked.connect(self.save_session)
        data_grid.addWidget(self.save_session_button, 9, 1)
        self.load_session_button = QPushButton("Load Session")
        self.load_session_button.clicked.connect(self.load_session)
        data_grid.addWidget(self.load_session_button, 9, 2)
        self.recent_session_combo = QComboBox()
        data_grid.addWidget(self.recent_session_combo, 10, 0, 1, 2)
        self.open_recent_button = QPushButton("Open Recent")
        self.open_recent_button.clicked.connect(self.load_recent_session)
        data_grid.addWidget(self.open_recent_button, 10, 2)
        self.check_updates_button = QPushButton("Check for Updates")
        self.check_updates_button.clicked.connect(self.check_for_updates)
        data_grid.addWidget(self.check_updates_button, 11, 0)
        self.version_label = QLabel(f"Version {__version__}")
        data_grid.addWidget(self.version_label, 11, 1, 1, 2)
        left_layout.addWidget(data_box)

        plot_box = self._section("Plot")
        plot_grid = QGridLayout()
        plot_box.layout().addLayout(plot_grid)
        plot_grid.addWidget(QLabel("Population"), 0, 0)
        self.population_combo = QComboBox()
        self.population_combo.addItems(["All Events"])
        self.population_combo.currentIndexChanged.connect(self._on_population_changed)
        plot_grid.addWidget(self.population_combo, 1, 0)
        plot_grid.addWidget(QLabel("Max Points"), 0, 1)
        self.max_points_spin = QSpinBox()
        self.max_points_spin.setRange(1000, 50000)
        self.max_points_spin.setSingleStep(1000)
        self.max_points_spin.setValue(int(max_points))
        self.max_points_spin.valueChanged.connect(self._trigger_auto_plot)
        plot_grid.addWidget(self.max_points_spin, 1, 1)
        self.plot_button = QPushButton("Plot Population")
        self.plot_button.clicked.connect(self.plot_population)
        plot_grid.addWidget(self.plot_button, 1, 2)
        self.zoom_box_button = QPushButton("Zoom Box")
        self.zoom_box_button.clicked.connect(self.start_zoom_box)
        plot_grid.addWidget(self.zoom_box_button, 1, 3)
        self.reset_zoom_button = QPushButton("Reset Zoom")
        self.reset_zoom_button.clicked.connect(self.reset_zoom)
        plot_grid.addWidget(self.reset_zoom_button, 1, 4)
        self.graph_options_button = QPushButton("Graph Options")
        self.graph_options_button.clicked.connect(self.open_graph_options_dialog)
        plot_grid.addWidget(self.graph_options_button, 1, 5)

        plot_grid.addWidget(QLabel("X Axis"), 2, 0)
        self.x_combo = QComboBox()
        self.x_combo.currentIndexChanged.connect(self._on_channel_changed)
        plot_grid.addWidget(self.x_combo, 3, 0)
        plot_grid.addWidget(QLabel("Y Axis"), 2, 1)
        self.y_combo = QComboBox()
        self.y_combo.currentIndexChanged.connect(self._on_channel_changed)
        plot_grid.addWidget(self.y_combo, 3, 1)
        plot_grid.addWidget(QLabel("Plot Mode"), 2, 2)
        self.plot_mode_combo = QComboBox()
        self.plot_mode_combo.addItems(["scatter", "count histogram"])
        self.plot_mode_combo.currentIndexChanged.connect(self._on_channel_changed)
        plot_grid.addWidget(self.plot_mode_combo, 3, 2)

        plot_grid.addWidget(QLabel("X Transform"), 4, 0)
        self.x_transform_combo = QComboBox()
        self.x_transform_combo.addItems(["linear", "log10", "arcsinh"])
        self.x_transform_combo.setCurrentText("arcsinh")
        self.x_transform_combo.currentIndexChanged.connect(self._trigger_auto_plot)
        plot_grid.addWidget(self.x_transform_combo, 5, 0)
        plot_grid.addWidget(QLabel("X Cofactor"), 4, 1)
        self.x_cofactor_spin = QSpinBox()
        self.x_cofactor_spin.setRange(1, 10000)
        self.x_cofactor_spin.setValue(150)
        self.x_cofactor_spin.valueChanged.connect(self._trigger_auto_plot)
        plot_grid.addWidget(self.x_cofactor_spin, 5, 1)
        plot_grid.addWidget(QLabel("Y Transform"), 4, 2)
        self.y_transform_combo = QComboBox()
        self.y_transform_combo.addItems(["linear", "log10", "arcsinh"])
        self.y_transform_combo.setCurrentText("arcsinh")
        self.y_transform_combo.currentIndexChanged.connect(self._trigger_auto_plot)
        plot_grid.addWidget(self.y_transform_combo, 5, 2)
        plot_grid.addWidget(QLabel("Y Cofactor"), 4, 3)
        self.y_cofactor_spin = QSpinBox()
        self.y_cofactor_spin.setRange(1, 10000)
        self.y_cofactor_spin.setValue(150)
        self.y_cofactor_spin.valueChanged.connect(self._trigger_auto_plot)
        plot_grid.addWidget(self.y_cofactor_spin, 5, 3)

        self.qt_plot_note = QLabel("Qt port currently supports folder load, well selection, plotting, and basic gate drawing.")
        self.qt_plot_note.setWordWrap(True)
        plot_box.layout().addWidget(self.qt_plot_note)
        auto_row = QHBoxLayout()
        auto_row.addWidget(QLabel("Auto Update"))
        self.auto_plot_auto_radio = QRadioButton("Auto")
        self.auto_plot_manual_radio = QRadioButton("Manual")
        self.auto_plot_auto_radio.setChecked(True)
        self.auto_plot_auto_radio.toggled.connect(self._on_auto_plot_mode_changed)
        auto_row.addWidget(self.auto_plot_auto_radio)
        auto_row.addWidget(self.auto_plot_manual_radio)
        auto_row.addStretch(1)
        plot_box.layout().addLayout(auto_row)
        left_layout.addWidget(plot_box)

        gating_box = self._section("Gating")
        gating_grid = QGridLayout()
        gating_box.layout().addLayout(gating_grid)
        gating_grid.addWidget(QLabel("Gate Type"), 0, 0)
        self.gate_type_combo = QComboBox()
        self.gate_type_combo.addItems(["polygon", "rectangle", "quad", "vertical", "horizontal"])
        gating_grid.addWidget(self.gate_type_combo, 1, 0)
        gating_grid.addWidget(QLabel("Gate Name"), 0, 1)
        self.gate_name_edit = QLineEdit("gate_1")
        gating_grid.addWidget(self.gate_name_edit, 1, 1, 1, 2)
        self.start_draw_button = QPushButton("Start Drawing")
        self.start_draw_button.clicked.connect(self.start_drawing)
        gating_grid.addWidget(self.start_draw_button, 2, 0)
        self.clear_pending_button = QPushButton("Clear Pending")
        self.clear_pending_button.clicked.connect(self.clear_pending)
        gating_grid.addWidget(self.clear_pending_button, 2, 1)
        self.save_gate_button = QPushButton("Save Gate")
        self.save_gate_button.clicked.connect(self.save_gate)
        gating_grid.addWidget(self.save_gate_button, 2, 2)
        self.move_gate_button = QPushButton("Move Gate")
        self.move_gate_button.clicked.connect(self.start_move_selected_gate)
        gating_grid.addWidget(self.move_gate_button, 3, 0)
        self.delete_gate_button = QPushButton("Delete Gate")
        self.delete_gate_button.clicked.connect(self.delete_selected_gate)
        gating_grid.addWidget(self.delete_gate_button, 3, 1)
        self.rename_gate_button = QPushButton("Rename Gate")
        self.rename_gate_button.clicked.connect(self.rename_selected_gate)
        gating_grid.addWidget(self.rename_gate_button, 3, 2)
        self.recolor_gate_button = QPushButton("Recolor")
        self.recolor_gate_button.clicked.connect(self.recolor_selected_gate)
        gating_grid.addWidget(self.recolor_gate_button, 4, 0)
        self.copy_gate_names_button = QPushButton("Copy Names")
        self.copy_gate_names_button.clicked.connect(self.copy_gate_names)
        gating_grid.addWidget(self.copy_gate_names_button, 4, 1)
        self.save_template_button = QPushButton("Save Template")
        self.save_template_button.clicked.connect(self.save_gate_template)
        gating_grid.addWidget(self.save_template_button, 4, 2)
        self.load_template_button = QPushButton("Load Template")
        self.load_template_button.clicked.connect(self.load_gate_template)
        gating_grid.addWidget(self.load_template_button, 5, 0, 1, 3)
        self.mode_label = QLabel("Mode: idle")
        gating_box.layout().addWidget(self.mode_label)
        gating_box.layout().addWidget(QLabel("Saved Gates"))
        self.saved_gate_list = QListWidget()
        self.saved_gate_list.itemSelectionChanged.connect(self._on_saved_gate_selected)
        gating_box.layout().addWidget(self.saved_gate_list)
        self.gate_summary = QTextEdit()
        self.gate_summary.setReadOnly(True)
        self.gate_summary.setPlainText("Select a gate to view summary.")
        gating_box.layout().addWidget(self.gate_summary)
        export_row = QHBoxLayout()
        self.export_summary_button = QPushButton("Export Summary CSV")
        self.export_summary_button.clicked.connect(self.export_gate_summary_csv)
        export_row.addWidget(self.export_summary_button)
        self.export_intensity_button = QPushButton("Export Intensities CSV")
        self.export_intensity_button.clicked.connect(self.export_intensity_csv)
        export_row.addWidget(self.export_intensity_button)
        self.export_plate_button = QPushButton("Export Plate CSV")
        self.export_plate_button.clicked.connect(self.export_plate_metadata_csv)
        export_row.addWidget(self.export_plate_button)
        gating_box.layout().addLayout(export_row)
        analysis_row = QHBoxLayout()
        self.analysis_preview_button = QPushButton("Analysis Preview")
        self.analysis_preview_button.clicked.connect(self.open_analysis_preview)
        analysis_row.addWidget(self.analysis_preview_button)
        self.export_html_button = QPushButton("Export HTML Report")
        self.export_html_button.clicked.connect(self.export_html_report)
        analysis_row.addWidget(self.export_html_button)
        self.export_notebook_button = QPushButton("Export Analysis Notebook")
        self.export_notebook_button.clicked.connect(self.create_analysis_notebook)
        analysis_row.addWidget(self.export_notebook_button)
        gating_box.layout().addLayout(analysis_row)
        left_layout.addWidget(gating_box)

        status_box = self._section("Status")
        status_layout = status_box.layout()
        self.status_label = QLabel("Choose a folder and click Load Folder.")
        self.status_label.setWordWrap(True)
        status_layout.addWidget(self.status_label)
        self.channel_status_label = QLabel("Channel union and mixed-channel warnings will appear here.")
        self.channel_status_label.setWordWrap(True)
        status_layout.addWidget(self.channel_status_label)
        left_layout.addWidget(status_box)
        left_layout.addStretch(1)

        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(10)
        right_splitter = QSplitter(Qt.Vertical)
        right_layout.addWidget(right_splitter)

        plot_panel = QGroupBox("Interactive Plot")
        plot_panel.setLayout(QVBoxLayout())
        self.figure = Figure(figsize=(8, 7), dpi=100)
        self.ax = self.figure.add_subplot(111)
        self.ax.set_title("No population plotted")
        self.ax.set_xlabel("X")
        self.ax.set_ylabel("Y")
        self.canvas = FigureCanvasQTAgg(self.figure)
        self.canvas.setFixedSize(760, 760)
        self.canvas.setFocusPolicy(Qt.StrongFocus)
        self.canvas.setFocus()
        self.toolbar = NavigationToolbar2QT(self.canvas, self)
        self.plot_canvas_row = QWidget()
        plot_canvas_row_layout = QHBoxLayout(self.plot_canvas_row)
        plot_canvas_row_layout.setContentsMargins(0, 0, 0, 0)
        plot_canvas_row_layout.addStretch(1)
        plot_canvas_row_layout.addWidget(self.canvas)
        plot_canvas_row_layout.addStretch(1)
        plot_panel.layout().addWidget(self.plot_canvas_row, stretch=1)
        plot_panel.layout().addWidget(self.toolbar)
        right_splitter.addWidget(plot_panel)

        heatmap_panel = QGroupBox("Well Heatmap")
        heatmap_panel.setLayout(QVBoxLayout())
        heatmap_controls = QGridLayout()
        heatmap_panel.layout().addLayout(heatmap_controls)
        heatmap_controls.addWidget(QLabel("Mode"), 0, 0)
        self.heatmap_mode_combo = QComboBox()
        self.heatmap_mode_combo.addItems(["percent", "mfi"])
        self.heatmap_mode_combo.currentIndexChanged.connect(self._schedule_heatmap_update)
        heatmap_controls.addWidget(self.heatmap_mode_combo, 0, 1)
        heatmap_controls.addWidget(QLabel("Metric"), 0, 2)
        self.heatmap_metric_combo = QComboBox()
        self.heatmap_metric_combo.currentIndexChanged.connect(self._schedule_heatmap_update)
        heatmap_controls.addWidget(self.heatmap_metric_combo, 0, 3)
        heatmap_controls.addWidget(QLabel("Channel"), 0, 4)
        self.heatmap_channel_combo = QComboBox()
        self.heatmap_channel_combo.currentIndexChanged.connect(self._schedule_heatmap_update)
        heatmap_controls.addWidget(self.heatmap_channel_combo, 0, 5)
        self.refresh_heatmap_button = QPushButton("Refresh Heatmap")
        self.refresh_heatmap_button.clicked.connect(self._update_heatmap)
        heatmap_controls.addWidget(self.refresh_heatmap_button, 0, 6)
        self.heatmap_status_label = QLabel("Heatmap ready")
        heatmap_controls.addWidget(self.heatmap_status_label, 0, 7)
        self.heatmap_figure = Figure(figsize=(8, 3.8), dpi=100)
        self.heatmap_ax = self.heatmap_figure.add_subplot(111)
        self.heatmap_canvas = FigureCanvasQTAgg(self.heatmap_figure)
        self.heatmap_canvas.setFixedSize(760, 420)
        self.heatmap_canvas_row = QWidget()
        heatmap_canvas_row_layout = QHBoxLayout(self.heatmap_canvas_row)
        heatmap_canvas_row_layout.setContentsMargins(0, 0, 0, 0)
        heatmap_canvas_row_layout.addStretch(1)
        heatmap_canvas_row_layout.addWidget(self.heatmap_canvas)
        heatmap_canvas_row_layout.addStretch(1)
        heatmap_panel.layout().addWidget(self.heatmap_canvas_row)
        right_splitter.addWidget(heatmap_panel)

        plate_panel = QGroupBox("Plate Layout")
        plate_panel.setLayout(QVBoxLayout())
        plate_panel.layout().addWidget(QLabel("Click a well to select it in the list. Use the sample/exclude controls on the left to edit metadata."))
        plate_button_row = QHBoxLayout()
        plate_button_row.addStretch(1)
        self.plate_editor_panel_button = QPushButton("Open Plate Map Editor")
        self.plate_editor_panel_button.clicked.connect(self.open_plate_map_editor)
        plate_button_row.addWidget(self.plate_editor_panel_button)
        plate_button_row.addStretch(1)
        plate_panel.layout().addLayout(plate_button_row)
        plate_grid = QGridLayout()
        plate_panel.layout().addLayout(plate_grid)
        for col in range(12):
            plate_grid.addWidget(QLabel(str(col + 1)), 0, col + 1)
        for row_idx, row_name in enumerate("ABCDEFGH", start=1):
            plate_grid.addWidget(QLabel(row_name), row_idx, 0)
            for col_idx in range(12):
                well = f"{row_name}{col_idx + 1}"
                button = QPushButton(well)
                button.setMinimumHeight(28)
                button.clicked.connect(lambda _checked=False, w=well: self._select_well_from_plate(w))
                plate_grid.addWidget(button, row_idx, col_idx + 1)
                self.plate_buttons[well] = button
        self.plate_summary_label = QLabel("No wells loaded")
        plate_panel.layout().addWidget(self.plate_summary_label)
        right_splitter.addWidget(plate_panel)
        right_splitter.setSizes([920, 520, 320])

        left_scroll = QScrollArea()
        left_scroll.setWidgetResizable(True)
        left_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        left_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        left_scroll.setWidget(left)

        right_scroll = QScrollArea()
        right_scroll.setWidgetResizable(True)
        right_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        right_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        right_scroll.setWidget(right)

        splitter.addWidget(left_scroll)
        splitter.addWidget(right_scroll)
        splitter.setSizes([520, 920])

    def _placeholder_frame(self, text):
        frame = QFrame()
        frame.setFrameShape(QFrame.StyledPanel)
        frame.setMinimumHeight(120)
        layout = QVBoxLayout(frame)
        layout.addWidget(QLabel(text))
        return frame

    def _browse_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "Choose FCS Folder", self.folder_edit.text().strip() or self.base_dir)
        if folder:
            self.folder_edit.setText(folder)

    def _load_sample(self, relpath):
        if relpath not in self.sample_cache:
            datafile = os.path.join(self.folder_edit.text().strip(), relpath)
            well = _get_well_name(relpath, self.instrument_combo.currentText())
            FCMeasurement = _flow_tools()["FCMeasurement"]
            self.sample_cache[relpath] = FCMeasurement(ID=well, datafile=datafile)
        return self.sample_cache[relpath]

    def _update_compensation_status(self):
        if self.compensation_enabled and self.compensation_matrix is not None and self.compensation_channels:
            self.compensation_status_label.setText(f"Compensation: on ({len(self.compensation_channels)} channels)")
        elif self.compensation_text.strip():
            self.compensation_status_label.setText("Compensation: configured but disabled")
        else:
            self.compensation_status_label.setText("Compensation: off")

    def _compensation_payload(self):
        return {
            "enabled": bool(self.compensation_enabled),
            "source_channels": list(self.compensation_source_channels),
            "channels": list(self.compensation_channels),
            "matrix": self.compensation_matrix.tolist() if isinstance(self.compensation_matrix, np.ndarray) else None,
            "text": self.compensation_text,
        }

    def _load_compensation_payload(self, payload):
        payload = payload or {}
        self.compensation_enabled = bool(payload.get("enabled", False))
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
            self.compensation_enabled = False
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
        size = int(float(parts[0]))
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

    def _apply_compensation(self, df):
        if not self.compensation_enabled or self.compensation_matrix is None or not self.compensation_channels:
            return df.copy(deep=False)
        channels = [channel for channel in self.compensation_channels if channel in df.columns]
        if len(channels) != len(self.compensation_channels):
            return df.copy(deep=False)
        try:
            inverse = np.linalg.pinv(self.compensation_matrix)
        except Exception as exc:
            self.status_label.setText(f"Compensation failed: {type(exc).__name__}: {exc}")
            return df.copy(deep=False)
        compensated = df.copy()
        values = compensated[channels].to_numpy(dtype=float)
        compensated_values = values @ inverse.T
        compensated.loc[:, channels] = compensated_values
        return compensated

    def open_compensation_editor(self):
        dialog = QDialog(self)
        dialog.setWindowTitle("Compensation")
        dialog.resize(980, 700)
        layout = QVBoxLayout(dialog)
        enabled_box = QCheckBox("Enable compensation")
        enabled_box.setChecked(self.compensation_enabled)
        layout.addWidget(enabled_box)
        layout.addWidget(QLabel("Paste a square spillover matrix with matching row/column channel labels. CSV or TSV works."))
        text_edit = QTextEdit()
        text_edit.setPlainText(self.compensation_text)
        layout.addWidget(text_edit, stretch=1)
        button_row = QHBoxLayout()
        load_button = QPushButton("Load File")
        autodetect_button = QPushButton("Auto Detect")
        apply_button = QPushButton("Apply")
        close_button = QPushButton("Close")
        button_row.addWidget(load_button)
        button_row.addWidget(autodetect_button)
        button_row.addStretch(1)
        button_row.addWidget(apply_button)
        button_row.addWidget(close_button)
        layout.addLayout(button_row)

        def _load_file():
            filename, _ = QFileDialog.getOpenFileName(dialog, "Load Compensation Matrix", "", "CSV/TSV files (*.csv *.tsv *.txt);;All files (*)")
            if not filename:
                return
            with open(filename) as fh:
                text_edit.setPlainText(fh.read())

        def _auto_detect():
            if not self.file_map:
                self.status_label.setText("Load a folder first.")
                return
            sample = self._load_sample(next(iter(self.file_map.values())))
            try:
                source_channels, matrix = self._extract_compensation_from_sample_meta(sample)
            except Exception as exc:
                self.status_label.setText(f"Automatic detection failed: {type(exc).__name__}: {exc}")
                return
            header = "," + ",".join(source_channels)
            rows = [f"{channel}," + ",".join(f"{value:.10g}" for value in matrix[idx]) for idx, channel in enumerate(source_channels)]
            text_edit.setPlainText("\n".join([header] + rows))

        def _apply():
            text = text_edit.toPlainText().strip()
            if text:
                try:
                    source_channels, matrix = self._parse_compensation_text(text)
                except Exception as exc:
                    self.status_label.setText(f"Invalid compensation matrix: {type(exc).__name__}: {exc}")
                    return
                mapping = self._default_compensation_mapping(source_channels)
                if any(not item for item in mapping):
                    self.status_label.setText("Some compensation channels could not be mapped automatically.")
                    return
                self.compensation_source_channels = list(source_channels)
                self.compensation_channels = list(mapping)
                self.compensation_matrix = matrix
                self.compensation_text = text
            else:
                self.compensation_source_channels = []
                self.compensation_channels = []
                self.compensation_matrix = None
                self.compensation_text = ""
            self.compensation_enabled = bool(enabled_box.isChecked()) and self.compensation_matrix is not None
            self.sample_cache = {}
            self._invalidate_cached_outputs()
            self._update_compensation_status()
            if self.file_map:
                self.plot_population()
            dialog.accept()

        load_button.clicked.connect(_load_file)
        autodetect_button.clicked.connect(_auto_detect)
        apply_button.clicked.connect(_apply)
        close_button.clicked.connect(dialog.close)
        dialog.exec()

    def _union_channel_names(self, channel_lists):
        ordered = []
        seen = set()
        for channels in channel_lists:
            for channel in channels:
                if channel not in seen:
                    seen.add(channel)
                    ordered.append(channel)
        return ordered

    def _selected_labels(self):
        return [item.data(Qt.UserRole) for item in self.well_list.selectedItems()]

    def _metadata_for_well(self, well):
        return self.plate_metadata.get(well, {})

    def _well_item_display_text(self, label):
        well = label.split(" | ")[0]
        relpath = self.file_map[label]
        meta = self._metadata_for_well(well)
        sample_name = str(meta.get("sample_name", "")).strip()
        excluded = bool(meta.get("excluded", False))
        prefix = "[EXCLUDED] " if excluded else ""
        sample_part = f" | {sample_name}" if sample_name else ""
        return f"{prefix}{well}{sample_part} | {relpath}"

    def _selected_wells(self):
        wells = []
        for label in self._selected_labels():
            if label:
                wells.append(label.split(" | ")[0])
        return wells

    def _refresh_well_list(self, selected_labels=None):
        selected_labels = list(selected_labels or self._selected_labels())
        self.well_list.blockSignals(True)
        self.well_list.clear()
        for label in self.file_map:
            item = QListWidgetItem(self._well_item_display_text(label))
            item.setData(Qt.UserRole, label)
            self.well_list.addItem(item)
            if label in selected_labels:
                item.setSelected(True)
        if self.well_list.count() and not self.well_list.selectedItems():
            self.well_list.item(0).setSelected(True)
        self.well_list.blockSignals(False)

    def _plate_badge_text(self, sample_name):
        text = str(sample_name or "").strip()
        if not text:
            return ""
        compact = "".join(ch for ch in text if ch.isalnum())
        return compact[:4].upper() if compact else text[:4].upper()

    def _plate_badge_color(self, sample_name):
        text = str(sample_name or "").strip()
        if not text:
            return "#2a3140"
        palette = ["#4f7cff", "#2f8c74", "#a56ad8", "#c77d2b", "#cc5f7a", "#3d97b8", "#7a9c34", "#b85c2e"]
        return palette[abs(hash(text)) % len(palette)]

    def _plot_x_transform(self):
        return self.x_transform_combo.currentText()

    def _plot_x_cofactor(self):
        return float(self.x_cofactor_spin.value())

    def _plot_y_transform(self):
        return self.y_transform_combo.currentText()

    def _plot_y_cofactor(self):
        return float(self.y_cofactor_spin.value())

    def _refresh_channel_controls(self):
        selected = self._selected_labels()
        if not selected:
            available_channels = list(self.channel_names)
        else:
            available_channels = self._union_channel_names(self.channel_names_by_label.get(label, []) for label in selected)

        self.x_combo.blockSignals(True)
        self.y_combo.blockSignals(True)
        current_x = self.x_combo.currentText()
        current_y = self.y_combo.currentText()
        self.x_combo.clear()
        self.y_combo.clear()
        self.x_combo.addItems(available_channels)
        self.y_combo.addItems(list(available_channels) + ["Count"])
        if available_channels:
            self.x_combo.setCurrentText(current_x if current_x in available_channels else ("FSC-A" if "FSC-A" in available_channels else available_channels[0]))
            if current_y == "Count" or self.plot_mode_combo.currentText() == "count histogram":
                self.y_combo.setCurrentText("Count")
            else:
                fallback_y = "SSC-A" if "SSC-A" in available_channels else (available_channels[1] if len(available_channels) > 1 else available_channels[0])
                self.y_combo.setCurrentText(current_y if current_y in available_channels else fallback_y)
        self.x_combo.blockSignals(False)
        self.y_combo.blockSignals(False)

        if selected:
            missing = []
            channels_to_check = [self.x_combo.currentText()]
            if self.plot_mode_combo.currentText() != "count histogram" and not _is_count_axis(self.y_combo.currentText()):
                channels_to_check.append(self.y_combo.currentText())
            for label in selected:
                available = set(self.channel_names_by_label.get(label, []))
                missing_channels = [channel for channel in channels_to_check if channel and channel not in available]
                if missing_channels:
                    missing.append(f"{label.split(' | ')[0]} missing {', '.join(missing_channels)}")
            if missing:
                self.channel_status_label.setText("Mixed channels: using channel union. " + " | ".join(missing[:4]))
            else:
                self.channel_status_label.setText("Channel controls updated from selected wells.")
        else:
            self.channel_status_label.setText("Channel controls updated from loaded folder.")

    def load_folder(self):
        folder = self.folder_edit.text().strip()
        if not os.path.isdir(folder):
            self.status_label.setText(f"Folder not found: {folder}")
            return

        self._suspend_auto_plot = True
        self.status_label.setText("Scanning folder and reading channels...")
        QApplication.processEvents()

        instrument = self.instrument_combo.currentText()
        files = _list_fcs_files(folder, instrument)
        self.file_map = {}
        self.channel_names_by_label = {}
        self.channel_names = []
        self.sample_cache = {}
        self.plate_metadata = {}
        self.current_data = pd.DataFrame()
        self.current_transformed = pd.DataFrame()
        self.gates = []
        self.pending_gate = None
        self.saved_gate_lookup = {}
        self.selected_gate_name = None

        for relpath in files:
            well = _get_well_name(relpath, instrument)
            label = f"{well} | {relpath}"
            self.file_map[label] = relpath

        channel_lists = []
        for label, relpath in self.file_map.items():
            sample = self._load_sample(relpath)
            sample_channels = _get_channel_names(sample)
            self.channel_names_by_label[label] = sample_channels
            channel_lists.append(sample_channels)
        self.channel_names = self._union_channel_names(channel_lists)

        self._refresh_well_list(selected_labels=list(self.file_map.keys())[:1])

        self.saved_gate_list.clear()
        self._refresh_population_combo()
        self._refresh_recent_sessions()
        self._refresh_channel_controls()
        self._refresh_heatmap_controls()
        self._refresh_plate_panel()
        self._invalidate_cached_outputs()
        if self.file_map:
            self.status_label.setText(f"Loaded {len(self.file_map)} wells in Qt mode. Basic gate drawing is available.")
        else:
            self.status_label.setText("No FCS files found in the selected folder.")
        self._clear_plot()
        self._disconnect_drawing()
        self._update_gate_summary()
        self._schedule_heatmap_update(delay_ms=0)
        self._suspend_auto_plot = False
        if self.file_map:
            self.plot_population()

    def _sample_raw_dataframe(self, label):
        relpath = self.file_map[label]
        sample = self._load_sample(relpath)
        df = self._apply_compensation(sample.data)
        df["__well__"] = _get_well_name(relpath, self.instrument_combo.currentText())
        df["__source__"] = relpath
        return df

    def _selected_raw_dataframe(self):
        labels = self._selected_labels()
        if not labels:
            return pd.DataFrame()
        frames = [self._sample_raw_dataframe(label) for label in labels]
        return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()

    def _display_dataframe(self):
        df = self._selected_raw_dataframe()
        if df.empty:
            return df, df
        population_name = self._selected_population_name()
        if population_name != "__all__":
            gate = next((item for item in self.gates if item["name"] == population_name), None)
            if gate is None:
                return pd.DataFrame(), pd.DataFrame()
            mask = self._population_mask(df, gate)
            df = df.loc[mask].copy()
            if df.empty:
                return df, df
        x_channel = self.x_combo.currentText()
        y_channel = self.y_combo.currentText()
        if x_channel not in df.columns:
            raise ValueError(f"Selected X channel '{x_channel}' is not available in the current wells.")
        if self.plot_mode_combo.currentText() == "count histogram" or _is_count_axis(y_channel):
            transformed = pd.DataFrame(index=df.index.copy())
            transformed[x_channel] = _transform_array(df[x_channel].to_numpy(), self._plot_x_transform(), self._plot_x_cofactor())
            transformed["__well__"] = df["__well__"].to_numpy()
            return df, transformed
        if y_channel not in df.columns:
            raise ValueError(f"Selected Y channel '{y_channel}' is not available in the current wells.")
        transformed = _apply_transform(
            df,
            x_channel,
            y_channel,
            self._plot_x_transform(),
            self._plot_x_cofactor(),
            y_method=self._plot_y_transform(),
            y_cofactor=self._plot_y_cofactor(),
        )
        transformed["__well__"] = df["__well__"].to_numpy()
        return df, transformed

    def _population_mask(self, raw_df, gate):
        mask = pd.Series(True, index=raw_df.index)
        for lineage_gate in self._population_lineage(gate["name"]):
            gated_df = raw_df.loc[mask].copy()
            if gated_df.empty:
                return pd.Series(False, index=raw_df.index)
            x_channel = lineage_gate["x_channel"]
            if x_channel not in gated_df.columns:
                return pd.Series(False, index=raw_df.index)
            if lineage_gate["gate_type"] == "vertical":
                transformed = pd.DataFrame(index=gated_df.index.copy())
                transformed[x_channel] = _transform_array(
                    gated_df[x_channel].to_numpy(),
                    lineage_gate.get("x_transform", "arcsinh"),
                    lineage_gate.get("x_cofactor", 150.0),
                )
            else:
                y_channel = lineage_gate.get("y_channel")
                if y_channel not in gated_df.columns:
                    return pd.Series(False, index=raw_df.index)
                transformed = _apply_transform(
                    gated_df,
                    x_channel,
                    y_channel,
                    lineage_gate.get("x_transform", "arcsinh"),
                    lineage_gate.get("x_cofactor", 150.0),
                    y_method=lineage_gate.get("y_transform", "arcsinh"),
                    y_cofactor=lineage_gate.get("y_cofactor", 150.0),
                )
            lineage_mask = pd.Series(_gate_mask(transformed, lineage_gate), index=gated_df.index)
            new_mask = pd.Series(False, index=raw_df.index)
            new_mask.loc[gated_df.index] = lineage_mask
            mask = new_mask
        return mask

    def _invalidate_cached_outputs(self):
        self._summary_cache = None
        self._intensity_cache = None

    def _downsample(self, transformed):
        if transformed.empty:
            return transformed
        max_points = self.max_points_spin.value()
        if len(transformed) <= max_points:
            return transformed
        labels = self._selected_labels()
        per_group = max(1, max_points // max(len(labels), 1))
        pieces = []
        for _, group in transformed.groupby("__well__", sort=False):
            pieces.append(group.sample(n=min(per_group, len(group)), random_state=0))
        return pd.concat(pieces, ignore_index=True)

    def _plot_selection_title(self):
        labels = self._selected_labels()
        if not labels:
            return ""
        wells = [label.split(" | ")[0] for label in labels]
        if len(wells) == 1:
            sample_name = str(self._metadata_for_well(wells[0]).get("sample_name", "")).strip()
            return f"{wells[0]} | {sample_name}" if sample_name else wells[0]
        if len(wells) <= 4:
            return ", ".join(wells)
        return f"{len(wells)} wells"

    def _population_display_label(self):
        return self.population_combo.currentText() or "All Events"

    def _selected_population_name(self):
        return self.population_labels.get(self.population_combo.currentText(), "__all__")

    def _population_lineage(self, name):
        lineage = []
        current = next((gate for gate in self.gates if gate["name"] == name), None)
        while current is not None:
            lineage.append(current)
            parent_name = current.get("parent_population", "__all__")
            if parent_name == "__all__":
                break
            current = next((gate for gate in self.gates if gate["name"] == parent_name), None)
        return list(reversed(lineage))

    def _refresh_population_combo(self, selected_name=None):
        self.population_labels = {"All Events": "__all__"}
        population_values = ["All Events"]
        for gate in self.gates:
            self.population_labels[gate["name"]] = gate["name"]
            population_values.append(gate["name"])
        current_text = self.population_combo.currentText()
        self.population_combo.blockSignals(True)
        self.population_combo.clear()
        self.population_combo.addItems(population_values)
        target = selected_name or current_text
        if target in population_values:
            self.population_combo.setCurrentText(target)
        else:
            self.population_combo.setCurrentText("All Events")
        self.population_combo.blockSignals(False)

    def _fluorescence_channels(self):
        return [channel for channel in self.channel_names if not any(token in channel for token in ("FSC", "SSC", "Time"))]

    def _scatter_x_axis_override_key(self):
        channel = self.x_combo.currentText()
        return channel or None

    def _scatter_y_axis_override_key(self):
        channel = self.y_combo.currentText()
        return channel or None

    def _hist_axis_override_key(self):
        channel = self.x_combo.currentText()
        return channel or None

    def _histogram_mode(self):
        return self.plot_mode_combo.currentText() == "count histogram" or _is_count_axis(self.y_combo.currentText())

    def _hist_bins(self):
        return 100

    def _sample_population_raw_dataframe(self, label, population_name):
        raw_df = self._sample_raw_dataframe(label)
        if raw_df.empty or population_name == "__all__":
            return raw_df
        gate = next((item for item in self.gates if item["name"] == population_name), None)
        if gate is None:
            return pd.DataFrame()
        mask = self._population_mask(raw_df, gate)
        return raw_df.loc[mask].copy()

    def _sample_population_transformed_dataframe(
        self,
        label,
        population_name,
        x_channel,
        y_channel,
        x_method,
        x_cofactor,
        y_method="arcsinh",
        y_cofactor=150.0,
    ):
        raw_df = self._sample_population_raw_dataframe(label, population_name)
        if raw_df.empty or x_channel not in raw_df.columns or y_channel not in raw_df.columns:
            return pd.DataFrame()
        transformed = _apply_transform(
            raw_df,
            x_channel,
            y_channel,
            x_method,
            x_cofactor,
            y_method=y_method,
            y_cofactor=y_cofactor,
        )
        transformed["__well__"] = raw_df["__well__"].to_numpy()
        return transformed

    def _median_scatter_axis_limits(self):
        if self._histogram_mode() or not self.file_map:
            return None
        x_channel = self.x_combo.currentText()
        y_channel = self.y_combo.currentText()
        if not x_channel or not y_channel or _is_count_axis(y_channel):
            return None
        population_name = self._selected_population_name()
        bounds = []
        for label in self.file_map:
            try:
                transformed_group = self._sample_population_transformed_dataframe(
                    label,
                    population_name,
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
        xmin, xmax, ymin, ymax = [float(value) for value in np.median(np.asarray(bounds, dtype=float), axis=0)]
        if np.isclose(xmin, xmax):
            pad = max(abs(xmin) * 0.05, 1.0)
        else:
            pad = (xmax - xmin) * 0.05
        xmin -= pad
        xmax += pad
        if np.isclose(ymin, ymax):
            pad = max(abs(ymin) * 0.05, 1.0)
        else:
            pad = (ymax - ymin) * 0.05
        ymin -= pad
        ymax += pad
        return xmin, xmax, ymin, ymax

    def _global_scatter_axis_extent(self):
        if self._histogram_mode() or not self.file_map:
            return None
        x_channel = self.x_combo.currentText()
        y_channel = self.y_combo.currentText()
        if not x_channel or not y_channel or _is_count_axis(y_channel):
            return None
        population_name = self._selected_population_name()
        xmin = xmax = ymin = ymax = None
        for label in self.file_map:
            try:
                transformed_group = self._sample_population_transformed_dataframe(
                    label,
                    population_name,
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

    def _rectangle_vertices(self, start_x, start_y, end_x, end_y):
        x0, x1 = sorted([float(start_x), float(end_x)])
        y0, y1 = sorted([float(start_y), float(end_y)])
        return [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]

    def _effective_scatter_axis_limits(self):
        base_limits = self._median_scatter_axis_limits()
        if base_limits is None:
            return None
        x_override = self.scatter_x_axis_overrides.get(self._scatter_x_axis_override_key())
        y_override = self.scatter_y_axis_overrides.get(self._scatter_y_axis_override_key())
        x_limits = x_override if x_override is not None else base_limits[:2]
        y_limits = y_override if y_override is not None else base_limits[2:]
        return (x_limits[0], x_limits[1], y_limits[0], y_limits[1])

    def _effective_histogram_axis_limits(self, transformed=None):
        base_limits = self._median_histogram_axis_limits(transformed=transformed)
        if base_limits is None:
            return None
        override = self.hist_axis_overrides.get(self._hist_axis_override_key())
        if override is None:
            return base_limits
        ymax = self._current_histogram_ymax(transformed=transformed, x_limits=(override[0], override[1]))
        return (override[0], override[1], override[2], ymax)

    def _current_histogram_ymax(self, transformed=None, x_limits=None):
        if transformed is None:
            transformed = self.current_transformed
        if transformed is None or transformed.empty:
            return 1.0
        x_channel = self.x_combo.currentText()
        if not x_channel or x_channel not in transformed.columns:
            return 1.0
        if x_limits is None:
            extent = self._global_histogram_axis_extent()
            if extent is None:
                return 1.0
            xmin, xmax = float(extent[0]), float(extent[1])
        else:
            xmin, xmax = x_limits
        edges = np.linspace(xmin, xmax, self._hist_bins() + 1)
        max_count = 0
        if "__well__" in transformed.columns:
            for _well, group in transformed.groupby("__well__", sort=False):
                x_values = pd.to_numeric(group[x_channel], errors="coerce").replace([np.inf, -np.inf], np.nan).dropna().to_numpy()
                if len(x_values) == 0:
                    continue
                counts, _ = np.histogram(x_values, bins=edges)
                if len(counts):
                    max_count = max(max_count, int(counts.max()))
        else:
            x_values = pd.to_numeric(transformed[x_channel], errors="coerce").replace([np.inf, -np.inf], np.nan).dropna().to_numpy()
            if len(x_values):
                counts, _ = np.histogram(x_values, bins=edges)
                if len(counts):
                    max_count = max(max_count, int(counts.max()))
        return max(float(max_count) * 1.05, 1.0)

    def _median_histogram_axis_limits(self, transformed=None):
        if not self._histogram_mode() or not self.file_map:
            return None
        x_channel = self.x_combo.currentText()
        if not x_channel:
            return None
        extent = self._global_histogram_axis_extent()
        if extent is None:
            return None
        xmin, xmax = float(extent[0]), float(extent[1])
        ymax = self._current_histogram_ymax(transformed=transformed, x_limits=(xmin, xmax))
        return xmin, xmax, 0.0, ymax

    def _global_histogram_axis_extent(self):
        if not self._histogram_mode() or not self.file_map:
            return None
        x_channel = self.x_combo.currentText()
        if not x_channel:
            return None
        population_name = self._selected_population_name()
        global_xmin = None
        global_xmax = None
        transformed_groups = []
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
            transformed_groups.append(x_values)
            group_xmin = float(np.min(x_values))
            group_xmax = float(np.max(x_values))
            global_xmin = group_xmin if global_xmin is None else min(global_xmin, group_xmin)
            global_xmax = group_xmax if global_xmax is None else max(global_xmax, group_xmax)
        if global_xmin is None or global_xmax is None:
            return None
        if np.isclose(global_xmin, global_xmax):
            x_pad = max(abs(global_xmax) * 0.1, 1.0)
        else:
            x_pad = (global_xmax - global_xmin) * 0.1
        xmin_limit = global_xmin - x_pad
        xmax_limit = global_xmax + x_pad
        edges = np.linspace(xmin_limit, xmax_limit, self._hist_bins() + 1)
        max_count = 0
        for x_values in transformed_groups:
            counts, _ = np.histogram(x_values, bins=edges)
            if len(counts):
                max_count = max(max_count, int(counts.max()))
        ymax_limit = max(float(max_count) * 1.1, 1.0)
        return xmin_limit, xmax_limit, 0.0, ymax_limit

    def _visible_gate(self, gate):
        histogram_mode = self.plot_mode_combo.currentText() == "count histogram" or _is_count_axis(self.y_combo.currentText())
        if gate["x_channel"] != self.x_combo.currentText():
            return False
        if gate["gate_type"] == "vertical":
            return True
        if histogram_mode:
            return False
        return gate.get("y_channel") in {None, self.y_combo.currentText()}

    def redraw(self):
        self.ax.clear()
        raw_df = self.current_data
        transformed = self.current_transformed
        plotted = self._downsample(transformed)

        if plotted.empty:
            self.ax.set_title("No population plotted")
            self.ax.set_xlabel("X")
            self.ax.set_ylabel("Y")
            self.canvas.draw_idle()
            return

        labels = self._selected_labels()
        x_channel = self.x_combo.currentText()
        y_channel = self.y_combo.currentText()
        histogram_mode = self.plot_mode_combo.currentText() == "count histogram" or _is_count_axis(y_channel)
        if histogram_mode:
            hist_limits = self._effective_histogram_axis_limits(plotted)
            hist_range = None if hist_limits is None else (hist_limits[0], hist_limits[1])
            if len(labels) <= 1:
                self.ax.hist(
                    plotted[x_channel],
                    bins=self._hist_bins(),
                    range=hist_range,
                    histtype="step",
                    linewidth=1.8,
                    color="#1f77b4",
                )
            else:
                for idx, (well, group) in enumerate(plotted.groupby("__well__", sort=False)):
                    self.ax.hist(
                        group[x_channel],
                        bins=self._hist_bins(),
                        range=hist_range,
                        histtype="step",
                        linewidth=1.6,
                        label=well,
                    )
                if len(labels) <= 12:
                    self.ax.legend(fontsize=8)
            self.ax.set_ylabel("Count")
        else:
            if len(labels) <= 1:
                self.ax.scatter(plotted[x_channel], plotted[y_channel], s=3, alpha=0.25, color="#1f77b4", rasterized=True)
            else:
                for _, (well, group) in enumerate(plotted.groupby("__well__", sort=False)):
                    self.ax.scatter(group[x_channel], group[y_channel], s=3, alpha=0.25, label=well, rasterized=True)
                if len(labels) <= 12:
                    self.ax.legend(markerscale=3, fontsize=8)
            self.ax.set_ylabel(f"{y_channel} ({self._plot_y_transform()})")

        for gate in self.gates:
            if self._visible_gate(gate):
                _render_gate(self.ax, gate, selected=(gate["name"] == self.selected_gate_name))

        if self.pending_gate is not None:
            spec = self._pending_to_gate_spec(preview=True)
            if spec is not None:
                _render_gate(self.ax, spec, selected=True)
                if self.pending_gate.gate_type == "polygon":
                    vertices = list(self.pending_gate.payload.get("vertices", []))
                    if vertices:
                        self.ax.scatter(
                            [point[0] for point in vertices],
                            [point[1] for point in vertices],
                            s=72,
                            color="#2f8c74",
                            edgecolors="#f6fffb",
                            linewidths=1.2,
                            zorder=7,
                        )
                    if vertices and self.polygon_cursor_point is not None:
                        xs = [point[0] for point in vertices] + [self.polygon_cursor_point[0]]
                        ys = [point[1] for point in vertices] + [self.polygon_cursor_point[1]]
                        self.ax.plot(xs, ys, linestyle="--", linewidth=1.2, color="#2f8c74")
                        self.ax.scatter(
                            [self.polygon_cursor_point[0]],
                            [self.polygon_cursor_point[1]],
                            s=60,
                            color="#2f8c74",
                            alpha=0.7,
                            zorder=7,
                        )
        if self.vertical_preview_x is not None:
            self.ax.axvline(self.vertical_preview_x, color="#2f8c74", linewidth=1.6, linestyle="--")
        if self.horizontal_preview_y is not None:
            self.ax.axhline(self.horizontal_preview_y, color="#2f8c74", linewidth=1.6, linestyle="--")
        if self.rectangle_start_point is not None and self.rectangle_current_point is not None:
            preview_vertices = self._rectangle_vertices(
                self.rectangle_start_point[0],
                self.rectangle_start_point[1],
                self.rectangle_current_point[0],
                self.rectangle_current_point[1],
            )
            preview = {
                "gate_type": "rectangle",
                "vertices": preview_vertices,
                "x_channel": x_channel,
                "y_channel": y_channel,
                "color": "#2f8c74",
            }
            _render_gate(self.ax, preview, selected=True)
            self.ax.scatter(
                [self.rectangle_start_point[0], self.rectangle_current_point[0]],
                [self.rectangle_start_point[1], self.rectangle_current_point[1]],
                s=28,
                color="#2f8c74",
                zorder=6,
            )
        if self.zoom_start_point is not None and self.zoom_current_point is not None:
            zoom_vertices = self._rectangle_vertices(
                self.zoom_start_point[0],
                self.zoom_start_point[1],
                self.zoom_current_point[0],
                self.zoom_current_point[1],
            )
            zoom_preview = {
                "gate_type": "rectangle",
                "vertices": zoom_vertices,
                "x_channel": x_channel,
                "y_channel": y_channel,
                "color": "#c77d2b",
            }
            _render_gate(self.ax, zoom_preview, selected=True)
            self.ax.scatter(
                [self.zoom_start_point[0], self.zoom_current_point[0]],
                [self.zoom_start_point[1], self.zoom_current_point[1]],
                s=28,
                color="#c77d2b",
                zorder=6,
            )

        self.ax.set_xlabel(f"{x_channel} ({self._plot_x_transform()})")
        title = f"{self._plot_selection_title()} | {self._population_display_label()} | {len(raw_df)} events"
        if len(labels) > 12:
            title += " | legend hidden"
        self.ax.set_title(title)
        self.ax.set_box_aspect(1)
        self.ax.set_anchor("C")
        if histogram_mode:
            if hist_limits is not None:
                xmin, xmax, ymin, ymax = hist_limits
                self.ax.set_xlim(xmin, xmax)
                self.ax.set_ylim(ymin, ymax)
        else:
            scatter_override = self._effective_scatter_axis_limits()
            if scatter_override is not None:
                self.ax.set_xlim(scatter_override[0], scatter_override[1])
                self.ax.set_ylim(scatter_override[2], scatter_override[3])
        self.figure.tight_layout()
        self.canvas.draw_idle()

    def plot_population(self):
        try:
            self.status_label.setText("Loading events and plotting population in Qt mode...")
            QApplication.processEvents()
            raw_df, transformed = self._display_dataframe()
            self.current_data = raw_df
            self.current_transformed = transformed
            self.redraw()
            self._update_gate_summary()
            self._schedule_heatmap_update()
            self._invalidate_cached_outputs()
            self.status_label.setText("Population plotted in Qt mode.")
        except Exception as exc:
            self.status_label.setText(f"Qt plot failed: {type(exc).__name__}: {exc}")

    def _pending_to_gate_spec(self, preview=False):
        if self.pending_gate is None:
            return None
        name = self.gate_name_edit.text().strip() or f"gate_{len(self.gates) + 1}"
        spec = {
            "name": "__pending__" if preview else name,
            "parent_population": self._selected_population_name(),
            "gate_type": self.pending_gate.gate_type,
            "x_channel": self.x_combo.currentText(),
            "y_channel": None if self.pending_gate.gate_type == "vertical" else self.y_combo.currentText(),
            "x_transform": self._plot_x_transform(),
            "x_cofactor": self._plot_x_cofactor(),
            "y_transform": self._plot_y_transform(),
            "y_cofactor": self._plot_y_cofactor(),
            "color": "#2f8c74",
        }
        spec.update(self.pending_gate.payload)
        return spec

    def start_drawing(self):
        if self.current_transformed.empty:
            self.status_label.setText("Plot a population before drawing.")
            return
        if self.plot_mode_combo.currentText() == "count histogram" and self.gate_type_combo.currentText() != "vertical":
            self.status_label.setText("Histogram mode only supports vertical gates.")
            return
        self._disconnect_drawing()
        gate_type = self.gate_type_combo.currentText()
        if gate_type == "rectangle":
            self.canvas_click_cid = self.canvas.mpl_connect("button_press_event", self._on_rectangle_click)
            self.canvas_motion_cid = self.canvas.mpl_connect("motion_notify_event", self._on_rectangle_motion)
            self.mode_label.setText("Mode: drawing rectangle")
        elif gate_type == "quad":
            self.canvas_click_cid = self.canvas.mpl_connect("button_press_event", self._on_quad_click)
            self.mode_label.setText("Mode: drawing quad")
        elif gate_type == "vertical":
            self.canvas_click_cid = self.canvas.mpl_connect("button_press_event", self._on_vertical_click)
            self.canvas_motion_cid = self.canvas.mpl_connect("motion_notify_event", self._on_vertical_motion)
            self.mode_label.setText("Mode: drawing vertical")
        elif gate_type == "horizontal":
            self.canvas_click_cid = self.canvas.mpl_connect("button_press_event", self._on_horizontal_click)
            self.canvas_motion_cid = self.canvas.mpl_connect("motion_notify_event", self._on_horizontal_motion)
            self.mode_label.setText("Mode: drawing horizontal")
        else:
            self.pending_gate = PendingGate("polygon", {"vertices": []})
            self.canvas_click_cid = self.canvas.mpl_connect("button_press_event", self._on_polygon_click)
            self.canvas_motion_cid = self.canvas.mpl_connect("motion_notify_event", self._on_polygon_motion)
            self.mode_label.setText("Mode: drawing polygon")
        self.status_label.setText("Drawing mode active.")

    def clear_pending(self):
        self.pending_gate = None
        self.rectangle_start_point = None
        self.rectangle_current_point = None
        self.zoom_start_point = None
        self.zoom_current_point = None
        self.polygon_vertices = []
        self.polygon_cursor_point = None
        self._disconnect_drawing()
        self.redraw()
        self.status_label.setText("Pending gate cleared.")

    def save_gate(self):
        spec = self._pending_to_gate_spec(preview=False)
        if spec is None:
            self.status_label.setText("Draw a gate before saving.")
            return
        specs_to_add = []
        if spec["gate_type"] in {"vertical", "horizontal"}:
            self._gate_group_counter += 1
            gate_group = f"threshold_group_{self._gate_group_counter}"
            axis_key = "x_threshold" if spec["gate_type"] == "vertical" else "y_threshold"
            for region in ("above", "below"):
                threshold_spec = dict(spec)
                threshold_spec["region"] = region
                threshold_spec["name"] = f"{spec['name']}_{region}"
                threshold_spec["gate_group"] = gate_group
                threshold_spec[axis_key] = spec[axis_key]
                specs_to_add.append(threshold_spec)
        else:
            self._gate_group_counter += 1
            spec["gate_group"] = f"gate_group_{self._gate_group_counter}"
            specs_to_add = [spec]
        existing = {gate["name"] for gate in self.gates}
        duplicate = next((gate["name"] for gate in specs_to_add if gate["name"] in existing), None)
        if duplicate is not None:
            self.status_label.setText(f"Gate name already exists: {duplicate}")
            return
        self.gates.extend(specs_to_add)
        self.pending_gate = None
        self.rectangle_start_point = None
        self.rectangle_current_point = None
        self.zoom_start_point = None
        self.zoom_current_point = None
        self.polygon_vertices = []
        self.polygon_cursor_point = None
        self.gate_name_edit.setText(f"gate_{len(self.gates) + 1}")
        self._refresh_saved_gates(selected_name=specs_to_add[0]["name"])
        self._refresh_population_combo()
        self._refresh_heatmap_controls()
        self._disconnect_drawing()
        self._invalidate_cached_outputs()
        self.redraw()
        self._update_gate_summary()
        self._schedule_heatmap_update()
        self.status_label.setText(f"Saved gate '{specs_to_add[0]['name']}'.")

    def _refresh_saved_gates(self, selected_name=None):
        self.saved_gate_lookup = {}
        self.saved_gate_list.blockSignals(True)
        self.saved_gate_list.clear()
        for gate in self.gates:
            label = self._gate_label(gate)
            self.saved_gate_lookup[label] = gate["name"]
            self.saved_gate_list.addItem(label)
            if gate["name"] == selected_name:
                self.saved_gate_list.item(self.saved_gate_list.count() - 1).setSelected(True)
        self.saved_gate_list.blockSignals(False)
        self.selected_gate_name = selected_name

    def _gate_label(self, gate):
        if gate["gate_type"] == "vertical":
            axes_label = f"vertical @ {gate['x_channel']}"
        elif gate["gate_type"] == "horizontal":
            axes_label = f"horizontal @ {gate['y_channel']}"
        else:
            y_channel = gate["y_channel"] if gate.get("y_channel") else gate["x_channel"]
            axes_label = f"{gate['x_channel']} vs {y_channel}"
        return f"{gate['name']} | {axes_label}"

    def _on_saved_gate_selected(self):
        selected_items = self.saved_gate_list.selectedItems()
        if not selected_items:
            self.selected_gate_name = None
            self.redraw()
            self._update_gate_summary()
            return
        label = selected_items[0].text()
        self.selected_gate_name = self.saved_gate_lookup.get(label)
        gate = self._selected_gate()
        if gate is not None:
            self._suspend_auto_plot = True
            if gate["x_channel"] in self.channel_names:
                self.x_combo.setCurrentText(gate["x_channel"])
            y_values = [self.y_combo.itemText(i) for i in range(self.y_combo.count())]
            if gate["gate_type"] == "vertical":
                self.plot_mode_combo.setCurrentText("count histogram")
                if "Count" in y_values:
                    self.y_combo.setCurrentText("Count")
            elif gate.get("y_channel") in y_values:
                self.plot_mode_combo.setCurrentText("scatter")
                self.y_combo.setCurrentText(gate["y_channel"])
            self.x_transform_combo.setCurrentText(gate.get("x_transform", "arcsinh"))
            self.x_cofactor_spin.setValue(int(gate.get("x_cofactor", 150.0)))
            self.y_transform_combo.setCurrentText(gate.get("y_transform", "arcsinh"))
            self.y_cofactor_spin.setValue(int(gate.get("y_cofactor", 150.0)))
            parent_population = gate.get("parent_population", "__all__")
            selected_population = "All Events" if parent_population == "__all__" else parent_population
            self._refresh_population_combo(selected_name=selected_population)
            self._suspend_auto_plot = False
            self.plot_population()
            self._enable_saved_gate_interaction()
        self.redraw()
        self._update_gate_summary()

    def _selected_gate(self):
        if not self.selected_gate_name:
            return None
        return next((gate for gate in self.gates if gate["name"] == self.selected_gate_name), None)

    def _gate_fraction(self, gate):
        labels = self._selected_labels()
        if not labels:
            return 0.0, 0, 0
        total_count = 0
        parent_total = 0
        for label in labels:
            frac, count, total = self._gate_fraction_for_label(gate, label)
            total_count += count
            parent_total += total
        return total_count / max(parent_total, 1), total_count, parent_total

    def _update_gate_summary(self):
        gate = self._selected_gate()
        if gate is None:
            self.gate_summary.setPlainText("Select a gate to view summary.")
            return
        frac, count, total = self._gate_fraction(gate)
        lines = [
            f"Gate: {gate['name']}",
            f"Type: {gate['gate_type']}",
            f"Channels: {gate['x_channel']} / {gate.get('y_channel') or 'Count'}",
            f"Percent of parent: {count} / {total} ({100 * frac:.1f}%)",
        ]
        self.gate_summary.setPlainText("\n".join(lines))

    def _gate_fraction_for_label(self, gate, label):
        raw_df = self._sample_raw_dataframe(label)
        if raw_df.empty:
            return 0.0, 0, 0
        parent_name = gate.get("parent_population", "__all__")
        if parent_name != "__all__":
            parent_gate = next((item for item in self.gates if item["name"] == parent_name), None)
            if parent_gate is None:
                return 0.0, 0, 0
            parent_mask = self._population_mask(raw_df, parent_gate)
            parent_df = raw_df.loc[parent_mask].copy()
        else:
            parent_df = raw_df
        if parent_df.empty:
            return 0.0, 0, 0
        x_channel = gate["x_channel"]
        if x_channel not in parent_df.columns:
            return 0.0, 0, len(parent_df)
        gate_type = gate["gate_type"]
        if gate_type == "vertical":
            transformed = pd.DataFrame(index=parent_df.index.copy())
            transformed[x_channel] = _transform_array(parent_df[x_channel].to_numpy(), gate.get("x_transform", "arcsinh"), gate.get("x_cofactor", 150.0))
        else:
            y_channel = gate.get("y_channel")
            if y_channel not in parent_df.columns:
                return 0.0, 0, len(parent_df)
            transformed = _apply_transform(
                parent_df,
                x_channel,
                y_channel,
                gate.get("x_transform", "arcsinh"),
                gate.get("x_cofactor", 150.0),
                y_method=gate.get("y_transform", "arcsinh"),
                y_cofactor=gate.get("y_cofactor", 150.0),
            )
        mask = _gate_mask(transformed, gate)
        count = int(mask.sum())
        total = len(parent_df)
        return count / max(total, 1), count, total

    def _on_rectangle_click(self, event):
        if event.inaxes != self.ax or event.xdata is None or event.ydata is None or event.button != 1:
            return
        point = (float(event.xdata), float(event.ydata))
        if self.rectangle_start_point is None:
            self.rectangle_start_point = point
            self.rectangle_current_point = point
            self.status_label.setText("Rectangle first corner set. Click the opposite corner.")
            self.redraw()
            return
        self.pending_gate = PendingGate("rectangle", {"vertices": self._rectangle_vertices(
            self.rectangle_start_point[0],
            self.rectangle_start_point[1],
            point[0],
            point[1],
        )})
        self.rectangle_start_point = None
        self.rectangle_current_point = None
        self._disconnect_drawing()
        self.redraw()
        self.status_label.setText("Rectangle captured. Click Save Gate to keep it.")

    def _on_rectangle_motion(self, event):
        if self.rectangle_start_point is None:
            return
        if event.inaxes != self.ax or event.xdata is None or event.ydata is None:
            return
        self.rectangle_current_point = (float(event.xdata), float(event.ydata))
        self._schedule_redraw()

    def _on_quad_click(self, event):
        if event.inaxes != self.ax or event.xdata is None or event.ydata is None or event.button != 1:
            return
        self.pending_gate = PendingGate(
            "quad",
            {
                "x_threshold": float(event.xdata),
                "y_threshold": float(event.ydata),
                "region": "top right",
            },
        )
        self._disconnect_drawing()
        self.redraw()
        self.status_label.setText("Quad gate captured. Click Save Gate to keep it.")

    def _on_vertical_click(self, event):
        if event.inaxes != self.ax or event.xdata is None or event.button != 1:
            return
        self.vertical_preview_x = None
        self.pending_gate = PendingGate("vertical", {"x_threshold": float(event.xdata), "region": "above"})
        self._disconnect_drawing()
        self.redraw()
        self.status_label.setText("Vertical gate captured. Click Save Gate to keep it.")

    def _on_vertical_motion(self, event):
        if event.inaxes != self.ax or event.xdata is None:
            return
        self.vertical_preview_x = float(event.xdata)
        self._schedule_redraw()

    def _on_horizontal_click(self, event):
        if event.inaxes != self.ax or event.ydata is None or event.button != 1:
            return
        self.horizontal_preview_y = None
        self.pending_gate = PendingGate("horizontal", {"y_threshold": float(event.ydata), "region": "above"})
        self._disconnect_drawing()
        self.redraw()
        self.status_label.setText("Horizontal gate captured. Click Save Gate to keep it.")

    def _on_horizontal_motion(self, event):
        if event.inaxes != self.ax or event.ydata is None:
            return
        self.horizontal_preview_y = float(event.ydata)
        self._schedule_redraw()

    def _on_polygon_click(self, event):
        if event.inaxes != self.ax or event.xdata is None or event.ydata is None:
            return
        point = (float(event.xdata), float(event.ydata))
        if event.button == 3 and len(self.polygon_vertices) >= 3:
            self.pending_gate = PendingGate("polygon", {"vertices": list(self.polygon_vertices)})
            self.polygon_vertices = []
            self.polygon_cursor_point = None
            self._disconnect_drawing()
            self.redraw()
            self.status_label.setText("Polygon captured. Click Save Gate to keep it.")
            return
        if event.button != 1:
            return
        if len(self.polygon_vertices) >= 3:
            first_x, first_y = self.polygon_vertices[0]
            x_span = max(self.ax.get_xlim()[1] - self.ax.get_xlim()[0], 1e-9)
            y_span = max(self.ax.get_ylim()[1] - self.ax.get_ylim()[0], 1e-9)
            close_tol = 0.04 * max(x_span, y_span)
            if np.hypot(point[0] - first_x, point[1] - first_y) <= close_tol or getattr(event, "dblclick", False):
                self.pending_gate = PendingGate("polygon", {"vertices": list(self.polygon_vertices)})
                self.polygon_vertices = []
                self.polygon_cursor_point = None
                self._disconnect_drawing()
                self.redraw()
                self.status_label.setText("Polygon captured. Click Save Gate to keep it.")
                return
        self.polygon_vertices.append(point)
        self.pending_gate = PendingGate("polygon", {"vertices": list(self.polygon_vertices)})
        self.redraw()
        self.status_label.setText("Polygon vertex added. Click near the first vertex, double-click, or right click to finish.")

    def _on_polygon_motion(self, event):
        if event.inaxes != self.ax or event.xdata is None or event.ydata is None:
            return
        if not self.polygon_vertices:
            return
        self.polygon_cursor_point = (float(event.xdata), float(event.ydata))
        self._schedule_redraw()

    def start_zoom_box(self):
        if self.current_transformed.empty:
            self.status_label.setText("Plot a population before zooming.")
            return
        self._disconnect_drawing()
        self.zoom_start_point = None
        self.zoom_current_point = None
        self.canvas_click_cid = self.canvas.mpl_connect("button_press_event", self._on_zoom_box_click)
        self.canvas_motion_cid = self.canvas.mpl_connect("motion_notify_event", self._on_zoom_box_motion)
        self.mode_label.setText("Mode: zoom box")
        self.status_label.setText("Zoom box mode active. Click one corner, then the opposite corner.")

    def _on_zoom_box_click(self, event):
        if event.inaxes != self.ax or event.xdata is None or event.ydata is None or event.button != 1:
            return
        point = (float(event.xdata), float(event.ydata))
        if self.zoom_start_point is None:
            self.zoom_start_point = point
            self.zoom_current_point = point
            self.status_label.setText("Zoom box first corner set. Click the opposite corner.")
            self.redraw()
            return
        x0, x1 = sorted([self.zoom_start_point[0], point[0]])
        y0, y1 = sorted([self.zoom_start_point[1], point[1]])
        if np.isclose(x0, x1) or np.isclose(y0, y1):
            self.status_label.setText("Zoom box corners must define a non-zero area.")
            self.zoom_current_point = point
            self.redraw()
            return
        if self.plot_mode_combo.currentText() == "count histogram" or _is_count_axis(self.y_combo.currentText()):
            key = self._hist_axis_override_key()
            if key is not None:
                self.hist_axis_overrides[key] = (x0, x1, y0, y1)
        else:
            x_key = self._scatter_x_axis_override_key()
            y_key = self._scatter_y_axis_override_key()
            if x_key is not None:
                self.scatter_x_axis_overrides[x_key] = (x0, x1)
            if y_key is not None:
                self.scatter_y_axis_overrides[y_key] = (y0, y1)
        self.zoom_start_point = None
        self.zoom_current_point = None
        self._disconnect_drawing()
        self.redraw()
        self.status_label.setText("Zoom box applied.")

    def _on_zoom_box_motion(self, event):
        if self.zoom_start_point is None:
            return
        if event.inaxes != self.ax or event.xdata is None or event.ydata is None:
            return
        self.zoom_current_point = (float(event.xdata), float(event.ydata))
        self._schedule_redraw()

    def reset_zoom(self):
        x_key = self._scatter_x_axis_override_key()
        y_key = self._scatter_y_axis_override_key()
        hist_key = self._hist_axis_override_key()
        if x_key is not None:
            self.scatter_x_axis_overrides.pop(x_key, None)
        if y_key is not None:
            self.scatter_y_axis_overrides.pop(y_key, None)
        if hist_key is not None:
            self.hist_axis_overrides.pop(hist_key, None)
        if not self.current_transformed.empty:
            self.redraw()
        self.status_label.setText("Zoom reset to automatic limits.")

    def start_move_selected_gate(self):
        if self.current_transformed.empty:
            self.status_label.setText("Plot a population before moving a gate.")
            return
        gate = self._selected_gate()
        if gate is None or not self._visible_gate(gate):
            self.status_label.setText("Select a visible saved gate first.")
            return
        if gate["gate_type"] not in {"polygon", "rectangle"}:
            self.status_label.setText("Move Selected Gate currently supports polygon and rectangle gates.")
            return
        self._disconnect_drawing()
        self.translate_gate_mode = True
        self.canvas_press_drag_cid = self.canvas.mpl_connect("button_press_event", self._on_drag_press)
        self.canvas_motion_cid = self.canvas.mpl_connect("motion_notify_event", self._on_drag_motion)
        self.canvas_release_cid = self.canvas.mpl_connect("button_release_event", self._on_drag_release)
        self.mode_label.setText(f"Mode: move {gate['name']}")
        self.status_label.setText("Move mode active. Drag inside the selected gate to translate it.")

    def _enable_saved_gate_interaction(self):
        gate = self._selected_gate()
        if gate is None or not self._visible_gate(gate):
            return
        self._disconnect_drawing()
        self.edit_gate_mode = True
        self.canvas_press_drag_cid = self.canvas.mpl_connect("button_press_event", self._on_drag_press)
        self.canvas_motion_cid = self.canvas.mpl_connect("motion_notify_event", self._on_drag_motion)
        self.canvas_release_cid = self.canvas.mpl_connect("button_release_event", self._on_drag_release)
        self.mode_label.setText(f"Mode: gate selected {gate['name']}")

    def start_edit_selected_gate(self):
        if self.current_transformed.empty:
            self.status_label.setText("Plot a population before editing a gate.")
            return
        gate = self._selected_gate()
        if gate is None or not self._visible_gate(gate):
            self.status_label.setText("Select a visible saved gate first.")
            return
        self._disconnect_drawing()
        self.edit_gate_mode = True
        self.canvas_press_drag_cid = self.canvas.mpl_connect("button_press_event", self._on_drag_press)
        self.canvas_motion_cid = self.canvas.mpl_connect("motion_notify_event", self._on_drag_motion)
        self.canvas_release_cid = self.canvas.mpl_connect("button_release_event", self._on_drag_release)
        self.mode_label.setText(f"Mode: edit {gate['name']}")
        self.status_label.setText("Edit mode active. Drag thresholds, quad lines, vertices, or a gate body.")

    def _gate_hit_test(self, gate, event):
        if event.inaxes != self.ax or event.xdata is None or event.ydata is None:
            return None
        x_span = max(self.ax.get_xlim()[1] - self.ax.get_xlim()[0], 1e-9)
        y_span = max(self.ax.get_ylim()[1] - self.ax.get_ylim()[0], 1e-9)
        x_tol = 0.03 * x_span
        y_tol = 0.03 * y_span
        if gate["gate_type"] == "vertical":
            if abs(float(event.xdata) - gate["x_threshold"]) <= x_tol:
                return {"mode": "vertical"}
            return None
        if gate["gate_type"] == "horizontal":
            if abs(float(event.ydata) - gate["y_threshold"]) <= y_tol:
                return {"mode": "horizontal"}
            return None
        if gate["gate_type"] == "quad":
            x_hit = abs(float(event.xdata) - gate["x_threshold"]) <= x_tol
            y_hit = abs(float(event.ydata) - gate["y_threshold"]) <= y_tol
            if x_hit or y_hit:
                return {"mode": "quad"}
            return None
        if gate["gate_type"] in {"polygon", "rectangle"}:
            vertices = np.asarray(gate["vertices"], dtype=float)
            if len(vertices) < 3:
                return None
            distances = np.sqrt(((vertices - np.array([[float(event.xdata), float(event.ydata)]])) ** 2).sum(axis=1))
            if self.edit_gate_mode and distances.min() <= max(x_tol, y_tol):
                return {"mode": "polygon_vertex", "vertex_index": int(distances.argmin())}
            if Path(vertices).contains_point((float(event.xdata), float(event.ydata))):
                return {"mode": "polygon_translate"}
        return None

    def _on_drag_press(self, event):
        if event.button != 1:
            return
        gate = self._selected_gate()
        if gate is None or not self._visible_gate(gate):
            return
        hit = self._gate_hit_test(gate, event)
        if hit is None:
            return
        self.drag_state = {
            "gate_name": gate["name"],
            "press_x": float(event.xdata),
            "press_y": float(event.ydata),
            "press_event_x": float(event.x),
            "press_event_y": float(event.y),
            "active": False,
            "original_gate": dict(gate),
            **hit,
        }

    def _on_drag_motion(self, event):
        if self.drag_state is None or event.inaxes != self.ax or event.xdata is None or event.ydata is None:
            return
        if not self.drag_state["active"]:
            dx_px = float(event.x) - self.drag_state["press_event_x"]
            dy_px = float(event.y) - self.drag_state["press_event_y"]
            if (dx_px * dx_px + dy_px * dy_px) ** 0.5 <= 8:
                return
            self.drag_state["active"] = True
            self.mode_label.setText(f"Mode: moving {self.drag_state['gate_name']}")
        gate = self._selected_gate()
        if gate is None:
            return
        original = self.drag_state["original_gate"]
        dx = float(event.xdata) - self.drag_state["press_x"]
        dy = float(event.ydata) - self.drag_state["press_y"]
        mode = self.drag_state["mode"]
        gate_group = gate.get("gate_group")
        targets = [item for item in self.gates if item.get("gate_group") == gate_group] if gate_group else [gate]
        originals = {
            item["name"]: next((g for g in self.gates if g["name"] == item["name"]), item)
            for item in targets
        }
        if mode == "vertical":
            for target in targets:
                target["x_threshold"] = original["x_threshold"] + dx
        elif mode == "horizontal":
            for target in targets:
                target["y_threshold"] = original["y_threshold"] + dy
        elif mode == "quad":
            gate["x_threshold"] = original["x_threshold"] + dx
            gate["y_threshold"] = original["y_threshold"] + dy
        elif mode == "polygon_vertex":
            vertices = list(original["vertices"])
            vertices[self.drag_state["vertex_index"]] = (float(event.xdata), float(event.ydata))
            gate["vertices"] = vertices
        elif mode == "polygon_translate":
            gate["vertices"] = [(x + dx, y + dy) for x, y in original["vertices"]]
        self._schedule_redraw()

    def _on_drag_release(self, _event):
        if self.drag_state is None:
            return
        gate_name = self.drag_state["gate_name"]
        moved = self.drag_state.get("active", False)
        self.drag_state = None
        was_translate = self.translate_gate_mode
        self.translate_gate_mode = False
        if was_translate:
            self._disconnect_drawing()
        else:
            self.edit_gate_mode = True
            self.mode_label.setText(f"Mode: gate selected {gate_name}")
        self.redraw()
        if moved:
            self._invalidate_cached_outputs()
            self._update_gate_summary()
            self._schedule_heatmap_update()
            self.status_label.setText(f"Updated gate '{gate_name}'.")
        else:
            self.status_label.setText("Move mode cancelled.")

    def _disconnect_drawing(self):
        self.edit_gate_mode = False
        self.translate_gate_mode = False
        self.drag_state = None
        if self.canvas_click_cid is not None:
            self.canvas.mpl_disconnect(self.canvas_click_cid)
            self.canvas_click_cid = None
        if self.canvas_motion_cid is not None:
            self.canvas.mpl_disconnect(self.canvas_motion_cid)
            self.canvas_motion_cid = None
        if self.canvas_release_cid is not None:
            self.canvas.mpl_disconnect(self.canvas_release_cid)
            self.canvas_release_cid = None
        if self.canvas_press_drag_cid is not None:
            self.canvas.mpl_disconnect(self.canvas_press_drag_cid)
            self.canvas_press_drag_cid = None
        self.rectangle_start_point = None
        self.rectangle_current_point = None
        self.zoom_start_point = None
        self.zoom_current_point = None
        self.vertical_preview_x = None
        self.horizontal_preview_y = None
        self.polygon_cursor_point = None
        self.mode_label.setText("Mode: idle")

    def _clear_plot(self):
        self.ax.clear()
        self.ax.set_title("No population plotted")
        self.ax.set_xlabel("X")
        self.ax.set_ylabel("Y")
        self.canvas.draw_idle()

    def _on_well_selection_changed(self):
        self._refresh_channel_controls()
        wells = self._selected_wells()
        if len(wells) == 1:
            self.sample_name_edit.setText(str(self._metadata_for_well(wells[0]).get("sample_name", "")))
        elif not wells:
            self.sample_name_edit.setText("")
        self._refresh_plate_panel()
        self._schedule_plot_update()

    def _on_channel_changed(self):
        if self.plot_mode_combo.currentText() == "count histogram":
            self.y_combo.blockSignals(True)
            self.y_combo.setCurrentText("Count")
            self.y_combo.blockSignals(False)
        self._refresh_heatmap_controls()
        self._schedule_plot_update()

    def _on_population_changed(self):
        self._schedule_plot_update()

    def _trigger_auto_plot(self, *_args):
        self._schedule_plot_update()

    def _on_auto_plot_mode_changed(self):
        self.auto_plot_enabled = self.auto_plot_auto_radio.isChecked()

    def open_graph_options_dialog(self):
        dialog = QDialog(self)
        dialog.setWindowTitle("Graph Options")
        dialog.resize(760, 320)
        layout = QVBoxLayout(dialog)
        grid = QGridLayout()
        layout.addLayout(grid)

        histogram_mode = self._histogram_mode()
        if histogram_mode:
            plotted = self._downsample(self.current_transformed)
            auto_limits = self._median_histogram_axis_limits(transformed=plotted)
            current = self._effective_histogram_axis_limits(transformed=plotted) or auto_limits
            extent = self._global_histogram_axis_extent()
        else:
            auto_limits = self._median_scatter_axis_limits()
            current = self._effective_scatter_axis_limits() or auto_limits
            extent = self._global_scatter_axis_extent()
        if current is None:
            current = (*self.ax.get_xlim(), *self.ax.get_ylim())
        if extent is None:
            extent = current

        scale_max = 1000

        def _fmt(value):
            return "" if value is None else f"{value:.6g}"

        def _safe_range(low, high):
            if not np.isfinite(low) or not np.isfinite(high):
                return -1.0, 1.0
            if np.isclose(low, high):
                pad = max(abs(high) * 0.1, 1.0)
                return low - pad, high + pad
            return low, high

        xmin_limit, xmax_limit = _safe_range(float(extent[0]), float(extent[1]))
        ymin_limit, ymax_limit = _safe_range(float(extent[2]), float(extent[3]))

        def _to_slider(value, low, high):
            if np.isclose(low, high):
                return 0
            clipped = min(max(float(value), low), high)
            return int(round((clipped - low) / (high - low) * scale_max))

        def _from_slider(raw, low, high):
            if np.isclose(low, high):
                return low
            return low + (high - low) * (float(raw) / scale_max)

        controls = {}

        def _add_axis_row(row, label_text, current_value, low, high):
            label = QLabel(label_text)
            edit = QLineEdit(_fmt(current_value))
            slider = QSlider(Qt.Horizontal)
            slider.setRange(0, scale_max)
            slider.setValue(_to_slider(current_value, low, high))
            range_label = QLabel(f"{_fmt(low)} to {_fmt(high)}")
            grid.addWidget(label, row, 0)
            grid.addWidget(edit, row, 1)
            grid.addWidget(slider, row, 2)
            grid.addWidget(range_label, row, 3)
            controls[label_text] = {"edit": edit, "slider": slider, "low": low, "high": high}
            return edit, slider

        xmin_edit, xmin_slider = _add_axis_row(0, "X Min", current[0], xmin_limit, xmax_limit)
        xmax_edit, xmax_slider = _add_axis_row(1, "X Max", current[1], xmin_limit, xmax_limit)
        ymin_edit, ymin_slider = _add_axis_row(2, "Y Min", current[2], ymin_limit, ymax_limit)
        ymax_edit, ymax_slider = _add_axis_row(3, "Y Max", current[3], ymin_limit, ymax_limit)

        auto_label = QLabel(
            "Auto limits: "
            f"X [{_fmt(auto_limits[0])}, {_fmt(auto_limits[1])}]"
            f"    Y [{_fmt(auto_limits[2])}, {_fmt(auto_limits[3])}]"
            if auto_limits is not None
            else "Auto limits unavailable for the current view."
        )
        auto_label.setWordWrap(True)
        layout.addWidget(auto_label)

        def _sync_edit_from_slider(edit, slider, low, high):
            edit.setText(_fmt(_from_slider(slider.value(), low, high)))

        def _sync_slider_from_edit(edit, slider, low, high):
            try:
                value = float(edit.text().strip())
            except ValueError:
                return
            slider.blockSignals(True)
            slider.setValue(_to_slider(value, low, high))
            slider.blockSignals(False)

        for item in controls.values():
            item["slider"].valueChanged.connect(
                lambda _value, edit=item["edit"], slider=item["slider"], low=item["low"], high=item["high"]: _sync_edit_from_slider(edit, slider, low, high)
            )
            item["edit"].editingFinished.connect(
                lambda edit=item["edit"], slider=item["slider"], low=item["low"], high=item["high"]: _sync_slider_from_edit(edit, slider, low, high)
            )

        button_row = QHBoxLayout()
        layout.addLayout(button_row)
        use_auto_button = QPushButton("Use Auto")
        apply_button = QPushButton("Apply")
        close_button = QPushButton("Close")
        button_row.addWidget(use_auto_button)
        button_row.addWidget(apply_button)
        button_row.addStretch(1)
        button_row.addWidget(close_button)

        def _reset_auto():
            if auto_limits is not None:
                xmin_edit.setText(_fmt(auto_limits[0]))
                xmax_edit.setText(_fmt(auto_limits[1]))
                ymin_edit.setText(_fmt(auto_limits[2]))
                ymax_edit.setText(_fmt(auto_limits[3]))
                _sync_slider_from_edit(xmin_edit, xmin_slider, xmin_limit, xmax_limit)
                _sync_slider_from_edit(xmax_edit, xmax_slider, xmin_limit, xmax_limit)
                _sync_slider_from_edit(ymin_edit, ymin_slider, ymin_limit, ymax_limit)
                _sync_slider_from_edit(ymax_edit, ymax_slider, ymin_limit, ymax_limit)
            if histogram_mode:
                hist_key = self._hist_axis_override_key()
                if hist_key is not None:
                    self.hist_axis_overrides.pop(hist_key, None)
            else:
                x_key = self._scatter_x_axis_override_key()
                y_key = self._scatter_y_axis_override_key()
                if x_key is not None:
                    self.scatter_x_axis_overrides.pop(x_key, None)
                if y_key is not None:
                    self.scatter_y_axis_overrides.pop(y_key, None)
            self.plot_population()

        def _apply():
            try:
                xmin = float(xmin_edit.text().strip())
                xmax = float(xmax_edit.text().strip())
                ymin = float(ymin_edit.text().strip())
                ymax = float(ymax_edit.text().strip())
            except ValueError:
                self.status_label.setText("Graph options require numeric axis limits.")
                return
            if xmin >= xmax or ymin >= ymax:
                self.status_label.setText("Axis minimums must be smaller than maximums.")
                return
            xmin = min(max(xmin, xmin_limit), xmax_limit)
            xmax = min(max(xmax, xmin_limit), xmax_limit)
            ymin = min(max(ymin, ymin_limit), ymax_limit)
            ymax = min(max(ymax, ymin_limit), ymax_limit)
            xmin_edit.setText(_fmt(xmin))
            xmax_edit.setText(_fmt(xmax))
            ymin_edit.setText(_fmt(ymin))
            ymax_edit.setText(_fmt(ymax))
            _sync_slider_from_edit(xmin_edit, xmin_slider, xmin_limit, xmax_limit)
            _sync_slider_from_edit(xmax_edit, xmax_slider, xmin_limit, xmax_limit)
            _sync_slider_from_edit(ymin_edit, ymin_slider, ymin_limit, ymax_limit)
            _sync_slider_from_edit(ymax_edit, ymax_slider, ymin_limit, ymax_limit)
            if histogram_mode:
                hist_key = self._hist_axis_override_key()
                if hist_key is not None:
                    self.hist_axis_overrides[hist_key] = (xmin, xmax, ymin, ymax)
            else:
                x_key = self._scatter_x_axis_override_key()
                y_key = self._scatter_y_axis_override_key()
                if x_key is not None:
                    self.scatter_x_axis_overrides[x_key] = (xmin, xmax)
                if y_key is not None:
                    self.scatter_y_axis_overrides[y_key] = (ymin, ymax)
            self.plot_population()

        use_auto_button.clicked.connect(_reset_auto)
        apply_button.clicked.connect(_apply)
        close_button.clicked.connect(dialog.close)
        dialog.exec()

    def _refresh_heatmap_controls(self):
        gate_names = [gate["name"] for gate in self.gates]
        self.heatmap_metric_combo.blockSignals(True)
        self.heatmap_metric_combo.clear()
        self.heatmap_metric_combo.addItems(gate_names)
        self.heatmap_metric_combo.blockSignals(False)
        channels = self._fluorescence_channels() or list(self.channel_names)
        self.heatmap_channel_combo.blockSignals(True)
        self.heatmap_channel_combo.clear()
        self.heatmap_channel_combo.addItems(channels)
        self.heatmap_channel_combo.blockSignals(False)

    def _schedule_heatmap_update(self, *_args, delay_ms=120):
        self._heatmap_update_pending = True
        self.heatmap_status_label.setText("Updating heatmap...")
        self._heatmap_timer.start(max(int(delay_ms), 0))

    def _schedule_redraw(self, delay_ms=12):
        self._redraw_timer.start(max(int(delay_ms), 0))

    def _schedule_plot_update(self, delay_ms=0):
        if self._suspend_auto_plot or not self.file_map or not self.auto_plot_enabled:
            return
        self._plot_timer.start(max(int(delay_ms), 0))

    def _session_dir(self):
        session_dir = os.path.join(os.path.expanduser("~"), "Library", "Application Support", "FlowJitsu", "sessions")
        os.makedirs(session_dir, exist_ok=True)
        return session_dir

    def _settings_path(self):
        settings_dir = os.path.join(os.path.expanduser("~"), "Library", "Application Support", "FlowJitsu")
        os.makedirs(settings_dir, exist_ok=True)
        return os.path.join(settings_dir, "settings.json")

    def _last_session_path(self):
        return os.path.join(self._session_dir(), "last_flow_session.json")

    def _load_settings(self):
        path = self._settings_path()
        if os.path.isfile(path):
            try:
                with open(path) as fh:
                    payload = json.load(fh)
                return payload if isinstance(payload, dict) else {}
            except Exception:
                return {}
        return {}

    def _save_settings(self, settings):
        with open(self._settings_path(), "w") as fh:
            json.dump(settings, fh, indent=2)

    def _recent_sessions(self):
        recent = self._load_settings().get("recent_sessions", [])
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
        current = self.recent_session_combo.currentText()
        self.recent_session_combo.blockSignals(True)
        self.recent_session_combo.clear()
        self.recent_session_combo.addItems(recent)
        if current in recent:
            self.recent_session_combo.setCurrentText(current)
        elif recent:
            self.recent_session_combo.setCurrentIndex(0)
        self.recent_session_combo.blockSignals(False)

    def _default_export_dir(self):
        export_dir = os.path.join(os.path.expanduser("~"), "Library", "Application Support", "FlowJitsu", "exports")
        os.makedirs(export_dir, exist_ok=True)
        return export_dir

    def _app_home(self):
        home = os.path.join(os.path.expanduser("~"), "Library", "Application Support", "FlowJitsu")
        os.makedirs(home, exist_ok=True)
        return home

    def _session_payload(self):
        return {
            "folder": self.folder_edit.text().strip(),
            "instrument": self.instrument_combo.currentText(),
            "gates": self.gates,
            "plate_metadata": self.plate_metadata,
            "compensation": self._compensation_payload(),
            "plot": {
                "population": self.population_combo.currentText(),
                "x_channel": self.x_combo.currentText(),
                "y_channel": self.y_combo.currentText(),
                "plot_mode": self.plot_mode_combo.currentText(),
                "x_transform": self.x_transform_combo.currentText(),
                "x_cofactor": int(self.x_cofactor_spin.value()),
                "y_transform": self.y_transform_combo.currentText(),
                "y_cofactor": int(self.y_cofactor_spin.value()),
                "max_points": int(self.max_points_spin.value()),
            },
        }

    def _apply_session_payload(self, payload):
        self._suspend_auto_plot = True
        folder = payload.get("folder", "")
        instrument = payload.get("instrument", self.instrument_combo.currentText())
        if folder:
            self.folder_edit.setText(folder)
        self.instrument_combo.setCurrentText(instrument)
        self.load_folder()
        self.gates = list(payload.get("gates", []))
        self.plate_metadata = dict(payload.get("plate_metadata", {}))
        self._load_compensation_payload(payload.get("compensation", {}))
        plot = payload.get("plot", {})
        self.max_points_spin.setValue(int(plot.get("max_points", self.max_points_spin.value())))
        self.x_transform_combo.setCurrentText(plot.get("x_transform", self.x_transform_combo.currentText()))
        self.x_cofactor_spin.setValue(int(plot.get("x_cofactor", self.x_cofactor_spin.value())))
        self.y_transform_combo.setCurrentText(plot.get("y_transform", self.y_transform_combo.currentText()))
        self.y_cofactor_spin.setValue(int(plot.get("y_cofactor", self.y_cofactor_spin.value())))
        if plot.get("plot_mode") in {"scatter", "count histogram"}:
            self.plot_mode_combo.setCurrentText(plot["plot_mode"])
        if plot.get("x_channel") in self.channel_names:
            self.x_combo.setCurrentText(plot["x_channel"])
        y_values = [self.y_combo.itemText(i) for i in range(self.y_combo.count())]
        if plot.get("y_channel") in y_values:
            self.y_combo.setCurrentText(plot["y_channel"])
        self._refresh_well_list(selected_labels=self._selected_labels())
        self._refresh_saved_gates()
        self._refresh_population_combo(selected_name=plot.get("population", "All Events"))
        self._refresh_heatmap_controls()
        self._refresh_plate_panel()
        self._invalidate_cached_outputs()
        self._update_gate_summary()
        self._schedule_heatmap_update(delay_ms=0)
        self.redraw()
        self._suspend_auto_plot = False
        if self.file_map:
            self.plot_population()

    def save_session(self):
        filename, _ = QFileDialog.getSaveFileName(
            self,
            "Save Session",
            os.path.join(self._session_dir(), "flow_session.json"),
            "JSON files (*.json)",
        )
        if not filename:
            return
        try:
            payload = self._session_payload()
            with open(filename, "w") as fh:
                json.dump(payload, fh, indent=2)
            with open(self._last_session_path(), "w") as fh:
                json.dump(payload, fh, indent=2)
            self._remember_recent_session(filename)
            self.status_label.setText(f"Saved session to {filename}")
        except Exception as exc:
            self.status_label.setText(f"Failed to save session: {type(exc).__name__}: {exc}")

    def load_session(self):
        filename, _ = QFileDialog.getOpenFileName(
            self,
            "Load Session",
            self._session_dir(),
            "JSON files (*.json)",
        )
        if not filename:
            return
        try:
            with open(filename) as fh:
                payload = json.load(fh)
            self._apply_session_payload(payload)
            with open(self._last_session_path(), "w") as fh:
                json.dump(payload, fh, indent=2)
            self._remember_recent_session(filename)
            self.status_label.setText(f"Loaded session from {filename}")
        except Exception as exc:
            self.status_label.setText(f"Failed to load session: {type(exc).__name__}: {exc}")

    def load_recent_session(self):
        filename = self.recent_session_combo.currentText().strip()
        if not filename:
            self.status_label.setText("No recent session selected.")
            return
        if not os.path.isfile(filename):
            self.status_label.setText(f"Recent session not found: {filename}")
            self._refresh_recent_sessions()
            return
        try:
            with open(filename) as fh:
                payload = json.load(fh)
            self._apply_session_payload(payload)
            with open(self._last_session_path(), "w") as fh:
                json.dump(payload, fh, indent=2)
            self._remember_recent_session(filename)
            self.status_label.setText(f"Loaded recent session from {filename}")
        except Exception as exc:
            self.status_label.setText(f"Failed to load recent session: {type(exc).__name__}: {exc}")

    def _autoload_last_session_or_folder(self, base_dir):
        last_session = self._last_session_path()
        if os.path.isfile(last_session):
            try:
                with open(last_session) as fh:
                    payload = json.load(fh)
                self._apply_session_payload(payload)
                self.status_label.setText(f"Loaded last session from {last_session}")
                return
            except Exception as exc:
                self.status_label.setText(f"Could not auto-load last session: {type(exc).__name__}: {exc}")
        if base_dir and os.path.isdir(base_dir):
            self.folder_edit.setText(base_dir)
            self.load_folder()

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
        }

    def check_for_updates(self):
        try:
            self.status_label.setText("Checking GitHub for updates...")
            latest = self._latest_release_info()
            latest_tag = latest.get("tag_name", "") or ""
            current_tag = f"v{_normalize_version_tag(__version__)}"
            self.version_label.setText(f"Version {__version__} | Latest {latest_tag or 'unknown'}")
            if latest_tag and _version_key(latest_tag) > _version_key(current_tag):
                action = QMessageBox.question(
                    self,
                    "Update Available",
                    f"A newer version is available.\n\nCurrent: {current_tag}\nLatest: {latest_tag}\n\nOpen the GitHub release page?",
                    QMessageBox.Yes | QMessageBox.No,
                    QMessageBox.Yes,
                )
                self.status_label.setText(f"Update available: {latest_tag}")
                if action == QMessageBox.Yes:
                    webbrowser.open(latest.get("html_url", GITHUB_RELEASES_URL))
            else:
                QMessageBox.information(
                    self,
                    "Up To Date",
                    f"You are already on the latest available version.\n\nCurrent: {current_tag}\nLatest: {latest_tag or current_tag}",
                )
                self.status_label.setText(f"Up to date: {current_tag}")
        except HTTPError as exc:
            self.status_label.setText(f"Update check failed: HTTPError {exc.code}")
        except Exception as exc:
            self.status_label.setText(f"Update check failed: {type(exc).__name__}: {exc}")

    def closeEvent(self, event):
        choice = QMessageBox.question(
            self,
            "Save Session Before Closing",
            "Do you want to save your session before closing?",
            QMessageBox.Yes | QMessageBox.No | QMessageBox.Cancel,
            QMessageBox.Yes,
        )
        if choice == QMessageBox.Cancel:
            event.ignore()
            return
        if choice == QMessageBox.Yes:
            filename, _ = QFileDialog.getSaveFileName(
                self,
                "Save Session",
                os.path.join(self._session_dir(), "flow_session.json"),
                "JSON files (*.json)",
            )
            if not filename:
                event.ignore()
                return
            try:
                payload = self._session_payload()
                with open(filename, "w") as fh:
                    json.dump(payload, fh, indent=2)
                with open(self._last_session_path(), "w") as fh:
                    json.dump(payload, fh, indent=2)
                self._remember_recent_session(filename)
            except Exception as exc:
                self.status_label.setText(f"Failed to save session: {type(exc).__name__}: {exc}")
                event.ignore()
                return
        event.accept()

    def _gate_template_payload(self):
        return {
            "template_type": "flow_gate_template",
            "version": 1,
            "instrument": self.instrument_combo.currentText(),
            "channels": sorted({
                channel
                for gate in self.gates
                for channel in [gate.get("x_channel"), gate.get("y_channel")]
                if channel
            }),
            "gates": self.gates,
        }

    def save_gate_template(self):
        if not self.gates:
            self.status_label.setText("No gates to save as a template.")
            return
        filename, _ = QFileDialog.getSaveFileName(
            self,
            "Save Gate Template",
            os.path.join(self._session_dir(), "gate_template.json"),
            "JSON files (*.json)",
        )
        if not filename:
            return
        try:
            with open(filename, "w") as fh:
                json.dump(self._gate_template_payload(), fh, indent=2)
            self.status_label.setText(f"Saved gate template to {filename}")
        except Exception as exc:
            self.status_label.setText(f"Failed to save gate template: {type(exc).__name__}: {exc}")

    def load_gate_template(self):
        filename, _ = QFileDialog.getOpenFileName(
            self,
            "Load Gate Template",
            self._session_dir(),
            "JSON files (*.json)",
        )
        if not filename:
            return
        try:
            with open(filename) as fh:
                payload = json.load(fh)
            if payload.get("template_type") != "flow_gate_template":
                raise ValueError("Selected file is not a gate template.")
            template_gates = payload.get("gates", [])
            if not isinstance(template_gates, list) or not template_gates:
                raise ValueError("Gate template does not contain any gates.")
            existing_names = {gate["name"] for gate in self.gates}
            duplicates = sorted(existing_names & {gate["name"] for gate in template_gates})
            if duplicates:
                raise ValueError(f"Template gate names already exist: {', '.join(duplicates)}")
            self.gates.extend(template_gates)
            self._refresh_saved_gates(selected_name=template_gates[0]["name"])
            self._refresh_population_combo()
            self._refresh_heatmap_controls()
            self._invalidate_cached_outputs()
            self.redraw()
            self._update_gate_summary()
            self._schedule_heatmap_update()
            self.status_label.setText(f"Loaded gate template from {filename}")
        except Exception as exc:
            self.status_label.setText(f"Failed to load gate template: {type(exc).__name__}: {exc}")

    def _summary_dataframe(self):
        if self._summary_cache is not None:
            return self._summary_cache.copy()
        rows = []
        for label, relpath in self.file_map.items():
            well = label.split(" | ")[0]
            if self._metadata_for_well(well).get("excluded", False):
                continue
            df = self._sample_raw_dataframe(label)
            meta = self._metadata_for_well(well)
            row = {
                "well": well,
                "source": relpath,
                "event_count": len(df),
                "sample_name": meta.get("sample_name", ""),
                "sample_type": meta.get("sample_type", ""),
                "dose_curve": meta.get("dose_curve", ""),
                "dose": meta.get("dose", ""),
                "replicate": meta.get("replicate", ""),
                "dose_direction": meta.get("dose_direction", ""),
                "treatment_group": meta.get("treatment_group", ""),
                "excluded": bool(meta.get("excluded", False)),
            }
            for gate in self.gates:
                frac, count, parent_total = self._gate_fraction_for_label(gate, label)
                row[f"pct_{gate['name']}"] = 100.0 * frac
                row[f"count_{gate['name']}"] = count
                row[f"parent_count_{gate['name']}"] = parent_total
            rows.append(row)
        summary = pd.DataFrame(rows)
        self._summary_cache = summary
        return summary.copy()

    def _intensity_distribution_dataframe(self):
        if self._intensity_cache is not None:
            return self._intensity_cache.copy()
        fluorescence_columns = self._fluorescence_channels()
        frames = []
        for label, relpath in self.file_map.items():
            well = label.split(" | ")[0]
            if self._metadata_for_well(well).get("excluded", False):
                continue
            df = self._sample_raw_dataframe(label)
            keep_columns = ["__well__", "__source__"] + [col for col in fluorescence_columns if col in df.columns]
            out = df[keep_columns].copy()
            out.rename(columns={"__well__": "well", "__source__": "source"}, inplace=True)
            meta = self._metadata_for_well(well)
            out["sample_name"] = meta.get("sample_name", "")
            out["sample_type"] = meta.get("sample_type", "")
            out["dose_curve"] = meta.get("dose_curve", "")
            out["dose"] = meta.get("dose", "")
            out["replicate"] = meta.get("replicate", "")
            out["dose_direction"] = meta.get("dose_direction", "")
            out["treatment_group"] = meta.get("treatment_group", "")
            out["excluded"] = bool(meta.get("excluded", False))
            for gate in self.gates:
                frac_mask = pd.Series(False, index=df.index)
                x_channel = gate["x_channel"]
                if x_channel in df.columns:
                    if gate["gate_type"] == "vertical":
                        transformed = pd.DataFrame(index=df.index.copy())
                        transformed[x_channel] = _transform_array(df[x_channel].to_numpy(), gate.get("x_transform", "arcsinh"), gate.get("x_cofactor", 150.0))
                        frac_mask = pd.Series(_gate_mask(transformed, gate), index=df.index)
                    else:
                        y_channel = gate.get("y_channel")
                        if y_channel in df.columns:
                            transformed = _apply_transform(
                                df,
                                x_channel,
                                y_channel,
                                gate.get("x_transform", "arcsinh"),
                                gate.get("x_cofactor", 150.0),
                                y_method=gate.get("y_transform", "arcsinh"),
                                y_cofactor=gate.get("y_cofactor", 150.0),
                            )
                            frac_mask = pd.Series(_gate_mask(transformed, gate), index=df.index)
                out[f"in_{gate['name']}"] = frac_mask.to_numpy()
            frames.append(out)
        intensity = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
        self._intensity_cache = intensity
        return intensity.copy()

    def _plate_metadata_dataframe(self):
        rows = []
        for well, meta in sorted(self.plate_metadata.items(), key=lambda item: (item[0][0], int(item[0][1:]))):
            row = {"well": well}
            row.update(meta)
            rows.append(row)
        return pd.DataFrame(rows)

    def export_gate_summary_csv(self):
        filename, _ = QFileDialog.getSaveFileName(
            self,
            "Export Gate Summary CSV",
            os.path.join(self._default_export_dir(), "flow_gate_summary.csv"),
            "CSV files (*.csv)",
        )
        if not filename:
            return
        try:
            self._summary_dataframe().to_csv(filename, index=False)
            self.status_label.setText(f"Saved gate summary to {filename}")
        except Exception as exc:
            self.status_label.setText(f"Failed to save gate summary: {type(exc).__name__}: {exc}")

    def delete_selected_gate(self):
        gate = self._selected_gate()
        if gate is None:
            self.status_label.setText("Select a saved gate to delete.")
            return
        gate_name = gate["name"]
        self.gates = [item for item in self.gates if item["name"] != gate_name]
        self._refresh_saved_gates(selected_name=None)
        self._refresh_population_combo()
        self._refresh_heatmap_controls()
        self._invalidate_cached_outputs()
        self.redraw()
        self._update_gate_summary()
        self._schedule_heatmap_update()
        self.status_label.setText(f"Deleted gate '{gate_name}'.")

    def rename_selected_gate(self):
        gate = self._selected_gate()
        if gate is None:
            self.status_label.setText("Select a saved gate to rename.")
            return
        new_name, ok = QInputDialog.getText(self, "Rename Gate", "New gate name:", text=gate["name"])
        new_name = new_name.strip()
        if not ok or not new_name:
            return
        existing = {item["name"] for item in self.gates if item["name"] != gate["name"]}
        if new_name in existing:
            self.status_label.setText(f"Gate name already exists: {new_name}")
            return
        old_name = gate["name"]
        gate["name"] = new_name
        self._refresh_saved_gates(selected_name=new_name)
        self._refresh_population_combo(selected_name=new_name if self._selected_population_name() == old_name else None)
        self._refresh_heatmap_controls()
        self._invalidate_cached_outputs()
        self.redraw()
        self._update_gate_summary()
        self._schedule_heatmap_update()
        self.status_label.setText(f"Renamed gate '{old_name}' to '{new_name}'.")

    def recolor_selected_gate(self):
        gate = self._selected_gate()
        if gate is None:
            self.status_label.setText("Select a saved gate to recolor.")
            return
        color = QColorDialog.getColor(initial=Qt.white, parent=self, title="Choose Gate Color")
        if not color.isValid():
            return
        gate["color"] = color.name()
        self._refresh_saved_gates(selected_name=gate["name"])
        self.redraw()
        self._update_gate_summary()
        self.status_label.setText(f"Updated gate color for {gate['name']}.")

    def copy_gate_names(self):
        names = "\n".join(gate["name"] for gate in self.gates)
        QApplication.clipboard().setText(names)
        self.status_label.setText("Copied gate names to clipboard.")

    def export_intensity_csv(self):
        filename, _ = QFileDialog.getSaveFileName(
            self,
            "Export Intensities CSV",
            os.path.join(self._default_export_dir(), "flow_intensity_distribution.csv"),
            "CSV files (*.csv)",
        )
        if not filename:
            return
        try:
            self._intensity_distribution_dataframe().to_csv(filename, index=False)
            self.status_label.setText(f"Saved intensity distribution to {filename}")
        except Exception as exc:
            self.status_label.setText(f"Failed to save intensity distribution: {type(exc).__name__}: {exc}")

    def export_plate_metadata_csv(self):
        filename, _ = QFileDialog.getSaveFileName(
            self,
            "Export Plate Metadata CSV",
            os.path.join(self._default_export_dir(), "flow_plate_metadata.csv"),
            "CSV files (*.csv)",
        )
        if not filename:
            return
        try:
            self._plate_metadata_dataframe().to_csv(filename, index=False)
            self.status_label.setText(f"Saved plate metadata to {filename}")
        except Exception as exc:
            self.status_label.setText(f"Failed to save plate metadata: {type(exc).__name__}: {exc}")

    def _analysis_bundle_paths(self):
        return _analysis_bundle_paths_impl(self)

    def _write_analysis_bundle_csvs(self, bundle_paths):
        return _write_analysis_bundle_csvs_impl(self, bundle_paths)

    def open_analysis_preview(self):
        try:
            summary = self._summary_dataframe()
            intensity = self._intensity_distribution_dataframe()
            if summary.empty and intensity.empty:
                self.status_label.setText("No data available yet.")
                return
            dialog = AnalysisPreviewDialog(self, summary, intensity)
            dialog.exec()
        except Exception as exc:
            self.status_label.setText(f"Failed to open analysis preview: {type(exc).__name__}: {exc}")

    def create_analysis_notebook(self):
        try:
            bundle_paths = self._analysis_bundle_paths()
            self._write_analysis_bundle_csvs(bundle_paths)
            nb = _analysis_notebook_dict_impl(
                summary_relpath=os.path.relpath(bundle_paths["summary_path"], os.path.dirname(bundle_paths["notebook_path"])),
                intensity_relpath=os.path.relpath(bundle_paths["intensity_path"], os.path.dirname(bundle_paths["notebook_path"])),
                plate_relpath=os.path.relpath(bundle_paths["plate_path"], os.path.dirname(bundle_paths["notebook_path"])),
                notebook_title=f"{bundle_paths['date_label']} Flow Desktop Analysis",
            )
            with open(bundle_paths["notebook_path"], "w") as fh:
                json.dump(nb, fh, indent=1)
            self.status_label.setText(f"Saved notebook to {bundle_paths['notebook_path']}")
        except Exception as exc:
            self.status_label.setText(f"Failed to create analysis notebook: {type(exc).__name__}: {exc}")

    def export_html_report(self):
        try:
            bundle_paths = self._analysis_bundle_paths()
            summary, intensity, plate = self._write_analysis_bundle_csvs(bundle_paths)
            html_document = _analysis_html_document_impl(self, summary, intensity, plate, bundle_paths)
            with open(bundle_paths["html_path"], "w", encoding="utf-8") as fh:
                fh.write(html_document)
            self.status_label.setText(f"Saved HTML report to {bundle_paths['html_path']}")
        except Exception as exc:
            self.status_label.setText(f"Failed to export HTML report: {type(exc).__name__}: {exc}")

    def _update_heatmap(self):
        self._heatmap_timer.stop()
        self._heatmap_update_pending = False
        self.heatmap_figure.clear()
        self.heatmap_ax = self.heatmap_figure.add_subplot(111)
        if not self.file_map:
            self.heatmap_ax.set_title("No data loaded")
            self.heatmap_canvas.draw_idle()
            self.heatmap_status_label.setText("Heatmap ready")
            return
        self.heatmap_status_label.setText("Updating heatmap...")
        QApplication.processEvents()
        try:
            plate = np.full((8, 12), np.nan)
            mode = self.heatmap_mode_combo.currentText()
            image = None
            if mode == "percent":
                gate_name = self.heatmap_metric_combo.currentText().strip()
                gate = next((item for item in self.gates if item["name"] == gate_name), None)
                if gate is None:
                    self.heatmap_ax.set_title("Select a saved gate for percent heatmap")
                else:
                    for label in self.file_map:
                        well = label.split(" | ")[0]
                        if self._metadata_for_well(well).get("excluded", False):
                            continue
                        frac, _count, _total = self._gate_fraction_for_label(gate, label)
                        plate[ord(well[0]) - 65, int(well[1:]) - 1] = 100.0 * frac
                    image = self.heatmap_ax.imshow(plate, cmap="viridis", vmin=0, vmax=100)
                    self.heatmap_figure.colorbar(image, ax=self.heatmap_ax, fraction=0.046, pad=0.04, label="% positive")
                    self.heatmap_ax.set_title(f"{gate_name} well heatmap")
            else:
                channel = self.heatmap_channel_combo.currentText().strip()
                if not channel:
                    self.heatmap_ax.set_title("Select a channel for MFI heatmap")
                else:
                    for label in self.file_map:
                        well = label.split(" | ")[0]
                        if self._metadata_for_well(well).get("excluded", False):
                            continue
                        raw_df = self._sample_raw_dataframe(label)
                        value = float(np.mean(raw_df[channel])) if (not raw_df.empty and channel in raw_df.columns) else np.nan
                        plate[ord(well[0]) - 65, int(well[1:]) - 1] = value
                    image = self.heatmap_ax.imshow(plate, cmap="magma")
                    self.heatmap_figure.colorbar(image, ax=self.heatmap_ax, fraction=0.046, pad=0.04, label=f"MFI {channel}")
                    self.heatmap_ax.set_title(f"MFI {channel}")
            self._annotate_heatmap_cells(plate, image=image)
            self.heatmap_ax.set_xticks(np.arange(12))
            self.heatmap_ax.set_yticks(np.arange(8))
            self.heatmap_ax.set_xticklabels([str(i) for i in range(1, 13)])
            self.heatmap_ax.set_yticklabels(list("ABCDEFGH"))
            self.heatmap_ax.set_xlabel("Column")
            self.heatmap_ax.set_ylabel("Row")
            self.heatmap_figure.tight_layout()
            self.heatmap_canvas.draw_idle()
            self.heatmap_status_label.setText("Heatmap ready")
        except Exception as exc:
            self.heatmap_ax.set_title(f"Heatmap failed: {type(exc).__name__}")
            self.heatmap_canvas.draw_idle()
            self.heatmap_status_label.setText("Heatmap update failed")

    def _annotate_heatmap_cells(self, plate, image=None):
        finite_values = plate[np.isfinite(plate)]
        if finite_values.size == 0:
            return
        for row_idx in range(plate.shape[0]):
            for col_idx in range(plate.shape[1]):
                value = plate[row_idx, col_idx]
                if not np.isfinite(value):
                    continue
                if image is not None:
                    rgba = image.cmap(image.norm(value))
                    luminance = 0.2126 * rgba[0] + 0.7152 * rgba[1] + 0.0722 * rgba[2]
                    color = "#111111" if luminance >= 0.5 else "#ffffff"
                else:
                    midpoint = float(np.nanmedian(finite_values))
                    color = "#ffffff" if value >= midpoint else "#111111"
                text = f"{value:.1f}"
                self.heatmap_ax.text(
                    col_idx,
                    row_idx,
                    text,
                    ha="center",
                    va="center",
                    color=color,
                    fontsize=8,
                    fontweight="bold",
                )

    def _select_well_from_plate(self, well):
        target_label = next((label for label in self.file_map if label.startswith(f"{well} |")), None)
        if target_label is None:
            self.status_label.setText(f"No FCS file loaded for well {well}.")
            return
        self.well_list.blockSignals(True)
        for idx in range(self.well_list.count()):
            item = self.well_list.item(idx)
            item.setSelected(item.data(Qt.UserRole) == target_label)
        self.well_list.blockSignals(False)
        self._on_well_selection_changed()

    def open_plate_map_editor(self):
        if not self.file_map:
            self.status_label.setText("Load a folder first.")
            return
        dialog = QDialog(self)
        dialog.setWindowTitle("Plate Map Editor")
        dialog.resize(1120, 760)
        layout = QVBoxLayout(dialog)
        layout.addWidget(QLabel("Drag across the plate to select groups of wells. Use sample assignment or dose-curve mode on the right."))

        body = QHBoxLayout()
        layout.addLayout(body, stretch=1)

        plate_box = QGroupBox("Plate")
        plate_box.setLayout(QVBoxLayout())
        body.addWidget(plate_box, stretch=3)

        editor_box = QGroupBox("Assignments")
        editor_box.setLayout(QVBoxLayout())
        body.addWidget(editor_box, stretch=2)

        row_names = "ABCDEFGH"
        available_wells = {label.split(" | ")[0] for label in self.file_map}
        table = QTableWidget(8, 12)
        table.setSelectionMode(QAbstractItemView.ExtendedSelection)
        table.setSelectionBehavior(QAbstractItemView.SelectItems)
        table.setHorizontalHeaderLabels([str(idx) for idx in range(1, 13)])
        table.setVerticalHeaderLabels(list(row_names))
        table.horizontalHeader().setDefaultSectionSize(64)
        table.verticalHeader().setDefaultSectionSize(52)
        for row_idx, row_name in enumerate(row_names):
            for col_idx in range(12):
                well = f"{row_name}{col_idx + 1}"
                item = QTableWidgetItem(well)
                item.setTextAlignment(Qt.AlignCenter)
                item.setFlags(Qt.ItemIsSelectable | Qt.ItemIsEnabled)
                item.setData(Qt.UserRole, well)
                table.setItem(row_idx, col_idx, item)
        plate_box.layout().addWidget(table)

        summary_label = QLabel("")
        summary_label.setWordWrap(True)
        plate_box.layout().addWidget(summary_label)

        form = QGridLayout()
        editor_box.layout().addLayout(form)

        assignment_mode_combo = QComboBox()
        assignment_mode_combo.addItems(["sample", "dose_curve"])
        sample_edit = QLineEdit(self.sample_name_edit.text().strip())
        sample_type_combo = QComboBox()
        sample_type_combo.addItems(["sample", "negative_control", "positive_control", ""])
        sample_type_combo.setCurrentText("sample")

        form.addWidget(QLabel("Assignment Type"), 0, 0)
        form.addWidget(assignment_mode_combo, 0, 1)
        form.addWidget(QLabel("Sample Name"), 1, 0)
        form.addWidget(sample_edit, 1, 1)
        form.addWidget(QLabel("Sample Type"), 2, 0)
        form.addWidget(sample_type_combo, 2, 1)

        button_row = QHBoxLayout()
        apply_button = QPushButton("Apply Sample")
        toggle_button = QPushButton("Toggle Exclude")
        clear_button = QPushButton("Delete Wells")
        button_row.addWidget(apply_button)
        button_row.addWidget(toggle_button)
        button_row.addWidget(clear_button)
        editor_box.layout().addLayout(button_row)

        sample_manager = QGroupBox("Sample Manager")
        sample_manager.setLayout(QVBoxLayout())
        editor_box.layout().addWidget(sample_manager)
        sample_list = QListWidget()
        sample_manager.layout().addWidget(sample_list)
        sample_action_row = QHBoxLayout()
        extend_button = QPushButton("Extend To Selection")
        delete_sample_button = QPushButton("Delete Sample")
        sample_action_row.addWidget(extend_button)
        sample_action_row.addWidget(delete_sample_button)
        sample_manager.layout().addLayout(sample_action_row)

        dose_box = QGroupBox("Dose Curve Parameters")
        dose_box.setLayout(QGridLayout())
        editor_box.layout().addWidget(dose_box)
        direction_combo = QComboBox()
        direction_combo.addItems(["horizontal", "vertical"])
        points_spin = QSpinBox()
        points_spin.setRange(1, 24)
        points_spin.setValue(4)
        top_dose_spin = QDoubleSpinBox()
        top_dose_spin.setRange(0.0, 1_000_000.0)
        top_dose_spin.setDecimals(4)
        top_dose_spin.setValue(50.0)
        dilution_spin = QDoubleSpinBox()
        dilution_spin.setRange(0.0001, 1_000_000.0)
        dilution_spin.setDecimals(4)
        dilution_spin.setValue(2.0)
        dose_box.layout().addWidget(QLabel("Direction"), 0, 0)
        dose_box.layout().addWidget(direction_combo, 0, 1)
        dose_box.layout().addWidget(QLabel("Points"), 1, 0)
        dose_box.layout().addWidget(points_spin, 1, 1)
        dose_box.layout().addWidget(QLabel("Top Dose"), 2, 0)
        dose_box.layout().addWidget(top_dose_spin, 2, 1)
        dose_box.layout().addWidget(QLabel("Dilution"), 3, 0)
        dose_box.layout().addWidget(dilution_spin, 3, 1)
        export_button = QPushButton("Export Plate CSV")
        export_button.clicked.connect(self.export_plate_metadata_csv)
        dose_box.layout().addWidget(export_button, 4, 0, 1, 2)

        curve_box = QGroupBox("Current Dose Curves")
        curve_box.setLayout(QVBoxLayout())
        editor_box.layout().addWidget(curve_box, stretch=1)
        curve_text = QTextEdit()
        curve_text.setReadOnly(True)
        curve_box.layout().addWidget(curve_text)

        info_label = QLabel("")
        info_label.setWordWrap(True)
        editor_box.layout().addWidget(info_label)
        editor_box.layout().addStretch(1)

        close_row = QHBoxLayout()
        close_row.addStretch(1)
        close_button = QPushButton("Close")
        close_button.clicked.connect(dialog.close)
        close_row.addWidget(close_button)
        layout.addLayout(close_row)

        def _selected_wells_from_table():
            wells = {item.data(Qt.UserRole) for item in table.selectedItems() if item is not None}
            return sorted(wells, key=lambda well: (well[0], int(well[1:])))

        def _set_main_well_selection(wells):
            target_labels = {label for label in self.file_map if label.split(" | ")[0] in set(wells)}
            self.well_list.blockSignals(True)
            for idx in range(self.well_list.count()):
                item = self.well_list.item(idx)
                item.setSelected(item.data(Qt.UserRole) in target_labels)
            self.well_list.blockSignals(False)
            self._on_well_selection_changed()

        def _sample_names_in_use():
            return sorted({
                str(meta.get("sample_name", "")).strip()
                for meta in self.plate_metadata.values()
                if str(meta.get("sample_name", "")).strip()
            })

        def _rebuild_dose_curve_definitions():
            rebuilt = {}
            grouped = {}
            for well, meta in self.plate_metadata.items():
                sample_name = str(meta.get("sample_name", "")).strip()
                curve_name = str(meta.get("dose_curve", "")).strip()
                if not sample_name or not curve_name:
                    continue
                grouped.setdefault(curve_name, []).append((well, meta))
            for curve_name, items in grouped.items():
                wells = sorted([well for well, _meta in items], key=lambda well: (well[0], int(well[1:])))
                first_meta = items[0][1]
                doses = []
                for _well, meta in items:
                    try:
                        doses.append(float(meta.get("dose", "")))
                    except Exception:
                        continue
                top_dose = max(doses) if doses else ""
                dilution = ""
                if len(doses) >= 2:
                    ordered = sorted([dose for dose in doses if dose > 0], reverse=True)
                    if len(ordered) >= 2 and ordered[1] > 0:
                        dilution = ordered[0] / ordered[1]
                rebuilt[curve_name] = {
                    "sample_name": str(first_meta.get("sample_name", "")).strip(),
                    "direction": first_meta.get("dose_direction", ""),
                    "points": len(wells),
                    "top_dose": top_dose,
                    "dilution": dilution,
                    "wells": wells,
                }
            return rebuilt

        def _refresh_curve_panel():
            definitions = _rebuild_dose_curve_definitions()
            if not definitions:
                curve_text.setPlainText("No dose curves assigned yet.")
                return
            blocks = []
            for key, definition in sorted(definitions.items()):
                wells_text = ", ".join(definition["wells"])
                blocks.append(
                    f"{key}\n"
                    f"  direction: {definition['direction']}\n"
                    f"  points: {definition['points']}\n"
                    f"  top dose: {definition['top_dose']}\n"
                    f"  dilution: {definition['dilution']}\n"
                    f"  wells: {wells_text}"
                )
            curve_text.setPlainText("\n\n".join(blocks))

        def _refresh_sample_panel():
            current = sample_list.currentItem().text() if sample_list.currentItem() else ""
            names = _sample_names_in_use()
            sample_list.blockSignals(True)
            sample_list.clear()
            for name in names:
                sample_list.addItem(name)
            if current in names:
                matches = sample_list.findItems(current, Qt.MatchExactly)
                if matches:
                    sample_list.setCurrentItem(matches[0])
            sample_list.blockSignals(False)

        def _selected_sample_name():
            item = sample_list.currentItem()
            return item.text().strip() if item is not None else ""

        def _refresh_dialog():
            selected_wells = set(_selected_wells_from_table())
            active_sample = _selected_sample_name()
            for row_idx, row_name in enumerate(row_names):
                for col_idx in range(12):
                    well = f"{row_name}{col_idx + 1}"
                    item = table.item(row_idx, col_idx)
                    meta = self._metadata_for_well(well)
                    sample_name = str(meta.get("sample_name", "")).strip()
                    excluded = bool(meta.get("excluded", False))
                    has_fcs = well in available_wells
                    if active_sample and sample_name == active_sample:
                        bg = QColor("#ffd166" if well not in selected_wells else "#f6bd60")
                        fg = QColor("#111111")
                    elif excluded:
                        bg = QColor("#d9d9d9")
                        fg = QColor("#111111")
                    elif sample_name:
                        bg = QColor(self._plate_badge_color(sample_name))
                        fg = QColor("#f7fbff")
                    elif has_fcs:
                        bg = QColor("#ffffff")
                        fg = QColor("#111111")
                    else:
                        bg = QColor("#f3f3f3")
                        fg = QColor("#7a7a7a")
                    item.setBackground(bg)
                    item.setForeground(fg)
                    tooltip = [
                        f"Well: {well}",
                        f"Sample: {sample_name or ''}",
                        f"Sample type: {meta.get('sample_type', '')}",
                        f"Dose curve: {meta.get('dose_curve', '')}",
                        f"Dose: {meta.get('dose', '')}",
                        f"Replicate: {meta.get('replicate', '')}",
                        f"Direction: {meta.get('dose_direction', '')}",
                        f"Excluded: {excluded}",
                        f"FCS file: {'yes' if has_fcs else 'no'}",
                    ]
                    item.setToolTip("\n".join(tooltip))
            wells = _selected_wells_from_table()
            if wells:
                first_meta = self._metadata_for_well(wells[0])
                sample_edit.setText(str(first_meta.get("sample_name", "")).strip())
                sample_type_combo.setCurrentText(str(first_meta.get("sample_type", "sample")).strip() or "sample")
            summary_label.setText(f"Selected wells ({len(wells)}): {', '.join(wells) if wells else 'none'}")
            info_label.setText(
                "Click or drag across wells to select them. "
                "Use Sample Manager to highlight an assigned sample across the plate."
            )
            self._refresh_well_list(selected_labels=self._selected_labels())
            self._refresh_plate_panel()
            _refresh_sample_panel()
            _refresh_curve_panel()

        def _apply_sample():
            wells = _selected_wells_from_table()
            if not wells:
                info_label.setText("No wells selected.")
                return
            sample_name = sample_edit.text().strip()
            sample_type = sample_type_combo.currentText().strip()
            for well in wells:
                meta = dict(self._metadata_for_well(well))
                if sample_name:
                    meta["sample_name"] = sample_name
                    meta["sample_type"] = sample_type
                else:
                    for field in ("sample_name", "sample_type", "dose_curve", "dose", "replicate", "dose_direction"):
                        meta.pop(field, None)
                self.plate_metadata[well] = meta
            _set_main_well_selection(wells)
            self.sample_name_edit.setText(sample_name)
            self._schedule_heatmap_update()
            info_label.setText(f"Applied sample metadata to {len(wells)} wells.")
            _refresh_dialog()

        def _apply_dose_curve():
            wells = _selected_wells_from_table()
            if not wells:
                info_label.setText("No wells selected.")
                return
            sample_name = sample_edit.text().strip()
            sample_type = sample_type_combo.currentText().strip()
            if not sample_name:
                info_label.setText("Enter a sample name first.")
                return
            direction = direction_combo.currentText().strip().lower()
            n_points = max(int(points_spin.value()), 1)
            top_dose = float(top_dose_spin.value())
            dilution = float(dilution_spin.value())
            grouped = {}
            for well in wells:
                row = well[0]
                col = int(well[1:])
                key = row if direction == "horizontal" else col
                grouped.setdefault(key, []).append(well)
            sorted_groups = []
            for key, group_wells in grouped.items():
                if direction == "horizontal":
                    ordered = sorted(group_wells, key=lambda well: int(well[1:]))
                else:
                    ordered = sorted(group_wells, key=lambda well: well[0])
                sorted_groups.append((key, ordered))
            sorted_groups.sort(key=lambda item: item[0])
            for replicate_idx, (_key, group_wells) in enumerate(sorted_groups, start=1):
                for point_idx, well in enumerate(group_wells[:n_points]):
                    dose_value = top_dose / (dilution ** point_idx)
                    meta = dict(self._metadata_for_well(well))
                    meta["sample_name"] = sample_name
                    meta["sample_type"] = sample_type
                    meta["dose_curve"] = sample_name
                    meta["dose"] = dose_value
                    meta["replicate"] = replicate_idx
                    meta["dose_direction"] = direction
                    self.plate_metadata[well] = meta
            _set_main_well_selection(wells)
            self.sample_name_edit.setText(sample_name)
            self._schedule_heatmap_update()
            info_label.setText(f"Assigned dose curve '{sample_name}' across {len(wells)} wells.")
            _refresh_dialog()

        def _apply_assignment():
            if assignment_mode_combo.currentText() == "dose_curve":
                _apply_dose_curve()
            else:
                _apply_sample()

        def _toggle_exclude():
            wells = _selected_wells_from_table()
            if not wells:
                info_label.setText("No wells selected.")
                return
            excluded_values = [bool(self._metadata_for_well(well).get("excluded", False)) for well in wells]
            new_value = not all(excluded_values)
            for well in wells:
                meta = dict(self._metadata_for_well(well))
                meta["excluded"] = new_value
                self.plate_metadata[well] = meta
            _set_main_well_selection(wells)
            self._schedule_heatmap_update()
            info_label.setText(f"{'Excluded' if new_value else 'Included'} {len(wells)} wells.")
            _refresh_dialog()

        def _clear_selected():
            wells = _selected_wells_from_table()
            if not wells:
                info_label.setText("No wells selected.")
                return
            for well in wells:
                self.plate_metadata.pop(well, None)
            _set_main_well_selection(wells)
            self._schedule_heatmap_update()
            info_label.setText(f"Cleared metadata for {len(wells)} wells.")
            _refresh_dialog()

        def _on_sample_selected():
            sample_name = _selected_sample_name()
            if not sample_name:
                _refresh_dialog()
                return
            wells = sorted(
                [well for well, meta in self.plate_metadata.items() if str(meta.get("sample_name", "")).strip() == sample_name],
                key=lambda well: (well[0], int(well[1:])),
            )
            table.blockSignals(True)
            table.clearSelection()
            for well in wells:
                row_idx = ord(well[0]) - 65
                col_idx = int(well[1:]) - 1
                item = table.item(row_idx, col_idx)
                if item is not None:
                    item.setSelected(True)
            table.blockSignals(False)
            _set_main_well_selection(wells)
            _refresh_dialog()

        def _extend_selected_sample():
            sample_name = _selected_sample_name()
            wells = _selected_wells_from_table()
            if not sample_name:
                info_label.setText("Select a sample first.")
                return
            if not wells:
                info_label.setText("Select wells to extend the sample into.")
                return
            source_wells = sorted(
                [well for well, meta in self.plate_metadata.items() if str(meta.get("sample_name", "")).strip() == sample_name],
                key=lambda well: (well[0], int(well[1:])),
            )
            source_meta = self._metadata_for_well(source_wells[0]) if source_wells else {}
            for well in wells:
                meta = dict(self._metadata_for_well(well))
                meta["sample_name"] = sample_name
                meta["sample_type"] = str(source_meta.get("sample_type", sample_type_combo.currentText().strip() or "sample")).strip()
                self.plate_metadata[well] = meta
            _set_main_well_selection(wells)
            self._schedule_heatmap_update()
            info_label.setText(f"Extended sample '{sample_name}' into {len(wells)} wells.")
            _refresh_dialog()

        def _delete_selected_sample():
            sample_name = _selected_sample_name()
            if not sample_name:
                info_label.setText("Select a sample first.")
                return
            wells = [
                well for well, meta in self.plate_metadata.items()
                if str(meta.get("sample_name", "")).strip() == sample_name
            ]
            if not wells:
                info_label.setText(f"No wells found for sample '{sample_name}'.")
                return
            for well in wells:
                meta = dict(self._metadata_for_well(well))
                for field in ("sample_name", "sample_type", "dose_curve", "dose", "replicate", "dose_direction"):
                    meta.pop(field, None)
                self.plate_metadata[well] = meta
            self._schedule_heatmap_update()
            info_label.setText(f"Deleted sample '{sample_name}' from {len(wells)} wells.")
            _refresh_dialog()

        def _update_assignment_mode():
            is_dose_curve = assignment_mode_combo.currentText() == "dose_curve"
            dose_box.setVisible(is_dose_curve)
            apply_button.setText("Apply Sample And Dose Curve" if is_dose_curve else "Apply Sample")

        table.itemSelectionChanged.connect(lambda: (_set_main_well_selection(_selected_wells_from_table()), _refresh_dialog()))
        apply_button.clicked.connect(_apply_assignment)
        toggle_button.clicked.connect(_toggle_exclude)
        clear_button.clicked.connect(_clear_selected)
        sample_list.itemSelectionChanged.connect(_on_sample_selected)
        extend_button.clicked.connect(_extend_selected_sample)
        delete_sample_button.clicked.connect(_delete_selected_sample)
        assignment_mode_combo.currentIndexChanged.connect(_update_assignment_mode)
        dialog.finished.connect(lambda _result: (self._refresh_plate_panel(), self._refresh_well_list(selected_labels=self._selected_labels())))
        _update_assignment_mode()
        _refresh_dialog()
        dialog.exec()

    def _refresh_plate_panel(self):
        selected_wells = set(self._selected_wells())
        available_wells = {label.split(" | ")[0] for label in self.file_map}
        for well, button in self.plate_buttons.items():
            meta = self._metadata_for_well(well)
            sample_name = str(meta.get("sample_name", "")).strip()
            excluded = bool(meta.get("excluded", False))
            has_fcs = well in available_wells
            badge = self._plate_badge_text(sample_name)
            text = badge if badge else well
            if excluded:
                text = f"{text} X"
            button.setText(text)
            tooltip = [well]
            if sample_name:
                tooltip.append(f"Sample: {sample_name}")
            tooltip.append(f"FCS file: {'yes' if has_fcs else 'no'}")
            if excluded:
                tooltip.append("Excluded from downstream analysis")
            button.setToolTip("\n".join(tooltip))
            if excluded:
                bg = "#5a6679"
                fg = "#fff5f5"
                border = "#ffb1b1"
            elif sample_name:
                bg = self._plate_badge_color(sample_name)
                fg = "#f7fbff"
                border = "#eff4fb"
            elif has_fcs:
                bg = "#242c39"
                fg = "#dbe4f1"
                border = "#d5dde9"
            else:
                bg = "#1a1f2b"
                fg = "#617087"
                border = "#515d73"
            selected_style = "border-width: 3px;" if well in selected_wells else "border-width: 1px;"
            button.setStyleSheet(f"background-color: {bg}; color: {fg}; border: 1px solid {border}; {selected_style}")
        assigned = sum(1 for meta in self.plate_metadata.values() if meta.get("sample_name"))
        excluded = sum(1 for meta in self.plate_metadata.values() if meta.get("excluded"))
        self.plate_summary_label.setText(f"FCS wells: {len(available_wells)}    assigned: {assigned}    excluded: {excluded}")

    def _assign_sample_name_to_selected_wells(self):
        wells = self._selected_wells()
        if not wells:
            self.status_label.setText("Select one or more wells first.")
            return
        sample_name = self.sample_name_edit.text().strip()
        for well in wells:
            meta = dict(self._metadata_for_well(well))
            if sample_name:
                meta["sample_name"] = sample_name
            else:
                meta.pop("sample_name", None)
            self.plate_metadata[well] = meta
        self._refresh_well_list(selected_labels=self._selected_labels())
        self._refresh_plate_panel()
        self.status_label.setText(f"Updated sample name for {len(wells)} well(s).")

    def _toggle_exclude_selected_wells(self):
        wells = self._selected_wells()
        if not wells:
            self.status_label.setText("Select one or more wells first.")
            return
        excluded_values = [bool(self._metadata_for_well(well).get("excluded", False)) for well in wells]
        new_value = not all(excluded_values)
        for well in wells:
            meta = dict(self._metadata_for_well(well))
            meta["excluded"] = new_value
            self.plate_metadata[well] = meta
        self._refresh_well_list(selected_labels=self._selected_labels())
        self._refresh_plate_panel()
        self._schedule_heatmap_update()
        self.status_label.setText(f"{'Excluded' if new_value else 'Included'} {len(wells)} well(s).")

    def _clear_selected_metadata(self):
        wells = self._selected_wells()
        if not wells:
            self.status_label.setText("Select one or more wells first.")
            return
        for well in wells:
            self.plate_metadata.pop(well, None)
        self.sample_name_edit.setText("")
        self._refresh_well_list(selected_labels=self._selected_labels())
        self._refresh_plate_panel()
        self._schedule_heatmap_update()
        self.status_label.setText(f"Cleared metadata for {len(wells)} well(s).")

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Escape:
            self.clear_pending()
            self.status_label.setText("Drawing mode cancelled.")
            event.accept()
            return
        if event.key() in {Qt.Key_Return, Qt.Key_Enter} and self.polygon_vertices and len(self.polygon_vertices) >= 3:
            self.pending_gate = PendingGate("polygon", {"vertices": list(self.polygon_vertices)})
            self.polygon_vertices = []
            self.polygon_cursor_point = None
            self._disconnect_drawing()
            self.redraw()
            self.status_label.setText("Polygon captured. Click Save Gate to keep it.")
            event.accept()
            return
        super().keyPressEvent(event)


def launch_desktop_app_qt(base_dir=None, instrument="Cytoflex", max_points=15000):
    app = QApplication.instance() or QApplication(sys.argv)
    window = FlowDesktopQtWindow(base_dir=base_dir, instrument=instrument, max_points=max_points)
    window.show()
    return app.exec()
