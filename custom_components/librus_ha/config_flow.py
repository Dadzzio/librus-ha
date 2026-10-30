"""Konfiguracja w UI: login i hasło do Librus Synergia, opcje odpytywania i ocen."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import voluptuous as vol
from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import callback

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
)

SCHEMAT = vol.Schema({vol.Required(CONF_USERNAME): str, vol.Required(CONF_PASSWORD): str})


def _sprawdz(login: str, haslo: str) -> None:
    api = LibrusApi(login, haslo)
    api.zaloguj()
    api.pobierz("Attendances")


class LibrusConfigFlow(ConfigFlow, domain=DOMAIN):
    VERSION = 1

    async def _waliduj(self, dane: dict[str, Any]) -> dict[str, str]:
        try:
            await self.hass.async_add_executor_job(
                _sprawdz, dane[CONF_USERNAME], dane[CONF_PASSWORD]
            )
        except LibrusBladLogowania:
            return {"base": "invalid_auth"}
        except LibrusBlad:
            return {"base": "cannot_connect"}
        return {}

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        bledy: dict[str, str] = {}
        if user_input is not None:
            await self.async_set_unique_id(user_input[CONF_USERNAME].lower())
            self._abort_if_unique_id_configured()
            bledy = await self._waliduj(user_input)
            if not bledy:
                return self.async_create_entry(
                    title=f"Librus ({user_input[CONF_USERNAME]})", data=user_input
                )
        return self.async_show_form(step_id="user", data_schema=SCHEMAT, errors=bledy)

    async def async_step_reauth(self, entry_data: Mapping[str, Any]) -> ConfigFlowResult:
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        wpis = self._get_reauth_entry()
        bledy: dict[str, str] = {}
        if user_input is not None:
            dane = {CONF_USERNAME: wpis.data[CONF_USERNAME], **user_input}
            bledy = await self._waliduj(dane)
            if not bledy:
                return self.async_update_reload_and_abort(wpis, data=dane)
        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=vol.Schema({vol.Required(CONF_PASSWORD): str}),
            description_placeholders={"login": wpis.data[CONF_USERNAME]},
            errors=bledy,
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        return LibrusOptionsFlow()


class LibrusOptionsFlow(OptionsFlow):
    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if user_input is not None:
            return self.async_create_entry(data=user_input)
        o = self.config_entry.options
        schemat = vol.Schema(
            {
                vol.Required(
                    CONF_INTERWAL_DZIEN, default=o.get(CONF_INTERWAL_DZIEN, DOMYSLNY_INTERWAL_DZIEN)
                ): vol.All(vol.Coerce(int), vol.Range(min=5, max=240)),
                vol.Required(
                    CONF_INTERWAL_NOC, default=o.get(CONF_INTERWAL_NOC, DOMYSLNY_INTERWAL_NOC)
                ): vol.All(vol.Coerce(int), vol.Range(min=15, max=720)),
                vol.Required(CONF_PLUS, default=o.get(CONF_PLUS, DOMYSLNY_PLUS)): vol.All(
                    vol.Coerce(float), vol.Range(min=0, max=1)
                ),
                vol.Required(CONF_MINUS, default=o.get(CONF_MINUS, DOMYSLNY_MINUS)): vol.All(
                    vol.Coerce(float), vol.Range(min=0, max=1)
                ),
            }
        )
        return self.async_show_form(step_id="init", data_schema=schemat)
