"""Stałe integracji Librus HA."""

DOMAIN = "librus_ha"

CONF_INTERWAL_DZIEN = "interwal_dzien"
CONF_INTERWAL_NOC = "interwal_noc"
CONF_PLUS = "plus"
CONF_MINUS = "minus"

DOMYSLNY_INTERWAL_DZIEN = 15  # min, dni robocze 7:00–17:00
DOMYSLNY_INTERWAL_NOC = 120  # min, pozostały czas
DOMYSLNY_PLUS = 0.5
DOMYSLNY_MINUS = 0.25

ZDARZENIE_FREKWENCJA = f"{DOMAIN}_nowy_wpis_frekwencji"
ZDARZENIE_OCENA = f"{DOMAIN}_nowa_ocena"
