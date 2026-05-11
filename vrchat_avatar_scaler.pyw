"""
VRChat Avatar Scaler
====================
Controls avatar eye height (scale) in VRChat via OSC.
Launch with  pythonw  or the included .vbs to suppress the console window.

Required (pip install):
    python-osc  pystray  Pillow  psutil

Optional (pip install):
    pynput               — enables global keyboard hotkeys (no administrator rights required)
    tinyoscquery zeroconf requests — enables OSCQuery for automatic port negotiation with VRChat
                                     (install via: pip install git+https://github.com/Hackebein/tinyoscquery.git zeroconf requests)

VRChat OSC ports (defaults):
    Send  →  9000   (VRChat listens here)
    Recv  ←  9001   (VRChat broadcasts here)

Docs:
    https://docs.vrchat.com/docs/osc-avatar-scaling
"""

# ─── Dependency guard ─────────────────────────────────────────────────────────
import sys as _sys
import tkinter as _tk
from tkinter import messagebox as _mb

_need = []
try:
    from pythonosc import udp_client, dispatcher, osc_server
except ImportError:
    _need.append("python-osc")
try:
    import pystray
except ImportError:
    _need.append("pystray")
try:
    from PIL import Image, ImageDraw, ImageTk
except ImportError:
    _need.append("Pillow")
try:
    import psutil
except ImportError:
    _need.append("psutil")

if _need:
    _r = _tk.Tk(); _r.withdraw()
    _mb.showerror(
        "VRChat Avatar Scaler — Missing Packages",
        "Required packages are not installed:\n\n"
        + "\n".join(f"    • {p}" for p in _need)
        + "\n\nInstall them with:\n\n"
        + f"    pip install {' '.join(_need)}"
        + "\n\n"
        + "If you already ran Install.bat and still see this, you may have\n"
        "multiple Python installations. Run Install.bat again and check\n"
        "the output carefully, or install manually using:\n\n"
        + f"    \"{_sys.executable}\" -m pip install {' '.join(_need)}\n\n"
        + f"(This copy of Python is at: {_sys.executable})"
    )
    raise SystemExit(1)

# ─── Optional packages ────────────────────────────────────────────────────────
# pynput: global hotkeys via accessibility API — no admin required
try:
    from pynput import keyboard as _pynput_kb
    _KB = True
except Exception:
    _KB = False

# tinyoscquery + zeroconf: OSCQuery service advertisement and discovery
try:
    from tinyoscquery.queryservice import OSCQueryService
    from tinyoscquery.query       import OSCQueryBrowser, OSCQueryClient
    from tinyoscquery.utility     import get_open_tcp_port, get_open_udp_port
    from tinyoscquery.shared.node import OSCAccess
    _OSCQ = True
except Exception:
    _OSCQ = False

# ─── Single-instance lock (UDP socket bound to a fixed port) ─────────────────
import socket as _socket
_LOCK_PORT = 47423   # arbitrary private port used only as a lock

def _acquire_instance_lock():
    """Returns a bound socket that acts as a process lock, or None if already running."""
    s = _socket.socket(_socket.AF_INET, _socket.SOCK_DGRAM)
    try:
        s.bind(("127.0.0.1", _LOCK_PORT))
        return s   # we own the lock
    except OSError:
        s.close()
        return None

_instance_lock = _acquire_instance_lock()
if _instance_lock is None:
    _r = _tk.Tk(); _r.withdraw()
    _mb.showinfo(
        "VRChat Avatar Scaler",
        "VRChat Avatar Scaler is already running.\n\n"
        "Check the system tray to find it."
    )
    raise SystemExit(0)

# ─── Standard imports ─────────────────────────────────────────────────────────
import json, math, os, sys, threading, time
import ctypes as _ctypes
import urllib.request as _urllib

from pathlib import Path
import tkinter as tk
from tkinter import ttk

# ─── Version ──────────────────────────────────────────────────────────────────
APP_VERSION       = "0.2.3"
_RELEASES_API_URL = "https://api.github.com/repos/SalbugVR/VRChat-Avatar-Scaler/releases/latest"
_RELEASES_PAGE    = "https://github.com/SalbugVR/VRChat-Avatar-Scaler/releases"

# ─── Config ───────────────────────────────────────────────────────────────────
_CFG = Path(__file__).with_name("scaler_config.json")
_DEFAULTS = {
    "default_height":           1.65,
    "last_height":              1.65,
    "retain_on_change":         True,
    "apply_default_on_change":  False,
    "auto_close_with_vrchat":   False,
    "auto_launch_with_vrchat":  False,
    "run_on_startup":           False,
    "start_minimized":          False,
    "close_to_tray":            True,
    "overlay_enabled":          False,
    "overlay_x":                None,
    "overlay_y":                None,
    "custom_presets":           [],
    "suppress_range_warning":   False,
    "oscquery_enabled":         True,
    "keyboard_enabled":         True,
    "kb_fine_up":               "ctrl+alt+up",
    "kb_fine_down":             "ctrl+alt+down",
    "kb_coarse_up":             "ctrl+alt+shift+up",
    "kb_coarse_down":           "ctrl+alt+shift+down",
    "kb_apply_default":         "ctrl+alt+home",
    "kb_quick_input":           "ctrl+alt+i",
    "vrc_ip":                   "127.0.0.1",
    "send_port":                9000,
    "recv_port":                9001,
}

def _load() -> dict:
    if _CFG.exists():
        try:
            d = json.loads(_CFG.read_text("utf-8"))
            for k, v in _DEFAULTS.items(): d.setdefault(k, v)
            return d
        except Exception: pass
    return _DEFAULTS.copy()

def _save(cfg: dict):
    try: _CFG.write_text(json.dumps(cfg, indent=2), "utf-8")
    except Exception: pass


def _fetch_latest_version() -> str | None:
    """
    Query GitHub releases API for the latest release tag.
    Returns the tag string (e.g. 'v0.3.0') or None on any failure.
    Runs in a background thread — never blocks the UI.
    """
    try:
        req = _urllib.Request(
            _RELEASES_API_URL,
            headers={"User-Agent": f"VRChatAvatarScaler/{APP_VERSION}",
                     "Accept":     "application/vnd.github+json"}
        )
        with _urllib.urlopen(req, timeout=8) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            return data.get("tag_name")
    except Exception:
        return None


# ─── Windows startup shortcut management ─────────────────────────────────────
_STARTUP_DIR      = Path(os.environ.get("APPDATA", "")) / \
                    "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Startup"
_STARTUP_SHORTCUT = _STARTUP_DIR / "VRChat Avatar Scaler.lnk"
_LAUNCHER_VBS     = Path(__file__).with_name("Launch Scaler (Silent).vbs")

def _startup_is_enabled() -> bool:
    return _STARTUP_SHORTCUT.exists()

def _set_startup(enable: bool) -> bool:
    """
    Create or remove a .lnk shortcut in the Windows startup folder.
    Returns True on success, False on failure.
    """
    try:
        if not enable:
            if _STARTUP_SHORTCUT.exists():
                _STARTUP_SHORTCUT.unlink()
            return True

        # Ensure the startup directory exists
        _STARTUP_DIR.mkdir(parents=True, exist_ok=True)

        # Build the .lnk via VBScript (no pywin32 dependency)
        target = str(_LAUNCHER_VBS.resolve()) if _LAUNCHER_VBS.exists() \
                 else str(Path(__file__).resolve())
        work   = str(Path(__file__).parent.resolve())
        dest   = str(_STARTUP_SHORTCUT)

        vbs = (
            f'Set ws = CreateObject("WScript.Shell")\n'
            f'Set sc = ws.CreateShortcut("{dest}")\n'
            f'sc.TargetPath = "{target}"\n'
            f'sc.WorkingDirectory = "{work}"\n'
            f'sc.Description = "VRChat Avatar Scaler"\n'
            f'sc.Save\n'
        )
        tmp = Path(os.environ.get("TEMP", ".")) / "_vrcas_shortcut.vbs"
        tmp.write_text(vbs, encoding="utf-8")
        import subprocess
        subprocess.run(["cscript", "//nologo", str(tmp)],
                       capture_output=True, timeout=10)
        tmp.unlink(missing_ok=True)
        return _STARTUP_SHORTCUT.exists()
    except Exception:
        return False

# ─── OSC addresses ────────────────────────────────────────────────────────────
OSC_HEIGHT   = "/avatar/eyeheight"
OSC_MIN      = "/avatar/eyeheightmin"
OSC_MAX      = "/avatar/eyeheightmax"
OSC_ALLOWED  = "/avatar/eyeheightscalingallowed"
OSC_CHANGE   = "/avatar/change"

# ─── Scale limits ─────────────────────────────────────────────────────────────
ABS_MIN  = 0.01;  ABS_MAX  = 10_000.0
SAFE_MIN = 0.1;   SAFE_MAX = 100.0
LOG_MIN  = math.log10(SAFE_MIN)   # −1.0
LOG_MAX  = math.log10(SAFE_MAX)   #  2.0

# ─── Presets ──────────────────────────────────────────────────────────────────
PRESETS = [
    ("Tiny\n0.30 m",    0.30),
    ("Small\n0.90 m",   0.90),
    ("Compact\n1.20 m", 1.20),
    ("Short\n1.52 m",   1.52),
    ("Average\n1.65 m", 1.65),
    ("Tall\n1.80 m",    1.80),
    ("Giant\n3.00 m",   3.00),
    ("Macro\n10.0 m",  10.00),
]

# ─── Palette ──────────────────────────────────────────────────────────────────
BG   = "#0f0f17"; BG2  = "#1a1a28"; BG3  = "#24243a"; BG4  = "#2e2e48"
A    = "#7b5ea7"; A2   = "#a87dd1"; AHL  = "#c9a0f0"
TEXT = "#e8e4f0"; DIM  = "#7a7590"
OK   = "#4ecb71"; WARN = "#f0a030"; ERR  = "#e05555"
LOCK = "#3a3a5a"    # locked slider colour
LIM  = "#e05555"    # Udon limit marker colour (red)

FT = ("Segoe UI", 16, "bold")   # title
FH = ("Segoe UI", 10, "bold")   # heading
FB = ("Segoe UI", 10)           # body
FM = ("Consolas", 12, "bold")   # mono
FS = ("Segoe UI", 8)            # small

# ─── Helpers ──────────────────────────────────────────────────────────────────
def _clamp(v, lo, hi): return max(lo, min(hi, v))

def _imp(m: float) -> str:
    ti = m / 0.0254
    return f"{int(ti//12)}'{ti%12:.1f}\""

def _make_icon(size=64) -> Image.Image:
    """Icon used for tray and taskbar."""
    img = Image.new("RGBA", (size, size), (0,0,0,0))
    d   = ImageDraw.Draw(img)
    s   = size
    d.ellipse([2, 2, s-2, s-2], fill=(123, 94, 167, 255))
    # head
    d.ellipse([int(s*.36), int(s*.09), int(s*.62), int(s*.35)], fill=(220,200,255,255))
    # body
    d.rounded_rectangle([int(s*.26), int(s*.38), int(s*.74), int(s*.72)],
                        radius=int(s*.08), fill=(220,200,255,255))
    # up arrow
    cx = s//2
    d.polygon([(cx, 2), (cx-5, 10), (cx+5, 10)], fill=(255,255,255,210))
    # down arrow
    d.polygon([(cx, s-2), (cx-5, s-10), (cx+5, s-10)], fill=(255,255,255,210))
    return img

# ─── Tooltip ──────────────────────────────────────────────────────────────────
class Tooltip:
    """Shows a floating tooltip after a hover delay; hides on mouse-leave."""
    def __init__(self, widget: tk.Widget, text: str, delay: int = 550, wrap: int = 300):
        self._w    = widget
        self._text = text
        self._delay= delay
        self._wrap = wrap
        self._job  = None
        self._tip  = None
        widget.bind("<Enter>",       self._enter, add="+")
        widget.bind("<Leave>",       self._leave, add="+")
        widget.bind("<ButtonPress>", self._leave, add="+")

    def _enter(self, _=None):
        self._job = self._w.after(self._delay, self._show)

    def _leave(self, _=None):
        if self._job: self._w.after_cancel(self._job); self._job = None
        if self._tip: self._tip.destroy(); self._tip = None

    def _show(self):
        x = self._w.winfo_rootx() + 8
        y = self._w.winfo_rooty() + self._w.winfo_height() + 4
        self._tip = tk.Toplevel(self._w)
        self._tip.wm_overrideredirect(True)
        self._tip.wm_geometry(f"+{x}+{y}")
        self._tip.attributes("-topmost", True)
        tk.Label(
            self._tip, text=self._text, font=FS,
            bg="#1e1e32", fg=TEXT, relief="flat",
            bd=1, padx=10, pady=6,
            wraplength=self._wrap, justify="left",
            highlightbackground=A, highlightthickness=1,
        ).pack()

