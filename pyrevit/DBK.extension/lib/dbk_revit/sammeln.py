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
# Vorrang bei der Wirt-Suche: senkrechte Durchbrüche sitzen in Decken/Dächern/Bodenplatten, waagerechte in Wänden
DECKEN_WIRTE = set(int(k) for k in (DB.BuiltInCategory.OST_Floors, DB.BuiltInCategory.OST_Roofs,
                                    DB.BuiltInCategory.OST_StructuralFoundation))
WAND_WIRTE = set(int(k) for k in (DB.BuiltInCategory.OST_Walls,))


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

def alle_ebenen(doc):
    """Alle Revit-Ebenen: [{name, hoehe_mm}] aufsteigend, Höhe bezogen auf den internen Ursprung."""
    lv = [(l.ProjectElevation * FUSS_MM, l.Name) for l in DB.FilteredElementCollector(doc).OfClass(DB.Level)]
    return [{"name": n, "hoehe_mm": int(round(h))} for h, n in sorted(lv)]


def ebenen(doc, geschosse=None):
    """Ebenen, die als Geschoss zählen (Liste von Namen; leer/None = alle Ebenen)."""
    alle = alle_ebenen(doc)
    if geschosse:
        gew = set(geschosse)
        auswahl = [e for e in alle if e["name"] in gew]
        if auswahl:
            return auswahl
    return alle


_HILFSEBENE = re.compile(r"(\bUK\b|\bOK\b|UKRD|OKRD|OKRB|UKRB|\bRD\b|\bRB\b|\bFBH\b|Hohlk|\bNN\b|Fundament|Attika|"
                         r"\bOKFF\b|\bUKFF\b|Rohdecke|Rohboden|\bOKRF\b|Unterkante|Oberkante|\bFFB\b)", re.I)


