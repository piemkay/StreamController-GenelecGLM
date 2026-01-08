from src.backend.PluginManager.PluginBase import PluginBase
from src.backend.PluginManager.ActionHolder import ActionHolder
from src.backend.PluginManager.ActionInputSupport import ActionInputSupport
from src.backend.DeckManagement.InputIdentifier import Input

import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Gtk, Adw

from .actions.GenelecVolumeDial.GenelecVolumeDial import GenelecVolumeDial
from .actions.GenelecMute.GenelecMute import GenelecMute
from .actions.GenelecPower.GenelecPower import GenelecPower


class GenelecGLMPlugin(PluginBase):
    def __init__(self):
        super().__init__()
        
        # Ensure default settings exist
        self._ensure_default_settings()

        # Register dial action for Stream Deck+ knobs - Volume Control
        self.volume_dial_holder = ActionHolder(
            plugin_base=self,
            action_base=GenelecVolumeDial,
            action_id="com_github_genelec_glm::VolumeDial",
            action_name="Genelec Volume Dial",
            action_support={
                Input.Key: ActionInputSupport.UNSUPPORTED,
                Input.Dial: ActionInputSupport.SUPPORTED,
                Input.Touchscreen: ActionInputSupport.UNTESTED,
            }
        )
        self.add_action_holder(self.volume_dial_holder)

        # Register mute toggle action for regular keys
        self.mute_holder = ActionHolder(
            plugin_base=self,
            action_base=GenelecMute,
            action_id="com_github_genelec_glm::Mute",
            action_name="Genelec Mute",
            action_support={
                Input.Key: ActionInputSupport.SUPPORTED,
                Input.Dial: ActionInputSupport.UNSUPPORTED,
                Input.Touchscreen: ActionInputSupport.UNTESTED,
            }
        )
        self.add_action_holder(self.mute_holder)

        # Register power action for wakeup/shutdown
        self.power_holder = ActionHolder(
            plugin_base=self,
            action_base=GenelecPower,
            action_id="com_github_genelec_glm::Power",
            action_name="Genelec Power",
            action_support={
                Input.Key: ActionInputSupport.SUPPORTED,
                Input.Dial: ActionInputSupport.UNSUPPORTED,
                Input.Touchscreen: ActionInputSupport.UNTESTED,
            }
        )
        self.add_action_holder(self.power_holder)

        # Register plugin
        self.register(
            plugin_name="Genelec GLM",
            github_repo="https://github.com/your-username/StreamController-GenelecGLM",
            plugin_version="1.0.0",
            app_version="1.5.0-beta"
        )

    def _ensure_default_settings(self):
        """Ensure plugin settings have default values."""
        settings = self.get_settings()
        defaults = {
            "max_volume_db": -10.0,  # Safety limit - never exceed this volume
            "default_volume_db": -30.0,  # Default/startup volume
        }
        changed = False
        for key, default in defaults.items():
            if key not in settings:
                settings[key] = default
                changed = True
        if changed:
            self.set_settings(settings)

    def get_max_volume_db(self) -> float:
        """Get the configured maximum volume limit in dB."""
        settings = self.get_settings()
        return settings.get("max_volume_db", -10.0)

    def get_default_volume_db(self) -> float:
        """Get the configured default/startup volume in dB."""
        settings = self.get_settings()
        default_vol = settings.get("default_volume_db", -30.0)
        # Ensure default doesn't exceed max
        max_vol = self.get_max_volume_db()
        return min(default_vol, max_vol)

    def get_settings_area(self) -> Adw.PreferencesGroup:
        """Return the plugin settings UI."""
        group = Adw.PreferencesGroup(title="Safety Settings")
        
        settings = self.get_settings()
        max_vol = settings.get("max_volume_db", -10.0)
        default_vol = settings.get("default_volume_db", -30.0)
        
        # Max volume setting
        max_adjustment = Gtk.Adjustment(
            value=max_vol,
            lower=-60.0,
            upper=0.0,
            step_increment=1.0,
            page_increment=5.0
        )
        
        max_vol_row = Adw.SpinRow(
            title="Maximum Volume (dB)",
            subtitle="Safety limit - volume will never exceed this value",
            adjustment=max_adjustment,
            digits=1
        )
        max_vol_row.connect("changed", self._on_max_volume_changed)
        group.add(max_vol_row)
        
        # Default/startup volume setting
        # Ensure upper > lower to avoid GTK assertion errors
        default_upper = max(max_vol, -59.0)  # Must be > -60.0 (lower bound)
        default_value = min(default_vol, default_upper)
        default_value = max(default_value, -60.0)  # Clamp to valid range
        
        default_adjustment = Gtk.Adjustment(
            value=default_value,
            lower=-60.0,
            upper=default_upper,
            step_increment=1.0,
            page_increment=5.0
        )
        
        self.default_vol_row = Adw.SpinRow(
            title="Default Volume (dB)",
            subtitle="Volume level used on startup before any interaction",
            adjustment=default_adjustment,
            digits=1
        )
        self.default_vol_row.connect("changed", self._on_default_volume_changed)
        group.add(self.default_vol_row)
        
        return group

    def _on_max_volume_changed(self, spin_row):
        """Handle max volume setting change."""
        settings = self.get_settings()
        new_max = spin_row.get_value()
        settings["max_volume_db"] = new_max
        
        # Also clamp default volume if it exceeds the new max
        if settings.get("default_volume_db", -30.0) > new_max:
            settings["default_volume_db"] = new_max
            # Update the default volume row if it exists
            if hasattr(self, 'default_vol_row'):
                self.default_vol_row.set_value(new_max)
        
        self.set_settings(settings)

    def _on_default_volume_changed(self, spin_row):
        """Handle default volume setting change."""
        settings = self.get_settings()
        settings["default_volume_db"] = spin_row.get_value()
        self.set_settings(settings)