# ─── Custom logarithmic slider ────────────────────────────────────────────────
class LogSlider(tk.Canvas):
    """
    Canvas-based log-scale slider with:
      • red Udon limit markers (only drawn when the world has set them)
      • locked state: fades out and blocks all interaction
    """
    _TR   = 7     # track half-height
    _THR  = 11    # thumb radius
    _PAD  = 16    # horizontal padding
    _VPAD = 26    # bottom padding (track centre from bottom of canvas)

    # (value_m, label, is_major)
    # Major ticks get a taller line + label; minor ticks get a short line only.
    _TICKS = [
        (0.10,  "0.1m",  True),
        (0.20,  "",      False),
        (0.30,  "0.3m",  False),
        (0.50,  "0.5m",  True),
        (1.00,  "1m",    True),
        (1.50,  "1.5m",  False),
        (2.00,  "2m",    True),
        (3.00,  "3m",    False),
        (5.00,  "5m",    True),
        (10.0,  "10m",   True),
        (20.0,  "20m",   False),
        (30.0,  "30m",   False),
        (50.0,  "50m",   True),
        (100.,  "100m",  True),
    ]

    def __init__(self, parent, lo: float, hi: float,
                 variable: tk.DoubleVar, command=None, **kw):
        kw.setdefault("height", 82)   # extra room for tick labels below track
        kw.setdefault("bg", BG)
        kw.setdefault("highlightthickness", 0)
        super().__init__(parent, **kw)
        self._lo  = lo; self._hi = hi
        self._var = variable; self._cmd = command
        self._lim_min: float | None = None
        self._lim_max: float | None = None
        self._locked  = False
        self._drag    = False
        variable.trace_add("write", lambda *_: self.after_idle(self._draw))
        self.bind("<Configure>",       lambda _: self._draw())
        self.bind("<ButtonPress-1>",   self._press)
        self.bind("<B1-Motion>",       self._motion)
        self.bind("<ButtonRelease-1>", self._release)

    # ── public ────────────────────────────────────────────────────────────────
    def set_limits(self, lo_m: float | None, hi_m: float | None):
        self._lim_min = None if lo_m is None else _clamp(math.log10(max(lo_m, 1e-4)), self._lo, self._hi)
        self._lim_max = None if hi_m is None else _clamp(math.log10(max(hi_m, 1e-4)), self._lo, self._hi)
        self.after_idle(self._draw)

    def clear_limits(self):
        self._lim_min = None; self._lim_max = None
        self.after_idle(self._draw)

    def set_locked(self, locked: bool):
        self._locked = locked
        self.after_idle(self._draw)

    # ── coordinate math ───────────────────────────────────────────────────────
    def _lv_to_x(self, lv: float) -> float:
        w = self.winfo_width()
        return self._PAD + (lv - self._lo) / (self._hi - self._lo) * (w - 2*self._PAD)

    def _x_to_lv(self, x: float) -> float:
        w = self.winfo_width()
        frac = (x - self._PAD) / (w - 2*self._PAD)
        return self._lo + _clamp(frac, 0.0, 1.0) * (self._hi - self._lo)

    # ── drawing ───────────────────────────────────────────────────────────────
    def _draw(self):
        self.delete("all")
        w = self.winfo_width()
        if w < 20: return

        pad   = self._PAD
        cy    = self.winfo_height() - self._VPAD - self._THR
        tr    = self._TR
        x0, x1 = pad, w - pad
        ty0   = cy - tr; ty1 = cy + tr

        lv  = _clamp(self._var.get(), self._lo, self._hi)
        xc  = self._lv_to_x(lv)
        out = (10**lv < SAFE_MIN or 10**lv > SAFE_MAX)

        # Track BG
        self.create_rectangle(x0, ty0, x1, ty1, fill=LOCK if self._locked else "#3a3a5a", outline="")

        # Filled portion
        fill = (WARN if out else A) if not self._locked else "#4a3a6a"
        self.create_rectangle(x0, ty0, xc, ty1, fill=fill, outline="")

        # ── Udon limit markers (red) — only when the world has set them ───────
        for llog in [self._lim_min, self._lim_max]:
            if llog is None: continue
            xm  = self._lv_to_x(llog)
            val = 10**llog
            # Shaded forbidden zone — solid dark red (tkinter Canvas has no alpha support)
            if llog == self._lim_min:
                self.create_rectangle(x0, ty0, xm, ty1, fill="#4a1a1a", outline="")
            else:
                self.create_rectangle(xm, ty0, x1, ty1, fill="#4a1a1a", outline="")
            # Marker line
            self.create_line(xm, ty0-10, xm, ty1+2, fill=LIM, width=2)
            # Triangle cap
            self.create_polygon(xm, ty0-11, xm-5, ty0-19, xm+5, ty0-19, fill=LIM, outline="")
            # Label
            lbl = f"{val:.2f} m"
            ax  = "center"
            tx  = xm
            if xm < x0+34: ax, tx = "w", x0
            elif xm > x1-34: ax, tx = "e", x1
            self.create_text(tx, ty0-21, text=lbl, fill=LIM, font=("Segoe UI",7,"bold"), anchor=ax)

        # ── Tick marks below track ────────────────────────────────────────
        tick_col  = "#555570" if self._locked else "#6a6585"
        label_col = "#555570" if self._locked else DIM
        prev_label_x = -999   # collision guard for labels

        for val, lbl, major in self._TICKS:
            lv_t = math.log10(val)
            if lv_t < self._lo or lv_t > self._hi:
                continue
            xt = self._lv_to_x(lv_t)
            tick_h = 7 if major else 4
            self.create_line(xt, ty1+2, xt, ty1+2+tick_h, fill=tick_col, width=1)

            if major and lbl:
                # Suppress label if too close to the previous one
                if xt - prev_label_x >= 28:
                    # Edge anchoring so first/last labels don't overflow
                    if xt <= x0 + 10:
                        anchor, tx = "nw", x0
                    elif xt >= x1 - 10:
                        anchor, tx = "ne", x1
                    else:
                        anchor, tx = "n", xt
                    self.create_text(tx, ty1+11, text=lbl,
                                     fill=label_col,
                                     font=("Segoe UI", 7),
                                     anchor=anchor)
                    prev_label_x = xt

        # Thumb
        if self._locked:
            self.create_oval(xc-self._THR, cy-self._THR, xc+self._THR, cy+self._THR,
                             fill="#4a3a6a", outline="#6a5a8a", width=2)
            # Lock icon (small padlock shape)
            self.create_rectangle(xc-4, cy-1, xc+4, cy+5, fill="#6a5a8a", outline="")
            self.create_arc(xc-4, cy-6, xc+4, cy+2, start=0, extent=180,
                            outline="#6a5a8a", style="arc", width=2)
        else:
            tc = "#ffffff" if self._drag else AHL
            self.create_oval(xc-self._THR, cy-self._THR, xc+self._THR, cy+self._THR,
                             fill=tc, outline=A2, width=2)

        # Locked overlay text
        if self._locked:
            self.create_rectangle(x0, ty0-2, x1, ty1+2, fill="#1a1a2a", outline="")
            mid = (x0+x1)//2
            self.create_text(mid, cy, text="⚿  Scaling locked by this world",
                             fill="#8a7a9a", font=("Segoe UI", 9, "italic"), anchor="center")

    # ── interaction ───────────────────────────────────────────────────────────
    def _press(self, e):
        if self._locked: return
        self._drag = True; self._update(e.x)
    def _motion(self, e):
        if self._locked or not self._drag: return
        self._update(e.x)
    def _release(self, e):
        self._drag = False; self._draw()
    def _update(self, x: float):
        lv = _clamp(self._x_to_lv(x), self._lo, self._hi)
        self._var.set(lv)
        if self._cmd: self._cmd(lv)


# ─── Keyboard input ───────────────────────────────────────────────────────────
class KeyboardInput:
    """
    Global hotkeys via pynput Listener (accessibility API — no admin required).
    Supports hold-to-repeat: fires immediately on press, then repeats after an
    initial delay. Fully supports numpad keys via Windows VK codes.

    Default bindings:
        Ctrl+Alt+Up          Fine scale up   (+1%)
        Ctrl+Alt+Down        Fine scale down (−1%)
        Ctrl+Alt+Shift+Up    Coarse up       (+10%)
        Ctrl+Alt+Shift+Down  Coarse down     (−10%)
        Ctrl+Alt+Home        Apply default height
    """
    _INITIAL_DELAY   = 0.35   # seconds before repeat starts
    _REPEAT_INTERVAL = 0.05   # seconds between repeats while held (20 Hz)

    _MODS = {"ctrl", "alt", "shift"}

    # Windows VK codes → canonical name for numpad keys
    _VK_TO_NAME = {
        96:  "numpad0", 97:  "numpad1", 98:  "numpad2", 99:  "numpad3",
        100: "numpad4", 101: "numpad5", 102: "numpad6", 103: "numpad7",
        104: "numpad8", 105: "numpad9",
        106: "numpad*", 107: "numpad+", 109: "numpad-",
        110: "numpad.", 111: "numpad/",
    }

    DEFAULTS = {
        "fine_up":       "ctrl+alt+up",
        "fine_down":     "ctrl+alt+down",
        "coarse_up":     "ctrl+alt+shift+up",
        "coarse_down":   "ctrl+alt+shift+down",
        "apply_default": "ctrl+alt+home",
        "quick_input":   "ctrl+alt+i",
    }
    CFG_KEYS = {
        "fine_up":       "kb_fine_up",
        "fine_down":     "kb_fine_down",
        "coarse_up":     "kb_coarse_up",
        "coarse_down":   "kb_coarse_down",
        "apply_default": "kb_apply_default",
        "quick_input":   "kb_quick_input",
    }

    def __init__(self, schedule, callbacks: dict):
        self._sched           = schedule
        self._cbs             = callbacks
        self._active          = False
        self._listener        = None
        self._held_mods:  set = set()    # currently depressed modifier names
        self._held_keys:  set = set()    # all currently depressed key ids
        self._repeating: dict = {}       # action → threading.Event (stop signal)
        self._lock = threading.Lock()
        self._hotkey_map: dict = {}      # action → (frozenset_mods, trigger_str)

    # ── static helpers ────────────────────────────────────────────────────────

    @staticmethod
    def _key_id(key) -> str | None:
        """Return a canonical lowercase string id for any pynput key."""
        try:
            K = _pynput_kb.Key
            # Modifier normalisation (collapse left/right variants)
            if key in (K.ctrl,  K.ctrl_l,  K.ctrl_r):           return "ctrl"
            if key in (K.alt,   K.alt_l,   K.alt_r, K.alt_gr):  return "alt"
            if key in (K.shift, K.shift_l, K.shift_r):           return "shift"
            # Numpad keys by Windows VK code (before falling through to .name)
            vk = getattr(key, "vk", None)
            if vk and vk in KeyboardInput._VK_TO_NAME:
                return KeyboardInput._VK_TO_NAME[vk]
            # Named special key (home, up, f1, …)
            name = getattr(key, "name", None)
            if name:
                return name.lower()
            # Regular printable character
            char = getattr(key, "char", None)
            if char:
                return char.lower()
        except Exception:
            pass
        return None

    @staticmethod
    def _parse(raw: str):
        """
        Parse a config string like 'ctrl+alt+up' or 'ctrl+numpad0' into
        (frozenset_of_modifiers, trigger_name).  Returns None if invalid.
        """
        # Normalise: lowercase, strip spaces around each token
        parts = [p.strip() for p in raw.lower().replace(" ", "").split("+") if p.strip()]
        mods     = frozenset(p for p in parts if p in KeyboardInput._MODS)
        triggers = [p for p in parts if p not in KeyboardInput._MODS]
        if len(triggers) != 1:
            return None
        return (mods, triggers[0])

    @staticmethod
    def bindings_from_cfg(cfg: dict) -> dict:
        return {
            action: (cfg.get(cfg_key) or KeyboardInput.DEFAULTS[action])
            for action, cfg_key in KeyboardInput.CFG_KEYS.items()
        }

    # ── lifecycle ─────────────────────────────────────────────────────────────

    def start(self, cfg: dict):
        if not _KB or not cfg.get("keyboard_enabled"):
            return
        self._hotkey_map = {}
        for action, raw in self.bindings_from_cfg(cfg).items():
            parsed = self._parse(raw)
            if parsed:
                self._hotkey_map[action] = parsed
        if not self._hotkey_map:
            return
        try:
            self._listener = _pynput_kb.Listener(
                on_press=self._on_press,
                on_release=self._on_release,
            )
            self._listener.start()
            self._active = True
        except Exception:
            pass

    def stop(self):
        if not self._active:
            return
        try:
            self._listener.stop()
        except Exception:
            pass
        with self._lock:
            for evt in self._repeating.values():
                evt.set()
            self._repeating.clear()
            self._held_mods.clear()
            self._held_keys.clear()
        self._listener = None
        self._active   = False

    def restart(self, cfg: dict):
        self.stop()
        self.start(cfg)

    # ── listener callbacks ────────────────────────────────────────────────────

    def _on_press(self, key):
        kid = self._key_id(key)
        if not kid:
            return
        with self._lock:
            if kid in self._MODS:
                self._held_mods.add(kid)
            self._held_keys.add(kid)
            for action, (req_mods, trigger) in self._hotkey_map.items():
                if kid == trigger and req_mods == self._held_mods \
                        and action not in self._repeating:
                    cb = self._cbs.get(action)
                    if cb:
                        self._sched(cb)   # fire immediately on first press
                        stop_evt = threading.Event()
                        self._repeating[action] = stop_evt
                        threading.Thread(
                            target=self._repeat_loop,
                            args=(cb, stop_evt),
                            daemon=True,
                        ).start()

    def _on_release(self, key):
        kid = self._key_id(key)
        if not kid:
            return
        with self._lock:
            if kid in self._MODS:
                self._held_mods.discard(kid)
            self._held_keys.discard(kid)
            # Cancel any hotkey that depended on this key
            to_stop = [
                action for action, (req_mods, trigger) in self._hotkey_map.items()
                if kid == trigger or kid in req_mods
            ]
            for action in to_stop:
                evt = self._repeating.pop(action, None)
                if evt:
                    evt.set()

    def _repeat_loop(self, cb, stop_evt: threading.Event):
        """Wait for the initial delay, then fire repeatedly until released."""
        if stop_evt.wait(timeout=self._INITIAL_DELAY):
            return   # released before repeat started
        while not stop_evt.is_set():
            self._sched(cb)
            stop_evt.wait(timeout=self._REPEAT_INTERVAL)


