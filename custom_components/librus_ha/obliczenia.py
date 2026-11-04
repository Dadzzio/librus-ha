"""Obliczenia na surowych danych z gateway API Librusa (bez zależności od HA).

Wejście to słowniki zwrócone przez LibrusApi.pobierz_wszystko(), np.
{"attendances": {"Attendances": [...]}, "lessons": {"Lessons": [...]}, ...}.
"""

from __future__ import annotations

import math
import re
import unicodedata
from datetime import date, timedelta
from typing import Any

# Gdy Attendances/Types jest niedostępne – typy standardowe Librusa.
TYPY_DOMYSLNE: dict[str, dict[str, Any]] = {
    "1": {"skrot": "nb", "nazwa": "nieobecność", "obecnosc": False},
    "2": {"skrot": "sp", "nazwa": "spóźnienie", "obecnosc": True},
    "3": {"skrot": "u", "nazwa": "nieobecność uspr.", "obecnosc": False},
    "4": {"skrot": "zw", "nazwa": "zwolnienie", "obecnosc": True},
    "100": {"skrot": "ob", "nazwa": "obecność", "obecnosc": True},
    "1266": {"skrot": "wy", "nazwa": "wycieczka", "obecnosc": True},
}

NIEZNANY_PRZEDMIOT = "Nieznany przedmiot"


def slug(tekst: str) -> str:
    """'Język polski' -> 'jezyk_polski'."""
    tekst = tekst.replace("ł", "l").replace("Ł", "L")
    tekst = unicodedata.normalize("NFKD", tekst).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "_", tekst.lower()).strip("_") or "brak"


def _id(obj: Any) -> str | None:
    """Id z obiektu {'Id': 5, 'Url': ...} albo z samej wartości."""
    if isinstance(obj, dict):
        obj = obj.get("Id")
    return None if obj is None else str(obj)


def _lista(dane: dict | None, klucz: str) -> list[dict]:
    if not isinstance(dane, dict):
        return []
    wartosc = dane.get(klucz)
    return wartosc if isinstance(wartosc, list) else []


def przedmioty(dane: dict) -> dict[str, str]:
    """Id przedmiotu -> nazwa."""
    return {
        str(s["Id"]): (s.get("Name") or "").strip() or NIEZNANY_PRZEDMIOT
        for s in _lista(dane.get("subjects"), "Subjects")
        if "Id" in s
    }


def lekcje_przedmiotow(dane: dict) -> dict[str, str]:
    """Id lekcji (przydział nauczyciel–przedmiot–klasa) -> Id przedmiotu."""
    return {
        str(l["Id"]): _id(l.get("Subject"))
        for l in _lista(dane.get("lessons"), "Lessons")
        if "Id" in l and _id(l.get("Subject"))
    }


def typy_frekwencji(dane: dict) -> dict[str, dict[str, Any]]:
    typy = dict(TYPY_DOMYSLNE)
    for t in _lista(dane.get("attendance_types"), "Types"):
        if "Id" not in t:
            continue
        skrot = (t.get("Short") or "").strip().lower()
        obecnosc = t.get("IsPresenceKind")
        if obecnosc is None:
            obecnosc = skrot in ("ob", "sp", "wy", "zw")
        if skrot == "zw":
            # w szkole zwolnienie liczy się jako obecność na lekcji
            obecnosc = True
        typy[str(t["Id"])] = {
            "skrot": skrot,
            "nazwa": (t.get("Name") or skrot).strip(),
            "obecnosc": bool(obecnosc),
        }
    return typy


def biezacy_semestr(dane: dict) -> int:
    semestry = [
        int(a["Semester"])
        for a in _lista(dane.get("attendances"), "Attendances")
        if str(a.get("Semester", "")).isdigit()
    ]
    return max(semestry) if semestry else 1


def _pusty_licznik() -> dict[str, Any]:
    return {
        "lekcji": 0,
        "obecnosci": 0,
        "nieusprawiedliwione": 0,
        "usprawiedliwione": 0,
        "zwolnienia": 0,
        "spoznienia": 0,
        "inne_nieobecnosci": 0,
    }


def _dodaj(licznik: dict[str, Any], typ: dict[str, Any]) -> None:
    licznik["lekcji"] += 1
    skrot = typ["skrot"]
    if typ["obecnosc"]:
        licznik["obecnosci"] += 1
        if skrot == "sp":
            licznik["spoznienia"] += 1
        elif skrot == "zw":
            licznik["zwolnienia"] += 1
    elif skrot == "nb":
        licznik["nieusprawiedliwione"] += 1
    elif skrot == "u":
        licznik["usprawiedliwione"] += 1
    else:
        licznik["inne_nieobecnosci"] += 1


