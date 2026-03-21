from __future__ import annotations


class SessionService:
    def __init__(self, window):
        self.window = window

    def save(self):
        return super(type(self.window), self.window).save_session()

    def load(self):
        return super(type(self.window), self.window).load_session()

    def load_recent(self):
        return super(type(self.window), self.window).load_recent_session()


class AnalysisService:
    def __init__(self, window):
        self.window = window

    def open_preview(self):
        return super(type(self.window), self.window).open_analysis_preview()

    def export_summary_csv(self):
        return super(type(self.window), self.window).export_gate_summary_csv()

    def export_intensity_csv(self):
        return super(type(self.window), self.window).export_intensity_csv()

    def export_plate_csv(self):
        return super(type(self.window), self.window).export_plate_metadata_csv()

    def export_html_report(self):
        return super(type(self.window), self.window).export_html_report()

    def export_notebook(self):
        return super(type(self.window), self.window).create_analysis_notebook()


class PlateMapService:
    def __init__(self, window):
        self.window = window

    def open_editor(self):
        return super(type(self.window), self.window).open_plate_map_editor()


class UpdateService:
    def __init__(self, window):
        self.window = window

    def check(self):
        return super(type(self.window), self.window).check_for_updates()


class CompensationService:
    def __init__(self, window):
        self.window = window

    def open_editor(self):
        return super(type(self.window), self.window).open_compensation_editor()
