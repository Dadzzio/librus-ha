"""Synchroniczny klient gateway API Librusa (wołany w executorze HA).

Logowanie i odświeżanie tokenu OAuth bierzemy z librus-apix, a dane czytamy
bezpośrednio z https://synergia.librus.pl/gateway/api/2.0/ (JSON).
"""

from __future__ import annotations

import logging
import re
import time
from typing import Any

import requests
from librus_apix.client import Client, new_client
from librus_apix.exceptions import AuthorizationError, MaintananceError

_LOGGER = logging.getLogger(__name__)

GATEWAY = "https://synergia.librus.pl/gateway/api/2.0/"

# klucz w wyniku -> (ścieżka w API, obowiązkowy, stały)
# obowiązkowe przerywają odświeżenie przy błędzie; stałe pobieramy raz na dobę
ZASOBY: dict[str, tuple[str, bool, bool]] = {
    "attendances": ("Attendances", True, False),
    "grades": ("Grades", False, False),
    "attendance_types": ("Attendances/Types", False, True),
    "lessons": ("Lessons", True, True),
    "subjects": ("Subjects", True, True),
    "grade_categories": ("Grades/Categories", False, True),
    "me": ("Me", False, True),
    "classes": ("Classes", False, True),
    "free_days": ("SchoolFreeDays", False, True),
}
CZAS_STALYCH = 24 * 3600  # s


class LibrusBlad(Exception):
    """Librus nie odpowiada poprawnie (sieć, przerwa techniczna, zła odpowiedź)."""


class LibrusBladLogowania(LibrusBlad):
    """Zły login lub hasło."""


class LibrusLimit(LibrusBlad):
    """Librus ogranicza liczbę zapytań (HTTP 429/503 albo blokada logowania)."""

    def __init__(self, tekst: str, ponow_za: int | None = None) -> None:
        super().__init__(tekst)
        self.ponow_za = ponow_za


class _BrakDostepu(LibrusBlad):
    """Zasób zwraca 401/403 mimo świeżego logowania – konto nie ma do niego dostępu."""


_LIMIT = re.compile(r"spr[oó]buj|wyst[aą]pi[lł] b[lł][aą]d|pr[oó]b|limit|zablok|blokad|captcha|p[oó][zź]niej|too many|later", re.I)
_ZLE_HASLO = re.compile(r"nieprawid|b[lł][eę]dn|niepoprawn|incorrect|invalid|wrong", re.I)


def _blad_logowania(tekst: str) -> LibrusBlad:
    """Tylko jawnie złe hasło uruchamia ponowne logowanie w HA; reszta to błąd chwilowy."""
    if _LIMIT.search(tekst):
        return LibrusLimit(f"Librus blokuje logowanie: {tekst}")
    if _ZLE_HASLO.search(tekst):
        return LibrusBladLogowania(tekst)
    return LibrusBlad(f"Logowanie nie powiodło się: {tekst}")


def _ponow_za(odp: requests.Response) -> int | None:
    try:
        return int(odp.headers.get("Retry-After", ""))
    except ValueError:
        return None


class LibrusApi:
    def __init__(self, login: str, haslo: str) -> None:
        self._login = login
        self._haslo = haslo
        self._client: Client | None = None
        self._zalogowano = 0.0
        self._stale: dict[str, tuple[float, Any]] = {}

    def zaloguj(self) -> None:
        client = new_client()
        try:
            client.get_token(self._login, self._haslo)
        except AuthorizationError as ex:
            raise _blad_logowania(str(ex)) from ex
        except MaintananceError as ex:
            raise LibrusBlad(f"Przerwa techniczna Librusa: {ex}") from ex
        except (requests.RequestException, ValueError, KeyError) as ex:
            # np. strona z captchą / blokadą zamiast JSON-a
            raise LibrusBlad(f"Logowanie nie powiodło się: {ex!r}"[:300]) from ex
        self._client = client
        self._zalogowano = time.monotonic()
        self._odswiez_oauth()

    def _odswiez_oauth(self) -> None:
        assert self._client is not None
        try:
            oauth = self._client.refresh_oauth()
        except AuthorizationError as ex:
            raise LibrusBlad(f"Nie udało się odświeżyć tokenu OAuth: {ex}") from ex
        jar = self._client.cookies
        for c in [c for c in jar if c.name == "oauth_token"]:
            jar.clear(c.domain, c.path, c.name)
        jar.set("oauth_token", oauth, domain="synergia.librus.pl", path="/")

    def pobierz(self, sciezka: str) -> dict[str, Any]:
        """GET z gateway API.

        Przy 401: raz nowy OAuth, potem najwyżej jedno nowe logowanie. Jeśli zasób
        dalej odmawia po świeżym logowaniu, to brak dostępu (nie logujemy w kółko –
        seria logowań to najprostsza droga do blokady po stronie Librusa).
        """
        if self._client is None:
            self.zaloguj()
        for proba in range(3):
            assert self._client is not None
            try:
                odp = self._client.get(GATEWAY + sciezka)
            except requests.RequestException as ex:
                raise LibrusBlad(f"{sciezka}: {ex}") from ex
            if odp.status_code in (429, 503):
                raise LibrusLimit(
                    f"{sciezka}: HTTP {odp.status_code} (limit zapytań)", _ponow_za(odp)
                )
            if odp.status_code in (401, 403):
                _LOGGER.debug("%s: HTTP %s, próba %d", sciezka, odp.status_code, proba + 1)
                swieze = time.monotonic() - self._zalogowano < 60
                if proba == 2 or (proba > 0 and swieze):
                    raise _BrakDostepu(f"{sciezka}: HTTP {odp.status_code} {odp.text[:200]}")
                if proba == 0:
                    try:
                        self._odswiez_oauth()
                        continue
                    except LibrusBlad:
                        pass
                if swieze:
                    raise _BrakDostepu(f"{sciezka}: HTTP {odp.status_code} {odp.text[:200]}")
                self.zaloguj()
                continue
            if odp.status_code >= 400:
                raise LibrusBlad(f"{sciezka}: HTTP {odp.status_code} {odp.text[:200]}")
            try:
                return odp.json()
            except ValueError as ex:
                raise LibrusBlad(f"{sciezka}: odpowiedź nie jest JSON-em") from ex
        raise LibrusBlad(f"{sciezka}: brak autoryzacji mimo ponownego logowania")

    def pobierz_wszystko(self) -> dict[str, Any]:
        dane: dict[str, Any] = {}
        teraz = time.monotonic()
        for klucz, (sciezka, wymagane, staly) in ZASOBY.items():
            if staly and klucz in self._stale and teraz - self._stale[klucz][0] < CZAS_STALYCH:
                dane[klucz] = self._stale[klucz][1]
                continue
            try:
                dane[klucz] = self.pobierz(sciezka)
            except (LibrusBladLogowania, LibrusLimit):
                raise
            except LibrusBlad as ex:
                if wymagane:
                    raise
                _LOGGER.warning("Librus: pomijam %s (%s)", sciezka, ex)
                dane[klucz] = None
                if not isinstance(ex, _BrakDostepu):
                    continue
            if staly:
                # także brak dostępu zapamiętujemy na dobę, żeby nie pytać co kwadrans
                self._stale[klucz] = (teraz, dane[klucz])
        return dane

    def wyczysc_stale(self) -> None:
        self._stale.clear()
