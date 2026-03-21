from __future__ import annotations

from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
)


def open_compensation_editor(window):
    dialog = QDialog(window)
    dialog.setWindowTitle("Compensation")
    dialog.resize(980, 700)
    layout = QVBoxLayout(dialog)
    enabled_box = QCheckBox("Enable compensation")
    enabled_box.setChecked(window.compensation_enabled)
    layout.addWidget(enabled_box)
    layout.addWidget(QLabel("Paste a square spillover matrix with matching row/column channel labels. CSV or TSV works."))
    text_edit = QTextEdit()
    text_edit.setPlainText(window.compensation_text)
    layout.addWidget(text_edit, stretch=1)
    button_row = QHBoxLayout()
    load_button = QPushButton("Load File")
    autodetect_button = QPushButton("Auto Detect")
    apply_button = QPushButton("Apply")
    close_button = QPushButton("Close")
    button_row.addWidget(load_button)
    button_row.addWidget(autodetect_button)
    button_row.addStretch(1)
    button_row.addWidget(apply_button)
    button_row.addWidget(close_button)
    layout.addLayout(button_row)

    def _load_file():
        filename, _ = QFileDialog.getOpenFileName(dialog, "Load Compensation Matrix", "", "CSV/TSV files (*.csv *.tsv *.txt);;All files (*)")
        if not filename:
            return
        with open(filename) as fh:
            text_edit.setPlainText(fh.read())

    def _auto_detect():
        if not window.file_map:
            window.status_label.setText("Load a folder first.")
            return
        sample = window._load_sample(next(iter(window.file_map.values())))
        try:
            source_channels, matrix = window._extract_compensation_from_sample_meta(sample)
        except Exception as exc:
            window.status_label.setText(f"Automatic detection failed: {type(exc).__name__}: {exc}")
            return
        header = "," + ",".join(source_channels)
        rows = [f"{channel}," + ",".join(f"{value:.10g}" for value in matrix[idx]) for idx, channel in enumerate(source_channels)]
        text_edit.setPlainText("\n".join([header] + rows))

    def _apply():
        text = text_edit.toPlainText().strip()
        if text:
            try:
                source_channels, matrix = window._parse_compensation_text(text)
            except Exception as exc:
                window.status_label.setText(f"Invalid compensation matrix: {type(exc).__name__}: {exc}")
                return
            mapping = window._default_compensation_mapping(source_channels)
            if any(not item for item in mapping):
                window.status_label.setText("Some compensation channels could not be mapped automatically.")
                return
            window.compensation_source_channels = list(source_channels)
            window.compensation_channels = list(mapping)
            window.compensation_matrix = matrix
            window.compensation_text = text
        else:
            window.compensation_source_channels = []
            window.compensation_channels = []
            window.compensation_matrix = None
            window.compensation_text = ""
        window.compensation_enabled = bool(enabled_box.isChecked()) and window.compensation_matrix is not None
        window.sample_cache = {}
        window._sample_raw_cache = {}
        window._invalidate_cached_outputs()
        window._update_compensation_status()
        if window.file_map:
            window.plot_population()
        dialog.accept()

    load_button.clicked.connect(_load_file)
    autodetect_button.clicked.connect(_auto_detect)
    apply_button.clicked.connect(_apply)
    close_button.clicked.connect(dialog.close)
    dialog.exec()