# ─── Hotkey recorder widget ───────────────────────────────────────────────────
# Human-readable labels for the action list shown in settings
_ACTION_LABELS = [
    ("fine_up",       "Scale up  +1%"),
    ("fine_down",     "Scale down  −1%"),
    ("coarse_up",     "Scale up  +10%"),
    ("coarse_down",   "Scale down  −10%"),
    ("apply_default", "Apply default height"),
    ("quick_input",   "Quick height input"),
]

def _fmt_hotkey(raw: str) -> str:
    """Convert 'ctrl+alt+shift+up' → 'Ctrl + Alt + Shift + ↑' for display."""
    _MAP = {
        "ctrl": "Ctrl", "alt": "Alt", "shift": "Shift",
        "up": "↑", "down": "↓", "left": "←", "right": "→",
        "home": "Home", "end": "End", "pageup": "Page Up", "page_up": "Page Up",
        "pagedown": "Page Down", "page_down": "Page Down",
        "insert": "Ins", "delete": "Del",
        "space": "Space", "tab": "Tab", "enter": "Enter",
        "esc": "Esc", "escape": "Esc",
        "f1":"F1","f2":"F2","f3":"F3","f4":"F4","f5":"F5","f6":"F6",
        "f7":"F7","f8":"F8","f9":"F9","f10":"F10","f11":"F11","f12":"F12",
        # Numpad keys
        "numpad0":"Num 0","numpad1":"Num 1","numpad2":"Num 2","numpad3":"Num 3",
        "numpad4":"Num 4","numpad5":"Num 5","numpad6":"Num 6","numpad7":"Num 7",
        "numpad8":"Num 8","numpad9":"Num 9",
        "numpad+":"Num +","numpad-":"Num −","numpad*":"Num ×",
        "numpad/":"Num /","numpad.":"Num .",
    }
    parts = [p.strip().lower() for p in raw.replace(" ", "").split("+")]
    return " + ".join(_MAP.get(p, p.upper()) for p in parts)


class HotkeyRecorder(tk.Frame):
    """
    Shows a table of action → hotkey rows. Each row has a 'Change' button.
    Clicking it enters record mode: the button turns into a 'Press keys…' label
    and a background thread calls keyboard.read_hotkey() to capture the combo.
    The new binding is written back into the provided cfg dict immediately.
    """
    _BTN_W = 9   # width of Change/Reset buttons

    def __init__(self, parent, cfg: dict, schedule, **kw):
        kw.setdefault("bg", BG3)
        super().__init__(parent, **kw)
        self.configure(highlightbackground=BG4, highlightthickness=1)
        self._cfg      = cfg
        self._schedule = schedule
        self._recording: str | None = None   # action currently being recorded

        inner = tk.Frame(self, bg=BG3)
        inner.pack(padx=10, pady=8, fill="x")

        tk.Label(inner, text="Keyboard bindings  (click Change, then press your combo):",
                 font=FS, bg=BG3, fg=DIM).pack(anchor="w", pady=(0, 6))

        self._rows: dict[str, dict] = {}   # action → {label_var, btn, reset_btn}

        bindings = KeyboardInput.bindings_from_cfg(cfg)

        for action, display in _ACTION_LABELS:
            row = tk.Frame(inner, bg=BG3)
            row.pack(fill="x", pady=2)

            tk.Label(row, text=display, font=FS, bg=BG3, fg=TEXT,
                     width=22, anchor="w").pack(side="left")

            lv = tk.StringVar(value=_fmt_hotkey(bindings[action]))
            lbl = tk.Label(row, textvariable=lv,
                           font=("Consolas", 8), bg=BG3, fg=AHL,
                           width=28, anchor="w")
            lbl.pack(side="left", padx=6)

            btn = tk.Button(row, text="Change",
                            width=self._BTN_W,
                            command=lambda a=action: self._start_record(a),
                            font=FS, bg=BG4, fg=TEXT,
                            activebackground=A, activeforeground=TEXT,
                            relief="flat", cursor="hand2")
            btn.pack(side="left", padx=2)

            rst = tk.Button(row, text="Reset",
                            width=self._BTN_W,
                            command=lambda a=action: self._reset(a),
                            font=FS, bg=BG4, fg=DIM,
                            activebackground=BG, activeforeground=TEXT,
                            relief="flat", cursor="hand2")
            rst.pack(side="left", padx=2)

            self._rows[action] = {"lv": lv, "lbl": lbl, "btn": btn, "rst": rst}

        # Disable all buttons when keyboard package is unavailable
        if not _KB:
            for r in self._rows.values():
                r["btn"].config(state="disabled")
                r["rst"].config(state="disabled")

    # ── recording ─────────────────────────────────────────────────────────────

    def _start_record(self, action: str):
        if not _KB:
            return
        if self._recording:
            return   # already recording something

        self._recording = action
        row = self._rows[action]

        # Visually enter record mode
        row["lv"].set("  Press keys…")
        row["lbl"].config(fg=WARN)
        row["btn"].config(text="Cancel", command=lambda: self._cancel_record(action))
        for a, r in self._rows.items():
            if a != action:
                r["btn"].config(state="disabled")
                r["rst"].config(state="disabled")

        threading.Thread(target=self._capture, args=(action,), daemon=True).start()

    def _capture(self, action: str):
        """
        Capture a key combo using pynput Listener (no admin required).
        Collects modifier keys as they are held, then finalises on the first
        non-modifier key release. ESC alone cancels.
        """
        if not _KB:
            self._schedule(lambda: self._finish_record(action, None))
            return

        pressed_names: list[str] = []
        result:        list[str | None] = [None]
        done_event = threading.Event()
        _MODS      = KeyboardInput._MODS

        def on_press(key):
            name = KeyboardInput._key_id(key)
            if name and name not in pressed_names:
                pressed_names.append(name)

        def on_release(key):
            name = KeyboardInput._key_id(key)
            if name and name not in _MODS:
                if name == "escape" and not any(
                        k not in _MODS for k in pressed_names if k != "escape"):
                    done_event.set()
                    return False
                mods = [k for k in pressed_names if k in _MODS]
                result[0] = "+".join(mods + [name])
                done_event.set()
                return False

        listener = _pynput_kb.Listener(on_press=on_press, on_release=on_release)
        listener.start()
        done_event.wait(timeout=15)
        listener.stop()
        self._schedule(lambda: self._finish_record(action, result[0]))

    def _finish_record(self, action: str, combo: str | None):
        if self._recording != action:
            return   # was cancelled
        self._recording = None

        row = self._rows[action]
        if combo:
            # Normalise to lowercase with + separator (keyboard library format)
            normalised = combo.lower().replace(" ", "")
            cfg_key    = KeyboardInput.CFG_KEYS[action]
            self._cfg[cfg_key] = normalised
            row["lv"].set(_fmt_hotkey(normalised))
            row["lbl"].config(fg=AHL)
        else:
            # Capture failed — restore previous value
            row["lv"].set(_fmt_hotkey(
                self._cfg.get(KeyboardInput.CFG_KEYS[action])
                or KeyboardInput.DEFAULTS[action]))
            row["lbl"].config(fg=AHL)

        row["btn"].config(text="Change",
                          command=lambda a=action: self._start_record(a),
                          state="normal")
        for r in self._rows.values():
            r["btn"].config(state="normal" if _KB else "disabled")
            r["rst"].config(state="normal" if _KB else "disabled")



    def _cancel_record(self, action: str):
        """Cancel an in-progress recording without applying a new binding."""
        prev = self._recording
        self._recording = None
        try:
            ctrl = _pynput_kb.Controller()
            ctrl.tap(_pynput_kb.Key.escape)
        except Exception:
            pass
        if prev:
            self._finish_record(prev, None)

    def _reset(self, action: str):
        default  = KeyboardInput.DEFAULTS[action]
        cfg_key  = KeyboardInput.CFG_KEYS[action]
        self._cfg[cfg_key] = default
        self._rows[action]["lv"].set(_fmt_hotkey(default))
        self._rows[action]["lbl"].config(fg=AHL)



# ─── Custom preset editor dialog ─────────────────────────────────────────────

class PresetEditorDialog:
    """
    Small modal dialog for adding or editing a custom preset.
    Calls on_save(name: str, height: float) when confirmed.
    """
    def __init__(self, parent: tk.Tk, on_save,
                 initial_name: str = "", initial_height: float = 1.65):
        self._on_save = on_save

        self.win = tk.Toplevel(parent)
        self.win.title("Custom Preset")
        self.win.configure(bg=BG)
        self.win.resizable(False, False)
        self.win.grab_set()
        self.win.attributes("-topmost", True)

        parent.update_idletasks()
        pw, ph = parent.winfo_width(), parent.winfo_height()
        px, py = parent.winfo_x(), parent.winfo_y()

        # Header
        tk.Frame(self.win, bg=A, height=4).pack(fill="x")
        tk.Label(self.win, text="  Custom Preset",
                 font=FH, bg=BG2, fg=AHL).pack(fill="x", ipady=7)

        body = tk.Frame(self.win, bg=BG)
        body.pack(padx=20, pady=14, fill="x")

        # Name
        tk.Label(body, text="Name:", font=FB, bg=BG, fg=TEXT).pack(anchor="w")
        self._name_var = tk.StringVar(value=initial_name)
        name_entry = tk.Entry(body, textvariable=self._name_var,
                              width=22, font=FB,
                              bg=BG3, fg=TEXT, insertbackground=TEXT,
                              relief="flat", bd=0,
                              highlightbackground=A, highlightthickness=1)
        name_entry.pack(fill="x", ipady=4, pady=(2, 10))

        # Height
        tk.Label(body, text="Eye height (metres):", font=FB, bg=BG, fg=TEXT).pack(anchor="w")
        self._h_var = tk.StringVar(value=f"{initial_height:.3f}")
        h_entry = tk.Entry(body, textvariable=self._h_var,
                           width=22, font=FB,
                           bg=BG3, fg=TEXT, insertbackground=TEXT,
                           relief="flat", bd=0,
                           highlightbackground=A, highlightthickness=1)
        h_entry.pack(fill="x", ipady=4, pady=(2, 0))
        Tooltip(h_entry, "Eye height in metres. "
                         "Accepts metres (1.65) or feet/inches (5'5\").")

        self._err = tk.Label(body, text="", font=FS, bg=BG, fg=ERR)
        self._err.pack(anchor="w", pady=(4, 0))

        # Buttons
        tk.Frame(self.win, bg=A, height=1).pack(fill="x")
        br = tk.Frame(self.win, bg=BG)
        br.pack(fill="x", padx=20, pady=10)
        tk.Button(br, text="Save",
                  command=self._save,
                  font=FB, bg=A, fg=TEXT,
                  activebackground=A2, activeforeground=TEXT,
                  relief="flat", padx=14, pady=4, cursor="hand2").pack(side="left")
        tk.Button(br, text="Cancel",
                  command=self.win.destroy,
                  font=FB, bg=BG3, fg=DIM,
                  activebackground=BG4, activeforeground=TEXT,
                  relief="flat", padx=14, pady=4, cursor="hand2").pack(side="left", padx=8)

        # Bindings
        for e in (name_entry, h_entry):
            e.bind("<Return>",   lambda _: self._save())
            e.bind("<KP_Enter>", lambda _: self._save())
            e.bind("<Escape>",   lambda _: self.win.destroy())

        # Size and position
        self.win.update_idletasks()
        w = self.win.winfo_reqwidth()
        h = self.win.winfo_reqheight()
        x = px + (pw - w) // 2
        y = py + (ph - h) // 2
        self.win.geometry(f"{w}x{h}+{x}+{y}")
        name_entry.focus_set()
        name_entry.select_range(0, "end")

    def _save(self):
        name = self._name_var.get().strip()
        if not name:
            self._err.config(text="Name cannot be empty.")
            return
        # Re-use QuickInputDialog parser for height
        h = QuickInputDialog._parse(self._h_var.get())
        if h is None or h <= 0:
            self._err.config(text="Enter a valid height (e.g. 1.65 or 5'5\").")
            return
        h = _clamp(h, ABS_MIN, ABS_MAX)
        self._on_save(name, h)
        self.win.destroy()


# ─── Quick height input dialog ────────────────────────────────────────────────

