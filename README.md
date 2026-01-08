# Genelec GLM Plugin for StreamController

Control your Genelec SAM speakers directly from your Stream Deck using the GLM network adapter.

## Features

- **Volume Dial Control** (Stream Deck+): Rotate the dial to adjust volume, press to toggle mute
- **Mute Toggle**: Quickly mute/unmute all monitors with a single button press
- **Power Control**: Wake up or shut down all monitors

## Requirements

### Hardware
- Genelec GLM USB adapter
- Genelec SAM series monitors (e.g., 8330, 8340, 8350, 7350 subwoofer)

### Software
- StreamController 1.5.0-beta or later
- Python 3.8+
- libhidapi-libusb0 (for USB communication)

### Linux USB Permissions
You need to add udev rules to allow non-root access to the GLM adapter. The rule must cover both the USB device and the hidraw device:

**Debian/Ubuntu:**
```bash
# Create the udev rule (covers both usb and hidraw)
echo -e 'SUBSYSTEM=="usb", ATTR{idVendor}=="1781", ATTR{idProduct}=="0e39", MODE="0666"\nSUBSYSTEM=="hidraw", ATTRS{idVendor}=="1781", ATTRS{idProduct}=="0e39", MODE="0666"' | sudo tee /etc/udev/rules.d/99-genelec-glm.rules

# Reload udev rules
sudo udevadm control --reload-rules
sudo udevadm trigger
```

**Arch Linux:**
```bash
# Create the udev rule (covers both usb and hidraw)
echo -e 'SUBSYSTEM=="usb", ATTR{idVendor}=="1781", ATTR{idProduct}=="0e39", MODE="0666", TAG+="uaccess"\nSUBSYSTEM=="hidraw", ATTRS{idVendor}=="1781", ATTRS{idProduct}=="0e39", MODE="0666", TAG+="uaccess"' | sudo tee /etc/udev/rules.d/99-genelec-glm.rules

# Reload udev rules
sudo udevadm control --reload-rules
sudo udevadm trigger
```

> **Note:** The second line with `SUBSYSTEM=="hidraw"` is essential - it grants access to the HID device that Python uses to communicate with the adapter.

After adding the rules, **unplug and replug** the GLM adapter for the rules to take effect.

## Installation

1. Copy this plugin folder to your StreamController plugins directory
2. Install dependencies:
   ```bash
   pip install git+https://github.com/markbergsma/genlc#egg=genlc hid
   ```
3. Install libhidapi for your distribution:
   
   **Debian/Ubuntu:**
   ```bash
   sudo apt-get install libhidapi-libusb0
   ```
   
   **Arch Linux:**
   ```bash
   sudo pacman -S hidapi
   ```
   
4. Restart StreamController

## Actions

### Genelec Volume Dial (Stream Deck+ only)
Control volume using the dial knobs on Stream Deck+.

**Settings:**
- **Step Size**: Volume change per rotation tick (0.5 - 6.0 dB)
- **Minimum Volume**: Lower volume limit (-130 to 0 dB)
- **Maximum Volume**: Upper volume limit (-60 to 0 dB)
- **Default Volume**: Reset value when dial is pressed
- **Press Action**: Toggle mute or reset to default
- **Display Mode**: Show volume in dB or percentage

### Genelec Mute
Toggle mute state for all monitors.

### Genelec Power
Wake up or shut down all monitors.

**Settings:**
- **Action Mode**: Toggle, Wake only, or Shutdown only

## Troubleshooting

### "Not connected to GLM adapter"
- Ensure the GLM USB adapter is plugged in
- Check USB permissions (see udev rules above)
- Try unplugging and replugging the adapter

### Volume changes are not applied
- Make sure GLM software is not running (only one application can control the adapter)
- Try clicking the refresh button in the action settings

## Credits

- [genlc](https://github.com/markbergsma/genlc) - Python module for Genelec SAM control by Mark Bergsma
- StreamController plugin architecture

## License

MIT License - see LICENSE file
