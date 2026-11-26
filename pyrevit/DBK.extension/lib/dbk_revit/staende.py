# -*- coding: utf-8 -*-
"""Stände der eigenen Firma: Name + 3D-Ansicht, je Revit-Modell (Kürzel) im Prüfset gespeichert.

Ältere Auswahlvorlagen (``vorlagen``) werden beim ersten Laden übernommen: Name und – falls
gesetzt – die 3D-Ansicht. Ebenen-Filter und Häkchen gibt es nicht mehr.
"""
from __future__ import unicode_literals

import uuid

from . import sammeln


def _schluessel(kuerzel):
    return "staende:%s" % (kuerzel or ""), "aktiver_stand:%s" % (kuerzel or "")


def neu(name, ansicht=None):
    return {"id": uuid.uuid4().hex[:8], "name": name, "ansicht": ansicht}


def laden(ordner, firma, kuerzel):
    ps = sammeln.pruefset_laden(ordner, firma)
    k_liste, k_aktiv = _schluessel(kuerzel)
    if k_liste in ps:
        return ps[k_liste], ps.get(k_aktiv) or ""
    alt = ps.get("vorlagen") or []
    staende = [{"id": v["id"], "name": v["name"], "ansicht": v.get("ansicht") if v.get("quelle") == "ansicht" else None}
               for v in alt if v.get("name")]
    return staende, ps.get("aktive_vorlage") or ""


def speichern(ordner, firma, kuerzel, staende, aktiv):
    ps = sammeln.pruefset_laden(ordner, firma)
    k_liste, k_aktiv = _schluessel(kuerzel)
    ps[k_liste] = staende
    ps[k_aktiv] = aktiv or ""
    sammeln.pruefset_speichern(ordner, firma, ps)
