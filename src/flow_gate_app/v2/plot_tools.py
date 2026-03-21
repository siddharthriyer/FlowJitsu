from __future__ import annotations

import numpy as np
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSlider,
    QVBoxLayout,
)


def open_graph_options_dialog(window):
    dialog = QDialog(window)
    dialog.setWindowTitle("Graph Options")
    dialog.resize(760, 320)
    layout = QVBoxLayout(dialog)
    grid = QGridLayout()
    layout.addLayout(grid)

    histogram_mode = window._histogram_mode()
    if histogram_mode:
        plotted = window._downsample(window.current_transformed)
        auto_limits = window._median_histogram_axis_limits(transformed=plotted)
        current = window._effective_histogram_axis_limits(transformed=plotted) or auto_limits
        extent = window._global_histogram_axis_extent()
    else:
        auto_limits = window._median_scatter_axis_limits()
        current = window._effective_scatter_axis_limits() or auto_limits
        extent = window._global_scatter_axis_extent()
    if current is None:
        current = (*window.ax.get_xlim(), *window.ax.get_ylim())
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
            hist_key = window._hist_axis_override_key()
            if hist_key is not None:
                window.hist_axis_overrides.pop(hist_key, None)
        else:
            x_key = window._scatter_x_axis_override_key()
            y_key = window._scatter_y_axis_override_key()
            if x_key is not None:
                window.scatter_x_axis_overrides.pop(x_key, None)
            if y_key is not None:
                window.scatter_y_axis_overrides.pop(y_key, None)
        window.plot_population()

    def _apply():
        try:
            xmin = float(xmin_edit.text().strip())
            xmax = float(xmax_edit.text().strip())
            ymin = float(ymin_edit.text().strip())
            ymax = float(ymax_edit.text().strip())
        except ValueError:
            window.status_label.setText("Graph options require numeric axis limits.")
            return
        if xmin >= xmax or ymin >= ymax:
            window.status_label.setText("Axis minimums must be smaller than maximums.")
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
            hist_key = window._hist_axis_override_key()
            if hist_key is not None:
                window.hist_axis_overrides[hist_key] = (xmin, xmax, ymin, ymax)
        else:
            x_key = window._scatter_x_axis_override_key()
            y_key = window._scatter_y_axis_override_key()
            if x_key is not None:
                window.scatter_x_axis_overrides[x_key] = (xmin, xmax)
            if y_key is not None:
                window.scatter_y_axis_overrides[y_key] = (ymin, ymax)
        window.plot_population()

    use_auto_button.clicked.connect(_reset_auto)
    apply_button.clicked.connect(_apply)
    close_button.clicked.connect(dialog.close)
    dialog.exec()


def update_heatmap(window):
    window._heatmap_timer.stop()
    window._heatmap_update_pending = False
    window.heatmap_figure.clear()
    window.heatmap_ax = window.heatmap_figure.add_subplot(111)
    if not window.file_map:
        window.heatmap_ax.set_title("No data loaded")
        window.heatmap_canvas.draw_idle()
        window.heatmap_status_label.setText("Heatmap ready")
        return
    window.heatmap_status_label.setText("Updating heatmap...")
    QApplication.processEvents()
    try:
        plate = np.full((8, 12), np.nan)
        mode = window.heatmap_mode_combo.currentText()
        image = None
        if mode == "percent":
            gate_name = window.heatmap_metric_combo.currentText().strip()
            gate = next((item for item in window.gates if item["name"] == gate_name), None)
            if gate is None:
                window.heatmap_ax.set_title("Select a saved gate for percent heatmap")
            else:
                for label in window.file_map:
                    well = label.split(" | ")[0]
                    if window._metadata_for_well(well).get("excluded", False):
                        continue
                    frac, _count, _total = window._gate_fraction_for_label(gate, label)
                    plate[ord(well[0]) - 65, int(well[1:]) - 1] = 100.0 * frac
                image = window.heatmap_ax.imshow(plate, cmap="viridis", vmin=0, vmax=100)
                window.heatmap_figure.colorbar(image, ax=window.heatmap_ax, fraction=0.046, pad=0.04, label="% positive")
                window.heatmap_ax.set_title(f"{gate_name} well heatmap")
        else:
            channel = window.heatmap_channel_combo.currentText().strip()
            if not channel:
                window.heatmap_ax.set_title("Select a channel for MFI heatmap")
            else:
                for label in window.file_map:
                    well = label.split(" | ")[0]
                    if window._metadata_for_well(well).get("excluded", False):
                        continue
                    raw_df = window._sample_raw_dataframe(label)
                    value = float(np.mean(raw_df[channel])) if (not raw_df.empty and channel in raw_df.columns) else np.nan
                    plate[ord(well[0]) - 65, int(well[1:]) - 1] = value
                image = window.heatmap_ax.imshow(plate, cmap="magma")
                window.heatmap_figure.colorbar(image, ax=window.heatmap_ax, fraction=0.046, pad=0.04, label=f"MFI {channel}")
                window.heatmap_ax.set_title(f"MFI {channel}")
        window._annotate_heatmap_cells(plate, image=image)
        window.heatmap_ax.set_xticks(np.arange(12))
        window.heatmap_ax.set_yticks(np.arange(8))
        window.heatmap_ax.set_xticklabels([str(i) for i in range(1, 13)])
        window.heatmap_ax.set_yticklabels(list("ABCDEFGH"))
        window.heatmap_ax.set_xlabel("Column")
        window.heatmap_ax.set_ylabel("Row")
        window.heatmap_figure.tight_layout()
        window.heatmap_canvas.draw_idle()
        window.heatmap_status_label.setText("Heatmap ready")
    except Exception:
        window.heatmap_ax.set_title("Heatmap failed")
        window.heatmap_canvas.draw_idle()
        window.heatmap_status_label.setText("Heatmap update failed")
