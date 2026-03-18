# FlowJitsu

FlowJitsu is a desktop app for flow cytometry gating, plate annotation, and quick downstream analysis.

It is designed for plate-based `.fcs` workflows where you want to:

- load a folder of FCS files
- gate populations interactively
- annotate wells with sample metadata and dose curves
- preview bar plots, distributions, and correlations
- export summary tables for follow-up analysis

## Run The App

If the Python version is installed into the lab conda environment:

```bash
conda activate biocompute-vscode-min
flow-gate-desktop
```

If you are running from source without installing:

```bash
cd "/Users/siddharthiyer/MIT Dropbox/Siddharth Iyer/Church Lab/Viral RNA Delivery/Data/Flow/flow_gate_app"
PYTHONPATH=src python -m flow_gate_app
```

## Install

From the `flow_gate_app` folder:

```bash
./install_flow_gate_app.sh
```

If you want to install into a different conda environment:

```bash
./install_flow_gate_app.sh my-env-name
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

Downloaded update files are saved to:

```text
~/Downloads/FlowJitsuUpdates/
```

On macOS, the app can download and replace the app bundle for you. On Windows, it downloads the packaged app and you replace the folder manually.

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
