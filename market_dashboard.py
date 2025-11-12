#!/usr/bin/env python3
"""
Market dashboard (Pi 5 + 7" screen) + Windows compatible

Behavior:
- Runs/updates only on market days (Mon–Fri, excluding US market holidays) during 8:30–15:00 CT
- After close / weekends / holidays: KEEP the last session visible (no fetches)
- At the next market day 8:30 AM CT: CLEAR and start a fresh session
- Three stacked charts (SPY, DIA, QQQ) with their own y-scales, shared x (8:30–15:00 CT)
- Header boxes with price + change (mid-tone background for visibility)
- White dashed line at previous close (yesterday 3:00 PM CT)
- Daily CSV persistence to ~/market/data/YYYY-MM-DD/prices.csv
"""

# ---------- 1) Imports & Global Configuration ----------
import os, csv, time, threading, logging
from datetime import datetime, date, timedelta, time as dtime
try:
    # Python 3.9+; on Windows also `pip install tzdata`
    from zoneinfo import ZoneInfo
except ModuleNotFoundError:
    raise SystemExit("Install Python 3.9+ or add tzdata: pip install tzdata")

import tkinter as tk
import requests

# Matplotlib (no toolbar); we embed it into Tkinter
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg

# --- API key from environment (never hard-code) ---
API_KEY = os.environ.get("FINNHUB_API_KEY")
if not API_KEY:
    raise SystemExit("Missing FINNHUB_API_KEY environment variable")

# --- Tickers & refresh cadence ---
TICKERS = ["SPY", "DIA", "QQQ"]
REFRESH_SECONDS = 300  # 5 minutes

# --- Time zone & market hours (Central Time) ---
TZ = ZoneInfo("America/Chicago")
MARKET_OPEN_CT  = dtime(8, 30)  # 8:30 AM CT
MARKET_CLOSE_CT = dtime(15, 0)  # 3:00 PM CT

# --- Storage location for daily CSVs ---
DATA_ROOT = os.path.expanduser("~/market/data")

# --- Theme / Colors ---
BG = "#0f1115"       # app background (dark)
FG = "#e6e6e6"       # light foreground text
PANEL = "#1d2233"
GRID = "#333a52"
AX_BG = "#151823"
# Brand-ish base colors
COLORS = {"SPY": "#1f77b4", "DIA": "#ff7f0e", "QQQ": "#2ca02c"}
# Mid-tone header backgrounds for readability
BG_COLORS = {"SPY": "#a6c8e6", "DIA": "#ffbb78", "QQQ": "#98df8a"}
# High-contrast change text
UP = "#1b5e20"      # dark green
DOWN = "#7f1d1d"    # dark red

# ---------- 2) Logging ----------
os.makedirs(DATA_ROOT, exist_ok=True)
LOG_PATH = os.path.expanduser("~/market/market.log")
logging.basicConfig(
    filename=LOG_PATH,
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s"
)

# ---------- 3) Runtime State ----------
# In-memory arrays for today's session; cleared at next market open (8:30 CT)
time_points: list[datetime] = []
prices: dict[str, list[float | None]] = {t: [] for t in TICKERS}
prev_close: dict[str, float | None] = {t: None for t in TICKERS}
current_day = date.today()

# ---------- 4) Storage (CSV) ----------
def today_dir(d: date | None = None) -> str:
    """Directory for today's data, e.g. ~/market/data/2025-08-26/"""
    d = d or date.today()
    p = os.path.join(DATA_ROOT, d.isoformat())
    os.makedirs(p, exist_ok=True)
    return p

def today_csv_path(d: date | None = None) -> str:
    """Path to today's CSV (ts, SPY, DIA, QQQ)."""
    return os.path.join(today_dir(d), "prices.csv")

def load_today() -> None:
    """Load today's CSV (if present) so we resume mid-session after a restart."""
    p = today_csv_path()
    if not os.path.exists(p):
        return
    try:
        with open(p, "r", newline="") as f:
            r = csv.DictReader(f)
            for row in r:
                ts = datetime.fromisoformat(row["ts"]).astimezone(TZ)
                time_points.append(ts)
                for t in TICKERS:
                    v = row.get(t)
                    prices[t].append(float(v) if v not in (None, "", "nan") else None)
        logging.info("Loaded %d prior points for today", len(time_points))
    except Exception as e:
        logging.error("Failed loading today data: %s", e)

def append_today(ts_local: datetime, snapshot: dict[str, float | None]) -> None:
    """Append one row (ISO ts + prices) to today's CSV."""
    p = today_csv_path()
    is_new = not os.path.exists(p)
    with open(p, "a", newline="") as f:
        w = csv.writer(f)
        if is_new:
            w.writerow(["ts"] + TICKERS)
        w.writerow([ts_local.isoformat()] + [
            f"{snapshot.get(t,'')}" if snapshot.get(t) is not None else "" for t in TICKERS
        ])

