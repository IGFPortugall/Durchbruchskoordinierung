# -*- coding: utf-8 -*-
from __future__ import unicode_literals

import unittest

from hilfen import PROJEKT, objekt
from dbk_core import Projekt, geometrie_hash


class GeometrieTest(unittest.TestCase):

    def test_rauschen_aendert_hash_nicht(self):
        a = {"min": [1000.0, 0, 0], "max": [1400.0, 250, 300]}
        b = {"min": [1000.4, 0.0001, 0], "max": [1399.8, 250, 300.2]}
        self.assertEqual(geometrie_hash(a), geometrie_hash(b))

    def test_verschieben_aendert_hash(self):
        a = {"min": [1000, 0, 0], "max": [1400, 250, 300]}
        b = {"min": [1300, 0, 0], "max": [1700, 250, 300]}
        self.assertNotEqual(geometrie_hash(a), geometrie_hash(b))

    def test_massaenderung_aendert_hash(self):
        a = {"min": [0, 0, 0], "max": [400, 250, 300], "masse": {"breite": 400}}
        b = {"min": [0, 0, 0], "max": [400, 250, 300], "masse": {"breite": 450}}
        self.assertNotEqual(geometrie_hash(a), geometrie_hash(b))


class ProjektTest(unittest.TestCase):

    def setUp(self):
        self.p = Projekt(PROJEKT)

    def test_tragende_wand(self):
        self.assertEqual(self.p.beteiligung(objekt("1")),
                         {"ARC": "pflicht", "TWP": "pflicht", "TGA": "info"})

    def test_standard_wenn_keine_regel_passt(self):
        self.assertEqual(self.p.pflichtrollen(objekt("1", tragend=False)), ["ARC"])

    def test_zusatzregel_gilt_zusaetzlich(self):
        self.assertEqual(self.p.pflichtrollen(objekt("1", kategorie="Geschossdecken", flaeche=1.5)),
                         ["ARC", "BH", "BS", "TWP"])

    def test_zusatzregel_ersetzt_standard_nicht(self):
        self.assertEqual(self.p.pflichtrollen(objekt("1", tragend=False, flaeche=2.0)), ["ARC", "BH"])

    def test_fehlender_pfad_passt_nicht(self):
        o = objekt("1")
        del o["flaeche_m2"]
        self.assertNotIn("BH", self.p.pflichtrollen(o))

    def test_eigene_status_und_wirkung(self):
        self.assertEqual(self.p.wirkung("zurueckgestellt"), "offen")
        self.assertEqual(self.p.wirkung("abgelehnt"), "blockiert")
        self.assertEqual(self.p.wirkung("gibtsnicht"), "offen")

    def test_ungueltige_wirkung(self):
        with self.assertRaises(ValueError):
            Projekt({"status": [{"id": "x", "wirkung": "egal"}]})

    def test_speichern_und_laden(self):
        import os, shutil, tempfile
        d = tempfile.mkdtemp()
        try:
            pfad = os.path.join(d, "projekt.json")
            self.p.speichern(pfad)
            q = Projekt.laden(pfad)
            self.assertEqual(q.als_dict(), self.p.als_dict())
            self.assertEqual(q.wirkung("zurueckgestellt"), "offen")
        finally:
            shutil.rmtree(d)


if __name__ == "__main__":
    unittest.main()
