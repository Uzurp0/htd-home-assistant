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
        # Try JSON first
        parsed = json.loads(option_value)
        return {int(k): str(v) for k, v in parsed.items()}
    except Exception:
        # Fallback: comma-separated like "1=Kitchen,2=Outside"
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

    # Parse friendly names from options
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
    should_poll = False

    unique_id: str = None
    device_name: str = None
    client: BaseClient = None
    sources: [str] = None
    zone: int = None
    changing_volume: int | None = None
    zone_info: ZoneDetail = None
    zones_map: dict[int, str] = None
    sources_map: dict[int, str] = None

    def __init__(
        self,
        unique_id,
        device_name,
        zone,
        sources,
        client,
        mappings
    ):
        self.unique_id = f"{unique_id}_{zone:02}"
        self.device_name = device_name
        self.zone = zone
        self.client = client
        self.sources = sources
        self.zones_map = mappings.get("zones", {})
        self.sources_map = mappings.get("sources", {})
        zone_fmt = f"02" if self.client.model["zones"] > 10 else "01"
        self.entity_id = get_media_player_entity_id(device_name, zone, zone_fmt)

    @property
    def enabled(self) -> bool:
        return self.zone_info is not None and self.zone_info.enabled

    @property
    def supported_features(self):
        return SUPPORT_HTD

    @property
    def name(self):
        """Return friendly zone name if available, hide if 'Unused'."""
        name = self.zones_map.get(
            self.zone,
            GENERIC_ZONE_NAMES.get(self.zone, f"Zone {self.zone} ({self.device_name})")
        )
        if not name or name.lower() == "unused":
            return None  # Hidden until renamed
        return name

    def update(self):
        self.zone_info = self.client.get_zone(self.zone)

    @property
    def state(self):
        if not self.client.connected:
            return STATE_UNAVAILABLE
        if self.zone_info is None:
            return STATE_UNKNOWN
        if self.zone_info.power:
            return STATE_ON
        return STATE_OFF

    @property
    def volume_step(self) -> float:
        return 1 / HtdConstants.MAX_VOLUME

    async def async_volume_up(self) -> None:
        await self.client.async_volume_up(self.zone)

    async def async_volume_down(self) -> None:
        await self.client.async_volume_down(self.zone)

    async def async_turn_on(self):
        await self.client.async_power_on(self.zone)

    async def async_turn_off(self):
        await self.client.async_power_off(self.zone)

    @property
    def volume_level(self) -> float:
        return self.zone_info.volume / HtdConstants.MAX_VOLUME

    @property
    def available(self) -> bool:
        return self.client.ready and self.zone_info is not None

    async def async_set_volume_level(self, volume: float):
        converted_volume = int(volume * HtdConstants.MAX_VOLUME)
        _LOGGER.info("setting new volume for zone %d to %f, raw htd = %d" % (self.zone, volume, converted_volume))
        await self.client.async_set_volume(self.zone, converted_volume)

    @property
    def is_volume_muted(self) -> bool:
        return self.zone_info.mute

    async def async_mute_volume(self, mute):
        if mute:
            await self.client.async_mute(self.zone)
        else:
            await self.client.async_unmute(self.zone)

    @property
    def source(self) -> str:
        """Return friendly source name if available, hide if 'Unused'."""
        name = self.sources_map.get(
            self.zone_info.source,
            GENERIC_SOURCE_NAMES.get(self.zone_info.source, f"Source {self.zone_info.source}")
        )
        if not name or name.lower() == "unused":
            return None
        return name

    @property
    def source_list(self):
        """Return the list of available sources with friendly names.
        - Only include sources that have a name assigned.
        - Skip any sources explicitly marked 'Unused'.
        """
        source_list = []
        for i in range(len(self.sources)):
            source_id = i + 1
            name = self.sources_map.get(
                source_id,
                GENERIC_SOURCE_NAMES.get(source_id, f"Source {source_id}")
            )
            if not name or name.lower() == "unused":
                continue
            source_list.append(name)
        return source_list

    @property
    def media_title(self):
        return self.source

    async def async_select_source(self, source: int):
        source_index = self.sources.index(source)
        await self.client.async_set_source(self.zone, source_index + 1)

    @property
    def icon(self):
        return "mdi:disc-player"

    async def async_added_to_hass(self):
        await self.client.async_subscribe(self._do_update)
        self.client.refresh()

    async def async_will_remove_from_hass(self):
        await self.client.async_unsubscribe(self._do_update)