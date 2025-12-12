"""Support for HTD"""

import logging
import re
import json

from homeassistant.components.media_player import MediaPlayerEntity
from homeassistant.components.media_player.const import (
    MediaPlayerEntityFeature
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    CONF_UNIQUE_ID,
    STATE_OFF,
    STATE_ON,
    STATE_UNKNOWN,
    STATE_UNAVAILABLE,
)
from homeassistant.core import HomeAssistant
from htd_client import BaseClient, HtdConstants, HtdMcaClient
from htd_client.models import ZoneDetail

from .const import DOMAIN, CONF_DEVICE_NAME

CONF_ZONES = "zones"
CONF_SOURCES = "sources"

def make_alphanumeric(input_string):
    temp = re.sub(r'[^a-zA-Z0-9]', '_', input_string)
    return re.sub(r'_+', '_', temp).strip('_')

get_media_player_entity_id = lambda name, zone_number, zone_fmt: f"media_player.{make_alphanumeric(name)}_zone_{zone_number:{zone_fmt}}".lower()

SUPPORT_HTD = (
    MediaPlayerEntityFeature.SELECT_SOURCE |
    MediaPlayerEntityFeature.TURN_OFF |
    MediaPlayerEntityFeature.TURN_ON |
    MediaPlayerEntityFeature.VOLUME_MUTE |
    MediaPlayerEntityFeature.VOLUME_SET |
    MediaPlayerEntityFeature.VOLUME_STEP
)

_LOGGER = logging.getLogger(__name__)

type HtdClientConfigEntry = ConfigEntry[BaseClient]

# --- Generic Friendly Names ---
GENERIC_ZONE_NAMES = {i: f"Zone {i}" for i in range(1, 13)}
GENERIC_SOURCE_NAMES = {i: f"Source {i}" for i in range(13, 20)}

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

    for device_index in range(len(htd_configs)):
        config = htd_configs[device_index]

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

    def __init__(self, unique_id, device_name, zone, sources, client, mappings):
        self._unique_id = f"{unique_id}_{zone:02}"
        self.device_name = device_name
        self.zone = zone
        self.client = client
        self.sources = sources
        self.zones_map = mappings.get("zones", {})
        self.sources_map = mappings.get("sources", {})
        zone_fmt = f"02" if self.client.model["zones"] > 10 else "01"
        self.entity_id = get_media_player_entity_id(device_name, zone, zone_fmt)
        self.zone_info: ZoneDetail | None = None

    @property
    def unique_id(self) -> str:
        return self._unique_id

    @property
    def device_info(self):
        return {
            "identifiers": {(DOMAIN, self.device_name)},
            "name": self.device_name,
            "manufacturer": "HTD",
        }

    @property
    def supported_features(self):
        return SUPPORT_HTD

    @property
    def name(self):
        name = self.zones_map.get(
            self.zone,
            GENERIC_ZONE_NAMES.get(self.zone, f"Zone {self.zone} ({self.device_name})")
        )
        if not name or name.lower() == "unused":
            return None
        return name

    def update(self):
        self.zone_info = self.client.get_zone(self.zone)

    @property
    def state(self):
        if not self.client.connected:
            return STATE_UNAVAILABLE
        if self.zone_info is None:
            return STATE_UNKNOWN
        return STATE_ON if self.zone_info.power else STATE_OFF

    @property
    def available(self) -> bool:
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

    async def async_set_volume_level(self, volume: float):
        converted_volume = int(volume * HtdConstants.MAX_VOLUME)
        _LOGGER.debug(
            "Setting volume for zone %d: normalized=%.2f, raw=%d",
            self.zone,
            volume,
            converted_volume,
        )
        await self.client.async_set_volume(self.zone, converted_volume)

    async def async_volume_up(self) -> None:
        _LOGGER.debug("Zone %d volume up requested", self.zone)
        await self.client.async_volume_up(self.zone)

    async def async_volume_down(self) -> None:
        _LOGGER.debug("Zone %d volume down requested", self.zone)
        await self.client.async_volume_down(self.zone)

    # --- Power controls ---
    async def async_turn_on(self):
        _LOGGER.debug("Zone %d turn_on requested", self.zone)
        await self.client.async_power_on(self.zone)

    async def async_turn_off(self):
        _LOGGER.debug("Zone %d turn_off requested", self.zone)
        await self.client.async_power_off(self.zone)

    # --- Mute controls ---
    @property
    def is_volume_muted(self) -> bool | None:
        if not self.zone_info:
            return None
        return self.zone_info.mute

    async def async_mute_volume(self, mute: bool):
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
    def source_list(self):
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
    def media_title(self):
        return self.source

    async def async_select_source(self, source: str):
        """Allow selecting source by friendly name or raw string."""
        for source_id in range(1, len(self.sources) + 1):
            friendly_name = self.sources_map.get(
                source_id,
                GENERIC_SOURCE_NAMES.get(source_id, f"Source {source_id}")
            )
            if friendly_name and friendly_name.lower().strip() == source.lower().strip():
                _LOGGER.debug("Zone %d select_source requested: %s (id=%d)", self.zone, friendly_name, source_id)