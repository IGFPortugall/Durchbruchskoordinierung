# -*- coding: utf-8 -*-
"""Prüfobjekte aus dem Revit-Modell sammeln und in Objektdaten (docs/DATENFORMAT.md) umwandeln.

Koordinaten: interne Revit-Koordinaten des aktiven Modells, in mm (Z oben).
"""
from __future__ import unicode_literals

import io
import json
import os
import re

from Autodesk.Revit import DB

from . import FUSS_MM
from dbk_core import geometrie_hash
from dbk_core.ereignisse import ordnername

WIRT_KATEGORIEN = [DB.BuiltInCategory.OST_Walls, DB.BuiltInCategory.OST_Floors,
                   DB.BuiltInCategory.OST_StructuralFraming, DB.BuiltInCategory.OST_Roofs,
                   DB.BuiltInCategory.OST_StructuralColumns, DB.BuiltInCategory.OST_StructuralFoundation]


def eid(element_id):
    """ElementId als int (Revit 2024+: .Value, älter: .IntegerValue)."""
    return int(getattr(element_id, "Value", None) or element_id.IntegerValue)


def typname(element):
    t = element.Document.GetElement(element.GetTypeId())
    if t is None:
        return ""
    p = t.get_Parameter(DB.BuiltInParameter.SYMBOL_NAME_PARAM)
    return (p.AsString() if p else None) or t.Name or ""


def familienname(element):
    if isinstance(element, DB.FamilyInstance):
        return element.Symbol.Family.Name
    t = element.Document.GetElement(element.GetTypeId())
    return getattr(t, "FamilyName", "") or ""


# ------------------------------------------------------------------ Prüfset

def pruefset_pfad(projektordner, firma):
    return os.path.join(projektordner, "pruefsets", ordnername(firma) + ".json")


def pruefset_laden(projektordner, firma):
    try:
        with io.open(pruefset_pfad(projektordner, firma), "r", encoding="utf-8-sig") as f:
            return json.load(f)
    except (IOError, OSError, ValueError):
        return {"typen": []}


def pruefset_speichern(projektordner, firma, daten):
    pfad = pruefset_pfad(projektordner, firma)
    if not os.path.isdir(os.path.dirname(pfad)):
        os.makedirs(os.path.dirname(pfad))
    text = json.dumps(daten, ensure_ascii=False, indent=2, sort_keys=True)
    if isinstance(text, bytes):
        text = text.decode("utf-8")
    with io.open(pfad + ".tmp", "w", encoding="utf-8") as f:
        f.write(text)
    if os.path.exists(pfad):
        os.remove(pfad)
    os.rename(pfad + ".tmp", pfad)


def baum(doc):
    """{Kategorie: {Familie: {Typ: Anzahl}}} aller Modell-Familienexemplare."""
    ergebnis = {}
    for e in DB.FilteredElementCollector(doc).OfClass(DB.FamilyInstance).WhereElementIsNotElementType():
        c = e.Category
        if c is None or c.CategoryType != DB.CategoryType.Model:
            continue
        fam = ergebnis.setdefault(c.Name, {}).setdefault(familienname(e), {})
        t = typname(e)
        fam[t] = fam.get(t, 0) + 1
    return ergebnis


def elemente_im_pruefset(doc, pruefset):
    gesucht = set((t["kategorie"], t["familie"], t["typ"]) for t in pruefset.get("typen", []))
    if not gesucht:
        return []
    return [e for e in DB.FilteredElementCollector(doc).OfClass(DB.FamilyInstance).WhereElementIsNotElementType()
            if e.Category is not None and (e.Category.Name, familienname(e), typname(e)) in gesucht]


# ------------------------------------------------------------------ Ebenen

def ebenen(doc):
    """[{name, hoehe_mm}] aufsteigend, Höhe bezogen auf den internen Ursprung."""
    lv = [(l.ProjectElevation * FUSS_MM, l.Name) for l in DB.FilteredElementCollector(doc).OfClass(DB.Level)]
    return [{"name": n, "hoehe_mm": int(round(h))} for h, n in sorted(lv)]


def ebene_fuer(z_mm, ebenenliste, toleranz_mm=300):
    name = ebenenliste[0]["name"] if ebenenliste else ""
    for e in ebenenliste:
        if e["hoehe_mm"] <= z_mm + toleranz_mm:
            name = e["name"]
    return name


# ------------------------------------------------------------------ Wirt