class QuickInputDialog:
    """
    Small borderless always-on-top entry window for rapid height input.
    Triggered by the quick_input hotkey while VRChat is focused.

    • Shows the current height as a pre-selected placeholder.
    • Enter  — parses and applies the typed value, then closes.
    • Escape — closes without applying.
    • Focus loss — closes without applying.
    • Accepts values in metres (e.g. "1.5", "1.5m") or
      imperial shorthand (e.g. "5'11" or "5ft11in").
    """

    def __init__(self, root: tk.Tk, current_h: float, on_apply):
        self._on_apply = on_apply

        win = tk.Toplevel(root)
        self.win = win
        win.wm_overrideredirect(True)
        win.wm_attributes("-topmost", True)
        win.wm_attributes("-alpha", 0.96)
        win.configure(bg=A)   # accent-colour 1 px border

        inner = tk.Frame(win, bg=BG, padx=14, pady=10)
        inner.pack(padx=1, pady=1)

        # Label row
        lbl_row = tk.Frame(inner, bg=BG)
        lbl_row.pack(fill="x", pady=(0, 6))
        tk.Label(lbl_row, text="⬡  Quick Height Input",
                 font=FH, bg=BG, fg=AHL).pack(side="left")
        tk.Label(lbl_row, text="  Enter = apply   Esc = cancel",
                 font=FS, bg=BG, fg=DIM).pack(side="right")

        # Entry
        self._var = tk.StringVar(value=f"{current_h:.3f}")
        entry = tk.Entry(inner, textvariable=self._var,
                         width=16, font=("Segoe UI", 18, "bold"),
                         bg=BG2, fg=AHL, insertbackground=AHL,
                         relief="flat", bd=0,
                         highlightbackground=A, highlightthickness=1,
                         justify="center")
        entry.pack(fill="x", ipady=6)

        # Hint
        self._hint = tk.Label(inner, text="metres  •  e.g.  1.65  or  5'9\"",
                              font=FS, bg=BG, fg=DIM)
        self._hint.pack(pady=(5, 0))

        # Position: centred horizontally near the top of the screen
        win.update_idletasks()
        w  = win.winfo_reqwidth()
        h  = win.winfo_reqheight()
        sw = root.winfo_screenwidth()
        x  = (sw - w) // 2
        y  = 60
        win.geometry(f"+{x}+{y}")

        # Bindings
        entry.bind("<Return>",    self._submit)
        entry.bind("<KP_Enter>",  self._submit)
        entry.bind("<Escape>",    self._cancel)
        win.bind("<FocusOut>",    self._on_focus_out)

        # Defer focus — VRChat (especially fullscreen) holds OS focus tightly.
        # A short delay gives the window manager time to actually render the
        # Toplevel before we attempt to steal focus.
        def _grab():
            try:
                win.lift()
                win.focus_force()
                entry.focus_force()
                entry.select_range(0, "end")
            except Exception:
                pass
        win.after(80, _grab)

    # ── input parsing ─────────────────────────────────────────────────────────

    @staticmethod
    def _parse(raw: str) -> float | None:
        """
        Try to parse a height value from a human-typed string.
        Handles:
          • plain metres:  "1.65", "1.65m"
          • feet/inches:   "5'9", "5'9\"", "5ft 9in", "5ft9"
          • inches only:   "69in"
        Returns metres as a float, or None if unparsable.
        """
        import re
        s = raw.strip().lower().replace(",", ".")

        # feet + inches: 5'9, 5'9", 5ft9in, 5 ft 9 in, etc.
        m = re.fullmatch(
            r"""(\d+(?:\.\d+)?)\s*(?:ft|feet|'|′)\s*"""
            r"""(\d+(?:\.\d+)?)\s*(?:in|inch(?:es)?|"|″)?""",
            s)
        if m:
            feet, inches = float(m.group(1)), float(m.group(2))
            return (feet * 12 + inches) * 0.0254

        # feet only: 5ft, 5'
        m = re.fullmatch(r"""(\d+(?:\.\d+)?)\s*(?:ft|feet|'|′)""", s)
        if m:
            return float(m.group(1)) * 12 * 0.0254

        # inches only: 69in, 69"
        m = re.fullmatch(r"""(\d+(?:\.\d+)?)\s*(?:in|inch(?:es)?|"|″)""", s)
        if m:
            return float(m.group(1)) * 0.0254

        # metres: 1.65, 1.65m
        m = re.fullmatch(r"""(\d+(?:\.\d+)?)\s*m?""", s)
        if m:
            return float(m.group(1))

        return None

    # ── actions ───────────────────────────────────────────────────────────────

    def _submit(self, _=None):
        val = self._parse(self._var.get())
        if val is None:
            # Flash the hint red briefly to signal bad input
            self._hint.config(text="⚠  Could not parse — try e.g.  1.65  or  5'9\"",
                              fg=ERR)
            self.win.after(1800, lambda: self._hint.config(
                text="metres  •  e.g.  1.65  or  5'9\"", fg=DIM))
            return
        self._on_apply(val)
        self.win.destroy()

    def _cancel(self, _=None):
        self.win.destroy()

    def _on_focus_out(self, event):
        # Only close if focus moved completely outside the dialog
        if event.widget == self.win:
            self.win.after(50, self._check_focus)

    def _check_focus(self):
        try:
            focused = self.win.focus_get()
            if focused is None or str(focused) not in str(self.win):
                self.win.destroy()
        except Exception:
            try: self.win.destroy()
            except Exception: pass


# ─── Range warning dialog ─────────────────────────────────────────────────────
class RangeWarning:
    def __init__(self, parent: tk.Tk, on_suppress):
        self.win = tk.Toplevel(parent)
        self.win.title("Unsupported Scale Range")
        self.win.configure(bg=BG)
        self.win.resizable(False, False)
        self.win.grab_set(); self.win.focus_force()
        parent.update_idletasks()
        pw, ph = parent.winfo_width(), parent.winfo_height()
        px, py = parent.winfo_x(), parent.winfo_y()
        self.win.geometry(f"+{px+(pw-460)//2}+{py+(ph-460)//2}")
        self.win.minsize(460, 0)
        self._sup = on_suppress
        self._build()

    def _build(self):
        tk.Frame(self.win, bg=WARN, height=8).pack(fill="x")
        banner = tk.Frame(self.win, bg="#281800")
        banner.pack(fill="x")
        tk.Label(banner, text="⚠  Unsupported Scale Range",
                 font=("Segoe UI", 13, "bold"), bg="#281800", fg=WARN).pack(
                 anchor="w", padx=16, pady=10)

        body = tk.Frame(self.win, bg=BG)
        body.pack(fill="both", expand=True, padx=20, pady=12)
        msg = (
            "The height you have selected falls outside VRChat's officially\n"
            "supported range of  0.1 m – 100 m.\n\n"
            "Operating outside this range is unsupported behaviour. Known issues\n"
            "include but may not be limited to:\n\n"
            "  •  Visual artefacts and rendering anomalies\n"
            "  •  IK and body-tracking misalignment or breakdown\n"
            "  •  UI and world menus may be very difficult or impossible\n"
            "     to interact with at extreme scales"
        )
        tk.Label(body, text=msg, font=FB, bg=BG, fg=TEXT, justify="left").pack(anchor="w")

        # Urgent notice — visually distinct
        notice_frame = tk.Frame(body, bg=WARN)
        notice_frame.pack(fill="x", pady=(12, 0))
        notice_inner = tk.Frame(notice_frame, bg="#281800")
        notice_inner.pack(padx=1, pady=1, fill="x")
        tk.Label(notice_inner,
                 text="⚠  Do not report bugs or contact VRChat Support\n"
                      "    for any issues encountered outside this range.",
                 font=("Segoe UI", 10, "bold"), bg="#281800", fg=WARN,
                 justify="left", padx=10, pady=8).pack(anchor="w")
        self._svar = tk.BooleanVar(value=False)
        tk.Checkbutton(body, text="Do not show this warning again",
                       variable=self._svar, font=FS,
                       bg=BG, fg=DIM, selectcolor=BG3,
                       activebackground=BG, activeforeground=TEXT,
                       highlightthickness=0).pack(anchor="w", pady=(10,0))
        tk.Frame(self.win, bg=BG3, height=1).pack(fill="x")
        br = tk.Frame(self.win, bg=BG)
        br.pack(fill="x", padx=20, pady=10)
        tk.Button(br, text="I understand — continue",
                  command=self._ok,
                  font=FB, bg=WARN, fg="#1a1200",
                  activebackground="#d48820", activeforeground="#1a1200",
                  relief="flat", padx=14, pady=5, cursor="hand2").pack(side="left")

    def _ok(self):
        self._sup(self._svar.get()); self.win.destroy()