def _podsumuj(licznik: dict[str, Any]) -> dict[str, Any]:
    lekcji, ob, zw = licznik["lekcji"], licznik["obecnosci"], licznik["zwolnienia"]
    wynik = dict(licznik)
    wynik["nieobecnosci"] = (
        licznik["nieusprawiedliwione"]
        + licznik["usprawiedliwione"]
        + licznik["inne_nieobecnosci"]
    )
    wynik["procent"] = round(100 * ob / lekcji, 1) if lekcji else None
    # zwolnienie liczy się jako obecność; tu procent z lekcji bez zwolnień
    wynik["procent_bez_zwolnien"] = (
        round(100 * (ob - zw) / (lekcji - zw), 1) if lekcji - zw > 0 else None
    )
    # > 0: tyle lekcji z rzędu można jeszcze opuścić i mieć >= 50%;
    # < 0: tyle obecności z rzędu brakuje do 50%
    wynik["zapas_do_50"] = 2 * ob - lekcji
    return wynik


def frekwencja(dane: dict, semestr: int | None = None) -> dict[str, Any]:
    """Frekwencja ogółem i per przedmiot dla semestru (domyślnie bieżącego) i całego roku."""
    semestr = semestr or biezacy_semestr(dane)
    typy = typy_frekwencji(dane)
    nazwy = przedmioty(dane)
    lekcje = lekcje_przedmiotow(dane)

    razem = _pusty_licznik()
    rok = _pusty_licznik()
    per_przedmiot: dict[str, dict[str, Any]] = {}
    per_przedmiot_rok: dict[str, dict[str, Any]] = {}
    # tygodnie (ISO), w których w semestrze były lekcje – do liczenia lekcji na tydzień
    tygodnie: set[tuple[int, int]] = set()
    wpisy: list[dict[str, Any]] = []

    for a in _lista(dane.get("attendances"), "Attendances"):
        typ = typy.get(_id(a.get("Type")) or "", {"skrot": "?", "nazwa": "?", "obecnosc": False})
        id_przedmiotu = lekcje.get(_id(a.get("Lesson")) or "")
        nazwa = nazwy.get(id_przedmiotu or "", NIEZNANY_PRZEDMIOT)
        klucz = slug(nazwa)
        _dodaj(rok, typ)
        _dodaj(per_przedmiot_rok.setdefault(klucz, _pusty_licznik()), typ)
        if str(a.get("Semester")) != str(semestr):
            continue
        if klucz not in per_przedmiot:
            per_przedmiot[klucz] = {"nazwa": nazwa, **_pusty_licznik()}
        _dodaj(per_przedmiot[klucz], typ)
        _dodaj(razem, typ)
        dzien = _data(a.get("Date"))
        if dzien:
            tygodnie.add(dzien.isocalendar()[:2])
        if typ["skrot"] != "ob":
            wpisy.append(
                {
                    "id": _id(a.get("Id")),
                    "data": a.get("Date"),
                    "lekcja": a.get("LessonNo"),
                    "przedmiot": nazwa,
                    "skrot": typ["skrot"],
                    "typ": typ["nazwa"],
                    "dodano": a.get("AddDate"),
                }
            )

    wpisy.sort(key=lambda w: (w["data"] or "", int(w["lekcja"] or 0)), reverse=True)
    liczba_tygodni = len(tygodnie)
    wynik_przedmioty = {}
    for k, v in per_przedmiot.items():
        nazwa = v.pop("nazwa")
        rok_p = _podsumuj(per_przedmiot_rok[k])
        wynik_przedmioty[k] = {
            "nazwa": nazwa,
            **_podsumuj(v),
            "lekcji_tygodniowo": round(v["lekcji"] / liczba_tygodni, 2) if liczba_tygodni else None,
            "rok": {x: rok_p[x] for x in ("lekcji", "obecnosci", "nieobecnosci", "procent", "zapas_do_50")},
        }
    return {
        "semestr": semestr,
        "razem": _podsumuj(razem),
        "rok": _podsumuj(rok),
        "przedmioty": wynik_przedmioty,
        "wpisy": wpisy,
    }


def _data(tekst: Any) -> date | None:
    try:
        return date.fromisoformat(str(tekst)[:10])
    except ValueError:
        return None


def _wielkanoc(rok: int) -> date:
    a, b, c = rok % 19, rok // 100, rok % 100
    d, e = b // 4, b % 4
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = c // 4, c % 4
    l = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l) // 451
    miesiac = (h + l - 7 * m + 114) // 31
    dzien = (h + l - 7 * m + 114) % 31 + 1
    return date(rok, miesiac, dzien)


