"""
GenelecManager - Handles communication with Genelec SAM speakers via GLM adapter.

Uses the genlc library: https://github.com/markbergsma/genlc
"""
import logging
import threading
import subprocess
import math
from typing import Optional, List, Dict, Any

logger = logging.getLogger(__name__)


class GenelecManager:
    """
    Singleton manager class for Genelec GLM communication.
    
    Handles discovery, volume control, mute/unmute, and power management
    of Genelec SAM monitors through the GLM USB adapter.
    """

    _instance = None
    _lock = threading.Lock()
    _initialized = False
    
    # GLM state
    _samgroup = None
    _usb_adapter = None
    _monitors: Dict[int, Any] = {}
    _current_volume_db: float = -30.0  # Default volume in dB (conservative)
    _is_muted: bool = False
    _pre_mute_volume: float = -30.0
    _is_connected: bool = False
    
    # Volume limits in dB
    MIN_VOLUME_DB: float = -130.0
    MAX_VOLUME_DB: float = 0.0
    DEFAULT_VOLUME_DB: float = -30.0
    
    # Configurable safety limit (set by plugin settings)
    _max_volume_db_limit: float = -10.0
    
    # Configurable default/startup volume (set by plugin settings)
    _default_volume_db_setting: float = -30.0

    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
        return cls._instance

    @classmethod
    def set_max_volume_limit(cls, max_db: float) -> None:
        """
        Set the maximum volume limit (safety feature).
        
        Args:
            max_db: Maximum allowed volume in dB (e.g., -10.0)
        """
        cls._max_volume_db_limit = max_db
        logger.info(f"Max volume limit set to {max_db} dB")

    @classmethod
    def get_max_volume_limit(cls) -> float:
        """Get the current maximum volume limit in dB."""
        return cls._max_volume_db_limit

    @classmethod
    def set_default_volume(cls, default_db: float) -> None:
        """
        Set the default/startup volume.
        
        Args:
            default_db: Default volume in dB (e.g., -30.0)
        """
        # Ensure it doesn't exceed max limit
        cls._default_volume_db_setting = min(default_db, cls._max_volume_db_limit)
        # Also update the current volume if not yet connected (startup value)
        if not cls._is_connected:
            cls._current_volume_db = cls._default_volume_db_setting
            cls._pre_mute_volume = cls._default_volume_db_setting
        logger.info(f"Default volume set to {cls._default_volume_db_setting} dB")

    @classmethod
    def get_default_volume(cls) -> float:
        """Get the configured default volume in dB."""
        return cls._default_volume_db_setting

    @classmethod
    def get_instance(cls) -> 'GenelecManager':
        """Get the singleton instance of GenelecManager."""
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    @classmethod
    def _ensure_imports(cls) -> bool:
        """Lazily import genlc modules. Returns True if successful."""
        if cls._initialized:
            return True
        
        try:
            global hid, transport, sam, const
            import hid
            from genlc import transport, sam, const
            cls._initialized = True
            logger.info("Successfully imported genlc modules")
            return True
        except ImportError as e:
            logger.error(f"Failed to import genlc modules: {e}")
            logger.error("Please install genlc: pip install git+https://github.com/markbergsma/genlc#egg=genlc")
            return False

    @classmethod
    def connect(cls) -> bool:
        """
        Connect to the GLM USB adapter and discover monitors.
        
        Returns:
            True if connection was successful, False otherwise.
        """
        if not cls._ensure_imports():
            return False
        
        with cls._lock:
            if cls._is_connected:
                return True
            
            try:
                # Connect to USB adapter
                hid_glm_adapter = hid.Device(const.GENELEC_GLM_VID, const.GENELEC_GLM_PID)
                usbtransport = transport.USBTransport(hid_glm_adapter)
                cls._samgroup = sam.SAMGroup(usbtransport)
                cls._usb_adapter = sam.USBAdapter(cls._samgroup)
                
                logger.info(f"Connected to GLM adapter: {hid_glm_adapter.manufacturer} {hid_glm_adapter.product}")
                
                # Discover monitors
                cls._discover_monitors()
                
                cls._is_connected = True
                return True
                
            except Exception as e:
                logger.error(f"Failed to connect to GLM adapter: {e}")
                cls._is_connected = False
                return False

    @classmethod
    def disconnect(cls) -> None:
        """Disconnect from the GLM adapter."""
        with cls._lock:
            if cls._samgroup and hasattr(cls._samgroup, 'transport'):
                try:
                    cls._samgroup.transport.adapter.close()
                except Exception:
                    pass
            cls._samgroup = None
            cls._usb_adapter = None
            cls._monitors = {}
            cls._is_connected = False

    @classmethod
    def is_connected(cls) -> bool:
        """Check if connected to GLM adapter."""
        return cls._is_connected

    @classmethod
    def _discover_monitors(cls) -> None:
        """Discover all monitors on the GLM network."""
        if not cls._samgroup:
            return
        
        cls._monitors = {}
        try:
            for monitor in cls._samgroup.discover_monitors():
                if monitor.address != 1:  # Skip USB adapter
                    cls._monitors[monitor.address] = monitor
                    try:
                        monitor.query_hardware()
                        logger.info(f"Discovered monitor [{monitor.address}]: {monitor.hardware[0]}")
                    except Exception:
                        logger.info(f"Discovered monitor [{monitor.address}]")
        except Exception as e:
            logger.error(f"Error discovering monitors: {e}")

    @classmethod
    def get_monitors(cls) -> List[Dict[str, Any]]:
        """
        Get list of discovered monitors.
        
        Returns:
            List of monitor info dicts with address, name, etc.
        """
        if not cls._is_connected:
            cls.connect()
        
        result = []
        for addr, monitor in cls._monitors.items():
            info = {
                'address': addr,
                'name': monitor.hardware[0] if monitor.hardware else f"Monitor {addr}",
                'serial': getattr(monitor, 'serial', None),
            }
            result.append(info)
        return result

    @classmethod
    def set_volume_db(cls, volume_db: float) -> bool:
        """
        Set the master volume in decibels.

        Args:
            volume_db: Volume in dB (-130.0 to 0.0)

        Returns:
            True if successful, False otherwise.
        """
        if not cls._is_connected:
            if not cls.connect():
                return False

        # Clamp volume to valid range and enforce safety limit
        max_allowed = min(cls.MAX_VOLUME_DB, cls._max_volume_db_limit)
        volume_db = max(cls.MIN_VOLUME_DB, min(max_allowed, volume_db))

        with cls._lock:
            try:
                # Fresh connection for each volume change prevents the 5s silence issue
                if not cls._ensure_imports():
                    return False

                hid_adapter = hid.Device(const.GENELEC_GLM_VID, const.GENELEC_GLM_PID)
                usbtransport = transport.USBTransport(hid_adapter)
                samgroup = sam.SAMGroup(usbtransport)

                # Set volume
                samgroup.set_volume_glm(volume_db)

                # Close connection immediately
                hid_adapter.close()

                cls._current_volume_db = volume_db
                cls._is_muted = False
                logger.debug(f"Set volume to {volume_db:.1f} dB")
                return True
            except Exception as e:
                logger.error(f"Failed to set volume: {e}")
                return False

    @classmethod
    def set_volume_percent(cls, percent: float) -> bool:
        """
        Set the master volume as a percentage.
        
        Args:
            percent: Volume percentage (0.0 to 100.0)
            
        Returns:
            True if successful, False otherwise.
        """
        # Convert percentage to dB using logarithmic scale
        # 0% -> -130dB (essentially silent), 100% -> 0dB
        if percent <= 0:
            volume_db = cls.MIN_VOLUME_DB
        else:
            # Logarithmic conversion: dB = 20 * log10(percent/100)
            volume_db = 20 * math.log10(percent / 100.0)
            volume_db = max(cls.MIN_VOLUME_DB, min(cls.MAX_VOLUME_DB, volume_db))
        
        return cls.set_volume_db(volume_db)

    @classmethod
    def get_volume_db(cls) -> float:
        """Get current volume in dB."""
        return cls._current_volume_db

    @classmethod
    def get_volume_percent(cls) -> float:
        """Get current volume as percentage."""
        # Convert dB back to percentage
        # percent = 100 * 10^(dB/20)
        if cls._current_volume_db <= cls.MIN_VOLUME_DB:
            return 0.0
        percent = 100 * (10 ** (cls._current_volume_db / 20.0))
        return max(0.0, min(100.0, percent))

    @classmethod
    def adjust_volume_db(cls, delta_db: float) -> bool:
        """
        Adjust volume by a delta in dB.
        
        Args:
            delta_db: Change in volume (positive = louder, negative = quieter)
            
        Returns:
            True if successful, False otherwise.
        """
        new_volume = cls._current_volume_db + delta_db
        return cls.set_volume_db(new_volume)

    @classmethod
    def mute(cls) -> bool:
        """
        Mute all monitors by setting volume to minimum.
        
        Returns:
            True if successful, False otherwise.
        """
        if not cls._is_connected:
            if not cls.connect():
                return False
        
        with cls._lock:
            try:
                # Store current volume for unmute, but use a safe limit
                # This prevents unmuting to unexpectedly loud volumes
                stored_volume = cls._current_volume_db
                # If the stored volume is very high (louder than -10dB), cap it
                # to prevent unexpected loudness on unmute
                SAFE_MAX_RESTORE = -10.0
                if stored_volume > SAFE_MAX_RESTORE:
                    stored_volume = SAFE_MAX_RESTORE
                    logger.warning(f"Capping restore volume to {SAFE_MAX_RESTORE}dB for safety")
                cls._pre_mute_volume = stored_volume
                
                # Use volume control for mute - set to minimum
                cls._samgroup.set_volume_glm(cls.MIN_VOLUME_DB)
                cls._is_muted = True
                logger.debug(f"Muted all monitors (will restore to {cls._pre_mute_volume}dB)")
                return True
            except Exception as e:
                logger.error(f"Failed to mute: {e}")
                return False

    @classmethod
    def unmute(cls) -> bool:
        """
        Unmute all monitors by restoring previous volume.
        
        Returns:
            True if successful, False otherwise.
        """
        if not cls._is_connected:
            if not cls.connect():
                return False
        
        with cls._lock:
            try:
                # Restore previous volume (volume is a broadcast command)
                cls._samgroup.set_volume_glm(cls._pre_mute_volume)
                cls._current_volume_db = cls._pre_mute_volume
                cls._is_muted = False
                logger.debug(f"Unmuted all monitors (volume restored to {cls._pre_mute_volume}dB)")
                return True
            except Exception as e:
                logger.error(f"Failed to unmute: {e}")
                return False

    @classmethod
    def toggle_mute(cls) -> bool:
        """
        Toggle mute state.
        
        Returns:
            True if successful, False otherwise.
        """
        if cls._is_muted:
            return cls.unmute()
        else:
            return cls.mute()

    @classmethod
    def is_muted(cls) -> bool:
        """Check if monitors are muted."""
        return cls._is_muted

    @classmethod
    def debug_available_methods(cls) -> list:
        """List all available methods on SAMGroup for debugging."""
        if not cls._samgroup:
            return []
        methods = [m for m in dir(cls._samgroup) if not m.startswith('_')]
        logger.info(f"Available SAMGroup methods: {methods}")
        return methods

    @classmethod
    def stay_online(cls) -> bool:
        """
        Send a keepalive to maintain device connectivity.

        This uses the GLM protocol's native stay_online command which
        keeps speakers active without affecting audio playback.

        Returns:
            True if successful, False otherwise.
        """
        if not cls._is_connected:
            return False

        with cls._lock:
            try:
                cls._samgroup.stay_online()
                return True
            except Exception as e:
                logger.debug(f"stay_online failed: {e}")
                return False

    @classmethod
    def wakeup_all(cls) -> bool:
        """
        Wake up all monitors from standby.
        
        Returns:
            True if successful, False otherwise.
        """
        if not cls._is_connected:
            if not cls.connect():
                return False
        
        with cls._lock:
            try:
                cls._samgroup.wakeup_all()
                logger.info("Woke up all monitors")
                return True
            except Exception as e:
                logger.error(f"Failed to wake up monitors: {e}")
                return False

    @classmethod
    def shutdown_all(cls) -> bool:
        """
        Put all monitors into standby.
        
        Returns:
            True if successful, False otherwise.
        """
        if not cls._is_connected:
            if not cls.connect():
                return False
        
        with cls._lock:
            try:
                cls._samgroup.shutdown_all()
                logger.info("Shut down all monitors")
                return True
            except Exception as e:
                logger.error(f"Failed to shut down monitors: {e}")
                return False

    @classmethod
    def mute_monitor(cls, address: int) -> bool:
        """
        Mute a specific monitor.
        
        Args:
            address: Monitor address (2+)
            
        Returns:
            True if successful, False otherwise.
        """
        if address not in cls._monitors:
            logger.error(f"Monitor {address} not found")
            return False
        
        try:
            cls._monitors[address].mute(True)
            return True
        except Exception as e:
            logger.error(f"Failed to mute monitor {address}: {e}")
            return False

    @classmethod
    def unmute_monitor(cls, address: int) -> bool:
        """
        Unmute a specific monitor.
        
        Args:
            address: Monitor address (2+)
            
        Returns:
            True if successful, False otherwise.
        """
        if address not in cls._monitors:
            logger.error(f"Monitor {address} not found")
            return False
        
        try:
            cls._monitors[address].mute(False)
            return True
        except Exception as e:
            logger.error(f"Failed to unmute monitor {address}: {e}")
            return False

    @classmethod
    def set_led(cls, address: int, color: str = "green", pulsing: bool = False) -> bool:
        """
        Set the LED color and state of a monitor.
        
        Args:
            address: Monitor address (2+)
            color: LED color ('green', 'red', 'yellow', 'off')
            pulsing: Whether the LED should pulse
            
        Returns:
            True if successful, False otherwise.
        """
        if address not in cls._monitors:
            logger.error(f"Monitor {address} not found")
            return False
        
        try:
            cls._monitors[address].bypass(led_color=color, led_pulsing=pulsing)
            return True
        except Exception as e:
            logger.error(f"Failed to set LED for monitor {address}: {e}")
            return False
