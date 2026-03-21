from __future__ import annotations

import json
import urllib.request
import webbrowser
from urllib.error import HTTPError

from PySide6.QtWidgets import QMessageBox

from .._app_version import __version__
from ..helpers import GITHUB_LATEST_RELEASE_API, GITHUB_RELEASES_URL, normalize_version_tag as _normalize_version_tag, version_key as _version_key


def latest_release_info():
    request = urllib.request.Request(
        GITHUB_LATEST_RELEASE_API,
        headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": "FlowJitsu",
        },
    )
    with urllib.request.urlopen(request, timeout=10) as response:
        payload = json.loads(response.read().decode("utf-8"))
    return {
        "tag_name": payload.get("tag_name", ""),
        "html_url": payload.get("html_url", GITHUB_RELEASES_URL),
    }


def check_for_updates(window):
    try:
        window.status_label.setText("Checking GitHub for updates...")
        latest = latest_release_info()
        latest_tag = latest.get("tag_name", "") or ""
        current_tag = f"v{_normalize_version_tag(__version__)}"
        window.version_label.setText(f"Version {__version__} | Latest {latest_tag or 'unknown'}")
        if latest_tag and _version_key(latest_tag) > _version_key(current_tag):
            action = QMessageBox.question(
                window,
                "Update Available",
                f"A newer version is available.\n\nCurrent: {current_tag}\nLatest: {latest_tag}\n\nOpen the GitHub release page?",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.Yes,
            )
            window.status_label.setText(f"Update available: {latest_tag}")
            if action == QMessageBox.Yes:
                webbrowser.open(latest.get("html_url", GITHUB_RELEASES_URL))
        else:
            QMessageBox.information(
                window,
                "Up To Date",
                f"You are already on the latest available version.\n\nCurrent: {current_tag}\nLatest: {latest_tag or current_tag}",
            )
            window.status_label.setText(f"Up to date: {current_tag}")
    except HTTPError as exc:
        window.status_label.setText(f"Update check failed: HTTPError {exc.code}")
    except Exception as exc:
        window.status_label.setText(f"Update check failed: {type(exc).__name__}: {exc}")
