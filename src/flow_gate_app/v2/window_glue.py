from __future__ import annotations

import json
import os

import numpy as np
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFileDialog

from ..helpers import PendingGate


def on_well_selection_changed(window):
    window._refresh_channel_controls()
    wells = window._selected_wells()
    if len(wells) == 1:
        window.sample_name_edit.setText(str(window._metadata_for_well(wells[0]).get("sample_name", "")))
    elif not wells:
        window.sample_name_edit.setText("")
    window._refresh_plate_panel()
    window._schedule_plot_update()


def on_channel_changed(window):
    if window.plot_mode_combo.currentText() == "count histogram":
        window.y_combo.blockSignals(True)
        window.y_combo.setCurrentText("Count")
        window.y_combo.blockSignals(False)
    window._refresh_heatmap_controls()
    window._schedule_plot_update()


def on_gate_type_changed(window):
    window.quad_preview_point = None
    window.vertical_preview_x = None
    window.horizontal_preview_y = None
    window.rectangle_start_point = None
    window.rectangle_current_point = None
    window.zoom_start_point = None
    window.zoom_current_point = None
    window.polygon_cursor_point = None
    window._disconnect_drawing()
    window.redraw()


def on_population_changed(window):
    window._schedule_plot_update()


def trigger_auto_plot(window, *_args):
    window._schedule_plot_update()


def on_auto_plot_mode_changed(window):
    window.auto_plot_enabled = window.auto_plot_auto_radio.isChecked()


def refresh_heatmap_controls(window):
    gate_names = [gate["name"] for gate in window.gates]
    window.heatmap_metric_combo.blockSignals(True)
    window.heatmap_metric_combo.clear()
    window.heatmap_metric_combo.addItems(gate_names)
    window.heatmap_metric_combo.blockSignals(False)
    channels = window._fluorescence_channels() or list(window.channel_names)
    window.heatmap_channel_combo.blockSignals(True)
    window.heatmap_channel_combo.clear()
    window.heatmap_channel_combo.addItems(channels)
    window.heatmap_channel_combo.blockSignals(False)


def schedule_heatmap_update(window, *_args, delay_ms=120):
    window._heatmap_update_pending = True
    window.heatmap_status_label.setText("Updating heatmap...")
    window._heatmap_timer.start(max(int(delay_ms), 0))


def schedule_redraw(window, delay_ms=12):
    window._redraw_timer.start(max(int(delay_ms), 0))


def schedule_plot_update(window, delay_ms=0):
    if window._suspend_auto_plot or not window.file_map or not window.auto_plot_enabled:
        return
    window._plot_timer.start(max(int(delay_ms), 0))


def session_payload(window):
    return {
        "folder": window.folder_edit.text().strip(),
        "instrument": window.instrument_combo.currentText(),
        "gates": window.gates,
        "plate_metadata": window.plate_metadata,
        "compensation": window._compensation_payload(),
        "plot": {
            "population": window.population_combo.currentText(),
            "x_channel": window.x_combo.currentText(),
            "y_channel": window.y_combo.currentText(),
            "plot_mode": window.plot_mode_combo.currentText(),
            "x_transform": window.x_transform_combo.currentText(),
            "x_cofactor": int(window.x_cofactor_spin.value()),
            "y_transform": window.y_transform_combo.currentText(),
            "y_cofactor": int(window.y_cofactor_spin.value()),
            "max_points": int(window.max_points_spin.value()),
        },
    }


def gate_template_payload(window):
    return {
        "template_type": "flow_gate_template",
        "version": 1,
        "instrument": window.instrument_combo.currentText(),
        "channels": sorted(
            {
                channel
                for gate in window.gates
                for channel in [gate.get("x_channel"), gate.get("y_channel")]
                if channel
            }
        ),
        "gates": window.gates,
    }


def save_gate_template(window):
    if not window.gates:
        window.status_label.setText("No gates to save as a template.")
        return
    filename, _ = QFileDialog.getSaveFileName(
        window,
        "Save Gate Template",
        os.path.join(window._session_dir(), "gate_template.json"),
        "JSON files (*.json)",
    )
    if not filename:
        return
    try:
        with open(filename, "w") as fh:
            json.dump(window._gate_template_payload(), fh, indent=2)
        window.status_label.setText(f"Saved gate template to {filename}")
    except Exception as exc:
        window.status_label.setText(f"Failed to save gate template: {type(exc).__name__}: {exc}")


def load_gate_template(window):
    filename, _ = QFileDialog.getOpenFileName(
        window,
        "Load Gate Template",
        window._session_dir(),
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
        existing_names = {gate["name"] for gate in window.gates}
        duplicates = sorted(existing_names & {gate["name"] for gate in template_gates})
        if duplicates:
            raise ValueError(f"Template gate names already exist: {', '.join(duplicates)}")
        window.gates.extend(template_gates)
        window._refresh_saved_gates(selected_name=template_gates[0]["name"])
        window._refresh_population_combo()
        window._refresh_heatmap_controls()
        window._invalidate_cached_outputs()
        window.redraw()
        window._update_gate_summary()
        window._schedule_heatmap_update()
        window.status_label.setText(f"Loaded gate template from {filename}")
    except Exception as exc:
        window.status_label.setText(f"Failed to load gate template: {type(exc).__name__}: {exc}")


def annotate_heatmap_cells(window, plate, image=None):
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
            window.heatmap_ax.text(
                col_idx,
                row_idx,
                f"{value:.1f}",
                ha="center",
                va="center",
                color=color,
                fontsize=8,
                fontweight="bold",
            )


def key_press_event(window, event):
    if event.key() == Qt.Key_Escape:
        window.clear_pending()
        window.status_label.setText("Drawing mode cancelled.")
        event.accept()
        return True
    if event.key() in {Qt.Key_Return, Qt.Key_Enter} and window.polygon_vertices and len(window.polygon_vertices) >= 3:
        window.pending_gate = PendingGate("polygon", {"vertices": list(window.polygon_vertices)})
        window.polygon_vertices = []
        window.polygon_cursor_point = None
        window._disconnect_drawing()
        window.redraw()
        window.status_label.setText("Polygon captured. Click Save Gate to keep it.")
        event.accept()
        return True
    return False
