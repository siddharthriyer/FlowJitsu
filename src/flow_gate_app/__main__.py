import os
import sys
import traceback

def _startup_log_path():
    if getattr(sys, "frozen", False):
        base = os.path.join(os.path.expanduser("~"), "Library", "Application Support", "FlowJitsu")
    else:
        base = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
    os.makedirs(base, exist_ok=True)
    return os.path.join(base, "startup_error.log")


if __name__ == "__main__":
    try:
        use_qt = "--ui=qt" in sys.argv or os.environ.get("FLOWJITSU_UI", "").strip().lower() == "qt"
        if use_qt:
            from flow_gate_app.flow_desktop_ui_qt import launch_desktop_app_qt

            launch_desktop_app_qt()
        else:
            from flow_gate_app.flow_desktop_ui import launch_desktop_app

            launch_desktop_app()
    except Exception:
        with open(_startup_log_path(), "w") as fh:
            fh.write(traceback.format_exc())
        raise
