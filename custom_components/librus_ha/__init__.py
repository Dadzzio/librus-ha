"""Librus HA – frekwencja i oceny z Librus Synergia."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant

from .coordinator import LibrusKoordynator

PLATFORMS = [Platform.SENSOR]

type LibrusConfigEntry = ConfigEntry[LibrusKoordynator]


async def async_setup_entry(hass: HomeAssistant, entry: LibrusConfigEntry) -> bool:
    koordynator = LibrusKoordynator(hass, entry)
    await koordynator.async_config_entry_first_refresh()
    entry.runtime_data = koordynator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_przeladuj))
    return True


async def _przeladuj(hass: HomeAssistant, entry: LibrusConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: LibrusConfigEntry) -> bool:
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def async_remove_entry(hass: HomeAssistant, entry: LibrusConfigEntry) -> None:
    from homeassistant.helpers.storage import Store

    from .const import DOMAIN

    await Store(hass, 1, f"{DOMAIN}.{entry.entry_id}.widziane").async_remove()
