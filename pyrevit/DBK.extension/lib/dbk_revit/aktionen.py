# -*- coding: utf-8 -*-
"""Einreichen und Modell veröffentlichen – ohne Oberfläche, damit auch testbar.

Beide Funktionen ändern das Revit-Modell nicht; sie schreiben nur in den Projektordner.
"""
from __future__ import unicode_literals

import hashlib
import os
import shutil
import tempfile
import time

from Autodesk.Revit import DB

from dbk_core import Ablage, Projekt, berechne
from dbk_core import zeit as dbk_zeit
from . import sammeln


def projekt_laden(ordner):
    return Projekt.laden(os.path.join(ordner, "projekt.json"))


def zustand_laden(ordner, absender=None):
    ablage = Ablage(ordner, absender)
    ablage.lade_neue()
    return ablage, berechne(ablage.alle(), projekt_laden(ordner))


# ------------------------------------------------------------------ Einreichen

NEU, GEOMETRIE, DATEN, UNVERAENDERT, FREMD = "neu", "geometrie", "daten", "unveraendert", "fremd"
ZUSTAND_TEXT = {NEU: "neu", GEOMETRIE: "verschoben/geändert", DATEN: "Daten geändert",
                UNVERAENDERT: "unverändert", FREMD: "gehört anderer Firma"}


class Plan(object):
    """Was beim Einreichen passieren würde – je Exemplar."""

    def __init__(self):
        self.objekte = {}       # oid -> Objektdaten
        self.zustand = {}       # oid -> NEU | GEOMETRIE | DATEN | UNVERAENDERT | FREMD
        self.element_ids = {}   # oid -> ElementId
        self.entfallen = []     # eingereicht, aber im Modell gelöscht
        self.ausgeschlossen = set()

    def liste(self, art):
        return [o for o, z in self.zustand.items() if z == art]

    @property
    def neu(self):
        return self.liste(NEU)

    @property
    def geometrie(self):
        return self.liste(GEOMETRIE)

    @property
    def daten(self):
        return self.liste(DATEN)

    @property
    def unveraendert(self):
        return len(self.liste(UNVERAENDERT))

    @property
    def leer(self):
        return not (self.neu or self.geometrie or self.daten or self.entfallen)

    def vorschlag(self):
        """Standardauswahl: alles Neue und Geänderte, ohne dauerhaft Ausgeschlossene."""
        return set(o for o, z in self.zustand.items()
                   if z in (NEU, GEOMETRIE, DATEN) and o not in self.ausgeschlossen)


def einreichen_planen(doc, einst, pruefset, fortschritt=None):
    ablage, z = zustand_laden(einst["projektordner"])
    kuerzel = einst["modellkuerzel"] or doc.Title
    firmenkuerzel = einst.get("rolle") or "DB"
    ebenen = sammeln.ebenen(doc)
    wirte = sammeln.WirtSuche(doc)
    plan = Plan()
    plan.ausgeschlossen = set(pruefset.get("ausgeschlossen", []))
    elemente = sammeln.elemente_im_pruefset(doc, pruefset)
    for i, e in enumerate(elemente):
        if fortschritt and i % 25 == 0:
            fortschritt(i, len(elemente))
        d = sammeln.objektdaten(e, kuerzel, firmenkuerzel, ebenen, wirte)
        if d is None:
            continue
        oid = sammeln.objekt_id(kuerzel, e)
        plan.objekte[oid] = d
        plan.element_ids[oid] = e.Id
        alt = z.objekte.get(oid)
        if alt is None:
            plan.zustand[oid] = NEU
        elif alt.besitzer != einst["firma"]:
            plan.zustand[oid] = FREMD
        elif alt.geometrie_hash != d["geometrie_hash"]:
            plan.zustand[oid] = GEOMETRIE
        elif _vergleich(alt.daten) != _vergleich(d):
            plan.zustand[oid] = DATEN
        else:
            plan.zustand[oid] = UNVERAENDERT
    # Gelöscht wird nur, was im Modell wirklich nicht mehr existiert – abgewählte Bauteile bleiben stehen.
    for oid, o in z.objekte.items():
        if o.besitzer == einst["firma"] and oid.startswith(kuerzel + ":") and oid not in plan.objekte:
            uid = o.daten.get("revit_unique_id")
            if uid and doc.GetElement(uid) is None:
                plan.entfallen.append(oid)
    return plan


def _vergleich(d):
    return dict((k, v) for k, v in d.items() if k not in ("wirt",))