# ─── Settings window ──────────────────────────────────────────────────────────
class Settings:
    def __init__(self, parent: tk.Tk, cfg: dict, on_save, get_h):
        self._cfg    = cfg
        self._save   = on_save
        self._get_h  = get_h
        self.win     = tk.Toplevel(parent)
        self.win.title("Settings — VRChat Avatar Scaler")
        self.win.configure(bg=BG)
        self.win.resizable(True, True)
        self.win.grab_set()
        self.win.minsize(500, 320)

        # ── Fixed header ──────────────────────────────────────────────────
        th = tk.Frame(self.win, bg=A)
        th.pack(fill="x", side="top")
        tk.Label(th, text="⚙  Settings", font=FT, bg=A, fg=TEXT).pack(
            anchor="w", padx=16, pady=10)

        # ── Fixed footer (Save / Cancel) ──────────────────────────────────
        footer = tk.Frame(self.win, bg=BG)
        footer.pack(fill="x", side="bottom")
        tk.Frame(footer, bg=A, height=1).pack(fill="x")
        br = tk.Frame(footer, bg=BG)
        br.pack(fill="x", padx=20, pady=10)
        tk.Button(br, text="Save Settings",
                  command=self._do_save,
                  font=FB, bg=A, fg=TEXT,
                  activebackground=A2, activeforeground=TEXT,
                  relief="flat", padx=14, pady=5, cursor="hand2").pack(side="left")
        tk.Button(br, text="Cancel",
                  command=self.win.destroy,
                  font=FB, bg=BG3, fg=DIM,
                  activebackground=BG4, activeforeground=TEXT,
                  relief="flat", padx=14, pady=5, cursor="hand2").pack(side="left", padx=8)

        # ── Scrollable middle area ─────────────────────────────────────────
        scroll_outer = tk.Frame(self.win, bg=BG)
        scroll_outer.pack(fill="both", expand=True, side="top")

        self._canvas = tk.Canvas(scroll_outer, bg=BG, highlightthickness=0,
                                 borderwidth=0)
        scrollbar = ttk.Scrollbar(scroll_outer, orient="vertical",
                                  command=self._canvas.yview)
        self._canvas.configure(yscrollcommand=scrollbar.set)

        scrollbar.pack(side="right", fill="y")
        self._canvas.pack(side="left", fill="both", expand=True)

        # Inner frame that holds all sections
        self._inner = tk.Frame(self._canvas, bg=BG)
        self._win_id = self._canvas.create_window((0, 0), window=self._inner,
                                                   anchor="nw")

        self._inner.bind("<Configure>", self._on_inner_configure)
        self._canvas.bind("<Configure>", self._on_canvas_configure)

        # Mouse wheel scrolling
        self.win.bind_all("<MouseWheel>",
            lambda e: self._canvas.yview_scroll(-1*(1 if e.delta>0 else -1), "units"))

        self._build()

        # Initial window size: full content height up to 80% of screen, min 400px
        self.win.update_idletasks()
        content_h = self._inner.winfo_reqheight()
        w_req     = max(500, self._inner.winfo_reqwidth() + 18)
        max_h     = int(parent.winfo_screenheight() * 0.80)
        win_h     = min(content_h + th.winfo_reqheight() + footer.winfo_reqheight() + 4,
                        max_h)
        win_h     = max(win_h, 400)
        x = parent.winfo_x() + 60
        y = parent.winfo_y() + 20
        # Don't let the window start off-screen
        y = min(y, parent.winfo_screenheight() - win_h - 40)
        self.win.geometry(f"{w_req}x{win_h}+{x}+{y}")

    def _on_inner_configure(self, _=None):
        self._canvas.configure(scrollregion=self._canvas.bbox("all"))

    def _on_canvas_configure(self, e):
        self._canvas.itemconfig(self._win_id, width=e.width)

    def _section(self, title: str) -> tk.Frame:
        tk.Frame(self._inner, bg=A, height=1).pack(fill="x")
        tk.Label(self._inner, text=f"  {title}", font=FH, bg=BG2, fg=AHL).pack(
            fill="x", ipady=6)
        f = tk.Frame(self._inner, bg=BG)
        f.pack(fill="x", padx=20, pady=(6, 10))
        return f

    def _entry(self, parent, var, width=10):
        e = tk.Entry(parent, textvariable=var, width=width,
                     font=FB, bg=BG3, fg=TEXT, insertbackground=TEXT,
                     relief="flat", bd=0,
                     highlightbackground=A, highlightthickness=1)
        return e

    def _check(self, parent, text: str, var: tk.BooleanVar,
               tip: str = "", cmd=None) -> tk.Checkbutton:
        cb = tk.Checkbutton(parent, text=text, variable=var, command=cmd,
                            font=FB, bg=BG, fg=TEXT, selectcolor=BG3,
                            activebackground=BG, activeforeground=TEXT,
                            highlightthickness=0)
        cb.pack(anchor="w", pady=2)
        if tip: Tooltip(cb, tip)
        return cb

    def _build(self):
        # ── Default height ────────────────────────────────────────────────
        s = self._section("Default Height")
        tk.Label(s, text="Applied when pressing '↺ Default' or on avatar/world change.",
                 font=FS, bg=BG, fg=DIM).pack(anchor="w", pady=(0, 6))

        row = tk.Frame(s, bg=BG); row.pack(fill="x")
        self._dh = tk.StringVar(value=f"{self._cfg['default_height']:.3f}")
        e = self._entry(row, self._dh)
        e.pack(side="left")
        Tooltip(e, "The eye height in metres to use as your default. "
                   "Click 'Use Current' to capture the height currently active.")
        tk.Label(row, text="m", font=FB, bg=BG, fg=DIM).pack(side="left", padx=4)
        btn = tk.Button(row, text="Use Current Height",
                        command=lambda: self._dh.set(f"{self._get_h():.3f}"),
                        font=FS, bg=BG3, fg=DIM,
                        activebackground=BG4, activeforeground=TEXT,
                        relief="flat", padx=8, pady=2, cursor="hand2")
        btn.pack(side="left", padx=10)
        Tooltip(btn, "Captures the height currently active in the main window as your new default.")

        # ── On avatar / world change ──────────────────────────────────────
        s2 = self._section("On Avatar / World Change")
        self._ret  = tk.BooleanVar(value=self._cfg["retain_on_change"])
        self._apd  = tk.BooleanVar(value=self._cfg["apply_default_on_change"])

        self._check(s2, "Retain active height",      self._ret,
                    "Re-sends your currently active height immediately after each avatar "
                    "or world change, so VRChat always reflects your intended size.",
                    cmd=lambda: self._apd.set(False) if self._ret.get() else None)

        self._check(s2, "Apply default height",      self._apd,
                    "Resets to your configured default height immediately after each avatar "
                    "or world change.",
                    cmd=lambda: self._ret.set(False) if self._apd.get() else None)

        # ── Lifecycle ─────────────────────────────────────────────────────
        s3 = self._section("Lifecycle")
        self._ac     = tk.BooleanVar(value=self._cfg["auto_close_with_vrchat"])
        self._al     = tk.BooleanVar(value=self._cfg["auto_launch_with_vrchat"])
        self._mini   = tk.BooleanVar(value=self._cfg["start_minimized"])
        # Read the startup shortcut's actual state from disk, not just config
        self._startup = tk.BooleanVar(value=_startup_is_enabled())
        self._check(s3, "Run on Windows startup", self._startup,
                    "Creates a shortcut in your Windows startup folder so the scaler "
                    "launches automatically when you log in. "
                    "Pair with 'Start minimized to tray' to keep it out of the way "
                    "until VRChat is running.")
        self._close_tray = tk.BooleanVar(value=self._cfg.get("close_to_tray", True))
        self._check(s3, "Hide to tray when closing window",
                    self._close_tray,
                    "When ticked, clicking the × button hides the scaler to the system "
                    "tray rather than exiting. Use Quit in the tray menu to exit fully.\n\n"
                    "When unticked, the × button exits the application completely.")
        self._check(s3, "Auto-launch when VRChat starts", self._al,
                    "The scaler will automatically show its window when VRChat is detected "
                    "as running. Useful when starting the scaler before VRChat.")
        self._check(s3, "Auto-close when VRChat exits", self._ac,
                    "The scaler will exit automatically 1.5 seconds after VRChat closes.")
        self._check(s3, "Start minimized to system tray", self._mini,
                    "The window will be hidden to the system tray on launch. "
                    "Click the tray icon to show it.")

        # ── Warnings ──────────────────────────────────────────────────────
        s4 = self._section("Warnings")
        self._sup  = tk.BooleanVar(value=self._cfg["suppress_range_warning"])
        self._check(s4, "Suppress out-of-range warning", self._sup,
                    "Disables the warning dialog shown when you set a height outside "
                    "VRChat's officially supported range of 0.1 m – 100 m.")

        # ── Controls ──────────────────────────────────────────────────────
        s_ctrl = self._section("Controls")

        # Keyboard
        kb_hdr = tk.Frame(s_ctrl, bg=BG); kb_hdr.pack(fill="x", pady=(0,4))
        self._kb_en = tk.BooleanVar(value=self._cfg.get("keyboard_enabled", True))
        kb_cb = self._check(kb_hdr, "Enable keyboard shortcuts (global)", self._kb_en,
                            "Register system-wide hotkeys so you can adjust scale even "
                            "when the window is hidden to the tray. "
                            "Requires the 'pynput' package (pip install pynput). "
                            "No administrator rights required.")
        if not _KB:
            kb_cb.config(state="disabled")
            tk.Label(kb_hdr,
                     text="  ⚠ 'pynput' package not installed — run Install.bat to set it up",
                     font=FS, bg=BG, fg=WARN).pack(anchor="w")

        # Interactive hotkey recorder
        self._hotkey_recorder = HotkeyRecorder(
            s_ctrl, self._cfg,
            schedule=lambda fn: self.win.after(0, fn))
        self._hotkey_recorder.pack(fill="x", pady=(0, 8))

        # ── Network ───────────────────────────────────────────────────────
        s5 = self._section("Network")

        # OSCQuery toggle
        self._oscq_en = tk.BooleanVar(value=self._cfg.get("oscquery_enabled", True))
        oscq_cb = self._check(s5,
            "Use OSCQuery for automatic port negotiation  (recommended)",
            self._oscq_en,
            "OSCQuery lets VRChat and the scaler find each other automatically "
            "using any available ports, eliminating conflicts with other OSC applications. "
            "When enabled, the fixed send/receive ports below are used as fallbacks only. "
            "Requires the 'tinyoscquery' package (pip install tinyoscquery).")
        if not _OSCQ:
            oscq_cb.config(state="disabled")
            tk.Label(s5,
                     text="  ⚠ 'tinyoscquery' not installed — run Install.bat to set it up\n"
                          "     (requires Git: https://git-scm.com/downloads)",
                     font=FS, bg=BG, fg=WARN).pack(anchor="w", pady=(0, 6))
        else:
            tk.Label(s5,
                     text="    When OSCQuery is active, VRChat shows a HUD notification "
                          "that it found this application.",
                     font=FS, bg=BG, fg=DIM).pack(anchor="w", pady=(0, 6))

        tk.Frame(s5, bg=BG3, height=1).pack(fill="x", pady=(4, 8))
        tk.Label(s5, text="Fixed ports (used when OSCQuery is disabled or unavailable):",
                 font=FS, bg=BG, fg=DIM).pack(anchor="w", pady=(0, 4))

        nr = tk.Frame(s5, bg=BG); nr.pack(fill="x")
        tk.Label(nr, text="VRChat IP:", font=FB, bg=BG, fg=DIM).pack(side="left")
        self._ip = tk.StringVar(value=self._cfg["vrc_ip"])
        e_ip = self._entry(nr, self._ip, 14); e_ip.pack(side="left", padx=(4,14))
        Tooltip(e_ip, "IP address of the machine running VRChat. "
                      "Leave as 127.0.0.1 if running on the same PC.")
        tk.Label(nr, text="Send:", font=FB, bg=BG, fg=DIM).pack(side="left")
        self._sp = tk.StringVar(value=str(self._cfg["send_port"]))
        e_sp = self._entry(nr, self._sp, 6); e_sp.pack(side="left", padx=(4,14))
        Tooltip(e_sp, "UDP port the scaler sends to. VRChat listens on 9000 by default.")
        tk.Label(nr, text="Recv:", font=FB, bg=BG, fg=DIM).pack(side="left")
        self._rp = tk.StringVar(value=str(self._cfg["recv_port"]))
        e_rp = self._entry(nr, self._rp, 6); e_rp.pack(side="left", padx=4)
        Tooltip(e_rp, "UDP port the scaler listens on. VRChat sends on 9001 by default.")

    def _do_save(self):
        try:   dh = _clamp(float(self._dh.get().replace(",",".")), ABS_MIN, ABS_MAX)
        except: dh = self._cfg["default_height"]
        try:   sp, rp = int(self._sp.get()), int(self._rp.get())
        except: sp, rp = self._cfg["send_port"], self._cfg["recv_port"]
        self._cfg.update({
            "default_height":           dh,
            "retain_on_change":         self._ret.get(),
            "apply_default_on_change":  self._apd.get(),
            "auto_close_with_vrchat":   self._ac.get(),
            "auto_launch_with_vrchat":  self._al.get(),
            "run_on_startup":           self._startup.get(),
            "close_to_tray":            self._close_tray.get(),
            "start_minimized":          self._mini.get(),
            "suppress_range_warning":   self._sup.get(),
            "oscquery_enabled":         self._oscq_en.get(),
            "keyboard_enabled":         self._kb_en.get(),
            "vrc_ip":                   self._ip.get().strip(),
            "send_port":                sp,
            "recv_port":                rp,
        })
        _save(self._cfg)
        # Apply startup shortcut change immediately
        _set_startup(self._startup.get())
        self._save()
        self.win.destroy()


# ─── Foreground window detection ─────────────────────────────────────────────

try:
    _u32  = _ctypes.windll.user32
    _k32  = _ctypes.windll.kernel32

    def _vrc_is_foreground() -> bool:
        """Return True only if the VRChat process owns the foreground window."""
        hwnd = _u32.GetForegroundWindow()
        if not hwnd:
            return False
        # Retrieve the PID of the process that owns the foreground window
        pid = _ctypes.c_ulong(0)
        _u32.GetWindowThreadProcessId(hwnd, _ctypes.byref(pid))
        if not pid.value:
            return False
        # Check whether that PID belongs to VRChat by executable name
        try:
            proc = psutil.Process(pid.value)
            return "vrchat" in (proc.name() or "").lower()
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            return False
except Exception:
    def _vrc_is_foreground() -> bool:
        return True   # non-Windows fallback: always visible


# ─── Height overlay ───────────────────────────────────────────────────────────

class HeightOverlay:
    """
    Small borderless always-on-top window showing the current eye height.
    Auto-hides when VRChat is not the foreground window.
    Draggable; position persists in config.
    """
    _ALPHA    = 0.90
    _POLL_S   = 0.15   # focus-check interval

    def __init__(self, root: tk.Tk, cfg: dict):
        self._root     = root
        self._cfg      = cfg
        self._win:     tk.Toplevel | None = None
        self._m_var:   tk.StringVar | None = None
        self._imp_var: tk.StringVar | None = None
        self._m_lbl:   tk.Label    | None = None
        self._enabled: bool = bool(cfg.get("overlay_enabled", False))
        self._focused: bool = False
        self._h:       float = float(cfg.get("last_height", 1.65))

        # Drag state
        self._drag_ox = 0
        self._drag_oy = 0

        self._poll_running = True
        threading.Thread(target=self._poll_loop, daemon=True).start()

    # ── public API ────────────────────────────────────────────────────────────

    @property
    def enabled(self) -> bool:
        return self._enabled

    def set_enabled(self, val: bool):
        self._enabled = val
        self._cfg["overlay_enabled"] = val
        self._apply_vis()

    def toggle(self):
        self.set_enabled(not self._enabled)

    def update_height(self, h: float):
        self._h = h
        if self._win and self._win.winfo_viewable():
            self._refresh_text()

    def destroy(self):
        self._poll_running = False
        if self._win:
            try:   self._win.destroy()
            except Exception: pass

    # ── window ────────────────────────────────────────────────────────────────

    def _build(self):
        w = tk.Toplevel(self._root)
        w.wm_overrideredirect(True)
        w.wm_attributes("-topmost", True)
        w.wm_attributes("-alpha", self._ALPHA)
        w.configure(bg=A)   # 1-px accent border via outer bg

        inner = tk.Frame(w, bg="#0d0d1f", padx=12, pady=8)
        inner.pack(padx=1, pady=1, fill="both", expand=True)

        # Header row
        hdr = tk.Frame(inner, bg="#0d0d1f")
        hdr.pack(fill="x")
        tk.Label(hdr, text="⬡  Eye Height",
                 font=("Segoe UI", 7), bg="#0d0d1f", fg=A2).pack(side="left")
        x_lbl = tk.Label(hdr, text="✕",
                         font=("Segoe UI", 7), bg="#0d0d1f", fg=DIM,
                         cursor="hand2")
        x_lbl.pack(side="right")
        x_lbl.bind("<Button-1>", lambda _: self.set_enabled(False))

        # Metric display
        self._m_var   = tk.StringVar()
        self._imp_var = tk.StringVar()
        self._m_lbl   = tk.Label(inner, textvariable=self._m_var,
                                 font=("Segoe UI", 22, "bold"),
                                 bg="#0d0d1f", fg=AHL)
        self._m_lbl.pack()
        tk.Label(inner, textvariable=self._imp_var,
                 font=("Consolas", 9), bg="#0d0d1f", fg=DIM).pack()

        # Drag bindings on all non-interactive surfaces
        for widget in (w, inner, hdr):
            widget.bind("<ButtonPress-1>",   self._drag_start)
            widget.bind("<B1-Motion>",       self._drag_move)
            widget.bind("<ButtonRelease-1>", self._drag_end)
            widget.config(cursor="fleur")
        # Restore default cursor and no-drag on the close button
        x_lbl.config(cursor="hand2")
        x_lbl.bind("<ButtonPress-1>",   lambda e: "break")   # don't drag on close
        x_lbl.bind("<B1-Motion>",       lambda e: "break")

        # Position — default: top-right corner with margin
        x = self._cfg.get("overlay_x")
        y = self._cfg.get("overlay_y")
        if x is None or y is None:
            x = self._root.winfo_screenwidth() - 200
            y = 40
        w.geometry(f"+{int(x)}+{int(y)}")
        self._win = w
        self._refresh_text()

    def _refresh_text(self):
        if not self._m_var:
            return
        out = self._h < SAFE_MIN or self._h > SAFE_MAX
        self._m_var.set(f"{self._h:.3f} m")
        self._imp_var.set(_imp(self._h))
        if self._m_lbl:
            self._m_lbl.config(fg=WARN if out else AHL)

    # ── visibility ────────────────────────────────────────────────────────────

    def _apply_vis(self):
        """Must be called on the main thread."""
        if self._enabled and self._focused:
            if self._win is None:
                self._build()
            else:
                self._refresh_text()
                self._win.deiconify()
        elif self._win is not None:
            self._win.withdraw()

    # ── drag ──────────────────────────────────────────────────────────────────

    def _drag_start(self, e):
        self._drag_ox = e.x_root - self._win.winfo_x()
        self._drag_oy = e.y_root - self._win.winfo_y()

    def _drag_move(self, e):
        if self._win:
            x = e.x_root - self._drag_ox
            y = e.y_root - self._drag_oy
            x, y = self._clamped(x, y)
            self._win.geometry(f"+{x}+{y}")

    def _drag_end(self, e):
        if self._win:
            x, y = self._clamped(self._win.winfo_x(), self._win.winfo_y())
            self._win.geometry(f"+{x}+{y}")
            self._cfg["overlay_x"] = x
            self._cfg["overlay_y"] = y

    def _clamped(self, x: int, y: int) -> tuple[int, int]:
        """Clamp overlay position so it stays fully within the screen bounds."""
        self._win.update_idletasks()
        sw = self._root.winfo_screenwidth()
        sh = self._root.winfo_screenheight()
        ww = self._win.winfo_width()
        wh = self._win.winfo_height()
        x  = _clamp(x, 0, max(0, sw - ww))
        y  = _clamp(y, 0, max(0, sh - wh))
        return int(x), int(y)

    # ── focus poll ────────────────────────────────────────────────────────────

    def _poll_loop(self):
        while self._poll_running:
            focused = _vrc_is_foreground()
            if focused != self._focused:
                self._focused = focused
                self._root.after(0, self._apply_vis)
            time.sleep(self._POLL_S)


