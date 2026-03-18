import tkinter as tk
from tkinter import filedialog, messagebox, ttk

import pandas as pd

from .helpers import event_adds_to_selection as _event_adds_to_selection
from .helpers import get_well_name as _get_well_name


def open_plate_map_editor(self):
    if not self.file_map:
        messagebox.showinfo("Plate Map", "Load a folder first.")
        return

    top = tk.Toplevel(self.root)
    top.title("Plate Map Editor")
    top.geometry("980x700")
    top.rowconfigure(0, weight=1)
    top.columnconfigure(0, weight=1)

    selected_wells = set()
    available_wells = {_get_well_name(relpath, self.instrument_var.get()) for relpath in self.file_map.values()}
    sample_name_var = tk.StringVar()
    direction_var = tk.StringVar(value="horizontal")
    curve_points_var = tk.IntVar(value=8)
    top_dose_var = tk.DoubleVar(value=1.0)
    dilution_var = tk.DoubleVar(value=3.0)
    info_var = tk.StringVar(value="Click or drag across wells to select them. Hold Shift or Control to add discontinuous groups.")
    drag_rect = {"id": None, "start": None}
    well_items = {}
    row_names = "ABCDEFGH"

    outer = ttk.Frame(top)
    outer.grid(row=0, column=0, sticky="nsew")
    outer.rowconfigure(0, weight=1)
    outer.columnconfigure(0, weight=1)

    scroll_canvas = tk.Canvas(outer, highlightthickness=0)
    scroll_canvas.grid(row=0, column=0, sticky="nsew")
    scroll = ttk.Scrollbar(outer, orient="vertical", command=scroll_canvas.yview)
    scroll.grid(row=0, column=1, sticky="ns")
    scroll_canvas.configure(yscrollcommand=scroll.set)

    content = ttk.Frame(scroll_canvas, padding=10)
    content_window = scroll_canvas.create_window((0, 0), window=content, anchor="nw")

    def _sync_scroll(_event=None):
        scroll_canvas.configure(scrollregion=scroll_canvas.bbox("all"))
        scroll_canvas.itemconfigure(content_window, width=scroll_canvas.winfo_width())

    content.bind("<Configure>", _sync_scroll)
    scroll_canvas.bind("<Configure>", _sync_scroll)

    def _wheel(event):
        scroll_canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")

    scroll_canvas.bind_all("<MouseWheel>", _wheel)

    def default_well_fill(well):
        if well in selected_wells:
            return "#8dd3c7"
        if well in available_wells:
            meta = self.plate_metadata.get(well, {})
            if meta.get("excluded", False):
                return "#d9d9d9"
            sample_name = meta.get("sample_name", "")
            if sample_name:
                palette = ["#cfe8ff", "#ffe0c7", "#d9f2d9", "#ecd9ff", "#ffeaa7", "#ffd6e7"]
                return palette[abs(hash(sample_name)) % len(palette)]
            return "#ffffff"
        return "#f3f3f3"

    def refresh_plate():
        for well, items in well_items.items():
            fill = default_well_fill(well)
            outline = "#1f77b4" if well in available_wells else "#b5b5b5"
            width = 3 if well in selected_wells else 1.5
            canvas.itemconfigure(items["oval"], fill=fill, outline=outline, width=width)

    def set_info():
        ordered = sorted(selected_wells, key=lambda w: (w[0], int(w[1:])))
        info_var.set(f"Selected wells ({len(ordered)}): {', '.join(ordered) if ordered else 'none'}")

    def toggle_well(well):
        if well in selected_wells:
            selected_wells.remove(well)
        else:
            selected_wells.add(well)
        refresh_plate()
        set_info()

    def wells_in_bbox(x0, y0, x1, y1):
        xmin, xmax = sorted((x0, x1))
        ymin, ymax = sorted((y0, y1))
        hits = []
        for well, items in well_items.items():
            cx, cy = items["center"]
            if xmin <= cx <= xmax and ymin <= cy <= ymax:
                hits.append(well)
        return hits

    def on_canvas_press(event):
        drag_rect["start"] = (event.x, event.y)
        if drag_rect["id"] is not None:
            canvas.delete(drag_rect["id"])
        drag_rect["id"] = canvas.create_rectangle(event.x, event.y, event.x, event.y, dash=(4, 2), outline="#3366cc")

    def on_canvas_drag(event):
        if drag_rect["id"] is None or drag_rect["start"] is None:
            return
        x0, y0 = drag_rect["start"]
        canvas.coords(drag_rect["id"], x0, y0, event.x, event.y)

    def on_canvas_release(event):
        if drag_rect["start"] is None:
            return
        x0, y0 = drag_rect["start"]
        moved = abs(event.x - x0) + abs(event.y - y0) > 8
        if drag_rect["id"] is not None:
            canvas.delete(drag_rect["id"])
            drag_rect["id"] = None
        drag_rect["start"] = None
        if moved:
            hits = wells_in_bbox(x0, y0, event.x, event.y)
            if not _event_adds_to_selection(event):
                selected_wells.clear()
            selected_wells.update(hits)
            refresh_plate()
            set_info()

    def on_well_click(well):
        def handler(_event):
            if not _event_adds_to_selection(_event):
                selected_wells.clear()
            toggle_well(well)
            meta = self.plate_metadata.get(well)
            if meta:
                messagebox.showinfo(
                    "Well Assignment",
                    f"Well {well}\n"
                    f"Sample: {meta.get('sample_name', '')}\n"
                    f"Dose curve: {meta.get('dose_curve', '')}\n"
                    f"Dose: {meta.get('dose', '')}\n"
                    f"Replicate: {meta.get('replicate', '')}\n"
                    f"Direction: {meta.get('dose_direction', '')}\n"
                    f"Excluded: {bool(meta.get('excluded', False))}",
                )
            return "break"
        return handler

    def sorted_selected_wells():
        return sorted(selected_wells, key=lambda w: (w[0], int(w[1:])))

    def apply_metadata():
        if not selected_wells:
            info_var.set("No wells selected.")
            return
        self._push_undo_state()
        for well in sorted_selected_wells():
            self.plate_metadata.setdefault(well, {})
            self.plate_metadata[well]["sample_name"] = sample_name_var.get().strip()
        refresh_plate()
        info_var.set(f"Applied metadata to {len(selected_wells)} wells.")
        self._mark_state_changed(f"Updated sample names for {len(selected_wells)} wells.")

    def apply_dose_curve():
        wells = sorted_selected_wells()
        if not wells:
            info_var.set("No wells selected.")
            return
        sample_name = sample_name_var.get().strip()
        if not sample_name:
            info_var.set("Enter a sample name first.")
            return
        curve_name = sample_name
        direction = direction_var.get().strip().lower()
        if direction not in {"horizontal", "vertical"}:
            info_var.set("Direction must be horizontal or vertical.")
            return
        n_points = max(int(curve_points_var.get()), 1)
        top_dose = float(top_dose_var.get())
        dilution = float(dilution_var.get())
        if dilution <= 0:
            info_var.set("Dilution must be > 0.")
            return

        self._push_undo_state()
        grouped = {}
        for well in wells:
            row = well[0]
            col = int(well[1:])
            key = row if direction == "horizontal" else col
            grouped.setdefault(key, []).append(well)

        sorted_groups = []
        for key, group_wells in grouped.items():
            if direction == "horizontal":
                group_sorted = sorted(group_wells, key=lambda w: int(w[1:]))
            else:
                group_sorted = sorted(group_wells, key=lambda w: w[0])
            sorted_groups.append((key, group_sorted))
        sorted_groups.sort(key=lambda item: item[0])

        for replicate_idx, (_key, group_wells) in enumerate(sorted_groups, start=1):
            for point_idx, well in enumerate(group_wells[:n_points]):
                dose_value = top_dose / (dilution ** point_idx)
                self.plate_metadata.setdefault(well, {})
                self.plate_metadata[well]["sample_name"] = sample_name
                self.plate_metadata[well]["dose_curve"] = curve_name
                self.plate_metadata[well]["dose"] = dose_value
                self.plate_metadata[well]["replicate"] = replicate_idx
                self.plate_metadata[well]["dose_direction"] = direction
        self.dose_curve_definitions[sample_name] = {
            "sample_name": sample_name,
            "direction": direction,
            "points": n_points,
            "top_dose": top_dose,
            "dilution": dilution,
            "wells": wells,
        }
        refresh_plate()
        refresh_curve_panel()
        info_var.set(f"Assigned sample '{sample_name}' to {len(wells)} wells with {direction} dose progression.")
        self._mark_state_changed(f"Updated dose curve metadata for {sample_name}.")

    def export_metadata():
        if not self.plate_metadata:
            messagebox.showinfo("Plate Map", "No metadata to export.")
            return
        filename = filedialog.asksaveasfilename(
            defaultextension=".csv",
            filetypes=[("CSV files", "*.csv")],
            initialfile="plate_map_metadata.csv",
        )
        if not filename:
            return
        rows = []
        for well, meta in sorted(self.plate_metadata.items(), key=lambda item: (item[0][0], int(item[0][1:]))):
            row = {"well": well}
            row.update(meta)
            rows.append(row)
        try:
            pd.DataFrame(rows).to_csv(filename, index=False)
            info_var.set(f"Saved plate metadata to {filename}")
        except Exception as exc:
            info_var.set(f"Failed to save plate metadata: {type(exc).__name__}: {exc}")

    def refresh_curve_panel():
        curve_text.configure(state="normal")
        curve_text.delete("1.0", tk.END)
        if not self.dose_curve_definitions:
            curve_text.insert("1.0", "No dose curves assigned yet.")
        else:
            for key, definition in sorted(self.dose_curve_definitions.items()):
                wells_text = ", ".join(definition["wells"])
                curve_text.insert(
                    tk.END,
                    f"{key}\n"
                    f"  direction: {definition['direction']}\n"
                    f"  points: {definition['points']}\n"
                    f"  top dose: {definition['top_dose']}\n"
                    f"  dilution: {definition['dilution']}\n"
                    f"  wells: {wells_text}\n\n",
                )
        curve_text.configure(state="disabled")

    content.columnconfigure(0, weight=1)
    canvas = tk.Canvas(content, width=760, height=430, bg="white")
    canvas.grid(row=0, column=0, padx=0, pady=(0, 10), sticky="ew")
    control = ttk.Frame(content, padding=10)
    control.grid(row=1, column=0, sticky="ew")

    margin_x = 70
    margin_y = 55
    spacing_x = 54
    spacing_y = 42
    radius = 16

    for col in range(12):
        canvas.create_text(margin_x + col * spacing_x, 20, text=str(col + 1), font=("Helvetica", 11, "bold"))
    for row_idx, row_name in enumerate(row_names):
        canvas.create_text(26, margin_y + row_idx * spacing_y, text=row_name, font=("Helvetica", 11, "bold"))
        for col_idx in range(12):
            well = f"{row_name}{col_idx + 1}"
            cx = margin_x + col_idx * spacing_x
            cy = margin_y + row_idx * spacing_y
            oval = canvas.create_oval(cx - radius, cy - radius, cx + radius, cy + radius, fill=default_well_fill(well), outline="#888", width=1.5)
            label = canvas.create_text(cx, cy, text=well, font=("Helvetica", 8))
            canvas.tag_bind(oval, "<Button-1>", on_well_click(well))
            canvas.tag_bind(label, "<Button-1>", on_well_click(well))
            well_items[well] = {"oval": oval, "label": label, "center": (cx, cy)}

    canvas.bind("<ButtonPress-1>", on_canvas_press)
    canvas.bind("<B1-Motion>", on_canvas_drag)
    canvas.bind("<ButtonRelease-1>", on_canvas_release)
    refresh_plate()

    basic = ttk.LabelFrame(control, text="Sample Assignment", padding=10)
    basic.grid(row=0, column=0, sticky="ew", pady=(0, 10))
    ttk.Label(basic, text="Sample Name").grid(row=0, column=0, sticky="w")
    ttk.Entry(basic, textvariable=sample_name_var, width=24).grid(row=1, column=0, padx=4)
    ttk.Button(basic, text="Apply Sample Name", command=apply_metadata).grid(row=1, column=1, padx=6)

    dose_frame = ttk.LabelFrame(control, text="Dose Curve Parameters", padding=10)
    dose_frame.grid(row=1, column=0, sticky="ew")
    ttk.Label(dose_frame, text="Direction").grid(row=0, column=0, sticky="w")
    ttk.Combobox(dose_frame, textvariable=direction_var, values=["horizontal", "vertical"], state="readonly", width=12).grid(row=1, column=0, padx=4)
    ttk.Label(dose_frame, text="Number of Points").grid(row=0, column=1, sticky="w")
    ttk.Spinbox(dose_frame, from_=1, to=24, textvariable=curve_points_var, width=10).grid(row=1, column=1, padx=4)
    ttk.Label(dose_frame, text="Top Dose").grid(row=0, column=2, sticky="w")
    ttk.Entry(dose_frame, textvariable=top_dose_var, width=12).grid(row=1, column=2, padx=4)
    ttk.Label(dose_frame, text="Dilution Per Step").grid(row=0, column=3, sticky="w")
    ttk.Entry(dose_frame, textvariable=dilution_var, width=12).grid(row=1, column=3, padx=4)
    ttk.Button(dose_frame, text="Apply Dose Curve", command=apply_dose_curve).grid(row=1, column=4, padx=8)
    ttk.Button(dose_frame, text="Export Plate CSV", command=export_metadata).grid(row=1, column=5, padx=8)

    curve_frame = ttk.LabelFrame(content, text="Current Dose Curves", padding=10)
    curve_frame.grid(row=2, column=0, sticky="ew")
    curve_text = tk.Text(curve_frame, width=90, height=10, wrap="word")
    curve_text.grid(row=0, column=0, sticky="ew")
    curve_text.configure(state="disabled")
    refresh_curve_panel()

    ttk.Label(content, textvariable=info_var, wraplength=900).grid(row=3, column=0, sticky="w", pady=(10, 10))


