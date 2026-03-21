from __future__ import annotations

from PySide6.QtWidgets import QApplication

from .._app_version import __version__
from ..helpers import APP_BRAND
from .services import AnalysisService, CompensationService, PlateMapService, SessionService, UpdateService
from .state import session_state_from_window, session_state_to_payload
from .window import FlowDesktopQtWindow


class FlowDesktopV2Window(FlowDesktopQtWindow):
    """V2 application shell.

    This preserves full feature parity by inheriting the working Qt implementation,
    while moving the public entrypoint to a new package structure with explicit
    services and typed state adapters.
    """

    def __init__(self, base_dir=None, instrument="Cytoflex", max_points=15000):
        super().__init__(base_dir=base_dir, instrument=instrument, max_points=max_points)
        self.session_service = SessionService(self)
        self.analysis_service = AnalysisService(self)
        self.plate_service = PlateMapService(self)
        self.update_service = UpdateService(self)
        self.compensation_service = CompensationService(self)
        self.setWindowTitle(f"{APP_BRAND} v{__version__}")
        self.qt_plot_note.setText(
            "FlowJitsu v2 keeps full desktop feature parity while moving the Qt app to a cleaner architecture."
        )

    def _session_payload(self):
        return session_state_to_payload(session_state_from_window(self))

    def save_session(self):
        return self.session_service.save()

    def load_session(self):
        return self.session_service.load()

    def load_recent_session(self):
        return self.session_service.load_recent()

    def check_for_updates(self):
        return self.update_service.check()

    def open_analysis_preview(self):
        return self.analysis_service.open_preview()

    def export_gate_summary_csv(self):
        return self.analysis_service.export_summary_csv()

    def export_intensity_csv(self):
        return self.analysis_service.export_intensity_csv()

    def export_plate_metadata_csv(self):
        return self.analysis_service.export_plate_csv()

    def export_html_report(self):
        return self.analysis_service.export_html_report()

    def create_analysis_notebook(self):
        return self.analysis_service.export_notebook()

    def open_plate_map_editor(self):
        return self.plate_service.open_editor()

    def open_compensation_editor(self):
        return self.compensation_service.open_editor()


def launch_desktop_app_v2(base_dir=None, instrument="Cytoflex", max_points=15000):
    app = QApplication.instance() or QApplication([])
    window = FlowDesktopV2Window(base_dir=base_dir, instrument=instrument, max_points=max_points)
    window.show()
    if hasattr(app, "exec"):
        return app.exec()
    return app.exec_()
