"""Support for HTD"""

import logging
import re
import json

from homeassistant.components.media_player import MediaPlayerEntity
from homeassistant.components.media_player.const import MediaPlayerEntityFeature
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    CONF_UNIQUE_ID,
    STATE_OFF,
    STATE_ON,
    STATE_UNKNOWN,
    STATE_UNAVAILABLE,
)
from homeassistant.core import HomeAssistant
from htd_client import BaseClient, HtdConstants
from htd_client.models import ZoneDetail

from .const import DOMAIN, CONF_DEVICE_NAME

CONF_ZONES = "zones"
CONF_SOURCES = "sources"

_LOGGER = logging.getLogger(__name__)

type HtdClientConfigEntry = ConfigEntry[BaseClient]

GENERIC_ZONE_NAMES = {i: f"Zone {i}" for i in range(1, 13)}
GENERIC_SOURCE_NAMES = {i: f"Source {i}" for i in range(13, 20)}

SUPPORT_HTD = (
    MediaPlayerEntityFeature.SELECT_SOURCE |
    MediaPlayerEntityFeature.TURN_OFF |
    MediaPlayerEntityFeature.TURN_ON |
    MediaPlayerEntityFeature.VOLUME_MUTE |
    MediaPlayerEntityFeature.VOLUME_SET |
    MediaPlayerEntityFeature.VOLUME_STEP
)

def make_alphanumeric(input_string):
    temp = re.sub(r'[^a-zA-Z0-9]', '_', input_string)
    return re.sub(r'_+', '_', temp).strip('_')

get_media_player_entity_id = lambda name, zone_number, zone_fmt: f"media_player.{make_alphanumeric(name)}_zone_{zone_number:{zone_fmt}}".lower()

def _parse_mapping(option_value: str) -> dict[int, str]:
    """Parse a JSON or comma-separated mapping string into a dict."""
    if not option_value:
        return {}
    try:
        parsed = json.loads(option_value)
        return {int(k): str(v) for k, v in parsed.items()}
    except Exception:
        mapping = {}
        for item in option_value.split(","):
            if "=" in item:
                k, v = item.split("=", 1)
                try:
                    mapping[int(k.strip())] = v.strip()
                except ValueError:
                    continue
        return mapping

async def async_setup_platform(hass, _, async_add_entities, __=None):
    htd_configs = hass.data[DOMAIN]
    entities = []

    for config in htd_configs:
        unique_id = config[CONF_UNIQUE_ID]
        device_name = config[CONF_DEVICE_NAME]
        client = config["client"]

        zone_count = client.get_zone_count()
        source_count = client.get_source_count()
        sources = [f"Source {i + 1}" for i in range(source_count)]

        for zone in range(1, zone_count + 1):
            entity = HtdDevice(
                unique_id,
                device_name,
                zone,
                sources,
                client,
                {}
            )
            entities.append(entity)

    async_add_entities(entities)
    return True

async def async_setup_entry(_: HomeAssistant, config_entry: HtdClientConfigEntry, async_add_entities):
    entities = []

    client = config_entry.runtime_data
    zone_count = client.get_zone_count()
    source_count = client.get_source_count()
    device_name = config_entry.title
    unique_id = config_entry.data.get(CONF_UNIQUE_ID)
    sources = [f"Source {i + 1}" for i in range(source_count)]

    zones_map = _parse_mapping(config_entry.options.get(CONF_ZONES, ""))
    sources_map = _parse_mapping(config_entry.options.get(CONF_SOURCES, ""))

    for zone in range(1, zone_count + 1):
        entity = HtdDevice(
            unique_id,
            device_name,
            zone,
            sources,
            client,
            {"zones": zones_map, "sources": sources_map}
        )
        entities.append(entity)

    async_add_entities(entities)

