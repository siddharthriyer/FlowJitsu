# FlowJitsu

FlowJitsu is a desktop app for flow cytometry gating, plate annotation, and quick downstream analysis.

It is designed for plate-based `.fcs` workflows where you want to:

- load a folder of FCS files
- gate populations interactively
- annotate wells with sample metadata and dose curves
- preview bar plots, distributions, and correlations
- export summary tables for follow-up analysis

## Install The App

The simplest way to install FlowJitsu is from the latest GitHub release:

1. open the latest release page
2. download the packaged app for your platform
3. unzip it
4. launch the app directly

Release assets:

- `FlowJitsu-macos-arm64.zip` for Apple Silicon Macs
- `FlowJitsu-macos-intel.zip` for Intel Macs
- `FlowJitsu-windows.zip` for Windows

If you prefer running from Python instead of the packaged app, use one of the options below.

## Run From Python

If you have installed the package into a Python environment:

```bash
flow-gate-desktop
```

If you are running from source without installing:

```bash
cd /path/to/flow_gate_app
PYTHONPATH=src python -m flow_gate_app
```

To force the legacy Tk UI instead of the default Qt UI:

```bash
PYTHONPATH=src python -m flow_gate_app --ui=tk
```

## Install Into Conda

From the `flow_gate_app` folder:

```bash
conda create -n flowjitsu python=3.10 -y
conda activate flowjitsu
python -m pip install -e .
```

Or install into an existing environment:

```bash
python -m pip install -e .
```

## Standalone macOS App

To build the macOS app bundle:

```bash
./build_macos_app.sh
```

The built app is:

```text
dist/FlowJitsu.app
```

When the bundled app runs, it stores sessions, exports, and generated notebooks in:

```text
~/Library/Application Support/FlowJitsu/
```

## Updating

Inside the app, use `Check for Updates` to look for the latest GitHub release.
The Qt app currently opens the release page when a newer version is available.

## What The App Exports

Exported analysis folders include:

- `flow_gate_summary.csv`
- `flow_intensity_distribution.csv`
- `plate_metadata.csv`

The app can also generate:

- an HTML summary report
- a Jupyter notebook for follow-up analysis

## Notes

- If you edit code under `src/flow_gate_app/`, those changes appear immediately only in a source run or editable install.
- If you are using `FlowJitsu.app`, rebuild the app after code changes.
