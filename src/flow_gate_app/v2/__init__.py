from .models import CompensationState, PlotState, SessionState


def launch_desktop_app_v2(*args, **kwargs):
    from .app import launch_desktop_app_v2 as _launch_desktop_app_v2

    return _launch_desktop_app_v2(*args, **kwargs)


def __getattr__(name):
    if name == "FlowDesktopV2Window":
        from .app import FlowDesktopV2Window as _FlowDesktopV2Window

        return _FlowDesktopV2Window
    raise AttributeError(name)


__all__ = [
    "CompensationState",
    "FlowDesktopV2Window",
    "PlotState",
    "SessionState",
    "launch_desktop_app_v2",
]
