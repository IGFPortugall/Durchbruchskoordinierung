# -*- coding: utf-8 -*-
from __future__ import unicode_literals

import os
import shutil
import sys
import tempfile
import unittest

HIER = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HIER), "src"))

from dbk_core import Ablage, Absender, Projekt, geometrie_hash  # noqa: E402
from dbk_core import zeit  # noqa: E402

PROJEKT = {
    "name": "Test",
    "rollen": [{"id": r, "name": r} for r in ("TGA", "ELT", "ARC", "TWP", "BS", "BH")],
    "status": [{"id": "zurueckgestellt", "name": "Zurückgestellt", "wirkung": "offen"}],
    "standard": {"ARC": "pflicht"},
    "regeln": [
        {"name": "Wand tragend", "wenn": {"wirt.kategorie": "Wände", "wirt.tragend": True},
         "rollen": {"ARC": "pflicht", "TWP": "pflicht", "TGA": "info"}},
        {"name": "Decke", "wenn": {"wirt.kategorie": "Geschossdecken"},
         "rollen": {"ARC": "pflicht", "TWP": "pflicht", "BS": "pflicht"}},
        {"name": "Groß", "zusatz": True, "wenn": {"flaeche_m2": {"gt": 1.0}},
         "rollen": {"BH": "pflicht"}},
    ],
}


def objekt(nr, x=0.0, tragend=True, kategorie="Wände", flaeche=0.12):
    geo = {"min": [x, 0, 2100], "max": [x + 400, 250, 2400], "form": "rechteck",
           "masse": {"breite": 400, "hoehe": 300}}
    return {"nummer": nr, "kategorie": "Allgemeines Modell", "familie": "IGF_Durchbruch",
            "typ": "Wand", "ebene": "2_OG01", "geometrie": geo, "flaeche_m2": flaeche,
            "wirt": {"kategorie": kategorie, "tragend": tragend},
            "geometrie_hash": geometrie_hash(geo)}


class OrdnerTest(unittest.TestCase):

    def setUp(self):
        # Künstliche Uhr: jedes Ereignis 1 s später, damit die Reihenfolge
        # in Tests nicht von Millisekunden-Zufällen abhängt.
        self._echte_uhr = zeit.jetzt_iso
        zaehler = [0]

        def uhr():
            zaehler[0] += 1
            return "2026-12-01T%02d:%02d:%02d.000Z" % (zaehler[0] // 3600, zaehler[0] // 60 % 60, zaehler[0] % 60)

        zeit.jetzt_iso = uhr
        self.ordner = tempfile.mkdtemp(prefix="dbk_test_")
        self.projekt = Projekt(PROJEKT)
        self.tga = Ablage(self.ordner, Absender("IGF", "T. Planer", "TGA"))
        self.arc = Ablage(self.ordner, Absender("Architekt XY", "A. Klein", "ARC"))
        self.twp = Ablage(self.ordner, Absender("Tragwerk Z", "M. Weber", "TWP"))

    def tearDown(self):
        zeit.jetzt_iso = self._echte_uhr
        shutil.rmtree(self.ordner, ignore_errors=True)

    def leser(self):
        a = Ablage(self.ordner)
        a.lade_neue()
        return a
