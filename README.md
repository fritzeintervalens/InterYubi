# InterYubi

A Windows tool that reads TOTP codes from your YubiKey and types them into the focused input field when you press a hotkey. It replaces the manual workflow of opening Yubico Authenticator, finding your account, copying the code, and pasting it.

## What You Need

**Python 3.11 or later.** Install from the [Microsoft Store](https://apps.microsoft.com/detail/9NRWMJP3717K) or [python.org](https://www.python.org/downloads/).

**YubiKey Manager CLI (`ykman`).** Install with winget:

```
winget install Yubico.YubiKeyManagerCLI
```

Or download it from [Yubico's developer site](https://developers.yubico.com/yubikey-manager/).

**A YubiKey with TOTP accounts already configured.** InterYubi reads codes from the OATH applet on your key. Use Yubico Authenticator to add accounts if you haven't set any up yet. Any YubiKey that supports OATH/TOTP will work (YubiKey 5 series, Security Key series with OATH, etc.).

## Getting Started

Install the Python dependencies:

```
pip install -r requirements.txt
```

Run the tool:

```
python interyubi.py
```

InterYubi starts in the system tray. Press **Ctrl+Alt+X** on any MFA input field and the code gets typed for you.

If your YubiKey has multiple TOTP accounts, domain auto detection will try to match the active browser tab to the right account. When it finds exactly one match, the code is typed immediately. When there is no match or more than one candidate, a selector popup appears near your cursor.

## The Selector Popup

The popup uses a dark theme (Catppuccin Mocha) and supports keyboard navigation. Arrow keys move between accounts, number keys 1 through 9 select directly, Enter confirms, and Escape cancels. A countdown bar at the bottom shows how much time is left on the current TOTP period. The bar transitions from green to yellow to red as the code nears expiration.

## Configuration

Right click the tray icon and choose **Settings** to open the settings window. All changes are saved to `config.json` and take effect immediately.

You can also edit `config.json` by hand. Copy `config.example.json` as a starting point:

```json
{
    "hotkey": "ctrl+alt+x",
    "selector_hotkey": null,
    "default_account": null,
    "type_delay_ms": 50,
    "auto_submit": false,
    "ykman_path": null,
    "oath_password": null,
    "domain_auto_detect": true
}
```

**hotkey** is the global key combination that triggers TOTP retrieval. The default is `ctrl+alt+x`. Click "Record" in Settings to capture a new combination.

**selector_hotkey** is an optional second hotkey that always opens the account selector, bypassing auto detection. Useful when you want to pick a different account than the one that would auto match.

**default_account** locks the tool to a specific account name (or substring). When set, the selector never appears for that account. Matching priority is exact, then prefix, then substring. If the substring matches more than one account, the selector appears.

**type_delay_ms** controls the delay in milliseconds between each keystroke when typing the code. The default of 50ms works for most applications. Lower it for speed or raise it if a site drops characters.

**auto_submit** sends an Enter keystroke after typing the code. Off by default.

**ykman_path** lets you point to a specific `ykman` executable if auto detection does not find it. Normally you can leave this null.

**oath_password** is for YubiKeys that have a password set on the OATH applet. Most users will not need this. Note that this value is stored in plaintext in `config.json`, so protect the file accordingly if you use it.

**domain_auto_detect** enables matching the active browser window title to your TOTP accounts. On by default. Supports Chrome, Firefox, Edge, Brave, Opera, Vivaldi, Arc, and others. Includes built-in aliases for common services like Google, Microsoft, GitHub, Amazon, and more.

## Auto Start on Login

Open Settings from the tray icon and check "Launch InterYubi on PC startup." This creates a shortcut in your Windows Startup folder that launches InterYubi silently (no console window) when you log in.

You can also run `create_shortcut.ps1` manually from PowerShell to create the shortcut.

## Verifying Your YubiKey Connection

Run the YubiKey module directly to confirm that `ykman` can talk to your key and list your accounts:

```
python yubikey.py
```

This prints all TOTP accounts and their current codes (or "[Requires Touch]" for touch protected accounts).

## Troubleshooting

**"ykman CLI not found"** means `ykman` is not on your PATH and was not found in the standard install locations. Install it with `winget install Yubico.YubiKeyManagerCLI` or set the `ykman_path` config option to point at the binary.

**"No YubiKey detected"** means the key is not plugged in, or another application is locking it. Yubico Authenticator in particular will hold an exclusive connection to the YubiKey. Close it before using InterYubi. If it still won't connect, check Task Manager for lingering `authenticator-helper.exe` processes.

**The hotkey does nothing.** Some applications running as Administrator block global hotkeys registered by non admin processes. Try running InterYubi as Administrator, or switch to a different hotkey combination in Settings.

**The code is not typed into the field.** Make sure the MFA input field has focus before pressing the hotkey. Click on it first if you are not sure. If the selector popup appeared, focus returns to the previous window after selection, but some applications may not regain focus correctly.

**The tool does not start silently.** The silent launcher depends on `pythonw.exe` being available. This ships with the standard Python installer but not always with the Microsoft Store version. Check that `pythonw.exe` is on your PATH.

## Security

TOTP secrets never leave the YubiKey hardware. InterYubi reads a time based code from the OATH applet on each hotkey press and immediately types it. No secrets or codes are cached, logged, or written to disk. The tool only acts on explicit user input (a hotkey press).

## Project Structure

```
interyubi.py          Main application (tray icon, hotkey handling, orchestration)
InterYubi.pyw         Windows GUI launcher (runs without a console window)
config.py             Configuration dataclass, load/save logic, named constants
config.example.json   Example configuration file
yubikey.py            ykman CLI interface (fetch codes, detect YubiKey)
selector.py           Account selector popup (tkinter, dark theme)
typing_engine.py      Keystroke simulation via pynput
domain_detect.py      Browser window title matching for auto detection
settings.py           Settings window (tkinter, dark theme)
theme.py              Catppuccin Mocha color constants
interyubi_silent.vbs  VBScript silent launcher (no console window)
create_shortcut.ps1   PowerShell script to create a Startup folder shortcut
requirements.txt      Python dependencies
```

## License

MIT. See [LICENSE](LICENSE) for the full text.
