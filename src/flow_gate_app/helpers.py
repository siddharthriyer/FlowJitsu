import os
import re
import subprocess
import sys
from dataclasses import dataclass

import numpy as np
import pandas as pd
from matplotlib.path import Path


GITHUB_REPO = "siddharthriyer/FlowJitsu"
GITHUB_RELEASES_URL = f"https://github.com/{GITHUB_REPO}/releases"
GITHUB_LATEST_RELEASE_API = f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"
APP_BRAND = "FlowJitsu"
DOWNLOADS_SUBDIR = "FlowJitsuUpdates"


def platform_key():
    if sys.platform.startswith("win"):
        return "windows"
    if sys.platform == "darwin":
        return "macos"
    return "other"


def open_path(path):
    path = os.path.abspath(path)
    if sys.platform.startswith("win"):
        os.startfile(path)
    elif sys.platform == "darwin":
        subprocess.Popen(["open", path], start_new_session=True)
    else:
        subprocess.Popen(["xdg-open", path], start_new_session=True)


def normalize_instrument_name(instrument):
    if instrument is None:
        return "cytoflex"
    normalized = instrument.strip().lower()
    if normalized == "symphopny":
        normalized = "symphony"
    return normalized


def preferred_data_dir(start_path):
    current = os.path.abspath(start_path)
    candidates = []
    if os.path.isdir(current):
        candidates.extend([
            os.path.join(current, "Data"),
            os.path.join(current, "data"),
            os.path.join(current, "..", "Data"),
            os.path.join(current, "..", "data"),
        ])
    else:
        parent = os.path.dirname(current)
        candidates.extend([
            os.path.join(parent, "Data"),
            os.path.join(parent, "data"),
            os.path.join(parent, "..", "Data"),
            os.path.join(parent, "..", "data"),
        ])
    for path in candidates:
        path = os.path.abspath(path)
        if os.path.isdir(path):
            return path
    return current if os.path.isdir(current) else os.path.dirname(current)


def list_fcs_files(datadir, instrument="Cytoflex"):
    instrument = normalize_instrument_name(instrument)
    fcs_files = []
    for root, _, files in os.walk(datadir):
        for file in files:
            if file.lower().endswith(".fcs"):
                relpath = os.path.relpath(os.path.join(root, file), datadir)
                fcs_files.append(relpath)
        if instrument != "symphony" and fcs_files:
            break
    return sorted(fcs_files)


def get_well_name(file, instrument="Cytoflex"):
    filename = os.path.basename(file)
    instrument = normalize_instrument_name(instrument)
    if instrument in {"cytoflex", "symphony"}:
        match = re.search(r"([A-H])(0?[1-9]|1[0-2])(?=\.fcs|\b)", filename, re.IGNORECASE)
        if match:
            row, col = match.groups()
            return f"{row.upper()}{int(col)}"
    raise ValueError(f"Could not determine well name from file: {file}")


def get_channel_names(sample):
    channels = sample.channels
    if hasattr(channels, "columns"):
        for column in ("$PnS", "$PnN"):
            if column in channels.columns:
                values = channels[column].dropna().astype(str)
                values = [value.strip() for value in values if value.strip()]
                if values:
                    return values
        return list(channels.index.astype(str))
    return [str(channel) for channel in channels]


def transform_array(values, method, cofactor):
    arr = np.asarray(values, dtype=float)
    if method == "linear":
        return arr
    if method == "log10":
        return np.log10(np.clip(arr, 1, None))
    if method == "arcsinh":
        return np.arcsinh(arr / max(float(cofactor), 1e-9))
    raise ValueError(f"Unsupported transform: {method}")


def apply_transform(df, x_channel, y_channel, method, cofactor, y_method=None, y_cofactor=None):
    x_method = method
    x_cofactor = cofactor
    if y_method is None:
        y_method = x_method
    if y_cofactor is None:
        y_cofactor = x_cofactor
    transformed = pd.DataFrame(index=df.index.copy())
    transformed[x_channel] = transform_array(df[x_channel].to_numpy(), x_method, x_cofactor)
    transformed[y_channel] = transform_array(df[y_channel].to_numpy(), y_method, y_cofactor)
    return transformed


def gate_plot_y_channel(gate):
    return gate["y_channel"] if gate.get("y_channel") else gate["x_channel"]


def is_count_axis(value):
    return str(value).strip().lower() in {"count", "__count__"}


def event_adds_to_selection(event):
    state = int(getattr(event, "state", 0))
    return bool(state & 0x0001 or state & 0x0004 or state & 0x0008 or state & 0x0010)


def normalize_version_tag(version):
    return str(version).strip().lstrip("vV")


def version_key(version):
    parts = re.findall(r"\d+", normalize_version_tag(version))
    return tuple(int(part) for part in parts) if parts else (0,)


