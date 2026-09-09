# NMZHelper

A Windows Python prototype for a programmable auto clicker.

## Run

```powershell
python -m pip install -r requirements.txt
python autoclicker.py
```

Set the minimum and maximum click interval in milliseconds, then click
**Start** to begin left-clicking at the current mouse position. Each click uses
a new random interval between those two values. If the selected delay before
the next click is greater than 5 seconds, the app shows a countdown. The button
toggles to **Stop** while clicking is active. Press **|**, **\\**, or **F6** to
stop clicking even when another window is focused.

The clicker uses `pynput` for mouse clicks and the global stop hotkey.