# ---------- 5) Market Days & Holidays ----------
# Try to use the `holidays` package; else fallback to minimal built-in list (NYSE 2024–2027).
_US_HOLIDAYS = None
try:
    import holidays  # pip install holidays
    _US_HOLIDAYS = holidays.US()  # observed US federal holidays; we add Good Friday below
except Exception:
    _US_HOLIDAYS = None

# Minimal built-in for 2024–2027 (standard NYSE closures incl. Good Friday)
from datetime import date as DateOnly
_BUILTIN_HOLIDAYS = {
    # 2024
    DateOnly(2024,1,1), DateOnly(2024,1,15), DateOnly(2024,2,19), DateOnly(2024,3,29),
    DateOnly(2024,5,27), DateOnly(2024,6,19), DateOnly(2024,7,4),  DateOnly(2024,9,2),
    DateOnly(2024,11,28), DateOnly(2024,12,25),
    # 2025
    DateOnly(2025,1,1),  DateOnly(2025,1,20), DateOnly(2025,2,17), DateOnly(2025,4,18),
    DateOnly(2025,5,26), DateOnly(2025,6,19), DateOnly(2025,7,4),  DateOnly(2025,9,1),
    DateOnly(2025,11,27), DateOnly(2025,12,25),
    # 2026
    DateOnly(2026,1,1),  DateOnly(2026,1,19), DateOnly(2026,2,16), DateOnly(2026,4,3),
    DateOnly(2026,5,25), DateOnly(2026,6,19), DateOnly(2026,7,3),  DateOnly(2026,9,7),
    DateOnly(2026,11,26), DateOnly(2026,12,25),
    # 2027
    DateOnly(2027,1,1),  DateOnly(2027,1,18), DateOnly(2027,2,15), DateOnly(2027,3,26),
    DateOnly(2027,5,31), DateOnly(2027,7,5),  DateOnly(2027,9,6),  DateOnly(2027,11,25),
    DateOnly(2027,12,24),
}

def is_us_holiday(d: date) -> bool:
    """True if `d` is a US market holiday (observed). Adds Good Friday if using holidays lib."""
    if _US_HOLIDAYS is not None:
        if d in _US_HOLIDAYS:
            return True
        # Add Good Friday (two days before Easter Sunday)
        try:
            import holidays.calendars as cal  # internal Easter algorithm
            easter = cal._ChristianHolidays()._easter(d.year)
            good_friday = easter - timedelta(days=2)
            if d == good_friday.date():
                return True
        except Exception:
            pass
        return False
    # Fallback built-in list
    return d in _BUILTIN_HOLIDAYS

def is_market_day(d: date) -> bool:
    """True if Mon–Fri AND not a holiday."""
    if d.weekday() >= 5:  # 5=Sat, 6=Sun
        return False
    if is_us_holiday(d):
        return False
    return True

def next_market_open_after(now_local: datetime) -> datetime:
    """
    Next market-day at 8:30 AM CT strictly after `now_local`.
    Used to sleep until the next time we should wake up and reset/fetch.
    """
    d = now_local.date()
    while True:
        if is_market_day(d):
            open_dt = datetime.combine(d, MARKET_OPEN_CT, tzinfo=TZ)
            if open_dt > now_local:
                return open_dt
        d += timedelta(days=1)

# ---------- 6) Finnhub API ----------
SESSION = requests.Session()
BASE = "https://finnhub.io/api/v1"

def get_quote(symbol: str) -> tuple[float | None, float | None]:
    """Fetch (current price, previous close) or (None, None) on error/rate-limit."""
    try:
        r = SESSION.get(f"{BASE}/quote", params={"symbol": symbol, "token": API_KEY}, timeout=10)
        if r.status_code == 429:
            logging.warning("Rate limited for %s", symbol)
            return None, None
        r.raise_for_status()
        j = r.json()
        return j.get("c"), j.get("pc")
    except Exception as e:
        logging.warning("Quote error %s: %s", symbol, e)
        return None, None

# ---------- 7) Market-Hours Helpers ----------
def is_market_open(now_local: datetime) -> bool:
    """True only when TODAY is a market day and the local time is within 8:30–15:00 CT."""
    return is_market_day(now_local.date()) and (MARKET_OPEN_CT <= now_local.time() <= MARKET_CLOSE_CT)

def today_window(now_local: datetime) -> tuple[datetime, datetime]:
    """Return today's [open, close] datetimes for clamping the x-axis (regardless of holiday)."""
    day = now_local.date()
    open_dt  = datetime.combine(day, MARKET_OPEN_CT, tzinfo=TZ)
    close_dt = datetime.combine(day, MARKET_CLOSE_CT, tzinfo=TZ)
    return open_dt, close_dt

