"""Synchroniczny klient gateway API Librusa (wołany w executorze HA).

Logowanie i odświeżanie tokenu OAuth bierzemy z librus-apix, a dane czytamy
bezpośrednio z https://synergia.librus.pl/gateway/api/2.0/ (JSON).
"""

from __future__ import annotations

import logging
from typing import Any

import requests
from librus_apix.client import Client, new_client
from librus_apix.exceptions import AuthorizationError, MaintananceError

_LOGGER = logging.getLogger(__name__)

GATEWAY = "https://synergia.librus.pl/gateway/api/2.0/"

# klucz w wyniku -> ścieżka w API; obowiązkowe przerywają odświeżenie przy błędzie
ZASOBY: dict[str, tuple[str, bool]] = {
    "attendances": ("Attendances", True),
    "attendance_types": ("Attendances/Types", False),
    "lessons": ("Lessons", True),
    "subjects": ("Subjects", True),
    "grades": ("Grades", False),
    "grade_categories": ("Grades/Categories", False),
    "me": ("Me", False),
    "classes": ("Classes", False),
    "free_days": ("SchoolFreeDays", False),
}


class LibrusBlad(Exception):
    """Librus nie odpowiada poprawnie (sieć, przerwa techniczna, zła odpowiedź)."""


class LibrusBladLogowania(LibrusBlad):
    """Zły login lub hasło."""


class LibrusApi:
    def __init__(self, login: str, haslo: str) -> None:
        self._login = login
        self._haslo = haslo
        self._client: Client | None = None

    def zaloguj(self) -> None:
        client = new_client()
        try:
            client.get_token(self._login, self._haslo)
        except AuthorizationError as ex:
            raise LibrusBladLogowania(str(ex)) from ex
        except MaintananceError as ex:
            raise LibrusBlad(f"Przerwa techniczna Librusa: {ex}") from ex
        except (requests.RequestException, ValueError, KeyError) as ex:
            raise LibrusBlad(f"Logowanie nie powiodło się: {ex}") from ex
        self._client = client
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
        """GET z gateway API; przy 401 najpierw nowy OAuth, potem nowe logowanie."""
        if self._client is None:
            self.zaloguj()
        for proba in range(3):
            assert self._client is not None
            try:
                odp = self._client.get(GATEWAY + sciezka)
            except requests.RequestException as ex:
                raise LibrusBlad(f"{sciezka}: {ex}") from ex
            if odp.status_code == 401:
                _LOGGER.debug("%s: 401, próba %d", sciezka, proba + 1)
                try:
                    if proba == 0:
                        self._odswiez_oauth()
                    else:
                        self.zaloguj()
                except LibrusBladLogowania:
                    raise
                except LibrusBlad:
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
        for klucz, (sciezka, wymagane) in ZASOBY.items():
            try:
                dane[klucz] = self.pobierz(sciezka)
            except LibrusBladLogowania:
                raise
            except LibrusBlad as ex:
                if wymagane:
                    raise
                _LOGGER.warning("Librus: pomijam %s (%s)", sciezka, ex)
                dane[klucz] = None
        return dane
