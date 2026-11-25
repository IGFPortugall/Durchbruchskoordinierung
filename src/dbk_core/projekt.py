# -*- coding: utf-8 -*-
"""Projekt-Einstellungen aus ``projekt.json`` (gepflegt über die Verwaltungs-Seite).

Beispiel:

    {
      "name": "Testprojekt",
      "rollen": [{"id": "ARC", "name": "Architektur"}, {"id": "TWP", "name": "Tragwerk"}],
      "status": [{"id": "zurueckgestellt", "name": "Zurückgestellt", "wirkung": "offen"}],
      "standard": {"ARC": "pflicht"},
      "regeln": [
        {"name": "Wand tragend",
         "wenn": {"wirt.kategorie": "Wände", "wirt.tragend": true},
         "rollen": {"ARC": "pflicht", "TWP": "pflicht"}},
        {"name": "Groß", "zusatz": true,
         "wenn": {"flaeche_m2": {"gt": 1.0}},
         "rollen": {"BH": "pflicht"}}
      ]
    }

Pflicht-Regeln:
  - Normale Regeln (Zeilen der Pflicht-Matrix): alle passenden werden vereinigt.
    Passt keine, gilt ``standard``.
  - Zusatz-Regeln (``"zusatz": true``) gelten immer zusätzlich, wenn sie passen.
  - Stufen: "pflicht" > "info". Nicht genannte Rollen sind unbeteiligt.
  - Bedingungen: Pfad mit Punkten in die Objektdaten; Wert direkt (Gleichheit)
    oder als Vergleich {"gt"|"gte"|"lt"|"lte"|"ne": x} bzw. {"in": [..]}.
"""
from __future__ import unicode_literals

import io
import json

PFLICHT = "pflicht"
INFO = "info"
_STUFE = {INFO: 1, PFLICHT: 2}

FREIGABE = "freigabe"
BLOCKIERT = "blockiert"
OFFEN = "offen"
WIRKUNGEN = (FREIGABE, BLOCKIERT, OFFEN)

STANDARD_STATUS = [
    {"id": "freigegeben", "name": "Freigegeben", "wirkung": FREIGABE, "farbe": "#3B6D11"},
    {"id": "abgelehnt", "name": "Abgelehnt", "wirkung": BLOCKIERT, "farbe": "#A32D2D"},
]

_FEHLT = object()


class Projekt(object):

    def __init__(self, daten=None):
        daten = daten or {}
        self.name = daten.get("name", "")
        self.rollen = list(daten.get("rollen", []))
        self.standard = dict(daten.get("standard", {}))
        self.regeln = list(daten.get("regeln", []))
        self.viewer = dict(daten.get("viewer", {}))  # Anzeige-Einstellungen, z. B. versatz_mm
        self.status = [dict(s) for s in STANDARD_STATUS]
        bekannte = set(s["id"] for s in self.status)
        for s in daten.get("status", []):
            if s.get("wirkung") not in WIRKUNGEN:
                raise ValueError("Status '%s' hat keine gültige Wirkung." % s.get("id"))
            if s["id"] in bekannte:
                for vorhanden in self.status:
                    if vorhanden["id"] == s["id"]:
                        vorhanden.update(s)
            else:
                self.status.append(dict(s))
                bekannte.add(s["id"])

    @classmethod
    def laden(cls, pfad):
        with io.open(pfad, "r", encoding="utf-8-sig") as f:
            return cls(json.load(f))

    def als_dict(self):
        eigene = [s for s in self.status if s["id"] not in ("freigegeben", "abgelehnt")]
        return {"name": self.name, "rollen": self.rollen, "status": eigene,
                "standard": self.standard, "regeln": self.regeln, "viewer": self.viewer}

    def speichern(self, pfad):
        text = json.dumps(self.als_dict(), ensure_ascii=False, indent=2, sort_keys=True)
        if isinstance(text, bytes):
            text = text.decode("utf-8")
        with io.open(pfad, "w", encoding="utf-8") as f:
            f.write(text)

    # ---------------------------------------------------------------- Status

    def wirkung(self, status_id):
        for s in self.status:
            if s["id"] == status_id:
                return s["wirkung"]
        return OFFEN

    # ------------------------------------------------------- Pflicht-Regeln

    def beteiligung(self, objektdaten):
        """dict Rolle -> "pflicht" | "info" für ein Prüfobjekt."""
        ergebnis = {}
        normale_passend = False
        for regel in self.regeln:
            if regel.get("zusatz"):
                continue
            if _passt(regel.get("wenn", {}), objektdaten):
                normale_passend = True
                _vereinige(ergebnis, regel.get("rollen", {}))
        if not normale_passend:
            _vereinige(ergebnis, self.standard)
        for regel in self.regeln:
            if regel.get("zusatz") and _passt(regel.get("wenn", {}), objektdaten):
                _vereinige(ergebnis, regel.get("rollen", {}))
        return ergebnis

    def pflichtrollen(self, objektdaten):
        return sorted(r for r, stufe in self.beteiligung(objektdaten).items() if stufe == PFLICHT)


def _vereinige(ziel, rollen):
    for rolle, stufe in rollen.items():
        if stufe not in _STUFE:
            continue
        if _STUFE[stufe] > _STUFE.get(ziel.get(rolle), 0):
            ziel[rolle] = stufe


def _wert(objekt, pfad):
    for teil in pfad.split("."):
        if isinstance(objekt, dict) and teil in objekt:
            objekt = objekt[teil]
        else:
            return _FEHLT
    return objekt


def _passt(bedingung, objektdaten):
    for pfad, erwartet in bedingung.items():
        w = _wert(objektdaten, pfad)
        if isinstance(erwartet, dict):
            if w is _FEHLT:
                return False
            for op, x in erwartet.items():
                try:
                    if op == "gt" and not w > x:
                        return False
                    if op == "gte" and not w >= x:
                        return False
                    if op == "lt" and not w < x:
                        return False
                    if op == "lte" and not w <= x:
                        return False
                except TypeError:
                    return False
                if op == "ne" and w == x:
                    return False
                if op == "in" and w not in x:
                    return False
        elif w is _FEHLT or w != erwartet:
            return False
    return True