def _swieta(rok: int) -> set[date]:
    """Dni ustawowo wolne w Polsce, które wypadają w roku szkolnym."""
    wielkanoc = _wielkanoc(rok)
    stale = [(1, 1), (1, 6), (5, 1), (5, 3), (11, 1), (11, 11), (12, 24), (12, 25), (12, 26)]
    return {date(rok, m, d) for m, d in stale} | {
        wielkanoc + timedelta(days=1),
        wielkanoc + timedelta(days=60),  # Boże Ciało
    }


def dni_wolne(dane: dict) -> set[date]:
    """Dni wolne szkoły z Librusa (SchoolFreeDays) – przerwy świąteczne, ferie, dni dyrektorskie."""
    wolne: set[date] = set()
    for d in _lista(dane.get("free_days"), "SchoolFreeDays"):
        od, do = _data(d.get("DateFrom")), _data(d.get("DateTo") or d.get("DateFrom"))
        if od and do:
            while od <= do:
                wolne.add(od)
                od += timedelta(days=1)
    return wolne


def _ostatni_piatek(rok: int, miesiac: int) -> date:
    d = (date(rok, miesiac + 1, 1) if miesiac < 12 else date(rok + 1, 1, 1)) - timedelta(days=1)
    while d.weekday() != 4:
        d -= timedelta(days=1)
    return d


def daty_konca(dane: dict, dzis: date) -> tuple[date, date]:
    """(koniec 1. semestru, koniec roku szkolnego) z Librusa (Classes), inaczej typowe daty."""
    rok_startu = dzis.year if dzis.month >= 9 else dzis.year - 1
    klasy = _lista(dane.get("classes"), "Classes")
    pojedyncza = (dane.get("classes") or {}).get("Class") if isinstance(dane.get("classes"), dict) else None
    if isinstance(pojedyncza, dict):
        klasy = [pojedyncza]
    id_klasy = _id((((dane.get("me") or {}).get("Me") or {}).get("Class")))
    klasa = next((k for k in klasy if _id(k.get("Id")) == id_klasy), klasy[0] if klasy else {})
    koniec_sem = _data(klasa.get("EndFirstSemester")) or _ostatni_piatek(rok_startu + 1, 1)
    koniec_roku = _data(klasa.get("EndSchoolYear")) or _ostatni_piatek(rok_startu + 1, 6)
    return koniec_sem, koniec_roku


def dni_nauki(od: date, do: date, wolne: set[date]) -> int:
    """Dni z lekcjami w przedziale (od, do] – dni robocze bez świąt i dni wolnych szkoły."""
    swieta = _swieta(od.year) | _swieta(do.year)
    dzien, licznik = od + timedelta(days=1), 0
    while dzien <= do:
        if dzien.weekday() < 5 and dzien not in swieta and dzien not in wolne:
            licznik += 1
        dzien += timedelta(days=1)
    return licznik


def _mozna_opuscic(zapas: int, pozostalo: int) -> int:
    # (obecności + pozostałe − k) / (lekcji + pozostałe) >= 50%  <=>  k <= (zapas + pozostałe) / 2
    return math.floor((zapas + pozostalo) / 2)


def prognoza(dane: dict, frek: dict[str, Any], dzis: date) -> dict[str, Any]:
    """Dopisuje do frekwencji per przedmiot: ile lekcji zostało i ile można opuścić (>= 50%)."""
    koniec_sem, koniec_roku = daty_konca(dane, dzis)
    wolne = dni_wolne(dane)
    z_librusa = bool(wolne)
    if not z_librusa:
        # brak SchoolFreeDays: przerwa świąteczna 23–31 grudnia + 2 tygodnie ferii
        # w połowie lutego (dokładne ferie zależą od województwa)
        rok = dzis.year if dzis.month >= 9 else dzis.year - 1
        wolne = {date(rok, 12, d) for d in range(23, 32)}
        ferie = date(rok + 1, 2, 2)
        wolne |= {ferie + timedelta(days=i) for i in range(14)}
    # w 2. semestrze koniec semestru = koniec roku
    koniec_biez = koniec_sem if frek["semestr"] == 1 and dzis <= koniec_sem else koniec_roku
    dni_sem = dni_nauki(dzis, koniec_biez, wolne)
    dni_rok = dni_nauki(dzis, koniec_roku, wolne)
    for p in frek["przedmioty"].values():
        tyg = p.get("lekcji_tygodniowo")
        if tyg is None:
            continue
        zostalo_sem = round(tyg * dni_sem / 5)
        zostalo_rok = round(tyg * dni_rok / 5)
        p["pozostalo_lekcji_semestr"] = zostalo_sem
        p["mozna_opuscic_semestr"] = _mozna_opuscic(p["zapas_do_50"], zostalo_sem)
        p["pozostalo_lekcji_rok"] = zostalo_rok
        # do klasyfikacji rocznej liczą się lekcje z całego roku
        p["mozna_opuscic_rok"] = _mozna_opuscic(p["rok"]["zapas_do_50"], zostalo_rok)
    return {
        "koniec_semestru": koniec_biez.isoformat(),
        "koniec_roku": koniec_roku.isoformat(),
        "dni_nauki_do_konca_semestru": dni_sem,
        "dni_nauki_do_konca_roku": dni_rok,
        "dni_wolne_z_librusa": z_librusa,
    }


