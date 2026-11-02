"""Wspólna baza encji: urządzenie „Szkoła” i unique_id."""

from __future__ import annotations

from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import LibrusKoordynator


class LibrusEncja(CoordinatorEntity[LibrusKoordynator]):
    _attr_has_entity_name = True

    def __init__(self, koordynator: LibrusKoordynator, klucz: str) -> None:
        super().__init__(koordynator)
        entry = koordynator.config_entry
        self._attr_unique_id = f"{entry.entry_id}_{klucz}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name="Szkoła",
            manufacturer="Librus Synergia",
            entry_type=DeviceEntryType.SERVICE,
        )
