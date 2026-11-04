"""Testy obliczeń (bez Home Assistanta): python -m unittest discover tests"""

import importlib.util
import unittest
from pathlib import Path

_SCIEZKA = Path(__file__).parents[1] / "custom_components" / "librus_ha" / "obliczenia.py"
_spec = importlib.util.spec_from_file_location("obliczenia", _SCIEZKA)
obliczenia = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(obliczenia)


def _wpis(i, lekcja, typ, data="2026-10-01", nr=1, semestr=1):
    return {
        "Id": i,
        "Lesson": {"Id": lekcja, "Url": "..."},
        "Date": data,
        "AddDate": f"{data} 08:00:00",
        "LessonNo": nr,
        "Semester": semestr,
        "Type": {"Id": typ, "Url": "..."},
    }


DANE = {
    "subjects": {"Subjects": [{"Id": 10, "Name": "matematyka"}, {"Id": 20, "Name": "Wychowanie fizyczne"}]},
    "lessons": {"Lessons": [{"Id": 100, "Subject": {"Id": 10}}, {"Id": 200, "Subject": {"Id": 20}}]},
    "attendance_types": {
        "Types": [
            {"Id": 1, "Name": "nieobecność", "Short": "nb", "IsPresenceKind": False},
            {"Id": 2, "Name": "spóźnienie", "Short": "sp", "IsPresenceKind": True},
            {"Id": 3, "Name": "nieobecność uspr.", "Short": "u", "IsPresenceKind": False},
            {"Id": 4, "Name": "zwolnienie", "Short": "zw", "IsPresenceKind": False},  # i tak obecność
            {"Id": 100, "Name": "obecność", "Short": "ob", "IsPresenceKind": True},
        ]
    },
    "attendances": {
        "Attendances": [
            # matematyka: 6 obecności, 1 spóźnienie, 3 usprawiedliwione => 7/10
            *[_wpis(f"m{i}", 100, 100, nr=i) for i in range(6)],
            _wpis("m6", 100, 2, data="2026-10-02"),
            *[_wpis(f"m{i}", 100, 3, data="2026-10-03", nr=i) for i in range(7, 10)],
            # WF: 1 obecność, 2 zwolnienia, 1 nieusprawiedliwiona
            _wpis("w0", 200, 100),
            _wpis("w1", 200, 4),
            _wpis("w2", 200, 4),
            _wpis("w3", 200, 1, data="2026-10-04"),
            # poprzedni semestr nie liczy się do bieżącego
            _wpis("s1", 100, 1, semestr=0),
        ]
    },
    "grade_categories": {
        "Categories": [
            {"Id": 1, "Name": "sprawdzian", "Weight": 3, "CountToTheAverage": True},
            {"Id": 2, "Name": "aktywność", "Weight": 1, "CountToTheAverage": True},
            {"Id": 3, "Name": "próbna", "Weight": 2, "CountToTheAverage": False},
        ]
    },
    "grades": {
        "Grades": [
            {"Id": 1, "Subject": {"Id": 10}, "Category": {"Id": 1}, "Grade": "4+", "Semester": 1, "Date": "2026-10-01", "IsConstituent": True},
            {"Id": 2, "Subject": {"Id": 10}, "Category": {"Id": 2}, "Grade": "2", "Semester": 1, "Date": "2026-10-02", "IsConstituent": True},
            {"Id": 3, "Subject": {"Id": 10}, "Category": {"Id": 3}, "Grade": "1", "Semester": 1, "Date": "2026-10-03", "IsConstituent": True},
            {"Id": 4, "Subject": {"Id": 10}, "Category": {"Id": 2}, "Grade": "np", "Semester": 1, "Date": "2026-10-04", "IsConstituent": True},
            {"Id": 5, "Subject": {"Id": 10}, "Category": {"Id": 1}, "Grade": "4", "Semester": 1, "IsSemesterProposition": True},
            {"Id": 6, "Subject": {"Id": 20}, "Category": {"Id": 2}, "Grade": "6", "Semester": 1, "Date": "2026-10-05", "IsConstituent": True},
        ]
    },
}


class TestFrekwencja(unittest.TestCase):
    def setUp(self):
        self.f = obliczenia.frekwencja(DANE)

    def test_semestr(self):
        self.assertEqual(self.f["semestr"], 1)

    def test_matematyka(self):
        m = self.f["przedmioty"]["matematyka"]
        self.assertEqual(m["lekcji"], 10)
        self.assertEqual(m["obecnosci"], 7)
        self.assertEqual(m["spoznienia"], 1)
        self.assertEqual(m["usprawiedliwione"], 3)
        self.assertEqual(m["procent"], 70.0)
        self.assertEqual(m["zapas_do_50"], 4)

    def test_wf_zwolnienia(self):
        w = self.f["przedmioty"]["wychowanie_fizyczne"]
        self.assertEqual(w["zwolnienia"], 2)
        self.assertEqual(w["nieusprawiedliwione"], 1)
        self.assertEqual(w["obecnosci"], 3)
        self.assertEqual(w["procent"], 75.0)
        self.assertEqual(w["procent_bez_zwolnien"], 50.0)
        self.assertEqual(w["zapas_do_50"], 2)

    def test_razem_i_rok(self):
        self.assertEqual(self.f["razem"]["lekcji"], 14)
        self.assertEqual(self.f["rok"]["lekcji"], 15)

    def test_wpisy_bez_obecnosci_od_najnowszego(self):
        self.assertTrue(all(w["skrot"] != "ob" for w in self.f["wpisy"]))
        self.assertEqual(self.f["wpisy"][0]["data"], "2026-10-04")
        self.assertEqual(self.f["wpisy"][0]["przedmiot"], "Wychowanie fizyczne")

    def test_bez_typow_i_nieznana_lekcja(self):
        dane = {
            "attendances": {"Attendances": [_wpis(1, 999, 100), _wpis(2, 999, 1)]},
            "attendance_types": None,
        }
        f = obliczenia.frekwencja(dane)
        p = f["przedmioty"][obliczenia.slug(obliczenia.NIEZNANY_PRZEDMIOT)]
        self.assertEqual(p["procent"], 50.0)


