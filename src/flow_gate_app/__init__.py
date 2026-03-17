from importlib import metadata

from .flow_desktop_ui import FlowDesktopApp, launch_desktop_app

try:
    __version__ = metadata.version("flow-gate-app")
except metadata.PackageNotFoundError:
    __version__ = "0.1.0"

__all__ = ["FlowDesktopApp", "launch_desktop_app", "__version__"]
