from __future__ import annotations

import numpy as np
import pandas as pd
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg, NavigationToolbar2QT
from matplotlib.figure import Figure
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QDialog,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QPushButton,
    QVBoxLayout,
)


def plt_col(index):
    palette = ["#4f7cff", "#2f8c74", "#a56ad8", "#c77d2b", "#cc5f7a", "#3d97b8", "#7a9c34", "#b85c2e"]
    return palette[index % len(palette)]


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