def gate_mask(transformed_df, gate_spec):
    gate_type = gate_spec["gate_type"]
    x_channel = gate_spec["x_channel"]
    x_values = transformed_df[x_channel].to_numpy()

    if gate_type in {"polygon", "rectangle"}:
        y_channel = gate_spec["y_channel"]
        points = transformed_df[[x_channel, y_channel]].to_numpy()
        return Path(gate_spec["vertices"]).contains_points(points)

    if gate_type == "quad":
        y_channel = gate_spec["y_channel"]
        y_values = transformed_df[y_channel].to_numpy()
        x0 = gate_spec["x_threshold"]
        y0 = gate_spec["y_threshold"]
        region = gate_spec["region"]
        if region == "top right":
            return (x_values >= x0) & (y_values >= y0)
        if region == "top left":
            return (x_values < x0) & (y_values >= y0)
        if region == "bottom left":
            return (x_values < x0) & (y_values < y0)
        if region == "bottom right":
            return (x_values >= x0) & (y_values < y0)
        raise ValueError(f"Unsupported quad region: {region}")

    if gate_type == "vertical":
        threshold = gate_spec["x_threshold"]
        if gate_spec["region"] == "above":
            return x_values >= threshold
        if gate_spec["region"] == "below":
            return x_values < threshold
        raise ValueError(f"Unsupported threshold region: {gate_spec['region']}")

    if gate_type == "horizontal":
        y_channel = gate_spec["y_channel"]
        y_values = transformed_df[y_channel].to_numpy()
        threshold = gate_spec["y_threshold"]
        if gate_spec["region"] == "above":
            return y_values >= threshold
        if gate_spec["region"] == "below":
            return y_values < threshold
        raise ValueError(f"Unsupported threshold region: {gate_spec['region']}")

    raise ValueError(f"Unsupported gate type: {gate_type}")


def render_gate(ax, gate_spec, selected=False, linestyle="-", label=None):
    color = gate_spec.get("color", "crimson")
    linewidth = 2.5 if selected else 1.8
    if gate_spec["gate_type"] in {"polygon", "rectangle"}:
        vertices = np.asarray(gate_spec["vertices"])
        closed = np.vstack([vertices, vertices[0]])
        return ax.plot(closed[:, 0], closed[:, 1], color=color, linewidth=linewidth, linestyle=linestyle, label=label)
    if gate_spec["gate_type"] == "quad":
        vline = ax.axvline(gate_spec["x_threshold"], color=color, linewidth=linewidth, linestyle=linestyle, label=label)
        hline = ax.axhline(gate_spec["y_threshold"], color=color, linewidth=linewidth, linestyle=linestyle)
        return [vline, hline]
    if gate_spec["gate_type"] == "vertical":
        return [ax.axvline(gate_spec["x_threshold"], color=color, linewidth=linewidth, linestyle=linestyle, label=label)]
    if gate_spec["gate_type"] == "horizontal":
        return [ax.axhline(gate_spec["y_threshold"], color=color, linewidth=linewidth, linestyle=linestyle, label=label)]
    return []


def build_flow_gate(gate_spec):
    tools = flow_tools()
    PolyGate = tools["PolyGate"]
    QuadGate = tools["QuadGate"]
    ThresholdGate = tools["ThresholdGate"]
    if gate_spec["gate_type"] in {"polygon", "rectangle"}:
        return PolyGate(
            gate_spec["vertices"],
            channels=(gate_spec["x_channel"], gate_spec["y_channel"]),
            region="in",
            name=gate_spec["name"],
        )
    if gate_spec["gate_type"] == "quad":
        return QuadGate(
            (gate_spec["x_threshold"], gate_spec["y_threshold"]),
            channels=[gate_spec["x_channel"], gate_spec["y_channel"]],
            region=gate_spec["region"],
            name=gate_spec["name"],
        )
    if gate_spec["gate_type"] == "vertical":
        return ThresholdGate(
            gate_spec["x_threshold"],
            channels=[gate_spec["x_channel"]],
            region=gate_spec["region"],
            name=gate_spec["name"],
        )
    if gate_spec["gate_type"] == "horizontal":
        return ThresholdGate(
            gate_spec["y_threshold"],
            channels=[gate_spec["y_channel"]],
            region=gate_spec["region"],
            name=gate_spec["name"],
        )
    raise ValueError(f"Unsupported gate type: {gate_spec['gate_type']}")


@dataclass
class PendingGate:
    gate_type: str
    payload: dict
_FLOW_TOOLS = None


def flow_tools():
    global _FLOW_TOOLS
    if _FLOW_TOOLS is None:
        from FlowCytometryTools import FCMeasurement, PolyGate, QuadGate, ThresholdGate
        _FLOW_TOOLS = {
            "FCMeasurement": FCMeasurement,
            "PolyGate": PolyGate,
            "QuadGate": QuadGate,
            "ThresholdGate": ThresholdGate,
        }
    return _FLOW_TOOLS
