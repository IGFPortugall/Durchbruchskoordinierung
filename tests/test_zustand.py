# -*- coding: utf-8 -*-
"""Abläufe aus dem Konzept (Kapitel 'Ablauf im Team') als Tests."""
from __future__ import unicode_literals

import unittest

from hilfen import OrdnerTest, objekt
from dbk_core import Ablage, Absender, berechne

OID = "HLS:4f1c-0042"


class AblaufTest(OrdnerTest):

    def einreichen(self, o=None, runde="R1"):
        self.tga.schreibe("eingereicht", OID, {"objekt": o or objekt("TGA-0042"), "runde": runde})

    def entscheide(self, ablage, wert, o=None, kommentar=None):
        h = (o or objekt("TGA-0042"))["geometrie_hash"]
        ablage.schreibe("status", OID, {"wert": wert, "geometrie_hash": h, "kommentar": kommentar})

    def zustand(self):
        return berechne(self.leser().alle(), self.projekt)

    def test_neu_eingereicht_ist_in_pruefung(self):
        self.tga.schreibe("pruefrunde_gestartet", None,
                          {"runde": "R1", "name": "Runde 1 – 2.OG", "frist": "2026-12-10"})
        self.einreichen()
        z = self.zustand()
        gs = z.gesamtstatus(OID)
        self.assertEqual(gs["status"], "in_pruefung")
        self.assertEqual((gs["pflicht_erfuellt"], gs["pflicht_gesamt"]), (0, 2))
        self.assertEqual(z.wartet_auf(rolle="ARC"), [OID])
        self.assertEqual(z.wartet_auf(rolle="TWP"), [OID])
        self.assertEqual(z.wartet_auf(firma="IGF", rolle="TGA"), [])
        self.assertEqual(z.runden["R1"]["frist"], "2026-12-10")
        self.assertEqual(z.objekte[OID].runden, ["R1"])

    def test_alle_pflichtrollen_frei(self):
        self.einreichen()
        self.entscheide(self.arc, "freigegeben")
        self.entscheide(self.twp, "freigegeben")
        z = self.zustand()
        self.assertEqual(z.gesamtstatus(OID)["status"], "freigegeben")
        self.assertEqual(z.wartet_auf(rolle="ARC"), [])

    def test_ablehnung_und_nacharbeit(self):
        self.einreichen()
        self.entscheide(self.arc, "freigegeben")
        self.entscheide(self.twp, "abgelehnt", kommentar="Zu nah an der Stütze")
        z = self.zustand()
        self.assertEqual(z.gesamtstatus(OID)["status"], "abgelehnt")
        self.assertEqual(z.wartet_auf(firma="IGF"), [OID])
        self.assertEqual(z.wartet_auf(rolle="TWP"), [])

        verschoben = objekt("TGA-0042", x=300)
        self.einreichen(verschoben, runde="R2")
        z = self.zustand()
        gs = z.gesamtstatus(OID)
        self.assertEqual(gs["status"], "in_pruefung")
        self.assertTrue(gs["geaendert"])
        self.assertTrue(gs["rollen"]["ARC"]["veraltet"])
        self.assertEqual(z.wartet_auf(rolle="ARC"), [OID])
        self.assertEqual(z.wartet_auf(rolle="TWP"), [OID])
        self.assertEqual(z.wartet_auf(firma="IGF"), [])
        self.assertEqual(z.objekte[OID].runden, ["R1", "R2"])

        self.entscheide(self.arc, "freigegeben", o=verschoben)
        self.entscheide(self.twp, "freigegeben", o=verschoben)
        self.assertEqual(self.zustand().gesamtstatus(OID)["status"], "freigegeben")

    def test_bleibt_so_nach_diskussion(self):
        self.einreichen()
        self.entscheide(self.twp, "abgelehnt")
        self.arc.schreibe("nachricht", OID, {"text": "Wir verschieben die Tür, Durchbruch kann bleiben."})
        self.einreichen()  # unverändert erneut eingereicht
        z = self.zustand()
        self.assertEqual(z.gesamtstatus(OID)["status"], "abgelehnt")  # gilt, bis TWP neu entscheidet
        self.assertIn(OID, z.wartet_auf(rolle="TWP"))
        self.assertEqual(z.wartet_auf(firma="IGF"), [])
        self.entscheide(self.twp, "freigegeben")
        self.entscheide(self.arc, "freigegeben")
        self.assertEqual(self.zustand().gesamtstatus(OID)["status"], "freigegeben")

    def test_eigener_status_blockiert_nicht(self):
        self.einreichen()
        self.entscheide(self.arc, "zurueckgestellt")
        self.entscheide(self.twp, "freigegeben")
        z = self.zustand()
        gs = z.gesamtstatus(OID)
        self.assertEqual(gs["status"], "in_pruefung")
        self.assertEqual(gs["pflicht_erfuellt"], 1)
        self.assertEqual(z.wartet_auf(rolle="ARC"), [])

    def test_info_rolle_zaehlt_nicht(self):
        self.einreichen()
        self.entscheide(self.arc, "freigegeben")
        self.entscheide(self.twp, "freigegeben")
        bh = Ablage(self.ordner, Absender("Bauherr", "B. Herr", "BH"))
        self.entscheide(bh, "abgelehnt")  # BH ist hier nicht Pflicht (Fläche klein)
        self.assertEqual(self.zustand().gesamtstatus(OID)["status"], "freigegeben")

    def test_geloescht_ist_geloescht(self):
        self.einreichen()
        self.entscheide(self.arc, "freigegeben")
        self.tga.schreibe("geloescht", OID, {})
        z = self.zustand()
        self.assertNotIn(OID, z.objekte)
        self.assertEqual(z.wartet_auf(rolle="TWP"), [])

    def test_fremde_firma_darf_nicht_aendern_oder_loeschen(self):
        self.einreichen()
        self.arc.schreibe("geloescht", OID, {})
        self.arc.schreibe("geaendert", OID, {"objekt": objekt("FAKE", x=999)})
        z = self.zustand()
        self.assertIn(OID, z.objekte)
        self.assertEqual(z.objekte[OID].daten["nummer"], "TGA-0042")
        self.assertEqual(len(z.ignoriert), 2)

    def test_modellversionen(self):
        self.arc.schreibe("modell_veroeffentlicht", None,
                          {"modell": "ARC", "datei": "modelle/ARC/aaa.frag", "hash": "aaa"})
        self.arc.schreibe("modell_veroeffentlicht", None,
                          {"modell": "ARC", "datei": "modelle/ARC/bbb.frag", "hash": "bbb"})
        self.twp.schreibe("modell_veroeffentlicht", None,
                          {"modell": "ARC", "datei": "modelle/ARC/fake.frag", "hash": "fake"})
        z = self.zustand()
        self.assertEqual(z.modelle["ARC"]["aktuell"]["hash"], "bbb")
        self.assertEqual([v["hash"] for v in z.modelle["ARC"]["versionen"]], ["aaa", "bbb"])
        self.assertEqual(z.modelle["ARC"]["besitzer"], "Architekt XY")
        self.assertEqual(len(z.ignoriert), 1)
        with self.assertRaises(ValueError):
            self.arc.schreibe("modell_veroeffentlicht", None, {"modell": "ARC"})

    def test_stand_und_ausrichtung(self):
        self.tga.schreibe("eingereicht", OID, {"objekt": objekt("TGA-0042"), "runde": "R1", "stand": "EG Rohbau"})
        self.arc.schreibe("modell_veroeffentlicht", None, {"modell": "ARC", "datei": "a.fbx", "hash": "a"})
        self.twp.schreibe("modell_ausrichtung", None, {"modell": "ARC", "versatz_m": [9, 9, 9], "drehung_grad": 90})
        self.arc.schreibe("modell_ausrichtung", None, {"modell": "ARC", "versatz_m": [1, 2, 0], "drehung_grad": 5})
        z = self.zustand()
        self.assertEqual(z.objekte[OID].stand, "EG Rohbau")
        self.assertEqual(z.modelle["ARC"]["ausrichtung"]["versatz_m"], [1, 2, 0])
        self.assertEqual(len(z.ignoriert), 1)

    def test_modell_entfernen(self):
        self.arc.schreibe("modell_veroeffentlicht", None, {"modell": "ARC", "datei": "a.fbx", "hash": "a"})
        self.twp.schreibe("modell_entfernt", None, {"modell": "ARC"})          # fremd → ignoriert
        self.assertIn("ARC", self.zustand().modelle)
        self.arc.schreibe("modell_entfernt", None, {"modell": "ARC"})
        self.assertNotIn("ARC", self.zustand().modelle)
        self.twp.schreibe("modell_veroeffentlicht", None, {"modell": "ARC", "datei": "b.fbx", "hash": "b"})
        self.assertEqual(self.zustand().modelle["ARC"]["besitzer"], "Tragwerk Z")   # beginnt von vorn
        with self.assertRaises(ValueError):
            self.arc.schreibe("modell_entfernt", None, {})

    def test_stand_momentaufnahme(self):
        a, b, c = objekt("TGA-1"), objekt("TGA-2"), objekt("TGA-3")
        self.tga.schreibe("stand_eingereicht", None, {"stand": "EG", "runde": "R1", "mitglieder": ["H:1", "H:2", "H:3"],
                                                      "objekte": {"H:1": a, "H:2": b, "H:3": c}})
        z = self.zustand()
        self.assertEqual(sorted(z.objekte), ["H:1", "H:2", "H:3"])
        self.assertEqual(z.objekte["H:1"].einreichung, "neu")
        self.arc.schreibe("status", "H:1", {"wert": "freigegeben", "geometrie_hash": a["geometrie_hash"]})
        # erneut: H:1 unverändert (nur Mitglied), H:2 nur Daten geändert, H:3 fehlt
        b2 = dict(b, nummer="TGA-2b")
        self.tga.schreibe("stand_eingereicht", None, {"stand": "EG", "runde": None, "mitglieder": ["H:1", "H:2"],
                                                      "objekte": {"H:2": b2}})
        z = self.zustand()
        self.assertEqual(sorted(z.objekte), ["H:1", "H:2"])                      # H:3 fällt heraus
        self.assertEqual(z.objekte["H:1"].einreichung, "unveraendert")
        self.assertEqual(z.objekte["H:2"].einreichung, "unveraendert")          # gleicher Hash = Datenabgleich
        self.assertEqual(z.objekte["H:2"].daten["nummer"], "TGA-2b")
        self.assertEqual(z.gesamtstatus("H:1")["rollen"]["ARC"]["status"], "freigegeben")   # Entscheidung bleibt
        self.assertEqual(z.staende["IGF|EG"]["anzahl"], 2)
        self.tga.schreibe("stand_zurueckgezogen", None, {"stand": "EG"})
        z = self.zustand()
        self.assertEqual(z.objekte, {})
        self.assertNotIn("IGF|EG", z.staende)
        with self.assertRaises(ValueError):
            self.tga.schreibe("stand_eingereicht", None, {"stand": "EG", "mitglieder": [], "objekte": {"H:9": a}})

    def test_verlauf_ist_chronologisch(self):
        self.einreichen()
        self.twp.schreibe("nachricht", OID, {"text": "Frage zur Lage"})
        self.entscheide(self.twp, "abgelehnt")
        self.tga.schreibe("nachricht", OID, {"text": "Verschiebe ich"})
        verlauf = self.zustand().objekte[OID].verlauf
        self.assertEqual([(e["art"], e["rolle"]) for e in verlauf],
                         [("eingereicht", "TGA"), ("nachricht", "TWP"),
                          ("status", "TWP"), ("nachricht", "TGA")])


if __name__ == "__main__":
    unittest.main()
