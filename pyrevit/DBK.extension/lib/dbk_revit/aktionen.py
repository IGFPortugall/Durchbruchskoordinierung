# -*- coding: utf-8 -*-
"""Einreichen und Modell veröffentlichen – ohne Oberfläche, damit auch testbar.

Beide Funktionen ändern das Revit-Modell nicht; sie schreiben nur in den Projektordner.
"""
from __future__ import unicode_literals

import hashlib
import io
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
    ebenen = sammeln.ebenen(doc, pruefset.get("geschosse"))
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


def einreichen_ausfuehren(einst, plan, rundenname=None, frist=None, auswahl=None, entfallen=True, stand=None):
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
        ablage.schreibe("eingereicht", oid, {"objekt": plan.objekte[oid], "runde": runde, "stand": stand})
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


FBX, IFC = "fbx", "ifc"
FORMAT_TEXT = {
    FBX: "FBX – schnell (Revit-eigener 3D-Export). Geometrie plus Kategorie, Familie, Typ, Ebene, System und "
         "Größe aus Revit. Empfohlen für Trassen, Kanäle und Rohre.",
    IFC: "IFC – langsam, dafür mit allen IFC-Eigenschaftssätzen (Psets). Sinnvoll, wenn andere Programme das "
         "Modell weiterverwenden sollen.",
}


def ifc_optionen(ansicht_id=None):
    """Auf Tempo eingestellt: IFC2x3, grobe Tessellierung, keine Mengen/Bounding Boxes/Räume."""
    opt = DB.IFCExportOptions()
    opt.FileVersion = DB.IFCVersion.IFC2x3CV2
    opt.WallAndColumnSplitting = False
    opt.ExportBaseQuantities = False
    opt.SpaceBoundaryLevel = 0
    # Interne Koordinaten: passt zu den Prüfobjekten (ebenfalls interne Koordinaten)
    opt.AddOption("SitePlacement", "3")
    opt.AddOption("ExportInternalRevitPropertySets", "false")
    opt.AddOption("ExportIFCCommonPropertySets", "true")
    opt.AddOption("ExportSchedulesAsPsets", "false")
    opt.AddOption("ExportRoomsInView", "false")
    opt.AddOption("Export2DElements", "false")
    opt.AddOption("ExportBoundingBox", "false")
    opt.AddOption("ExportSolidModelRep", "false")
    opt.AddOption("UseActiveViewGeometry", "false")
    opt.AddOption("TessellationLevelOfDetail", "0.25")
    opt.AddOption("StoreIFCGUID", "false")
    if ansicht_id is not None:
        opt.FilterViewId = ansicht_id
        opt.AddOption("VisibleElementsOfCurrentView", "true")
    return opt


def _mit_ausgeblendeten_durchbruechen(doc, ansicht, pruefset, mit_durchbruechen, export, verstecken=None):
    """Führt ``export()`` aus, während die Durchbrüche (und ``verstecken``) in der Ansicht ausgeblendet sind.

    Die Transaktion wird immer zurückgerollt – die Ansicht bleibt unverändert.
    """
    t = DB.Transaction(doc, "DBK: Export")
    t.Start()
    try:
        ids = list(verstecken or [])
        if pruefset and not mit_durchbruechen:
            ids += [e.Id for e in sammeln.elemente_im_pruefset(doc, pruefset)]
        ids = [i for i in ids if not doc.GetElement(i).IsHidden(ansicht)]
        if ids:
            ansicht.HideElements(sammeln._liste(ids))
        doc.Regenerate()
        return export()
    finally:
        t.RollBack()


def ifc_aus_ansicht(doc, ansicht, ordner, dateiname, pruefset=None, mit_durchbruechen=False, verstecken=None):
    """Exportiert genau die sichtbaren Elemente der Ansicht als IFC (ohne Durchbrüche)."""
    ok = _mit_ausgeblendeten_durchbruechen(doc, ansicht, pruefset, mit_durchbruechen,
                                           lambda: doc.Export(ordner, dateiname, ifc_optionen(ansicht.Id)), verstecken)
    if not ok:
        raise RuntimeError("Revit hat den IFC-Export abgelehnt.")
    return os.path.join(ordner, dateiname if dateiname.lower().endswith(".ifc") else dateiname + ".ifc")


