from __future__ import annotations

import io
import os
import re

import numpy as np
import pandas as pd
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QFileDialog, QListWidgetItem

from ..helpers import (
    apply_transform as _apply_transform,
    gate_mask as _gate_mask,
    get_channel_names as _get_channel_names,
    get_well_name as _get_well_name,
    is_count_axis as _is_count_axis,
    list_fcs_files as _list_fcs_files,
    transform_array as _transform_array,
)


def browse_folder(window):
    folder = QFileDialog.getExistingDirectory(window, "Choose FCS Folder", window.folder_edit.text().strip() or window.base_dir)
    if folder:
        window.folder_edit.setText(folder)


def load_sample(window, relpath):
    if relpath not in window.sample_cache:
        datafile = os.path.join(window.folder_edit.text().strip(), relpath)
        well = _get_well_name(relpath, window.instrument_combo.currentText())
        FCMeasurement = window._flow_measurement_class()
        window.sample_cache[relpath] = FCMeasurement(ID=well, datafile=datafile)
    return window.sample_cache[relpath]


def update_compensation_status(window):
    if window.compensation_enabled and window.compensation_matrix is not None and window.compensation_channels:
        window.compensation_status_label.setText(f"Compensation: on ({len(window.compensation_channels)} channels)")
    elif window.compensation_text.strip():
        window.compensation_status_label.setText("Compensation: configured but disabled")
    else:
        window.compensation_status_label.setText("Compensation: off")


def compensation_payload(window):
    return {
        "enabled": bool(window.compensation_enabled),
        "source_channels": list(window.compensation_source_channels),
        "channels": list(window.compensation_channels),
        "matrix": window.compensation_matrix.tolist() if isinstance(window.compensation_matrix, np.ndarray) else None,
        "text": window.compensation_text,
    }


def load_compensation_payload(window, payload):
    payload = payload or {}
    window.compensation_enabled = bool(payload.get("enabled", False))
    window.compensation_source_channels = list(payload.get("source_channels", []) or [])
    window.compensation_channels = list(payload.get("channels", []) or [])
    matrix = payload.get("matrix")
    window.compensation_matrix = np.asarray(matrix, dtype=float) if matrix is not None else None
    window.compensation_text = str(payload.get("text", "") or "")
    if window.compensation_matrix is not None and (
        window.compensation_matrix.ndim != 2
        or window.compensation_matrix.shape[0] != window.compensation_matrix.shape[1]
        or window.compensation_matrix.shape[0] != len(window.compensation_channels)
    ):
        window.compensation_matrix = None
        window.compensation_source_channels = []
        window.compensation_channels = []
        window.compensation_enabled = False
    window._update_compensation_status()


def parse_compensation_text(_window, text):
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


def parse_spill_string(_window, raw_value):
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


def extract_compensation_from_sample_meta(window, sample):
    meta = getattr(sample, "meta", None)
    if not isinstance(meta, dict):
        raise ValueError("Sample metadata is unavailable.")
    for key in ("SPILL", "$SPILL", "SPILLOVER", "$SPILLOVER"):
        if key in meta and meta.get(key):
            return window._parse_spill_string(meta.get(key))
    raise ValueError("No SPILL/SPILLOVER compensation metadata was found in the sample.")


def normalize_channel_token(_window, value):
    return re.sub(r"[^a-z0-9]+", "", str(value or "").strip().lower())


def default_compensation_mapping(window, source_channels):
    used = set()
    mapping = []
    normalized_targets = {window._normalize_channel_token(channel): channel for channel in window.channel_names}
    for source in source_channels:
        direct = source if source in window.channel_names and source not in used else None
        if direct is None:
            direct = normalized_targets.get(window._normalize_channel_token(source))
            if direct in used:
                direct = None
        if direct is None:
            source_norm = window._normalize_channel_token(source)
            for channel in window.channel_names:
                channel_norm = window._normalize_channel_token(channel)
                if channel not in used and (source_norm in channel_norm or channel_norm in source_norm):
                    direct = channel
                    break
        if direct is None:
            direct = ""
        else:
            used.add(direct)
        mapping.append(direct)
    return mapping


