# Flow Gate App

Desktop flow cytometry gating and plate-annotation app for the Church Lab flow workflows.

## What It Does

This package provides a standalone desktop application for flow cytometry analysis with a workflow built around:

- loading a folder of `.fcs` files from a plate-based run
- interactively plotting wells and gated populations
- creating and editing polygon, quad, vertical, and horizontal gates
- assigning sample metadata and dose-curve metadata on a 96-well plate map
- excluding wells from downstream analysis
- exporting summary and per-event CSVs
- generating a downstream Jupyter notebook for plotting and analysis

The app is designed so users can do interactive gating and plate annotation in the GUI, then switch to notebooks only for downstream figure-making and custom analysis.

## Package Layout

- `src/flow_gate_app/flow_desktop_ui.py`: main desktop application
- `src/FlowCytometryTools/`: vendored patched copy of `FlowCytometryTools`
- `.github/workflows/release.yml`: GitHub Actions build/release workflow
- `sessions/`: saved app sessions
- `exports/`: exported CSVs and analysis handoff files

## Key Concepts

### Sessions

The app can save and load session JSON files containing:

- selected data folder
- instrument
- saved gates
- plate metadata
- dose-curve definitions

It also maintains a `last_flow_session.json` file in `sessions/` so the most recent gates and metadata can be restored automatically.

### Exports

The desktop app writes timestamped export folders under `exports/`. These include:

- `flow_gate_summary.csv`: per-well gate percentages and counts
- `flow_intensity_distribution.csv`: per-event fluorescence distributions and gate membership
- `plate_metadata.csv`: sample and plate annotations

### Generated Notebook

The app can generate a dated notebook that loads those CSVs and includes example plotting helpers for:

- percent-positive bar plots
- dose curves
- fluorescence intensity distributions

The analysis preview and exported report plots use a heavier GraphPad Prism-like visual treatment:

- thicker axis lines
- thick bar outlines
- thicker legend box outlines

### Update Checks

The desktop UI includes a `Check for Updates` button. It queries the latest GitHub Release for `siddharthriyer/FlowJitsu`, compares that release tag to the local app version, and can:

- download the recommended release asset into `~/Downloads/FlowJitsuUpdates/`
- open the GitHub release page
- report when the app is already current

When running as a bundled macOS app, the updater can also:

- unzip the downloaded app bundle
- ask where to install the replacement app
- close the current app
- replace the app bundle and relaunch it

On Windows, the updater currently supports download and extraction of the packaged app, followed by manual folder replacement. Automatic in-place Windows app replacement is not implemented yet.

## Install

### Recommended: install into `biocompute-vscode-min`

From the `flow_gate_app` folder:

```bash
./install_flow_gate_app.sh
```

To install into a different conda environment:

```bash
./install_flow_gate_app.sh my-env-name
```

### Install From A Built Wheel

If you already built a wheel in `dist/`, install it into the target conda env with:

```bash
./install_flow_gate_wheel.sh dist/flow_gate_app-0.1.0-py3-none-any.whl
```

Or specify a different conda env:

```bash
./install_flow_gate_wheel.sh dist/flow_gate_app-0.1.0-py3-none-any.whl my-env-name
```

### Manual install

From the `flow_gate_app` folder:

```bash
pip install -e .
flow-gate-desktop
```

Or without installing:

```bash
PYTHONPATH=src python -m flow_gate_app
```

## Run

After install:

```bash
conda activate biocompute-vscode-min
flow-gate-desktop
```

## Updating The Software

For local development:

- edit the code in `src/flow_gate_app/`
- if you installed with `pip install -e .`, changes are picked up immediately

For versioned distribution:

- increment `version` in `pyproject.toml`
- build a new wheel with `./build_wheel.sh`
- distribute the new wheel from `dist/`
- install or upgrade it with `./install_flow_gate_wheel.sh <wheel-path>`

## Standalone macOS App

This is the start of the long-term path for users who do not want to manage Python directly.

### Build A macOS App Bundle

From the package root:

```bash
./build_macos_app.sh
```

Or build using a different conda env:

```bash
./build_macos_app.sh my-env-name
```

This uses PyInstaller and creates:

