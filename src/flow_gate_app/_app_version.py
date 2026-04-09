from importlib import metadata


try:
    __version__ = metadata.version("flow-gate-app")
except metadata.PackageNotFoundError:
    __version__ = "0.1.18"
