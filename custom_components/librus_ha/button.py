"""Przycisk ręcznego odświeżenia danych z Librusa."""

from __future__ import annotations

from homeassistant.components.button import ButtonEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import LibrusConfigEntry
from .coordinator import LibrusKoordynator
from .entity import LibrusEncja


async def async_setup_entry(
    hass: HomeAssistant, entry: LibrusConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    async_add_entities([LibrusOdswiez(entry.runtime_data)])


class LibrusOdswiez(LibrusEncja, ButtonEntity):
    _attr_name = "Odśwież"
    _attr_icon = "mdi:refresh"

    def __init__(self, koordynator: LibrusKoordynator) -> None:
        super().__init__(koordynator, "odswiez")

    @property
    def available(self) -> bool:
        # przycisk działa też wtedy, gdy ostatnie odświeżenie się nie udało
        return True

    async def async_press(self) -> None:
        await self.coordinator.async_refresh()