def _verknuepfungen(doc):
    """[(Dokument, Transform Link->Host, Titel)] inkl. aktivem Modell."""
    ergebnis = [(doc, DB.Transform.Identity, doc.Title)]
    for li in DB.FilteredElementCollector(doc).OfClass(DB.RevitLinkInstance):
        ld = li.GetLinkDocument()
        if ld is not None:
            ergebnis.append((ld, li.GetTotalTransform(), ld.Title))
    return ergebnis


def _outline_in(bb_min, bb_max, transform):
    inv = transform.Inverse
    ecken = [inv.OfPoint(DB.XYZ(x, y, z)) for x in (bb_min.X, bb_max.X)
             for y in (bb_min.Y, bb_max.Y) for z in (bb_min.Z, bb_max.Z)]
    return DB.Outline(DB.XYZ(min(p.X for p in ecken), min(p.Y for p in ecken), min(p.Z for p in ecken)),
                      DB.XYZ(max(p.X for p in ecken), max(p.Y for p in ecken), max(p.Z for p in ecken)))


def _box_in_host(bb_min, bb_max, transform):
    ecken = [transform.OfPoint(DB.XYZ(x, y, z)) for x in (bb_min.X, bb_max.X)
             for y in (bb_min.Y, bb_max.Y) for z in (bb_min.Z, bb_max.Z)]
    return ((min(p.X for p in ecken), min(p.Y for p in ecken), min(p.Z for p in ecken)),
            (max(p.X for p in ecken), max(p.Y for p in ecken), max(p.Z for p in ecken)))


def _ist_tragend(e):
    c = eid(e.Category.Id)
    if c == int(DB.BuiltInCategory.OST_Walls):
        p = e.get_Parameter(DB.BuiltInParameter.WALL_STRUCTURAL_SIGNIFICANT)
        return bool(p and p.AsInteger() == 1)
    if c == int(DB.BuiltInCategory.OST_Floors):
        p = e.get_Parameter(DB.BuiltInParameter.FLOOR_PARAM_IS_STRUCTURAL)
        return bool(p and p.AsInteger() == 1)
    return True


ZELLE_FT = 10.0   # Rastergröße des räumlichen Index (ca. 3 m)


