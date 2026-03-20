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

This release includes both the legacy Tk desktop app and the newer Qt desktop app.

- launch the Tk app with `python -m flow_gate_app`
- launch the Qt app with `python -m flow_gate_app --ui=qt`
- the Qt app is the active migration path and now includes plotting, gating, plate-map editing, compensation, analysis preview, exports, and update checking

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
- scrolling through long well lists
- seeing excluded wells marked directly in the list
- seeing mixed-channel well entries annotated with channel-count badges when channel sets differ across files

Drag and drop support:

- drop a folder onto the drop zone to load it
- drop a session `.json` file to load a saved session
- drop a gate-template `.json` file to import gates

Compensation support:

- open the compensation editor from the `Compensation` button
- enable or disable compensation
- paste a square labeled spillover matrix
- auto-detect compensation from FCS metadata when present
- automatically map compensation source channels onto loaded channels when possible
- persist compensation in saved sessions

Qt compensation behavior:

- supports pasted matrices and SPILL or SPILLOVER metadata detection
- stores the active compensation matrix inside the session
- applies compensation before downstream plotting and gating
- currently relies on automatic channel mapping rather than a full manual mapping editor

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
- choosing auto-replot behavior:
  - `Auto`
  - `Manual`
- setting transform independently for each axis:
  - X transform
  - X cofactor
  - Y transform
  - Y cofactor
- opening graph controls with `Graph Options`
- drawing a `Zoom Box`
- resetting plot limits with `Reset Zoom`
- viewing a mixed-channel warning banner when selected wells do not all share the same channels
- seeing the selected well name in the plot title
- seeing the assigned sample name in the plot title when one selected well has metadata
- keeping the interactive plot square

Supported transforms:

- `linear`
- `log10`
- `arcsinh`

Scatter axis limit behavior:

- auto-limits are shared across all loaded FCS files
- per-file limits are based on robust quantiles rather than absolute extremes
- shared limits use median per-file bounds
- manual overrides can be applied with both text entry and sliders
- manual overrides can be reset back to automatic limits

Histogram axis limit behavior:

- histogram X and Y limits are controlled with both text entry and sliders in the `Histogram` tab of `Graph Options`
- histogram slider ranges use the full extent across all loaded FCS files
- histogram X max extends to the maximum transformed channel value across all files plus padding
- histogram Y max extends to the maximum histogram count across all files plus padding
- histogram Y auto-scaling follows the data currently being plotted while X remains channel-shared
- `Apply` keeps the window open
- `Use Auto` resets only the active plot-type limits and keeps the window open

Mixed-channel plotting behavior:

- channel menus use the union of channels across the selected wells
- if selected wells do not all contain the chosen channels, the app shows a warning instead of hiding those channels
- wells missing the current plot channels are skipped only where necessary
- gates that depend on unavailable channels are skipped for wells that do not contain those channels
- mixed-channel experiments can still be plotted and analyzed without forcing all files to share the same channel intersection

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
- move the selected polygon or rectangle gate with `Move Selected Gate`
- move polygon vertices
- translate full polygons
- translate full rectangle gates
- move quad intersections
- move vertical and horizontal thresholds
- show vertical thresholds on any plot whose X axis matches the threshold channel
- switch to histogram view automatically when selecting a vertical threshold gate
- cancel active drawing or zoom mode with `Esc`
- use the visible mode banner to confirm whether the app is idle, drawing, dragging, or zooming
- scroll saved gates, gate percentages, and gate statistics panels when content is long

Gate behavior:

- gates are defined in the transformed coordinate system
- gates are attached to a parent population
- child populations can be gated recursively
- selecting a saved gate shows its parent population underneath the selected gate
- saved-gate heatmaps update when gates move
- gate statistics update from the selected gate
- drawing and dragging only begin after real pointer movement, which improves reliability on older trackpads
- polygon drawing shows large vertex markers and can be closed by clicking near the first vertex, double-clicking, or right-clicking

Gate organization:

- gates are shown in the saved-gate list
- saved-gate list entries emphasize lineage and channels rather than recomputing percentages for every refresh
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
- see excluded wells marked in the main well list
- use a drag-selectable plate table in the Qt editor
- manage samples from the editor with sample create, extend, and delete actions
- see richer well tooltips including sample type, dose, replicate, direction, exclusion state, and FCS availability

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
- a local heatmap status indicator
- centered heatmap display in the Qt layout

Heatmap behavior:

- updates after loading data
- updates after saving, deleting, renaming, or moving gates
- updates after plate metadata changes that affect analysis
- updates are slightly deferred after gate edits to reduce UI stalls
- shows `Updating heatmap...` near the heatmap controls while a refresh is running
- keeps annotation text readable by using light text on dark cells and dark text on light cells
- does not change just because a different saved gate is selected

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
- `line`
- `distribution`
- `correlation`

Layout features:

- scrollable top control panel
- scrollable right-side sample palette panel
- live Matplotlib preview
- toolbar for navigation and saving
- dose-aware defaults for line plots when dose metadata is available

### Bar Mode

Bar mode supports:

- choosing the `% positive` column
- choosing bar X grouping
- choosing bar hue grouping
- GraphPad Prism-like styling
- capped error bars
- overlaid replicate dots
- configurable bar fill color
- configurable bar outline width
- configurable axis line width
- configurable legend border width

### Line Mode

Line mode supports:

- choosing the `% positive` column
- using dose-aware X groupings
- plotting replicate means with SD error bars
- overlaying replicate dots
- log or linear X scale
- log or linear Y scale

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
- applying palette groups to sample-colored bar and line plots

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
- exporting summary CSV
- exporting intensities CSV
- exporting plate metadata CSV

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
- prompts to save on close in the Qt app
- auto-loads the last session in the Qt app

## Updates

The app includes a built-in updater.

Updater features:

- checks the latest GitHub release
- compares release version with local app version
- reports when the app is already current
- opens the release page when useful
- the Qt app currently opens the release page when an update is found

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
- the Qt compensation editor currently depends on automatic channel mapping
- compensation requires a valid labeled spillover matrix when not auto-detected
- gates are drawn in transformed coordinates, so changing transforms changes how a gate lines up visually unless the gate was created under the same transform settings
- mixed-channel experiments are supported, but gates and plots can only use channels present in each individual well

## File Reference

Important files in the repo:

- `README.md`: short end-user quickstart
- `manual.md`: full feature reference
- `src/flow_gate_app/flow_desktop_ui.py`: main desktop UI
- `src/flow_gate_app/analysis_views.py`: analysis preview and export plotting
- `src/flow_gate_app/plate_views.py`: plate map and exclusion editors
- `src/flow_gate_app/helpers.py`: plotting, transforms, and utility helpers