def apply_compensation(window, df):
    if not window.compensation_enabled or window.compensation_matrix is None or not window.compensation_channels:
        return df.copy(deep=False)
    channels = [channel for channel in window.compensation_channels if channel in df.columns]
    if len(channels) != len(window.compensation_channels):
        return df.copy(deep=False)
    try:
        inverse = np.linalg.pinv(window.compensation_matrix)
    except Exception as exc:
        window.status_label.setText(f"Compensation failed: {type(exc).__name__}: {exc}")
        return df.copy(deep=False)
    compensated = df.copy()
    values = compensated[channels].to_numpy(dtype=float)
    compensated_values = values @ inverse.T
    compensated.loc[:, channels] = compensated_values
    return compensated


def union_channel_names(_window, channel_lists):
    ordered = []
    seen = set()
    for channels in channel_lists:
        for channel in channels:
            if channel not in seen:
                seen.add(channel)
                ordered.append(channel)
    return ordered


def selected_labels(window):
    return [item.data(Qt.UserRole) for item in window.well_list.selectedItems()]


def metadata_for_well(window, well):
    return window.plate_metadata.get(well, {})


def well_item_display_text(window, label):
    well = label.split(" | ")[0]
    relpath = window.file_map[label]
    meta = window._metadata_for_well(well)
    sample_name = str(meta.get("sample_name", "")).strip()
    excluded = bool(meta.get("excluded", False))
    prefix = "[EXCLUDED] " if excluded else ""
    sample_part = f" | {sample_name}" if sample_name else ""
    return f"{prefix}{well}{sample_part} | {relpath}"


def selected_wells(window):
    wells = []
    for label in window._selected_labels():
        if label:
            wells.append(label.split(" | ")[0])
    return wells


def refresh_well_list(window, selected_labels=None):
    selected_labels = list(selected_labels or window._selected_labels())
    window.well_list.blockSignals(True)
    window.well_list.clear()
    for label in window.file_map:
        item = QListWidgetItem(window._well_item_display_text(label))
        item.setData(Qt.UserRole, label)
        window.well_list.addItem(item)
        if label in selected_labels:
            item.setSelected(True)
    if window.well_list.count() and not window.well_list.selectedItems():
        window.well_list.item(0).setSelected(True)
    window.well_list.blockSignals(False)


def plate_badge_text(_window, sample_name):
    text = str(sample_name or "").strip()
    if not text:
        return ""
    compact = "".join(ch for ch in text if ch.isalnum())
    return compact[:4].upper() if compact else text[:4].upper()


def plate_badge_color(_window, sample_name):
    text = str(sample_name or "").strip()
    if not text:
        return "#2a3140"
    palette = ["#4f7cff", "#2f8c74", "#a56ad8", "#c77d2b", "#cc5f7a", "#3d97b8", "#7a9c34", "#b85c2e"]
    return palette[abs(hash(text)) % len(palette)]


def plot_x_transform(window):
    return window.x_transform_combo.currentText()


def plot_x_cofactor(window):
    return float(window.x_cofactor_spin.value())


def plot_y_transform(window):
    return window.y_transform_combo.currentText()


def plot_y_cofactor(window):
    return float(window.y_cofactor_spin.value())


def refresh_channel_controls(window):
    selected = window._selected_labels()
    if not selected:
        available_channels = list(window.channel_names)
    else:
        available_channels = window._union_channel_names(window.channel_names_by_label.get(label, []) for label in selected)

    window.x_combo.blockSignals(True)
    window.y_combo.blockSignals(True)
    current_x = window.x_combo.currentText()
    current_y = window.y_combo.currentText()
    window.x_combo.clear()
    window.y_combo.clear()
    window.x_combo.addItems(available_channels)
    window.y_combo.addItems(list(available_channels) + ["Count"])
    if available_channels:
        window.x_combo.setCurrentText(current_x if current_x in available_channels else ("FSC-A" if "FSC-A" in available_channels else available_channels[0]))
        if current_y == "Count" or window.plot_mode_combo.currentText() == "count histogram":
            window.y_combo.setCurrentText("Count")
        else:
            fallback_y = "SSC-A" if "SSC-A" in available_channels else (available_channels[1] if len(available_channels) > 1 else available_channels[0])
            window.y_combo.setCurrentText(current_y if current_y in available_channels else fallback_y)
    window.x_combo.blockSignals(False)
    window.y_combo.blockSignals(False)

    if selected:
        missing = []
        channels_to_check = [window.x_combo.currentText()]
        if window.plot_mode_combo.currentText() != "count histogram" and not _is_count_axis(window.y_combo.currentText()):
            channels_to_check.append(window.y_combo.currentText())
        for label in selected:
            available = set(window.channel_names_by_label.get(label, []))
            missing_channels = [channel for channel in channels_to_check if channel and channel not in available]
            if missing_channels:
                missing.append(f"{label.split(' | ')[0]} missing {', '.join(missing_channels)}")
        if missing:
            window.channel_status_label.setText("Mixed channels: using channel union. " + " | ".join(missing[:4]))
        else:
            window.channel_status_label.setText("Channel controls updated from selected wells.")
    else:
        window.channel_status_label.setText("Channel controls updated from loaded folder.")


