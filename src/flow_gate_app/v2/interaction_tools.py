from __future__ import annotations

import numpy as np
import pandas as pd
from matplotlib.lines import Line2D
from matplotlib.path import Path
from PySide6.QtWidgets import QApplication

from ..helpers import (
    PendingGate,
    apply_transform as _apply_transform,
    gate_mask as _gate_mask,
    is_count_axis as _is_count_axis,
    render_gate as _render_gate,
    transform_array as _transform_array,
)


def _interactive_active(window):
    return (
        window.drag_state is not None
        or window.rectangle_start_point is not None
        or window.zoom_start_point is not None
        or window.vertical_preview_x is not None
        or window.horizontal_preview_y is not None
        or window.quad_preview_point is not None
        or window.polygon_cursor_point is not None
    )


def _gate_linestyle(index):
    styles = ["-", "--", ":", "-.", (0, (5, 1)), (0, (3, 1, 1, 1))]
    return styles[index % len(styles)]


def _interactive_downsample(window, transformed, limit=4000):
    plotted = window._downsample(transformed)
    if plotted.empty or len(plotted) <= limit:
        return plotted
    if "__well__" not in plotted.columns:
        return plotted.sample(n=limit, random_state=0)
    pieces = []
    groups = list(plotted.groupby("__well__", sort=False))
    per_group = max(1, limit // max(len(groups), 1))
    for _, group in groups:
        pieces.append(group.sample(n=min(per_group, len(group)), random_state=0))
    return pd.concat(pieces, ignore_index=True)


def _clear_preview_artists(window):
    for artist in getattr(window, "_preview_artists", []):
        try:
            artist.remove()
        except Exception:
            pass
    window._preview_artists = []


def _draw_preview_overlay(window):
    _clear_preview_artists(window)
    ax = window.ax
    artists = []

    if window.vertical_preview_x is not None:
        (line,) = ax.plot(
            [window.vertical_preview_x, window.vertical_preview_x],
            list(ax.get_ylim()),
            color="#2f8c74",
            linewidth=1.6,
            linestyle="--",
            zorder=8,
        )
        artists.append(line)

    if window.horizontal_preview_y is not None:
        (line,) = ax.plot(
            list(ax.get_xlim()),
            [window.horizontal_preview_y, window.horizontal_preview_y],
            color="#2f8c74",
            linewidth=1.6,
            linestyle="--",
            zorder=8,
        )
        artists.append(line)

    if window.quad_preview_point is not None:
        qx, qy = window.quad_preview_point
        (vline,) = ax.plot(
            [qx, qx],
            list(ax.get_ylim()),
            color="#2f8c74",
            linewidth=1.6,
            linestyle="--",
            zorder=8,
        )
        (hline,) = ax.plot(
            list(ax.get_xlim()),
            [qy, qy],
            color="#2f8c74",
            linewidth=1.6,
            linestyle="--",
            zorder=8,
        )
        (marker,) = ax.plot(
            [qx],
            [qy],
            linestyle="None",
            marker="o",
            markersize=6,
            color="#2f8c74",
            zorder=9,
        )
        artists.extend([vline, hline, marker])

    if window.rectangle_start_point is not None and window.rectangle_current_point is not None:
        vertices = window._rectangle_vertices(
            window.rectangle_start_point[0],
            window.rectangle_start_point[1],
            window.rectangle_current_point[0],
            window.rectangle_current_point[1],
        )
        xs = [point[0] for point in vertices] + [vertices[0][0]]
        ys = [point[1] for point in vertices] + [vertices[0][1]]
        (line,) = ax.plot(xs, ys, color="#2f8c74", linewidth=1.8, linestyle="--", zorder=8)
        (markers,) = ax.plot(
            [window.rectangle_start_point[0], window.rectangle_current_point[0]],
            [window.rectangle_start_point[1], window.rectangle_current_point[1]],
            linestyle="None",
            marker="o",
            markersize=5,
            color="#2f8c74",
            zorder=9,
        )
        artists.extend([line, markers])

    if window.zoom_start_point is not None and window.zoom_current_point is not None:
        vertices = window._rectangle_vertices(
            window.zoom_start_point[0],
            window.zoom_start_point[1],
            window.zoom_current_point[0],
            window.zoom_current_point[1],
        )
        xs = [point[0] for point in vertices] + [vertices[0][0]]
        ys = [point[1] for point in vertices] + [vertices[0][1]]
        (line,) = ax.plot(xs, ys, color="#c77d2b", linewidth=1.8, linestyle="--", zorder=8)
        (markers,) = ax.plot(
            [window.zoom_start_point[0], window.zoom_current_point[0]],
            [window.zoom_start_point[1], window.zoom_current_point[1]],
            linestyle="None",
            marker="o",
            markersize=5,
            color="#c77d2b",
            zorder=9,
        )
        artists.extend([line, markers])

    if window.polygon_vertices:
        vertices = list(window.polygon_vertices)
        xs = [point[0] for point in vertices]
        ys = [point[1] for point in vertices]
        if window.polygon_cursor_point is not None:
            xs = xs + [window.polygon_cursor_point[0]]
            ys = ys + [window.polygon_cursor_point[1]]
        (line,) = ax.plot(xs, ys, color="#2f8c74", linewidth=1.4, linestyle="--", zorder=8)
        (markers,) = ax.plot(
            [point[0] for point in vertices],
            [point[1] for point in vertices],
            linestyle="None",
            marker="o",
            markersize=8,
            markerfacecolor="#2f8c74",
            markeredgecolor="#f6fffb",
            markeredgewidth=1.2,
            zorder=9,
        )
        artists.extend([line, markers])
        if window.polygon_cursor_point is not None:
            (cursor,) = ax.plot(
                [window.polygon_cursor_point[0]],
                [window.polygon_cursor_point[1]],
                linestyle="None",
                marker="o",
                markersize=7,
                color="#2f8c74",
                alpha=0.7,
                zorder=9,
            )
            artists.append(cursor)

    window._preview_artists = artists
    if artists:
        window.canvas.draw_idle()


def redraw(window):
    _clear_preview_artists(window)
    window.ax.clear()
    raw_df = window.current_data
    transformed = window.current_transformed
    interactive = _interactive_active(window)
    plotted = _interactive_downsample(window, transformed) if interactive else window._downsample(transformed)

    if plotted.empty:
        window.ax.set_title("No population plotted")
        window.ax.set_xlabel("X")
        window.ax.set_ylabel("Y")
        window.canvas.draw_idle()
        return

    labels = window._selected_labels()
    x_channel = window.x_combo.currentText()
    y_channel = window.y_combo.currentText()
    plot_mode = window.plot_mode_combo.currentText()
    histogram_mode = plot_mode == "count histogram" or _is_count_axis(y_channel)
    hex_mode = plot_mode == "hex density" and not histogram_mode
    hist_limits = None
    data_legend = None
    if histogram_mode:
        hist_limits = window._effective_histogram_axis_limits(plotted)
        hist_range = None if hist_limits is None else (hist_limits[0], hist_limits[1])
        if len(labels) <= 1:
            window.ax.hist(
                plotted[x_channel],
                bins=window._hist_bins(),
                range=hist_range,
                histtype="step",
                linewidth=1.8,
                color="#1f77b4",
            )
        else:
            for idx, (well, group) in enumerate(plotted.groupby("__well__", sort=False)):
                window.ax.hist(
                    group[x_channel],
                    bins=window._hist_bins(),
                    range=hist_range,
                    histtype="step",
                    linewidth=1.6,
                    label=well,
                )
            if len(labels) <= 12 and not interactive:
                data_legend = window.ax.legend(fontsize=8, loc="upper left")
        window.ax.set_ylabel("Count")
    else:
        if len(labels) <= 1:
            if hex_mode:
                window.ax.hexbin(
                    plotted[x_channel],
                    plotted[y_channel],
                    gridsize=window.hex_size_spin.value(),
                    bins="log",
                    mincnt=1,
                    cmap="viridis",
                    linewidths=0.0,
                )
            else:
                window.ax.scatter(plotted[x_channel], plotted[y_channel], s=3, alpha=0.25, color="#1f77b4", rasterized=True)
        else:
            if hex_mode:
                window.ax.hexbin(
                    plotted[x_channel],
                    plotted[y_channel],
                    gridsize=window.hex_size_spin.value(),
                    bins="log",
                    mincnt=1,
                    cmap="viridis",
                    linewidths=0.0,
                )
            else:
                for _, (well, group) in enumerate(plotted.groupby("__well__", sort=False)):
                    window.ax.scatter(group[x_channel], group[y_channel], s=3, alpha=0.25, label=well, rasterized=True)
                if len(labels) <= 12 and not interactive:
                    data_legend = window.ax.legend(markerscale=3, fontsize=8, loc="upper left")
        window.ax.set_ylabel(f"{y_channel} ({window._plot_y_transform()})")

    visible_gates = [gate for gate in window.gates if window._visible_gate(gate)]
    gate_handles = []
    gate_labels = []
    for idx, gate in enumerate(visible_gates):
        artists = _render_gate(
            window.ax,
            gate,
            selected=(gate["name"] == window.selected_gate_name),
            linestyle=_gate_linestyle(idx),
            label=gate["name"],
        )
        if artists:
            gate_handles.append(
                Line2D(
                    [0],
                    [0],
                    color=gate.get("color", "crimson"),
                    linewidth=2.5 if gate["name"] == window.selected_gate_name else 1.8,
                    linestyle=_gate_linestyle(idx),
                )
            )
            gate_labels.append(gate["name"])

    if len(gate_handles) > 1 and not interactive:
        gate_legend = window.ax.legend(gate_handles, gate_labels, title="Gates", fontsize=8, title_fontsize=8, loc="upper right")
        if data_legend is not None:
            window.ax.add_artist(data_legend)
            window.ax.add_artist(gate_legend)

    if window.pending_gate is not None:
        spec = window._pending_to_gate_spec(preview=True)
        if spec is not None:
            if window.pending_gate.gate_type == "polygon":
                vertices = list(window.pending_gate.payload.get("vertices", []))
                if vertices:
                    window.ax.scatter(
                        [point[0] for point in vertices],
                        [point[1] for point in vertices],
                        s=72,
                        color="#2f8c74",
                        edgecolors="#f6fffb",
                        linewidths=1.2,
                        zorder=7,
                    )
                    if len(vertices) >= 2:
                        xs = [point[0] for point in vertices]
                        ys = [point[1] for point in vertices]
                        if len(vertices) >= 3 and not window.polygon_vertices:
                            xs.append(vertices[0][0])
                            ys.append(vertices[0][1])
                        window.ax.plot(
                            xs,
                            ys,
                            linestyle="-",
                            linewidth=1.2,
                            color="#2f8c74",
                        )
                if vertices and window.polygon_cursor_point is not None:
                    xs = [point[0] for point in vertices] + [window.polygon_cursor_point[0]]
                    ys = [point[1] for point in vertices] + [window.polygon_cursor_point[1]]
                    window.ax.plot(xs, ys, linestyle="--", linewidth=1.2, color="#2f8c74")
                    window.ax.scatter(
                        [window.polygon_cursor_point[0]],
                        [window.polygon_cursor_point[1]],
                        s=60,
                        color="#2f8c74",
                        alpha=0.7,
                        zorder=7,
                    )
            else:
                _render_gate(window.ax, spec, selected=True)
    if window.vertical_preview_x is not None:
        window.ax.axvline(window.vertical_preview_x, color="#2f8c74", linewidth=1.6, linestyle="--")
    if window.horizontal_preview_y is not None:
        window.ax.axhline(window.horizontal_preview_y, color="#2f8c74", linewidth=1.6, linestyle="--")
    if window.rectangle_start_point is not None and window.rectangle_current_point is not None:
        preview_vertices = window._rectangle_vertices(
            window.rectangle_start_point[0],
            window.rectangle_start_point[1],
            window.rectangle_current_point[0],
            window.rectangle_current_point[1],
        )
        preview = {
            "gate_type": "rectangle",
            "vertices": preview_vertices,
            "x_channel": x_channel,
            "y_channel": y_channel,
            "color": "#2f8c74",
        }
        _render_gate(window.ax, preview, selected=True)
        window.ax.scatter(
            [window.rectangle_start_point[0], window.rectangle_current_point[0]],
            [window.rectangle_start_point[1], window.rectangle_current_point[1]],
            s=28,
            color="#2f8c74",
            zorder=6,
        )
    if window.zoom_start_point is not None and window.zoom_current_point is not None:
        zoom_vertices = window._rectangle_vertices(
            window.zoom_start_point[0],
            window.zoom_start_point[1],
            window.zoom_current_point[0],
            window.zoom_current_point[1],
        )
        zoom_preview = {
            "gate_type": "rectangle",
            "vertices": zoom_vertices,
            "x_channel": x_channel,
            "y_channel": y_channel,
            "color": "#c77d2b",
        }
        _render_gate(window.ax, zoom_preview, selected=True)
        window.ax.scatter(
            [window.zoom_start_point[0], window.zoom_current_point[0]],
            [window.zoom_start_point[1], window.zoom_current_point[1]],
            s=28,
            color="#c77d2b",
            zorder=6,
        )

    window.ax.set_xlabel(f"{x_channel} ({window._plot_x_transform()})")
    title = f"{window._plot_selection_title()} | {window._population_display_label()} | {len(raw_df)} events"
    if len(labels) > 12:
        title += " | legend hidden"
    window.ax.set_title(title)
    window.ax.set_box_aspect(1)
    window.ax.set_anchor("C")
    if histogram_mode:
        if hist_limits is not None:
            xmin, xmax, ymin, ymax = hist_limits
            window.ax.set_xlim(xmin, xmax)
            window.ax.set_ylim(ymin, ymax)
    else:
        scatter_override = window._effective_scatter_axis_limits()
        if scatter_override is not None:
            window.ax.set_xlim(scatter_override[0], scatter_override[1])
            window.ax.set_ylim(scatter_override[2], scatter_override[3])
    if not interactive:
        window.figure.tight_layout()
    window.canvas.draw_idle()


def plot_population(window):
    try:
        window.status_label.setText("Loading events and plotting population in Qt mode...")
        QApplication.processEvents()
        raw_df, transformed = window._display_dataframe()
        window.current_data = raw_df
        window.current_transformed = transformed
        window.redraw()
        if window.selected_gate_name and window._selected_gate() is not None:
            window._enable_saved_gate_interaction()
        window._update_gate_summary()
        window._schedule_heatmap_update()
        window.status_label.setText("Population plotted in Qt mode.")
    except Exception as exc:
        window.status_label.setText(f"Qt plot failed: {type(exc).__name__}: {exc}")


def pending_to_gate_spec(window, preview=False):
    if window.pending_gate is None:
        return None
    name = window.gate_name_edit.text().strip() or f"gate_{len(window.gates) + 1}"
    spec = {
        "name": "__pending__" if preview else name,
        "parent_population": window._selected_population_name(),
        "gate_type": window.pending_gate.gate_type,
        "x_channel": window.x_combo.currentText(),
        "y_channel": None if window.pending_gate.gate_type == "vertical" else window.y_combo.currentText(),
        "x_transform": window._plot_x_transform(),
        "x_cofactor": window._plot_x_cofactor(),
        "y_transform": window._plot_y_transform(),
        "y_cofactor": window._plot_y_cofactor(),
        "color": "#2f8c74",
    }
    spec.update(window.pending_gate.payload)
    return spec


def start_drawing(window):
    if window.current_transformed.empty:
        window.status_label.setText("Plot a population before drawing.")
        return
    if window.plot_mode_combo.currentText() == "count histogram" and window.gate_type_combo.currentText() != "vertical":
        window.status_label.setText("Histogram mode only supports vertical gates.")
        return
    window._disconnect_drawing()
    gate_type = window.gate_type_combo.currentText()
    if gate_type == "rectangle":
        window.canvas_click_cid = window.canvas.mpl_connect("button_press_event", window._on_rectangle_click)
        window.canvas_motion_cid = window.canvas.mpl_connect("motion_notify_event", window._on_rectangle_motion)
        window.mode_label.setText("Mode: drawing rectangle")
    elif gate_type == "quad":
        window.canvas_click_cid = window.canvas.mpl_connect("button_press_event", window._on_quad_click)
        window.canvas_motion_cid = window.canvas.mpl_connect("motion_notify_event", window._on_quad_motion)
        window.mode_label.setText("Mode: drawing quad")
    elif gate_type == "vertical":
        window.canvas_click_cid = window.canvas.mpl_connect("button_press_event", window._on_vertical_click)
        window.canvas_motion_cid = window.canvas.mpl_connect("motion_notify_event", window._on_vertical_motion)
        window.mode_label.setText("Mode: drawing vertical")
    elif gate_type == "horizontal":
        window.canvas_click_cid = window.canvas.mpl_connect("button_press_event", window._on_horizontal_click)
        window.canvas_motion_cid = window.canvas.mpl_connect("motion_notify_event", window._on_horizontal_motion)
        window.mode_label.setText("Mode: drawing horizontal")
    else:
        window.pending_gate = PendingGate("polygon", {"vertices": []})
        window.canvas_click_cid = window.canvas.mpl_connect("button_press_event", window._on_polygon_click)
        window.canvas_motion_cid = window.canvas.mpl_connect("motion_notify_event", window._on_polygon_motion)
        window.mode_label.setText("Mode: drawing polygon")
    window.status_label.setText("Drawing mode active.")


def clear_pending(window):
    window.pending_gate = None
    window.rectangle_start_point = None
    window.rectangle_current_point = None
    window.zoom_start_point = None
    window.zoom_current_point = None
    window.quad_preview_point = None
    window.polygon_vertices = []
    window.polygon_cursor_point = None
    window._disconnect_drawing()
    window.redraw()
    window.status_label.setText("Pending gate cleared.")


def save_gate(window):
    spec = window._pending_to_gate_spec(preview=False)
    if spec is None:
        window.status_label.setText("Draw a gate before saving.")
        return
    specs_to_add = []
    if spec["gate_type"] in {"vertical", "horizontal"}:
        window._gate_group_counter += 1
        gate_group = f"threshold_group_{window._gate_group_counter}"
        axis_key = "x_threshold" if spec["gate_type"] == "vertical" else "y_threshold"
        for region in ("above", "below"):
            threshold_spec = dict(spec)
            threshold_spec["region"] = region
            threshold_spec["name"] = f"{spec['name']}_{region}"
            threshold_spec["gate_group"] = gate_group
            threshold_spec[axis_key] = spec[axis_key]
            specs_to_add.append(threshold_spec)
    else:
        window._gate_group_counter += 1
        spec["gate_group"] = f"gate_group_{window._gate_group_counter}"
        specs_to_add = [spec]
    existing = {gate["name"] for gate in window.gates}
    duplicate = next((gate["name"] for gate in specs_to_add if gate["name"] in existing), None)
    if duplicate is not None:
        window.status_label.setText(f"Gate name already exists: {duplicate}")
        return
    window.gates.extend(specs_to_add)
    window.pending_gate = None
    window.rectangle_start_point = None
    window.rectangle_current_point = None
    window.zoom_start_point = None
    window.zoom_current_point = None
    window.polygon_vertices = []
    window.polygon_cursor_point = None
    window.gate_name_edit.setText(f"gate_{len(window.gates) + 1}")
    window._refresh_saved_gates(selected_name=specs_to_add[0]["name"])
    window._refresh_population_combo()
    window._refresh_heatmap_controls()
    window._disconnect_drawing()
    window._invalidate_cached_outputs()
    window.redraw()
    window._update_gate_summary()
    window._schedule_heatmap_update()
    window.status_label.setText(f"Saved gate '{specs_to_add[0]['name']}'.")


def refresh_saved_gates(window, selected_name=None):
    window.saved_gate_lookup = {}
    window.saved_gate_list.blockSignals(True)
    window.saved_gate_list.clear()
    for gate in window.gates:
        label = window._gate_label(gate)
        window.saved_gate_lookup[label] = gate["name"]
        window.saved_gate_list.addItem(label)
        if gate["name"] == selected_name:
            window.saved_gate_list.item(window.saved_gate_list.count() - 1).setSelected(True)
    window.saved_gate_list.blockSignals(False)
    window.selected_gate_name = selected_name


def gate_label(window, gate):
    lineage_names = [item["name"] for item in window._population_lineage(gate["name"])]
    lineage_label = "All Events > " + " > ".join(lineage_names)
    if gate["gate_type"] == "vertical":
        axes_label = f"vertical @ {gate['x_channel']}"
    elif gate["gate_type"] == "horizontal":
        axes_label = f"horizontal @ {gate['y_channel']}"
    else:
        y_channel = gate["y_channel"] if gate.get("y_channel") else gate["x_channel"]
        axes_label = f"{gate['x_channel']} vs {y_channel}"
    return f"{lineage_label} | {axes_label}"


def on_saved_gate_selected(window):
    selected_items = window.saved_gate_list.selectedItems()
    if not selected_items:
        window.selected_gate_name = None
        window.redraw()
        window._update_gate_summary()
        return
    label = selected_items[0].text()
    window.selected_gate_name = window.saved_gate_lookup.get(label)
    gate = window._selected_gate()
    if gate is not None:
        window._suspend_auto_plot = True
        if gate["x_channel"] in window.channel_names:
            window.x_combo.setCurrentText(gate["x_channel"])
        y_values = [window.y_combo.itemText(i) for i in range(window.y_combo.count())]
        if gate["gate_type"] == "vertical":
            window.plot_mode_combo.setCurrentText("count histogram")
            if "Count" in y_values:
                window.y_combo.setCurrentText("Count")
        elif gate.get("y_channel") in y_values:
            window.plot_mode_combo.setCurrentText("scatter")
            window.y_combo.setCurrentText(gate["y_channel"])
        window.x_transform_combo.setCurrentText(gate.get("x_transform", "arcsinh"))
        window.x_cofactor_spin.setValue(int(gate.get("x_cofactor", 150.0)))
        window.y_transform_combo.setCurrentText(gate.get("y_transform", "arcsinh"))
        window.y_cofactor_spin.setValue(int(gate.get("y_cofactor", 150.0)))
        parent_population = gate.get("parent_population", "__all__")
        selected_population = "All Events" if parent_population == "__all__" else parent_population
        window._refresh_population_combo(selected_name=selected_population)
        window._suspend_auto_plot = False
        window.plot_population()
        window._enable_saved_gate_interaction()
    window.redraw()
    window._update_gate_summary()


def selected_gate(window):
    if not window.selected_gate_name:
        return None
    return next((gate for gate in window.gates if gate["name"] == window.selected_gate_name), None)


def gate_fraction(window, gate):
    labels = window._selected_labels()
    if not labels:
        return 0.0, 0, 0
    total_count = 0
    parent_total = 0
    for label in labels:
        frac, count, total = window._gate_fraction_for_label(gate, label)
        total_count += count
        parent_total += total
    return total_count / max(parent_total, 1), total_count, parent_total


def update_gate_summary(window):
    gate = window._selected_gate()
    if gate is None:
        window.gate_summary.setPlainText("Select a gate to view summary.")
        return
    frac, count, total = window._gate_fraction(gate)
    lines = [
        f"Gate: {gate['name']}",
        f"Type: {gate['gate_type']}",
        f"Channels: {gate['x_channel']} / {gate.get('y_channel') or 'Count'}",
        f"Percent of parent: {count} / {total} ({100 * frac:.1f}%)",
    ]
    window.gate_summary.setPlainText("\n".join(lines))


def gate_fraction_for_label(window, gate, label):
    raw_df = window._sample_raw_dataframe(label)
    if raw_df.empty:
        return 0.0, 0, 0
    parent_name = gate.get("parent_population", "__all__")
    if parent_name != "__all__":
        parent_gate = next((item for item in window.gates if item["name"] == parent_name), None)
        if parent_gate is None:
            return 0.0, 0, 0
        parent_mask = window._population_mask(raw_df, parent_gate)
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


def on_rectangle_click(window, event):
    if event.inaxes != window.ax or event.xdata is None or event.ydata is None or event.button != 1:
        return
    point = (float(event.xdata), float(event.ydata))
    if window.rectangle_start_point is None:
        window.rectangle_start_point = point
        window.rectangle_current_point = point
        window.status_label.setText("Rectangle first corner set. Click the opposite corner.")
        window.redraw()
        return
    window.pending_gate = PendingGate("rectangle", {"vertices": window._rectangle_vertices(
        window.rectangle_start_point[0],
        window.rectangle_start_point[1],
        point[0],
        point[1],
    )})
    window.rectangle_start_point = None
    window.rectangle_current_point = None
    window._disconnect_drawing()
    window.redraw()
    window.status_label.setText("Rectangle captured. Click Save Gate to keep it.")


def on_rectangle_motion(window, event):
    if window.rectangle_start_point is None:
        return
    if event.inaxes != window.ax or event.xdata is None or event.ydata is None:
        return
    window.rectangle_current_point = (float(event.xdata), float(event.ydata))
    _draw_preview_overlay(window)


def on_quad_click(window, event):
    if event.inaxes != window.ax or event.xdata is None or event.ydata is None or event.button != 1:
        return
    window.quad_preview_point = None
    window.pending_gate = PendingGate(
        "quad",
        {
            "x_threshold": float(event.xdata),
            "y_threshold": float(event.ydata),
            "region": "top right",
        },
    )
    window._disconnect_drawing()
    window.redraw()
    window.status_label.setText("Quad gate captured. Click Save Gate to keep it.")


def on_quad_motion(window, event):
    if event.inaxes != window.ax or event.xdata is None or event.ydata is None:
        return
    window.quad_preview_point = (float(event.xdata), float(event.ydata))
    _draw_preview_overlay(window)


def on_vertical_click(window, event):
    if event.inaxes != window.ax or event.xdata is None or event.button != 1:
        return
    window.vertical_preview_x = None
    window.pending_gate = PendingGate("vertical", {"x_threshold": float(event.xdata), "region": "above"})
    window._disconnect_drawing()
    window.redraw()
    window.status_label.setText("Vertical gate captured. Click Save Gate to keep it.")


def on_vertical_motion(window, event):
    if event.inaxes != window.ax or event.xdata is None:
        return
    window.vertical_preview_x = float(event.xdata)
    _draw_preview_overlay(window)


def on_horizontal_click(window, event):
    if event.inaxes != window.ax or event.ydata is None or event.button != 1:
        return
    window.horizontal_preview_y = None
    window.pending_gate = PendingGate("horizontal", {"y_threshold": float(event.ydata), "region": "above"})
    window._disconnect_drawing()
    window.redraw()
    window.status_label.setText("Horizontal gate captured. Click Save Gate to keep it.")


def on_horizontal_motion(window, event):
    if event.inaxes != window.ax or event.ydata is None:
        return
    window.horizontal_preview_y = float(event.ydata)
    _draw_preview_overlay(window)


def on_polygon_click(window, event):
    if event.inaxes != window.ax or event.xdata is None or event.ydata is None:
        return
    point = (float(event.xdata), float(event.ydata))
    if event.button == 3 and len(window.polygon_vertices) >= 3:
        window.pending_gate = PendingGate("polygon", {"vertices": list(window.polygon_vertices)})
        window.polygon_vertices = []
        window.polygon_cursor_point = None
        window._disconnect_drawing()
        window.redraw()
        window.status_label.setText("Polygon captured. Click Save Gate to keep it.")
        return
    if event.button != 1:
        return
    if len(window.polygon_vertices) >= 3:
        first_x, first_y = window.polygon_vertices[0]
        x_span = max(window.ax.get_xlim()[1] - window.ax.get_xlim()[0], 1e-9)
        y_span = max(window.ax.get_ylim()[1] - window.ax.get_ylim()[0], 1e-9)
        close_tol = 0.04 * max(x_span, y_span)
        if np.hypot(point[0] - first_x, point[1] - first_y) <= close_tol or getattr(event, "dblclick", False):
            window.pending_gate = PendingGate("polygon", {"vertices": list(window.polygon_vertices)})
            window.polygon_vertices = []
            window.polygon_cursor_point = None
            window._disconnect_drawing()
            window.redraw()
            window.status_label.setText("Polygon captured. Click Save Gate to keep it.")
            return
    window.polygon_vertices.append(point)
    window.pending_gate = PendingGate("polygon", {"vertices": list(window.polygon_vertices)})
    window.redraw()
    window.status_label.setText("Polygon vertex added. Click near the first vertex, double-click, or right click to finish.")


def on_polygon_motion(window, event):
    if event.inaxes != window.ax or event.xdata is None or event.ydata is None:
        return
    if not window.polygon_vertices:
        return
    window.polygon_cursor_point = (float(event.xdata), float(event.ydata))
    _draw_preview_overlay(window)


def start_zoom_box(window):
    if window.current_transformed.empty:
        window.status_label.setText("Plot a population before zooming.")
        return
    window._disconnect_drawing()
    window.zoom_start_point = None
    window.zoom_current_point = None
    window.canvas_click_cid = window.canvas.mpl_connect("button_press_event", window._on_zoom_box_click)
    window.canvas_motion_cid = window.canvas.mpl_connect("motion_notify_event", window._on_zoom_box_motion)
    window.mode_label.setText("Mode: zoom box")
    window.status_label.setText("Zoom box mode active. Click one corner, then the opposite corner.")


def on_zoom_box_click(window, event):
    if event.inaxes != window.ax or event.xdata is None or event.ydata is None or event.button != 1:
        return
    point = (float(event.xdata), float(event.ydata))
    if window.zoom_start_point is None:
        window.zoom_start_point = point
        window.zoom_current_point = point
        window.status_label.setText("Zoom box first corner set. Click the opposite corner.")
        window.redraw()
        return
    x0, x1 = sorted([window.zoom_start_point[0], point[0]])
    y0, y1 = sorted([window.zoom_start_point[1], point[1]])
    if np.isclose(x0, x1) or np.isclose(y0, y1):
        window.status_label.setText("Zoom box corners must define a non-zero area.")
        window.zoom_current_point = point
        window.redraw()
        return
    x_pad = max((x1 - x0) * 0.08, 1e-9)
    y_pad = max((y1 - y0) * 0.08, 1e-9)
    x0 -= x_pad
    x1 += x_pad
    y0 -= y_pad
    y1 += y_pad
    if window.plot_mode_combo.currentText() == "count histogram" or _is_count_axis(window.y_combo.currentText()):
        key = window._hist_axis_override_key()
        if key is not None:
            window.hist_axis_overrides[key] = (x0, x1, y0, y1)
    else:
        x_key = window._scatter_x_axis_override_key()
        y_key = window._scatter_y_axis_override_key()
        if x_key is not None:
            window.scatter_x_axis_overrides[x_key] = (x0, x1)
        if y_key is not None:
            window.scatter_y_axis_overrides[y_key] = (y0, y1)
    window.zoom_start_point = None
    window.zoom_current_point = None
    window._disconnect_drawing()
    window.redraw()
    window.status_label.setText("Zoom box applied.")


def on_zoom_box_motion(window, event):
    if window.zoom_start_point is None:
        return
    if event.inaxes != window.ax or event.xdata is None or event.ydata is None:
        return
    window.zoom_current_point = (float(event.xdata), float(event.ydata))
    _draw_preview_overlay(window)


def reset_zoom(window):
    x_key = window._scatter_x_axis_override_key()
    y_key = window._scatter_y_axis_override_key()
    hist_key = window._hist_axis_override_key()
    if x_key is not None:
        window.scatter_x_axis_overrides.pop(x_key, None)
    if y_key is not None:
        window.scatter_y_axis_overrides.pop(y_key, None)
    if hist_key is not None:
        window.hist_axis_overrides.pop(hist_key, None)
    if not window.current_transformed.empty:
        window.redraw()
    window.status_label.setText("Zoom reset to automatic limits.")


def start_move_selected_gate(window):
    if window.current_transformed.empty:
        window.status_label.setText("Plot a population before moving a gate.")
        return
    gate = window._selected_gate()
    if gate is None or not window._visible_gate(gate):
        window.status_label.setText("Select a visible saved gate first.")
        return
    if gate["gate_type"] not in {"polygon", "rectangle"}:
        window.status_label.setText("Move Selected Gate currently supports polygon and rectangle gates.")
        return
    window._disconnect_drawing()
    window.translate_gate_mode = True
    window.canvas_press_drag_cid = window.canvas.mpl_connect("button_press_event", window._on_drag_press)
    window.canvas_motion_cid = window.canvas.mpl_connect("motion_notify_event", window._on_drag_motion)
    window.canvas_release_cid = window.canvas.mpl_connect("button_release_event", window._on_drag_release)
    window.mode_label.setText(f"Mode: move {gate['name']}")
    window.status_label.setText("Move mode active. Drag inside the selected gate to translate it.")


def enable_saved_gate_interaction(window):
    gate = window._selected_gate()
    if gate is None or not window._visible_gate(gate):
        return
    window._disconnect_drawing()
    window.translate_gate_mode = False
    window.edit_gate_mode = True
    window.canvas_press_drag_cid = window.canvas.mpl_connect("button_press_event", window._on_drag_press)
    window.canvas_motion_cid = window.canvas.mpl_connect("motion_notify_event", window._on_drag_motion)
    window.canvas_release_cid = window.canvas.mpl_connect("button_release_event", window._on_drag_release)
    window.mode_label.setText(f"Mode: gate selected {gate['name']} (drag to move or edit)")


def start_edit_selected_gate(window):
    if window.current_transformed.empty:
        window.status_label.setText("Plot a population before editing a gate.")
        return
    gate = window._selected_gate()
    if gate is None or not window._visible_gate(gate):
        window.status_label.setText("Select a visible saved gate first.")
        return
    window._disconnect_drawing()
    window.edit_gate_mode = True
    window.canvas_press_drag_cid = window.canvas.mpl_connect("button_press_event", window._on_drag_press)
    window.canvas_motion_cid = window.canvas.mpl_connect("motion_notify_event", window._on_drag_motion)
    window.canvas_release_cid = window.canvas.mpl_connect("button_release_event", window._on_drag_release)
    window.mode_label.setText(f"Mode: edit {gate['name']}")
    window.status_label.setText("Edit mode active. Drag thresholds, quad lines, vertices, or a gate body.")


def gate_hit_test(window, gate, event):
    if event.inaxes != window.ax or event.xdata is None or event.ydata is None:
        return None
    x_span = max(window.ax.get_xlim()[1] - window.ax.get_xlim()[0], 1e-9)
    y_span = max(window.ax.get_ylim()[1] - window.ax.get_ylim()[0], 1e-9)
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
        if window.edit_gate_mode and distances.min() <= max(x_tol, y_tol):
            return {"mode": "polygon_vertex", "vertex_index": int(distances.argmin())}
        if Path(vertices).contains_point((float(event.xdata), float(event.ydata))):
            return {"mode": "polygon_translate"}
    return None


def on_drag_press(window, event):
    if event.button != 1:
        return
    gate = window._selected_gate()
    if gate is None or not window._visible_gate(gate):
        return
    hit = window._gate_hit_test(gate, event)
    if hit is None:
        return
    window.drag_state = {
        "gate_name": gate["name"],
        "press_x": float(event.xdata),
        "press_y": float(event.ydata),
        "press_event_x": float(event.x),
        "press_event_y": float(event.y),
        "active": False,
        "original_gate": dict(gate),
        **hit,
    }


def on_drag_motion(window, event):
    if window.drag_state is None or event.inaxes != window.ax or event.xdata is None or event.ydata is None:
        return
    if not window.drag_state["active"]:
        dx_px = float(event.x) - window.drag_state["press_event_x"]
        dy_px = float(event.y) - window.drag_state["press_event_y"]
        if (dx_px * dx_px + dy_px * dy_px) ** 0.5 <= 8:
            return
        window.drag_state["active"] = True
        window.mode_label.setText(f"Mode: moving {window.drag_state['gate_name']}")
    gate = window._selected_gate()
    if gate is None:
        return
    original = window.drag_state["original_gate"]
    dx = float(event.xdata) - window.drag_state["press_x"]
    dy = float(event.ydata) - window.drag_state["press_y"]
    mode = window.drag_state["mode"]
    gate_group = gate.get("gate_group")
    targets = [item for item in window.gates if item.get("gate_group") == gate_group] if gate_group else [gate]
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
        vertices[window.drag_state["vertex_index"]] = (float(event.xdata), float(event.ydata))
        gate["vertices"] = vertices
    elif mode == "polygon_translate":
        gate["vertices"] = [(x + dx, y + dy) for x, y in original["vertices"]]
    window._schedule_redraw()


def on_drag_release(window, _event):
    if window.drag_state is None:
        return
    gate_name = window.drag_state["gate_name"]
    moved = window.drag_state.get("active", False)
    window.drag_state = None
    was_translate = window.translate_gate_mode
    window.translate_gate_mode = False
    if was_translate:
        window._disconnect_drawing()
    else:
        window.edit_gate_mode = True
        window.mode_label.setText(f"Mode: gate selected {gate_name}")
    window.redraw()
    if moved:
        window._invalidate_cached_outputs()
        window._update_gate_summary()
        window._schedule_heatmap_update()
        window.status_label.setText(f"Updated gate '{gate_name}'.")
    else:
        window.status_label.setText("Move mode cancelled.")


def disconnect_drawing(window):
    _clear_preview_artists(window)
    window.edit_gate_mode = False
    window.translate_gate_mode = False
    window.drag_state = None
    if window.canvas_click_cid is not None:
        window.canvas.mpl_disconnect(window.canvas_click_cid)
        window.canvas_click_cid = None
    if window.canvas_motion_cid is not None:
        window.canvas.mpl_disconnect(window.canvas_motion_cid)
        window.canvas_motion_cid = None
    if window.canvas_release_cid is not None:
        window.canvas.mpl_disconnect(window.canvas_release_cid)
        window.canvas_release_cid = None
    if window.canvas_press_drag_cid is not None:
        window.canvas.mpl_disconnect(window.canvas_press_drag_cid)
        window.canvas_press_drag_cid = None
    window.rectangle_start_point = None
    window.rectangle_current_point = None
    window.zoom_start_point = None
    window.zoom_current_point = None
    window.vertical_preview_x = None
    window.horizontal_preview_y = None
    window.quad_preview_point = None
    window.polygon_cursor_point = None
    window.mode_label.setText("Mode: idle")


def clear_plot(window):
    window.ax.clear()
    window.ax.set_title("No population plotted")
    window.ax.set_xlabel("X")
    window.ax.set_ylabel("Y")
    window.canvas.draw_idle()