class TestPrognoza(unittest.TestCase):
    def test_mozna_opuscic(self):
        from datetime import date

        dane = {
            **DANE,
            "classes": {"Class": {"Id": 1, "EndFirstSemester": "2026-10-16", "EndSchoolYear": "2026-10-30"}},
            "free_days": {"SchoolFreeDays": [{"DateFrom": "2026-10-12", "DateTo": "2026-10-13"}]},
        }
        f = obliczenia.frekwencja(dane)
        # matematyka: 10 lekcji w 1 tygodniu (wszystkie wpisy z 1–3.10) => 10/tydzień
        self.assertEqual(f["przedmioty"]["matematyka"]["lekcji_tygodniowo"], 10)
        p = obliczenia.prognoza(dane, f, date(2026, 10, 9))
        # 12–16.10: 5 dni roboczych − 2 wolne = 3 dni nauki => 6 lekcji
        self.assertEqual(p["dni_nauki_do_konca_semestru"], 3)
        m = f["przedmioty"]["matematyka"]
        self.assertEqual(m["pozostalo_lekcji_semestr"], 6)
        # zapas 4 (7 obecności z 10) + 6 pozostałych => (4 + 6) / 2 = 5
        self.assertEqual(m["mozna_opuscic_semestr"], 5)
        # rok: 19–30.10 = 10 dni nauki więcej => 3+10 = 13 dni, 26 lekcji; rok ma też wpis z sem. 0
        self.assertEqual(p["dni_nauki_do_konca_roku"], 13)
        self.assertEqual(m["rok"]["lekcji"], 11)
        self.assertEqual(m["mozna_opuscic_rok"], (2 * 7 - 11 + 26) // 2)

    def test_wielkanoc(self):
        from datetime import date

        self.assertEqual(obliczenia._wielkanoc(2027), date(2027, 3, 28))
        self.assertEqual(obliczenia._wielkanoc(2026), date(2026, 4, 5))


class TestOceny(unittest.TestCase):
    def test_wartosc(self):
        self.assertEqual(obliczenia.wartosc_oceny("4+"), 4.5)
        self.assertEqual(obliczenia.wartosc_oceny("3-"), 2.75)
        self.assertEqual(obliczenia.wartosc_oceny("6"), 6.0)
        self.assertIsNone(obliczenia.wartosc_oceny("np"))
        self.assertIsNone(obliczenia.wartosc_oceny("+"))

    def test_srednia_wazona(self):
        o = obliczenia.oceny(DANE)
        m = o["matematyka"]
        # (4.5*3 + 2*1) / 4 ; "1" z kategorii niewliczanej i "np" pominięte
        self.assertEqual(m["srednia"], 3.88)
        self.assertEqual(m["proponowana_semestralna"], "4")
        self.assertEqual(len(m["oceny"]), 4)
        self.assertEqual(obliczenia.srednia_ogolna(o), round((3.88 + 6.0) / 2, 2))

    def test_szkola_wylaczyla_srednie(self):
        dane = {
            **DANE,
            "grade_categories": {
                "Categories": [
                    {"Id": 1, "Name": "sprawdzian", "CountToTheAverage": False},
                    {"Id": 2, "Name": "kartkówka", "CountToTheAverage": False},
                ]
            },
            "grades": {
                "Grades": [
                    {"Id": 1, "Subject": {"Id": 10}, "Category": {"Id": 1}, "Grade": "3", "Semester": 1},
                    {"Id": 2, "Subject": {"Id": 10}, "Category": {"Id": 2}, "Grade": "3+", "Semester": 1},
                    {"Id": 3, "Subject": {"Id": 10}, "Category": {"Id": 2}, "Grade": "0", "Semester": 1},
                ]
            },
        }
        m = obliczenia.oceny(dane)["matematyka"]
        self.assertEqual(m["srednia"], 3.25)  # "0" (brak oceny) pominięte
        self.assertTrue(all(o["liczona"] for o in m["oceny"]))

    def test_zadna_ocena_nie_liczona(self):
        dane = {
            **DANE,
            "grades": {
                "Grades": [
                    {"Id": 1, "Subject": {"Id": 10}, "Category": {"Id": 1}, "Grade": "3", "Semester": 1, "IsConstituent": False},
                    {"Id": 2, "Subject": {"Id": 10}, "Category": {"Id": 2}, "Grade": "5", "Semester": 1, "IsConstituent": False},
                ]
            },
        }
        m = obliczenia.oceny(dane)["matematyka"]
        self.assertFalse(any(o["liczona"] for o in m["oceny"]))
        self.assertEqual(m["srednia"], 3.5)  # wagi 3 i 1: (3*3 + 5*1) / 4

    def test_slug(self):
        self.assertEqual(obliczenia.slug("Język polski"), "jezyk_polski")
        self.assertEqual(obliczenia.slug("bezpieczeństwo i Internet wszechrzeczy"), "bezpieczenstwo_i_internet_wszechrzeczy")
        self.assertEqual(obliczenia.slug("Zajęcia z wychowawcą"), "zajecia_z_wychowawca")


if __name__ == "__main__":
    unittest.main()
