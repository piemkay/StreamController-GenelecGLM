"""
GenelecVolumeDial - Stream Deck+ dial action for Genelec GLM volume control.

Rotate the dial to adjust volume, press to toggle mute.
"""
from src.backend.PluginManager.ActionBase import ActionBase
from src.backend.PluginManager.EventAssigner import EventAssigner
from src.backend.DeckManagement.InputIdentifier import Input
import sys
import os
import importlib.util

import time

import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Gtk, Adw, GLib


class GenelecVolumeDial(ActionBase):
    """
    Action for Stream Deck+ dials/knobs to control Genelec GLM volume.
    Rotate the dial to increase/decrease volume.
    Press the dial to toggle mute.
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._genelec_manager = None
        self._pending_volume_db = None  # Pending volume to set
        self._last_send_time = 0  # Last time we sent a volume command
        self._keepalive_source_id = None  # GLib timeout for keepalive
        self._keepalive_count = 0  # Number of keepalives sent
        self._load_genelec_manager()
        
        # Register dial-specific event assigners
        self._register_dial_events()

    def _register_dial_events(self):
        """Register event assigners for dial rotation events."""
        # Clear the default key event assigners from ActionBase that don't apply to dials
        self.clear_event_assigners()
        
        # Add dial-specific event assigners
        self.add_event_assigner(EventAssigner(
            id="Dial Down",
            ui_label="Dial Down",
            default_events=[Input.Dial.Events.DOWN],
            callback=self.on_dial_down
        ))
        self.add_event_assigner(EventAssigner(
            id="Dial Up",
            ui_label="Dial Up",
            default_events=[Input.Dial.Events.UP],
            callback=self.on_dial_up
        ))
        self.add_event_assigner(EventAssigner(
            id="Dial Turn CW",
            ui_label="Dial Turn CW",
            default_events=[Input.Dial.Events.TURN_CW],
            callback=self.on_dial_turn_cw
        ))
        self.add_event_assigner(EventAssigner(
            id="Dial Turn CCW",
            ui_label="Dial Turn CCW",
            default_events=[Input.Dial.Events.TURN_CCW],
            callback=self.on_dial_turn_ccw
        ))

    def _load_genelec_manager(self):
        """Dynamically load the GenelecManager from the plugin's internal directory."""
        try:
            plugin_path = self.plugin_base.PATH
            module_path = os.path.join(plugin_path, "internal", "GenelecManager.py")
            spec = importlib.util.spec_from_file_location("GenelecManager", module_path)
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            self._genelec_manager = module.GenelecManager
            # Apply plugin settings
            self._apply_plugin_settings()
        except Exception as e:
            print(f"Failed to load GenelecManager: {e}")
            self._genelec_manager = None

    def _apply_plugin_settings(self):
        """Apply the plugin's settings to the GenelecManager."""
        if self._genelec_manager:
            try:
                max_vol = self.plugin_base.get_max_volume_db()
                self._genelec_manager.set_max_volume_limit(max_vol)
                
                default_vol = self.plugin_base.get_default_volume_db()
                self._genelec_manager.set_default_volume(default_vol)
            except Exception as e:
                print(f"Failed to apply plugin settings: {e}")

    def _lm(self, key: str) -> str:
        """Get localized string with fallback to key."""
        try:
            return self.plugin_base.locale_manager.get(key)
        except Exception:
            return key

    def on_ready(self) -> None:
        """Called when the deck is fully loaded. Initialize the dial display."""
        # Initialize settings with defaults if not set
        self._ensure_default_settings()
        
        # Show initial display immediately
        self._update_display()
        
        # Defer GLM connection to after GTK is fully initialized
        # This avoids crashes during startup
        GLib.idle_add(self._deferred_connect)

    def _deferred_connect(self) -> bool:
        """Connect to GLM after GTK startup is complete."""
        try:
            if self._genelec_manager and not self._genelec_manager.is_connected():
                self._genelec_manager.connect()
                self._update_display()
        except Exception as e:
            print(f"Deferred GLM connection failed: {e}")
        return False  # Don't repeat

    def _ensure_default_settings(self):
        """Ensure settings have default values."""
        settings = self.get_settings()
        defaults = {
            "step_size_db": 1.0,  # Volume change per rotation tick in dB
            "min_volume_db": -60.0,  # Minimum volume in dB
            "max_volume_db": 0.0,  # Maximum volume in dB
            "default_volume_db": -30.0,  # Default/reset volume in dB (conservative)
            "press_action": "mute",  # What happens on dial press: mute, reset
            "display_mode": "db",  # Display mode: db, percent
        }
        changed = False
        for key, default in defaults.items():
            if key not in settings:
                settings[key] = default
                changed = True
        if changed:
            self.set_settings(settings)

    def on_dial_rotate(self, direction: int) -> None:
        """
        Called when the dial is rotated.

        Args:
            direction: Positive for clockwise, negative for counter-clockwise.
        """
        if not self._genelec_manager:
            self.show_error(duration=1)
            return

        # Lazy connect on first interaction
        if not self._genelec_manager.is_connected():
            if not self._genelec_manager.connect():
                self.show_error(duration=1)
                return

        settings = self.get_settings()
        step_db = settings.get("step_size_db", 1.0)
        min_db = settings.get("min_volume_db", -60.0)
        max_db = settings.get("max_volume_db", 0.0)

        # Enforce plugin's global max volume limit
        try:
            plugin_max = self.plugin_base.get_max_volume_db()
            max_db = min(max_db, plugin_max)
        except Exception:
            pass

        # Calculate new volume from pending or current
        if self._pending_volume_db is not None:
            current_db = self._pending_volume_db
        else:
            current_db = self._genelec_manager.get_volume_db()
        new_db = current_db + (direction * step_db)
        new_db = max(min_db, min(max_db, new_db))

        # Store pending volume
        self._pending_volume_db = new_db

        # Rate limit: only send commands every 200ms
        now = time.time()
        time_since_last = now - self._last_send_time

        if time_since_last >= 0.2:
            # Enough time passed, send immediately
            self._send_volume(new_db)

        # Always update display for responsiveness
        self._genelec_manager._current_volume_db = new_db
        self._update_display()

        # Start keepalive to prevent speaker silence
        # Cancel previous keepalive timer and restart
        if self._keepalive_source_id is not None:
            GLib.source_remove(self._keepalive_source_id)
        self._keepalive_count = 0
        # Send just a few keepalive commands to bridge the gap
        self._keepalive_source_id = GLib.timeout_add(800, self._send_keepalive)

    def _send_volume(self, volume_db: float) -> None:
        """Send volume command and update timestamp."""
        if self._genelec_manager.set_volume_db(volume_db):
            self._last_send_time = time.time()
        else:
            self.show_error(duration=1)

    def _send_keepalive(self) -> bool:
        """Send keepalive volume commands to prevent speaker silence."""
        self._keepalive_count += 1
        # Send just 3 keepalives at 800ms intervals (2.4 seconds total)
        if self._keepalive_count <= 3:
            current_vol = self._genelec_manager.get_volume_db()
            self._genelec_manager.set_volume_db(current_vol)
            return True  # Continue
        else:
            self._keepalive_source_id = None
            return False  # Stop

    def on_dial_turn_cw(self, data=None) -> None:
        """Called when the dial is rotated clockwise (volume up)."""
        self.on_dial_rotate(1)

    def on_dial_turn_ccw(self, data=None) -> None:
        """Called when the dial is rotated counter-clockwise (volume down)."""
        self.on_dial_rotate(-1)

    def on_dial_down(self, data=None) -> None:
        """Called when the dial is pressed down. Toggle mute or reset volume."""
        if not self._genelec_manager:
            self.show_error(duration=1)
            return
        
        # Lazy connect on first interaction
        if not self._genelec_manager.is_connected():
            if not self._genelec_manager.connect():
                self.show_error(duration=1)
                return
        
        settings = self.get_settings()
        press_action = settings.get("press_action", "mute")
        
        if press_action == "mute":
            self._toggle_mute()
        elif press_action == "reset":
            self._reset_to_default()

    def on_dial_up(self, data=None) -> None:
        """Called when the dial is released. Currently not used."""
        pass

    def _toggle_mute(self) -> None:
        """Toggle mute state."""
        if not self._genelec_manager:
            return
        
        if self._genelec_manager.toggle_mute():
            self._update_display()
        else:
            self.show_error(duration=1)

    def _reset_to_default(self) -> None:
        """Reset the volume to the configured default."""
        if not self._genelec_manager:
            return
        
        settings = self.get_settings()
        default_db = settings.get("default_volume_db", -20.0)
        
        # Enforce plugin's global max volume limit
        try:
            plugin_max = self.plugin_base.get_max_volume_db()
            default_db = min(default_db, plugin_max)
        except Exception:
            pass
        
        if self._genelec_manager.set_volume_db(default_db):
            self._update_display()
        else:
            self.show_error(duration=1)

    def _update_display(self) -> None:
        """Update the dial's visual display."""
        try:
            settings = self.get_settings()
            display_mode = settings.get("display_mode", "db")
            
            # Check if manager is available and connected
            is_connected = False
            is_muted = False
            current_db = -20.0
            
            if self._genelec_manager:
                is_connected = self._genelec_manager.is_connected()
                if is_connected:
                    is_muted = self._genelec_manager.is_muted()
                    current_db = self._genelec_manager.get_volume_db()
            
            # Set top label
            self.set_top_label(self._lm("display.volume"), font_size=12)
            
            # Set center label based on state
            if not self._genelec_manager:
                value_text = "ERR"
            elif not is_connected:
                value_text = "..."
            elif is_muted:
                value_text = self._lm("display.mute")
            else:
                if display_mode == "percent":
                    percent = self._genelec_manager.get_volume_percent()
                    value_text = f"{percent:.0f}%"
                else:
                    value_text = f"{current_db:.1f}dB"
            
            self.set_center_label(value_text, font_size=16)
            
            # Update dial indicator
            try:
                min_db = settings.get("min_volume_db", -60.0)
                max_db = settings.get("max_volume_db", 0.0)
                # Enforce plugin's global max volume limit for indicator
                try:
                    plugin_max = self.plugin_base.get_max_volume_db()
                    max_db = min(max_db, plugin_max)
                except Exception:
                    pass
                # Normalize to 0-1 range for the dial indicator
                if max_db > min_db:
                    normalized = (current_db - min_db) / (max_db - min_db)
                else:
                    normalized = 0.5
                normalized = max(0.0, min(1.0, normalized))
                self.set_dial_indicator(normalized)
            except Exception:
                # set_dial_indicator might not be available in all versions
                pass
        except Exception as e:
            print(f"Error updating display: {e}")
            self.set_center_label("ERR", font_size=16)

    def get_config_rows(self) -> list:
        """Return configuration rows for the action."""
        settings = self.get_settings()
        rows = []

        # -- Step Size (dB per rotation) --
        self.step_row = Adw.SpinRow.new_with_range(0.5, 6.0, 0.5)
        self.step_row.set_title(self._lm("config.step_size"))
        self.step_row.set_subtitle(self._lm("config.step_size.subtitle"))
        self.step_row.set_value(settings.get("step_size_db", 1.0))
        self.step_row.connect("notify::value", self._on_step_changed)
        rows.append(self.step_row)

        # -- Minimum Volume (dB) --
        self.min_row = Adw.SpinRow.new_with_range(-130.0, 0.0, 1.0)
        self.min_row.set_title(self._lm("config.min_volume"))
        self.min_row.set_subtitle(self._lm("config.min_volume.subtitle"))
        self.min_row.set_value(settings.get("min_volume_db", -60.0))
        self.min_row.connect("notify::value", self._on_min_changed)
        rows.append(self.min_row)

        # -- Maximum Volume (dB) - constrained by plugin's global limit --
        try:
            plugin_max = self.plugin_base.get_max_volume_db()
        except Exception:
            plugin_max = 0.0
        # Ensure upper > lower to avoid GTK assertion errors
        max_upper = max(plugin_max, -59.0)
        self.max_row = Adw.SpinRow.new_with_range(-60.0, max_upper, 1.0)
        self.max_row.set_title(self._lm("config.max_volume"))
        self.max_row.set_subtitle(self._lm("config.max_volume.subtitle"))
        # Ensure saved value is within valid range
        saved_max = min(settings.get("max_volume_db", 0.0), max_upper)
        saved_max = max(saved_max, -60.0)
        self.max_row.set_value(saved_max)
        self.max_row.connect("notify::value", self._on_max_changed)
        rows.append(self.max_row)

        # -- Default Volume (dB) - constrained by plugin's global limit --
        default_upper = max(plugin_max, -59.0)
        self.default_row = Adw.SpinRow.new_with_range(-60.0, default_upper, 1.0)
        self.default_row.set_title(self._lm("config.default_volume"))
        self.default_row.set_subtitle(self._lm("config.default_volume.subtitle"))
        saved_default = min(settings.get("default_volume_db", -20.0), default_upper)
        saved_default = max(saved_default, -60.0)
        self.default_row.set_value(saved_default)
        self.default_row.connect("notify::value", self._on_default_changed)
        rows.append(self.default_row)

        # -- Press Action --
        self.press_model = Gtk.StringList.new([
            self._lm("config.press_action.mute"),
            self._lm("config.press_action.reset"),
        ])
        self.press_row = Adw.ComboRow()
        self.press_row.set_title(self._lm("config.press_action"))
        self.press_row.set_model(self.press_model)
        
        press_action = settings.get("press_action", "mute")
        press_index = 0 if press_action == "mute" else 1
        self.press_row.set_selected(press_index)
        self.press_row.connect("notify::selected", self._on_press_action_changed)
        rows.append(self.press_row)

        # -- Display Mode --
        self.display_model = Gtk.StringList.new([
            self._lm("config.display_mode.db"),
            self._lm("config.display_mode.percent"),
        ])
        self.display_row = Adw.ComboRow()
        self.display_row.set_title(self._lm("config.display_mode"))
        self.display_row.set_model(self.display_model)
        
        display_mode = settings.get("display_mode", "db")
        display_index = 0 if display_mode == "db" else 1
        self.display_row.set_selected(display_index)
        self.display_row.connect("notify::selected", self._on_display_mode_changed)
        rows.append(self.display_row)

        # -- Connection Status --
        status_row = Adw.ActionRow()
        status_row.set_title(self._lm("config.connection_status"))
        
        # Try to connect if not already connected
        is_connected = False
        if self._genelec_manager:
            if not self._genelec_manager.is_connected():
                self._genelec_manager.connect()
            is_connected = self._genelec_manager.is_connected()
        
        if is_connected:
            monitors = self._genelec_manager.get_monitors()
            status_text = f"{len(monitors)} " + self._lm("config.monitors_found")
        else:
            status_text = self._lm("config.not_connected")
        status_row.set_subtitle(status_text)
        
        # Reconnect button
        reconnect_button = Gtk.Button()
        reconnect_button.set_icon_name("view-refresh-symbolic")
        reconnect_button.set_valign(Gtk.Align.CENTER)
        reconnect_button.connect("clicked", self._on_reconnect)
        status_row.add_suffix(reconnect_button)
        rows.append(status_row)

        return rows

    def _on_step_changed(self, row, *args):
        """Handle step size change."""
        settings = self.get_settings()
        settings["step_size_db"] = row.get_value()
        self.set_settings(settings)

    def _on_min_changed(self, row, *args):
        """Handle minimum volume change."""
        settings = self.get_settings()
        settings["min_volume_db"] = row.get_value()
        self.set_settings(settings)
        self._update_display()

    def _on_max_changed(self, row, *args):
        """Handle maximum volume change."""
        settings = self.get_settings()
        settings["max_volume_db"] = row.get_value()
        self.set_settings(settings)
        self._update_display()

    def _on_default_changed(self, row, *args):
        """Handle default volume change."""
        settings = self.get_settings()
        settings["default_volume_db"] = row.get_value()
        self.set_settings(settings)

    def _on_press_action_changed(self, row, *args):
        """Handle press action change."""
        settings = self.get_settings()
        settings["press_action"] = "mute" if row.get_selected() == 0 else "reset"
        self.set_settings(settings)

    def _on_display_mode_changed(self, row, *args):
        """Handle display mode change."""
        settings = self.get_settings()
        settings["display_mode"] = "db" if row.get_selected() == 0 else "percent"
        self.set_settings(settings)
        self._update_display()

    def _on_reconnect(self, button):
        """Handle reconnect button click."""
        if self._genelec_manager:
            self._genelec_manager.disconnect()
            if self._genelec_manager.connect():
                self._update_display()
