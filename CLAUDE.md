# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Important Reminders

**Always bump the version in `manifest.json`** when making any code changes.

## Project Overview

StreamController plugin for controlling Genelec SAM professional monitoring speakers via the Genelec GLM USB network adapter. Provides volume dial control, mute toggle, and power control actions for Stream Deck devices.

## Setup

```bash
# Install Python dependencies
pip install git+https://github.com/markbergsma/genlc#egg=genlc hidapi

# Install system dependency
sudo apt-get install libhidapi-libusb0  # Debian/Ubuntu
sudo pacman -S hidapi                    # Arch Linux

# Linux USB permissions (udev rules required)
echo -e 'SUBSYSTEM=="usb", ATTR{idVendor}=="1781", ATTR{idProduct}=="0e39", MODE="0666"\nSUBSYSTEM=="hidraw", ATTRS{idVendor}=="1781", ATTRS{idProduct}=="0e39", MODE="0666"' | sudo tee /etc/udev/rules.d/99-genelec-glm.rules
sudo udevadm control --reload-rules && sudo udevadm trigger
```

No automated tests or linting configured.

## Architecture

### Entry Point
- `main.py` - GenelecGLMPlugin class, registers actions and manages global safety settings (max volume, default volume)

### Core Component
- `internal/GenelecManager.py` - **Singleton** handling all GLM adapter USB communication via hidapi and the `genlc` library. Thread-safe with lock-based synchronization.

### Actions (Stream Deck)
- `actions/GenelecVolumeDial/` - Stream Deck+ dial: rotate for volume (configurable dB steps), press for mute/reset
- `actions/GenelecMute/` - Key: simple mute toggle
- `actions/GenelecPower/` - Key: power control (toggle/wake/shutdown modes)

### Key Design Patterns
- **Lazy Loading**: Actions dynamically import GenelecManager via `importlib.util.spec_from_file_location()` to avoid circular dependencies
- **Deferred Connection**: Uses `GLib.idle_add()` to defer GLM connection until GTK initialization completes
- **Safety Limits**: Volume constrained at plugin and action levels (default max: -10 dB, range: -130 dB to 0 dB)

### Dependencies
- `genlc` - Genelec SAM control protocol (Mark Bergsma)
- `hidapi` - USB HID communication
- Gtk 4.0 / Adw 1 - UI widgets
- StreamController framework (1.5.0-beta+)

### Hardware Constants
- Genelec GLM USB: Vendor `0x1781`, Product `0x0e39`