_OCENA = re.compile(r"^\s*([1-6])\s*([+-]?)\s*$")


def wartosc_oceny(ocena: str, plus: float = 0.5, minus: float = 0.25) -> float | None:
    """'4+' -> 4.5, '3-' -> 2.75; 'np', 'bz', '+' -> None."""
    m = _OCENA.match(ocena or "")
    if not m:
        return None
    wartosc = float(m.group(1))
    if m.group(2) == "+":
        wartosc += plus
    elif m.group(2) == "-":
        wartosc -= minus
    return wartosc


def _srednia(oceny: list[dict[str, Any]]) -> float | None:
    licz = [o for o in oceny if o["liczona"] and o["wartosc"] is not None and o["waga"] > 0]
    suma_wag = sum(o["waga"] for o in licz)
    if not suma_wag:
        return None
    return round(sum(o["wartosc"] * o["waga"] for o in licz) / suma_wag, 2)


def oceny(
    dane: dict, semestr: int | None = None, plus: float = 0.5, minus: float = 0.25
) -> dict[str, dict[str, Any]]:
    """Oceny cząstkowe, średnie ważone i oceny (proponowane) semestralne per przedmiot."""
    semestr = semestr or biezacy_semestr(dane)
    nazwy = przedmioty(dane)
    kategorie = {
        str(k["Id"]): k for k in _lista(dane.get("grade_categories"), "Categories") if "Id" in k
    }
    # gdy szkoła wyłączyła średnie, żadna kategoria nie jest liczona do średniej –
    # wtedy liczymy wszystkie (jak LibrusPro)
    srednie_wylaczone = not any(
        k.get("CountToTheAverage") is True for k in kategorie.values()
    )
    wynik: dict[str, dict[str, Any]] = {}

    for g in _lista(dane.get("grades"), "Grades"):
        nazwa = nazwy.get(_id(g.get("Subject")) or "", NIEZNANY_PRZEDMIOT)
        klucz = slug(nazwa)
        p = wynik.setdefault(
            klucz,
            {
                "nazwa": nazwa,
                "oceny": [],
                "oceny_rok": [],
                "proponowana_semestralna": None,
                "semestralna": None,
                "proponowana_roczna": None,
                "roczna": None,
            },
        )
        tekst = str(g.get("Grade") or "").strip()
        if g.get("IsFinal"):
            p["roczna"] = tekst
            continue
        if g.get("IsFinalProposition"):
            p["proponowana_roczna"] = tekst
            continue
        sem = str(g.get("Semester"))
        if g.get("IsSemester"):
            if sem == str(semestr):
                p["semestralna"] = tekst
            continue
        if g.get("IsSemesterProposition"):
            if sem == str(semestr):
                p["proponowana_semestralna"] = tekst
            continue

        kat = kategorie.get(_id(g.get("Category")) or "", {})
        waga = kat.get("Weight")
        liczona = g.get("IsConstituent", True) is not False and (
            srednie_wylaczone or kat.get("CountToTheAverage", True) is not False
        )
        ocena = {
            "id": _id(g.get("Id")),
            "ocena": tekst,
            "wartosc": wartosc_oceny(tekst, plus, minus),
            "waga": int(waga) if isinstance(waga, (int, float)) else 1,
            "kategoria": (kat.get("Name") or "").strip(),
            "data": g.get("Date"),
            "dodano": g.get("AddDate"),
            "liczona": liczona,
            "semestr": int(sem) if sem.isdigit() else None,
        }
        p["oceny_rok"].append(ocena)
        if sem == str(semestr):
            p["oceny"].append(ocena)

    for p in wynik.values():
        for lista in (p["oceny"], p["oceny_rok"]):
            lista.sort(key=lambda o: o["data"] or "")
        p["srednia"] = _srednia(p["oceny"])
        p["srednia_rok"] = _srednia(p.pop("oceny_rok"))
    return wynik


def srednia_ogolna(oceny_przedmiotow: dict[str, dict[str, Any]]) -> float | None:
    """Średnia ze średnich przedmiotów (jak w Librusie 'średnia ogólna')."""
    srednie = [p["srednia"] for p in oceny_przedmiotow.values() if p["srednia"] is not None]
    return round(sum(srednie) / len(srednie), 2) if srednie else None
