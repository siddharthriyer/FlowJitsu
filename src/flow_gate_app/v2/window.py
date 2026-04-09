import os
import sys

import matplotlib
import pandas as pd

matplotlib.use("QtAgg")

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication, QListWidget, QMainWindow

from .._app_version import __version__
from ..helpers import APP_BRAND, flow_tools as _flow_tools
from .compensation_dialog import open_compensation_editor as _open_compensation_editor
from .data_runtime import (
    apply_compensation as _apply_compensation_impl,
    browse_folder as _browse_folder_impl,
    compensation_payload as _compensation_payload_impl,
    current_histogram_ymax as _current_histogram_ymax_impl,
    default_compensation_mapping as _default_compensation_mapping_impl,
    display_dataframe as _display_dataframe_impl,
    downsample as _downsample_impl,
    effective_histogram_axis_limits as _effective_histogram_axis_limits_impl,
    effective_scatter_axis_limits as _effective_scatter_axis_limits_impl,
    extract_compensation_from_sample_meta as _extract_compensation_from_sample_meta_impl,
    fluorescence_channels as _fluorescence_channels_impl,
    global_histogram_axis_extent as _global_histogram_axis_extent_impl,
    global_scatter_axis_extent as _global_scatter_axis_extent_impl,
    hist_axis_override_key as _hist_axis_override_key_impl,
    hist_bins as _hist_bins_impl,
    histogram_mode as _histogram_mode_impl,
    invalidate_cached_outputs as _invalidate_cached_outputs_impl,
    load_compensation_payload as _load_compensation_payload_impl,
    load_folder as _load_folder_impl,
    load_sample as _load_sample_impl,
    median_histogram_axis_limits as _median_histogram_axis_limits_impl,
    median_scatter_axis_limits as _median_scatter_axis_limits_impl,
    metadata_for_well as _metadata_for_well_impl,
    normalize_channel_token as _normalize_channel_token_impl,
    parse_compensation_text as _parse_compensation_text_impl,
    parse_spill_string as _parse_spill_string_impl,
    plate_badge_color as _plate_badge_color_impl,
    plate_badge_text as _plate_badge_text_impl,
    plot_selection_title as _plot_selection_title_impl,
    plot_x_cofactor as _plot_x_cofactor_impl,
    plot_x_transform as _plot_x_transform_impl,
    plot_y_cofactor as _plot_y_cofactor_impl,
    plot_y_transform as _plot_y_transform_impl,
    population_display_label as _population_display_label_impl,
    population_lineage as _population_lineage_impl,
    population_mask as _population_mask_impl,
    population_raw_dataframe as _population_raw_dataframe_impl,
    rectangle_vertices as _rectangle_vertices_impl,
    refresh_channel_controls as _refresh_channel_controls_impl,
    refresh_population_combo as _refresh_population_combo_impl,
    refresh_well_list as _refresh_well_list_impl,
    sample_population_raw_dataframe as _sample_population_raw_dataframe_impl,
    sample_population_transformed_dataframe as _sample_population_transformed_dataframe_impl,
    sample_raw_dataframe as _sample_raw_dataframe_impl,
    scatter_x_axis_override_key as _scatter_x_axis_override_key_impl,
    scatter_y_axis_override_key as _scatter_y_axis_override_key_impl,
    selected_labels as _selected_labels_impl,
    selected_labels_key as _selected_labels_key_impl,
    selected_population_name as _selected_population_name_impl,
    selected_raw_dataframe as _selected_raw_dataframe_impl,
    selected_wells as _selected_wells_impl,
    union_channel_names as _union_channel_names_impl,
    update_compensation_status as _update_compensation_status_impl,
    visible_gate as _visible_gate_impl,
    well_item_display_text as _well_item_display_text_impl,
)
from .export_tools import (
    analysis_bundle_paths as _analysis_bundle_paths_impl,
    create_analysis_notebook as _create_analysis_notebook_impl,
    export_gate_summary_csv as _export_gate_summary_csv_impl,
    export_html_report as _export_html_report_impl,
    export_intensity_csv as _export_intensity_csv_impl,
    export_plate_metadata_csv as _export_plate_metadata_csv_impl,
    intensity_distribution_dataframe as _intensity_distribution_dataframe_impl,
    open_analysis_preview as _open_analysis_preview_impl,
    plate_metadata_dataframe as _plate_metadata_dataframe_impl,
    summary_dataframe as _summary_dataframe_impl,
    write_analysis_bundle_csvs as _write_analysis_bundle_csvs_impl,
)
from .interaction_tools import (
    clear_pending as _clear_pending,
    clear_plot as _clear_plot_impl,
    disconnect_drawing as _disconnect_drawing_impl,
    enable_saved_gate_interaction as _enable_saved_gate_interaction_impl,
    gate_fraction as _gate_fraction_impl,
    gate_fraction_for_label as _gate_fraction_for_label_impl,
    gate_hit_test as _gate_hit_test_impl,
    gate_label as _gate_label_impl,
    on_drag_motion as _on_drag_motion_impl,
    on_drag_press as _on_drag_press_impl,
    on_drag_release as _on_drag_release_impl,
    on_horizontal_click as _on_horizontal_click_impl,
    on_horizontal_motion as _on_horizontal_motion_impl,
    on_polygon_click as _on_polygon_click_impl,
    on_polygon_motion as _on_polygon_motion_impl,
    on_quad_click as _on_quad_click_impl,
    on_quad_motion as _on_quad_motion_impl,
    on_rectangle_click as _on_rectangle_click_impl,
    on_rectangle_motion as _on_rectangle_motion_impl,
    on_saved_gate_selected as _on_saved_gate_selected_impl,
    on_vertical_click as _on_vertical_click_impl,
    on_vertical_motion as _on_vertical_motion_impl,
    on_zoom_box_click as _on_zoom_box_click_impl,
    on_zoom_box_motion as _on_zoom_box_motion_impl,
    pending_to_gate_spec as _pending_to_gate_spec_impl,
    plot_population as _plot_population_impl,
    redraw as _redraw_impl,
    refresh_saved_gates as _refresh_saved_gates_impl,
    reset_zoom as _reset_zoom_impl,
    save_gate as _save_gate_impl,
    selected_gate as _selected_gate_impl,
    start_drawing as _start_drawing_impl,
    start_edit_selected_gate as _start_edit_selected_gate_impl,
    start_move_selected_gate as _start_move_selected_gate_impl,
    start_zoom_box as _start_zoom_box_impl,
    update_gate_summary as _update_gate_summary_impl,
)
from .management_tools import (
    assign_sample_name_to_selected_wells as _assign_sample_name_to_selected_wells_impl,
    clear_selected_metadata as _clear_selected_metadata_impl,
    copy_gate_names as _copy_gate_names_impl,
    delete_selected_gate as _delete_selected_gate_impl,
    recolor_selected_gate as _recolor_selected_gate_impl,
    refresh_plate_panel as _refresh_plate_panel_impl,
    rename_selected_gate as _rename_selected_gate_impl,
    select_well_from_plate as _select_well_from_plate_impl,
    toggle_exclude_selected_wells as _toggle_exclude_selected_wells_impl,
)
from .plate_editor import open_plate_map_editor as _open_plate_map_editor
from .plot_tools import open_graph_options_dialog as _open_graph_options_dialog, update_heatmap as _update_heatmap_impl
from .session_runtime import (
    app_home as _app_home,
    apply_session_payload as _apply_session_payload_impl,
    autoload_last_session_or_folder as _autoload_last_session_or_folder_impl,
    close_event as _close_event,
    default_export_dir as _default_export_dir,
    last_session_path as _last_session_path,
    load_recent_session as _load_recent_session_impl,
    load_session as _load_session_impl,
    load_settings as _load_settings_impl,
    recent_sessions as _recent_sessions_impl,
    refresh_recent_sessions as _refresh_recent_sessions_impl,
    remember_recent_session as _remember_recent_session_impl,
    save_session as _save_session_impl,
    save_settings as _save_settings_impl,
    session_dir as _session_dir,
    settings_path as _settings_path,
)
from .update_service import check_for_updates as _check_for_updates, latest_release_info as _latest_release_info
from .ui_layout import build_ui as _build_ui_impl, placeholder_frame as _placeholder_frame_impl, section as _section_impl
from .window_glue import (
    annotate_heatmap_cells as _annotate_heatmap_cells_impl,
    gate_template_payload as _gate_template_payload_impl,
    key_press_event as _key_press_event_impl,
    load_gate_template as _load_gate_template_impl,
    on_auto_plot_mode_changed as _on_auto_plot_mode_changed_impl,
    on_channel_changed as _on_channel_changed_impl,
    on_gate_type_changed as _on_gate_type_changed_impl,
    on_population_changed as _on_population_changed_impl,
    on_well_selection_changed as _on_well_selection_changed_impl,
    refresh_heatmap_controls as _refresh_heatmap_controls_impl,
    save_gate_template as _save_gate_template_impl,
    schedule_heatmap_update as _schedule_heatmap_update_impl,
    schedule_plot_update as _schedule_plot_update_impl,
    schedule_redraw as _schedule_redraw_impl,
    session_payload as _session_payload_impl,
    trigger_auto_plot as _trigger_auto_plot_impl,
)


