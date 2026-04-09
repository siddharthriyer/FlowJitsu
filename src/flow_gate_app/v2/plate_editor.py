from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QDialog,
    QDoubleSpinBox,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QPushButton,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QVBoxLayout,
)


def open_plate_map_editor(window):
    if not window.file_map:
        window.status_label.setText("Load a folder first.")
        return
    dialog = QDialog(window)
    dialog.setWindowTitle("Plate Map Editor")
    dialog.resize(1120, 760)
    layout = QVBoxLayout(dialog)
    layout.addWidget(QLabel("Drag across the plate to select groups of wells. Use sample assignment or dose-curve mode on the right."))

    body = QHBoxLayout()
    layout.addLayout(body, stretch=1)

    plate_box = QGroupBox("Plate")
    plate_box.setLayout(QVBoxLayout())
    body.addWidget(plate_box, stretch=3)

    editor_box = QGroupBox("Assignments")
    editor_box.setLayout(QVBoxLayout())
    body.addWidget(editor_box, stretch=2)

    row_names = "ABCDEFGH"
    available_wells = {label.split(" | ")[0] for label in window.file_map}
    table = QTableWidget(8, 12)
    table.setSelectionMode(QAbstractItemView.ExtendedSelection)
    table.setSelectionBehavior(QAbstractItemView.SelectItems)
    table.setHorizontalHeaderLabels([str(idx) for idx in range(1, 13)])
    table.setVerticalHeaderLabels(list(row_names))
    table.horizontalHeader().setDefaultSectionSize(64)
    table.verticalHeader().setDefaultSectionSize(52)
    for row_idx, row_name in enumerate(row_names):
        for col_idx in range(12):
            well = f"{row_name}{col_idx + 1}"
            item = QTableWidgetItem(well)
            item.setTextAlignment(Qt.AlignCenter)
            item.setFlags(Qt.ItemIsSelectable | Qt.ItemIsEnabled)
            item.setData(Qt.UserRole, well)
            table.setItem(row_idx, col_idx, item)
    plate_box.layout().addWidget(table)

    summary_label = QLabel("")
    summary_label.setWordWrap(True)
    plate_box.layout().addWidget(summary_label)

    form = QGridLayout()
    editor_box.layout().addLayout(form)

    assignment_mode_combo = QComboBox()
    assignment_mode_combo.addItems(["sample", "dose_curve"])
    sample_edit = QLineEdit(window.sample_name_edit.text().strip())
    sample_type_combo = QComboBox()
    sample_type_combo.addItems(["sample", "negative_control", "positive_control", ""])
    sample_type_combo.setCurrentText("sample")

    form.addWidget(QLabel("Assignment Type"), 0, 0)
    form.addWidget(assignment_mode_combo, 0, 1)
    form.addWidget(QLabel("Sample Name"), 1, 0)
    form.addWidget(sample_edit, 1, 1)
    form.addWidget(QLabel("Sample Type"), 2, 0)
    form.addWidget(sample_type_combo, 2, 1)

    button_row = QHBoxLayout()
    apply_button = QPushButton("Apply Sample")
    toggle_button = QPushButton("Toggle Exclude")
    clear_button = QPushButton("Delete Wells")
    button_row.addWidget(apply_button)
    button_row.addWidget(toggle_button)
    button_row.addWidget(clear_button)
    editor_box.layout().addLayout(button_row)

    sample_manager = QGroupBox("Sample Manager")
    sample_manager.setLayout(QVBoxLayout())
    editor_box.layout().addWidget(sample_manager)
    sample_list = QListWidget()
    sample_manager.layout().addWidget(sample_list)
    sample_action_row = QHBoxLayout()
    extend_button = QPushButton("Extend To Selection")
    delete_sample_button = QPushButton("Delete Sample")
    sample_action_row.addWidget(extend_button)
    sample_action_row.addWidget(delete_sample_button)
    sample_manager.layout().addLayout(sample_action_row)

    dose_box = QGroupBox("Dose Curve Parameters")
    dose_box.setLayout(QGridLayout())
    editor_box.layout().addWidget(dose_box)
    direction_combo = QComboBox()
    direction_combo.addItems(["horizontal", "vertical"])
    dose_mode_combo = QComboBox()
    dose_mode_combo.addItems(["dilution_series", "manual_list"])
    points_spin = QSpinBox()
    points_spin.setRange(1, 24)
    points_spin.setValue(4)
    top_dose_spin = QDoubleSpinBox()
    top_dose_spin.setRange(0.0, 1_000_000.0)
    top_dose_spin.setDecimals(4)
    top_dose_spin.setValue(50.0)
    dilution_spin = QDoubleSpinBox()
    dilution_spin.setRange(0.0001, 1_000_000.0)
    dilution_spin.setDecimals(4)
    dilution_spin.setValue(2.0)
    manual_dose_edit = QLineEdit("")
    manual_dose_edit.setPlaceholderText("e.g. 50, 10, 2, 0.4")
    dose_box.layout().addWidget(QLabel("Direction"), 0, 0)
    dose_box.layout().addWidget(direction_combo, 0, 1)
    dose_box.layout().addWidget(QLabel("Dose Entry"), 1, 0)
    dose_box.layout().addWidget(dose_mode_combo, 1, 1)
    dose_box.layout().addWidget(QLabel("Points"), 2, 0)
    dose_box.layout().addWidget(points_spin, 2, 1)
    top_dose_label = QLabel("Top Dose")
    dose_box.layout().addWidget(top_dose_label, 3, 0)
    dose_box.layout().addWidget(top_dose_spin, 3, 1)
    dilution_label = QLabel("Dilution")
    dose_box.layout().addWidget(dilution_label, 4, 0)
    dose_box.layout().addWidget(dilution_spin, 4, 1)
    manual_dose_label = QLabel("Manual Doses")
    dose_box.layout().addWidget(manual_dose_label, 5, 0)
    dose_box.layout().addWidget(manual_dose_edit, 5, 1)
    export_button = QPushButton("Export Plate CSV")
    export_button.clicked.connect(window.export_plate_metadata_csv)
    dose_box.layout().addWidget(export_button, 6, 0, 1, 2)

    curve_box = QGroupBox("Current Dose Curves")
    curve_box.setLayout(QVBoxLayout())
    editor_box.layout().addWidget(curve_box, stretch=1)
    curve_text = QTextEdit()
    curve_text.setReadOnly(True)
    curve_box.layout().addWidget(curve_text)

    info_label = QLabel("")
    info_label.setWordWrap(True)
    editor_box.layout().addWidget(info_label)
    editor_box.layout().addStretch(1)

    close_row = QHBoxLayout()
    close_row.addStretch(1)
    close_button = QPushButton("Close")
    close_button.clicked.connect(dialog.close)
    close_row.addWidget(close_button)
    layout.addLayout(close_row)

    def _selected_wells_from_table():
        wells = {item.data(Qt.UserRole) for item in table.selectedItems() if item is not None}
        return sorted(wells, key=lambda well: (well[0], int(well[1:])))

    def _set_main_well_selection(wells, schedule_plot=True):
        target_labels = {label for label in window.file_map if label.split(" | ")[0] in set(wells)}
        window.well_list.blockSignals(True)
        for idx in range(window.well_list.count()):
            item = window.well_list.item(idx)
            item.setSelected(item.data(Qt.UserRole) in target_labels)
        window.well_list.blockSignals(False)
        window._refresh_channel_controls()
        window._refresh_plate_panel()
        if len(wells) == 1:
            window.sample_name_edit.setText(str(window._metadata_for_well(wells[0]).get("sample_name", "")))
        elif not wells:
            window.sample_name_edit.setText("")
        if schedule_plot:
            window._schedule_plot_update()

    def _sample_names_in_use():
        return sorted({
            str(meta.get("sample_name", "")).strip()
            for meta in window.plate_metadata.values()
            if str(meta.get("sample_name", "")).strip()
        })

    def _rebuild_dose_curve_definitions():
        rebuilt = {}
        grouped = {}
        for well, meta in window.plate_metadata.items():
            sample_name = str(meta.get("sample_name", "")).strip()
            curve_name = str(meta.get("dose_curve", "")).strip()
            if not sample_name or not curve_name:
                continue
            grouped.setdefault(curve_name, []).append((well, meta))
        for curve_name, items in grouped.items():
            wells = sorted([well for well, _meta in items], key=lambda well: (well[0], int(well[1:])))
            first_meta = items[0][1]
            doses = []
            for _well, meta in items:
                try:
                    doses.append(float(meta.get("dose", "")))
                except Exception:
                    continue
            top_dose = max(doses) if doses else ""
            dilution = ""
            if len(doses) >= 2:
                ordered = sorted([dose for dose in doses if dose > 0], reverse=True)
                if len(ordered) >= 2 and ordered[1] > 0:
                    dilution = ordered[0] / ordered[1]
            rebuilt[curve_name] = {
                "sample_name": str(first_meta.get("sample_name", "")).strip(),
                "direction": first_meta.get("dose_direction", ""),
                "points": len(wells),
                "top_dose": top_dose,
                "dilution": dilution,
                "wells": wells,
            }
        return rebuilt

    def _refresh_curve_panel():
        definitions = _rebuild_dose_curve_definitions()
        if not definitions:
            curve_text.setPlainText("No dose curves assigned yet.")
            return
        blocks = []
        for key, definition in sorted(definitions.items()):
            wells_text = ", ".join(definition["wells"])
            blocks.append(
                f"{key}\n"
                f"  direction: {definition['direction']}\n"
                f"  points: {definition['points']}\n"
                f"  top dose: {definition['top_dose']}\n"
                f"  dilution: {definition['dilution']}\n"
                f"  wells: {wells_text}"
            )
        curve_text.setPlainText("\n\n".join(blocks))

    def _refresh_sample_panel():
        current = sample_list.currentItem().text() if sample_list.currentItem() else ""
        names = _sample_names_in_use()
        sample_list.blockSignals(True)
        sample_list.clear()
        for name in names:
            sample_list.addItem(name)
        if current in names:
            matches = sample_list.findItems(current, Qt.MatchExactly)
            if matches:
                sample_list.setCurrentItem(matches[0])
        sample_list.blockSignals(False)

    def _selected_sample_name():
        item = sample_list.currentItem()
        return item.text().strip() if item is not None else ""

    def _refresh_dialog():
        selected_wells = set(_selected_wells_from_table())
        active_sample = _selected_sample_name()
        for row_idx, row_name in enumerate(row_names):
            for col_idx in range(12):
                well = f"{row_name}{col_idx + 1}"
                item = table.item(row_idx, col_idx)
                meta = window._metadata_for_well(well)
                sample_name = str(meta.get("sample_name", "")).strip()
                excluded = bool(meta.get("excluded", False))
                has_fcs = well in available_wells
                if active_sample and sample_name == active_sample:
                    bg = QColor("#ffd166" if well not in selected_wells else "#f6bd60")
                    fg = QColor("#111111")
                elif excluded:
                    bg = QColor("#d9d9d9")
                    fg = QColor("#111111")
                elif sample_name:
                    bg = QColor(window._plate_badge_color(sample_name))
                    fg = QColor("#f7fbff")
                elif has_fcs:
                    bg = QColor("#ffffff")
                    fg = QColor("#111111")
                else:
                    bg = QColor("#f3f3f3")
                    fg = QColor("#7a7a7a")
                item.setBackground(bg)
                item.setForeground(fg)
                tooltip = [
                    f"Well: {well}",
                    f"Sample: {sample_name or ''}",
                    f"Sample type: {meta.get('sample_type', '')}",
                    f"Dose curve: {meta.get('dose_curve', '')}",
                    f"Dose: {meta.get('dose', '')}",
                    f"Replicate: {meta.get('replicate', '')}",
                    f"Direction: {meta.get('dose_direction', '')}",
                    f"Excluded: {excluded}",
                    f"FCS file: {'yes' if has_fcs else 'no'}",
                ]
                item.setToolTip("\n".join(tooltip))
        wells = _selected_wells_from_table()
        if wells:
            first_meta = window._metadata_for_well(wells[0])
            sample_edit.setText(str(first_meta.get("sample_name", "")).strip())
            sample_type_combo.setCurrentText(str(first_meta.get("sample_type", "sample")).strip() or "sample")
        summary_label.setText(f"Selected wells ({len(wells)}): {', '.join(wells) if wells else 'none'}")
        info_label.setText(
            "Click or drag across wells to select them. "
            "Use Sample Manager to highlight an assigned sample across the plate."
        )
        _refresh_sample_panel()
        _refresh_curve_panel()

    def _apply_sample():
        wells = _selected_wells_from_table()
        if not wells:
            info_label.setText("No wells selected.")
            return
        sample_name = sample_edit.text().strip()
        sample_type = sample_type_combo.currentText().strip()
        for well in wells:
            meta = dict(window._metadata_for_well(well))
            if sample_name:
                meta["sample_name"] = sample_name
                meta["sample_type"] = sample_type
            else:
                for field in ("sample_name", "sample_type", "dose_curve", "dose", "replicate", "dose_direction"):
                    meta.pop(field, None)
            window.plate_metadata[well] = meta
        _set_main_well_selection(wells)
        window.sample_name_edit.setText(sample_name)
        window._invalidate_cached_outputs()
        window._schedule_heatmap_update()
        info_label.setText(f"Applied sample metadata to {len(wells)} wells.")
        _refresh_dialog()

    def _apply_dose_curve():
        wells = _selected_wells_from_table()
        if not wells:
            info_label.setText("No wells selected.")
            return
        sample_name = sample_edit.text().strip()
        sample_type = sample_type_combo.currentText().strip()
        if not sample_name:
            info_label.setText("Enter a sample name first.")
            return
        direction = direction_combo.currentText().strip().lower()
        dose_mode = dose_mode_combo.currentText().strip()
        manual_doses = []
        if dose_mode == "manual_list":
            raw = manual_dose_edit.text().strip()
            if not raw:
                info_label.setText("Enter one or more manual doses first.")
                return
            try:
                manual_doses = [
                    float(token)
                    for token in raw.replace("\n", ",").replace(";", ",").split(",")
                    if token.strip()
                ]
            except Exception:
                info_label.setText("Manual doses must be numeric values separated by commas.")
                return
            if not manual_doses:
                info_label.setText("Enter one or more manual doses first.")
                return
            n_points = len(manual_doses)
            top_dose = max(manual_doses)
            dilution = ""
        else:
            n_points = max(int(points_spin.value()), 1)
            top_dose = float(top_dose_spin.value())
            dilution = float(dilution_spin.value())
        grouped = {}
        for well in wells:
            row = well[0]
            col = int(well[1:])
            key = row if direction == "horizontal" else col
            grouped.setdefault(key, []).append(well)
        sorted_groups = []
        for key, group_wells in grouped.items():
            if direction == "horizontal":
                ordered = sorted(group_wells, key=lambda well: int(well[1:]))
            else:
                ordered = sorted(group_wells, key=lambda well: well[0])
            sorted_groups.append((key, ordered))
        sorted_groups.sort(key=lambda item: item[0])
        for replicate_idx, (_key, group_wells) in enumerate(sorted_groups, start=1):
            for point_idx, well in enumerate(group_wells[:n_points]):
                dose_value = manual_doses[point_idx] if dose_mode == "manual_list" else top_dose / (dilution ** point_idx)
                meta = dict(window._metadata_for_well(well))
                meta["sample_name"] = sample_name
                meta["sample_type"] = sample_type
                meta["dose_curve"] = sample_name
                meta["dose"] = dose_value
                meta["replicate"] = replicate_idx
                meta["dose_direction"] = direction
                window.plate_metadata[well] = meta
        _set_main_well_selection(wells)
        window.sample_name_edit.setText(sample_name)
        window._invalidate_cached_outputs()
        window._schedule_heatmap_update()
        info_label.setText(
            f"Assigned dose curve '{sample_name}' across {len(wells)} wells using "
            f"{'manual doses' if dose_mode == 'manual_list' else 'a dilution series'}."
        )
        _refresh_dialog()

    def _apply_assignment():
        if assignment_mode_combo.currentText() == "dose_curve":
            _apply_dose_curve()
        else:
            _apply_sample()

    def _toggle_exclude():
        wells = _selected_wells_from_table()
        if not wells:
            info_label.setText("No wells selected.")
            return
        excluded_values = [bool(window._metadata_for_well(well).get("excluded", False)) for well in wells]
        new_value = not all(excluded_values)
        for well in wells:
            meta = dict(window._metadata_for_well(well))
            meta["excluded"] = new_value
            window.plate_metadata[well] = meta
        _set_main_well_selection(wells, schedule_plot=False)
        window._invalidate_cached_outputs()
        window._schedule_heatmap_update()
        info_label.setText(f"{'Excluded' if new_value else 'Included'} {len(wells)} wells.")
        window._schedule_plot_update()
        _refresh_dialog()

    def _clear_selected():
        wells = _selected_wells_from_table()
        if not wells:
            info_label.setText("No wells selected.")
            return
        for well in wells:
            window.plate_metadata.pop(well, None)
        _set_main_well_selection(wells)
        window._invalidate_cached_outputs()
        window._schedule_heatmap_update()
        info_label.setText(f"Cleared metadata for {len(wells)} wells.")
        _refresh_dialog()

    def _on_sample_selected():
        sample_name = _selected_sample_name()
        if not sample_name:
            _refresh_dialog()
            return
        wells = sorted(
            [well for well, meta in window.plate_metadata.items() if str(meta.get("sample_name", "")).strip() == sample_name],
            key=lambda well: (well[0], int(well[1:])),
        )
        table.blockSignals(True)
        table.clearSelection()
        for well in wells:
            row_idx = ord(well[0]) - 65
            col_idx = int(well[1:]) - 1
            item = table.item(row_idx, col_idx)
            if item is not None:
                item.setSelected(True)
        table.blockSignals(False)
        _set_main_well_selection(wells)
        _refresh_dialog()

    def _extend_selected_sample():
        sample_name = _selected_sample_name()
        wells = _selected_wells_from_table()
        if not sample_name:
            info_label.setText("Select a sample first.")
            return
        if not wells:
            info_label.setText("Select wells to extend the sample into.")
            return
        source_wells = sorted(
            [well for well, meta in window.plate_metadata.items() if str(meta.get("sample_name", "")).strip() == sample_name],
            key=lambda well: (well[0], int(well[1:])),
        )
        source_meta = window._metadata_for_well(source_wells[0]) if source_wells else {}
        for well in wells:
            meta = dict(window._metadata_for_well(well))
            meta["sample_name"] = sample_name
            meta["sample_type"] = str(source_meta.get("sample_type", sample_type_combo.currentText().strip() or "sample")).strip()
            window.plate_metadata[well] = meta
        _set_main_well_selection(wells, schedule_plot=False)
        window._invalidate_cached_outputs()
        window._schedule_heatmap_update()
        info_label.setText(f"Extended sample '{sample_name}' into {len(wells)} wells.")
        window._schedule_plot_update()
        _refresh_dialog()

    def _delete_selected_sample():
        sample_name = _selected_sample_name()
        if not sample_name:
            info_label.setText("Select a sample first.")
            return
        wells = [
            well for well, meta in window.plate_metadata.items()
            if str(meta.get("sample_name", "")).strip() == sample_name
        ]
        if not wells:
            info_label.setText(f"No wells found for sample '{sample_name}'.")
            return
        for well in wells:
            meta = dict(window._metadata_for_well(well))
            for field in ("sample_name", "sample_type", "dose_curve", "dose", "replicate", "dose_direction"):
                meta.pop(field, None)
            window.plate_metadata[well] = meta
        _set_main_well_selection(wells, schedule_plot=False)
        window._invalidate_cached_outputs()
        window._schedule_heatmap_update()
        info_label.setText(f"Deleted sample '{sample_name}' from {len(wells)} wells.")
        window._schedule_plot_update()
        _refresh_dialog()

    def _update_assignment_mode():
        is_dose_curve = assignment_mode_combo.currentText() == "dose_curve"
        dose_box.setVisible(is_dose_curve)
        apply_button.setText("Apply Sample And Dose Curve" if is_dose_curve else "Apply Sample")

    def _update_dose_mode():
        is_manual = dose_mode_combo.currentText() == "manual_list"
        top_dose_label.setVisible(not is_manual)
        top_dose_spin.setVisible(not is_manual)
        dilution_label.setVisible(not is_manual)
        dilution_spin.setVisible(not is_manual)
        manual_dose_label.setVisible(is_manual)
        manual_dose_edit.setVisible(is_manual)
        points_spin.setEnabled(not is_manual)

    table.itemSelectionChanged.connect(_refresh_dialog)
    apply_button.clicked.connect(_apply_assignment)
    toggle_button.clicked.connect(_toggle_exclude)
    clear_button.clicked.connect(_clear_selected)
    sample_list.itemSelectionChanged.connect(_on_sample_selected)
    extend_button.clicked.connect(_extend_selected_sample)
    delete_sample_button.clicked.connect(_delete_selected_sample)
    assignment_mode_combo.currentIndexChanged.connect(_update_assignment_mode)
    dose_mode_combo.currentIndexChanged.connect(_update_dose_mode)
    dialog.finished.connect(lambda _result: (window._refresh_plate_panel(), window._refresh_well_list(selected_labels=window._selected_labels())))
    _update_assignment_mode()
    _update_dose_mode()
    _refresh_dialog()
    dialog.exec()