def load_folder(window):
    folder = window.folder_edit.text().strip()
    if not os.path.isdir(folder):
        window.status_label.setText(f"Folder not found: {folder}")
        return

    window._suspend_auto_plot = True
    window.status_label.setText("Scanning folder and reading channels...")
    QApplication.processEvents()

    instrument = window.instrument_combo.currentText()
    files = _list_fcs_files(folder, instrument)
    window.file_map = {}
    window.channel_names_by_label = {}
    window.channel_names = []
    window.sample_cache = {}
    window._sample_raw_cache = {}
    window.plate_metadata = {}
    window.current_data = pd.DataFrame()
    window.current_transformed = pd.DataFrame()
    window.gates = []
    window.pending_gate = None
    window.saved_gate_lookup = {}
    window.selected_gate_name = None

    for relpath in files:
        well = _get_well_name(relpath, instrument)
        label = f"{well} | {relpath}"
        window.file_map[label] = relpath

    channel_lists = []
    for label, relpath in window.file_map.items():
        sample = window._load_sample(relpath)
        sample_channels = _get_channel_names(sample)
        window.channel_names_by_label[label] = sample_channels
        channel_lists.append(sample_channels)
    window.channel_names = window._union_channel_names(channel_lists)

    window._refresh_well_list(selected_labels=list(window.file_map.keys())[:1])
    window.saved_gate_list.clear()
    window._refresh_population_combo()
    window._refresh_recent_sessions()
    window._refresh_channel_controls()
    window._refresh_heatmap_controls()
    window._refresh_plate_panel()
    window._invalidate_cached_outputs()
    if window.file_map:
        window.status_label.setText(f"Loaded {len(window.file_map)} wells in Qt mode. Basic gate drawing is available.")
    else:
        window.status_label.setText("No FCS files found in the selected folder.")
    window._clear_plot()
    window._disconnect_drawing()
    window._update_gate_summary()
    window._schedule_heatmap_update(delay_ms=0)
    window._suspend_auto_plot = False
    if window.file_map:
        window.plot_population()


def sample_raw_dataframe(window, label):
    cached = window._sample_raw_cache.get(label)
    if cached is not None:
        return cached.copy(deep=False)
    relpath = window.file_map[label]
    sample = window._load_sample(relpath)
    df = window._apply_compensation(sample.data)
    df["__well__"] = _get_well_name(relpath, window.instrument_combo.currentText())
    df["__source__"] = relpath
    window._sample_raw_cache[label] = df
    return df.copy(deep=False)


def selected_labels_key(window):
    return tuple(window._selected_labels())


def selected_raw_dataframe(window):
    labels = window._selected_labels_key()
    if not labels:
        return pd.DataFrame()
    cached = window._selected_raw_cache.get(labels)
    if cached is not None:
        return cached.copy(deep=False)
    frames = [window._sample_raw_dataframe(label) for label in labels]
    combined = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
    window._selected_raw_cache[labels] = combined
    return combined.copy(deep=False)


def display_dataframe(window):
    cache_key = (
        window._selected_labels_key(),
        window._selected_population_name(),
        window.x_combo.currentText(),
        window.y_combo.currentText(),
        window._plot_x_transform(),
        window._plot_x_cofactor(),
        window._plot_y_transform(),
        window._plot_y_cofactor(),
        window.plot_mode_combo.currentText(),
    )
    cached = window._display_cache.get(cache_key)
    if cached is not None:
        raw_df, transformed = cached
        return raw_df.copy(deep=False), transformed.copy(deep=False)

    df = window._population_raw_dataframe(window._selected_population_name())
    if df.empty:
        return df, df
    x_channel = window.x_combo.currentText()
    y_channel = window.y_combo.currentText()
    if x_channel not in df.columns:
        raise ValueError(f"Selected X channel '{x_channel}' is not available in the current wells.")
    if window.plot_mode_combo.currentText() == "count histogram" or _is_count_axis(y_channel):
        transformed = pd.DataFrame(index=df.index.copy())
        transformed[x_channel] = _transform_array(df[x_channel].to_numpy(), window._plot_x_transform(), window._plot_x_cofactor())
        transformed["__well__"] = df["__well__"].to_numpy()
        window._display_cache[cache_key] = (df, transformed)
        return df.copy(deep=False), transformed.copy(deep=False)
    if y_channel not in df.columns:
        raise ValueError(f"Selected Y channel '{y_channel}' is not available in the current wells.")
    transformed = _apply_transform(
        df,
        x_channel,
        y_channel,
        window._plot_x_transform(),
        window._plot_x_cofactor(),
        y_method=window._plot_y_transform(),
        y_cofactor=window._plot_y_cofactor(),
    )
    transformed["__well__"] = df["__well__"].to_numpy()
    window._display_cache[cache_key] = (df, transformed)
    return df.copy(deep=False), transformed.copy(deep=False)