def open_exclusion_editor(self):
    if not self.file_map:
        messagebox.showinfo("Excluded Wells", "Load a folder first.")
        return

    top = tk.Toplevel(self.root)
    top.title("Excluded Wells Editor")
    top.geometry("920x620")
    top.rowconfigure(0, weight=1)
    top.columnconfigure(0, weight=1)

    selected_wells = set()
    available_wells = {_get_well_name(relpath, self.instrument_var.get()) for relpath in self.file_map.values()}
    info_var = tk.StringVar(value="Select wells to exclude. Hold Shift or Control to add discontinuous groups.")
    drag_rect = {"id": None, "start": None}
    well_items = {}
    row_names = "ABCDEFGH"

    outer = ttk.Frame(top, padding=10)
    outer.grid(row=0, column=0, sticky="nsew")
    outer.rowconfigure(0, weight=1)
    outer.columnconfigure(0, weight=1)

    canvas = tk.Canvas(outer, width=760, height=430, bg="white")
    canvas.grid(row=0, column=0, sticky="nsew")

    def default_well_fill(well):
        if well in selected_wells:
            return "#ffd166"
        if well not in available_wells:
            return "#f3f3f3"
        if self.plate_metadata.get(well, {}).get("excluded", False):
            return "#7f7f7f"
        if self.plate_metadata.get(well, {}).get("sample_name", ""):
            return "#cfe8ff"
        return "#ffffff"

    def refresh_plate():
        for well, items in well_items.items():
            canvas.itemconfigure(items["oval"], fill=default_well_fill(well))

    def set_info():
        ordered = sorted(selected_wells, key=lambda w: (w[0], int(w[1:])))
        info_var.set(f"Selected wells ({len(ordered)}): {', '.join(ordered) if ordered else 'none'}")

    def wells_in_bbox(x0, y0, x1, y1):
        xmin, xmax = sorted((x0, x1))
        ymin, ymax = sorted((y0, y1))
        hits = []
        for well, items in well_items.items():
            cx, cy = items["center"]
            if xmin <= cx <= xmax and ymin <= cy <= ymax and well in available_wells:
                hits.append(well)
        return hits

    def on_canvas_press(event):
        drag_rect["start"] = (event.x, event.y)
        if drag_rect["id"] is not None:
            canvas.delete(drag_rect["id"])
        drag_rect["id"] = canvas.create_rectangle(event.x, event.y, event.x, event.y, dash=(4, 2), outline="#3366cc")

    def on_canvas_drag(event):
        if drag_rect["id"] is None or drag_rect["start"] is None:
            return
        x0, y0 = drag_rect["start"]
        canvas.coords(drag_rect["id"], x0, y0, event.x, event.y)

    def on_canvas_release(event):
        if drag_rect["start"] is None:
            return
        x0, y0 = drag_rect["start"]
        moved = abs(event.x - x0) + abs(event.y - y0) > 8
        if drag_rect["id"] is not None:
            canvas.delete(drag_rect["id"])
            drag_rect["id"] = None
        drag_rect["start"] = None
        if moved:
            hits = wells_in_bbox(x0, y0, event.x, event.y)
            if not _event_adds_to_selection(event):
                selected_wells.clear()
            selected_wells.update(hits)
            refresh_plate()
            set_info()

    def on_well_click(well):
        def handler(event):
            if well not in available_wells:
                return "break"
            if not _event_adds_to_selection(event):
                selected_wells.clear()
            if well in selected_wells:
                selected_wells.remove(well)
            else:
                selected_wells.add(well)
            refresh_plate()
            set_info()
            meta = self.plate_metadata.get(well, {})
            messagebox.showinfo(
                "Well Status",
                f"Well {well}\n"
                f"Sample: {meta.get('sample_name', '')}\n"
                f"Excluded: {bool(meta.get('excluded', False))}",
            )
            return "break"
        return handler

    def apply_excluded(excluded_value):
        if not selected_wells:
            info_var.set("No wells selected.")
            return
        self._push_undo_state()
        for well in selected_wells:
            self.plate_metadata.setdefault(well, {})
            self.plate_metadata[well]["excluded"] = bool(excluded_value)
        refresh_plate()
        self.update_heatmap()
        info_var.set(f"{'Excluded' if excluded_value else 'Included'} {len(selected_wells)} wells for downstream analysis.")
        self._mark_state_changed(f"{'Excluded' if excluded_value else 'Included'} {len(selected_wells)} wells.")

    margin_x = 70
    margin_y = 55
    spacing_x = 54
    spacing_y = 42
    radius = 16

    for col in range(12):
        canvas.create_text(margin_x + col * spacing_x, 20, text=str(col + 1), font=("Helvetica", 11, "bold"))
    for row_idx, row_name in enumerate(row_names):
        canvas.create_text(26, margin_y + row_idx * spacing_y, text=row_name, font=("Helvetica", 11, "bold"))
        for col_idx in range(12):
            well = f"{row_name}{col_idx + 1}"
            cx = margin_x + col_idx * spacing_x
            cy = margin_y + row_idx * spacing_y
            oval = canvas.create_oval(cx - radius, cy - radius, cx + radius, cy + radius, fill=default_well_fill(well), outline="#888", width=1.5)
            label = canvas.create_text(cx, cy, text=well, font=("Helvetica", 8))
            canvas.tag_bind(oval, "<Button-1>", on_well_click(well))
            canvas.tag_bind(label, "<Button-1>", on_well_click(well))
            well_items[well] = {"oval": oval, "label": label, "center": (cx, cy)}

    canvas.bind("<ButtonPress-1>", on_canvas_press)
    canvas.bind("<B1-Motion>", on_canvas_drag)
    canvas.bind("<ButtonRelease-1>", on_canvas_release)
    refresh_plate()

    controls = ttk.Frame(outer, padding=(0, 10, 0, 0))
    controls.grid(row=1, column=0, sticky="ew")
    ttk.Button(controls, text="Exclude Selected", command=lambda: apply_excluded(True)).grid(row=0, column=0, padx=(0, 8))
    ttk.Button(controls, text="Include Selected", command=lambda: apply_excluded(False)).grid(row=0, column=1, padx=(0, 8))
    ttk.Label(controls, textvariable=info_var, wraplength=820).grid(row=1, column=0, columnspan=2, sticky="w", pady=(10, 0))
