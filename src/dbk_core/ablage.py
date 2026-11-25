# -*- coding: utf-8 -*-
"""Lesen und Schreiben der Ereignis-Dateien im gemeinsamen Projektordner.

Aufbau:
    <projektordner>/
      projekt.json
      ereignisse/<Firma>/<zeit>_<seq>_<id>.json

Regeln:
  - Jede Firma schreibt nur in ihren eigenen Unterordner.
  - Eine Datei pro Ereignis; Dateien werden nie geändert.
  - Schreiben erst als .tmp, dann umbenennen, damit Sync-Dienste keine halben
    Dateien verteilen.
  - Beim Lesen werden halbe/kaputte Dateien übersprungen und später erneut
    versucht; Ereignisse, deren Firma nicht zum Ordner passt, werden verworfen.
"""
from __future__ import unicode_literals

import io
import json
import os

from . import ereignisse as ev
from . import zeit

EREIGNIS_ORDNER = "ereignisse"


class Ablage(object):

    def __init__(self, projektordner, absender=None):
        self.wurzel = projektordner
        self.absender = absender
        self._gelesen = set()
        self._ereignisse = []
        self._seq = None
        self.unvollstaendig = set()   # Dateien, die (noch) nicht lesbar sind
        self.verworfen = set()        # Dateien mit falscher Firma oder Form

    # ---------------------------------------------------------------- Lesen

    def ereignis_ordner(self):
        return os.path.join(self.wurzel, EREIGNIS_ORDNER)

    def lade_neue(self):
        """Liest alle noch nicht gelesenen Dateien. Gibt die neuen Ereignisse zurück."""
        neu = []
        basis = self.ereignis_ordner()
        if not os.path.isdir(basis):
            return neu
        for firmenordner in sorted(os.listdir(basis)):
            ordner = os.path.join(basis, firmenordner)
            if not os.path.isdir(ordner):
                continue
            for datei in sorted(os.listdir(ordner)):
                if not datei.endswith(".json"):
                    continue
                pfad = os.path.join(ordner, datei)
                if pfad in self._gelesen or pfad in self.verworfen:
                    continue
                e = self._lies(pfad)
                if e is None:
                    self.unvollstaendig.add(pfad)
                    continue
                self.unvollstaendig.discard(pfad)
                if not ev.ist_gueltig(e) or ev.ordnername(e["firma"]) != firmenordner:
                    self.verworfen.add(pfad)
                    continue
                self._gelesen.add(pfad)
                self._ereignisse.append(e)
                neu.append(e)
        return neu

    def alle(self):
        """Alle bisher gelesenen Ereignisse in fester Reihenfolge."""
        return sorted(self._ereignisse, key=ev.sortierschluessel)

    @staticmethod
    def _lies(pfad):
        try:
            with io.open(pfad, "r", encoding="utf-8-sig") as f:
                return json.load(f)
        except (IOError, OSError, ValueError):
            return None

    # ------------------------------------------------------------ Schreiben

    def eigener_ordner(self):
        self._brauche_absender()
        return os.path.join(self.ereignis_ordner(), ev.ordnername(self.absender.firma))

    def schreibe(self, art, objekt=None, daten=None):
        """Erzeugt ein Ereignis, speichert es und gibt es zurück."""
        self._brauche_absender()
        ordner = self.eigener_ordner()
        if not os.path.isdir(ordner):
            os.makedirs(ordner)
        seq = self._naechste_seq(ordner)
        e = ev.baue(self.absender, art, objekt, daten, seq)
        name = "%s_%06d_%s.json" % (zeit.kompakt(e["zeit"]), seq, e["id"][:8])
        ziel = os.path.join(ordner, name)
        tmp = ziel + ".tmp"
        text = json.dumps(e, ensure_ascii=False, indent=1, sort_keys=True)
        if isinstance(text, bytes):  # Python 2 liefert bei reinem ASCII bytes
            text = text.decode("utf-8")
        with io.open(tmp, "w", encoding="utf-8") as f:
            f.write(text)
        os.rename(tmp, ziel)
        self._seq = seq
        self._gelesen.add(ziel)
        self._ereignisse.append(e)
        return e

    def _naechste_seq(self, ordner):
        if self._seq is None:
            hoechste = 0
            for datei in os.listdir(ordner):
                teile = datei.split("_")
                if len(teile) >= 3 and datei.endswith(".json"):
                    try:
                        hoechste = max(hoechste, int(teile[1]))
                    except ValueError:
                        pass
            self._seq = hoechste
        return self._seq + 1

    def _brauche_absender(self):
        if self.absender is None:
            raise ValueError("Zum Schreiben wird ein Absender (Firma, Name, Rolle) benötigt.")