def population_mask(window, raw_df, gate):
    mask = pd.Series(True, index=raw_df.index)
    for lineage_gate in window._population_lineage(gate["name"]):
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


def invalidate_cached_outputs(window):
    window._summary_cache = None
    window._intensity_cache = None
    window._selected_raw_cache = {}
    window._population_raw_cache = {}
    window._sample_population_cache = {}
    window._sample_population_transform_cache = {}
    window._display_cache = {}


def downsample(window, transformed):
    if transformed.empty:
        return transformed
    max_points = window.max_points_spin.value()
    if len(transformed) <= max_points:
        return transformed
    labels = window._selected_labels()
    per_group = max(1, max_points // max(len(labels), 1))
    pieces = []
    for _, group in transformed.groupby("__well__", sort=False):
        pieces.append(group.sample(n=min(per_group, len(group)), random_state=0))
    return pd.concat(pieces, ignore_index=True)


def plot_selection_title(window):
    labels = window._selected_labels()
    if not labels:
        return ""
    wells = [label.split(" | ")[0] for label in labels]
    if len(wells) == 1:
        sample_name = str(window._metadata_for_well(wells[0]).get("sample_name", "")).strip()
        return f"{wells[0]} | {sample_name}" if sample_name else wells[0]
    if len(wells) <= 4:
        return ", ".join(wells)
    return f"{len(wells)} wells"


def population_display_label(window):
    return window.population_combo.currentText() or "All Events"


def selected_population_name(window):
    return window.population_labels.get(window.population_combo.currentText(), "__all__")


def population_lineage(window, name):
    lineage = []
    current = next((gate for gate in window.gates if gate["name"] == name), None)
    while current is not None:
        lineage.append(current)
        parent_name = current.get("parent_population", "__all__")
        if parent_name == "__all__":
            break
        current = next((gate for gate in window.gates if gate["name"] == parent_name), None)
    return list(reversed(lineage))


def refresh_population_combo(window, selected_name=None):
    window.population_labels = {"All Events": "__all__"}
    population_values = ["All Events"]
    for gate in window.gates:
        window.population_labels[gate["name"]] = gate["name"]
        population_values.append(gate["name"])
    current_text = window.population_combo.currentText()
    window.population_combo.blockSignals(True)
    window.population_combo.clear()
    window.population_combo.addItems(population_values)
    target = selected_name or current_text
    if target in population_values:
        window.population_combo.setCurrentText(target)
    else:
        window.population_combo.setCurrentText("All Events")
    window.population_combo.blockSignals(False)


def fluorescence_channels(window):
    return [channel for channel in window.channel_names if not any(token in channel for token in ("FSC", "SSC", "Time"))]


def scatter_x_axis_override_key(window):
    channel = window.x_combo.currentText()
    return channel or None


def scatter_y_axis_override_key(window):
    channel = window.y_combo.currentText()
    return channel or None


def hist_axis_override_key(window):
    channel = window.x_combo.currentText()
    return channel or None


def histogram_mode(window):
    return window.plot_mode_combo.currentText() == "count histogram" or _is_count_axis(window.y_combo.currentText())


def hist_bins(_window):
    return 100


def sample_population_raw_dataframe(window, label, population_name):
    cache_key = (label, population_name)
    cached = window._sample_population_cache.get(cache_key)
    if cached is not None:
        return cached.copy(deep=False)
    raw_df = window._sample_raw_dataframe(label)
    if raw_df.empty or population_name == "__all__":
        window._sample_population_cache[cache_key] = raw_df
        return raw_df.copy(deep=False)
    gate = next((item for item in window.gates if item["name"] == population_name), None)
    if gate is None:
        return pd.DataFrame()
    mask = window._population_mask(raw_df, gate)
    out = raw_df.loc[mask].copy()
    window._sample_population_cache[cache_key] = out
    return out.copy(deep=False)


def population_raw_dataframe(window, population_name):
    cache_key = (window._selected_labels_key(), population_name)
    cached = window._population_raw_cache.get(cache_key)
    if cached is not None:
        return cached.copy(deep=False)
    frames = []
    for label in window._selected_labels():
        sample_df = window._sample_population_raw_dataframe(label, population_name)
        if not sample_df.empty:
            frames.append(sample_df)
    df = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
    window._population_raw_cache[cache_key] = df
    return df.copy(deep=False)


def sample_population_transformed_dataframe(window, label, population_name, x_channel, y_channel, x_method, x_cofactor, y_method="arcsinh", y_cofactor=150.0):
    cache_key = (
        label,
        population_name,
        x_channel,
        y_channel,
        x_method,
        float(x_cofactor),
        y_method,
        float(y_cofactor),
    )
    cached = window._sample_population_transform_cache.get(cache_key)
    if cached is not None:
        return cached.copy(deep=False)
    raw_df = window._sample_population_raw_dataframe(label, population_name)
    if raw_df.empty or x_channel not in raw_df.columns or y_channel not in raw_df.columns:
        return pd.DataFrame()
    transformed = _apply_transform(raw_df, x_channel, y_channel, x_method, x_cofactor, y_method=y_method, y_cofactor=y_cofactor)
    transformed["__well__"] = raw_df["__well__"].to_numpy()
    window._sample_population_transform_cache[cache_key] = transformed
    return transformed.copy(deep=False)


def median_scatter_axis_limits(window):
    if window._histogram_mode() or not window.file_map:
        return None
    x_channel = window.x_combo.currentText()
    y_channel = window.y_combo.currentText()
    if not x_channel or not y_channel or _is_count_axis(y_channel):
        return None
    population_name = window._selected_population_name()
    bounds = []
    for label in window.file_map:
        try:
            transformed_group = window._sample_population_transformed_dataframe(
                label,
                population_name,
                x_channel,
                y_channel,
                window._plot_x_transform(),
                window._plot_x_cofactor(),
                y_method=window._plot_y_transform(),
                y_cofactor=window._plot_y_cofactor(),
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
            float(np.quantile(x_values, window._robust_axis_lower_q())),
            float(np.quantile(x_values, window._robust_axis_upper_q())),
            float(np.quantile(y_values, window._robust_axis_lower_q())),
            float(np.quantile(y_values, window._robust_axis_upper_q())),
        ))
    if not bounds:
        return None
    xmin, xmax, ymin, ymax = [float(value) for value in np.median(np.asarray(bounds, dtype=float), axis=0)]
    x_pad = max(abs(xmin) * 0.05, 1.0) if np.isclose(xmin, xmax) else (xmax - xmin) * 0.05
    xmin -= x_pad
    xmax += x_pad
    y_pad = max(abs(ymin) * 0.05, 1.0) if np.isclose(ymin, ymax) else (ymax - ymin) * 0.05
    ymin -= y_pad
    ymax += y_pad
    return xmin, xmax, ymin, ymax