class HtdDevice(MediaPlayerEntity):
    """Representation of an HTD zone as a Home Assistant media player entity."""

    should_poll = False

    def __init__(self, unique_id: str, device_name: str, zone: int, sources: list[str], client: BaseClient, mappings: dict):
        self._unique_id = f"{unique_id}_{zone:02}"
        self.device_name = device_name
        self.zone = zone
        self.client = client
        self.sources = sources
        self.zones_map = mappings.get("zones", {})
        self.sources_map = mappings.get("sources", {})
        zone_fmt = "02" if self.client.model["zones"] > 10 else "01"
        self.entity_id = get_media_player_entity_id(device_name, zone, zone_fmt)
        self.zone_info: ZoneDetail | None = None

    @property
    def unique_id(self) -> str:
        return self._unique_id

    @property
    def device_info(self) -> dict:
        """Return device info for grouping zones under the HTD device."""
        return {
            "identifiers": {(DOMAIN, self.device_name)},
            "name": self.device_name,
            "manufacturer": "HTD",
            "model": self.client.model.get("name", "Unknown"),
        }

    @property
    def supported_features(self) -> int:
        return SUPPORT_HTD

    @property
    def name(self) -> str | None:
        """Return friendly zone name if available, hide if 'Unused'."""
        name = self.zones_map.get(
            self.zone,
            GENERIC_ZONE_NAMES.get(self.zone, f"Zone {self.zone} ({self.device_name})")
        )
        if not name or name.lower() == "unused":
            return None
        return name

    def update(self) -> None:
        """Manual polling update — fetches zone info directly from client."""
        zone_status = self.client.get_zone(self.zone)
        if zone_status:
            self._do_update(zone_status)
        else:
            self._attr_state = STATE_UNKNOWN

    @property
    def state(self) -> str:
        if not self.client.connected:
            return STATE_UNAVAILABLE
        if self.zone_info is None:
            return STATE_UNKNOWN
        return STATE_ON if self.zone_info.power else STATE_OFF

    @property
    def available(self) -> bool:
        """Return True if client is ready and zone info is available."""
        return self.client.ready and self.zone_info is not None

    # --- Volume controls ---
    @property
    def volume_step(self) -> float:
        return 1 / HtdConstants.MAX_VOLUME

    @property
    def volume_level(self) -> float | None:
        if not self.zone_info:
            return None
        return self.zone_info.volume / HtdConstants.MAX_VOLUME

    async def async_set_volume_level(self, volume: float) -> None:
        """Set volume level (0.0–1.0 normalized)."""
        converted_volume = int(volume * HtdConstants.MAX_VOLUME)
        _LOGGER.debug(
            "Setting volume for zone %d: normalized=%.2f, raw=%d",
            self.zone,
            volume,
            converted_volume,
        )
        await self.client.async_set_volume(self.zone, converted_volume)

    async def async_volume_up(self) -> None:
        """Increase volume by one step."""
        _LOGGER.debug("Zone %d volume up requested", self.zone)
        await self.client.async_volume_up(self.zone)

    async def async_volume_down(self) -> None:
        """Decrease volume by one step."""
        _LOGGER.debug("Zone %d volume down requested", self.zone)
        await self.client.async_volume_down(self.zone)

    # --- Power controls ---
    async def async_turn_on(self) -> None:
        """Turn on the zone."""
        _LOGGER.debug("Zone %d turn_on requested", self.zone)
        await self.client.async_power_on(self.zone)

    async def async_turn_off(self) -> None:
        """Turn off the zone."""
        _LOGGER.debug("Zone %d turn_off requested", self.zone)
        await self.client.async_power_off(self.zone)

    # --- Mute controls ---
    @property
    def is_volume_muted(self) -> bool | None:
        if not self.zone_info:
            return None
        return self.zone_info.mute

    async def async_mute_volume(self, mute: bool) -> None:
        """Mute or unmute the zone."""
        _LOGGER.debug("Zone %d mute action requested: mute=%s", self.zone, mute)
        if mute:
            await self.client.async_mute(self.zone)
        else:
            await self.client.async_unmute(self.zone)

    # --- Source handling ---
    @property
    def source(self) -> str | None:
        if not self.zone_info:
            return None
        source_id = self.zone_info.source
        name = self.sources_map.get(
            source_id,
            GENERIC_SOURCE_NAMES.get(source_id, f"Source {source_id}")
        )
        if not name:
            return f"Source {source_id}"
        if name.lower() == "unused":
            return "Unused"
        return name

    @property
    def source_list(self) -> list[str]:
        """Return list of available sources, including 'Unused' placeholders."""
        source_list = []
        for i in range(len(self.sources)):
            source_id = i + 1
            name = self.sources_map.get(
                source_id,
                GENERIC_SOURCE_NAMES.get(source_id, f"Source {source_id}")
            )
            if not name:
                name = f"Source {source_id}"
            if name.lower() == "unused":
                source_list.append("Unused")
            else:
                source_list.append(name)
        return source_list

    @property
    def media_title(self) -> str | None:
        """Return the currently selected source name."""
        return self.source

    async def async_select_source(self, source: str) -> None:
        """Allow selecting source by friendly name or raw string."""
        for source_id in range(1, len(self.sources) + 1):
            friendly_name = self.sources_map.get(
                source_id,
                GENERIC_SOURCE_NAMES.get(source_id, f"Source {source_id}")
            )
            if friendly_name and friendly_name.lower().strip() == source.lower().strip():
                _LOGGER.debug("Zone %d select_source requested: %s (id=%d)", self.zone, friendly_name, source_id)
                await self.client.async_set_source(self.zone, source_id)
                return

        if source in self.sources:
            source_index = self.sources.index(source)
            _LOGGER.debug("Zone %d select_source requested: %s (raw index=%d)", self.zone, source, source_index + 1)
            await self.client.async_set_source(self.zone, source_index + 1)
            return

        _LOGGER.warning("Zone %d unknown source selection: %s. Available sources: %s", self.zone, source, self.source_list)

    # --- Subscription handling ---
    async def async_added_to_hass(self) -> None:
        """Subscribe to HTD client updates when entity is added."""
        await self.client.async_subscribe(self._do_update)
        self.client.refresh()
        self.update()  # ensure initial state is set immediately

    async def async_will_remove_from_hass(self) -> None:
        """Unsubscribe from HTD client updates when entity is removed."""
        await self.client.async_unsubscribe(self._do_update)

    def _do_update(self, zone_status: ZoneDetail) -> None:
        """Handle updates from HTD client and refresh entity state."""
        if zone_status.zone != self.zone:
            return

        normalized_volume = zone_status.volume / HtdConstants.MAX_VOLUME
        source_name = self.sources_map.get(
            zone_status.source,
            GENERIC_SOURCE_NAMES.get(zone_status.source, f"Source {zone_status.source}")
        )
        if not source_name:
            source_name = f"Source {zone_status.source}"
        elif source_name.lower() == "unused":
            source_name = "Unused"

        if not self.client.connected:
            self._attr_state = STATE_UNAVAILABLE
        else:
            self._attr_state = STATE_ON if zone_status.power else STATE_OFF

        _LOGGER.debug(
            "Zone %d updated: power=%s, volume=%d (normalized=%.2f), source=%d (%s), mute=%s",
            zone_status.zone,
            zone_status.power,
            zone_status.volume,
            normalized_volume,
            zone_status.source,
            source_name,
            zone_status.mute,
        )

        self.zone_info = zone_status
        self._attr_volume_level = normalized_volume
        self._attr_is_volume_muted = zone_status.mute
        self._attr_source = source_name
        self.async_write_ha_state()

    @property
    def extra_state_attributes(self) -> dict:
        """Expose raw and friendly HTD values for debugging/power users."""
        if not self.zone_info:
            return {}
        return {
            "raw_volume": self.zone_info.volume,
            "raw_source_id": self.zone_info.source,
            "friendly_zone_name": self.name,
            "friendly_source_name": self.source,
        }