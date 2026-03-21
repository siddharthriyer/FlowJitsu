from __future__ import annotations

import json
import os

import pandas as pd
from PySide6.QtWidgets import QFileDialog

from ..analysis_views import (
    analysis_bundle_paths as _analysis_bundle_paths_impl,
    analysis_html_document as _analysis_html_document_impl,
    analysis_notebook_dict as _analysis_notebook_dict_impl,
    write_analysis_bundle_csvs as _write_analysis_bundle_csvs_impl,
)
from ..helpers import apply_transform as _apply_transform, gate_mask as _gate_mask, transform_array as _transform_array
from .analysis_dialog import AnalysisPreviewDialog


def summary_dataframe(window):
    if window._summary_cache is not None:
        return window._summary_cache.copy(deep=False)
    rows = []
    for label, relpath in window.file_map.items():
        well = label.split(" | ")[0]
        if window._metadata_for_well(well).get("excluded", False):
            continue
        df = window._sample_raw_dataframe(label)
        meta = window._metadata_for_well(well)
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
        for gate in window.gates:
            frac, count, parent_total = window._gate_fraction_for_label(gate, label)
            row[f"pct_{gate['name']}"] = 100.0 * frac
            row[f"count_{gate['name']}"] = count
            row[f"parent_count_{gate['name']}"] = parent_total
        rows.append(row)
    summary = pd.DataFrame(rows)
    window._summary_cache = summary
    return summary.copy(deep=False)


def intensity_distribution_dataframe(window):
    if window._intensity_cache is not None:
        return window._intensity_cache.copy(deep=False)
    fluorescence_columns = window._fluorescence_channels()
    frames = []
    for label, relpath in window.file_map.items():
        well = label.split(" | ")[0]
        if window._metadata_for_well(well).get("excluded", False):
            continue
        df = window._sample_raw_dataframe(label)
        keep_columns = ["__well__", "__source__"] + [col for col in fluorescence_columns if col in df.columns]
        out = df[keep_columns].copy()
        out.rename(columns={"__well__": "well", "__source__": "source"}, inplace=True)
        meta = window._metadata_for_well(well)
        out["sample_name"] = meta.get("sample_name", "")
        out["sample_type"] = meta.get("sample_type", "")
        out["dose_curve"] = meta.get("dose_curve", "")
        out["dose"] = meta.get("dose", "")
        out["replicate"] = meta.get("replicate", "")
        out["dose_direction"] = meta.get("dose_direction", "")
        out["treatment_group"] = meta.get("treatment_group", "")
        out["excluded"] = bool(meta.get("excluded", False))
        for gate in window.gates:
            frac_mask = pd.Series(False, index=df.index)
            x_channel = gate["x_channel"]
            if x_channel in df.columns:
                if gate["gate_type"] == "vertical":
                    transformed = pd.DataFrame(index=df.index.copy())
                    transformed[x_channel] = _transform_array(
                        df[x_channel].to_numpy(),
                        gate.get("x_transform", "arcsinh"),
                        gate.get("x_cofactor", 150.0),
                    )
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
    window._intensity_cache = intensity
    return intensity.copy(deep=False)


def plate_metadata_dataframe(window):
    rows = []
    for well, meta in sorted(window.plate_metadata.items(), key=lambda item: (item[0][0], int(item[0][1:]))):
        row = {"well": well}
        row.update(meta)
        rows.append(row)
    return pd.DataFrame(rows)


def export_gate_summary_csv(window):
    filename, _ = QFileDialog.getSaveFileName(
        window,
        "Export Gate Summary CSV",
        os.path.join(window._default_export_dir(), "flow_gate_summary.csv"),
        "CSV files (*.csv)",
    )
    if not filename:
        return
    try:
        window._summary_dataframe().to_csv(filename, index=False)
        window.status_label.setText(f"Saved gate summary to {filename}")
    except Exception as exc:
        window.status_label.setText(f"Failed to save gate summary: {type(exc).__name__}: {exc}")


def export_intensity_csv(window):
    filename, _ = QFileDialog.getSaveFileName(
        window,
        "Export Intensities CSV",
        os.path.join(window._default_export_dir(), "flow_intensity_distribution.csv"),
        "CSV files (*.csv)",
    )
    if not filename:
        return
    try:
        window._intensity_distribution_dataframe().to_csv(filename, index=False)
        window.status_label.setText(f"Saved intensity distribution to {filename}")
    except Exception as exc:
        window.status_label.setText(f"Failed to save intensity distribution: {type(exc).__name__}: {exc}")


def export_plate_metadata_csv(window):
    filename, _ = QFileDialog.getSaveFileName(
        window,
        "Export Plate Metadata CSV",
        os.path.join(window._default_export_dir(), "flow_plate_metadata.csv"),
        "CSV files (*.csv)",
    )
    if not filename:
        return
    try:
        window._plate_metadata_dataframe().to_csv(filename, index=False)
        window.status_label.setText(f"Saved plate metadata to {filename}")
    except Exception as exc:
        window.status_label.setText(f"Failed to save plate metadata: {type(exc).__name__}: {exc}")


def analysis_bundle_paths(window):
    return _analysis_bundle_paths_impl(window)


def write_analysis_bundle_csvs(window, bundle_paths):
    return _write_analysis_bundle_csvs_impl(window, bundle_paths)


def open_analysis_preview(window):
    try:
        summary = window._summary_dataframe()
        intensity = window._intensity_distribution_dataframe()
        if summary.empty and intensity.empty:
            window.status_label.setText("No data available yet.")
            return
        dialog = AnalysisPreviewDialog(window, summary, intensity)
        dialog.exec()
    except Exception as exc:
        window.status_label.setText(f"Failed to open analysis preview: {type(exc).__name__}: {exc}")


def create_analysis_notebook(window):
    try:
        bundle_paths = window._analysis_bundle_paths()
        window._write_analysis_bundle_csvs(bundle_paths)
        nb = _analysis_notebook_dict_impl(
            summary_relpath=os.path.relpath(bundle_paths["summary_path"], os.path.dirname(bundle_paths["notebook_path"])),
            intensity_relpath=os.path.relpath(bundle_paths["intensity_path"], os.path.dirname(bundle_paths["notebook_path"])),
            plate_relpath=os.path.relpath(bundle_paths["plate_path"], os.path.dirname(bundle_paths["notebook_path"])),
            notebook_title=f"{bundle_paths['date_label']} Flow Desktop Analysis",
        )
        with open(bundle_paths["notebook_path"], "w") as fh:
            json.dump(nb, fh, indent=1)
        window.status_label.setText(f"Saved notebook to {bundle_paths['notebook_path']}")
    except Exception as exc:
        window.status_label.setText(f"Failed to create analysis notebook: {type(exc).__name__}: {exc}")


def export_html_report(window):
    try:
        bundle_paths = window._analysis_bundle_paths()
        summary, intensity, plate = window._write_analysis_bundle_csvs(bundle_paths)
        html_document = _analysis_html_document_impl(window, summary, intensity, plate, bundle_paths)
        with open(bundle_paths["html_path"], "w", encoding="utf-8") as fh:
            fh.write(html_document)
        window.status_label.setText(f"Saved HTML report to {bundle_paths['html_path']}")
    except Exception as exc:
        window.status_label.setText(f"Failed to export HTML report: {type(exc).__name__}: {exc}")