def global_scatter_axis_extent(window):
    if window._histogram_mode() or not window.file_map:
        return None
    x_channel = window.x_combo.currentText()
    y_channel = window.y_combo.currentText()
    if not x_channel or not y_channel or _is_count_axis(y_channel):
        return None
    population_name = window._selected_population_name()
    xmin = xmax = ymin = ymax = None
    for label in window.file_map:
        try:
            transformed_group = window._sample_population_transformed_dataframe(
                label,
                population_name,
                x_channel,
                y_channel,
                window._plot_x_transform(),
                window._plot_x_cofactor(),
                y_method=window._plot_y_transform(),
                y_cofactor=window._plot_y_cofactor(),
            )
        except Exception:
            continue
        if x_channel not in transformed_group.columns or y_channel not in transformed_group.columns:
            continue
        x_values = pd.to_numeric(transformed_group[x_channel], errors="coerce").replace([np.inf, -np.inf], np.nan).dropna().to_numpy()
        y_values = pd.to_numeric(transformed_group[y_channel], errors="coerce").replace([np.inf, -np.inf], np.nan).dropna().to_numpy()
        if len(x_values) == 0 or len(y_values) == 0:
            continue
        group_xmin = float(np.quantile(x_values, window._robust_axis_lower_q()))
        group_xmax = float(np.quantile(x_values, window._robust_axis_upper_q()))
        group_ymin = float(np.quantile(y_values, window._robust_axis_lower_q()))
        group_ymax = float(np.quantile(y_values, window._robust_axis_upper_q()))
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


