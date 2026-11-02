# Librus HA

Integracja Home Assistanta z Librus Synergia: **dokładna frekwencja per przedmiot** i **średnie ważone ocen**.

Logowanie i token OAuth bierze z biblioteki [librus-apix](https://github.com/RustySnek/librus-apix),
a dane czyta wprost z gateway API Librusa (`/gateway/api/2.0/`): `Attendances`, `Attendances/Types`,
`Lessons`, `Subjects`, `Grades`, `Grades/Categories`, `Me`. Każdy wpis frekwencji ma lekcję,
a lekcja przedmiot – dlatego procent per przedmiot jest liczony z prawdziwej liczby lekcji, nie szacowany.

## Instalacja (HACS)

1. HACS → ⋮ → **Custom repositories** → `https://github.com/Dadzzio/librus-ha`, kategoria **Integration**.
2. Znajdź **Librus HA** → **Download** → restart HA.
3. **Settings → Devices & services → Add integration → Librus HA** → login i hasło do Synergii.

Hasło zostaje w konfiguracji HA (`.storage/core.config_entries`), nie ma go w repo.

## Encje (urządzenie „Szkoła”)

| Encja | Stan | Najważniejsze atrybuty |
|---|---|---|
| `sensor.szkola_frekwencja` | % obecności w bieżącym semestrze | `lekcji`, `obecnosci`, `nieobecnosci`, `nieusprawiedliwione`, `usprawiedliwione`, `zwolnienia`, `spoznienia`, `procent_bez_zwolnien`, `zapas_do_50`, `procent_rok`, `przedmioty` (tabela), `ostatnie_wpisy` |
| `sensor.szkola_frekwencja_<przedmiot>` | % obecności z przedmiotu | jak wyżej + `ostatnie_wpisy` z przedmiotu |
| `sensor.szkola_srednia` | średnia ze średnich przedmiotów | `przedmioty` |
| `button.szkola_odswiez` | przycisk: od razu pobiera dane z Librusa | – |
| `sensor.szkola_srednia_<przedmiot>` | średnia ważona z przedmiotu | `oceny_tekst`, `oceny` (ocena, waga, kategoria, data), `srednia_rok`, `proponowana_semestralna`, `semestralna`, `proponowana_roczna`, `roczna` |

**Zasady liczenia**
- Obecność = typy, które Librus oznacza jako obecność (`IsPresenceKind`): obecność, spóźnienie, wycieczka… oraz zawsze zwolnienie (`zw`), bo szkoła liczy je jako obecność.
- `procent_bez_zwolnien` to procent z lekcji bez zwolnień (zwolnienia pominięte w liczniku i mianowniku).
- `zapas_do_50` > 0: tyle lekcji z rzędu można opuścić i zostać ≥ 50%; < 0: tyle obecności z rzędu brakuje do 50%.
- Średnia ważona tylko z ocen 1–6 z kategorii liczonych do średniej; `+` = +0,5, `-` = −0,25 (zmienisz w opcjach).

## Zdarzenia (do automatyzacji)

- `librus_ha_nowy_wpis_frekwencji` – nowa nieobecność / spóźnienie / zwolnienie: `data`, `lekcja`, `przedmiot`, `skrot`, `typ`.
- `librus_ha_nowa_ocena` – nowa ocena: `przedmiot`, `ocena`, `waga`, `kategoria`, `data`.

Przy pierwszym uruchomieniu integracja tylko zapamiętuje istniejące wpisy (bez zalewu zdarzeń).

```yaml
triggers:
  - trigger: event
    event_type: librus_ha_nowy_wpis_frekwencji
actions:
  - action: notify.mobile_app_szymons_iphone
    data:
      title: "Librus: {{ trigger.event.data.typ }}"
      message: "{{ trigger.event.data.data }}, lekcja {{ trigger.event.data.lekcja }}: {{ trigger.event.data.przedmiot }}"
```

## Opcje

Settings → Devices & services → Librus HA → **Configure**: odpytywanie w dni robocze 7–17 (domyślnie 15 min)
i w pozostałym czasie (120 min), wartość plusa i minusa.

## Testy

```sh
python -m unittest discover -v tests
```

Integracja jest nieoficjalna – korzysta z prywatnego API Librusa.
