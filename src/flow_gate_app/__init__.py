from ._app_version import __version__


def launch_desktop_app(*args, **kwargs):
    from .flow_desktop_ui import launch_desktop_app as _launch_desktop_app

    return _launch_desktop_app(*args, **kwargs)


def launch_desktop_app_qt(*args, **kwargs):
    from .flow_desktop_ui_qt import launch_desktop_app_qt as _launch_desktop_app_qt

    return _launch_desktop_app_qt(*args, **kwargs)


def __getattr__(name):
    if name == "FlowDesktopApp":
        from .flow_desktop_ui import FlowDesktopApp as _FlowDesktopApp

        return _FlowDesktopApp
    if name == "FlowDesktopQtWindow":
        from .flow_desktop_ui_qt import FlowDesktopQtWindow as _FlowDesktopQtWindow

        return _FlowDesktopQtWindow
    raise AttributeError(name)


__all__ = [
    "FlowDesktopApp",
    "FlowDesktopQtWindow",
    "launch_desktop_app",
    "launch_desktop_app_qt",
    "__version__",
]