def geschoss_vorschlag(doc):
    """Ebenen ohne typische Hilfsbezeichnungen (OK, UK, RD, RB, FBH, Hohlkörper …) als Geschoss vorschlagen."""
    namen = [e["name"] for e in alle_ebenen(doc)]
    vorschlag = [n for n in namen if not _HILFSEBENE.search(n)]
    return vorschlag or namen


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

    def finde(self, element, box=None, bevorzugt=None):
        """box: (min, max) in Fuß – die echte Öffnung; ohne: Begrenzungsbox des Elements.
        bevorzugt: Kategorie-IDs, die zuerst gelten (Decken-Durchbruch → Decken/Dächer, Wand → Wände)."""
        if isinstance(element, DB.FamilyInstance) and element.Host is not None and element.Host.Category is not None:
            return self._daten(element.Host, element.Document.Title)
        if box is None:
            bb = element.get_BoundingBox(None)
            if bb is None:
                return {}
            box = ((bb.Min.X, bb.Min.Y, bb.Min.Z), (bb.Max.X, bb.Max.Y, bb.Max.Z))
        mi, ma = box
        kandidaten = set()
        for zx in range(int(mi[0] // ZELLE_FT), int(ma[0] // ZELLE_FT) + 1):
            for zy in range(int(mi[1] // ZELLE_FT), int(ma[1] // ZELLE_FT) + 1):
                kandidaten.update(self.raster.get((zx, zy), ()))
        bester, beste_menge, vorrang = None, 0.0, False
        for i in kandidaten:
            wmi, wma, w, titel = self.eintraege[i]
            menge = 1.0
            for k in range(3):
                d = min(ma[k], wma[k]) - max(mi[k], wmi[k])
                if d <= 0:
                    menge = 0.0
                    break
                menge *= d
            if menge <= 0:
                continue
            ist_vorrang = bool(bevorzugt) and w.Category is not None and eid(w.Category.Id) in bevorzugt
            if (ist_vorrang and not vorrang) or (ist_vorrang == vorrang and menge > beste_menge):
                bester, beste_menge, vorrang = (w, titel), menge, ist_vorrang
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
    """(Wert in mm, Parametername) des ersten vorhandenen Längen-Parameters > 0 – Exemplar vor Typ."""
    for quelle in (e, e.Document.GetElement(e.GetTypeId())):
        if quelle is None:
            continue
        for n in namen:
            p = quelle.LookupParameter(n)
            if p is not None and p.StorageType == DB.StorageType.Double and p.AsDouble() > 0:
                return p.AsDouble() * FUSS_MM, n
    return None, None


# Welche Parameter die Öffnung beschreiben – „Gesamt …“ (Öffnung inkl. Abstände) vor dem Kern-Maß.
# Im Prüfset unter „masse_parameter“ überschreibbar, z. B. {"breite": ["Öffnungsbreite"]}.
MASSE_PARAMETER = {
    "breite": ["Gesamt Breite", "Breite", "Width", "b"],
    "hoehe": ["Gesamt Höhe", "Höhe", "Hoehe", "Height", "h"],
    "laenge": ["Gesamt Länge", "Länge", "Laenge", "Length", "l"],
    "tiefe": ["Gesamt Tiefe", "Tiefe", "Depth", "t"],
    "durchmesser": ["Gesamt Durchmesser", "Durchmesser", "DN", "Diameter", "D"],
}


def _masse_parameter(pruefset):
    eigen = (pruefset or {}).get("masse_parameter") or {}
    return dict((k, list(eigen.get(k) or []) + v) for k, v in MASSE_PARAMETER.items())


def koerper_box(element):
    """Box (min, max in Fuß) aus den Volumenkörpern – ohne Symbol-/Modelllinien der Familie.

    Durchbruchfamilien enthalten oft Linien zwischen den Ebenen; die Begrenzungsbox ist dann
    mehrere Meter hoch. Fällt auf die Begrenzungsbox zurück, wenn es keine Körper gibt."""
    lo, hi, _ = koerper_boxen(element)
    if lo is None:
        return None
    return lo, hi


def koerper_boxen(element):
    """(min, max, lokal): achsparallele Box in Projektkoordinaten (Fuß) und die gedrehte Box im
    Koordinatensystem des Exemplars – damit der Viewer schräge Wände und runde Deckendurchbrüche
    richtig zeigt. lokal = {"mitte_mm", "achsen" (3 Einheitsvektoren), "groesse_mm"} oder None."""
    opt = DB.Options()
    opt.DetailLevel = DB.ViewDetailLevel.Fine
    opt.IncludeNonVisibleObjects = False
    lo, hi = [1e18] * 3, [-1e18] * 3
    llo, lhi = [1e18] * 3, [-1e18] * 3
    inst = element.GetTransform() if isinstance(element, DB.FamilyInstance) else DB.Transform.Identity
    zurueck = inst.Inverse

    def merken(p, a, b):
        for k, v in enumerate((p.X, p.Y, p.Z)):
            a[k] = min(a[k], v)
            b[k] = max(b[k], v)

    def koerper(geo, trafo):
        if geo is None:
            return
        for g in geo:
            if isinstance(g, DB.GeometryInstance):
                koerper(g.GetSymbolGeometry(), trafo.Multiply(g.Transform))
            elif isinstance(g, DB.Solid) and g.Volume > 1e-9:
                bb = g.GetBoundingBox()
                t = trafo.Multiply(bb.Transform)
                for x in (bb.Min.X, bb.Max.X):
                    for y in (bb.Min.Y, bb.Max.Y):
                        for z in (bb.Min.Z, bb.Max.Z):
                            p = t.OfPoint(DB.XYZ(x, y, z))
                            merken(p, lo, hi)
                            merken(zurueck.OfPoint(p), llo, lhi)

    try:
        koerper(element.get_Geometry(opt), DB.Transform.Identity)
    except Exception:
        pass
    if lo[0] < 1e17:
        mitte = inst.OfPoint(DB.XYZ(*[(llo[k] + lhi[k]) / 2.0 for k in range(3)]))
        lokal = {"mitte_mm": [int(round(v * FUSS_MM)) for v in (mitte.X, mitte.Y, mitte.Z)],
                 "achsen": [[round(v, 4) for v in (a.X, a.Y, a.Z)] for a in (inst.BasisX, inst.BasisY, inst.BasisZ)],
                 "groesse_mm": [int(round((lhi[k] - llo[k]) * FUSS_MM)) for k in range(3)]}
        return tuple(lo), tuple(hi), lokal
    bb = element.get_BoundingBox(None)
    if bb is None:
        return None, None, None
    return (bb.Min.X, bb.Min.Y, bb.Min.Z), (bb.Max.X, bb.Max.Y, bb.Max.Z), None


def objekt_id(modellkuerzel, element):
    return "%s:%s" % (modellkuerzel, element.UniqueId)


def objektdaten(element, modellkuerzel, firmenkuerzel, ebenenliste, wirtsuche, pruefset=None):
    lo, hi, lokal = koerper_boxen(element)
    if lo is None:
        return None
    box = (lo, hi)
    gmin = [int(round(v * FUSS_MM)) for v in box[0]]
    gmax = [int(round(v * FUSS_MM)) for v in box[1]]
    fam, typ = familienname(element), typname(element)
    dx, dy, dz = gmax[0] - gmin[0], gmax[1] - gmin[1], gmax[2] - gmin[2]
    namen = _masse_parameter(pruefset)
    quelle = {}

    def wert(art):
        v, n = _param_mm(element, namen[art])
        if v:
            quelle[art] = n
            return int(round(v))
        return None

    # Decke (senkrechter Durchbruch): hat Länge statt Höhe, oder Körper flacher als breit, oder Wirt ist Decke/Dach
    hoehe, laenge = wert("hoehe"), wert("laenge")
    vermutlich_decke = (laenge is not None and hoehe is None) or (hoehe is None and laenge is None and dz < min(dx, dy))
    wirt = wirtsuche.finde(element, box, DECKEN_WIRTE if vermutlich_decke else WAND_WIRTE) if wirtsuche else {}
    decke = (laenge is not None and hoehe is None) or \
        wirt.get("kategorie") in ("Geschossdecken", "Dächer", "Floors", "Roofs") or \
        (hoehe is None and laenge is None and dz < min(dx, dy))
    durchmesser = wert("durchmesser")
    rund = bool(durchmesser) or bool(_RUND.search(fam + " " + typ))
    tiefe = wert("tiefe") or (dz if decke else min(dx, dy))
    if rund:
        d = durchmesser or (min(dx, dy) if decke else min(max(dx, dy), dz))
        masse, groesse, form = {"durchmesser": d, "tiefe": tiefe}, "Ø%d" % d, "rund"
        flaeche = 3.14159 * (d / 2000.0) ** 2
    elif decke:
        b = wert("breite") or max(dx, dy)
        l = laenge or min(dx, dy)
        masse, groesse, form = {"breite": b, "laenge": l, "tiefe": tiefe}, "%d×%d" % (b, l), "rechteck"
        flaeche = b * l / 1e6
    else:
        b = wert("breite") or max(dx, dy)
        h = hoehe or dz
        masse, groesse, form = {"breite": b, "hoehe": h, "tiefe": tiefe}, "%d×%d" % (b, h), "rechteck"
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
        "ok_mm": gmax[2] - okff,
        "lage": "decke" if decke else "wand",
        "masse_quelle": quelle,                 # welcher Revit-Parameter welches Maß geliefert hat
        "ausrichtung": lokal,                   # gedrehte Box (Exemplar-Achsen) für die Darstellung
        "flaeche_m2": round(flaeche, 3),
        "wirt": wirt,
        "geometrie_hash": geometrie_hash(geometrie),
    }
