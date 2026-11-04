"""Koordynator: odpytuje Librusa, liczy frekwencję i oceny, wysyła zdarzenia o nowościach."""

from __future__ import annotations

import logging
from datetime import timedelta
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.storage import Store
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from . import obliczenia
from .api import LibrusApi, LibrusBlad, LibrusBladLogowania
from .const import (
    CONF_INTERWAL_DZIEN,
    CONF_INTERWAL_NOC,
    CONF_MINUS,
    CONF_PLUS,
    DOMAIN,
    DOMYSLNY_INTERWAL_DZIEN,
    DOMYSLNY_INTERWAL_NOC,
    DOMYSLNY_MINUS,
    DOMYSLNY_PLUS,
    ZDARZENIE_FREKWENCJA,
    ZDARZENIE_OCENA,
)

_LOGGER = logging.getLogger(__name__)

WERSJA_MAGAZYNU = 1


class LibrusKoordynator(DataUpdateCoordinator[dict[str, Any]]):
    config_entry: ConfigEntry

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=DOMAIN,
            update_interval=timedelta(minutes=DOMYSLNY_INTERWAL_DZIEN),
        )
        self.api = LibrusApi(entry.data[CONF_USERNAME], entry.data[CONF_PASSWORD])
        self._magazyn: Store[dict[str, list[str]]] = Store(
            hass, WERSJA_MAGAZYNU, f"{DOMAIN}.{entry.entry_id}.widziane"
        )
        self._widziane: dict[str, set[str]] | None = None

    def _opcja(self, klucz: str, domyslna: Any) -> Any:
        return self.config_entry.options.get(klucz, domyslna)

    def _ustaw_interwal(self) -> None:
        teraz = dt_util.now()
        dzien = teraz.weekday() < 5 and 7 <= teraz.hour < 17
        minuty = (
            self._opcja(CONF_INTERWAL_DZIEN, DOMYSLNY_INTERWAL_DZIEN)
            if dzien
            else self._opcja(CONF_INTERWAL_NOC, DOMYSLNY_INTERWAL_NOC)
        )
        self.update_interval = timedelta(minutes=int(minuty))

    async def _async_update_data(self) -> dict[str, Any]:
        self._ustaw_interwal()
        try:
            surowe = await self.hass.async_add_executor_job(self.api.pobierz_wszystko)
        except LibrusBladLogowania as ex:
            raise ConfigEntryAuthFailed(str(ex)) from ex
        except LibrusBlad as ex:
            raise UpdateFailed(str(ex)) from ex

        frek = obliczenia.frekwencja(surowe)
        frek["prognoza"] = obliczenia.prognoza(surowe, frek, dt_util.now().date())
        oceny = obliczenia.oceny(
            surowe,
            semestr=frek["semestr"],
            plus=float(self._opcja(CONF_PLUS, DOMYSLNY_PLUS)),
            minus=float(self._opcja(CONF_MINUS, DOMYSLNY_MINUS)),
        )
        me = (surowe.get("me") or {}).get("Me") or {}
        uczen = me.get("User") or me.get("Account") or {}
        dane = {
            "uczen": {
                "imie": uczen.get("FirstName"),
                "nazwisko": uczen.get("LastName"),
            },
            "semestr": frek["semestr"],
            "frekwencja": frek,
            "oceny": oceny,
            "oceny_dostepne": surowe.get("grades") is not None,
            "srednia": obliczenia.srednia_ogolna(oceny),
            "aktualizacja": dt_util.now().isoformat(),
        }
        await self._zglos_nowosci(dane)
        return dane

    async def _zglos_nowosci(self, dane: dict[str, Any]) -> None:
        wpisy = {w["id"]: w for w in dane["frekwencja"]["wpisy"] if w["id"]}
        oceny = {
            o["id"]: {**o, "przedmiot": p["nazwa"]}
            for p in dane["oceny"].values()
            for o in p["oceny"]
            if o["id"]
        }

        if self._widziane is None:
            zapisane = await self._magazyn.async_load()
            if zapisane is None:
                # pierwsze uruchomienie: zapamiętaj stan bez zasypywania zdarzeniami
                self._widziane = {"frekwencja": set(wpisy), "oceny": set(oceny)}
                await self._zapisz()
                return
            self._widziane = {k: set(v) for k, v in zapisane.items()}

        nowe_wpisy = [w for i, w in wpisy.items() if i not in self._widziane["frekwencja"]]
        nowe_oceny = [o for i, o in oceny.items() if i not in self._widziane["oceny"]]
        for w in sorted(nowe_wpisy, key=lambda w: (w["data"] or "", int(w["lekcja"] or 0))):
            self.hass.bus.async_fire(ZDARZENIE_FREKWENCJA, w)
        for o in sorted(nowe_oceny, key=lambda o: o["dodano"] or ""):
            self.hass.bus.async_fire(ZDARZENIE_OCENA, o)
        if nowe_wpisy or nowe_oceny:
            self._widziane["frekwencja"] |= set(wpisy)
            self._widziane["oceny"] |= set(oceny)
            await self._zapisz()

    async def _zapisz(self) -> None:
        assert self._widziane is not None
        await self._magazyn.async_save({k: sorted(v) for k, v in self._widziane.items()})
