"""Sensory: frekwencja i średnie – ogółem i per przedmiot."""

from __future__ import annotations

from typing import Any

from homeassistant.components.sensor import SensorEntity, SensorStateClass
from homeassistant.const import PERCENTAGE
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import LibrusConfigEntry
from .coordinator import LibrusKoordynator
from .entity import LibrusEncja

POLA_FREKWENCJI = (
    "lekcji",
    "obecnosci",
    "nieobecnosci",
    "nieusprawiedliwione",
    "usprawiedliwione",
    "zwolnienia",
    "spoznienia",
    "procent_bez_zwolnien",
    "zapas_do_50",
)


async def async_setup_entry(
    hass: HomeAssistant, entry: LibrusConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    koordynator = entry.runtime_data
    async_add_entities(
        [LibrusFrekwencja(koordynator), LibrusSrednia(koordynator)]
    )
    znane_frek: set[str] = set()
    znane_oceny: set[str] = set()

    @callback
    def _dodaj_przedmioty() -> None:
        dane = koordynator.data or {}
        nowe: list[SensorEntity] = []
        for klucz in dane.get("frekwencja", {}).get("przedmioty", {}):
            if klucz not in znane_frek:
                znane_frek.add(klucz)
                nowe.append(LibrusFrekwencjaPrzedmiotu(koordynator, klucz))
        for klucz in dane.get("oceny", {}):
            if klucz not in znane_oceny:
                znane_oceny.add(klucz)
                nowe.append(LibrusSredniaPrzedmiotu(koordynator, klucz))
        if nowe:
            async_add_entities(nowe)

    _dodaj_przedmioty()
    entry.async_on_unload(koordynator.async_add_listener(_dodaj_przedmioty))


class LibrusFrekwencja(LibrusEncja, SensorEntity):
    _attr_name = "Frekwencja"
    _attr_icon = "mdi:account-check"
    _attr_native_unit_of_measurement = PERCENTAGE
    _attr_state_class = SensorStateClass.MEASUREMENT
    _unrecorded_attributes = frozenset({"przedmioty", "ostatnie_wpisy"})

    def __init__(self, koordynator: LibrusKoordynator) -> None:
        super().__init__(koordynator, "frekwencja")

    @property
    def _frek(self) -> dict[str, Any]:
        return (self.coordinator.data or {}).get("frekwencja", {})

    @property
    def native_value(self) -> float | None:
        return self._frek.get("razem", {}).get("procent")

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        f = self._frek
        razem = f.get("razem", {})
        przedmioty = sorted(
            (
                {"przedmiot": p["nazwa"], "procent": p["procent"], **{k: p[k] for k in POLA_FREKWENCJI}}
                for p in f.get("przedmioty", {}).values()
            ),
            key=lambda p: p["procent"] if p["procent"] is not None else 101,
        )
        return {
            "semestr": f.get("semestr"),
            **{k: razem.get(k) for k in POLA_FREKWENCJI},
            "procent_rok": f.get("rok", {}).get("procent"),
            "przedmioty": przedmioty,
            "ostatnie_wpisy": f.get("wpisy", [])[:15],
            "aktualizacja": (self.coordinator.data or {}).get("aktualizacja"),
        }


class LibrusFrekwencjaPrzedmiotu(LibrusEncja, SensorEntity):
    _attr_icon = "mdi:book-account"
    _attr_native_unit_of_measurement = PERCENTAGE
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, koordynator: LibrusKoordynator, przedmiot: str) -> None:
        super().__init__(koordynator, f"frekwencja_{przedmiot}")
        self._przedmiot = przedmiot
        self._attr_name = f"Frekwencja {self._p.get('nazwa', przedmiot)}"

    @property
    def _p(self) -> dict[str, Any]:
        return (
            (self.coordinator.data or {})
            .get("frekwencja", {})
            .get("przedmioty", {})
            .get(self._przedmiot, {})
        )

    @property
    def available(self) -> bool:
        return super().available and bool(self._p)

    @property
    def native_value(self) -> float | None:
        return self._p.get("procent")

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        p = self._p
        wpisy = [
            w
            for w in (self.coordinator.data or {}).get("frekwencja", {}).get("wpisy", [])
            if w["przedmiot"] == p.get("nazwa")
        ]
        return {
            "przedmiot": p.get("nazwa"),
            **{k: p.get(k) for k in POLA_FREKWENCJI},
            "ostatnie_wpisy": wpisy[:10],
        }


class LibrusSrednia(LibrusEncja, SensorEntity):
    _attr_name = "Średnia"
    _attr_icon = "mdi:school"
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_suggested_display_precision = 2

    def __init__(self, koordynator: LibrusKoordynator) -> None:
        super().__init__(koordynator, "srednia")

    @property
    def available(self) -> bool:
        return super().available and bool((self.coordinator.data or {}).get("oceny_dostepne"))

    @property
    def native_value(self) -> float | None:
        return (self.coordinator.data or {}).get("srednia")

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        oceny = (self.coordinator.data or {}).get("oceny", {})
        return {
            "przedmioty": {p["nazwa"]: p["srednia"] for p in oceny.values()},
        }


class LibrusSredniaPrzedmiotu(LibrusEncja, SensorEntity):
    _attr_icon = "mdi:numeric"
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_suggested_display_precision = 2
    _unrecorded_attributes = frozenset({"oceny"})

    def __init__(self, koordynator: LibrusKoordynator, przedmiot: str) -> None:
        super().__init__(koordynator, f"srednia_{przedmiot}")
        self._przedmiot = przedmiot
        self._attr_name = f"Średnia {self._p.get('nazwa', przedmiot)}"

    @property
    def _p(self) -> dict[str, Any]:
        return (self.coordinator.data or {}).get("oceny", {}).get(self._przedmiot, {})

    @property
    def available(self) -> bool:
        return super().available and bool(self._p)

    @property
    def native_value(self) -> float | None:
        return self._p.get("srednia")

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        p = self._p
        return {
            "przedmiot": p.get("nazwa"),
            "oceny_tekst": ", ".join(o["ocena"] for o in p.get("oceny", [])),
            "oceny": [
                {k: o[k] for k in ("ocena", "waga", "kategoria", "data", "liczona")}
                for o in p.get("oceny", [])
            ],
            "srednia_rok": p.get("srednia_rok"),
            "proponowana_semestralna": p.get("proponowana_semestralna"),
            "semestralna": p.get("semestralna"),
            "proponowana_roczna": p.get("proponowana_roczna"),
            "roczna": p.get("roczna"),
        }