def fbx_aus_ansicht(doc, ansicht, ordner, dateiname, pruefset=None, verstecken=None):
    """Revit-eigener FBX-Export der 3D-Ansicht (ohne Durchbrüche). Deutlich schneller als IFC."""
    opt = DB.FBXExportOptions()
    opt.UseLevelsOfDetail = True
    opt.LevelsOfDetailValue = 4
    opt.WithoutBoundaryEdges = True
    opt.StopOnError = False
    ansichten = DB.ViewSet()
    ansichten.Insert(ansicht)
    ok = _mit_ausgeblendeten_durchbruechen(doc, ansicht, pruefset, False,
                                           lambda: doc.Export(ordner, dateiname, ansichten, opt), verstecken)
    pfad = os.path.join(ordner, dateiname if dateiname.lower().endswith(".fbx") else dateiname + ".fbx")
    if ok is False or not os.path.isfile(pfad):
        raise RuntimeError("Revit hat den FBX-Export abgelehnt.")
    return pfad


def _param_text(e, bip):
    p = e.get_Parameter(bip)
    if p is None or not p.HasValue:
        return None
    return p.AsString() or p.AsValueString()


def bauteil_infos(doc, ansicht, pruefset=None, fortschritt=None):
    """Kategorie, Familie, Typ, Ebene, System, Größe und Bounding Box (mm) der sichtbaren Bauteile.

    Für FBX: der Viewer nimmt daraus Kategorien, Eigenschaften und die Ausrichtung.
    """
    durch = set(sammeln.eid(e.Id) for e in sammeln.elemente_im_pruefset(doc, pruefset or {}))
    elemente = [e for e in DB.FilteredElementCollector(doc, ansicht.Id).WhereElementIsNotElementType()
                if e.Category is not None and e.Category.CategoryType == DB.CategoryType.Model
                and not isinstance(e, DB.RevitLinkInstance) and sammeln.eid(e.Id) not in durch]
    return _infos(doc, elemente, None, "", fortschritt)


def link_infos(doc, ansicht, link, fortschritt=None):
    """Wie bauteil_infos, aber für die in der Ansicht sichtbaren Elemente einer Verknüpfung (Host-Koordinaten)."""
    ldoc = link.GetLinkDocument()
    if ldoc is None:
        return {"bauteile": {}, "bbox_mm": None}
    elemente = [e for e in DB.FilteredElementCollector(doc, ansicht.Id, link.Id).WhereElementIsNotElementType()
                if e.Category is not None and e.Category.CategoryType == DB.CategoryType.Model]
    return _infos(ldoc, elemente, link.GetTotalTransform(), "L%s:" % sammeln.eid(link.Id), fortschritt)


def infos_vereinen(teile):
    infos, gmin, gmax = {}, [1e18] * 3, [-1e18] * 3
    for t in teile:
        infos.update(t["bauteile"])
        if t.get("bbox_mm"):
            b = t["bbox_mm"]
            gmin = [min(gmin[k], b[k]) for k in range(3)]
            gmax = [max(gmax[k], b[k + 3]) for k in range(3)]
    return {"bauteile": infos, "bbox_mm": gmin + gmax if infos else None}


def _box(bb, transform):
    if transform is None:
        return (bb.Min.X, bb.Min.Y, bb.Min.Z, bb.Max.X, bb.Max.Y, bb.Max.Z)
    ecken = [transform.OfPoint(DB.XYZ(x, y, z)) for x in (bb.Min.X, bb.Max.X)
             for y in (bb.Min.Y, bb.Max.Y) for z in (bb.Min.Z, bb.Max.Z)]
    return (min(p.X for p in ecken), min(p.Y for p in ecken), min(p.Z for p in ecken),
            max(p.X for p in ecken), max(p.Y for p in ecken), max(p.Z for p in ecken))


def _infos(doc, elemente, transform, praefix, fortschritt):
    ebenen = dict((sammeln.eid(l.Id), l.Name) for l in DB.FilteredElementCollector(doc).OfClass(DB.Level))
    infos, gmin, gmax = {}, [1e18] * 3, [-1e18] * 3
    for i, e in enumerate(elemente):
        if fortschritt and i % 2000 == 0:
            fortschritt(i, len(elemente))
        bb = e.get_BoundingBox(None)
        if bb is None:
            continue
        b = [int(round(v * FUSS)) for v in _box(bb, transform)]
        for k in range(3):
            gmin[k] = min(gmin[k], b[k])
            gmax[k] = max(gmax[k], b[k + 3])
        lvl = getattr(e, "LevelId", None)
        if lvl is None or lvl == DB.ElementId.InvalidElementId:
            p = e.get_Parameter(DB.BuiltInParameter.RBS_START_LEVEL_PARAM) or \
                e.get_Parameter(DB.BuiltInParameter.FAMILY_LEVEL_PARAM)
            lvl = p.AsElementId() if p is not None and p.StorageType == DB.StorageType.ElementId else None
        d = {"k": e.Category.Name, "f": sammeln.familienname(e), "t": sammeln.typname(e), "b": b}
        if lvl is not None and lvl != DB.ElementId.InvalidElementId:
            d["e"] = ebenen.get(sammeln.eid(lvl))
        s = _param_text(e, DB.BuiltInParameter.RBS_SYSTEM_NAME_PARAM)
        if s:
            d["s"] = s
        g = _param_text(e, DB.BuiltInParameter.RBS_CALCULATED_SIZE)
        if g:
            d["g"] = g
        infos[praefix + str(sammeln.eid(e.Id))] = d
    return {"bauteile": infos, "bbox_mm": gmin + gmax if infos else None}


