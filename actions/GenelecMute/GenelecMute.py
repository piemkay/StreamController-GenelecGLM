"""
GenelecMute - Stream Deck key action for Genelec GLM mute toggle.

Press the key to toggle mute on/off for all Genelec monitors.
"""
from src.backend.PluginManager.ActionBase import ActionBase
import sys
import os
import importlib.util

import gi
gi.require_version("Gtk", "4.0")
from gi.repository import GLib


class GenelecMute(ActionBase):
    """
    Action for Stream Deck keys to toggle mute on Genelec GLM monitors.
    Press the key to toggle mute state.
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._genelec_manager = None
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
        
        if self._genelec_manager.toggle_mute():
            self._update_display()
        else:
            self.show_error(duration=1)

    def on_key_up(self) -> None:
        """Called when the key is released."""
        pass

    def _update_display(self) -> None:
        """Update the key's visual display."""
        try:
            is_connected = False
            is_muted = False
            
            if self._genelec_manager:
                is_connected = self._genelec_manager.is_connected()
                if is_connected:
                    is_muted = self._genelec_manager.is_muted()
            
            # Set label based on state
            if not self._genelec_manager:
                self.set_bottom_label("ERR", font_size=12)
            elif not is_connected:
                self.set_bottom_label("...", font_size=12)
            elif is_muted:
                self.set_bottom_label(self._lm("display.muted"), font_size=12)
            else:
                self.set_bottom_label(self._lm("display.unmuted"), font_size=12)
        except Exception as e:
            print(f"Error updating display: {e}")

    def get_config_rows(self) -> list:
        """Return configuration rows for the action."""
        import gi
        gi.require_version("Adw", "1")
        from gi.repository import Gtk, Adw
        
        rows = []

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

    def _on_reconnect(self, button):
        """Handle reconnect button click."""
        if self._genelec_manager:
            self._genelec_manager.disconnect()
            if self._genelec_manager.connect():
                self._update_display()