# ─── OSCQuery manager ─────────────────────────────────────────────────────────

class OSCQueryManager:
    """
    Handles OSCQuery service advertisement and VRChat discovery.

    When active:
      • Picks a free UDP port for the OSC listener (no fixed 9001 conflict).
      • Picks a free TCP port for the OSCQuery HTTP server.
      • Advertises the service via mDNS so VRChat finds us automatically.
      • Advertises /avatar in the address tree so VRChat sends avatar events here.
      • Discovers VRChat's own OSCQuery service to learn its actual OSC send port.
      • Calls on_vrc_found(ip, osc_port) when VRChat is discovered.

    Falls back gracefully if tinyoscquery is not installed or fails.
    """
    SERVICE_NAME     = "VRChatAvatarScaler"
    DISCOVERY_DELAY  = 2.0    # seconds to wait for mDNS responses
    RETRY_INTERVAL   = 10.0   # seconds between re-discovery attempts

    def __init__(self, on_vrc_found, on_status):
        self._on_found   = on_vrc_found    # callback(ip: str, port: int)
        self._on_status  = on_status       # callback(msg: str, ok: bool)
        self._service:   OSCQueryService | None = None
        self._running    = False
        self._recv_port: int | None = None   # dynamic UDP port we chose

    @property
    def recv_port(self) -> int | None:
        """The dynamic UDP port the OSC server should listen on, or None."""
        return self._recv_port

    def start(self, cfg: dict, osc_port_hint: int):
        """
        Start advertising and begin VRChat discovery.
        osc_port_hint is the fallback if dynamic port allocation fails.
        """
        if not _OSCQ or not cfg.get("oscquery_enabled", True):
            return

        try:
            self._recv_port = get_open_udp_port()
            http_port       = get_open_tcp_port()
        except Exception:
            self._recv_port = osc_port_hint
            http_port       = osc_port_hint + 1

        try:
            self._service = OSCQueryService(
                self.SERVICE_NAME, http_port, self._recv_port
            )
            # Advertise /avatar so VRChat knows to send us avatar change events
            # and all avatar parameter updates (including /avatar/eyeheight).
            self._service.advertise_endpoint(
                "/avatar",
                access=OSCAccess.WRITEONLY_VALUE
            )
            self._on_status(
                f"OSCQuery active — listening on :{self._recv_port} "
                f"(HTTP :{http_port})", True)
        except Exception as e:
            self._on_status(f"OSCQuery failed to start: {e}", False)
            self._recv_port = None
            self._service   = None
            return

        self._running = True
        threading.Thread(target=self._discover_loop, daemon=True).start()

    def stop(self):
        self._running = False
        if self._service:
            try:
                del self._service   # triggers __del__ → unregister_all_services
            except Exception:
                pass
            self._service = None

    def restart(self, cfg: dict, osc_port_hint: int):
        self.stop()
        time.sleep(0.3)
        self.start(cfg, osc_port_hint)

    # ── discovery ─────────────────────────────────────────────────────────────

    def _discover_loop(self):
        """Periodically browse for VRChat's OSCQuery service."""
        while self._running:
            try:
                browser = OSCQueryBrowser()
                time.sleep(self.DISCOVERY_DELAY)
                svc = browser.find_service_by_name("VRChat")
                if svc:
                    client    = OSCQueryClient(svc)
                    host_info = client.get_host_info()
                    if host_info:
                        self._on_found(host_info.osc_ip, host_info.osc_port)
                        return   # found — stop discovery loop
            except Exception:
                pass
            # Wait before retrying
            for _ in range(int(self.RETRY_INTERVAL / 0.5)):
                if not self._running:
                    return
                time.sleep(0.5)


