# MarketDashboard
Raspberry Pi Market Dashboard — Installation Instructions
====================================================

This guide explains how to install and run the Market Dashboard on a Raspberry Pi 5 (with the 7" display) or on Windows.

------------------------------------------------------------
2) Create a project folder and virtual environment
------------------------------------------------------------

mkdir -p ~/market
cd ~/market
python3 -m venv .venv
source .venv/bin/activate

------------------------------------------------------------
3) Install Python dependencies
------------------------------------------------------------

pip install matplotlib requests holidays

> Note: The 'holidays' package is optional but recommended for accurate US market holidays.
> If you run on Windows, also do: pip install tzdata

------------------------------------------------------------
4) Get a free Finnhub API key
------------------------------------------------------------

1. Create a free account at https://finnhub.io
2. Copy your API key.
3. On the Pi:

echo 'export FINNHUB_API_KEY=YOUR_KEY_HERE' >> ~/.bashrc
source ~/.bashrc

(Or set it just for this session:)

export FINNHUB_API_KEY=YOUR_KEY_HERE

------------------------------------------------------------
5) Put the code in place
------------------------------------------------------------

Save market_dashboard.py into ~/market/

------------------------------------------------------------
6) Run it
------------------------------------------------------------

source ~/market/.venv/bin/activate
python ~/market/market_dashboard.py

Press ESC to exit fullscreen.

------------------------------------------------------------
Windows (Dev/Preview)
------------------------------------------------------------

# In PowerShell
mkdir $HOME\market
cd $HOME\market
py -m venv .venv
.\.venv\Scripts\activate
pip install matplotlib requests tzdata holidays
setx FINNHUB_API_KEY "YOUR_KEY_HERE"
notepad market_dashboard.py  # paste the script
python market_dashboard.py

------------------------------------------------------------
(Optional) Auto-start on Raspberry Pi
------------------------------------------------------------

Launch the dashboard automatically at login:

mkdir -p ~/.config/lxsession/LXDE-pi
nano ~/.config/lxsession/LXDE-pi/autostart

Add this line at the end (adjust path if needed):

@/home/pi/market/.venv/bin/python /home/pi/market/market_dashboard.py

Reboot to test.

------------------------------------------------------------
Configuration
------------------------------------------------------------

- Tickers: Edit TICKERS = ["SPY","DIA","QQQ"]
- Update interval: REFRESH_SECONDS = 300 (5 minutes)
- Colors: tweak COLORS, BG_COLORS, BG, FG, etc.
- Time zone: currently America/Chicago. Change TZ if desired.
  (Market-hours logic still follows 8:30–3:00 CT.)

------------------------------------------------------------
Troubleshooting
------------------------------------------------------------

- Missing FINNHUB_API_KEY:
  export your key in the shell (or add to ~/.bashrc)

- Windows timezone error (ZoneInfoNotFoundError):
  pip install tzdata

- Holidays not recognized:
  pip install holidays (a fallback 2024–2027 list is built in)

- Nothing updates after close:
  This is by design. The dashboard freezes after 3:00 PM CT
  and resumes next market day at 8:30 AM CT.


------------------------------------------------------------
Requirements
------------------------------------------------------------

matplotlib
requests
holidays
tzdata
