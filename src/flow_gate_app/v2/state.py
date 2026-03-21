from __future__ import annotations

from .models import CompensationState, PlotState, SessionState


def session_state_from_window(window) -> SessionState:
    compensation_matrix = None
    if window.compensation_matrix is not None:
        compensation_matrix = window.compensation_matrix.tolist()
    return SessionState(
        folder=window.folder_edit.text().strip(),
        instrument=window.instrument_combo.currentText(),
        gates=[dict(gate) for gate in window.gates],
        plate_metadata={well: dict(meta) for well, meta in window.plate_metadata.items()},
        recent_sessions=list(window._recent_sessions()),
        compensation=CompensationState(
            enabled=bool(window.compensation_enabled),
            source_channels=list(window.compensation_source_channels),
            mapped_channels=list(window.compensation_channels),
            matrix=compensation_matrix,
            raw_text=window.compensation_text,
        ),
        plot=PlotState(
            population=window._selected_population_name(),
            plot_mode=window.plot_mode_combo.currentText(),
            x_channel=window.x_combo.currentText(),
            y_channel=window.y_combo.currentText(),
            x_transform=window.x_transform_combo.currentText(),
            y_transform=window.y_transform_combo.currentText(),
            x_cofactor=float(window.x_cofactor_spin.value()),
            y_cofactor=float(window.y_cofactor_spin.value()),
            max_points=int(window.max_points_spin.value()),
            auto_plot=bool(window.auto_plot_enabled),
            scatter_x_axis_overrides={key: list(value) for key, value in window.scatter_x_axis_overrides.items()},
            scatter_y_axis_overrides={key: list(value) for key, value in window.scatter_y_axis_overrides.items()},
            hist_axis_overrides={key: list(value) for key, value in window.hist_axis_overrides.items()},
        ),
    )


def session_state_to_payload(state: SessionState) -> dict:
    payload = {
        "folder": state.folder,
        "instrument": state.instrument,
        "gates": [dict(gate) for gate in state.gates],
        "plate_metadata": {well: dict(meta) for well, meta in state.plate_metadata.items()},
        "population": state.plot.population,
        "plot_mode": state.plot.plot_mode,
        "x_channel": state.plot.x_channel,
        "y_channel": state.plot.y_channel,
        "x_transform": state.plot.x_transform,
        "y_transform": state.plot.y_transform,
        "x_cofactor": state.plot.x_cofactor,
        "y_cofactor": state.plot.y_cofactor,
        "max_points": state.plot.max_points,
        "auto_plot": state.plot.auto_plot,
        "scatter_x_axis_overrides": state.plot.scatter_x_axis_overrides,
        "scatter_y_axis_overrides": state.plot.scatter_y_axis_overrides,
        "hist_axis_overrides": state.plot.hist_axis_overrides,
        "compensation": {
            "enabled": state.compensation.enabled,
            "source_channels": list(state.compensation.source_channels),
            "mapped_channels": list(state.compensation.mapped_channels),
            "matrix": state.compensation.matrix,
            "text": state.compensation.raw_text,
        },
    }
    return payload

