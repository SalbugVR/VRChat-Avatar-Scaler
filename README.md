# VRChat Avatar Scaler

A Windows desktop application that lets you control your VRChat avatar's size in real time. Set an exact height, use quick presets, adjust with keyboard shortcuts, and have your scale restored automatically whenever you switch avatars or enter a new world — all without touching the in-game menus.

![Platform](https://img.shields.io/badge/platform-Windows-blue)
![Python](https://img.shields.io/badge/python-3.10%2B-blue)
![License](https://img.shields.io/badge/license-MIT-green)

---

<img width="922" height="512" alt="pythonw_ek3Apdztp5" src="https://github.com/user-attachments/assets/ebb9dc52-e5a4-42f4-b541-6d81fc8782da" />

---

## Disclaimer

This application was made entirely with Claude. I cannot speak entirely to its stability, but I have dogfooded and iterated on it enough that it has been stable for my use.

## What does it do?

VRChat lets external tools change your avatar's size by sending a simple network message (OSC). This app provides a friendly interface for that — a slider, preset buttons, exact value entry, and keyboard shortcuts — so you can dial in your exact height without navigating menus.

It also watches for avatar and world changes and can instantly restore your preferred scale after each one, effectively keeping your preferred height across avatars.

---

## Contents

- [Requirements](#requirements)
- [Installation](#installation)
- [Enabling OSC in VRChat](#enabling-osc-in-vrchat)
- [Features](#features)
- [Keyboard shortcuts](#keyboard-shortcuts)
- [Height overlay](#height-overlay)
- [Settings reference](#settings-reference)
- [Eye height vs. total height](#eye-height-vs-total-height)
- [Files included](#files-included)
- [Troubleshooting](#troubleshooting)
- [OSC technical reference](#osc-technical-reference)
- [To-Do List](#to-do-list)

---

## Requirements

| Requirement | Details |
|---|---|
| Windows 10 or 11 | Required for the system tray and overlay features |
| Python 3.10 or newer | Free download from [python.org](https://www.python.org/downloads/) |
| VRChat (PC version) | OSC must be enabled in-game — see below |

> **Don't have Python?** The installer will detect this and offer to open the Python download page for you.

---

## Installation

### Option A — Quick install (recommended)

This is the easiest way, especially if you are not familiar with the command line.

1. [Download](https://github.com/SalbugVR/VRChat-Avatar-Scaler/releases) and unzip the VRChat Avatar Scaler folder somewhere convenient (e.g. your Documents folder).
2. Double-click **`Install.bat`**.
3. Follow the prompts. The installer will:
   - Check that Python is installed and up to date
   - Install all required packages automatically
   - Create a shortcut on your desktop
4. When it finishes, press **Y** to launch immediately.

That's all. Move on to [Enabling OSC in VRChat](#enabling-osc-in-vrchat).

---

### Option B — Manual install

Use this if the installer fails, or if you prefer to do things yourself.

**Step 1 — Install Python**

Go to [python.org/downloads](https://www.python.org/downloads/) and download the latest Python 3 release.

> ⚠️ **Important:** On the first screen of the Python installer, tick the checkbox that says **"Add Python to PATH"** before clicking Install Now. If you miss this, the app will not be able to find Python.

**Step 2 — Install required packages**

Open **Command Prompt** or **PowerShell** (press `Win + R`, type `cmd`, press Enter) and paste:

```
pip install python-osc pystray Pillow psutil
```

Then for optional keyboard shortcut support (recommended):

```
pip install pynput
```

**Step 3 — Launch the app**

Double-click **`Launch Scaler (Silent).vbs`** to start without a console window appearing.

---

## Enabling OSC in VRChat

OSC is the feature that lets external tools like this one talk to VRChat.

**How to enable OSC**
1. Open the **Action Menu**.
2. Go to **Options → OSC → Enabled**.

---

## Features

### Slider

The main control is a horizontal slider that covers VRChat's full supported range — **0.1 m to 100 m** — using a logarithmic scale. This means small heights (like 0.2 m) are just as easy to fine-tune as large ones (like 50 m). The slider gets more precise as you make the window wider.

**Tick marks** are drawn below the slider at key heights (0.1 m, 0.5 m, 1 m, 2 m, 5 m, 10 m, 50 m, 100 m and more) so you can see at a glance where you are.

If the current world has set height limits via Udon scripting, **red markers** appear on the slider showing the allowed range, and the zones outside those limits are shaded. If the world has fully disabled scaling, the slider fades out and is blocked until you leave.

To go beyond VRChat's supported range, you'll need to manually input your desired height in the text field below the slider or adjust with the (%) buttons. The absolute limits are 0.01 m to 10,000 m.

If you go beyond VRChat's supported range of 0.1 m - 100 m, you'll be met with a caution message.

> ⚠️ Do **NOT** submit bug reports or contact VRChat Support if issues are encountered while operating outside of the supported range.

### Exact value entry

Type any height in metres in the text field and press **Enter** (or click **Send ▶**) to apply it instantly.

### Percentage step buttons

Six buttons let you nudge your scale relative to your current height:

| Button | Effect |
|---|---|
| −50% | Half your current height |
| −10% | Slightly shorter |
| −1% | Fine reduction |
| +1% | Fine increase |
| +10% | Slightly taller |
| +50% | One and a half times current |

### Presets

Eight preset buttons cover the most common sizes:

| Preset | Eye height |
|---|---|
| Tiny | 0.30 m |
| Small | 0.90 m |
| Compact | 1.20 m |
| Short | 1.52 m |
| Average | 1.65 m |
| Tall | 1.80 m |
| Giant | 3.00 m |
| Macro | 10.0 m |

### Default height

Your **default height** is a saved value you can return to at any time.

- **↺ Default** — instantly snaps back to your default height and sends it to VRChat.
- **★ Set Default** — saves whatever height is currently active as your new default.
- You can also type an exact value in Settings, or use the **Use Current Height** button there.

### Avatar and world change handling

Every time you switch avatar, VRChat changes scale to match the avatar's author set scale or last-saved scale. The scaler can respond automatically the moment this happens:

| Mode | What happens |
|---|---|
| **Retain active height** | Your current height is re-sent immediately. You should not notice any change. |
| **Apply default height** | Your configured height is sent instead. Useful for having a "home" size. |
| **Neither selected** | VRChat's default behaviour is left as-is. |

Configure this in **Settings → On Avatar / World Change**.

### Keyboard shortcuts

With the `pynput` package installed, you can adjust your scale from anywhere — even when the scaler window is hidden to the tray — using keyboard shortcuts.

See [Keyboard shortcuts](#keyboard-shortcuts) below for the full list and instructions on changing them.

### Height overlay

A small floating display that shows your current eye height on screen. See [Height overlay](#height-overlay) below.

### VRChat process detection

The scaler watches for the VRChat process in the background. The coloured dot in the top-left of the window shows the current status:

- 🟢 **Running** — VRChat is open and OSC is ready.
- 🔴 **Not running** — VRChat is not detected.

You can configure the scaler to automatically show its window when VRChat launches (**Auto-launch**) and close itself when VRChat exits (**Auto-close**) in Settings.

### System tray

Closing the main window does not exit the scaler — it hides to the system tray in the bottom-right of your taskbar. Right-click the tray icon for a menu:

- **Show / Hide** — toggle the main window (also the default double-click action)
- **Apply Default Height** — send your default height without opening the window
- **Toggle Overlay** — show or hide the height overlay
- **Quit** — exit the application completely

### Run on Windows startup

In **Settings → Lifecycle**, tick **Run on Windows startup** to have the scaler launch automatically when you log in. Pair this with **Start minimized to tray** and the scaler will sit silently in the background until you need it.

---

## Keyboard shortcuts

Requires the `pynput` package (installed automatically by `Install.bat`).

### Default bindings

| Action | Shortcut |
|---|---|
| Scale up +1% | `Ctrl + Alt + ↑` |
| Scale down −1% | `Ctrl + Alt + ↓` |
| Scale up +10% | `Ctrl + Alt + Shift + ↑` |
| Scale down −10% | `Ctrl + Alt + Shift + ↓` |
| Apply default height | `Ctrl + Alt + Home` |

**Holding** a scale shortcut scales continuously — it fires immediately, pauses briefly, then repeats rapidly until you let go. This lets you make both fine adjustments and large sweeping changes with the same key.

### Changing bindings

1. Open **⚙ Settings → Controls**.
2. Click **Change** next to the action you want to rebind.
3. The button changes to show **Press keys…** — hold your desired modifier keys (Ctrl, Alt, Shift) and then press the trigger key.
4. The label updates immediately to show the new binding.
5. Click **Reset** next to any action to restore its factory default.
6. Click **Save Settings** to apply.

---

## Height overlay

The overlay is a small always-on-top display that shows your current eye height in metres and feet/inches. It is designed to be glanceable while you are in VRChat without getting in the way.

### Turning it on

Click **📏 Overlay** in the top-right of the main window, or right-click the tray icon and choose **Toggle Overlay**. The button turns bright when the overlay is active. Click or toggle again to turn it off.

### Behaviour

The overlay **only appears when VRChat is the active (focused) window**. It hides automatically when you switch to anything else — a browser, Discord, your desktop, etc. — and reappears when you bring VRChat back to the front.

### Moving it

Click and drag anywhere on the overlay to move it. Its position is saved automatically and remembered between sessions. By default it appears in the top-right corner of your screen.

### Closing it

Click the small **✕** in the corner of the overlay, use the **📏 Overlay** button in the main window, or use the tray menu.

---

## Settings reference

Open Settings with the **⚙ Settings** button in the top-right corner of the main window. Hover over any label or checkbox to read a description of what it does.

### Default Height

| Setting | Description |
|---|---|
| Default height value | The eye height (in metres) used by **↺ Default** and on automatic re-apply. |
| Use Current Height | Captures whatever height is active right now as the new default. |

### On Avatar / World Change

| Setting | Description |
|---|---|
| Retain active height | Re-sends your current height instantly after each avatar or world change. |
| Apply default height | Sends your default height instead after each change. |

Only one of these can be active at a time. If neither is enabled, VRChat's scale reset is left as-is.

### Lifecycle

| Setting | Description |
|---|---|
| Run on Windows startup | Creates a startup shortcut so the scaler launches when you log in. Unticking removes the shortcut. |
| Auto-launch when VRChat starts | Brings the scaler window to the front automatically when VRChat is detected. |
| Auto-close when VRChat exits | Exits the scaler 1.5 seconds after VRChat closes. |
| Start minimized to tray | Hides the window on launch; access via the tray icon. |

### Warnings

| Setting | Description |
|---|---|
| Suppress out-of-range warning | Disables the warning shown when you select a height outside 0.1–100 m. |

### Controls

Configure whether keyboard shortcuts are enabled and change the key bindings for each action. See [Keyboard shortcuts](#keyboard-shortcuts) for details.

### Network (Advanced)

These should not need changing unless you have a non-standard VRChat setup.

| Setting | Default | Description |
|---|---|---|
| VRChat IP | 127.0.0.1 | IP address of the machine running VRChat. Leave as-is if VRChat is on the same PC. |
| Send port | 9000 | Port the scaler sends OSC messages to. VRChat listens here by default. |
| Recv port | 9001 | Port the scaler listens on. VRChat sends status updates here by default. |

Settings are saved to `scaler_config.json` in the same folder as the script. You can delete this file to reset everything to defaults.

---

## Eye height vs. total height

VRChat uses **eye height** — the height of the avatar's eyes above the ground — to set scale, not total height. On most standard-sized humanoid avatars, the eyes are roughly **10 cm below the top of the head**.

A handy rule of thumb:

> **Eye height ≈ Total height − 0.10 m**

**Example:** If you want your avatar to appear 1.60 m tall, set your eye height to approximately **1.50 m**.

---

## Files included

| File | Purpose |
|---|---|
| `vrchat_avatar_scaler.pyw` | The main application. |
| `Install.bat` | One-click installer — run this first. |
| `Launch Scaler (Silent).vbs` | Launches the app without a console window. Use this for daily use and shortcuts. |
| `README.md` | This file. |
| `scaler_config.json` | Created automatically on first run. Stores all settings and your last-used height. Delete to reset to defaults. |

---

## Troubleshooting

### VRChat is not changing size

1. Make sure OSC is enabled: **Action Menu → Options → OSC → Enabled**.
2. Check the status dot in the top-left of the scaler window — it should be green.
3. Make sure no firewall is blocking local UDP traffic on port 9000.
4. Check that nothing else is already using port 9000 (another OSC app, for example).

### My scale changes every time I switch avatar or enter a world

Enable **Retain active height** in **Settings → On Avatar / World Change**. The scaler listens for the message VRChat sends on every avatar switch and world transition and re-sends your height immediately.

### "Port in use — receive disabled" in the status bar

Something else on your PC is already using port 9001. Change the **Recv port** in **Settings → Network** to a different number (e.g. 9002). The Send port (9000) is rarely affected since other apps send to VRChat rather than listen.

### Keyboard shortcuts are not working

- Open **Settings → Controls** and confirm **Enable keyboard shortcuts** is ticked.
- Make sure `pynput` is installed. Run `Install.bat` again to check.
- If it still does not work, open Command Prompt and run: `pip install --upgrade pynput`

### The height overlay appears when the wrong window is focused

This should not occur in the current version, which identifies VRChat by process name rather than window title. If you do experience this, please open an issue on GitHub with details about which application was focused.

---

## OSC technical reference

VRChat communicates via UDP using the OSC protocol. The scaler sends to port **9000** and receives on port **9001** by default.

| OSC Address | Type | Direction | Description |
|---|---|---|---|
| `/avatar/eyeheight` | `float` | Send & receive | Eye height in metres. Officially supported range: 0.1–100 m. Absolute limits: 0.01–10,000 m. |
| `/avatar/eyeheightmin` | `float` | Receive only | Minimum height permitted by the current world (Udon). VRChat broadcasts 0.2 m when no world limit is set. |
| `/avatar/eyeheightmax` | `float` | Receive only | Maximum height permitted by the current world (Udon). VRChat broadcasts 5.0 m when no world limit is set. |
| `/avatar/eyeheightscalingallowed` | `bool` | Receive only | `false` when the current world has fully disabled avatar scaling. |
| `/avatar/change` | `string` | Receive only | Broadcast by VRChat on every avatar switch and world transition. |

[Full VRChat OSC documentation](https://docs.vrchat.com/docs/osc-overview)

---

## To-Do List

- Integrate SteamVR Input to control avatar height with VR controller inputs.