# ─── Main application ─────────────────────────────────────────────────────────
class ScalerApp:
    def __init__(self, root: tk.Tk):
        self.root  = root
        self.cfg   = _load()

        self._h:         float         = self.cfg["last_height"]
        self._vrc_on:    bool          = False
        self._supp:      bool          = False   # slider ↔ entry guard
        self._warned:    bool          = False
        self._udon_min:  float | None  = None
        self._udon_max:  float | None  = None
        self._locked:    bool          = False
        self._svr_on:      bool          = False   # server started
        self.tray:         pystray.Icon | None = None
        self._overlay:     HeightOverlay | None = None
        self._quick_input: QuickInputDialog | None = None

        # OSCQuery manager (optional — degrades gracefully)
        self._oscq = OSCQueryManager(
            on_vrc_found=lambda ip, port: self.root.after(
                0, lambda: self._on_vrc_oscquery_found(ip, port)),
            on_status=lambda msg, ok: self.root.after(0, lambda: self._status(msg, ok)),
        )

        # Input handlers
        self._kb_input   = KeyboardInput(
            schedule=lambda fn: root.after(0, fn),
            callbacks={
                "fine_up":       lambda: self._set(self._h * 1.01),
                "fine_down":     lambda: self._set(self._h * 0.99),
                "coarse_up":     lambda: self._set(self._h * 1.10),
                "coarse_down":   lambda: self._set(self._h * 0.90),
                "apply_default": self._apply_default,
                "quick_input":   self._show_quick_input,
            },
        )

        # OSC client
        self._osc = udp_client.SimpleUDPClient(self.cfg["vrc_ip"], self.cfg["send_port"])

        # Slider variable
        self._lv = tk.DoubleVar(value=_clamp(
            math.log10(max(self._h, 10**LOG_MIN)), LOG_MIN, LOG_MAX))

        root.title("VRChat Avatar Scaler")
        root.configure(bg=BG)
        root.resizable(True, True)
        root.minsize(920, 480)

        # Taskbar / window icon — supply multiple sizes so Windows picks the right one
        # for each context (title bar = 16px, taskbar = 32px, Alt-Tab = 48px)
        try:
            _icons = [ImageTk.PhotoImage(_make_icon(sz)) for sz in (16, 32, 48, 256)]
            root.iconphoto(True, *_icons)
            root._icon_refs = _icons   # prevent garbage collection
        except Exception:
            pass

        self._build()
        self._refresh_display(self._h)
        self._refresh_badges()

        self._tray_setup()
        self._oscq.start(self.cfg, self.cfg["recv_port"])
        self._osc_listen()
        self._vrc_monitor_start()

        root.protocol("WM_DELETE_WINDOW", self._on_close_button)
        if self.cfg.get("start_minimized"):
            root.after(150, self._hide)

        # Start input handlers and overlay after main loop is ready
        root.after(300, self._start_inputs)
        root.after(400, self._start_overlay)
        root.after(5000, self._start_update_check)   # delay so startup feels snappy

    # ── Build UI ──────────────────────────────────────────────────────────────
    def _build(self):
        # ── Title bar (full width) ────────────────────────────────────────
        tb = tk.Frame(self.root, bg=A)
        tb.pack(fill="x")
        tl = tk.Frame(tb, bg=A)
        tl.pack(side="left", padx=16, pady=10)
        tk.Label(tl, text="⬡  VRChat Avatar Scaler",
                 font=FT, bg=A, fg=TEXT).pack(anchor="w")
        tk.Label(tl, text="OSC Eye Height Controller  •  /avatar/eyeheight",
                 font=FS, bg=A, fg="#d8c8f0").pack(anchor="w")

        tr = tk.Frame(tb, bg=A)
        tr.pack(side="right", padx=12)
        sbtn = tk.Button(tr, text="⚙  Settings",
                         command=self._open_settings,
                         font=FS, bg=BG, fg=AHL,
                         activebackground=BG2, activeforeground=AHL,
                         relief="flat", padx=10, pady=5, cursor="hand2")
        sbtn.pack(side="right")
        Tooltip(sbtn, "Open Settings to configure default height, "
                      "avatar-change behaviour, lifecycle, and network options.", wrap=260)
        self._overlay_btn = tk.Button(tr, text="📏  Overlay",
                                      command=self._toggle_overlay,
                                      font=FS, bg=BG, fg=DIM,
                                      activebackground=BG2, activeforeground=AHL,
                                      relief="flat", padx=10, pady=5, cursor="hand2")
        self._overlay_btn.pack(side="right", padx=(0, 4))
        Tooltip(self._overlay_btn,
                "Toggle the floating height overlay.\n"
                "The overlay is only visible when VRChat is the active window.\n"
                "Drag it to reposition; click ✕ on the overlay to hide it.", wrap=280)

        # ── Update notification banner (hidden until an update is found) ───
        self._update_bar = tk.Frame(self.root, bg="#1a2a1a")
        # Not packed yet — shown only when update is available
        ub_inner = tk.Frame(self._update_bar, bg="#1a2a1a")
        ub_inner.pack(padx=12, pady=5, fill="x")
        self._update_lbl = tk.Label(ub_inner,
            text="", font=FS, bg="#1a2a1a", fg=OK, cursor="hand2")
        self._update_lbl.pack(side="left")
        self._update_lbl.bind("<Button-1>", lambda _: self._open_releases())
        tk.Button(ub_inner, text="✕", font=FS,
                  bg="#1a2a1a", fg=DIM, relief="flat",
                  activebackground="#1a2a1a", activeforeground=TEXT,
                  cursor="hand2",
                  command=self._dismiss_update_bar).pack(side="right")

        # ── VRChat status bar (full width) ────────────────────────────────
        vf = tk.Frame(self.root, bg=BG2)
        self._vrc_frame = vf
        vf.pack(fill="x")
        vf.configure(highlightbackground=BG3, highlightthickness=1)
        vi = tk.Frame(vf, bg=BG2)
        vi.pack(padx=14, pady=5, fill="x")
        tk.Label(vi, text="VRChat:", font=FB, bg=BG2, fg=DIM).pack(side="left")
        self._vrc_dot = tk.Label(vi, text="●", font=FB, bg=BG2, fg=DIM)
        self._vrc_dot.pack(side="left", padx=4)
        self._vrc_txt = tk.Label(vi, text="Not detected", font=FB, bg=BG2, fg=DIM)
        self._vrc_txt.pack(side="left")
        self._ret_badge = tk.Label(vi, text="", font=FS, bg=BG2, fg=A2)
        self._ret_badge.pack(side="right")

        # ── Two-column body (grid so both panels get correct height) ─────
        body = tk.Frame(self.root, bg=BG)
        body.pack(fill="both", expand=True)
        body.columnconfigure(0, weight=57, minsize=540)  # left panel
        body.columnconfigure(1, weight=0,  minsize=1)    # divider
        body.columnconfigure(2, weight=43, minsize=360)  # right panel
        body.rowconfigure(0, weight=1)
        LEFT  = tk.Frame(body, bg=BG)
        DIV   = tk.Frame(body, bg=BG3, width=1)
        RIGHT = tk.Frame(body, bg=BG)
        LEFT.grid( row=0, column=0, sticky="nsew", padx=(16, 8), pady=10)
        DIV.grid(  row=0, column=1, sticky="ns",   pady=6)
        RIGHT.grid(row=0, column=2, sticky="nsew", padx=(8, 14), pady=10)

        # ════ LEFT PANEL ═════════════════════════════════════════════════

        # Height display
        df = tk.Frame(LEFT, bg=BG2)
        df.pack(fill="x", pady=(0, 8))
        df.configure(highlightbackground=A, highlightthickness=1)
        di = tk.Frame(df, bg=BG2)
        di.pack(padx=16, pady=10)
        tk.Label(di, text="Current Eye Height", font=FS, bg=BG2, fg=DIM).pack()
        mr = tk.Frame(di, bg=BG2); mr.pack()
        self._m_lbl = tk.Label(mr, text="1.650",
                               font=("Segoe UI", 34, "bold"), bg=BG2, fg=AHL)
        self._m_lbl.pack(side="left")
        tk.Label(mr, text=" m", font=("Segoe UI", 18), bg=BG2, fg=DIM).pack(
            side="left", anchor="s", pady=6)
        self._imp_lbl = tk.Label(di, text="", font=FM, bg=BG2, fg=DIM)
        self._imp_lbl.pack()

        br2 = tk.Frame(di, bg=BG2); br2.pack(pady=(4,0))
        self._def_badge  = tk.Label(br2, text="", font=FS, bg=BG2, fg=DIM)
        self._def_badge.pack(side="left")
        self._rng_warn   = tk.Label(br2, text="",
                                    font=("Segoe UI", 8, "bold"), bg=BG2, fg=WARN)
        self._rng_warn.pack(side="left", padx=(12,0))
        Tooltip(self._rng_warn,
                "This height is outside VRChat's officially supported range (0.1 m – 100 m). "
                "You may encounter visual or IK issues. "
                "Do not report bugs encountered at this scale.", wrap=320)

        # Slider
        self._slider = LogSlider(LEFT, LOG_MIN, LOG_MAX, self._lv,
                                 command=self._sl_move, height=56)
        self._slider.pack(fill="x", pady=(0, 4))

        # Entry row
        er = tk.Frame(LEFT, bg=BG); er.pack(fill="x", pady=4)
        tk.Label(er, text="Set (m):", font=FB, bg=BG, fg=TEXT).pack(side="left")
        self._ev = tk.StringVar(value=f"{self._h:.3f}")
        self._ew = tk.Entry(er, textvariable=self._ev, width=9,
                            font=FM, bg=BG3, fg=AHL, insertbackground=AHL,
                            relief="flat", bd=0,
                            highlightbackground=A, highlightthickness=1)
        self._ew.pack(side="left", padx=8)
        Tooltip(self._ew, "Type an exact eye height in metres and press Enter. "
                          "Values outside 0.1 – 100 m are possible but unsupported.")
        for ev in ("<Return>","<KP_Enter>","<FocusOut>"): self._ew.bind(ev, self._entry_submit)

        def _btn(p, t, cmd, bg=A, fg=TEXT, abg=None, afg=TEXT, tip=""):
            b = tk.Button(p, text=t, command=cmd,
                          font=FB, bg=bg, fg=fg,
                          activebackground=abg or BG4, activeforeground=afg,
                          relief="flat", padx=9, pady=3, cursor="hand2")
            b.pack(side="left", padx=2)
            if tip: Tooltip(b, tip)
            return b

        _btn(er, "Send ▶",        self._entry_submit,   bg=A,   abg=A2,
             tip="Send the typed height to VRChat via OSC.")
        _btn(er, "↺ Default",     self._apply_default,  bg=BG3, fg=DIM,
             tip="Reset to your configured default height and send it to VRChat.")
        _btn(er, "★ Set Default", self._make_default,   bg=BG3, fg=A2,  afg=AHL,
             tip="Save the current height as your default. "
                 "It will be used by '↺ Default' and on avatar/world change if configured.")

        # Percentage buttons
        pr = tk.Frame(LEFT, bg=BG); pr.pack(fill="x", pady=2)
        tk.Label(pr, text="Adjust:", font=FB, bg=BG, fg=DIM).pack(side="left", padx=(0,4))
        for lbl, pct in [("−50%",-0.50),("−10%",-0.10),("−1%",-0.01),
                          ("+1%", 0.01),("+10%", 0.10),("+50%", 0.50)]:
            c = WARN if pct < 0 else OK
            b = tk.Button(pr, text=lbl,
                          command=lambda p=pct: self._set(self._h*(1+p)),
                          font=FB, bg=BG3, fg=c,
                          activebackground=BG4, activeforeground=c,
                          relief="flat", padx=7, pady=3, cursor="hand2")
            b.pack(side="left", padx=2)
            Tooltip(b, f"Multiply current height by {1+pct:.2f}×.")

        # ════ RIGHT PANEL ════════════════════════════════════════════════

        # Container for built-in presets — pack/pack_forget this single frame
        # to cleanly hide/show everything when custom presets are in use.
        self._builtin_preset_container = tk.Frame(RIGHT, bg=BG)
        self._builtin_preset_container.pack(fill="x")

        tk.Label(self._builtin_preset_container, text="Presets",
                 font=FH, bg=BG, fg=TEXT).pack(anchor="w")
        self._builtin_preset_frame = tk.Frame(self._builtin_preset_container, bg=BG)
        self._builtin_preset_frame.pack(fill="x", pady=4)
        for i, (label, h) in enumerate(PRESETS):
            b = tk.Button(self._builtin_preset_frame, text=label,
                          command=lambda h=h: self._set(h),
                          font=("Segoe UI", 9), bg=BG3, fg=TEXT,
                          activebackground=A, activeforeground=TEXT,
                          relief="flat", padx=6, pady=5, width=9, cursor="hand2")
            b.grid(row=i//4, column=i%4, padx=2, pady=2, sticky="ew")
            Tooltip(b, f"Set eye height to {h:.2f} m  ({_imp(h)}).")
        for c in range(4): self._builtin_preset_frame.columnconfigure(c, weight=1)
        tk.Frame(self._builtin_preset_container, bg=A2, height=1).pack(fill="x", pady=(10, 6))

        # ── Custom presets ────────────────────────────────────────────────
        self._cust_section = tk.Frame(RIGHT, bg=BG)
        self._cust_section.pack(fill="x")
        cust_hdr = tk.Frame(self._cust_section, bg=BG); cust_hdr.pack(fill="x")
        tk.Label(cust_hdr, text="Custom Presets", font=FH, bg=BG, fg=TEXT).pack(side="left")
        add_btn = tk.Button(cust_hdr, text="＋",
                            command=self._add_custom_preset,
                            font=("Segoe UI", 11, "bold"),
                            bg=BG3, fg=OK,
                            activebackground=BG4, activeforeground=OK,
                            relief="flat", padx=6, pady=0, cursor="hand2")
        add_btn.pack(side="right")
        Tooltip(add_btn, "Add a new custom preset with a name and height of your choice.")

        # Container that _rebuild_custom_presets will repopulate
        self._custom_frame = tk.Frame(self._cust_section, bg=BG)
        self._custom_frame.pack(fill="x", pady=4)
        self._rebuild_custom_presets()

        tk.Frame(RIGHT, bg=A2, height=1).pack(fill="x", pady=(10,6))
        tk.Label(RIGHT, text="World / Udon Limits", font=FH, bg=BG, fg=TEXT).pack(anchor="w")

        lf = tk.Frame(RIGHT, bg=BG2)
        lf.pack(fill="x", pady=4)
        lf.configure(highlightbackground=BG3, highlightthickness=1)
        li = tk.Frame(lf, bg=BG2)
        li.pack(padx=12, pady=8, fill="x")

        ar = tk.Frame(li, bg=BG2); ar.pack(fill="x")
        tk.Label(ar, text="Scaling:", font=FB, bg=BG2, fg=DIM).pack(side="left")
        self._al_dot = tk.Label(ar, text="●", font=FB, bg=BG2, fg=OK)
        self._al_dot.pack(side="left", padx=4)
        self._al_txt = tk.Label(ar, text="Allowed", font=FB, bg=BG2, fg=OK)
        self._al_txt.pack(side="left")
        Tooltip(self._al_dot,
                "Green = VRChat and this world allow scaling.\n"
                "Red = The current world has disabled avatar scaling via Udon.")

        mr2 = tk.Frame(li, bg=BG2); mr2.pack(fill="x", pady=(6,0))
        tk.Label(mr2, text="Min:", font=FB, bg=BG2, fg=DIM).pack(side="left")
        self._min_lbl = tk.Label(mr2, text="Not set", font=FB, bg=BG2, fg=DIM)
        self._min_lbl.pack(side="left", padx=4)
        tk.Label(mr2, text="  Max:", font=FB, bg=BG2, fg=DIM).pack(side="left")
        self._max_lbl = tk.Label(mr2, text="Not set", font=FB, bg=BG2, fg=DIM)
        self._max_lbl.pack(side="left", padx=4)

        note_row = tk.Frame(li, bg=BG2); note_row.pack(fill="x", pady=(4,0))
        self._lim_note = tk.Label(note_row,
            text="No world-defined limits in this world.",
            font=FS, bg=BG2, fg=DIM)
        self._lim_note.pack(anchor="w")
        Tooltip(self._lim_note,
                "When a world author sets height limits via Udon, red markers "
                "appear on the slider showing the allowed range. "
                "If scaling is fully locked, the slider is greyed out and disabled.")

        # ── Status bar ─────────────────────────────────────────────────────
        sb = tk.Frame(self.root, bg=BG3)
        sb.pack(fill="x")
        self._cdot = tk.Label(sb, text="●", font=FS, bg=BG3, fg=DIM)
        self._cdot.pack(side="left", padx=(10,2), pady=5)
        self._svar = tk.StringVar(value="Initializing…")
        tk.Label(sb, textvariable=self._svar, font=FS, bg=BG3, fg=DIM).pack(side="left")

        self._plbl = tk.Label(sb, text="", font=FS, bg=BG3, fg=DIM)
        self._plbl.pack(side="right", padx=4)
        self._plbl.config(text=f"→:{self.cfg['send_port']}  ←:{self.cfg['recv_port']}")

        # OSC info button (far right)
        osc_info = tk.Label(sb, text="ℹ OSC", font=FS, bg=BG3, fg=A2, cursor="hand2")
        osc_info.pack(side="right", padx=(0, 6), pady=5)
        Tooltip(osc_info,
                "OSC (Open Sound Control) is the protocol VRChat uses to communicate\n"
                "with external tools. This application sends your chosen eye height to\n"
                "VRChat over UDP on the local network.\n\n"
                "To enable it in VRChat: Action Menu → Options → OSC → Enabled.\n\n"
                "💡 Tip: most buttons and settings in this application have helpful\n"
                "descriptions — hover your cursor over them to read more.",
                wrap=320)

        self._refresh_default_badge()

    # ── Input handlers ────────────────────────────────────────────────────────
    def _start_inputs(self):
        self._kb_input.start(self.cfg)

    # ── OSCQuery callbacks ────────────────────────────────────────────────────
    def _on_vrc_oscquery_found(self, ip: str, port: int):
        """Called (on main thread) when VRChat is discovered via OSCQuery."""
        self._osc = udp_client.SimpleUDPClient(ip, port)
        self._update_port_label()
        self._status(
            f"OSCQuery: discovered VRChat at {ip}:{port} — sending there now",
            True)

    def _update_port_label(self):
        recv = self._oscq.recv_port or self.cfg["recv_port"]
        if self._oscq.recv_port:
            self._plbl.config(
                text=f"OSCQuery  ←:{recv}",
                fg=A2)
        else:
            self._plbl.config(
                text=f"→:{self.cfg['send_port']}  ←:{self.cfg['recv_port']}",
                fg=DIM)

    def _start_overlay(self):
        self._overlay = HeightOverlay(self.root, self.cfg)
        self._update_overlay_btn()

    # ── Update check ──────────────────────────────────────────────────────────

    def _start_update_check(self):
        threading.Thread(target=self._run_update_check, daemon=True).start()

    def _run_update_check(self):
        tag = _fetch_latest_version()
        if not tag:
            return
        # Normalise — strip leading 'v' for comparison
        latest = tag.lstrip("v").strip()
        current = APP_VERSION.lstrip("v").strip()
        if latest != current:
            try:
                from packaging.version import Version
                is_newer = Version(latest) > Version(current)
            except Exception:
                # packaging not available — simple string compare
                is_newer = latest != current
            if is_newer:
                self.root.after(0, lambda: self._show_update_banner(tag))

    def _show_update_banner(self, tag: str):
        self._update_lbl.config(
            text=f"🔔  Version {tag} is available — click here to download")
        self._update_bar.pack(fill="x", before=self._vrc_frame)

    def _dismiss_update_bar(self):
        self._update_bar.pack_forget()

    def _open_releases(self):
        import webbrowser
        webbrowser.open(_RELEASES_PAGE)

    def _toggle_overlay(self):
        if self._overlay:
            self._overlay.toggle()
            self._update_overlay_btn()
            _save(self.cfg)

    def _update_overlay_btn(self):
        if self._overlay and self._overlay.enabled:
            self._overlay_btn.config(fg=AHL)
        else:
            self._overlay_btn.config(fg=DIM)

    # ── Settings ──────────────────────────────────────────────────────────────
    def _open_settings(self):
        def on_save():
            self._osc = udp_client.SimpleUDPClient(self.cfg["vrc_ip"], self.cfg["send_port"])
            self._oscq.restart(self.cfg, self.cfg["recv_port"])
            self._update_port_label()
            self._refresh_badges()
            self._kb_input.restart(self.cfg)
        Settings(self.root, self.cfg, on_save, lambda: self._h)

    # ── Tray ──────────────────────────────────────────────────────────────────
    def _tray_setup(self):
        menu = pystray.Menu(
            pystray.MenuItem("VRChat Avatar Scaler", None, enabled=False),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Show / Hide", self._tray_toggle, default=True),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Apply Default Height",
                             lambda *_: self.root.after(0, self._apply_default)),
            pystray.MenuItem("Toggle Overlay",
                             lambda *_: self.root.after(0, self._toggle_overlay)),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Quit", lambda *_: self.root.after(0, self._quit)),
        )
        self.tray = pystray.Icon("VRChat Avatar Scaler",
                                 _make_icon(64),
                                 "VRChat Avatar Scaler",
                                 menu)
        threading.Thread(target=self.tray.run, daemon=True).start()

    def _tray_toggle(self, *_):
        self.root.after(0, lambda: (
            self._hide() if self.root.winfo_viewable() else self._show_window()))

    def _hide(self):
        self.root.withdraw()

    def _on_close_button(self):
        """Handles the window × button — hides to tray or quits based on settings."""
        if self.cfg.get("close_to_tray", True) and not sys.platform.startswith("linux"):
            self._hide()
        else:
            self._quit()

    def _show_window(self):
        self.root.deiconify()
        self.root.lift()
        self.root.focus_force()

    # ── Lifecycle ─────────────────────────────────────────────────────────────
    def _quit(self):
        self.cfg["last_height"] = self._h
        _save(self.cfg)
        self._kb_input.stop()
        self._oscq.stop()
        if self._overlay:
            self._overlay.destroy()
        try: self.tray.stop()
        except Exception: pass
        self.root.destroy()

    # ── VRChat process monitor ────────────────────────────────────────────────
    def _vrc_monitor_start(self):
        threading.Thread(target=self._vrc_loop, daemon=True).start()

    def _vrc_loop(self):
        while True:
            on = any(
                "vrchat" in (p.info.get("name") or "").lower()
                for p in psutil.process_iter(["name"])
                if not _safe_proc_err(p)
            )
            if on != self._vrc_on:
                self._vrc_on = on
                self.root.after(0, self._vrc_changed, on)
            time.sleep(3)

    def _vrc_changed(self, on: bool):
        if on:
            self._vrc_dot.config(fg=OK)
            self._vrc_txt.config(text="Running", fg=OK)
            self._status("VRChat detected — OSC ready", True)
            if self.cfg.get("auto_launch_with_vrchat"):
                self._show_window()
            # Re-advertise via OSCQuery so VRChat picks up the scaler at its startup
            if _OSCQ and self.cfg.get("oscquery_enabled", True):
                self._oscq.restart(self.cfg, self.cfg["recv_port"])
        else:
            self._vrc_dot.config(fg=ERR)
            self._vrc_txt.config(text="Not running", fg=ERR)
            self._status("VRChat not running — standing by", False)
            # Clear any world-specific state that VRChat can no longer update
            self._udon_min = None
            self._udon_max = None
            self._locked   = False
            self._update_limits()
            self._update_allowed(True)
            if self.cfg.get("auto_close_with_vrchat"):
                self.root.after(1500, self._quit)

    # ── OSC listener ──────────────────────────────────────────────────────────
    def _osc_listen(self):
        d = dispatcher.Dispatcher()
        d.map(OSC_HEIGHT,  self._oh_height)
        d.map(OSC_MIN,     self._oh_min)
        d.map(OSC_MAX,     self._oh_max)
        d.map(OSC_ALLOWED, self._oh_allowed)
        d.map(OSC_CHANGE,  self._oh_change)
        d.set_default_handler(lambda *_: None)

        # Use the dynamic port assigned by OSCQueryManager if available,
        # otherwise fall back to the configured fixed port.
        port = self._oscq.recv_port or self.cfg["recv_port"]

        try:
            srv = osc_server.ThreadingOSCUDPServer(("0.0.0.0", port), d)
            self._svr_on = True
            threading.Thread(target=srv.serve_forever, daemon=True).start()
            self._update_port_label()
            if not (self._oscq.recv_port):
                # OSCQuery not active — show the manual-enable reminder
                self._status(
                    f"Listening on :{port} — enable OSC in VRChat ▸ Action Menu ▸ OSC",
                    True)
        except OSError as e:
            self._status(f"Port {port} in use — receive disabled ({e})", False)

    def _oh_height(self, _, *args):
        if args:
            h = _clamp(float(args[0]), ABS_MIN, ABS_MAX)
            self.root.after(0, lambda: self._refresh_display(h, from_vrc=True))

    # VRChat always broadcasts these defaults even when no world has set limits.
    # Treat them as "not set" so no markers are drawn.
    _VRC_DEFAULT_MIN = 0.2
    _VRC_DEFAULT_MAX = 5.0

    def _oh_min(self, _, *args):
        if args:
            v = float(args[0])
            if abs(v - self._VRC_DEFAULT_MIN) < 1e-4:
                return   # VRChat default — not a world-defined restriction
            self._udon_min = v
            self.root.after(0, lambda: self._update_limits())

    def _oh_max(self, _, *args):
        if args:
            v = float(args[0])
            if abs(v - self._VRC_DEFAULT_MAX) < 1e-4:
                return   # VRChat default — not a world-defined restriction
            self._udon_max = v
            self.root.after(0, lambda: self._update_limits())

    def _oh_allowed(self, _, *args):
        if args:
            allowed = bool(args[0])
            self.root.after(0, lambda: self._update_allowed(allowed))

    def _oh_change(self, _, *args):
        """Avatar or world changed — clear any stale world limits, then re-apply height."""
        # Reset world-specific state so stale limits from the previous world don't persist
        self._udon_min  = None
        self._udon_max  = None
        self._locked    = False
        self.root.after(0, lambda: self._update_limits())
        self.root.after(0, lambda: self._update_allowed(True))

        if self.cfg.get("retain_on_change"):
            h = self._h
            self._status(f"Avatar/world change — re-applying {h:.3f} m…", True)
            self._send(h)
        elif self.cfg.get("apply_default_on_change"):
            dh = self.cfg["default_height"]
            self._status(f"Avatar/world change — applying default {dh:.3f} m…", True)
            self.root.after(0, lambda: self._set(dh))

    # ── World limits ──────────────────────────────────────────────────────────
    def _update_limits(self):
        lo, hi = self._udon_min, self._udon_max
        has = lo is not None or hi is not None
        if lo is not None:
            self._min_lbl.config(text=f"{lo:.3f} m  ({_imp(lo)})", fg=LIM)
        else:
            self._min_lbl.config(text="Not set", fg=DIM)
        if hi is not None:
            self._max_lbl.config(text=f"{hi:.3f} m  ({_imp(hi)})", fg=LIM)
        else:
            self._max_lbl.config(text="Not set", fg=DIM)
        self._slider.set_limits(lo, hi)
        if has:
            self._lim_note.config(
                text="⬤  World-defined limits active — red markers shown on slider.",
                fg=LIM)
        else:
            self._lim_note.config(
                text="No world-defined limits in this world.", fg=DIM)

    def _update_allowed(self, allowed: bool):
        self._locked = not allowed
        self._slider.set_locked(self._locked)
        if allowed:
            self._al_dot.config(fg=OK)
            self._al_txt.config(text="Allowed", fg=OK)
        else:
            self._al_dot.config(fg=ERR)
            self._al_txt.config(text="Locked — world has disabled scaling", fg=ERR)

    # ── Display ───────────────────────────────────────────────────────────────
    def _refresh_display(self, h: float, from_vrc: bool = False):
        self._supp = True
        h = _clamp(h, ABS_MIN, ABS_MAX)
        self._h = h
        self.cfg["last_height"] = h

        out = h < SAFE_MIN or h > SAFE_MAX
        self._m_lbl.config(text=f"{h:.3f}", fg=WARN if out else AHL)
        self._imp_lbl.config(text=_imp(h))
        self._ev.set(f"{h:.3f}")
        lv = _clamp(math.log10(max(h, 10**LOG_MIN)), LOG_MIN, LOG_MAX)
        self._lv.set(lv)
        self._rng_warn.config(text="⚠ Outside supported range" if out else "")

        if from_vrc:
            self._status(f"VRChat echoed: {h:.3f} m  ({_imp(h)})", True)

        if self._overlay:
            self._overlay.update_height(h)

        self._supp = False

    def _refresh_badges(self):
        self._refresh_default_badge()
        if self.cfg.get("retain_on_change"):
            self._ret_badge.config(text="↩ Retain height: ON", fg=A2)
        elif self.cfg.get("apply_default_on_change"):
            self._ret_badge.config(text="↩ Apply default: ON", fg=WARN)
        else:
            self._ret_badge.config(text="", fg=DIM)

    def _refresh_default_badge(self):
        self._def_badge.config(text=f"Default: {self.cfg['default_height']:.3f} m")

    def _status(self, msg: str, ok: bool = True):
        self._svar.set(msg)
        self._cdot.config(fg=OK if ok else ERR)

    # ── Controls ──────────────────────────────────────────────────────────────
    def _sl_move(self, lv):
        if self._supp: return
        h = _clamp(round(10**float(lv), 4), ABS_MIN, ABS_MAX)
        self._range_check(h)
        self._refresh_display(h)
        self._send(h)

    def _entry_submit(self, _=None):
        try: v = float(self._ev.get().replace(",", "."))
        except ValueError:
            self._ev.set(f"{self._h:.3f}"); return
        self._set(v)

    def _set(self, h: float):
        h = _clamp(h, ABS_MIN, ABS_MAX)
        self._range_check(h)
        self._refresh_display(h)
        self._send(h)

    def _apply_default(self): self._set(self.cfg["default_height"])

    # ── Custom presets ────────────────────────────────────────────────────────

    def _rebuild_custom_presets(self):
        """Clear and redraw the custom presets grid from cfg['custom_presets'].
        Hides built-in presets while any custom presets exist."""
        for w in self._custom_frame.winfo_children():
            w.destroy()

        presets: list[dict] = self.cfg.get("custom_presets", [])

        # Toggle the entire built-in container — single pack/pack_forget, no ordering issues
        if presets:
            self._builtin_preset_container.pack_forget()
        else:
            self._builtin_preset_container.pack(fill="x", before=self._cust_section)

        if not presets:
            tk.Label(self._custom_frame,
                     text="No custom presets yet.\nClick ＋ to add one.",
                     font=FS, bg=BG, fg=DIM, justify="center").pack(pady=6)
            return

        for i, p in enumerate(presets):
            name   = p.get("name", "?")
            height = float(p.get("height", 1.65))
            col, row = i % 4, i // 4

            # Compact two-line label: name on top, height below
            label = f"{name}\n{height:.2f} m"
            b = tk.Button(self._custom_frame,
                          text=label,
                          command=lambda h=height: self._set(h),
                          font=("Segoe UI", 9), bg=BG4, fg=TEXT,
                          activebackground=A, activeforeground=TEXT,
                          relief="flat", padx=4, pady=5, width=9, cursor="hand2")
            b.grid(row=row, column=col, padx=2, pady=2, sticky="ew")

            Tooltip(b, f"{name}\n{height:.3f} m  ({_imp(height)})\n\n"
                       "Left-click to apply.\nRight-click for edit / delete options.")

            # Right-click context menu
            b.bind("<Button-3>",
                   lambda e, idx=i: self._custom_preset_menu(e, idx))

        for c in range(4):
            self._custom_frame.columnconfigure(c, weight=1)

    def _custom_preset_menu(self, event, index: int):
        menu = tk.Menu(self.root, tearoff=0,
                       bg=BG3, fg=TEXT, activebackground=A,
                       activeforeground=TEXT, relief="flat",
                       font=FB, bd=0)
        menu.add_command(label="✏  Edit",
                         command=lambda: self._edit_custom_preset(index))
        menu.add_separator()
        menu.add_command(label="🗑  Delete",
                         command=lambda: self._delete_custom_preset(index),
                         foreground=ERR, activeforeground=ERR)
        menu.tk_popup(event.x_root, event.y_root)

    def _add_custom_preset(self):
        def on_save(name: str, height: float):
            self.cfg.setdefault("custom_presets", []).append(
                {"name": name, "height": height})
            _save(self.cfg)
            self._rebuild_custom_presets()
        PresetEditorDialog(self.root, on_save,
                           initial_height=self._h)

    def _edit_custom_preset(self, index: int):
        presets = self.cfg.get("custom_presets", [])
        if index >= len(presets):
            return
        p = presets[index]
        def on_save(name: str, height: float):
            presets[index] = {"name": name, "height": height}
            _save(self.cfg)
            self._rebuild_custom_presets()
        PresetEditorDialog(self.root, on_save,
                           initial_name=p.get("name", ""),
                           initial_height=float(p.get("height", 1.65)))

    def _delete_custom_preset(self, index: int):
        presets = self.cfg.get("custom_presets", [])
        if index >= len(presets):
            return
        name = presets[index].get("name", "this preset")
        if tk.messagebox.askyesno(
                "Delete Preset",
                f"Delete \"{name}\"?",
                parent=self.root):
            presets.pop(index)
            _save(self.cfg)
            self._rebuild_custom_presets()

    def _show_quick_input(self):
        """Open the floating quick-input dialog (guard against stacking)."""
        # If already open, just bring it to the front
        if self._quick_input is not None:
            try:
                self._quick_input.win.lift()
                self._quick_input.win.focus_force()
                return
            except Exception:
                self._quick_input = None

        def on_apply(val: float):
            self._quick_input = None
            self._set(val)

        self._quick_input = QuickInputDialog(
            self.root, self._h, on_apply)
        # Clear reference when dialog is closed by any means
        self._quick_input.win.bind(
            "<Destroy>",
            lambda _: setattr(self, "_quick_input", None))

    def _make_default(self):
        self.cfg["default_height"] = self._h
        _save(self.cfg)
        self._refresh_default_badge()
        self._status(f"Default saved: {self._h:.3f} m  ({_imp(self._h)})", True)

    def _send(self, h: float):
        try:
            self._osc.send_message(OSC_HEIGHT, float(h))
            self._status(
                f"Sent {h:.3f} m  ({_imp(h)})  →  VRChat :{self.cfg['send_port']}", True)
        except Exception as e:
            self._status(f"Send error: {e}", False)

    def _range_check(self, h: float):
        out = h < SAFE_MIN or h > SAFE_MAX
        if out and not self._warned and not self.cfg.get("suppress_range_warning"):
            self._warned = True
            self.root.after(50, lambda: RangeWarning(
                self.root,
                lambda sup: (
                    self.cfg.update({"suppress_range_warning": sup}),
                    _save(self.cfg)
                )
            ))


# ─── Utility ──────────────────────────────────────────────────────────────────
def _safe_proc_err(p) -> bool:
    try: p.info  # access may raise
    except (psutil.NoSuchProcess, psutil.AccessDenied): return True
    return False


# ─── Entry point ──────────────────────────────────────────────────────────────
def main():
    root = tk.Tk()
    app  = ScalerApp(root)

    root.update_idletasks()
    w, h   = root.winfo_width(), root.winfo_height()
    sw, sh = root.winfo_screenwidth(), root.winfo_screenheight()
    root.geometry(f"+{(sw-w)//2}+{(sh-h)//2}")

    root.mainloop()
    _save(app.cfg)


if __name__ == "__main__":
    main()