class WirtSuche(object):
    """Sucht das Bauteil (Wand, Decke, Unterzug …), das ein Durchbruch durchdringt – auch in Verknüpfungen.

    Alle möglichen Wirtsbauteile werden einmal mit ihrer Bounding Box (in Koordinaten
    des aktiven Modells) in ein 2D-Raster einsortiert; je Durchbruch werden dann nur
    die Bauteile der berührten Rasterzellen verglichen.
    """

    def __init__(self, doc):
        kats = [DB.ElementId(k) for k in WIRT_KATEGORIEN]
        filt = DB.ElementMulticategoryFilter(_liste(kats))
        self.raster = {}
        self.eintraege = []
        for d, t, titel in _verknuepfungen(doc):
            for w in DB.FilteredElementCollector(d).WherePasses(filt).WhereElementIsNotElementType():
                bb = w.get_BoundingBox(None)
                if bb is None:
                    continue
                mi, ma = _box_in_host(bb.Min, bb.Max, t)
                i = len(self.eintraege)
                self.eintraege.append((mi, ma, w, titel))
                for zx in range(int(mi[0] // ZELLE_FT), int(ma[0] // ZELLE_FT) + 1):
                    for zy in range(int(mi[1] // ZELLE_FT), int(ma[1] // ZELLE_FT) + 1):
                        self.raster.setdefault((zx, zy), []).append(i)

    def finde(self, element):
        if isinstance(element, DB.FamilyInstance) and element.Host is not None and element.Host.Category is not None:
            return self._daten(element.Host, element.Document.Title)
        bb = element.get_BoundingBox(None)
        if bb is None:
            return {}
        mi, ma = (bb.Min.X, bb.Min.Y, bb.Min.Z), (bb.Max.X, bb.Max.Y, bb.Max.Z)
        kandidaten = set()
        for zx in range(int(mi[0] // ZELLE_FT), int(ma[0] // ZELLE_FT) + 1):
            for zy in range(int(mi[1] // ZELLE_FT), int(ma[1] // ZELLE_FT) + 1):
                kandidaten.update(self.raster.get((zx, zy), ()))
        bester, beste_menge = None, 0.0
        for i in kandidaten:
            wmi, wma, w, titel = self.eintraege[i]
            menge = 1.0
            for k in range(3):
                d = min(ma[k], wma[k]) - max(mi[k], wmi[k])
                if d <= 0:
                    menge = 0.0
                    break
                menge *= d
            if menge > beste_menge:
                bester, beste_menge = (w, titel), menge
        return self._daten(bester[0], bester[1]) if bester else {}

    @staticmethod
    def _daten(w, titel):
        d = {"kategorie": w.Category.Name, "tragend": _ist_tragend(w), "typ": typname(w), "modell": titel}
        t = w.Document.GetElement(w.GetTypeId())
        fr = t.get_Parameter(DB.BuiltInParameter.FIRE_RATING) if t else None
        if fr and fr.AsString():
            d["feuerwiderstand"] = fr.AsString()
        return d


def _ueberlappung(ol, bb):
    dx = min(ol.MaximumPoint.X, bb.Max.X) - max(ol.MinimumPoint.X, bb.Min.X)
    dy = min(ol.MaximumPoint.Y, bb.Max.Y) - max(ol.MinimumPoint.Y, bb.Min.Y)
    dz = min(ol.MaximumPoint.Z, bb.Max.Z) - max(ol.MinimumPoint.Z, bb.Min.Z)
    return max(dx, 0) * max(dy, 0) * max(dz, 0)


def _liste(ids):
    from System.Collections.Generic import List
    l = List[DB.ElementId]()
    for i in ids:
        l.Add(i)
    return l


# ------------------------------------------------------------------ Objektdaten

_RUND = re.compile(r"(rund|kreis|kernbohr|Ø|bohrung)", re.I)


def _param_mm(e, namen):
    for quelle in (e, e.Document.GetElement(e.GetTypeId())):
        if quelle is None:
            continue
        for n in namen:
            p = quelle.LookupParameter(n)
            if p is not None and p.StorageType == DB.StorageType.Double and p.AsDouble() > 0:
                return p.AsDouble() * FUSS_MM
    return None


def objekt_id(modellkuerzel, element):
    return "%s:%s" % (modellkuerzel, element.UniqueId)


def objektdaten(element, modellkuerzel, firmenkuerzel, ebenenliste, wirtsuche):
    bb = element.get_BoundingBox(None)
    if bb is None:
        return None
    gmin = [int(round(v * FUSS_MM)) for v in (bb.Min.X, bb.Min.Y, bb.Min.Z)]
    gmax = [int(round(v * FUSS_MM)) for v in (bb.Max.X, bb.Max.Y, bb.Max.Z)]
    fam, typ = familienname(element), typname(element)
    wirt = wirtsuche.finde(element) if wirtsuche else {}
    decke = wirt.get("kategorie") in ("Geschossdecken", "Dächer", "Floors", "Roofs")
    dx, dy, dz = gmax[0] - gmin[0], gmax[1] - gmin[1], gmax[2] - gmin[2]

    durchmesser = _param_mm(element, ["Durchmesser", "DN", "Diameter", "D"])
    rund = bool(durchmesser) or bool(_RUND.search(fam + " " + typ))
    if rund:
        d = int(round(durchmesser or (min(dx, dy) if decke else dz)))
        masse, groesse, form = {"durchmesser": d}, "Ø%d" % d, "rund"
        flaeche = 3.14159 * (d / 2000.0) ** 2
    else:
        b = _param_mm(element, ["Breite", "Width", "b"])
        h = _param_mm(element, ["Höhe", "Hoehe", "Height", "h"])
        if decke:
            b, h = b or max(dx, dy), h or min(dx, dy)
        else:
            b, h = b or max(dx, dy), h or dz
        b, h = int(round(b)), int(round(h))
        masse, groesse, form = {"breite": b, "hoehe": h}, "%d×%d" % (b, h), "rechteck"
        flaeche = b * h / 1e6

    geometrie = {"min": gmin, "max": gmax, "form": form, "masse": masse}
    mark = element.get_Parameter(DB.BuiltInParameter.ALL_MODEL_MARK)
    nummer = (mark.AsString() if mark else None) or "%s-%d" % (firmenkuerzel, eid(element.Id))
    ifc = element.get_Parameter(DB.BuiltInParameter.IFC_GUID)
    ebene = ebene_fuer(gmin[2], ebenenliste)
    okff = next((e["hoehe_mm"] for e in ebenenliste if e["name"] == ebene), 0)
    return {
        "nummer": nummer,
        "kategorie": element.Category.Name, "familie": fam, "typ": typ,
        "ebene": ebene,
        "revit_unique_id": element.UniqueId, "revit_id": eid(element.Id),
        "ifc_guid": (ifc.AsString() if ifc else None) or "",
        "modell": modellkuerzel, "revit_modell": element.Document.Title,
        "geometrie": geometrie, "groesse": groesse, "uk_mm": gmin[2] - okff,   # UK über Ebene
        "flaeche_m2": round(flaeche, 3),
        "wirt": wirt,
        "geometrie_hash": geometrie_hash(geometrie),
    }