```text
dist/FlowJitsu.app
```

### Runtime Data Location

When run as a bundled app, session files, exports, and generated notebooks are written to:

```text
~/Library/Application Support/FlowJitsu/
```

This avoids trying to write inside the `.app` bundle itself.

### Updating The Standalone App

The simplest update model is:

1. bump the package version in `pyproject.toml`
2. rebuild the app with `./build_macos_app.sh`
3. distribute the new `FlowJitsu.app`
4. users replace their old app bundle with the new one

Their exported data and saved sessions stay in `~/Library/Application Support/FlowJitsu/`, so replacing the app bundle should not wipe their working state.

### Standalone App Update Script

To replace an installed app bundle with a new build:

```bash
./update_macos_app.sh /path/to/FlowJitsu.app
```

By default this installs into `/Applications`.

To install into a user-local applications folder instead:

```bash
./update_macos_app.sh /path/to/FlowJitsu.app ~/Applications
```

This script replaces the app bundle only. It does not delete user sessions or exports, because those live under:

```text
~/Library/Application Support/FlowJitsu/
```

## Wheel Distribution Workflow

### For You

From the package root:

```bash
./build_wheel.sh
```

This creates files under `dist/`, including a wheel like:

```text
flow_gate_app-0.1.0-py3-none-any.whl
```

### For Labmates

Once they have the wheel file, they can run:

```bash
./install_flow_gate_wheel.sh dist/flow_gate_app-0.1.0-py3-none-any.whl
```

or, if they only have the wheel file and not the full repo:

```bash
conda activate biocompute-vscode-min
python -m pip install --upgrade flow_gate_app-0.1.0-py3-none-any.whl
```

This gives them the packaged app without needing an editable source checkout.

## Code Overview

### Main App

`src/flow_gate_app/flow_desktop_ui.py` contains the desktop application. It is currently a single-file UI/controller module that handles:

- tkinter layout
- matplotlib embedding
- gate creation/editing
- plate metadata editing
- export generation
- analysis preview plots

### Entrypoints

- `flow_gate_desktop` console script from `pyproject.toml`
- `python -m flow_gate_app`
- compatibility wrapper at `../bin/flow_desktop_ui.py`

### Vendored Dependency

`src/FlowCytometryTools/` is a bundled patched copy of `FlowCytometryTools`.

This is intentional. It prevents labmates from hitting the older Python compatibility issue where some upstream installs still use `collections` instead of `collections.abc`.

## Dependency Notes

This package vendors a patched copy of `FlowCytometryTools`, so users do not need a separate system install of that package and will not hit the older `collections` vs `collections.abc` compatibility issue.

## GitHub Setup

This folder is now structured so it can be moved into its own GitHub repository.

Recommended repo layout:

- make `flow_gate_app/` the repository root
- commit `.github/workflows/release.yml`
- create version tags like `v0.1.0`

If you leave it nested inside a larger local repo, GitHub Actions will not automatically use the workflow unless this folder becomes the actual repository root on GitHub.

## GitHub Release Workflow

Once `flow_gate_app/` is its own GitHub repo:

1. push the code to GitHub
2. bump `version` in `pyproject.toml`
3. create and push a tag like:

```bash
git tag v0.1.0
git push origin v0.1.0
```

GitHub Actions will then:

- build a wheel and source distribution
- build a macOS app bundle
- zip the macOS app
- attach release artifacts to a GitHub Release
- generate SHA256 checksums

Artifacts produced by the workflow:

- Python wheel
- source tarball
- `FlowJitsu-macos.zip`
- `SHA256SUMS.txt`

## Local Release Build

To build everything locally before publishing:

```bash
./build_release_assets.sh
```

This will:

- build the wheel
- build the macOS app bundle
- create a zipped macOS app
- write checksums in `dist/SHA256SUMS.txt`

## Easy Update Distribution

The easiest update path is:

1. publish a new GitHub Release
2. labmates download the newest wheel or `FlowJitsu-macos.zip`
3. they either:
   - install the new wheel with `install_flow_gate_wheel.sh`
   - or replace the macOS app with `update_macos_app.sh`

That gives you a simple but reliable update story without building a true in-app auto-updater yet.
