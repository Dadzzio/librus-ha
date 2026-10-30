"""Obliczenia na surowych danych z gateway API Librusa (bez zależności od HA).

Wejście to słowniki zwrócone przez LibrusApi.pobierz_wszystko(), np.
{"attendances": {"Attendances": [...]}, "lessons": {"Lessons": [...]}, ...}.
"""

from __future__ import annotations

import re
import unicodedata
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
    """Frekwencja ogółem i per przedmiot dla semestru (domyślnie bieżącego)."""
    semestr = semestr or biezacy_semestr(dane)
    typy = typy_frekwencji(dane)
    nazwy = przedmioty(dane)
    lekcje = lekcje_przedmiotow(dane)

    razem = _pusty_licznik()
    rok = _pusty_licznik()
    per_przedmiot: dict[str, dict[str, Any]] = {}
    wpisy: list[dict[str, Any]] = []

    for a in _lista(dane.get("attendances"), "Attendances"):
        typ = typy.get(_id(a.get("Type")) or "", {"skrot": "?", "nazwa": "?", "obecnosc": False})
        _dodaj(rok, typ)
        if str(a.get("Semester")) != str(semestr):
            continue
        id_przedmiotu = lekcje.get(_id(a.get("Lesson")) or "")
        nazwa = nazwy.get(id_przedmiotu or "", NIEZNANY_PRZEDMIOT)
        klucz = slug(nazwa)
        if klucz not in per_przedmiot:
            per_przedmiot[klucz] = {"nazwa": nazwa, **_pusty_licznik()}
        _dodaj(per_przedmiot[klucz], typ)
        _dodaj(razem, typ)
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
    return {
        "semestr": semestr,
        "razem": _podsumuj(razem),
        "rok": _podsumuj(rok),
        "przedmioty": {
            k: {"nazwa": v.pop("nazwa"), **_podsumuj(v)} for k, v in per_przedmiot.items()
        },
        "wpisy": wpisy,
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
        liczona = kat.get("CountToTheAverage", True) is not False and g.get(
            "IsConstituent", True
        ) is not False
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
