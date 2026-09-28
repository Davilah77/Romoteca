from __future__ import annotations

import csv
import hashlib
import json
import os
import queue
import shutil
import subprocess
import sys
import tempfile
import threading
import tkinter as tk
import urllib.request
import webbrowser
from dataclasses import dataclass, field
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from . import __version__
from .dat_parser import DatError, load_dat
from .i18n import Translator
from .matcher import compare_catalog, find_unknown_files
from .models import DatCatalog, GameResult, GameState, ScanSummary, ScannedFile
from .online_sources import OnlineDat, download_dat, list_github_dats, list_redump_dats
from .scanner import ScanCancelled, scan_folder
from .settings import load_settings, save_settings


@dataclass
class CollectionSession:
    catalog: DatCatalog
    rom_folder: Path | None = None
    results: list[GameResult] = field(default_factory=list)
    unknown_files: list[ScannedFile] = field(default_factory=list)
    summary: ScanSummary | None = None

    @property
    def key(self) -> str:
        return self.catalog.source_path.name


def application_directory() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[1]


def resource_path(name: str) -> Path:
    base = Path(getattr(sys, "_MEIPASS", application_directory()))
    return base / name


class RomotecaApp(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.settings = load_settings()
        self.language = self.settings.get("language", "en")
        self.tr = Translator(self.language)
        self.theme_mode = self.settings.get("theme_mode", "system")
        self.dark_mode = self._theme_is_dark(self.theme_mode)
        self.scan_workers = self.settings.get("scan_workers", "auto")
        self.collections: dict[str, CollectionSession] = {}
        self.current_key: str | None = None
        self.events: queue.Queue[tuple] = queue.Queue()
        self.cancel_event = threading.Event()
        self.auto_bios = bool(self.settings.get("auto_bios", True))
        stored_bios = self.settings.get("bios_folder")
        self.manual_bios_folder = Path(stored_bios) if stored_bios else None
        self.dats_directory = application_directory() / "dats"
        self.dats_directory.mkdir(parents=True, exist_ok=True)

        self.title(f"Romoteca {__version__}")
        icon = resource_path("packaging/Romoteca.ico")
        if icon.is_file():
            try:
                self.iconbitmap(default=str(icon))
            except tk.TclError:
                pass
        self.geometry(self.settings.get("window_geometry", "1180x720"))
        self.minsize(900, 560)
        self._configure_style()
        self._create_icons()
        self._build_ui()
        self._load_local_dats()
        self._translate_ui()
        self._restore_layout()
        self.protocol("WM_DELETE_WINDOW", self._close_app)
        self.after(100, self._process_events)

    @staticmethod
    def _system_prefers_dark() -> bool:
        if sys.platform != "win32":
            return False
        try:
            import winreg
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize") as key:
                return int(winreg.QueryValueEx(key, "AppsUseLightTheme")[0]) == 0
        except (OSError, ValueError):
            return False

    @classmethod
    def _theme_is_dark(cls, mode: str) -> bool:
        return mode == "dark" or (mode == "system" and cls._system_prefers_dark())

    def _set_native_titlebar(self) -> None:
        if sys.platform != "win32":
            return
        try:
            import ctypes
            hwnd = ctypes.windll.user32.GetParent(self.winfo_id())
            value = ctypes.c_int(1 if self.dark_mode else 0)
            ctypes.windll.dwmapi.DwmSetWindowAttribute(hwnd, 20, ctypes.byref(value), ctypes.sizeof(value))
        except (AttributeError, OSError):
            pass

    def _close_app(self) -> None:
        self.settings["window_geometry"] = self.geometry()
        self.settings["collection_tree_columns"] = {column: self.collection_tree.column(column, "width") for column in ("name", "have")}
        self.settings["result_tree_columns"] = {column: self.result_tree.column(column, "width") for column in ("#0", "status", "game", "have", "detail")}
        try:
            self.settings["pane_sash"] = self.main_pane.sashpos(0)
        except tk.TclError:
            pass
        save_settings(self.settings)
        self.destroy()

    def _restore_layout(self) -> None:
        for column, width in self.settings.get("collection_tree_columns", {}).items():
            if column in ("name", "have"):
                self.collection_tree.column(column, width=int(width))
        for column, width in self.settings.get("result_tree_columns", {}).items():
            if column in ("#0", "status", "game", "have", "detail"):
                self.result_tree.column(column, width=int(width))
        try:
            self.main_pane.sashpos(0, int(self.settings.get("pane_sash", 290)))
        except (tk.TclError, ValueError):
            pass

    @property
    def current(self) -> CollectionSession | None:
        return self.collections.get(self.current_key or "")

    def _configure_style(self) -> None:
        style = ttk.Style(self)
        if self.dark_mode and "clam" in style.theme_names():
            style.theme_use("clam")
        elif "vista" in style.theme_names():
            style.theme_use("vista")
        if self.dark_mode:
            background, foreground, field = "#202124", "#f1f3f4", "#303134"
            self.configure(background=background)
            self.option_add("*Menu.background", background)
            self.option_add("*Menu.foreground", foreground)
            self.option_add("*Menu.activeBackground", "#3c4043")
            self.option_add("*Menu.activeForeground", foreground)
            style.configure(".", background=background, foreground=foreground)
            style.configure("TFrame", background=background)
            style.configure("TLabel", background=background, foreground=foreground)
            style.configure("TLabelframe", background=background, foreground=foreground)
            style.configure("TLabelframe.Label", background=background, foreground=foreground)
            style.configure("TButton", background=field, foreground=foreground)
            style.configure("TEntry", fieldbackground=field, foreground=foreground)
            style.configure("TCombobox", fieldbackground=field, foreground=foreground)
            style.map("TCombobox", fieldbackground=[("readonly", field)], foreground=[("readonly", foreground)], selectbackground=[("readonly", "#245a9a")], selectforeground=[("readonly", "#ffffff")])
            style.configure("Muted.TLabel", background=background, foreground="#b8c0cc")
            style.configure("Status.TLabel", background=background, foreground=foreground)
            style.configure("Treeview", background=field, fieldbackground=field, foreground=foreground)
            style.map("Treeview", background=[("selected", "#245a9a")], foreground=[("selected", "#ffffff")])
            self._set_dynamic_tree_colors("dark")
        else:
            self.configure(background="#f0f0f0")
            self.option_add("*Menu.background", "#f0f0f0")
            self.option_add("*Menu.foreground", "#202124")
            style.configure("Muted.TLabel", background="#f0f0f0", foreground="#5b6470")
            style.configure("Status.TLabel", background="#f0f0f0", foreground="#202124")
            self._set_dynamic_tree_colors("light")
        style.configure("Title.TLabel", font=("Segoe UI", 16, "bold"))
        if not self.dark_mode:
            style.configure("Muted.TLabel", foreground="#5b6470")
        style.configure("Treeview", rowheight=27, font=("Segoe UI", 10))
        style.configure("Treeview.Heading", font=("Segoe UI", 10, "bold"))
        style.configure("Collection.Horizontal.TProgressbar", troughcolor="#e7edf3", background="#28a745", lightcolor="#28a745", darkcolor="#188038", thickness=14)

    def _folder_icon(self, color: str) -> tk.PhotoImage:
        image = tk.PhotoImage(width=18, height=16)
        image.put("#000000", to=(1, 4, 17, 15))
        image.put(color, to=(2, 5, 16, 14))
        image.put("#000000", to=(3, 1, 10, 5))
        image.put(color, to=(4, 2, 9, 5))
        image.put("#ffffff", to=(3, 6, 15, 7))
        return image

    def _create_icons(self) -> None:
        self.icons = {
            "complete": self._folder_icon("#36a852"),
            "partial": self._folder_icon("#f2b632"),
            "missing": self._folder_icon("#d94a48"),
            "unknown": self._folder_icon("#f2b632"),
            "clone": self._folder_icon("#f3f3f3"),
        }

    def _build_ui(self) -> None:
        self.menu_bar = tk.Menu(self)
        menu_background = "#202124" if self.dark_mode else "#f0f0f0"
        self.top_menu_frame = tk.Frame(self, background=menu_background, height=30)
        self.top_menu_frame.pack(fill="x", side="top")
        root = ttk.Frame(self, padding=(14, 10, 14, 0))
        root.pack(fill="both", expand=True)

        header = ttk.Frame(root)
        header.pack(fill="x", pady=(0, 10))
        ttk.Label(header, text="Romoteca", style="Title.TLabel").pack(side="left")
        self.subtitle_label = ttk.Label(header, style="Muted.TLabel")
        self.subtitle_label.pack(side="left", padx=(12, 0), pady=(7, 0))

        toolbar = ttk.Frame(root)
        toolbar.pack(fill="x", pady=(0, 10))
        self.import_button = ttk.Button(toolbar, command=self._import_dat)
        self.import_button.pack(side="left")
        self.online_button = ttk.Button(toolbar, command=self._download_online_dat)
        self.online_button.pack(side="left", padx=(8, 0))
        self.folder_button = ttk.Button(toolbar, command=self._choose_rom_folder)
        self.folder_button.pack(side="left", padx=(8, 0))
        self.scan_button = ttk.Button(toolbar, command=self._start_scan, state="disabled")
        self.scan_button.pack(side="left", padx=(8, 0))
        self.cancel_button = ttk.Button(toolbar, command=self.cancel_event.set, state="disabled")
        self.cancel_button.pack(side="left", padx=(8, 0))
        self.export_button = ttk.Button(toolbar, command=self._export_csv, state="disabled")
        self.export_button.pack(side="right")

        pane = self.main_pane = ttk.Panedwindow(root, orient="horizontal")
        pane.pack(fill="both", expand=True)
        self.left_panel = ttk.Frame(pane, width=290)
        self.main_panel = ttk.Frame(pane)
        pane.add(self.left_panel, weight=0)
        pane.add(self.main_panel, weight=1)

        self.collections_frame = ttk.LabelFrame(self.left_panel, padding=6)
        self.collections_frame.pack(fill="both", expand=True)
        self.collection_tree = ttk.Treeview(
            self.collections_frame, columns=("name", "have"), show="headings",
            selectmode="browse", height=20,
        )
        self.collection_tree.column("name", width=205)
        self.collection_tree.column("have", width=65, anchor="center", stretch=False)
        for tag, color in (("pending", "#30343b"), ("green", "#137333"), ("yellow", "#9a6200"), ("red", "#b42318")):
            self.collection_tree.tag_configure(tag, foreground=color, font=("Segoe UI", 10, "bold"))
        self.collection_tree.pack(fill="both", expand=True)
        self.collection_tree.bind("<<TreeviewSelect>>", self._select_collection)

        self.info_frame = ttk.LabelFrame(self.main_panel, padding=10)
        self.info_frame.pack(fill="x", padx=(10, 0))
        self.dat_var = tk.StringVar()
        self.folder_var = tk.StringVar()
        self.bios_var = tk.StringVar()
        self.percent_var = tk.StringVar(value="—")
        ttk.Label(self.info_frame, textvariable=self.dat_var).pack(anchor="w")
        ttk.Label(self.info_frame, textvariable=self.folder_var, style="Muted.TLabel").pack(anchor="w", pady=(4, 0))
        bios_line = ttk.Frame(self.info_frame)
        bios_line.pack(fill="x", pady=(2, 0))
        ttk.Label(bios_line, textvariable=self.bios_var, style="Muted.TLabel").pack(side="left")
        self.bios_status_label = tk.Label(bios_line, text="?", font=("Segoe UI", 11, "bold"), fg="#6b7280")
        self.bios_status_label.pack(side="left", padx=(8, 0))
        percent_line = ttk.Frame(self.info_frame)
        percent_line.pack(fill="x", pady=(8, 0))
        self.collection_progress = ttk.Progressbar(percent_line, mode="determinate", maximum=100, style="Collection.Horizontal.TProgressbar")
        self.collection_progress.pack(side="left", fill="x", expand=True)
        ttk.Label(percent_line, textvariable=self.percent_var, width=18, anchor="e", font=("Segoe UI", 9, "bold")).pack(side="left", padx=(10, 0))

        filters = ttk.Frame(self.main_panel, padding=(10, 10, 0, 8))
        filters.pack(fill="x")
        self.show_label = ttk.Label(filters)
        self.show_label.pack(side="left")
        self.filter_var = tk.StringVar()
        self.filter_box = ttk.Combobox(filters, textvariable=self.filter_var, state="readonly", width=17)
        self.filter_box.pack(side="left", padx=(8, 0))
        self.filter_box.bind("<<ComboboxSelected>>", lambda _event: self._fill_results())

        table_frame = ttk.Frame(self.main_panel)
        table_frame.pack(fill="both", expand=True, padx=(10, 0))
        self.result_tree = ttk.Treeview(
            table_frame, columns=("status", "game", "have", "detail"),
            show="tree headings", selectmode="browse",
        )
        self.result_tree.column("#0", width=34, anchor="center", stretch=False)
        self.result_tree.column("status", width=105, stretch=False)
        self.result_tree.column("game", width=380)
        self.result_tree.column("have", width=75, anchor="center", stretch=False)
        self.result_tree.column("detail", width=300)
        self.result_tree.tag_configure("complete", foreground="#137333")
        self.result_tree.tag_configure("partial", foreground="#9a6200")
        self.result_tree.tag_configure("missing", foreground="#b42318")
        self.result_tree.tag_configure("unknown", foreground="#9a6200")
        scrollbar = ttk.Scrollbar(table_frame, orient="vertical", command=self.result_tree.yview)
        self.result_tree.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side="right", fill="y")
        self.result_tree.pack(side="left", fill="both", expand=True)

        legend = ttk.Frame(self.main_panel, padding=(10, 8, 0, 6))
        legend.pack(fill="x")
        self.legend_title = ttk.Label(legend)
        self.legend_title.pack(side="left", padx=(0, 8))
        self.legend_labels: dict[str, ttk.Label] = {}
        for key in ("complete", "partial", "missing", "clone"):
            ttk.Label(legend, image=self.icons[key]).pack(side="left", padx=(8, 3))
            label = ttk.Label(legend)
            label.pack(side="left")
            self.legend_labels[key] = label

        self.status_var = tk.StringVar()
        self.status = ttk.Label(self, textvariable=self.status_var, style="Status.TLabel", padding=(14, 7))
        self.status.pack(side="bottom", fill="x")
        self.progress = ttk.Progressbar(self, mode="determinate")
        self._set_dynamic_tree_colors("dark" if self.dark_mode else "light")
        self._set_native_titlebar()

    def _set_dynamic_tree_colors(self, mode: str) -> None:
        if not hasattr(self, "collection_tree"):
            return
        if mode == "dark":
            colors = {"pending": "#e4e7eb", "green": "#49d17d", "yellow": "#f3c969", "red": "#ff6b6b"}
            result_colors = {"complete": "#49d17d", "partial": "#f3c969", "missing": "#ff6b6b", "unknown": "#f3c969"}
        else:
            colors = {"pending": "#30343b", "green": "#137333", "yellow": "#9a6200", "red": "#b42318"}
            result_colors = {"complete": "#137333", "partial": "#9a6200", "missing": "#b42318", "unknown": "#9a6200"}
        for tag, color in colors.items():
            self.collection_tree.tag_configure(tag, foreground=color, font=("Segoe UI", 10, "bold"))
        for tag, color in result_colors.items():
            self.result_tree.tag_configure(tag, foreground=color)
        if hasattr(self, "bios_status_label"):
            self.bios_status_label.configure(background="#202124" if mode == "dark" else "#f0f0f0")

    def _build_menu(self) -> None:
        self.menu_bar.delete(0, "end")
        for child in self.top_menu_frame.winfo_children():
            child.destroy()
        menu_background = "#202124" if self.dark_mode else "#f0f0f0"
        menu_foreground = "#f1f3f4" if self.dark_mode else "#202124"
        self.top_menu_frame.configure(background=menu_background)

        def add_menu_button(label: str, menu: tk.Menu) -> None:
            button = tk.Menubutton(self.top_menu_frame, text=label, menu=menu, relief="flat", bd=0, padx=8, pady=5, background=menu_background, foreground=menu_foreground, activebackground="#3c4043" if self.dark_mode else "#d9d9d9", activeforeground=menu_foreground)
            button.pack(side="left")

        file_menu = tk.Menu(self, tearoff=False)
        file_menu.add_command(label=self.tr("import_dat"), command=self._import_dat)
        file_menu.add_command(label=self.tr("download_online"), command=self._download_online_dat)
        file_menu.add_command(label=self.tr("select_roms"), command=self._choose_rom_folder)
        file_menu.add_command(label=self.tr("scan"), command=self._start_scan)
        file_menu.add_separator()
        file_menu.add_command(label=self.tr("export"), command=self._export_csv)
        file_menu.add_separator()
        file_menu.add_command(label=self.tr("exit"), command=self.destroy)
        add_menu_button(self.tr("file"), file_menu)

        settings_menu = tk.Menu(self, tearoff=False)
        settings_menu.add_command(label=self.tr("bios_folder"), command=self._choose_bios_folder)
        self.auto_bios_var = tk.BooleanVar(value=self.auto_bios)
        settings_menu.add_checkbutton(label=self.tr("auto_bios"), variable=self.auto_bios_var, command=self._toggle_auto_bios)
        workers_menu = tk.Menu(settings_menu, tearoff=False)
        self.scan_workers_var = tk.StringVar(value=str(self.scan_workers))
        for value, label in (("auto", self.tr("workers_auto")), ("2", "2"), ("4", "4"), ("8", "8"), ("12", "12")):
            workers_menu.add_radiobutton(label=label, value=value, variable=self.scan_workers_var, command=self._set_scan_workers)
        settings_menu.add_cascade(label=self.tr("scan_workers"), menu=workers_menu)
        theme_menu = tk.Menu(settings_menu, tearoff=False)
        self.theme_var = tk.StringVar(value=self.theme_mode)
        for value, label in (("system", self.tr("theme_system")), ("light", self.tr("theme_light")), ("dark", self.tr("theme_dark"))):
            theme_menu.add_radiobutton(label=label, value=value, variable=self.theme_var, command=self._set_theme)
        settings_menu.add_cascade(label=self.tr("theme"), menu=theme_menu)
        self.dark_mode_var = tk.BooleanVar(value=self.dark_mode)
        settings_menu.add_separator()
        settings_menu.add_command(label=self.tr("check_updates"), command=self._check_for_updates)
        add_menu_button(self.tr("settings"), settings_menu)

        language_menu = tk.Menu(self, tearoff=False)
        self.language_var = tk.StringVar(value=self.language)
        language_menu.add_radiobutton(label="English", value="en", variable=self.language_var, command=lambda: self._change_language("en"))
        language_menu.add_radiobutton(label="Español", value="es", variable=self.language_var, command=lambda: self._change_language("es"))
        language_menu.add_radiobutton(label="Français", value="fr", variable=self.language_var, command=lambda: self._change_language("fr"))
        language_menu.add_radiobutton(label="Deutsch", value="de", variable=self.language_var, command=lambda: self._change_language("de"))
        language_menu.add_radiobutton(label="Nederlands", value="nl", variable=self.language_var, command=lambda: self._change_language("nl"))
        language_menu.add_radiobutton(label="Русский", value="ru", variable=self.language_var, command=lambda: self._change_language("ru"))
        add_menu_button(self.tr("language"), language_menu)

        help_menu = tk.Menu(self, tearoff=False)
        help_menu.add_command(label=self.tr("about"), command=self._show_about)
        sites_menu = tk.Menu(help_menu, tearoff=False)
        for key, url in self._dat_websites():
            sites_menu.add_command(label=key, command=lambda target=url: webbrowser.open(target))
        help_menu.add_cascade(label=self.tr("dat_websites"), menu=sites_menu)
        add_menu_button(self.tr("help"), help_menu)

    @staticmethod
    def _dat_websites() -> tuple[tuple[str, str], ...]:
        return (
            ("Datomatic / No-Intro", "https://datomatic.no-intro.org/"),
            ("Redump", "https://redump.info/downloads"),
            ("TOSEC", "https://www.tosecdev.org/"),
        )

    def _set_scan_workers(self) -> None:
        self.scan_workers = self.scan_workers_var.get()
        self.settings["scan_workers"] = self.scan_workers
        save_settings(self.settings)

    def _set_theme(self) -> None:
        self.theme_mode = self.theme_var.get()
        self.dark_mode = self._theme_is_dark(self.theme_mode)
        self.settings["theme_mode"] = self.theme_mode
        save_settings(self.settings)
        self._configure_style()
        self._create_icons()
        self._translate_ui()

    def _toggle_dark_mode(self) -> None:
        self.theme_mode = "dark" if self.dark_mode_var.get() else "light"
        self._set_theme()

    def _translate_ui(self) -> None:
        self._build_menu()
        self.subtitle_label.configure(text=self.tr("app_subtitle"))
        self.import_button.configure(text=self.tr("import_dat"))
        self.online_button.configure(text=self.tr("download_online"))
        self.folder_button.configure(text=self.tr("select_roms"))
        self.scan_button.configure(text=self.tr("scan"))
        self.cancel_button.configure(text="Cancelar" if self.language == "es" else "Cancel")
        self.export_button.configure(text=self.tr("export"))
        self.collections_frame.configure(text=self.tr("collections"))
        self.info_frame.configure(text=self.tr("collection"))
        self.collection_tree.heading("name", text=self.tr("name"))
        self.collection_tree.heading("have", text=self.tr("have"))
        self.show_label.configure(text=self.tr("show"))
        filters = (self.tr("all"), self.tr("complete_plural"), self.tr("partial_plural"), self.tr("missing_plural"), self.tr("unknown_plural"))
        self.filter_box.configure(values=filters)
        self.filter_var.set(filters[0])
        self.result_tree.heading("#0", text="")
        self.result_tree.heading("status", text=self.tr("status"))
        self.result_tree.heading("game", text=self.tr("game"))
        self.result_tree.heading("have", text=self.tr("have"))
        self.result_tree.heading("detail", text=self.tr("detail"))
        self.legend_title.configure(text=self.tr("legend"))
        for key, label in self.legend_labels.items():
            label.configure(text=self.tr(key))
        self._show_current_info()
        self._fill_results()
        if not self.current:
            self.status_var.set(self.tr("ready"))

    def _change_language(self, language: str) -> None:
        self.language = language
        self.tr.set_language(language)
        self.settings["language"] = language
        save_settings(self.settings)
        self._translate_ui()

    def _show_about(self) -> None:
        messagebox.showinfo(self.tr("about"), self.tr("about_text", version=__version__), parent=self)

    def _check_for_updates(self) -> None:
        self.status_var.set(self.tr("checking_updates"))

        def worker() -> None:
            try:
                request = urllib.request.Request(
                    "https://api.github.com/repos/Davilah77/Romoteca/releases/latest",
                    headers={"Accept": "application/vnd.github+json", "User-Agent": "Romoteca"},
                )
                with urllib.request.urlopen(request, timeout=15) as response:
                    release = json.loads(response.read().decode("utf-8"))
                latest = str(release.get("tag_name", "")).lstrip("v")
                asset = next((item for item in release.get("assets", []) if item.get("name") == "Romoteca.exe"), None)
                self.events.put(("update_available", latest, asset, release.get("html_url", "")))
            except Exception as exc:
                self.events.put(("update_error", str(exc)))

        threading.Thread(target=worker, daemon=True).start()

    def _download_and_install_update(self, asset: dict, release_url: str) -> None:
        if not getattr(sys, "frozen", False):
            webbrowser.open(release_url)
            return
        target = Path(sys.executable).resolve()
        temporary = Path(tempfile.gettempdir()) / "Romoteca.new.exe"
        try:
            with urllib.request.urlopen(asset["browser_download_url"], timeout=60) as response:
                temporary.write_bytes(response.read())
            expected = str(asset.get("digest", "")).removeprefix("sha256:").lower()
            if expected:
                actual = hashlib.sha256(temporary.read_bytes()).hexdigest()
                if actual != expected:
                    raise ValueError("Downloaded update checksum does not match")
            script = temporary.with_suffix(".cmd")
            script.write_text(f'@echo off\r\ntimeout /t 2 /nobreak >nul\r\ncopy /y "{temporary}" "{target}" >nul\r\nstart "" "{target}"\r\ndel "%~f0"\r\n', encoding="utf-8")
            subprocess.Popen(["cmd", "/c", str(script)], creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            self.destroy()
        except Exception as exc:
            temporary.unlink(missing_ok=True)
            messagebox.showerror(self.tr("update_error_title"), str(exc), parent=self)

    def _load_local_dats(self) -> None:
        paths = sorted((*self.dats_directory.glob("*.dat"), *self.dats_directory.glob("*.xml")))
        for path in paths:
            self._add_catalog(path, show_errors=False)
        if self.collections and not self.current_key:
            first = next(iter(self.collections))
            self.collection_tree.selection_set(first)
            self.collection_tree.focus(first)
            self._activate_collection(first)

    def _add_catalog(self, path: Path, show_errors: bool = True) -> None:
        try:
            catalog = load_dat(path)
        except DatError as exc:
            if show_errors:
                messagebox.showerror(self.tr("dat_error"), str(exc), parent=self)
            return
        folders = self.settings.setdefault("collection_folders", {})
        stored = folders.get(path.name)
        session = CollectionSession(catalog=catalog, rom_folder=Path(stored) if stored else None)
        self._restore_session(session)
        self.collections[path.name] = session
        if self.collection_tree.exists(path.name):
            self.collection_tree.delete(path.name)
        self.collection_tree.insert("", "end", iid=path.name, values=(catalog.name, "—"), tags=("pending",))
        self._update_collection_row(session)

    def _import_dat(self) -> None:
        selected = filedialog.askopenfilename(title=self.tr("choose_dat"), filetypes=(("DAT/XML", "*.dat *.xml"), ("All files", "*.*")))
        if not selected:
            return
        source = Path(selected)
        destination = self.dats_directory / source.name
        try:
            if source.resolve() != destination.resolve():
                shutil.copy2(source, destination)
            self._add_catalog(destination)
        except OSError as exc:
            messagebox.showerror(self.tr("dat_error"), str(exc), parent=self)
            return
        self.collection_tree.selection_set(destination.name)
        self.collection_tree.focus(destination.name)
        self._activate_collection(destination.name)

    def _download_online_dat(self) -> None:
        if getattr(self, "online_window", None) and self.online_window.winfo_exists():
            self.online_window.lift()
            return
        window = self.online_window = tk.Toplevel(self)
        window.title(self.tr("download_online"))
        saved_geometry = self.settings.get("online_window_geometry")
        if saved_geometry:
            window.geometry(saved_geometry)
        else:
            self.update_idletasks()
            x = max(self.winfo_x() + (self.winfo_width() - 620) // 2, 0)
            y = max(self.winfo_y() + (self.winfo_height() - 180) // 2, 0)
            window.geometry(f"620x180+{x}+{y}")
        window.transient(self)
        window.grab_set()

        def close_online_window() -> None:
            self.settings["online_window_geometry"] = window.geometry()
            save_settings(self.settings)
            window.grab_release()
            window.destroy()

        window.protocol("WM_DELETE_WINDOW", close_online_window)
        frame = ttk.Frame(window, padding=14)
        frame.pack(fill="both", expand=True)
        source_var = tk.StringVar(value="Redump (official HTTPS)")
        platform_var = tk.StringVar()
        status_var = tk.StringVar(value=self.tr("online_loading"))
        ttk.Label(frame, text=self.tr("online_source")).grid(row=0, column=0, sticky="w", pady=4)
        source_box = ttk.Combobox(frame, textvariable=source_var, state="readonly", values=("Redump (official HTTPS)", "GitHub DAT Catalog · Redump", "GitHub DAT Catalog · No-Intro", "GitHub DAT Catalog · TOSEC", "GitHub DAT Catalog · TOSEC-ISO"), width=42)
        source_box.grid(row=0, column=1, sticky="ew", pady=4)
        ttk.Label(frame, text=self.tr("online_platform")).grid(row=1, column=0, sticky="w", pady=4)
        platform_box = ttk.Combobox(frame, textvariable=platform_var, state="readonly", width=42)
        platform_box.grid(row=1, column=1, sticky="ew", pady=4)
        ttk.Label(frame, textvariable=status_var, style="Muted.TLabel").grid(row=2, column=0, columnspan=2, sticky="w", pady=(5, 8))
        download_button = ttk.Button(frame, text=self.tr("download"), state="disabled")
        download_button.grid(row=3, column=1, sticky="e")
        frame.columnconfigure(1, weight=1)
        entries: list[OnlineDat] = []
        window.online_entries = entries
        window.online_status_var = status_var
        window.online_platform_box = platform_box
        window.online_download_button = download_button

        def load_entries(selected: str) -> None:
            try:
                if selected.startswith("Redump"):
                    loaded = list_redump_dats()
                else:
                    loaded = list_github_dats(selected.rsplit("· ", 1)[-1])
                self.events.put(("online_loaded", loaded))
            except Exception as exc:
                self.events.put(("online_error", str(exc)))

        def reload_entries(_event=None) -> None:
            download_button.configure(state="disabled")
            platform_box.configure(values=())
            platform_var.set("")
            status_var.set(self.tr("online_loading"))
            threading.Thread(target=load_entries, args=(source_var.get(),), daemon=True).start()

        def start_download() -> None:
            selected = platform_var.get()
            entry = next((item for item in getattr(window, "online_entries", []) if item.platform == selected), None)
            if not entry:
                return
            download_button.configure(state="disabled")
            status_var.set(self.tr("online_downloading"))
            destination = self.dats_directory / entry.filename
            if destination.exists():
                destination = destination.with_name(f"{destination.stem} (online){destination.suffix}")
            def worker() -> None:
                try:
                    path = download_dat(entry, destination)
                    self.events.put(("online_complete", path, window))
                except Exception as exc:
                    self.events.put(("online_error", str(exc)))
            threading.Thread(target=worker, daemon=True).start()

        source_box.bind("<<ComboboxSelected>>", reload_entries)
        download_button.configure(command=start_download)
        self.after(50, reload_entries)

    def _select_collection(self, _event=None) -> None:
        selected = self.collection_tree.selection()
        if selected:
            self._activate_collection(selected[0])

    def _activate_collection(self, key: str) -> None:
        self.current_key = key
        self._show_current_info()
        self._fill_results()
        self._update_buttons()
        self.status_var.set(self.tr("scan_ready"))

    def _show_current_info(self) -> None:
        current = self.current
        if not current:
            self.dat_var.set(self.tr("dat_none"))
            self.folder_var.set(self.tr("folder_none"))
            self.bios_var.set(self.tr("bios_none"))
            self._set_bios_indicator("unknown")
            self._update_collection_progress(None)
            return
        catalog = current.catalog
        version = f" · {catalog.version}" if catalog.version else ""
        self.dat_var.set(f"DAT: {catalog.name}{version} · {len(catalog.games):,} {self.tr('game').lower()}")
        self.folder_var.set(("Carpeta de ROMs: " if self.language == "es" else "ROM folder: ") + (str(current.rom_folder) if current.rom_folder else self.tr("folder_none").split(": ", 1)[-1]))
        bios = self._effective_bios_folder(current.rom_folder)
        self.bios_var.set(f"BIOS: {bios}" if bios else self.tr("bios_none"))
        self._set_bios_indicator(self._bios_state(current))
        self._update_collection_progress(current)

    def _set_bios_indicator(self, state: str) -> None:
        symbols = {"ok": ("✓", "#137333"), "partial": ("⚠", "#b7791f"), "missing": ("✕", "#b42318"), "unknown": ("?", "#6b7280")}
        symbol, color = symbols.get(state, symbols["unknown"])
        self.bios_status_label.configure(text=symbol, fg=color)

    def _bios_state(self, session: CollectionSession) -> str:
        bios = [result for result in session.results if "[bios]" in (result.game.name + " " + result.game.description).lower()]
        if not bios:
            return "unknown"
        if all(result.state == GameState.COMPLETE for result in bios):
            return "ok"
        if any(result.state == GameState.PARTIAL for result in bios) or any(result.state == GameState.COMPLETE for result in bios):
            return "partial"
        return "missing"

    def _update_collection_progress(self, session: CollectionSession | None) -> None:
        if not session or not session.summary:
            self.collection_progress.configure(value=0)
            self.percent_var.set("—")
            return
        summary = session.summary
        total = summary.complete + summary.partial + summary.missing
        percent = (summary.complete / total * 100) if total else 0
        self.collection_progress.configure(value=percent)
        self.percent_var.set(f"{percent:.1f}% ({summary.complete}/{total})")

    @staticmethod
    def _catalog_extensions(catalog: DatCatalog) -> set[str] | None:
        extensions = {Path(asset.name).suffix.lower() for game in catalog.games for asset in game.assets}
        return extensions or None

    def _choose_rom_folder(self) -> None:
        current = self.current
        if not current:
            return
        initial = current.rom_folder or self.settings.get("last_rom_folder") or Path.home()
        selected = filedialog.askdirectory(title=self.tr("choose_roms"), initialdir=str(initial), mustexist=True)
        if not selected:
            return
        current.rom_folder = Path(selected)
        current.results = []
        current.unknown_files = []
        current.summary = None
        self.settings["last_rom_folder"] = selected
        self.settings.setdefault("collection_folders", {})[current.key] = selected
        save_settings(self.settings)
        self._show_current_info()
        self._update_buttons()
        self.status_var.set(self.tr("folder_selected"))

    @staticmethod
    def _scanned_to_dict(item: ScannedFile) -> dict:
        return {"path": str(item.path), "display_name": item.display_name, "size": item.size, "crc": item.crc, "sha1": item.sha1, "archive_member": item.archive_member, "verifiable": item.verifiable}

    @staticmethod
    def _scanned_from_dict(data: dict) -> ScannedFile:
        return ScannedFile(path=Path(data["path"]), display_name=data.get("display_name", Path(data["path"]).name), size=int(data.get("size", 0)), crc=data.get("crc"), sha1=data.get("sha1"), archive_member=data.get("archive_member"), verifiable=bool(data.get("verifiable", True)))

    def _persist_session(self, session: CollectionSession) -> None:
        cache = self.settings.setdefault("scan_cache", {})
        cache[session.key] = {
            "folder": str(session.rom_folder) if session.rom_folder else None,
            "summary": session.summary.__dict__ if session.summary else None,
            "results": [{"game": session.catalog.games.index(result.game), "state": result.state.value, "found": result.found_assets, "expected": result.expected_assets, "matches": [self._scanned_to_dict(item) for item in result.matches]} for result in session.results],
            "unknown": [self._scanned_to_dict(item) for item in session.unknown_files],
        }
        save_settings(self.settings)

    def _restore_session(self, session: CollectionSession) -> None:
        cached = self.settings.get("scan_cache", {}).get(session.key)
        if not isinstance(cached, dict):
            return
        try:
            restored = []
            for item in cached.get("results", []):
                game = session.catalog.games[int(item["game"])]
                restored.append(GameResult(game=game, state=GameState(item["state"]), found_assets=int(item["found"]), expected_assets=int(item["expected"]), matches=[self._scanned_from_dict(match) for match in item.get("matches", [])]))
            summary = cached.get("summary")
            session.results = restored
            session.unknown_files = [self._scanned_from_dict(item) for item in cached.get("unknown", [])]
            session.summary = ScanSummary(**summary) if summary else None
        except (KeyError, TypeError, ValueError, IndexError):
            session.results, session.unknown_files, session.summary = [], [], None

    def _choose_bios_folder(self) -> None:
        initial = self.manual_bios_folder or Path.home()
        selected = filedialog.askdirectory(title=self.tr("choose_bios"), initialdir=str(initial), mustexist=True)
        if not selected:
            return
        self.manual_bios_folder = Path(selected)
        self.auto_bios = False
        self.settings["bios_folder"] = selected
        self.settings["auto_bios"] = False
        save_settings(self.settings)
        self._show_current_info()

    def _toggle_auto_bios(self) -> None:
        self.auto_bios = bool(self.auto_bios_var.get())
        self.settings["auto_bios"] = self.auto_bios
        save_settings(self.settings)
        self._show_current_info()

    def _effective_bios_folder(self, rom_folder: Path | None) -> Path | None:
        if self.auto_bios and rom_folder:
            roms_parent = rom_folder.parent
            if roms_parent.name.lower() == "roms":
                candidate = roms_parent.parent / "bios"
                if candidate.is_dir():
                    return candidate
        if self.manual_bios_folder and self.manual_bios_folder.is_dir():
            return self.manual_bios_folder
        return None

    def _update_buttons(self) -> None:
        current = self.current
        self.scan_button.configure(state="normal" if current and current.rom_folder else "disabled")
        self.folder_button.configure(state="normal" if current else "disabled")
        self.export_button.configure(state="normal" if current and current.results else "disabled")

    def _set_busy(self, busy: bool) -> None:
        state = "disabled" if busy else "normal"
        self.import_button.configure(state=state)
        self.online_button.configure(state=state)
        self.folder_button.configure(state=state)
        self.scan_button.configure(state="disabled" if busy else "normal")
        self.cancel_button.configure(state="normal" if busy else "disabled")
        if busy:
            self.progress.configure(value=0, maximum=100)
            self.progress.pack(side="bottom", fill="x")
        else:
            self.progress.pack_forget()
            self.progress.configure(value=0)
            self._update_buttons()

    def _start_scan(self) -> None:
        current = self.current
        if not current or not current.rom_folder:
            return
        self.cancel_event.clear()
        self._set_busy(True)
        self.status_var.set(self.tr("preparing"))
        threading.Thread(target=self._scan_worker, args=(current.key,), daemon=True).start()

    def _scan_worker(self, key: str) -> None:
        session = self.collections[key]
        assert session.rom_folder
        workers = None if self.scan_workers == "auto" else int(self.scan_workers)
        def progress(current: int, total: int, name: str) -> None:
            self.events.put(("progress", current, total, name))
        try:
            allowed_extensions = self._catalog_extensions(session.catalog)
            rom_scanned = scan_folder(session.rom_folder, progress=progress, cancelled=self.cancel_event.is_set, allowed_extensions=allowed_extensions, workers=workers)
            scanned = list(rom_scanned)
            needs_bios = any(
                "[bios]" in (game.name + " " + game.description).lower()
                for game in session.catalog.games
            )
            bios = self._effective_bios_folder(session.rom_folder) if needs_bios else None
            if bios and bios.resolve() != session.rom_folder.resolve():
                scanned.extend(scan_folder(bios, cancelled=self.cancel_event.is_set, allowed_extensions=allowed_extensions, workers=workers))
            results, summary = compare_catalog(session.catalog, scanned)
            # BIOS files belonging to other systems should not appear as unknown ROMs.
            unknown = find_unknown_files(results, rom_scanned)
            self.events.put(("complete", key, results, summary, unknown))
        except ScanCancelled:
            self.events.put(("cancelled",))
        except Exception as exc:
            self.events.put(("error", str(exc)))

    def _process_events(self) -> None:
        try:
            while True:
                event = self.events.get_nowait()
                if event[0] == "progress":
                    _, current, total, name = event
                    self.progress.configure(maximum=max(total, 1), value=current)
                    self.status_var.set(self.tr("scanning", current=current, total=total, name=name))
                elif event[0] == "complete":
                    _, key, results, summary, unknown = event
                    session = self.collections[key]
                    session.results, session.summary, session.unknown_files = results, summary, unknown
                    self._persist_session(session)
                    self._set_busy(False)
                    self._update_collection_row(session)
                    if key == self.current_key:
                        self._fill_results()
                        self._show_current_info()
                        self._show_summary(session)
                elif event[0] == "cancelled":
                    self._set_busy(False)
                    self.status_var.set(self.tr("cancelled"))
                elif event[0] == "error":
                    self._set_busy(False)
                    messagebox.showerror(self.tr("scan_error"), event[1], parent=self)
                    self.status_var.set(self.tr("scan_failed"))
                elif event[0] == "update_available":
                    latest, asset, release_url = event[1], event[2], event[3]
                    if not latest or latest == __version__ or not asset:
                        self.status_var.set(self.tr("updates_current"))
                    elif messagebox.askyesno(self.tr("update_available_title"), self.tr("update_available", version=latest), parent=self):
                        self.status_var.set(self.tr("updating"))
                        threading.Thread(target=self._download_and_install_update, args=(asset, release_url), daemon=True).start()
                    else:
                        self.status_var.set(self.tr("ready"))
                elif event[0] == "update_error":
                    self.status_var.set(self.tr("updates_failed"))
                    messagebox.showerror(self.tr("update_error_title"), event[1], parent=self)
                elif event[0] == "online_loaded":
                    window = getattr(self, "online_window", None)
                    if window and window.winfo_exists():
                        entries = event[1]
                        window.online_entries = entries
                        platforms = sorted({item.platform for item in entries})
                        window.online_platform_box.configure(values=platforms)
                        if platforms:
                            window.online_platform_box.set(platforms[0])
                            window.online_download_button.configure(state="normal")
                        window.online_status_var.set(self.tr("online_ready", count=len(platforms)))
                elif event[0] == "online_complete":
                    path, window = event[1], event[2]
                    if window.winfo_exists():
                        self.settings["online_window_geometry"] = window.geometry()
                        save_settings(self.settings)
                        window.grab_release()
                        window.destroy()
                    self._add_catalog(path)
                    self.collection_tree.selection_set(path.name)
                    self.collection_tree.focus(path.name)
                    self._activate_collection(path.name)
                    self.status_var.set(self.tr("online_saved", path=path.name))
                elif event[0] == "online_error":
                    window = getattr(self, "online_window", None)
                    if window and window.winfo_exists():
                        window.online_status_var.set(self.tr("online_failed"))
                        window.online_download_button.configure(state="normal")
                        messagebox.showerror(self.tr("online_error_title"), event[1], parent=window)
                    else:
                        messagebox.showerror(self.tr("online_error_title"), event[1], parent=self)
        except queue.Empty:
            pass
        self.after(100, self._process_events)

    def _update_collection_row(self, session: CollectionSession) -> None:
        if session.summary:
            total = session.summary.complete + session.summary.partial + session.summary.missing
            have = session.summary.complete + session.summary.partial
            tag = "green" if total and have == total else ("yellow" if have else "red")
            self.collection_tree.item(session.key, values=(session.catalog.name, f"{have}/{total}"), tags=(tag,))

    def _show_summary(self, session: CollectionSession) -> None:
        summary = session.summary
        if not summary:
            return
        total = summary.complete + summary.partial + summary.missing
        percent = (summary.complete / total * 100) if total else 0
        self.status_var.set(f"{self.tr('complete_plural')} {summary.complete:,}/{total:,} ({percent:.1f} %) · {self.tr('partial_plural')} {summary.partial:,} · {self.tr('missing_plural')} {summary.missing:,} · {self.tr('unknown_plural')} {summary.unknown:,}")

    def _filter_state(self) -> str:
        return {self.tr("all"): "all", self.tr("complete_plural"): "complete", self.tr("partial_plural"): "partial", self.tr("missing_plural"): "missing", self.tr("unknown_plural"): "unknown"}.get(self.filter_var.get(), "all")

    def _fill_results(self) -> None:
        if not hasattr(self, "result_tree"):
            return
        self.result_tree.delete(*self.result_tree.get_children())
        session = self.current
        if not session:
            return
        selected = self._filter_state()
        for result in session.results:
            key = {GameState.COMPLETE: "complete", GameState.PARTIAL: "partial", GameState.MISSING: "missing"}[result.state]
            if selected not in ("all", key):
                continue
            clone = result.game.clone_of is not None and result.state == GameState.COMPLETE
            icon_key = "clone" if clone else key
            status_key = "clone" if clone else key
            detail = ""
            if result.matches:
                first = result.matches[0]
                detail = first.path.name + (f" › {first.archive_member}" if first.archive_member else "")
            self.result_tree.insert("", "end", image=self.icons[icon_key], values=(self.tr(status_key), result.game.description, f"{result.found_assets}/{result.expected_assets}", detail), tags=(key,))
        if selected in ("all", "unknown"):
            for item in session.unknown_files:
                detail = str(item.path) + (f" › {item.archive_member}" if item.archive_member else "")
                self.result_tree.insert("", "end", image=self.icons["unknown"], values=(self.tr("unknown"), item.display_name, "—", detail), tags=("unknown",))

    def _export_csv(self) -> None:
        session = self.current
        if not session or not session.results:
            return
        selected = filedialog.asksaveasfilename(title=self.tr("export"), defaultextension=".csv", filetypes=(("CSV", "*.csv"),), initialfile="romoteca-report.csv")
        if not selected:
            return
        try:
            with open(selected, "w", newline="", encoding="utf-8-sig") as stream:
                writer = csv.writer(stream, delimiter=";")
                writer.writerow((self.tr("status"), self.tr("game"), "Found", "Expected", "Files"))
                for result in session.results:
                    files = " | ".join(str(match.path) + (f"::{match.archive_member}" if match.archive_member else "") for match in result.matches)
                    state_key = {
                        GameState.COMPLETE: "complete",
                        GameState.PARTIAL: "partial",
                        GameState.MISSING: "missing",
                    }[result.state]
                    writer.writerow((self.tr(state_key), result.game.description, result.found_assets, result.expected_assets, files))
        except OSError as exc:
            messagebox.showerror(self.tr("scan_error"), str(exc), parent=self)
            return
        self.status_var.set(self.tr("report_saved", path=selected))


def run() -> None:
    RomotecaApp().mainloop()
