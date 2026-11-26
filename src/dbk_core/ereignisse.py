# -*- coding: utf-8 -*-
"""Ereignis-Format.

Ein Ereignis ist ein dict, das 1:1 als JSON-Datei gespeichert wird:

    {
      "schema": 1,
      "id": "9f0c...",              eindeutig
      "zeit": "2026-11-24T10:20:11.123Z",
      "seq": 17,                    fortlaufend je Firma
      "firma": "IGF",
      "name": "M. Muster",
      "rolle": "TGA",
      "art": "status",
      "objekt": "HLS:4f1c...-0004a2b1",   Prüfobjekt-ID oder null
      "daten": {...}
    }

Arten und ihre ``daten``:
  pruefrunde_gestartet  {"runde": id, "name": str, "frist": "YYYY-MM-DD" | null}
  eingereicht           {"objekt": Objektdaten, "runde": id | null, "stand": Name | null}
  geaendert             {"objekt": Objektdaten}
  geloescht             {}
  status                {"wert": Status-ID, "geometrie_hash": str, "kommentar": str | null}
  nachricht             {"text": str}
  stand_eingereicht     {"stand": Name, "runde": id | null, "mitglieder": [oid, ...],
                         "objekte": {oid: Objektdaten}}   – nur Neue/Geänderte mit Daten
  stand_zurueckgezogen  {"stand": Name}
  modell_veroeffentlicht {"modell": "ARC", "datei": "modelle/ARC/<hash>.frag",
                          "hash": str, "quelle": "ARC.ifc", "stand": str,
                          "ebenen": [{"name", "hoehe_mm"}], "plaene": [...]}

Objektdaten enthalten mindestens ``geometrie_hash``; alles Weitere
(nummer, kategorie, familie, typ, ebene, wirt, geometrie, ifc_guid, ...)
ist frei und wird für Filter, Pflicht-Regeln und Berichte genutzt.
"""
from __future__ import unicode_literals

import re
import uuid

from . import zeit

SCHEMA = 1

PRUEFRUNDE_GESTARTET = "pruefrunde_gestartet"
EINGEREICHT = "eingereicht"
GEAENDERT = "geaendert"
GELOESCHT = "geloescht"
STATUS = "status"
NACHRICHT = "nachricht"

MODELL_VEROEFFENTLICHT = "modell_veroeffentlicht"
MODELL_AUSRICHTUNG = "modell_ausrichtung"   # {"modell", "x_mm", "y_mm", "z_mm", "drehung_grad"} – nur Besitzer
MODELL_ENTFERNT = "modell_entfernt"         # {"modell"} – nur Besitzer; Modell verschwindet für alle

# Stand als Momentaufnahme: alle Mitglieder; Objektdaten nur für Neue/Geänderte.
# Was vorher im Stand war und fehlt, fällt heraus.
STAND_EINGEREICHT = "stand_eingereicht"     # {"stand", "runde", "mitglieder": [oid], "objekte": {oid: Objektdaten}}
STAND_ZURUECKGEZOGEN = "stand_zurueckgezogen"   # {"stand"} – alle Objekte des Stands fallen heraus

ARTEN = (PRUEFRUNDE_GESTARTET, EINGEREICHT, GEAENDERT, GELOESCHT, STATUS, NACHRICHT,
         MODELL_VEROEFFENTLICHT, MODELL_AUSRICHTUNG, MODELL_ENTFERNT, STAND_EINGEREICHT, STAND_ZURUECKGEZOGEN)

# Arten ohne Bezug zu einem Prüfobjekt
OHNE_OBJEKT = (PRUEFRUNDE_GESTARTET, MODELL_VEROEFFENTLICHT, MODELL_AUSRICHTUNG, MODELL_ENTFERNT,
               STAND_EINGEREICHT, STAND_ZURUECKGEZOGEN)

PFLICHTFELDER = ("schema", "id", "zeit", "seq", "firma", "name", "rolle", "art", "objekt", "daten")


class Absender(object):
    """Wer gerade arbeitet (aus dem Start-Dialog)."""

    def __init__(self, firma, name, rolle):
        if not firma or not name or not rolle:
            raise ValueError("Firma, Name und Rolle sind erforderlich.")
        self.firma = firma
        self.name = name
        self.rolle = rolle


def ordnername(firma):
    """Firmenname als sicherer Ordnername (nur Buchstaben, Ziffern, - und _)."""
    return re.sub(r"[^0-9A-Za-zÄÖÜäöüß_-]+", "_", firma).strip("_") or "_"


def baue(absender, art, objekt, daten, seq, zeitpunkt=None):
    if art not in ARTEN:
        raise ValueError("Unbekannte Ereignis-Art: %s" % art)
    if art not in OHNE_OBJEKT and not objekt:
        raise ValueError("Ereignis '%s' braucht ein Objekt." % art)
    if art == MODELL_VEROEFFENTLICHT:
        for feld in ("modell", "datei", "hash"):
            if not (daten or {}).get(feld):
                raise ValueError("Modell-Veröffentlichung braucht '%s'." % feld)
    if art in (MODELL_AUSRICHTUNG, MODELL_ENTFERNT) and not (daten or {}).get("modell"):
        raise ValueError("Ereignis '%s' braucht 'modell'." % art)
    if art in (STAND_EINGEREICHT, STAND_ZURUECKGEZOGEN) and (daten or {}).get("stand") is None:
        raise ValueError("Ereignis '%s' braucht 'stand' (\"\" = ohne Stand)." % art)
    if art == STAND_EINGEREICHT:
        mitglieder = daten.get("mitglieder")
        objekte = daten.get("objekte") or {}
        if not isinstance(mitglieder, list):
            raise ValueError("Stand-Einreichung braucht die Liste 'mitglieder'.")
        for oid, obj in objekte.items():
            if oid not in mitglieder or not (obj or {}).get("geometrie_hash"):
                raise ValueError("Stand-Einreichung: '%s' fehlt in 'mitglieder' oder hat keinen geometrie_hash." % oid)
    if art in (EINGEREICHT, GEAENDERT):
        obj = (daten or {}).get("objekt") or {}
        if not obj.get("geometrie_hash"):
            raise ValueError("Objektdaten brauchen einen geometrie_hash.")
    if art == STATUS:
        if not (daten or {}).get("wert") or not (daten or {}).get("geometrie_hash"):
            raise ValueError("Status braucht 'wert' und 'geometrie_hash'.")
    return {
        "schema": SCHEMA,
        "id": uuid.uuid4().hex,
        "zeit": zeitpunkt or zeit.jetzt_iso(),
        "seq": seq,
        "firma": absender.firma,
        "name": absender.name,
        "rolle": absender.rolle,
        "art": art,
        "objekt": objekt,
        "daten": daten or {},
    }


def ist_gueltig(e):
    """Grobe Formprüfung für gelesene Dateien."""
    if not isinstance(e, dict):
        return False
    for feld in PFLICHTFELDER:
        if feld not in e:
            return False
    return e["art"] in ARTEN and isinstance(e["daten"], dict)


def sortierschluessel(e):
    """Reihenfolge: UTC-Zeit, dann Firma, dann laufende Nummer der Firma."""
    return (e["zeit"], e["firma"], e["seq"])
