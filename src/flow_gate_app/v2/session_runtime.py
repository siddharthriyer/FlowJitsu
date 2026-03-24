from __future__ import annotations

import json
import os

from PySide6.QtWidgets import QFileDialog, QMessageBox


def session_dir(window):
    session_dir = os.path.join(os.path.expanduser("~"), "Library", "Application Support", "FlowJitsu", "sessions")
    os.makedirs(session_dir, exist_ok=True)
    return session_dir


def settings_path(window):
    settings_dir = os.path.join(os.path.expanduser("~"), "Library", "Application Support", "FlowJitsu")
    os.makedirs(settings_dir, exist_ok=True)
    return os.path.join(settings_dir, "settings.json")


def last_session_path(window):
    return os.path.join(session_dir(window), "last_flow_session.json")


def load_settings(window):
    path = settings_path(window)
    if os.path.isfile(path):
        try:
            with open(path) as fh:
                payload = json.load(fh)
            return payload if isinstance(payload, dict) else {}
        except Exception:
            return {}
    return {}


def save_settings(window, settings):
    with open(settings_path(window), "w") as fh:
        json.dump(settings, fh, indent=2)


def recent_sessions(window):
    recent = load_settings(window).get("recent_sessions", [])
    return [path for path in recent if isinstance(path, str) and os.path.isfile(path)]


def remember_recent_session(window, path):
    if not path:
        return
    path = os.path.abspath(path)
    recent = [item for item in recent_sessions(window) if os.path.abspath(item) != path]
    recent.insert(0, path)
    settings = load_settings(window)
    settings["recent_sessions"] = recent[:12]
    save_settings(window, settings)
    refresh_recent_sessions(window)


def refresh_recent_sessions(window):
    recent = recent_sessions(window)
    current = window.recent_session_combo.currentText()
    window.recent_session_combo.blockSignals(True)
    window.recent_session_combo.clear()
    window.recent_session_combo.addItems(recent)
    if current in recent:
        window.recent_session_combo.setCurrentText(current)
    elif recent:
        window.recent_session_combo.setCurrentIndex(0)
    window.recent_session_combo.blockSignals(False)


def default_export_dir(window):
    export_dir = os.path.join(os.path.expanduser("~"), "Library", "Application Support", "FlowJitsu", "exports")
    os.makedirs(export_dir, exist_ok=True)
    return export_dir


def app_home(window):
    home = os.path.join(os.path.expanduser("~"), "Library", "Application Support", "FlowJitsu")
    os.makedirs(home, exist_ok=True)
    return home


def apply_session_payload(window, payload):
    window._suspend_auto_plot = True
    folder = payload.get("folder", "")
    instrument = payload.get("instrument", window.instrument_combo.currentText())
    if folder:
        window.folder_edit.setText(folder)
    window.instrument_combo.setCurrentText(instrument)
    window.load_folder()
    window.gates = list(payload.get("gates", []))
    window.plate_metadata = dict(payload.get("plate_metadata", {}))
    window._load_compensation_payload(payload.get("compensation", {}))
    plot = payload.get("plot", {})
    window.max_points_spin.setValue(int(plot.get("max_points", window.max_points_spin.value())))
    window.x_transform_combo.setCurrentText(plot.get("x_transform", window.x_transform_combo.currentText()))
    window.x_cofactor_spin.setValue(int(plot.get("x_cofactor", window.x_cofactor_spin.value())))
    window.y_transform_combo.setCurrentText(plot.get("y_transform", window.y_transform_combo.currentText()))
    window.y_cofactor_spin.setValue(int(plot.get("y_cofactor", window.y_cofactor_spin.value())))
    if plot.get("plot_mode") in {"scatter", "count histogram"}:
        window.plot_mode_combo.setCurrentText(plot["plot_mode"])
    if plot.get("x_channel") in window.channel_names:
        window.x_combo.setCurrentText(plot["x_channel"])
    y_values = [window.y_combo.itemText(i) for i in range(window.y_combo.count())]
    if plot.get("y_channel") in y_values:
        window.y_combo.setCurrentText(plot["y_channel"])
    window._refresh_well_list(selected_labels=window._selected_labels())
    window._refresh_saved_gates()
    window._refresh_population_combo(selected_name=plot.get("population", "All Events"))
    window._refresh_heatmap_controls()
    window._refresh_plate_panel()
    window._invalidate_cached_outputs()
    window._update_gate_summary()
    window._schedule_heatmap_update(delay_ms=0)
    window.redraw()
    window._suspend_auto_plot = False
    if window.file_map:
        window.plot_population()


