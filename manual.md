# FlowJitsu Manual

This document is a comprehensive reference for the FlowJitsu desktop application.

## Overview

FlowJitsu is a plate-oriented flow cytometry analysis app for:

- loading folders of `.fcs` files
- plotting events from selected wells
- drawing and editing gates
- annotating wells with sample metadata
- building dose curves and grouped analyses
- previewing downstream plots
- exporting analysis files
- saving reusable sessions and gate templates
- checking for app updates

## Main Workflow

The typical workflow is:

1. load a folder of FCS files
2. select wells
3. choose X and Y channels
4. choose per-axis transforms
5. plot a population
6. draw and save gates
7. annotate the plate map
8. inspect the well heatmap
9. open analysis preview
10. export reports or CSVs

## Data Loading

The `Data` panel supports:

- choosing a data folder manually
- browsing to a folder
- setting a home folder
- loading detected `.fcs` files from the chosen folder
- selecting instrument mode:
  - `Cytoflex`
  - `Symphony`
- viewing detected wells in the well list

Drag and drop support:

- drop a folder onto the drop zone to load it
- drop a session `.json` file to load a saved session
- drop a gate-template `.json` file to import gates

Compensation support:

- open the compensation editor from the `Compensation` button
- enable or disable compensation
- paste a square labeled spillover matrix
- load a matrix from file
- auto-detect compensation from FCS metadata when present
- match compensation source channels to app channels
- preview before/after compensation on a scatterplot
- persist compensation in saved sessions

Compensation metadata detection currently looks for:

- `SPILL`
- `$SPILL`
- `SPILLOVER`
- `$SPILLOVER`

## Plot Panel

The `Plot` panel supports:

- choosing the active population
- setting max plotted events
- plotting the selected population
- choosing X and Y channels
- switching plot mode:
  - `scatter`
  - `count histogram`
- setting transform independently for each axis:
  - X transform
  - X cofactor
  - Y transform
  - Y cofactor
- opening slider-based shared scatter axis controls with `Axes Limits`

Supported transforms:

- `linear`
- `log10`
- `arcsinh`

Scatter axis limit behavior:

- auto-limits are shared across all loaded FCS files
- per-file limits are based on robust quantiles rather than absolute extremes
- shared limits use median per-file bounds
- manual overrides can be applied with sliders
- manual overrides can be reset back to automatic limits

## Gating

Supported gate types:

- polygon
- quad
- vertical threshold
- horizontal threshold

Gating features:

- draw new gates interactively
- preview a pending gate before saving
- save gates into the current session
- auto-generate paired `above` and `below` gates for threshold gates
- rename gates
- recolor gates
- delete gates
- drag saved gates directly on the plot
- move polygon vertices
- translate full polygons
- move quad intersections
- move vertical and horizontal thresholds

Gate behavior:

- gates are defined in the transformed coordinate system
- gates are attached to a parent population
- child populations can be gated recursively
- saved-gate heatmaps update when gates move
- gate statistics update from the selected gate

Gate organization:

- gates are shown in the saved-gate list
- hierarchical population labels are displayed as lineage paths
- threshold gate pairs are grouped together
- boolean populations are generated for compatible sibling fluorescence gates

Gate template features:

- save current gates as a reusable template JSON
- load template gates into the current experiment
- validate required channels before import
- block duplicate gate names

## Plate Map And Metadata

The `Plate Map` editor supports metadata assignment across wells.

Metadata fields include:

- `sample_name`
- `treatment_group`
- `dose_curve`
- `dose`
- `replicate`
- `sample_type`
- `dose_direction`
- `excluded`

Selection behavior:

- click individual wells
- drag across wells to select blocks
- use additive selection modifiers for discontinuous groups

Plate features:

- assign sample metadata to selected wells
- assign dose curves
- mark wells excluded from downstream analysis
- inspect well metadata in the editor
- preview the plate layout in the main window

Dose curve defaults:

- top dose: `50`
- dilution ratio: `2`
- points: `4`

Control assignment:

- wells can be marked as:
  - `sample`
  - `negative_control`
  - `positive_control`

These control assignments are used in Analysis Preview normalization.

## Heatmap

The main window includes a well heatmap panel.

Supported heatmap modes:

- percent positive
- mean fluorescence intensity
- channel correlation

Heatmap controls include:

- metric selection for percent-positive heatmaps
- population selection for MFI and correlation heatmaps
- channel selection
- second channel selection for correlation mode
- custom heatmap title
- save heatmap to file

Heatmap behavior:

- updates after loading data
- updates after saving, deleting, renaming, or moving gates
- updates after plate metadata changes that affect analysis

## Plate Overview

The right-side plate overview panel shows:

- which wells have FCS data
- which wells have assigned sample names
- excluded wells
- compact sample badges

Plate overview features:

- hover tooltips with well metadata
- live summary of FCS wells, assigned wells, and excluded wells

## Analysis Preview

The `Analysis Preview` window provides downstream plot previews and styling controls.

Plot types:

- `bar`
- `distribution`
- `correlation`

Layout features:

- scrollable top control panel
- scrollable right-side sample palette panel
- live Matplotlib preview
- toolbar for navigation and saving

### Bar Mode

Bar mode supports:

- choosing the `% positive` column
- choosing bar X grouping
- choosing bar hue grouping
- GraphPad Prism-like styling
- capped error bars
- configurable bar fill color
- configurable bar outline width
- configurable axis line width
- configurable legend border width

Bar normalization metrics:

- `raw_percent`
- `delta_vs_negative`
- `fold_vs_negative`
- `percent_of_positive`
- `minmax_neg_to_pos`

Control comparison grouping:

- `global`
- `x_axis`
- `sample_name`
- `dose_curve`
- `treatment_group`
- `replicate`
- `well`

Control labels are editable:

- negative-control label
- positive-control label

### Distribution Mode

Distribution mode supports:

- selecting an intensity channel
- optional gate filter
- distribution hue grouping
- violin plots instead of KDE
- log-scaled fluorescence axis

### Correlation Mode

Correlation mode supports:

- choosing correlation X
- choosing correlation Y
- grouping correlations by bar X
- optional bar hue grouping
- plotting correlation coefficients as bars

Mode-specific control behavior:

- bar mode hides distribution-only controls
- distribution mode shows intensity-channel, gate-filter, and dist-hue controls
- correlation mode shows only correlation-relevant channel controls

### Sample Palette Grouping

The palette panel supports:

- organizing samples into palette groups
- assigning palette names per group
- moving selected samples between groups
- resetting grouping
- using seaborn or matplotlib palette names

Groups available:

- `Ungrouped`
- `Group 1`
- `Group 2`
- `Group 3`
- `Group 4`

### Advanced Settings

The `Advanced Settings` dialog supports:

- axis line width
- bar outline width
- legend outline width
- bar fill color
- error bar cap size

## Export And Reporting

The `Analysis And Export` section supports:

- opening Analysis Preview
- exporting an HTML report
- creating a Jupyter notebook
- opening Plate Map
- opening Excluded Wells editor
- exporting summary CSV
- exporting intensities CSV

Generated analysis files can include:

- `flow_gate_summary.csv`
- `flow_intensity_distribution.csv`
- `plate_metadata.csv`
- HTML report
- Jupyter notebook

HTML report behavior:

- includes summary tables
- includes plate metadata preview
- includes default summary plots

Notebook generation behavior:

- generates a dated notebook
- points to the exported CSV files
- includes starter code for downstream analysis

## Session Management

The `Session` section supports:

- undo
- redo
- save session
- load session
- open recent session
- check for updates

Session behavior:

- stores current folder
- stores instrument
- stores gates
- stores plate metadata
- stores dose-curve definitions
- stores compensation settings
- maintains a last-session file
- supports autosave state tracking

## Updates

The app includes a built-in updater.

Updater features:

- checks the latest GitHub release
- compares release version with local app version
- reports when the app is already current
- opens the release page when useful
- downloads packaged release assets

macOS updater behavior:

- can download the release zip
- can replace the app bundle in place
- can relaunch the updated app

Windows updater behavior:

- downloads the packaged app
- supports extraction
- currently expects manual replacement after download

Downloaded updates are stored in:

- `~/Downloads/FlowJitsuUpdates/`

## Styling

Several plots use a GraphPad Prism-like style:

- thicker axis lines
- thicker bar outlines
- thicker legend box outlines
- capped error bars
- light-blue default bar fill

This styling applies in:

- analysis preview plots
- exported summary bar plots
- main plot axis styling
- heatmap axis styling

## Saved Data Locations

When running from a bundled macOS app, app data is stored in:

- `~/Library/Application Support/FlowJitsu/`

This location is used for:

- sessions
- exports
- generated notebooks

## Current Practical Limits

Current limitations to be aware of:

- drag and drop requires `tkinterdnd2`
- automatic in-place updating is stronger on macOS than Windows
- compensation requires a valid labeled spillover matrix when not auto-detected
- gates are drawn in transformed coordinates, so changing transforms changes how a gate lines up visually unless the gate was created under the same transform settings

## File Reference

Important files in the repo:

- `README.md`: short end-user quickstart
- `manual.md`: full feature reference
- `src/flow_gate_app/flow_desktop_ui.py`: main desktop UI
- `src/flow_gate_app/analysis_views.py`: analysis preview and export plotting
- `src/flow_gate_app/plate_views.py`: plate map and exclusion editors
- `src/flow_gate_app/helpers.py`: plotting, transforms, and utility helpers
