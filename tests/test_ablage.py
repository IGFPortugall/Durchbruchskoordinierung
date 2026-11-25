# -*- coding: utf-8 -*-
from __future__ import unicode_literals

import io
import json
import os
import unittest

from hilfen import OrdnerTest, objekt
from dbk_core import Ablage, Absender


class AblageTest(OrdnerTest):

    def test_schreiben_und_lesen(self):
        self.tga.schreibe("eingereicht", "HLS:1", {"objekt": objekt("TGA-1"), "runde": "R1"})
        self.arc.schreibe("nachricht", "HLS:1", {"text": "Bitte prüfen – Größe ok?"})
        alle = self.leser().alle()
        self.assertEqual([e["art"] for e in alle], ["eingereicht", "nachricht"])
        self.assertEqual(alle[1]["daten"]["text"], "Bitte prüfen – Größe ok?")

    def test_jede_firma_eigener_ordner(self):
        self.tga.schreibe("nachricht", "HLS:1", {"text": "a"})
        self.arc.schreibe("nachricht", "HLS:1", {"text": "b"})
        ordner = sorted(os.listdir(os.path.join(self.ordner, "ereignisse")))
        self.assertEqual(ordner, ["Architekt_XY", "IGF"])

    def test_seq_laeuft_weiter_nach_neustart(self):
        self.tga.schreibe("nachricht", "HLS:1", {"text": "a"})
        self.tga.schreibe("nachricht", "HLS:1", {"text": "b"})
        neu = Ablage(self.ordner, Absender("IGF", "Kollege", "ELT"))
        e = neu.schreibe("nachricht", "HLS:1", {"text": "c"})
        self.assertEqual(e["seq"], 3)

    def test_inkrementell(self):
        leser = Ablage(self.ordner)
        self.tga.schreibe("nachricht", "HLS:1", {"text": "a"})
        self.assertEqual(len(leser.lade_neue()), 1)
        self.assertEqual(len(leser.lade_neue()), 0)
        self.arc.schreibe("nachricht", "HLS:1", {"text": "b"})
        self.assertEqual(len(leser.lade_neue()), 1)
        self.assertEqual(len(leser.alle()), 2)

    def test_halbe_datei_wird_spaeter_gelesen(self):
        ordner = os.path.join(self.ordner, "ereignisse", "IGF")
        os.makedirs(ordner)
        pfad = os.path.join(ordner, "20261124T100000000Z_000001_abcdef12.json")
        with io.open(pfad, "w", encoding="utf-8") as f:
            f.write('{"schema": 1, "id": "abc')
        leser = Ablage(self.ordner)
        self.assertEqual(leser.lade_neue(), [])
        self.assertIn(pfad, leser.unvollstaendig)
        e = {"schema": 1, "id": "abcdef12", "zeit": "2026-11-24T10:00:00.000Z", "seq": 1,
             "firma": "IGF", "name": "x", "rolle": "TGA", "art": "nachricht",
             "objekt": "HLS:1", "daten": {"text": "fertig"}}
        with io.open(pfad, "w", encoding="utf-8") as f:
            f.write(json.dumps(e))
        self.assertEqual(len(leser.lade_neue()), 1)
        self.assertNotIn(pfad, leser.unvollstaendig)

    def test_tmp_dateien_werden_ignoriert(self):
        self.tga.schreibe("nachricht", "HLS:1", {"text": "a"})
        ordner = os.path.join(self.ordner, "ereignisse", "IGF")
        with io.open(os.path.join(ordner, "x.json.tmp"), "w", encoding="utf-8") as f:
            f.write("{")
        self.assertEqual(len(self.leser().alle()), 1)

    def test_fremde_firma_im_ordner_wird_verworfen(self):
        e = self.arc.schreibe("status", "HLS:1", {"wert": "freigegeben", "geometrie_hash": "x"})
        ordner = os.path.join(self.ordner, "ereignisse", "IGF")
        os.makedirs(ordner)
        with io.open(os.path.join(ordner, "gefaelscht.json"), "w", encoding="utf-8") as f:
            f.write(json.dumps(e))
        leser = self.leser()
        self.assertEqual(len(leser.alle()), 1)
        self.assertEqual(len(leser.verworfen), 1)

    def test_lesen_ohne_absender_schreiben_nicht(self):
        with self.assertRaises(ValueError):
            Ablage(self.ordner).schreibe("nachricht", "HLS:1", {"text": "a"})

    def test_ungueltige_ereignisse(self):
        with self.assertRaises(ValueError):
            self.tga.schreibe("quatsch", "HLS:1", {})
        with self.assertRaises(ValueError):
            self.tga.schreibe("eingereicht", "HLS:1", {"objekt": {"nummer": "ohne hash"}})
        with self.assertRaises(ValueError):
            self.arc.schreibe("status", "HLS:1", {"wert": "freigegeben"})


if __name__ == "__main__":
    unittest.main()