ROBUST_AXIS_LOWER_Q = 0.01
ROBUST_AXIS_UPPER_Q = 0.99


class NonSelectingWheelListWidget(QListWidget):
    def wheelEvent(self, event):
        selected_rows = [self.row(item) for item in self.selectedItems()]
        current_row = self.currentRow()
        super().wheelEvent(event)
        self.blockSignals(True)
        self.clearSelection()
        for row in selected_rows:
            item = self.item(row)
            if item is not None:
                item.setSelected(True)
        if current_row >= 0:
            current_item = self.item(current_row)
            if current_item is not None:
                self.setCurrentItem(current_item)
        self.blockSignals(False)


class FlowDesktopQtWindow(QMainWindow):
    def __init__(self, base_dir=None, instrument="Cytoflex", max_points=15000):
        super().__init__()
        self.base_dir = base_dir or os.getcwd()
        self.file_map = {}
        self.channel_names_by_label = {}
        self.channel_names = []
        self.sample_cache = {}
        self._sample_raw_cache = {}
        self._selected_raw_cache = {}
        self._population_raw_cache = {}
        self._sample_population_cache = {}
        self._sample_population_transform_cache = {}
        self._display_cache = {}
        self.compensation_enabled = False
        self.compensation_source_channels = []
        self.compensation_channels = []
        self.compensation_matrix = None
        self.compensation_text = ""
        self.plate_metadata = {}
        self.plate_buttons = {}
        self.population_labels = {"All Events": "__all__"}
        self.current_data = pd.DataFrame()
        self.current_transformed = pd.DataFrame()
        self.gates = []
        self.pending_gate = None
        self.saved_gate_lookup = {}
        self.selected_gate_name = None
        self._summary_cache = None
        self._intensity_cache = None
        self.rectangle_start_point = None
        self.rectangle_current_point = None
        self.zoom_start_point = None
        self.zoom_current_point = None
        self.vertical_preview_x = None
        self.horizontal_preview_y = None
        self.quad_preview_point = None
        self.polygon_vertices = []
        self.polygon_cursor_point = None
        self.canvas_click_cid = None
        self.canvas_motion_cid = None
        self.canvas_release_cid = None
        self.canvas_press_drag_cid = None
        self.scatter_x_axis_overrides = {}
        self.scatter_y_axis_overrides = {}
        self.hist_axis_overrides = {}
        self.edit_gate_mode = False
        self.translate_gate_mode = False
        self.drag_state = None
        self._suspend_auto_plot = False
        self.auto_plot_enabled = True
        self._gate_group_counter = 0
        self._heatmap_update_pending = False
        self._heatmap_timer = QTimer(self)
        self._heatmap_timer.setSingleShot(True)
        self._heatmap_timer.timeout.connect(self._update_heatmap)
        self._redraw_timer = QTimer(self)
        self._redraw_timer.setSingleShot(True)
        self._redraw_timer.timeout.connect(self.redraw)
        self._plot_timer = QTimer(self)
        self._plot_timer.setSingleShot(True)
        self._plot_timer.timeout.connect(self.plot_population)
        self.current_session_path = None

        self.setWindowTitle(f"{APP_BRAND} v{__version__} [Qt Preview]")
        self.resize(1640, 940)
        self._build_ui(instrument=instrument, max_points=max_points)
        self.hex_size_label.setVisible(False)
        self.hex_size_spin.setVisible(False)
        self._update_compensation_status()
        self._autoload_last_session_or_folder(base_dir)

    def _app_version_text(self):
        return __version__

    def _flow_measurement_class(self):
        return _flow_tools()["FCMeasurement"]

    def _robust_axis_lower_q(self):
        return ROBUST_AXIS_LOWER_Q

    def _robust_axis_upper_q(self):
        return ROBUST_AXIS_UPPER_Q

    def _section(self, title):
        return _section_impl(title)

    def _build_ui(self, instrument, max_points):
        return _build_ui_impl(self, instrument, max_points, NonSelectingWheelListWidget)

    def _placeholder_frame(self, text):
        return _placeholder_frame_impl(text)

    def _browse_folder(self):
        return _browse_folder_impl(self)

    def _load_sample(self, relpath):
        return _load_sample_impl(self, relpath)

    def _update_compensation_status(self):
        return _update_compensation_status_impl(self)

    def _compensation_payload(self):
        return _compensation_payload_impl(self)

    def _load_compensation_payload(self, payload):
        return _load_compensation_payload_impl(self, payload)

    def _parse_compensation_text(self, text):
        return _parse_compensation_text_impl(self, text)

    def _parse_spill_string(self, raw_value):
        return _parse_spill_string_impl(self, raw_value)

    def _extract_compensation_from_sample_meta(self, sample):
        return _extract_compensation_from_sample_meta_impl(self, sample)

    def _normalize_channel_token(self, value):
        return _normalize_channel_token_impl(self, value)

    def _default_compensation_mapping(self, source_channels):
        return _default_compensation_mapping_impl(self, source_channels)

    def _apply_compensation(self, df):
        return _apply_compensation_impl(self, df)

    def open_compensation_editor(self):
        return _open_compensation_editor(self)

    def _union_channel_names(self, channel_lists):
        return _union_channel_names_impl(self, channel_lists)

    def _selected_labels(self):
        return _selected_labels_impl(self)

    def _metadata_for_well(self, well):
        return _metadata_for_well_impl(self, well)

    def _well_item_display_text(self, label):
        return _well_item_display_text_impl(self, label)

    def _selected_wells(self):
        return _selected_wells_impl(self)

    def _refresh_well_list(self, selected_labels=None):
        return _refresh_well_list_impl(self, selected_labels=selected_labels)

    def _plate_badge_text(self, sample_name):
        return _plate_badge_text_impl(self, sample_name)

    def _plate_badge_color(self, sample_name):
        return _plate_badge_color_impl(self, sample_name)

    def _plot_x_transform(self):
        return _plot_x_transform_impl(self)

    def _plot_x_cofactor(self):
        return _plot_x_cofactor_impl(self)

    def _plot_y_transform(self):
        return _plot_y_transform_impl(self)

    def _plot_y_cofactor(self):
        return _plot_y_cofactor_impl(self)

    def _refresh_channel_controls(self):
        return _refresh_channel_controls_impl(self)

    def load_folder(self):
        return _load_folder_impl(self)

    def _sample_raw_dataframe(self, label):
        return _sample_raw_dataframe_impl(self, label)

    def _selected_labels_key(self):
        return _selected_labels_key_impl(self)

    def _selected_raw_dataframe(self):
        return _selected_raw_dataframe_impl(self)

    def _display_dataframe(self):
        return _display_dataframe_impl(self)

    def _population_mask(self, raw_df, gate):
        return _population_mask_impl(self, raw_df, gate)

    def _invalidate_cached_outputs(self):
        return _invalidate_cached_outputs_impl(self)

    def _downsample(self, transformed):
        return _downsample_impl(self, transformed)

    def _plot_selection_title(self):
        return _plot_selection_title_impl(self)

    def _population_display_label(self):
        return _population_display_label_impl(self)

    def _selected_population_name(self):
        return _selected_population_name_impl(self)

    def _population_lineage(self, name):
        return _population_lineage_impl(self, name)

    def _refresh_population_combo(self, selected_name=None):
        return _refresh_population_combo_impl(self, selected_name=selected_name)

    def _fluorescence_channels(self):
        return _fluorescence_channels_impl(self)

    def _scatter_x_axis_override_key(self):
        return _scatter_x_axis_override_key_impl(self)

    def _scatter_y_axis_override_key(self):
        return _scatter_y_axis_override_key_impl(self)

    def _hist_axis_override_key(self):
        return _hist_axis_override_key_impl(self)

    def _histogram_mode(self):
        return _histogram_mode_impl(self)

    def _hist_bins(self):
        return _hist_bins_impl(self)

    def _sample_population_raw_dataframe(self, label, population_name):
        return _sample_population_raw_dataframe_impl(self, label, population_name)

    def _population_raw_dataframe(self, population_name):
        return _population_raw_dataframe_impl(self, population_name)

    def _sample_population_transformed_dataframe(
        self,
        label,
        population_name,
        x_channel,
        y_channel,
        x_method,
        x_cofactor,
        y_method="arcsinh",
        y_cofactor=150.0,
    ):
        return _sample_population_transformed_dataframe_impl(
            self,
            label,
            population_name,
            x_channel,
            y_channel,
            x_method,
            x_cofactor,
            y_method=y_method,
            y_cofactor=y_cofactor,
        )

    def _median_scatter_axis_limits(self):
        return _median_scatter_axis_limits_impl(self)

    def _global_scatter_axis_extent(self):
        return _global_scatter_axis_extent_impl(self)

    def _rectangle_vertices(self, start_x, start_y, end_x, end_y):
        return _rectangle_vertices_impl(self, start_x, start_y, end_x, end_y)

    def _effective_scatter_axis_limits(self):
        return _effective_scatter_axis_limits_impl(self)

    def _effective_histogram_axis_limits(self, transformed=None):
        return _effective_histogram_axis_limits_impl(self, transformed=transformed)

    def _current_histogram_ymax(self, transformed=None, x_limits=None):
        return _current_histogram_ymax_impl(self, transformed=transformed, x_limits=x_limits)

    def _median_histogram_axis_limits(self, transformed=None):
        return _median_histogram_axis_limits_impl(self, transformed=transformed)

    def _global_histogram_axis_extent(self):
        return _global_histogram_axis_extent_impl(self)

    def _visible_gate(self, gate):
        return _visible_gate_impl(self, gate)

    def redraw(self):
        return _redraw_impl(self)

    def plot_population(self):
        return _plot_population_impl(self)

    def _pending_to_gate_spec(self, preview=False):
        return _pending_to_gate_spec_impl(self, preview=preview)

    def start_drawing(self):
        return _start_drawing_impl(self)

    def clear_pending(self):
        return _clear_pending(self)

    def save_gate(self):
        return _save_gate_impl(self)

    def _refresh_saved_gates(self, selected_name=None):
        return _refresh_saved_gates_impl(self, selected_name=selected_name)

    def _gate_label(self, gate):
        return _gate_label_impl(self, gate)

    def _on_saved_gate_selected(self):
        return _on_saved_gate_selected_impl(self)

    def _selected_gate(self):
        return _selected_gate_impl(self)

    def _gate_fraction(self, gate):
        return _gate_fraction_impl(self, gate)

    def _update_gate_summary(self):
        return _update_gate_summary_impl(self)

    def _gate_fraction_for_label(self, gate, label):
        return _gate_fraction_for_label_impl(self, gate, label)

    def _on_rectangle_click(self, event):
        return _on_rectangle_click_impl(self, event)

    def _on_rectangle_motion(self, event):
        return _on_rectangle_motion_impl(self, event)

    def _on_quad_click(self, event):
        return _on_quad_click_impl(self, event)

    def _on_quad_motion(self, event):
        return _on_quad_motion_impl(self, event)

    def _on_vertical_click(self, event):
        return _on_vertical_click_impl(self, event)

    def _on_vertical_motion(self, event):
        return _on_vertical_motion_impl(self, event)

    def _on_horizontal_click(self, event):
        return _on_horizontal_click_impl(self, event)

    def _on_horizontal_motion(self, event):
        return _on_horizontal_motion_impl(self, event)

    def _on_polygon_click(self, event):
        return _on_polygon_click_impl(self, event)

    def _on_polygon_motion(self, event):
        return _on_polygon_motion_impl(self, event)

    def start_zoom_box(self):
        return _start_zoom_box_impl(self)

    def _on_zoom_box_click(self, event):
        return _on_zoom_box_click_impl(self, event)

    def _on_zoom_box_motion(self, event):
        return _on_zoom_box_motion_impl(self, event)

    def reset_zoom(self):
        return _reset_zoom_impl(self)

    def start_move_selected_gate(self):
        return _start_move_selected_gate_impl(self)

    def _enable_saved_gate_interaction(self):
        return _enable_saved_gate_interaction_impl(self)

    def start_edit_selected_gate(self):
        return _start_edit_selected_gate_impl(self)

    def _gate_hit_test(self, gate, event):
        return _gate_hit_test_impl(self, gate, event)

    def _on_drag_press(self, event):
        return _on_drag_press_impl(self, event)

    def _on_drag_motion(self, event):
        return _on_drag_motion_impl(self, event)

    def _on_drag_release(self, _event):
        return _on_drag_release_impl(self, _event)

    def _disconnect_drawing(self):
        return _disconnect_drawing_impl(self)

    def _clear_plot(self):
        return _clear_plot_impl(self)

    def _on_well_selection_changed(self):
        return _on_well_selection_changed_impl(self)

    def _on_channel_changed(self):
        return _on_channel_changed_impl(self)

    def _on_gate_type_changed(self):
        return _on_gate_type_changed_impl(self)

    def _on_population_changed(self):
        return _on_population_changed_impl(self)

    def _trigger_auto_plot(self, *_args):
        return _trigger_auto_plot_impl(self, *_args)

    def _on_auto_plot_mode_changed(self):
        return _on_auto_plot_mode_changed_impl(self)

    def open_graph_options_dialog(self):
        return _open_graph_options_dialog(self)

    def _refresh_heatmap_controls(self):
        return _refresh_heatmap_controls_impl(self)

    def _schedule_heatmap_update(self, *_args, delay_ms=120):
        return _schedule_heatmap_update_impl(self, *_args, delay_ms=delay_ms)

    def _schedule_redraw(self, delay_ms=12):
        return _schedule_redraw_impl(self, delay_ms=delay_ms)

    def _schedule_plot_update(self, delay_ms=0):
        return _schedule_plot_update_impl(self, delay_ms=delay_ms)

    def _session_dir(self):
        return _session_dir(self)

    def _settings_path(self):
        return _settings_path(self)

    def _last_session_path(self):
        return _last_session_path(self)

    def _load_settings(self):
        return _load_settings_impl(self)

    def _save_settings(self, settings):
        return _save_settings_impl(self, settings)

    def _recent_sessions(self):
        return _recent_sessions_impl(self)

    def _remember_recent_session(self, path):
        return _remember_recent_session_impl(self, path)

    def _refresh_recent_sessions(self):
        return _refresh_recent_sessions_impl(self)

    def _default_export_dir(self):
        return _default_export_dir(self)

    def _app_home(self):
        return _app_home(self)

    def _session_payload(self):
        return _session_payload_impl(self)

    def _apply_session_payload(self, payload):
        return _apply_session_payload_impl(self, payload)

    def save_session(self):
        return _save_session_impl(self)

    def load_session(self):
        return _load_session_impl(self)

    def load_recent_session(self):
        return _load_recent_session_impl(self)

    def _autoload_last_session_or_folder(self, base_dir):
        return _autoload_last_session_or_folder_impl(self, base_dir)

    def _latest_release_info(self):
        return _latest_release_info()

    def check_for_updates(self):
        return _check_for_updates(self)

    def closeEvent(self, event):
        return _close_event(self, event)

    def _gate_template_payload(self):
        return _gate_template_payload_impl(self)

    def save_gate_template(self):
        return _save_gate_template_impl(self)

    def load_gate_template(self):
        return _load_gate_template_impl(self)

    def _summary_dataframe(self):
        return _summary_dataframe_impl(self)

    def _intensity_distribution_dataframe(self):
        return _intensity_distribution_dataframe_impl(self)

    def _plate_metadata_dataframe(self):
        return _plate_metadata_dataframe_impl(self)

    def export_gate_summary_csv(self):
        return _export_gate_summary_csv_impl(self)

    def delete_selected_gate(self):
        return _delete_selected_gate_impl(self)

    def rename_selected_gate(self):
        return _rename_selected_gate_impl(self)

    def recolor_selected_gate(self):
        return _recolor_selected_gate_impl(self)

    def copy_gate_names(self):
        return _copy_gate_names_impl(self)

    def export_intensity_csv(self):
        return _export_intensity_csv_impl(self)

    def export_plate_metadata_csv(self):
        return _export_plate_metadata_csv_impl(self)

    def _analysis_bundle_paths(self, notebook_path=None):
        return _analysis_bundle_paths_impl(self, notebook_path=notebook_path)

    def _write_analysis_bundle_csvs(self, bundle_paths):
        return _write_analysis_bundle_csvs_impl(self, bundle_paths)

    def open_analysis_preview(self):
        return _open_analysis_preview_impl(self)

    def create_analysis_notebook(self):
        return _create_analysis_notebook_impl(self)

    def export_html_report(self):
        return _export_html_report_impl(self)

    def _update_heatmap(self):
        return _update_heatmap_impl(self)

    def _annotate_heatmap_cells(self, plate, image=None):
        return _annotate_heatmap_cells_impl(self, plate, image=image)

    def _select_well_from_plate(self, well):
        return _select_well_from_plate_impl(self, well)

    def open_plate_map_editor(self):
        return _open_plate_map_editor(self)

    def _refresh_plate_panel(self):
        return _refresh_plate_panel_impl(self)

    def _assign_sample_name_to_selected_wells(self):
        return _assign_sample_name_to_selected_wells_impl(self)

    def _toggle_exclude_selected_wells(self):
        return _toggle_exclude_selected_wells_impl(self)

    def _clear_selected_metadata(self):
        return _clear_selected_metadata_impl(self)

    def keyPressEvent(self, event):
        if _key_press_event_impl(self, event):
            return
        super().keyPressEvent(event)


def launch_desktop_app_qt(base_dir=None, instrument="Cytoflex", max_points=15000):
    app = QApplication.instance() or QApplication(sys.argv)
    window = FlowDesktopQtWindow(base_dir=base_dir, instrument=instrument, max_points=max_points)
    window.show()
    return app.exec()
