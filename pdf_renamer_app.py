#!/usr/bin/env python3
"""
Pdf Rename, window.

Paste or browse to a folder, click Rename PDFs. Every PDF whose publication
year and title are confirmed against the publisher record is renamed to
YYYY_Title.pdf on the spot. The rest are listed with a proposed name and a
reason, and one button applies those too once you have looked at them.

All logic lives in renamer_core.py. This file only draws the window, runs
the job on a worker thread, and shows what happened.

Launch with an optional folder argument (dropping a folder on the desktop
shortcut does this):
    pythonw pdf_renamer_app.py "D:\\papers"
"""

from __future__ import annotations

import os
import queue
import subprocess
import sys
import threading
import traceback
from pathlib import Path

import tkinter as tk
from tkinter import messagebox, simpledialog, ttk

APP_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(APP_DIR))
import renamer_core as core  # noqa: E402

CRASH_LOG = APP_DIR / "pdf_renamer_error.log"

COLOURS = {
    core.RENAMED: "#1d6b34",
    core.NEEDS_LOOK: "#92400e",
    core.FAILED: "#b02c2c",
    core.NOT_RESOLVED: "#b02c2c",
    core.SKIPPED: "#4b5563",
}
# Light tints behind the legend chips, one per outcome colour above.
TINTS = {
    core.RENAMED: "#e6f4ea",
    core.NEEDS_LOOK: "#fdf1dc",
    core.FAILED: "#fbe9e9",
    core.NOT_RESOLVED: "#fbe9e9",
    core.SKIPPED: "#eef0f3",
}

# Flat palette: white surfaces, hairline borders, one teal accent for the
# main action and amber for the secondary one. No tinted bands.
NAVY = "#122c4a"
ACCENT = "#ca4a09"
ACCENT_HOVER = "#a83d07"
SLATE = "#334155"
SLATE_HOVER = "#1f2937"
RED = "#b91c1c"
RED_HOVER = "#991b1b"
BG = "#ffffff"
CARD = "#ffffff"
BORDER = "#e3e6eb"
TEXT = "#000000"
MUTED = "#000000"
STRIP = "#ffffff"
HEAD = "#f4f5f7"
STRIPE = "#fafbfc"
DISABLED = "#c3c9d2"
# Calibri sits smaller on the line than Segoe UI, so every size is one point
# larger than it would be in Segoe. Carlito is its metric twin on Linux.
UI_FONT = "Calibri" if sys.platform.startswith("win") else "Carlito"

# 64 px PNG of the app icon for the title bar and taskbar (Tk's .ico reader is
# picky, a PhotoImage is not), and a 28 px one for the window itself.
LOGO_PNG_B64 = (
    "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"
)
ICON_PNG_B64 = (
    "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"
)


def clean_path(raw: str) -> str:
    """Accept whatever a person pastes: quotes, file:///, trailing slash."""
    s = (raw or "").strip().strip('"').strip("'").strip()
    if s.lower().startswith("file:///"):
        s = s[8:].replace("/", os.sep)
        from urllib.parse import unquote
        s = unquote(s)
    s = os.path.expandvars(os.path.expanduser(s))
    return s.rstrip("\\/") if len(s) > 3 else s


