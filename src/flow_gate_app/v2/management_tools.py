from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QColorDialog, QInputDialog


def delete_selected_gate(window):
    gate = window._selected_gate()
    if gate is None:
        window.status_label.setText("Select a saved gate to delete.")
        return
    gate_name = gate["name"]
    window.gates = [item for item in window.gates if item["name"] != gate_name]
    window._refresh_saved_gates(selected_name=None)
    window._refresh_population_combo()
    window._refresh_heatmap_controls()
    window._invalidate_cached_outputs()
    window.redraw()
    window._update_gate_summary()
    window._schedule_heatmap_update()
    window.status_label.setText(f"Deleted gate '{gate_name}'.")


def rename_selected_gate(window):
    gate = window._selected_gate()
    if gate is None:
        window.status_label.setText("Select a saved gate to rename.")
        return
    new_name, ok = QInputDialog.getText(window, "Rename Gate", "New gate name:", text=gate["name"])
    new_name = new_name.strip()
    if not ok or not new_name:
        return
    existing = {item["name"] for item in window.gates if item["name"] != gate["name"]}
    if new_name in existing:
        window.status_label.setText(f"Gate name already exists: {new_name}")
        return
    old_name = gate["name"]
    gate["name"] = new_name
    window._refresh_saved_gates(selected_name=new_name)
    window._refresh_population_combo(selected_name=new_name if window._selected_population_name() == old_name else None)
    window._refresh_heatmap_controls()
    window._invalidate_cached_outputs()
    window.redraw()
    window._update_gate_summary()
    window._schedule_heatmap_update()
    window.status_label.setText(f"Renamed gate '{old_name}' to '{new_name}'.")


def recolor_selected_gate(window):
    gate = window._selected_gate()
    if gate is None:
        window.status_label.setText("Select a saved gate to recolor.")
        return
    color = QColorDialog.getColor(initial=Qt.white, parent=window, title="Choose Gate Color")
    if not color.isValid():
        return
    gate["color"] = color.name()
    window._refresh_saved_gates(selected_name=gate["name"])
    window.redraw()
    window._update_gate_summary()
    window.status_label.setText(f"Updated gate color for {gate['name']}.")


def copy_gate_names(window):
    names = "\n".join(gate["name"] for gate in window.gates)
    QApplication.clipboard().setText(names)
    window.status_label.setText("Copied gate names to clipboard.")


def select_well_from_plate(window, well):
    target_label = next((label for label in window.file_map if label.startswith(f"{well} |")), None)
    if target_label is None:
        window.status_label.setText(f"No FCS file loaded for well {well}.")
        return
    window.well_list.blockSignals(True)
    for idx in range(window.well_list.count()):
        item = window.well_list.item(idx)
        item.setSelected(item.data(Qt.UserRole) == target_label)
    window.well_list.blockSignals(False)
    window._on_well_selection_changed()


def refresh_plate_panel(window):
    selected_wells = set(window._selected_wells())
    available_wells = {label.split(" | ")[0] for label in window.file_map}
    for well, button in window.plate_buttons.items():
        meta = window._metadata_for_well(well)
        sample_name = str(meta.get("sample_name", "")).strip()
        excluded = bool(meta.get("excluded", False))
        has_fcs = well in available_wells
        badge = window._plate_badge_text(sample_name)
        text = badge if badge else well
        if excluded:
            text = f"{text} X"
        button.setText(text)
        tooltip = [well]
        if sample_name:
            tooltip.append(f"Sample: {sample_name}")
        tooltip.append(f"FCS file: {'yes' if has_fcs else 'no'}")
        if excluded:
            tooltip.append("Excluded from downstream analysis")
        button.setToolTip("\n".join(tooltip))
        if excluded:
            bg = "#5a6679"
            fg = "#fff5f5"
            border = "#ffb1b1"
        elif sample_name:
            bg = window._plate_badge_color(sample_name)
            fg = "#f7fbff"
            border = "#eff4fb"
        elif has_fcs:
            bg = "#242c39"
            fg = "#dbe4f1"
            border = "#d5dde9"
        else:
            bg = "#1a1f2b"
            fg = "#617087"
            border = "#515d73"
        selected_style = "border-width: 3px;" if well in selected_wells else "border-width: 1px;"
        button.setStyleSheet(f"background-color: {bg}; color: {fg}; border: 1px solid {border}; {selected_style}")
    assigned = sum(1 for meta in window.plate_metadata.values() if meta.get("sample_name"))
    excluded = sum(1 for meta in window.plate_metadata.values() if meta.get("excluded"))
    window.plate_summary_label.setText(f"FCS wells: {len(available_wells)}    assigned: {assigned}    excluded: {excluded}")


def assign_sample_name_to_selected_wells(window):
    wells = window._selected_wells()
    if not wells:
        window.status_label.setText("Select one or more wells first.")
        return
    sample_name = window.sample_name_edit.text().strip()
    for well in wells:
        meta = dict(window._metadata_for_well(well))
        if sample_name:
            meta["sample_name"] = sample_name
        else:
            meta.pop("sample_name", None)
        window.plate_metadata[well] = meta
    window._invalidate_cached_outputs()
    window._refresh_well_list(selected_labels=window._selected_labels())
    window._refresh_plate_panel()
    window.status_label.setText(f"Updated sample name for {len(wells)} well(s).")


def toggle_exclude_selected_wells(window):
    wells = window._selected_wells()
    if not wells:
        window.status_label.setText("Select one or more wells first.")
        return
    excluded_values = [bool(window._metadata_for_well(well).get("excluded", False)) for well in wells]
    new_value = not all(excluded_values)
    for well in wells:
        meta = dict(window._metadata_for_well(well))
        meta["excluded"] = new_value
        window.plate_metadata[well] = meta
    window._invalidate_cached_outputs()
    window._refresh_well_list(selected_labels=window._selected_labels())
    window._refresh_plate_panel()
    window._schedule_heatmap_update()
    window.status_label.setText(f"{'Excluded' if new_value else 'Included'} {len(wells)} well(s).")


def clear_selected_metadata(window):
    wells = window._selected_wells()
    if not wells:
        window.status_label.setText("Select one or more wells first.")
        return
    for well in wells:
        window.plate_metadata.pop(well, None)
    window.sample_name_edit.setText("")
    window._invalidate_cached_outputs()
    window._refresh_well_list(selected_labels=window._selected_labels())
    window._refresh_plate_panel()
    window._schedule_heatmap_update()
    window.status_label.setText(f"Cleared metadata for {len(wells)} well(s).")