def einreichen_ausfuehren(einst, plan, rundenname=None, frist=None, auswahl=None, entfallen=True):
    """Reicht ein. auswahl: Menge von Objekt-IDs (None = Vorschlag des Plans)."""
    from .einstellungen import absender
    auswahl = plan.vorschlag() if auswahl is None else set(auswahl)
    pruefen = [o for o in plan.neu + plan.geometrie + plan.liste(UNVERAENDERT) if o in auswahl]
    daten = [o for o in plan.daten if o in auswahl]
    ablage = Ablage(einst["projektordner"], absender(einst))
    ablage.lade_neue()
    runde = None
    if rundenname and pruefen:
        runde = "R-" + dbk_zeit.kompakt(dbk_zeit.jetzt_iso())[:15]
        ablage.schreibe("pruefrunde_gestartet", None, {"runde": runde, "name": rundenname, "frist": frist})
    for oid in pruefen:
        ablage.schreibe("eingereicht", oid, {"objekt": plan.objekte[oid], "runde": runde})
    for oid in daten:
        ablage.schreibe("geaendert", oid, {"objekt": plan.objekte[oid]})
    if entfallen:
        for oid in plan.entfallen:
            ablage.schreibe("geloescht", oid, {})
    return {"runde": runde, "eingereicht": len(pruefen), "geaendert": len(daten),
            "geloescht": len(plan.entfallen) if entfallen else 0}


# ------------------------------------------------------------------ Modell veröffentlichen

B = DB.BuiltInCategory
TGA_KATEGORIEN = [
    B.OST_DuctCurves, B.OST_DuctFitting, B.OST_DuctAccessory, B.OST_DuctTerminal, B.OST_FlexDuctCurves,
    B.OST_DuctInsulations, B.OST_PipeCurves, B.OST_PipeFitting, B.OST_PipeAccessory, B.OST_FlexPipeCurves,
    B.OST_PipeInsulations, B.OST_PlumbingFixtures, B.OST_Sprinklers, B.OST_MechanicalEquipment,
    B.OST_CableTray, B.OST_CableTrayFitting, B.OST_Conduit, B.OST_ConduitFitting,
    B.OST_ElectricalEquipment, B.OST_ElectricalFixtures, B.OST_LightingFixtures, B.OST_GenericModel,
]


def _sha1(pfad):
    h = hashlib.sha1()
    with open(pfad, "rb") as f:
        while True:
            block = f.read(1 << 20)
            if not block:
                break
            h.update(block)
    return h.hexdigest()[:16]


def ifc_optionen(ansicht_id=None):
    opt = DB.IFCExportOptions()
    opt.FileVersion = DB.IFCVersion.IFC4
    opt.WallAndColumnSplitting = False
    opt.ExportBaseQuantities = False
    # Interne Koordinaten: passt zu den Prüfobjekten (ebenfalls interne Koordinaten)
    opt.AddOption("SitePlacement", "3")
    opt.AddOption("ExportInternalRevitPropertySets", "false")
    opt.AddOption("StoreIFCGUID", "false")
    if ansicht_id is not None:
        opt.FilterViewId = ansicht_id
        opt.AddOption("VisibleElementsOfCurrentView", "true")
    return opt


def ifc_aus_ansicht(doc, ansicht, ordner, dateiname, pruefset=None, mit_durchbruechen=False):
    """Exportiert genau die sichtbaren Elemente der Ansicht als IFC.

    Ohne ``mit_durchbruechen`` werden die Durchbrüche nur innerhalb einer Transaktion
    ausgeblendet, die danach zurückgerollt wird; die Ansicht bleibt wie eingestellt.
    """
    t = DB.Transaction(doc, "DBK: IFC-Export")
    t.Start()
    try:
        if pruefset and not mit_durchbruechen:
            ids = [e.Id for e in sammeln.elemente_im_pruefset(doc, pruefset)]
            if ids:
                ansicht.HideElements(sammeln._liste(ids))
        doc.Regenerate()
        ok = doc.Export(ordner, dateiname, ifc_optionen(ansicht.Id))
    finally:
        t.RollBack()
    if not ok:
        raise RuntimeError("Revit hat den IFC-Export abgelehnt.")
    return os.path.join(ordner, dateiname if dateiname.lower().endswith(".ifc") else dateiname + ".ifc")


def ifc_veroeffentlichen(doc, einst, ifc_pfad, kuerzel, quelle_titel, kopieren=True):
    """Legt eine IFC-Datei unter modelle/<Kürzel>/<Hash>.ifc ab und schreibt das Ereignis.

    Die Web-App wandelt sie beim ersten Öffnen in Fragments um (modelle/<Kürzel>/<Hash>.frag).
    """
    from .einstellungen import absender
    h = _sha1(ifc_pfad)
    ordner = os.path.join(einst["projektordner"], "modelle", kuerzel)
    if not os.path.isdir(ordner):
        os.makedirs(ordner)
    ziel = os.path.join(ordner, h + ".ifc")
    if not os.path.exists(ziel):
        if kopieren:
            shutil.copyfile(ifc_pfad, ziel + ".tmp")
            os.rename(ziel + ".tmp", ziel)
        else:
            os.rename(ifc_pfad, ziel)
    elif not kopieren:
        os.remove(ifc_pfad)
    daten = {"modell": kuerzel, "datei": "modelle/%s/%s.ifc" % (kuerzel, h), "hash": h, "format": "ifc",
             "quelle": quelle_titel, "stand": time.strftime("%Y-%m-%d %H:%M"), "ebenen": sammeln.ebenen(doc),
             "groesse_mb": round(os.path.getsize(ziel) / 1e6, 2)}
    ablage = Ablage(einst["projektordner"], absender(einst))
    ablage.lade_neue()
    ablage.schreibe("modell_veroeffentlicht", None, daten)
    return daten