class RoundButton(tk.Canvas):
    """A rounded, filled button. Tk's own buttons are always rectangles."""

    def __init__(self, parent, text, command, bg, hover, fg="white",
                 font=None, radius=9, padx=22, pady=7):
        super().__init__(parent, highlightthickness=0, bd=0, bg=parent.cget("bg"),
                         cursor="hand2")
        from tkinter import font as tkfont
        self._font = tkfont.Font(font=font or (UI_FONT, 11, "bold"))
        self._text, self._command = text, command
        self._bg, self._hover, self._fg = bg, hover, fg
        self._radius, self._enabled = radius, True
        w = self._font.measure(text) + 2 * padx
        h = self._font.metrics("linespace") + 2 * pady
        self.configure(width=w, height=h)
        self._shape = self._rounded(2, 2, w - 2, h - 2, radius, bg)
        self._label = self.create_text(w // 2, h // 2, text=text, fill=fg, font=self._font)
        self.bind("<Enter>", lambda e: self._paint(self._hover))
        self.bind("<Leave>", lambda e: self._paint(self._bg))
        self.bind("<Button-1>", self._click)

    def _rounded(self, x1, y1, x2, y2, r, fill):
        pts = [x1 + r, y1, x2 - r, y1, x2, y1, x2, y1 + r, x2, y2 - r, x2, y2,
               x2 - r, y2, x1 + r, y2, x1, y2, x1, y2 - r, x1, y1 + r, x1, y1]
        return self.create_polygon(pts, smooth=True, splinesteps=24, fill=fill, outline=fill)

    def _paint(self, colour):
        if self._enabled:
            self.itemconfigure(self._shape, fill=colour, outline=colour)

    def _click(self, event=None):
        if self._enabled and self._command:
            self._command()

    def set_enabled(self, enabled: bool):
        self._enabled = enabled
        colour = self._bg if enabled else DISABLED
        self.itemconfigure(self._shape, fill=colour, outline=colour)
        self.configure(cursor="hand2" if enabled else "arrow")

    # keep the two calls the rest of the window makes on ordinary buttons
    def config(self, **kw):
        if "state" in kw:
            self.set_enabled(kw.pop("state") == "normal")
        if kw:
            super().config(**kw)

    def __getitem__(self, key):
        if key == "state":
            return "normal" if self._enabled else "disabled"
        return super().__getitem__(key)


class Chip(tk.Canvas):
    """A rounded legend chip: tinted pill, coloured dot, dark text."""

    def __init__(self, parent, text, colour, tint, font=None):
        super().__init__(parent, highlightthickness=0, bd=0, bg=parent.cget("bg"))
        from tkinter import font as tkfont
        f = tkfont.Font(font=font or (UI_FONT, 10, "bold"))
        padx, pady, dot = 12, 4, 8
        w = dot + 7 + f.measure(text) + 2 * padx
        h = f.metrics("linespace") + 2 * pady
        self.configure(width=w, height=h)
        r = h // 2
        pts = [r, 0, w - r, 0, w, 0, w, r, w, h - r, w, h, w - r, h, r, h, 0, h, 0, h - r, 0, r, 0, 0]
        self.create_polygon(pts, smooth=True, splinesteps=24, fill=tint, outline=tint)
        cy = h // 2
        self.create_oval(padx, cy - dot // 2, padx + dot, cy + dot // 2, fill=colour, outline=colour)
        self.create_text(padx + dot + 7, cy, text=text, anchor="w", fill=colour, font=f)


def windows_folder_dialog(parent_hwnd: int, start: Path, title: str):
    """Windows' own file dialog, with files visible and a Select Folder button.

    The standard "Select Folder" dialog hides files, and the standard "Open"
    dialog cannot pick a folder. Windows' underlying dialog (IFileOpenDialog)
    can do both if asked directly: keep files visible, relabel the OK button,
    stop it insisting on an existing file, and read back the folder it is
    showing when OK is pressed. Returns the folder path, or None if cancelled.
    Raises on any COM failure so the caller can fall back.
    """
    import ctypes
    from ctypes import byref, c_void_p, c_ulong, c_wchar_p, POINTER

    class GUID(ctypes.Structure):
        _fields_ = [("d1", ctypes.c_ulong), ("d2", ctypes.c_ushort),
                    ("d3", ctypes.c_ushort), ("d4", ctypes.c_ubyte * 8)]

        def __init__(self, text):
            super().__init__()
            ctypes.oledll.ole32.CLSIDFromString(text, byref(self))

    def call(obj, index, argtypes, *args):
        vtbl = ctypes.cast(obj, POINTER(POINTER(c_void_p)))[0]
        proto = ctypes.WINFUNCTYPE(ctypes.HRESULT, c_void_p, *argtypes)
        return proto(vtbl[index])(obj, *args)

    ctypes.windll.ole32.CoInitializeEx(None, 2)          # apartment threaded; harmless if already done
    CLSID_FileOpenDialog = GUID("{DC1C5A9C-E88A-4DDE-A5A1-60F82A20AEF7}")
    IID_IFileOpenDialog = GUID("{D57C7288-D4AD-4768-BE02-9D969532D960}")
    IID_IShellItem = GUID("{43826D1E-E718-42EE-BC55-8E77BAF3B6D8}")
    FOS_NOCHANGEDIR, FOS_FORCEFILESYSTEM, FOS_NOVALIDATE = 0x8, 0x40, 0x100
    FOS_FILEMUSTEXIST, FOS_DONTADDTORECENT = 0x1000, 0x2000000
    SIGDN_FILESYSPATH = 0x80058000
    E_CANCELLED = -2147023673                              # HRESULT 0x800704C7

    dlg = c_void_p()
    ctypes.oledll.ole32.CoCreateInstance(byref(CLSID_FileOpenDialog), None, 1,
                                         byref(IID_IFileOpenDialog), byref(dlg))
    try:
        opts = c_ulong()
        call(dlg, 10, (POINTER(c_ulong),), byref(opts))                          # GetOptions
        flags = (opts.value | FOS_NOCHANGEDIR | FOS_FORCEFILESYSTEM | FOS_NOVALIDATE
                 | FOS_DONTADDTORECENT) & ~FOS_FILEMUSTEXIST
        call(dlg, 9, (c_ulong,), flags)                                           # SetOptions
        call(dlg, 17, (c_wchar_p,), title)                                        # SetTitle
        call(dlg, 18, (c_wchar_p,), "Select Folder")                              # SetOkButtonLabel
        call(dlg, 19, (c_wchar_p,), "Folder:")                                    # SetFileNameLabel
        call(dlg, 15, (c_wchar_p,), "Select this folder")                         # SetFileName
        item = c_void_p()
        try:
            ctypes.oledll.shell32.SHCreateItemFromParsingName(str(start), None,
                                                              byref(IID_IShellItem), byref(item))
            call(dlg, 12, (c_void_p,), item)                                      # SetFolder
        except OSError:
            pass
        finally:
            if item:
                call(item, 2, ())                                                 # Release
        try:
            call(dlg, 3, (c_void_p,), parent_hwnd)                                # Show
        except OSError as exc:
            if exc.args and exc.args[0] == E_CANCELLED:
                return None
            raise
        folder = c_void_p()
        call(dlg, 13, (POINTER(c_void_p),), byref(folder))                        # GetFolder
        try:
            name = c_wchar_p()
            call(folder, 5, (c_ulong, POINTER(c_wchar_p)), SIGDN_FILESYSPATH, byref(name))
            path = name.value
            ctypes.windll.ole32.CoTaskMemFree(name)
            return path
        finally:
            call(folder, 2, ())
    finally:
        call(dlg, 2, ())


class FolderPicker(tk.Toplevel):
    """A folder picker that also shows the files inside each folder.

    Windows' own "Select Folder" dialog lists folders only, and its "Open"
    dialog cannot select a folder. This one does both: double click a folder
    to go inside it, see its files, and press Select Folder to take the
    folder you are looking at (or the folder of a highlighted file).
    """

    def __init__(self, parent, start: Path, title="Select the folder holding your PDFs"):
        super().__init__(parent)
        self.title(title)
        self.result = None
        self.transient(parent)
        self.configure(bg=BG)
        sw, sh = self.winfo_screenwidth(), self.winfo_screenheight()
        w, h = min(900, int(sw * 0.6)), min(600, int(sh * 0.7))
        self.geometry(f"{w}x{h}+{(sw - w) // 2}+{(sh - h) // 3}")
        self.minsize(560, 380)
        self.current = start if start.is_dir() else Path.home()

        # path bar: Up, editable path, Go
        bar = tk.Frame(self, bg=BG, padx=12, pady=10)
        bar.pack(fill="x")
        ttk.Button(bar, text="Up", width=5, command=self.go_up).pack(side="left")
        self.path_var = tk.StringVar()
        entry = ttk.Entry(bar, textvariable=self.path_var, font=(UI_FONT, 11))
        entry.pack(side="left", fill="x", expand=True, padx=8)
        entry.bind("<Return>", lambda e: self.go_to(self.path_var.get()))
        ttk.Button(bar, text="Go", width=5, command=lambda: self.go_to(self.path_var.get())).pack(side="left")

        # quick places
        places = tk.Frame(self, bg=BG, padx=12)
        places.pack(fill="x")
        for label, target in self._places():
            b = tk.Label(places, text=label, bg=BG, fg="#1d4ed8", cursor="hand2",
                         font=(UI_FONT, 10, "underline"))
            b.pack(side="left", padx=(0, 14))
            b.bind("<Button-1>", lambda e, t=target: self.go_to(t))

        # listing: folders first, then files; PDFs marked
        frame = tk.Frame(self, bg=BORDER, highlightthickness=0)
        frame.pack(fill="both", expand=True, padx=12, pady=(8, 8))
        self.tree = ttk.Treeview(frame, columns=("kind", "size"), show="tree headings",
                                 selectmode="browse")
        self.tree.heading("#0", text="Name", anchor="w")
        self.tree.heading("kind", text="Type", anchor="w")
        self.tree.heading("size", text="Size", anchor="e")
        self.tree.column("#0", width=520, stretch=True)
        self.tree.column("kind", width=110, stretch=False)
        self.tree.column("size", width=90, stretch=False, anchor="e")
        vsb = ttk.Scrollbar(frame, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=vsb.set)
        self.tree.pack(side="left", fill="both", expand=True, padx=(1, 0), pady=1)
        vsb.pack(side="right", fill="y", pady=1, padx=(0, 1))
        self.tree.tag_configure("folder", foreground=TEXT, font=(UI_FONT, 11, "bold"))
        self.tree.tag_configure("pdf", foreground=COLOURS[core.RENAMED])
        self.tree.tag_configure("file", foreground="#6b7280")
        self.tree.bind("<Double-1>", self.on_double)
        self.tree.bind("<Return>", self.on_double)
        self.tree.bind("<BackSpace>", lambda e: self.go_up())

        # footer: count, buttons
        foot = tk.Frame(self, bg=BG, padx=12, pady=10)
        foot.pack(fill="x")
        self.count_var = tk.StringVar()
        tk.Label(foot, textvariable=self.count_var, bg=BG, fg=TEXT, font=(UI_FONT, 10),
                 anchor="w").pack(side="left", fill="x", expand=True)
        ttk.Button(foot, text="Cancel", command=self.destroy).pack(side="right")
        RoundButton(foot, "Select Folder", self.select, bg=ACCENT, hover=ACCENT_HOVER,
                    font=(UI_FONT, 11, "bold"), padx=18, pady=5).pack(side="right", padx=(0, 8))

        self.bind("<Escape>", lambda e: self.destroy())
        self.go_to(self.current)
        self.grab_set()
        self.tree.focus_set()

    @staticmethod
    def _places():
        home = Path.home()
        out = [("Home", home)]
        for name in ("Desktop", "Downloads", "Documents"):
            if (home / name).is_dir():
                out.append((name, home / name))
        for d in home.glob("OneDrive*"):
            if d.is_dir():
                out.append((d.name[:24], d))
        return out

    def go_to(self, target):
        target = Path(clean_path(str(target))) if isinstance(target, str) else target
        if target.is_file():
            target = target.parent
        if not target.is_dir():
            self.count_var.set("That folder does not exist.")
            return
        self.current = target
        self.path_var.set(str(target))
        self.tree.delete(*self.tree.get_children())
        folders, files = [], []
        try:
            for p in target.iterdir():
                try:
                    if p.name.startswith((".", "$", "__pycache__", core.LOG_PREFIX)):
                        continue
                    (folders if p.is_dir() else files).append(p)
                except OSError:
                    continue
        except PermissionError:
            self.count_var.set("Windows will not let this folder be read.")
            return
        folders.sort(key=lambda p: p.name.lower())
        files.sort(key=lambda p: p.name.lower())
        for f in folders:
            self.tree.insert("", "end", iid=str(f), text="  " + f.name, values=("Folder", ""), tags=("folder",))
        pdfs = 0
        for f in files:
            is_pdf = f.suffix.lower() == ".pdf"
            pdfs += is_pdf
            try:
                size = f.stat().st_size
                shown = f"{size / 1024:.0f} KB" if size < 1_048_576 else f"{size / 1_048_576:.1f} MB"
            except OSError:
                shown = ""
            self.tree.insert("", "end", iid=str(f), text="  " + f.name,
                             values=("PDF" if is_pdf else f.suffix.lstrip(".").upper() or "File", shown),
                             tags=("pdf" if is_pdf else "file",))
        self.count_var.set(f"{len(folders)} folders,  {len(files)} files,  {pdfs} PDFs in this folder")

    def go_up(self):
        if self.current.parent != self.current:
            self.go_to(self.current.parent)

    def on_double(self, event=None):
        sel = self.tree.focus()
        if sel and Path(sel).is_dir():
            self.go_to(Path(sel))

    def select(self):
        sel = self.tree.focus()
        chosen = self.current
        if sel:
            p = Path(sel)
            chosen = p if p.is_dir() else p.parent
        self.result = chosen
        self.destroy()


class App(tk.Tk):
    def __init__(self, initial_folder: str | None = None):
        super().__init__()
        self.settings = core.load_settings()
        self.result: core.RunResult | None = None
        self.worker: threading.Thread | None = None
        self.cancel = threading.Event()
        self.inbox: queue.Queue = queue.Queue()

        # The window's own header already shows the icon and the name, so the
        # Windows title bar carries only the icon and the close buttons.
        self.title(" ")
        sw, sh = self.winfo_screenwidth(), self.winfo_screenheight()
        scale = max(1.0, self.winfo_fpixels("1i") / 96.0)      # 1.5 on a 150 percent display
        w, h = min(int(sw * 0.72), int(1240 * scale)), min(int(sh * 0.78), int(800 * scale))
        self.geometry(f"{w}x{h}+{(sw - w) // 2}+{(sh - h) // 3}")
        self.minsize(int(880 * scale), int(520 * scale))
        # Window icons. Windows takes the title bar icon from the image whose
        # size matches its small icon size (16, 20 or 24 px depending on the
        # display scale) and the taskbar icon from the large size (32 to 64).
        # Handing Tk transparent images at the small sizes and the real icon
        # at the large ones leaves the title bar showing nothing, as asked,
        # while the taskbar and Alt+Tab keep the icon. The real icon is listed
        # first because Tk falls back to the first image when no size matches.
        try:
            self._icon64 = tk.PhotoImage(data=ICON_PNG_B64)
            self._icons = [self._icon64]
            for size in (32, 40, 48):
                img = self._icon64.copy()
                factor = 64 // size if 64 % size == 0 else 0
                if factor:
                    img = self._icon64.subsample(factor, factor)
                    self._icons.append(img)
            self._blanks = [tk.PhotoImage(width=n, height=n) for n in (16, 20, 24)]
            self.iconphoto(True, *self._icons, *self._blanks)
        except Exception:
            try:
                self.iconbitmap(str(APP_DIR / "app_icon.ico"))
            except Exception:
                pass

        self._build()
        self.report_callback_exception = self._tk_error

        start = initial_folder or self.settings.get("last_folder", "")
        if start and Path(start).is_dir():
            self.path_var.set(start)
            self._folder_changed()
        self.after(100, self._poll)

    # ---------------------------------------------------------------- UI --

    def _build(self):
        self.configure(bg=BG)
        style = ttk.Style(self)
        try:
            style.theme_use("vista" if sys.platform.startswith("win") else "clam")
        except tk.TclError:
            pass
        base = (UI_FONT, 11)
        style.configure(".", font=base)
        style.configure("Card.TLabel", background=CARD, foreground=TEXT, font=base)
        style.configure("CardMuted.TLabel", background=CARD, foreground=MUTED, font=(UI_FONT, 10))
        style.configure("CardHead.TLabel", background=CARD, foreground=MUTED, font=(UI_FONT, 10, "bold"))
        style.configure("Card.TCheckbutton", background=CARD, foreground=TEXT, font=base)
        style.map("Card.TCheckbutton", background=[("active", CARD)])
        style.configure("Strip.TLabel", background=STRIP, foreground=TEXT, font=(UI_FONT, 11))
        style.configure("Body.TLabel", background=BG, foreground=MUTED, font=(UI_FONT, 10))
        style.configure("TButton", font=base, padding=(12, 5))
        style.configure("TEntry", padding=4)
        style.configure("Treeview", rowheight=26, font=(UI_FONT, 11), background=CARD,
                        fieldbackground=CARD, foreground=TEXT, borderwidth=0)
        style.configure("Treeview.Heading", font=(UI_FONT, 11, "bold"), padding=(8, 6),
                        background=HEAD, foreground=TEXT, relief="flat")
        style.map("Treeview.Heading", background=[("active", HEAD)])
        style.configure("Strip.Horizontal.TProgressbar", troughcolor=HEAD, background=ACCENT,
                        borderwidth=0, thickness=5)

        # ---- header: icon and name, hairline underneath --------------------
        header = tk.Frame(self, bg=CARD, padx=18, pady=10)
        header.pack(fill="x")
        tk.Frame(self, bg=BORDER, height=1).pack(fill="x")
        try:
            self._logo = tk.PhotoImage(data=LOGO_PNG_B64)
            tk.Label(header, image=self._logo, bg=CARD).pack(side="left", padx=(0, 10))
        except tk.TclError:
            self._logo = None
        tk.Label(header, text=core.APP_NAME, bg=CARD, fg=TEXT,
                 font=(UI_FONT, 13, "bold")).pack(side="left")
        tk.Label(header, text=f"v{core.APP_VERSION}", bg=CARD, fg=MUTED,
                 font=(UI_FONT, 10)).pack(side="right")
        help_btn = tk.Label(header, text="Help", bg=CARD, fg="#1d4ed8", cursor="hand2",
                            font=(UI_FONT, 10, "underline"))
        help_btn.pack(side="right", padx=(0, 14))
        help_btn.bind("<Button-1>", lambda e: self.open_help())

        body = tk.Frame(self, bg=BG, padx=18, pady=14)
        body.pack(fill="both", expand=True)

        # ---- card: folder and options -------------------------------------
        card = self._card(body)
        card.pack(side="top", fill="x")
        card.columnconfigure(1, weight=1)
        ttk.Label(card, text="FOLDER", style="CardHead.TLabel").grid(
            row=0, column=0, columnspan=4, sticky="w", pady=(0, 8))
        ttk.Label(card, text="Folder", style="Card.TLabel").grid(row=1, column=0, sticky="w", padx=(0, 10))
        self.path_var = tk.StringVar()
        self.path_box = ttk.Entry(card, textvariable=self.path_var, font=base)
        self.path_box.grid(row=1, column=1, sticky="ew")
        self.path_box.bind("<Return>", lambda e: self.start())
        self.path_box.bind("<FocusOut>", lambda e: self._folder_changed())
        ttk.Button(card, text="Browse...", command=self.browse).grid(row=1, column=2, padx=(8, 0))
        action = tk.Frame(card, bg=CARD)
        action.grid(row=1, column=3, padx=(14, 0), sticky="ew")
        self.go_btn = RoundButton(action, "Rename PDFs", self.start, bg=ACCENT, hover=ACCENT_HOVER,
                                  font=(UI_FONT, 13, "bold"), padx=26, pady=8)
        self.go_btn.pack()
        self.stop_btn = RoundButton(action, "Stop", self.stop, bg=RED, hover=RED_HOVER,
                                    font=(UI_FONT, 13, "bold"), padx=40, pady=8)

        ttk.Label(card, text="Pattern", style="Card.TLabel").grid(
            row=2, column=0, sticky="w", padx=(0, 10), pady=(8, 0))
        self.template_var = tk.StringVar(value=self.settings.get("template", core.DEFAULT_TEMPLATE))
        self.template_box = ttk.Combobox(card, textvariable=self.template_var,
                                         values=core.TEMPLATES, font=base)
        self.template_box.grid(row=2, column=1, sticky="w", pady=(8, 0), ipadx=40)
        self.template_box.bind("<<ComboboxSelected>>", lambda e: self._template_changed())
        self.template_box.bind("<FocusOut>", lambda e: self._template_changed())
        self.template_box.bind("<Return>", lambda e: self._template_changed())
        self.example_var = tk.StringVar()
        ttk.Label(card, textvariable=self.example_var, style="CardMuted.TLabel").grid(
            row=2, column=2, columnspan=2, sticky="w", padx=(12, 0), pady=(8, 0))

        opts = tk.Frame(card, bg=CARD)
        opts.grid(row=3, column=0, columnspan=4, sticky="ew", pady=(8, 0))
        self.recurse_var = tk.BooleanVar(value=bool(self.settings.get("recurse", False)))
        self.recheck_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(opts, text="Include subfolders", variable=self.recurse_var,
                        style="Card.TCheckbutton", command=self._folder_changed).pack(side="left")
        ttk.Checkbutton(opts, text="Re-check files that already look renamed", variable=self.recheck_var,
                        style="Card.TCheckbutton", command=self._folder_changed).pack(side="left", padx=(18, 0))
        ttk.Label(opts, text="Tokens  {year} {title} {author} {journal} {doi}",
                  style="CardMuted.TLabel").pack(side="right")
        self._template_changed(quiet=True)

        # ---- status strip ---------------------------------------------------
        strip = tk.Frame(body, bg=BG, padx=2, pady=2)
        strip.pack(side="top", fill="x", pady=(10, 0))
        strip.columnconfigure(0, weight=1)
        self.status_var = tk.StringVar(
            value="Paste a folder path or click Browse, then click Rename PDFs.")
        ttk.Label(strip, textvariable=self.status_var, style="Strip.TLabel", anchor="w").grid(
            row=0, column=0, sticky="ew")
        self.progress = ttk.Progressbar(strip, mode="determinate", style="Strip.Horizontal.TProgressbar")
        self.progress.grid(row=1, column=0, sticky="ew", pady=(6, 0))
        self.progress.grid_remove()

        # ---- bottom bar, packed before the results so it always stays visible --
        bottom = tk.Frame(body, bg=BG)
        bottom.pack(side="bottom", fill="x", pady=(12, 0))
        self.summary_var = tk.StringVar(value="")
        ttk.Label(bottom, textvariable=self.summary_var, style="Body.TLabel", anchor="w").pack(
            side="left", fill="x", expand=True)
        self.apply_btn = RoundButton(bottom, "Rename the 'Needs a look' rows too",
                                     self.apply_uncertain, bg=SLATE, hover=SLATE_HOVER,
                                     font=(UI_FONT, 11, "bold"), padx=18, pady=6)
        self.apply_btn.pack(side="right", padx=(8, 0))
        self.apply_btn.set_enabled(False)
        self.undo_btn = ttk.Button(bottom, text="Undo last run", command=self.undo, state="disabled")
        self.undo_btn.pack(side="right", padx=(8, 0))
        self.open_btn = ttk.Button(bottom, text="Open folder", command=self.open_folder, state="disabled")
        self.open_btn.pack(side="right")

        # ---- card: results --------------------------------------------------
        results = self._card(body)
        results.pack(side="top", fill="both", expand=True, pady=(12, 0))
        head = tk.Frame(results, bg=CARD)
        head.pack(fill="x", pady=(0, 8))
        ttk.Label(head, text="RESULTS", style="CardHead.TLabel").pack(side="left")
        legend = tk.Frame(head, bg=CARD)
        legend.pack(side="right")
        for label in (core.RENAMED, core.NEEDS_LOOK, core.NOT_RESOLVED, core.SKIPPED):
            Chip(legend, label, COLOURS[label], TINTS[label]).pack(side="left", padx=(6, 0))

        table = tk.Frame(results, bg=BORDER, highlightthickness=0)
        table.pack(fill="both", expand=True)
        cols = ("outcome", "current", "new", "note")
        self.tree = ttk.Treeview(table, columns=cols, show="headings", selectmode="extended")
        for col, text, width, stretch in (
            ("outcome", "Result", 120, False),
            ("current", "Current name", 300, True),
            ("new", "New name  (double click to edit)", 380, True),
            ("note", "Why", 340, True),
        ):
            self.tree.heading(col, text=text, anchor="w")
            self.tree.column(col, width=width, minwidth=80, stretch=stretch, anchor="w")
        vsb = ttk.Scrollbar(table, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=vsb.set)
        self.tree.pack(side="left", fill="both", expand=True, padx=(1, 0), pady=1)
        vsb.pack(side="right", fill="y", pady=1, padx=(0, 1))
        for outcome, colour in COLOURS.items():
            self.tree.tag_configure(f"{outcome}|even", foreground=colour, background=CARD)
            self.tree.tag_configure(f"{outcome}|odd", foreground=colour, background=STRIPE)
        self.tree.bind("<Double-1>", self.edit_row)
        self.tree.bind("<Motion>", self._hover_note)
        self.rows: dict[str, core.Record] = {}

    # ---- small widget helpers -------------------------------------------------

    @staticmethod
    def _card(parent):
        """A white panel with a hairline border, the visual unit of the window."""
        return tk.Frame(parent, bg=CARD, padx=14, pady=12,
                        highlightbackground=BORDER, highlightthickness=1)

    def _running(self, on: bool):
        if on:
            self.go_btn.pack_forget()
            self.stop_btn.pack()
            self.progress.grid()
        else:
            self.stop_btn.pack_forget()
            self.go_btn.pack()
            self.progress.grid_remove()

    def open_help(self):
        """Open the guide. README.md is the one kept up to date."""
        readme = next((APP_DIR / n for n in ("README.md", "README.txt")
                       if (APP_DIR / n).exists()), APP_DIR / "README.md")
        try:
            if sys.platform.startswith("win"):
                os.startfile(str(readme))
            elif sys.platform == "darwin":
                subprocess.Popen(["open", str(readme)])
            else:
                subprocess.Popen(["xdg-open", str(readme)])
        except Exception:
            messagebox.showinfo(core.APP_NAME, f"The guide is {readme.name} in\n{APP_DIR}")

    # ------------------------------------------------------------ folder --

    def template(self) -> str:
        return self.template_var.get().strip() or core.DEFAULT_TEMPLATE

    def _template_changed(self, quiet: bool = False):
        t = self.template()
        err = core.validate_template(t)
        if err:
            self.example_var.set(err)
            if not quiet:
                self.status_var.set(err)
            return
        self.example_var.set("e.g.  " + core.example_name(t))
        core.save_settings({"template": t})
        if not quiet:
            self._folder_changed()

    def folder(self) -> Path | None:
        p = clean_path(self.path_var.get())
        if p and Path(p).is_file():          # a pasted PDF path means its folder
            p = str(Path(p).parent)
        if p != self.path_var.get():
            self.path_var.set(p)
        return Path(p) if p and Path(p).is_dir() else None

    def browse(self):
        """Windows' native dialog with files visible and a Select Folder button.

        Falls back to the app's own picker on other systems, or if Windows
        refuses the request for any reason (the reason is written to the
        error log so it can be looked at, without interrupting the user).
        """
        start = self.folder() or Path.home()
        chosen = None
        if sys.platform.startswith("win"):
            try:
                import ctypes
                hwnd = ctypes.windll.user32.GetAncestor(self.winfo_id(), 2)
                chosen = windows_folder_dialog(hwnd, start, "Select the folder holding your PDFs")
                if chosen is None:
                    return                                   # cancelled
            except Exception:
                try:
                    with open(CRASH_LOG, "a", encoding="utf-8") as fh:
                        fh.write("Native folder dialog failed, used the built in one:\n"
                                 + traceback.format_exc() + "\n")
                except Exception:
                    pass
                chosen = None
        if chosen is None:
            dlg = FolderPicker(self, start)
            self.wait_window(dlg)
            chosen = dlg.result
        if chosen:
            self.path_var.set(os.path.normpath(str(chosen)))
            self._folder_changed()

    def _folder_changed(self):
        folder = self.folder()
        self.open_btn.config(state="normal" if folder else "disabled")
        self.undo_btn.config(state="normal" if folder and core.find_logs(folder) else "disabled")
        if not folder:
            if self.path_var.get().strip():
                self.status_var.set("That folder does not exist. Check the path.")
            return
        try:
            todo, decided, others = core.collect(folder, self.recurse_var.get(),
                                                 self.recheck_var.get(), self.template())
        except Exception:
            return
        bits = [f"{len(todo)} PDF files to look at"]
        if decided:
            bits.append(f"{len(decided)} already renamed")
        if others:
            bits.append(f"{others} other files will be left alone")
        self.status_var.set(",  ".join(bits) + ".  Click Rename PDFs.")

    # --------------------------------------------------------------- run --

    def start(self):
        if self.worker and self.worker.is_alive():
            return
        folder = self.folder()
        if not folder:
            messagebox.showwarning(core.APP_NAME, "Choose a folder first.")
            return
        template = self.template()
        err = core.validate_template(template)
        if err:
            messagebox.showwarning(core.APP_NAME, err)
            return
        todo, decided, _ = core.collect(folder, self.recurse_var.get(), self.recheck_var.get(), template)
        if not todo:
            self._show(core.RunResult(folder=folder, records=decided))
            self.status_var.set("Nothing to do: no PDF files that need renaming.")
            return

        core.save_settings({"last_folder": str(folder), "recurse": self.recurse_var.get(),
                            "template": template})
        self.cancel.clear()
        self.result = None
        self._clear_rows()
        self.progress.config(maximum=max(len(todo), 1), value=0)
        self._running(True)
        self.apply_btn.set_enabled(False)
        self.status_var.set(f"Reading {len(todo)} files and checking each against Crossref...")

        # Tk variables may only be read on the main thread. Capture them here,
        # not inside the job, or Tk raises "main thread is not in main loop".
        recurse, recheck = self.recurse_var.get(), self.recheck_var.get()

        def job():
            try:
                res = core.run_folder(
                    folder, recurse, recheck,
                    progress=lambda i, n, name: self.inbox.put(("progress", i, n, name)),
                    cancel=self.cancel, template=template,
                )
                self.inbox.put(("done", res))
            except Exception:
                self.inbox.put(("error", traceback.format_exc()))

        self.worker = threading.Thread(target=job, daemon=True)
        self.worker.start()

    def stop(self):
        self.cancel.set()
        self.status_var.set("Stopping. Files already being read will finish, nothing will be renamed.")

    def _poll(self):
        try:
            while True:
                msg = self.inbox.get_nowait()
                kind = msg[0]
                if kind == "progress":
                    _, i, n, name = msg
                    self.progress.config(maximum=max(n, 1), value=i)
                    self.status_var.set(f"Checked {i} of {n}   {name}")
                elif kind == "done":
                    self._finish(msg[1])
                elif kind == "error":
                    self._finish(None)
                    self._crash(msg[1])
        except queue.Empty:
            pass
        self.after(100, self._poll)

    def _finish(self, res):
        self._running(False)
        if res is None:
            return
        self.result = res
        self._show(res)
        n_ren, n_look = res.count(core.RENAMED), res.count(core.NEEDS_LOOK)
        n_fail, n_no = res.count(core.FAILED), res.count(core.NOT_RESOLVED)
        n_skip = res.count(core.SKIPPED)
        parts = [f"Renamed {n_ren}"]
        if n_look:
            parts.append(f"{n_look} need a look")
        if n_fail:
            parts.append(f"{n_fail} failed")
        if n_no:
            parts.append(f"{n_no} not resolved")
        if n_skip:
            parts.append(f"{n_skip} skipped")
        line = ",  ".join(parts) + "."
        if res.cancelled:
            line = "Stopped.  Nothing was renamed.  " + line
        if res.offline:
            line += "  No internet connection, Crossref could not be reached."
        elif not core.polite_pool_ready():
            line += "  (Set CONTACT_EMAIL, see README.)"
        self.status_var.set(line)
        self.undo_btn.config(state="normal" if core.find_logs(res.folder) else "disabled")
        self.apply_btn.set_enabled(bool(n_look))

    # ------------------------------------------------------------- table --

    def _clear_rows(self):
        self.tree.delete(*self.tree.get_children())
        self.rows = {}
        self.summary_var.set("")

    def _show(self, res: core.RunResult):
        self._clear_rows()
        for i, rec in enumerate(res.records):
            parity = "odd" if i % 2 else "even"
            iid = self.tree.insert("", "end", values=(
                rec.outcome, rec.name, rec.proposed if rec.outcome != core.RENAMED
                else Path(rec.new_path).name, rec.note), tags=(f"{rec.outcome}|{parity}",))
            self.rows[iid] = rec
        if res.log_path:
            self.summary_var.set(f"Log: {Path(res.log_path).name}   (Undo reads it)")

    def _hover_note(self, event):
        # A long reason is truncated in the column. Show it in the status
        # line while the mouse is over the row.
        iid = self.tree.identify_row(event.y)
        rec = self.rows.get(iid)
        if rec and rec.note and self.tree.identify_column(event.x) == "#4":
            self.status_var.set(rec.note)

    def edit_row(self, event=None):
        iid = self.tree.focus()
        rec = self.rows.get(iid)
        if not rec or rec.outcome != core.NEEDS_LOOK:
            return
        new = simpledialog.askstring(
            "Edit new name", f"New name for\n{rec.name}", initialvalue=rec.proposed, parent=self)
        if new is None:
            return
        new = new.strip()
        if not new:
            return
        if not new.lower().endswith(".pdf"):
            new += ".pdf"
        rec.proposed = new
        self.tree.set(iid, "new", new)

    # ------------------------------------------------------------ apply --

    def apply_uncertain(self):
        if not self.result:
            return
        pending = [r for r in self.result.records if r.outcome == core.NEEDS_LOOK and r.proposed]
        if not pending:
            return
        ok = messagebox.askyesno(
            "Confirm",
            f"Rename {len(pending)} files marked 'Needs a look'?\n\n"
            f"Their years came from a title search or an unverified DOI, "
            f"not from a DOI confirmed against the PDF text.\n\n"
            f"An undo log will be written.",
            default="no")
        if not ok:
            return
        log = core.apply_records(self.result.folder, self.result.records)
        self.result.log_path = log or self.result.log_path
        self.result.records.sort(key=lambda r: (core.OUTCOME_ORDER.index(r.outcome)
                                                if r.outcome in core.OUTCOME_ORDER else 99,
                                                r.name.lower()))
        self._show(self.result)
        n_fail = sum(1 for r in pending if r.outcome == core.FAILED)
        n_ok = sum(1 for r in pending if r.outcome == core.RENAMED)
        self.status_var.set(f"Renamed {n_ok} more." + (f"  {n_fail} failed." if n_fail else ""))
        self.apply_btn.set_enabled(False)
        self.undo_btn.config(state="normal")

    # ------------------------------------------------------------- undo --

    def undo(self):
        folder = self.folder()
        if not folder:
            return
        logs = core.find_logs(folder)
        if not logs:
            messagebox.showinfo(core.APP_NAME, "No undo log in this folder.")
            return
        ok = messagebox.askyesno(
            "Undo", f"Put the original names back?\n\nFrom {logs[0].name}", default="no")
        if not ok:
            return
        restored, errors, _ = core.undo_last(folder)
        msg = f"Restored {restored} files."
        if errors:
            msg += "\n\nIssues:\n" + "\n".join(f"{n}: {why}" for n, why in errors[:12])
        messagebox.showinfo("Undo finished", msg)
        self._clear_rows()
        self.result = None
        self.apply_btn.set_enabled(False)
        self._folder_changed()

    # ------------------------------------------------------------ misc --

    def open_folder(self):
        folder = self.folder()
        if not folder:
            return
        try:
            if sys.platform.startswith("win"):
                os.startfile(str(folder))
            elif sys.platform == "darwin":
                subprocess.Popen(["open", str(folder)])
            else:
                subprocess.Popen(["xdg-open", str(folder)])
        except Exception as exc:
            messagebox.showerror(core.APP_NAME, f"Could not open the folder:\n{exc}")

    def _tk_error(self, exc, val, tb):
        self._crash("".join(traceback.format_exception(exc, val, tb)))

    def _crash(self, text: str):
        try:
            CRASH_LOG.write_text(text, encoding="utf-8")
        except Exception:
            pass
        messagebox.showerror(
            core.APP_NAME,
            "Something went wrong. Details were written to\n"
            f"{CRASH_LOG.name}\nnext to the app.\n\n{text.strip().splitlines()[-1]}")

    def destroy(self):
        self.cancel.set()
        core.save_settings({"recurse": self.recurse_var.get()})
        super().destroy()


def main():
    if sys.platform.startswith("win"):
        try:                                   # crisp text on high DPI screens
            import ctypes
            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except Exception:
            pass
    initial = None
    if len(sys.argv) > 1:
        cand = clean_path(sys.argv[1])
        if Path(cand).is_file():
            cand = str(Path(cand).parent)
        if Path(cand).is_dir():
            initial = cand
    app = App(initial)
    app.mainloop()


if __name__ == "__main__":
    try:
        main()
    except Exception:
        try:
            CRASH_LOG.write_text(traceback.format_exc(), encoding="utf-8")
        except Exception:
            pass
        raise
