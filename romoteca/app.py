from __future__ import annotations

import csv
import queue
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from . import __version__
from .dat_parser import DatError, load_dat
from .matcher import compare_catalog
from .models import DatCatalog, GameResult, GameState, ScanSummary
from .scanner import ScanCancelled, scan_folder
from .settings import load_settings, save_settings


class RomotecaApp(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title(f"Romoteca {__version__}")
        self.geometry("1050x680")
        self.minsize(820, 520)

        self.catalog: DatCatalog | None = None
        self.rom_folder: Path | None = None
        self.results: list[GameResult] = []
        self.summary: ScanSummary | None = None
        self.events: queue.Queue[tuple] = queue.Queue()
        self.cancel_event = threading.Event()
        self.settings = load_settings()

        self._configure_style()
        self._build_ui()
        self.after(100, self._process_events)

    def _configure_style(self) -> None:
        style = ttk.Style(self)
        if "vista" in style.theme_names():
            style.theme_use("vista")
        style.configure("Title.TLabel", font=("Segoe UI", 16, "bold"))
        style.configure("Muted.TLabel", foreground="#5b6470")
        style.configure("Treeview", rowheight=27, font=("Segoe UI", 10))
        style.configure("Treeview.Heading", font=("Segoe UI", 10, "bold"))

    def _build_ui(self) -> None:
        outer = ttk.Frame(self, padding=16)
        outer.pack(fill="both", expand=True)

        header = ttk.Frame(outer)
        header.pack(fill="x")
        ttk.Label(header, text="Romoteca", style="Title.TLabel").pack(side="left")
        ttk.Label(
            header, text="Inventario seguro de colecciones", style="Muted.TLabel"
        ).pack(side="left", padx=(12, 0), pady=(7, 0))

        toolbar = ttk.Frame(outer, padding=(0, 14, 0, 10))
        toolbar.pack(fill="x")
        self.dat_button = ttk.Button(toolbar, text="Cargar DAT", command=self._choose_dat)
        self.dat_button.pack(side="left")
        self.folder_button = ttk.Button(
            toolbar, text="Seleccionar carpeta", command=self._choose_folder
        )
        self.folder_button.pack(side="left", padx=(8, 0))
        self.scan_button = ttk.Button(
            toolbar, text="Escanear", command=self._start_scan, state="disabled"
        )
        self.scan_button.pack(side="left", padx=(8, 0))
        self.cancel_button = ttk.Button(
            toolbar, text="Cancelar", command=self.cancel_event.set, state="disabled"
        )
        self.cancel_button.pack(side="left", padx=(8, 0))
        self.export_button = ttk.Button(
            toolbar, text="Exportar CSV", command=self._export_csv, state="disabled"
        )
        self.export_button.pack(side="right")

        info = ttk.LabelFrame(outer, text="Colección", padding=10)
        info.pack(fill="x")
        self.dat_var = tk.StringVar(value="DAT: sin seleccionar")
        self.folder_var = tk.StringVar(value="Carpeta: sin seleccionar")
        ttk.Label(info, textvariable=self.dat_var).pack(anchor="w")
        ttk.Label(info, textvariable=self.folder_var, style="Muted.TLabel").pack(
            anchor="w", pady=(4, 0)
        )

        filters = ttk.Frame(outer, padding=(0, 10, 0, 8))
        filters.pack(fill="x")
        ttk.Label(filters, text="Mostrar:").pack(side="left")
        self.filter_var = tk.StringVar(value="Todos")
        filter_box = ttk.Combobox(
            filters,
            textvariable=self.filter_var,
            values=("Todos", "Completos", "Incompletos", "Faltan"),
            state="readonly",
            width=16,
        )
        filter_box.pack(side="left", padx=(8, 0))
        filter_box.bind("<<ComboboxSelected>>", lambda _event: self._fill_table())

        self.tree = ttk.Treeview(
            outer,
            columns=("state", "game", "have", "detail"),
            show="headings",
            selectmode="browse",
        )
        self.tree.heading("state", text="Estado")
        self.tree.heading("game", text="Juego")
        self.tree.heading("have", text="Tengo")
        self.tree.heading("detail", text="Detalle")
        self.tree.column("state", width=110, stretch=False)
        self.tree.column("game", width=430)
        self.tree.column("have", width=80, anchor="center", stretch=False)
        self.tree.column("detail", width=280)
        self.tree.tag_configure("complete", foreground="#137333")
        self.tree.tag_configure("partial", foreground="#a15c00")
        self.tree.tag_configure("missing", foreground="#a61b1b")
        scrollbar = ttk.Scrollbar(outer, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=scrollbar.set)
        self.tree.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

        self.status_var = tk.StringVar(value="Carga un DAT y selecciona una carpeta.")
        self.status = ttk.Label(self, textvariable=self.status_var, padding=(16, 8))
        self.status.pack(side="bottom", fill="x")
        self.progress = ttk.Progressbar(self, mode="determinate")
        self.progress.pack(side="bottom", fill="x")

    def _choose_dat(self) -> None:
        selected = filedialog.askopenfilename(
            title="Seleccionar archivo DAT",
            filetypes=(("Archivos DAT/XML", "*.dat *.xml"), ("Todos", "*.*")),
        )
        if not selected:
            return
        try:
            self.catalog = load_dat(selected)
        except DatError as exc:
            messagebox.showerror("DAT no válido", str(exc), parent=self)
            return
        version = f" · {self.catalog.version}" if self.catalog.version else ""
        self.dat_var.set(
            f"DAT: {self.catalog.name}{version} · "
            f"{len(self.catalog.games):,} juegos · {self.catalog.asset_count:,} archivos"
        )
        self.results.clear()
        self._fill_table()
        self._update_scan_button()
        self.status_var.set("DAT cargado. Selecciona una carpeta o inicia el escaneo.")

    def _choose_folder(self) -> None:
        initial = self.settings.get("last_rom_folder") or str(Path.home())
        selected = filedialog.askdirectory(
            title="Seleccionar carpeta de ROMs", initialdir=initial, mustexist=True
        )
        if not selected:
            return
        self.rom_folder = Path(selected)
        self.folder_var.set(f"Carpeta: {self.rom_folder}")
        self.settings["last_rom_folder"] = str(self.rom_folder)
        save_settings(self.settings)
        self._update_scan_button()
        self.status_var.set("Carpeta seleccionada. Pulsa Escanear cuando quieras.")

    def _update_scan_button(self) -> None:
        state = "normal" if self.catalog and self.rom_folder else "disabled"
        self.scan_button.configure(state=state)

    def _set_busy(self, busy: bool) -> None:
        state = "disabled" if busy else "normal"
        self.dat_button.configure(state=state)
        self.folder_button.configure(state=state)
        self.scan_button.configure(state="disabled" if busy else "normal")
        self.cancel_button.configure(state="normal" if busy else "disabled")
        if not busy:
            self._update_scan_button()

    def _start_scan(self) -> None:
        if not self.catalog or not self.rom_folder:
            return
        self.cancel_event.clear()
        self.progress.configure(value=0, maximum=100)
        self._set_busy(True)
        self.status_var.set("Preparando el escaneo…")
        threading.Thread(target=self._scan_worker, daemon=True).start()

    def _scan_worker(self) -> None:
        assert self.catalog and self.rom_folder

        def progress(current: int, total: int, name: str) -> None:
            self.events.put(("progress", current, total, name))

        try:
            scanned = scan_folder(
                self.rom_folder,
                progress=progress,
                cancelled=self.cancel_event.is_set,
            )
            results, summary = compare_catalog(self.catalog, scanned)
            self.events.put(("complete", results, summary))
        except ScanCancelled:
            self.events.put(("cancelled",))
        except Exception as exc:  # Keep worker failures inside the GUI.
            self.events.put(("error", str(exc)))

    def _process_events(self) -> None:
        try:
            while True:
                event = self.events.get_nowait()
                if event[0] == "progress":
                    _, current, total, name = event
                    self.progress.configure(maximum=max(total, 1), value=current)
                    self.status_var.set(f"Escaneando {current:,}/{total:,}: {name}")
                elif event[0] == "complete":
                    _, self.results, self.summary = event
                    self._set_busy(False)
                    self._fill_table()
                    self.export_button.configure(state="normal")
                    self._show_summary()
                elif event[0] == "cancelled":
                    self._set_busy(False)
                    self.status_var.set("Escaneo cancelado. No se ha modificado ningún archivo.")
                elif event[0] == "error":
                    self._set_busy(False)
                    messagebox.showerror("Error durante el escaneo", event[1], parent=self)
                    self.status_var.set("No se pudo completar el escaneo.")
        except queue.Empty:
            pass
        self.after(100, self._process_events)

    def _show_summary(self) -> None:
        if not self.summary:
            return
        total = self.summary.complete + self.summary.partial + self.summary.missing
        percent = (self.summary.complete / total * 100) if total else 0
        self.status_var.set(
            f"Completos {self.summary.complete:,}/{total:,} ({percent:.1f} %) · "
            f"Incompletos {self.summary.partial:,} · Faltan {self.summary.missing:,} · "
            f"No identificados {self.summary.unknown:,} · "
            f"Sin verificar {self.summary.unverified_containers:,}"
        )

    def _fill_table(self) -> None:
        self.tree.delete(*self.tree.get_children())
        selected_filter = self.filter_var.get()
        allowed = {
            "Completos": GameState.COMPLETE,
            "Incompletos": GameState.PARTIAL,
            "Faltan": GameState.MISSING,
        }.get(selected_filter)
        for result in self.results:
            if allowed and result.state != allowed:
                continue
            detail = ""
            if result.matches:
                first = result.matches[0]
                detail = first.path.name
                if first.archive_member:
                    detail += f" › {first.archive_member}"
            tag = {
                GameState.COMPLETE: "complete",
                GameState.PARTIAL: "partial",
                GameState.MISSING: "missing",
            }[result.state]
            self.tree.insert(
                "",
                "end",
                values=(
                    result.state.value,
                    result.game.description,
                    f"{result.found_assets}/{result.expected_assets}",
                    detail,
                ),
                tags=(tag,),
            )

    def _export_csv(self) -> None:
        if not self.results:
            return
        selected = filedialog.asksaveasfilename(
            title="Guardar informe",
            defaultextension=".csv",
            filetypes=(("CSV", "*.csv"),),
            initialfile="informe_romoteca.csv",
        )
        if not selected:
            return
        try:
            with open(selected, "w", newline="", encoding="utf-8-sig") as stream:
                writer = csv.writer(stream, delimiter=";")
                writer.writerow(("Estado", "Juego", "Encontrados", "Esperados", "Archivos"))
                for result in self.results:
                    files = " | ".join(
                        str(match.path)
                        + (f"::{match.archive_member}" if match.archive_member else "")
                        for match in result.matches
                    )
                    writer.writerow(
                        (
                            result.state.value,
                            result.game.description,
                            result.found_assets,
                            result.expected_assets,
                            files,
                        )
                    )
        except OSError as exc:
            messagebox.showerror("No se pudo guardar", str(exc), parent=self)
            return
        self.status_var.set(f"Informe guardado en {selected}")


def run() -> None:
    app = RomotecaApp()
    app.mainloop()