FUSS = 304.8


def modell_version(doc):
    """Kennung des gespeicherten Modellstands (ändert sich bei Speichern/Synchronisieren)."""
    try:
        v = DB.Document.GetDocumentVersion(doc)
        return "%s-%s" % (v.VersionGUID, v.NumberOfSaves)
    except Exception:
        return None


def _kopieren(quelle, ziel, fortschritt=None):
    """Kopiert in Blöcken mit Fortschritt (MB). Bei Fehler wird die halbe Datei entfernt."""
    tmp = ziel + ".tmp"
    gesamt = os.path.getsize(quelle)
    try:
        with open(quelle, "rb") as q:
            with open(tmp, "wb") as z:
                kopiert = 0
                while True:
                    block = q.read(4 << 20)
                    if not block:
                        break
                    z.write(block)
                    kopiert += len(block)
                    if fortschritt:
                        fortschritt(kopiert, gesamt)
        if os.path.exists(ziel):
            os.remove(tmp)
        else:
            os.rename(tmp, ziel)
    except Exception:
        if os.path.exists(tmp):
            try:
                os.remove(tmp)
            except OSError:
                pass
        raise


def datei_veroeffentlichen(doc, einst, pfad, kuerzel, quelle_titel, format_, geschosse=None, zusatz=None,
                           version=None, fortschritt=None, name=None):
    """Legt eine Modelldatei unter modelle/<Kürzel>/<Hash>.<format> ab und schreibt das Ereignis.

    zusatz: optionale Bauteil-Infos (dict) – werden als <Hash>.json daneben gelegt (FBX).
    IFC wandelt die Web-App beim ersten Öffnen in Fragments um.
    """
    import json
    from .einstellungen import absender
    h = _sha1(pfad)
    ordner = os.path.join(einst["projektordner"], "modelle", kuerzel)
    if not os.path.isdir(ordner):
        os.makedirs(ordner)
    ziel = os.path.join(ordner, "%s.%s" % (h, format_))
    if not os.path.exists(ziel):
        _kopieren(pfad, ziel, fortschritt)
    daten = {"modell": kuerzel, "datei": "modelle/%s/%s.%s" % (kuerzel, h, format_), "hash": h, "format": format_,
             "quelle": quelle_titel, "stand": time.strftime("%Y-%m-%d %H:%M"),
             "ebenen": sammeln.ebenen(doc, geschosse), "groesse_mb": round(os.path.getsize(ziel) / 1e6, 2)}
    if version:
        daten["revit_version"] = version
    if name:
        daten["name"] = name
    if zusatz is not None:
        info = os.path.join(ordner, "%s.json" % h)
        text = json.dumps(zusatz, ensure_ascii=False, separators=(",", ":"))
        if isinstance(text, bytes):
            text = text.decode("utf-8")
        with io.open(info + ".tmp", "w", encoding="utf-8") as f:
            f.write(text)
        if os.path.exists(info):
            os.remove(info + ".tmp")
        else:
            os.rename(info + ".tmp", info)
        daten["info"] = "modelle/%s/%s.json" % (kuerzel, h)
    ablage = Ablage(einst["projektordner"], absender(einst))
    ablage.lade_neue()
    ablage.schreibe("modell_veroeffentlicht", None, daten)
    return daten


def ifc_veroeffentlichen(doc, einst, ifc_pfad, kuerzel, quelle_titel, kopieren=True):
    """Kompatibel zum bisherigen Aufruf: IFC-Datei veröffentlichen."""
    return datei_veroeffentlichen(doc, einst, ifc_pfad, kuerzel, quelle_titel, IFC)