def ms_until(dt: datetime, now_local: datetime) -> int:
    """Milliseconds until `dt` (never less than 1 ms)."""
    return max(1, int((dt - now_local).total_seconds() * 1000))

# ---------- 8) UI (Tkinter window + Matplotlib figure) ----------
class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Market Dashboard")
        self.configure(bg=BG)
        self.geometry("900x600")
        self.resizable(False, False)

        # ----- Header row: three equal-width boxes (grid + uniform columns) -----
        header = tk.Frame(self, bg=BG)
        header.pack(side=tk.TOP, fill=tk.X, padx=10, pady=(10, 6))

        self.boxes = {}
        for i, t in enumerate(TICKERS):
            header.grid_columnconfigure(i, weight=1, uniform="boxes")  # equal widths
            box = tk.Frame(header, bg=BG_COLORS[t], bd=0, relief="flat")
            box.grid(row=0, column=i, sticky="nsew", padx=8)

            name = tk.Label(box, text=t, bg=BG_COLORS[t], fg=COLORS[t],
                            font=("Arial", 13, "bold"))
            name.pack(anchor="w", padx=10, pady=(8, 0))

            price_var = tk.StringVar(value="—")
            price_lbl = tk.Label(box, textvariable=price_var, bg=BG_COLORS[t],
                                 fg=COLORS[t], font=("Arial", 18, "bold"))
            price_lbl.pack(anchor="w", padx=10)

            change_var = tk.StringVar(value="—")
            change_lbl = tk.Label(box, textvariable=change_var, bg=BG_COLORS[t],
                                  fg="#222", font=("Arial", 11, "bold"))
            change_lbl.pack(anchor="w", padx=10, pady=(0, 8))

            self.boxes[t] = (price_var, change_var, change_lbl)

        # Optional status line under the header (e.g., "Market Closed — ...")
        self.status = tk.Label(header, text="", bg=BG, fg=FG, font=("Arial", 10))
        self.status.grid(row=1, column=0, columnspan=len(TICKERS), sticky="w", padx=8, pady=(6, 0))

        # ----- Three stacked subplots (shared x) -----
        self.fig, self.axes = plt.subplots(
            nrows=3, ncols=1, sharex=True, figsize=(9, 5), dpi=100,
            gridspec_kw={"height_ratios": [1, 1, 1]},
            constrained_layout=True
        )
        # Extra breathing room so labels aren't clipped
        self.fig.set_constrained_layout_pads(w_pad=0.06, h_pad=0.06, hspace=0.08, wspace=0.06)
        self.fig.patch.set_facecolor(BG)

        # Cross-platform time ticks (avoids %-I/%#I issues)
        locator = mdates.AutoDateLocator()
        formatter = mdates.ConciseDateFormatter(locator, tz=TZ)

        self.lines = {}
        for ax, t in zip(self.axes, TICKERS):
            ax.set_facecolor(AX_BG)
            ax.grid(True, linestyle="--", alpha=0.35)
            ax.tick_params(colors=FG, labelsize=9)
            for s in ax.spines.values():
                s.set_color(GRID)
            ax.set_ylabel(f"{t} ($)", color=FG, fontsize=11, fontweight="bold",
                          rotation=0, labelpad=34)
            ax.margins(x=0.02)

            ax.xaxis.set_major_locator(locator)
            ax.xaxis.set_major_formatter(formatter)

            # One line per ticker; also track dashed prev-close line handles
            line, = ax.plot([], [], color=COLORS[t], linewidth=2.0, label=t)
            ax._pc_lines = []  # artists for dashed lines to clear/redraw
            self.lines[t] = (ax, line)

        # Clamp x-axis to today's 8:30–15:00 window from the start
        self.open_dt, self.close_dt = today_window(datetime.now(TZ))
        for ax in self.axes:
            ax.set_xlim(self.open_dt, self.close_dt)

        # Embed figure into Tk
        self.canvas = FigureCanvasTkAgg(self.fig, master=self)
        self.canvas.get_tk_widget().configure(bg=BG, highlightthickness=0, bd=0)
        self.canvas.get_tk_widget().pack(side=tk.TOP, fill=tk.BOTH, expand=True,
                                         padx=14, pady=(6, 12))

        # Kick off the loop
        self.after(250, self.refresh_loop)

    # ---------- 9) Refresh Loop ----------
    def refresh_loop(self):
        """Spawn a single update cycle in a thread; schedule the next cycle from there."""
        threading.Thread(target=self._refresh_once, daemon=True).start()

    def _refresh_once(self):
        """One cycle: decide whether to fetch or sleep; update charts/UI accordingly."""
        global current_day
        now_local = datetime.now(TZ)

        # New calendar day? If it's a market day and we're at/after open, reset.
        if date.today() != current_day and is_market_day(now_local.date()) and now_local.time() >= MARKET_OPEN_CT:
            current_day = date.today()
            time_points.clear()
            for t in TICKERS:
                prices[t].clear()
            # Recompute today's x-window and apply
            self.open_dt, self.close_dt = today_window(now_local)
            for ax in self.axes:
                ax.set_xlim(self.open_dt, self.close_dt)
            logging.info("New trading session started at 8:30 AM CT — cleared previous day.")

        # If NOT a market day (weekend/holiday) → hold last screen; wake at next market open
        if not is_market_day(now_local.date()):
            nxt = next_market_open_after(now_local)
            self.status.config(text="Market Closed (Holiday/Weekend) — holding last session")
            self.after(ms_until(nxt, now_local), self.refresh_loop)
            return

        # If outside 8:30–15:00 CT today → hold last screen; wake at next market open
        if not (MARKET_OPEN_CT <= now_local.time() <= MARKET_CLOSE_CT):
            nxt = next_market_open_after(now_local)
            self.status.config(text="Market Closed — charts reset next market day 8:30 AM CT")
            self.after(ms_until(nxt, now_local), self.refresh_loop)
            return
        else:
            self.status.config(text="")

        # ---- Market is OPEN: fetch and render ----
        snapshot: dict[str, float | None] = {}
        for t in TICKERS:
            cur, pc = get_quote(t)
            if pc is not None:
                prev_close[t] = pc  # yesterday's 3:00 PM CT close until today's is set
            snapshot[t] = float(cur) if cur is not None else None
            time.sleep(0.20)  # tiny spacing to be nice to API

        # Store in-memory + append to today's CSV
        time_points.append(now_local)
        for t in TICKERS:
            prices[t].append(snapshot.get(t))
        append_today(now_local, snapshot)

        # Update header UI & charts, then schedule next refresh
        self._apply_header(snapshot)
        self._redraw_chart()
        self.after(REFRESH_SECONDS * 1000, self.refresh_loop)

    # ---------- 10) Header Update ----------
    def _apply_header(self, snapshot: dict[str, float | None]) -> None:
        """Update price + change text/colors for the header boxes."""
        for t in TICKERS:
            price_var, change_var, change_lbl = self.boxes[t]
            cur = snapshot.get(t)
            pc = prev_close.get(t)

            # Price text
            price_var.set(f"{cur:,.2f}" if cur is not None else "—")

            # Change text (+/- diff and %), colored for contrast
            if cur is None or pc is None:
                change_var.set("—")
                change_lbl.configure(fg="#222")
            else:
                diff = cur - pc
                pct = (diff / pc) * 100 if pc else 0.0
                sign = "+" if diff >= 0 else ""
                change_var.set(f"{sign}{diff:.2f} ({sign}{pct:.2f}%)")
                change_lbl.configure(fg=UP if diff >= 0 else DOWN)

    # ---------- 11) Redraw Charts ----------
    def _redraw_chart(self) -> None:
        """Set line data, enforce x-limits, draw dashed prev-close line, pad y-limits, redraw."""
        for t in TICKERS:
            ax, line = self.lines[t]

            # Data for this ticker
            y = [v for v in prices[t] if v is not None]
            x = time_points[:len(y)]

            # Update main line + keep x clamped to 8:30–15:00
            line.set_data(x, y)
            ax.set_xlim(self.open_dt, self.close_dt)

            # Remove any prior dashed lines (avoid stacking)
            for artist in list(ax._pc_lines):
                try:
                    artist.remove()
                except:
                    pass
            ax._pc_lines.clear()

            # Draw dashed previous-close reference line (yesterday's 3:00 PM CT close)
            pc = prev_close.get(t)
            if pc is not None:
                ref = ax.axhline(pc, linestyle="--", linewidth=1.0, color="white", alpha=0.75)
                ax._pc_lines.append(ref)

            # Y-limits: include today's data and the prev-close line, add a bit of padding
            if y:
                ymin, ymax = min(y), max(y)
                if pc is not None:
                    ymin, ymax = min(ymin, pc), max(ymax, pc)
                if ymin == ymax:
                    pad = max(0.5, 0.005 * (ymin if ymin else 1))
                else:
                    pad = 0.02 * (ymax - ymin)
                ax.set_ylim(ymin - pad, ymax + pad)
            elif pc is not None:
                ax.set_ylim(pc * 0.995, pc * 1.005)

        self.canvas.draw_idle()

# ---------- 12) Entrypoint ----------
def main():
    """Load today's CSV (if any), create the app, run fullscreen (Esc exits)."""
    load_today()
    app = App()
    app.attributes("-fullscreen", True)            # kiosk-style fullscreen
    app.bind("<Escape>", lambda e: app.attributes("-fullscreen", False))  # exit fullscreen with Esc
    app.mainloop()

if __name__ == "__main__":
    main()
