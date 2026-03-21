from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class CompensationState:
    enabled: bool = False
    source_channels: list[str] = field(default_factory=list)
    mapped_channels: list[str] = field(default_factory=list)
    matrix: list[list[float]] | None = None
    raw_text: str = ""


@dataclass(slots=True)
class PlotState:
    population: str = "__all__"
    plot_mode: str = "scatter"
    x_channel: str = ""
    y_channel: str = ""
    x_transform: str = "arcsinh"
    y_transform: str = "arcsinh"
    x_cofactor: float = 150.0
    y_cofactor: float = 150.0
    max_points: int = 15000
    auto_plot: bool = True
    scatter_x_axis_overrides: dict[str, list[float]] = field(default_factory=dict)
    scatter_y_axis_overrides: dict[str, list[float]] = field(default_factory=dict)
    hist_axis_overrides: dict[str, list[float]] = field(default_factory=dict)


@dataclass(slots=True)
class SessionState:
    folder: str = ""
    instrument: str = "Cytoflex"
    gates: list[dict[str, Any]] = field(default_factory=list)
    plate_metadata: dict[str, dict[str, Any]] = field(default_factory=dict)
    recent_sessions: list[str] = field(default_factory=list)
    compensation: CompensationState = field(default_factory=CompensationState)
    plot: PlotState = field(default_factory=PlotState)