def rectangle_vertices(_window, start_x, start_y, end_x, end_y):
    x0, x1 = sorted([float(start_x), float(end_x)])
    y0, y1 = sorted([float(start_y), float(end_y)])
    return [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]


def effective_scatter_axis_limits(window):
    base_limits = window._median_scatter_axis_limits()
    if base_limits is None:
        return None
    x_override = window.scatter_x_axis_overrides.get(window._scatter_x_axis_override_key())
    y_override = window.scatter_y_axis_overrides.get(window._scatter_y_axis_override_key())
    x_limits = x_override if x_override is not None else base_limits[:2]
    y_limits = y_override if y_override is not None else base_limits[2:]
    return (x_limits[0], x_limits[1], y_limits[0], y_limits[1])


def effective_histogram_axis_limits(window, transformed=None):
    base_limits = window._median_histogram_axis_limits(transformed=transformed)
    if base_limits is None:
        return None
    override = window.hist_axis_overrides.get(window._hist_axis_override_key())
    if override is None:
        return base_limits
    ymax = window._current_histogram_ymax(transformed=transformed, x_limits=(override[0], override[1]))
    return (override[0], override[1], override[2], ymax)


def current_histogram_ymax(window, transformed=None, x_limits=None):
    if transformed is None:
        transformed = window.current_transformed
    if transformed is None or transformed.empty:
        return 1.0
    x_channel = window.x_combo.currentText()
    if not x_channel or x_channel not in transformed.columns:
        return 1.0
    if x_limits is None:
        extent = window._global_histogram_axis_extent()
        if extent is None:
            return 1.0
        xmin, xmax = float(extent[0]), float(extent[1])
    else:
        xmin, xmax = x_limits
    edges = np.linspace(xmin, xmax, window._hist_bins() + 1)
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


def median_histogram_axis_limits(window, transformed=None):
    if not window._histogram_mode() or not window.file_map:
        return None
    x_channel = window.x_combo.currentText()
    if not x_channel:
        return None
    extent = window._global_histogram_axis_extent()
    if extent is None:
        return None
    xmin, xmax = float(extent[0]), float(extent[1])
    ymax = window._current_histogram_ymax(transformed=transformed, x_limits=(xmin, xmax))
    return xmin, xmax, 0.0, ymax


def global_histogram_axis_extent(window):
    if not window._histogram_mode() or not window.file_map:
        return None
    x_channel = window.x_combo.currentText()
    if not x_channel:
        return None
    population_name = window._selected_population_name()
    global_xmin = None
    global_xmax = None
    transformed_groups = []
    for label in window.file_map:
        try:
            group = window._sample_population_raw_dataframe(label, population_name)
        except Exception:
            continue
        if group.empty or x_channel not in group.columns:
            continue
        x_values = _transform_array(group[x_channel].to_numpy(), window._plot_x_transform(), window._plot_x_cofactor())
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
    x_pad = max(abs(global_xmax) * 0.1, 1.0) if np.isclose(global_xmin, global_xmax) else (global_xmax - global_xmin) * 0.1
    xmin_limit = global_xmin - x_pad
    xmax_limit = global_xmax + x_pad
    edges = np.linspace(xmin_limit, xmax_limit, window._hist_bins() + 1)
    max_count = 0
    for x_values in transformed_groups:
        counts, _ = np.histogram(x_values, bins=edges)
        if len(counts):
            max_count = max(max_count, int(counts.max()))
    ymax_limit = max(float(max_count) * 1.1, 1.0)
    return xmin_limit, xmax_limit, 0.0, ymax_limit


def visible_gate(window, gate):
    histogram_mode = window.plot_mode_combo.currentText() == "count histogram" or _is_count_axis(window.y_combo.currentText())
    if gate["x_channel"] != window.x_combo.currentText():
        return False
    if gate["gate_type"] == "vertical":
        return True
    if histogram_mode:
        return False
    return gate.get("y_channel") in {None, window.y_combo.currentText()}
