"""
GenelecPower - Stream Deck key action for Genelec GLM power control.

Press the key to wake up or shut down all Genelec monitors.
"""
from src.backend.PluginManager.ActionBase import ActionBase
import sys
import os
import importlib.util

import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Gtk, Adw, GLib


class GenelecPower(ActionBase):
    """
    Action for Stream Deck keys to control power state of Genelec GLM monitors.
    Press the key to wake up or shut down all monitors.
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._genelec_manager = None
        self._is_on = True  # Assume monitors are on initially
        self._load_genelec_manager()

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
        """Called when the deck is fully loaded. Initialize the display."""
        # Initialize settings with defaults if not set
        self._ensure_default_settings()
        
        # Load power state from settings
        settings = self.get_settings()
        self._is_on = settings.get("is_on", True)
        
        self._update_display()
        
        # Defer GLM connection to after GTK is fully initialized
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
            "action_mode": "toggle",  # toggle, wake_only, shutdown_only
            "is_on": True,
        }
        changed = False
        for key, default in defaults.items():
            if key not in settings:
                settings[key] = default
                changed = True
        if changed:
            self.set_settings(settings)

    def on_key_down(self) -> None:
        """Called when the key is pressed."""
        if not self._genelec_manager:
            self.show_error(duration=1)
            return
        
        # Lazy connect on first interaction
        if not self._genelec_manager.is_connected():
            if not self._genelec_manager.connect():
                self.show_error(duration=1)
                return
        
        settings = self.get_settings()
        action_mode = settings.get("action_mode", "toggle")
        
        success = False
        
        if action_mode == "toggle":
            if self._is_on:
                success = self._genelec_manager.shutdown_all()
                if success:
                    self._is_on = False
            else:
                success = self._genelec_manager.wakeup_all()
                if success:
                    self._is_on = True
        elif action_mode == "wake_only":
            success = self._genelec_manager.wakeup_all()
            if success:
                self._is_on = True
        elif action_mode == "shutdown_only":
            success = self._genelec_manager.shutdown_all()
            if success:
                self._is_on = False
        
        if success:
            # Save state
            settings["is_on"] = self._is_on
            self.set_settings(settings)
            self._update_display()
        else:
            self.show_error(duration=1)

    def on_key_up(self) -> None:
        """Called when the key is released."""
        pass

    def _update_display(self) -> None:
        """Update the key's visual display."""
        try:
            # Set label based on state
            if not self._genelec_manager:
                self.set_bottom_label("ERR", font_size=12)
            elif self._is_on:
                self.set_bottom_label(self._lm("display.power_on"), font_size=12)
            else:
                self.set_bottom_label(self._lm("display.power_off"), font_size=12)
        except Exception as e:
            print(f"Error updating display: {e}")

    def get_config_rows(self) -> list:
        """Return configuration rows for the action."""
        settings = self.get_settings()
        rows = []

        # -- Action Mode --
        self.mode_model = Gtk.StringList.new([
            self._lm("config.mode.toggle"),
            self._lm("config.mode.wake_only"),
            self._lm("config.mode.shutdown_only"),
        ])
        self.mode_row = Adw.ComboRow()
        self.mode_row.set_title(self._lm("config.action_mode"))
        self.mode_row.set_subtitle(self._lm("config.action_mode.subtitle"))
        self.mode_row.set_model(self.mode_model)
        
        action_mode = settings.get("action_mode", "toggle")
        mode_map = {"toggle": 0, "wake_only": 1, "shutdown_only": 2}
        mode_index = mode_map.get(action_mode, 0)
        self.mode_row.set_selected(mode_index)
        self.mode_row.connect("notify::selected", self._on_mode_changed)
        rows.append(self.mode_row)

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

    def _on_mode_changed(self, row, *args):
        """Handle action mode change."""
        settings = self.get_settings()
        mode_map = {0: "toggle", 1: "wake_only", 2: "shutdown_only"}
        settings["action_mode"] = mode_map.get(row.get_selected(), "toggle")
        self.set_settings(settings)

    def _on_reconnect(self, button):
        """Handle reconnect button click."""
        if self._genelec_manager:
            self._genelec_manager.disconnect()
            if self._genelec_manager.connect():
                self._update_display()