def save_session(window):
    filename = window.current_session_path
    if not filename:
        filename, _ = QFileDialog.getSaveFileName(
            window,
            "Save Session",
            os.path.join(session_dir(window), "flow_session.json"),
            "JSON files (*.json)",
        )
        if not filename:
            return
    try:
        payload = window._session_payload()
        with open(filename, "w") as fh:
            json.dump(payload, fh, indent=2)
        with open(last_session_path(window), "w") as fh:
            json.dump(payload, fh, indent=2)
        window.current_session_path = os.path.abspath(filename)
        remember_recent_session(window, filename)
        window.status_label.setText(f"Saved session to {filename}")
    except Exception as exc:
        window.status_label.setText(f"Failed to save session: {type(exc).__name__}: {exc}")


def load_session(window):
    filename, _ = QFileDialog.getOpenFileName(
        window,
        "Load Session",
        session_dir(window),
        "JSON files (*.json)",
    )
    if not filename:
        return
    try:
        with open(filename) as fh:
            payload = json.load(fh)
        apply_session_payload(window, payload)
        with open(last_session_path(window), "w") as fh:
            json.dump(payload, fh, indent=2)
        window.current_session_path = os.path.abspath(filename)
        remember_recent_session(window, filename)
        window.status_label.setText(f"Loaded session from {filename}")
    except Exception as exc:
        window.status_label.setText(f"Failed to load session: {type(exc).__name__}: {exc}")


def load_recent_session(window):
    filename = window.recent_session_combo.currentText().strip()
    if not filename:
        window.status_label.setText("No recent session selected.")
        return
    if not os.path.isfile(filename):
        window.status_label.setText(f"Recent session not found: {filename}")
        refresh_recent_sessions(window)
        return
    try:
        with open(filename) as fh:
            payload = json.load(fh)
        apply_session_payload(window, payload)
        with open(last_session_path(window), "w") as fh:
            json.dump(payload, fh, indent=2)
        window.current_session_path = os.path.abspath(filename)
        remember_recent_session(window, filename)
        window.status_label.setText(f"Loaded recent session from {filename}")
    except Exception as exc:
        window.status_label.setText(f"Failed to load recent session: {type(exc).__name__}: {exc}")


def autoload_last_session_or_folder(window, base_dir):
    last_session = last_session_path(window)
    if os.path.isfile(last_session):
        try:
            with open(last_session) as fh:
                payload = json.load(fh)
            apply_session_payload(window, payload)
            window.current_session_path = None
            window.status_label.setText(f"Loaded last session from {last_session}")
            return
        except Exception as exc:
            window.status_label.setText(f"Could not auto-load last session: {type(exc).__name__}: {exc}")
    if base_dir and os.path.isdir(base_dir):
        window.folder_edit.setText(base_dir)
        window.load_folder()


def close_event(window, event):
    choice = QMessageBox.question(
        window,
        "Save Session Before Closing",
        "Do you want to save your session before closing?",
        QMessageBox.Yes | QMessageBox.No | QMessageBox.Cancel,
        QMessageBox.Yes,
    )
    if choice == QMessageBox.Cancel:
        event.ignore()
        return
    if choice == QMessageBox.Yes:
        filename = window.current_session_path
        if not filename:
            filename, _ = QFileDialog.getSaveFileName(
                window,
                "Save Session",
                os.path.join(session_dir(window), "flow_session.json"),
                "JSON files (*.json)",
            )
            if not filename:
                event.ignore()
                return
        try:
            payload = window._session_payload()
            with open(filename, "w") as fh:
                json.dump(payload, fh, indent=2)
            with open(last_session_path(window), "w") as fh:
                json.dump(payload, fh, indent=2)
            window.current_session_path = os.path.abspath(filename)
            remember_recent_session(window, filename)
        except Exception as exc:
            window.status_label.setText(f"Failed to save session: {type(exc).__name__}: {exc}")
            event.ignore()
            return
    event.accept()
