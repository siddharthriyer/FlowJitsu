from ._app_version import __version__


def launch_desktop_app(*args, **kwargs):
    from .flow_desktop_ui import launch_desktop_app as _launch_desktop_app

    return _launch_desktop_app(*args, **kwargs)


def launch_desktop_app_qt(*args, **kwargs):
    from .v2 import launch_desktop_app_v2 as _launch_desktop_app_qt

    return _launch_desktop_app_qt(*args, **kwargs)


def launch_desktop_app_v2(*args, **kwargs):
    from .v2 import launch_desktop_app_v2 as _launch_desktop_app_v2

    return _launch_desktop_app_v2(*args, **kwargs)


def __getattr__(name):
    if name == "FlowDesktopApp":
        from .flow_desktop_ui import FlowDesktopApp as _FlowDesktopApp

        return _FlowDesktopApp
    if name == "FlowDesktopQtWindow":
        from .v2 import FlowDesktopV2Window as _FlowDesktopQtWindow

        return _FlowDesktopQtWindow
    if name == "FlowDesktopV2Window":
        from .v2 import FlowDesktopV2Window as _FlowDesktopV2Window

        return _FlowDesktopV2Window
    raise AttributeError(name)


__all__ = [
    "FlowDesktopApp",
    "FlowDesktopQtWindow",
    "FlowDesktopV2Window",
    "launch_desktop_app",
    "launch_desktop_app_qt",
    "launch_desktop_app_v2",
    "__version__",
]
