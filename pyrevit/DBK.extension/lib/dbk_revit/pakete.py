# -*- coding: utf-8 -*-
"""Pakete: was beim Einreichen rausgeht. Jedes Paket hat eine eigene 3D-Ansicht.

Durchbruch-Paket ("durchbrueche"): Bauteile des Prüfsets, gefiltert nach Ebenen und
Familien/Typen; einzelne Exemplare abwählbar ("aus"). Sie werden als Prüfobjekte
eingereicht (optional zusätzlich als IFC).

TGA-Paket ("tga"): Gewerke-Kategorien, optional auf Ebenen begrenzt (Schnittbox in
der Höhe). Exportiert wird als IFC genau, was in der Ansicht sichtbar ist – ohne Durchbrüche.

Gespeichert in pruefsets/<Firma>.json unter "pakete".
"""
from __future__ import unicode_literals

import uuid

from Autodesk.Revit import DB

from . import FUSS_MM, sammeln
from .sammeln import _liste, eid

DURCHBRUECHE = "durchbrueche"
TGA = "tga"
B = DB.BuiltInCategory

GEWERKE = [
    ("Lüftung", [B.OST_DuctCurves, B.OST_DuctFitting, B.OST_DuctAccessory, B.OST_DuctTerminal,
                 B.OST_FlexDuctCurves, B.OST_DuctInsulations]),
    ("Rohrleitungen", [B.OST_PipeCurves, B.OST_PipeFitting, B.OST_PipeAccessory, B.OST_FlexPipeCurves,
                       B.OST_PipeInsulations]),
    ("Sanitär, Sprinkler", [B.OST_PlumbingFixtures, B.OST_Sprinklers]),
    ("Geräte", [B.OST_MechanicalEquipment]),
    ("Elektro", [B.OST_CableTray, B.OST_CableTrayFitting, B.OST_Conduit, B.OST_ConduitFitting,
                 B.OST_ElectricalEquipment, B.OST_ElectricalFixtures, B.OST_LightingFixtures]),
    ("Allgemeine Modelle", [B.OST_GenericModel]),
]
GEWERK_NAMEN = [g[0] for g in GEWERKE]


# ------------------------------------------------------------------ Daten

def laden(ordner, firma):
    return sammeln.pruefset_laden(ordner, firma).get("pakete", [])


def speichern(ordner, firma, pakete):
    ps = sammeln.pruefset_laden(ordner, firma)
    ps["pakete"] = pakete
    ps.pop("exporte", None)
    sammeln.pruefset_speichern(ordner, firma, ps)


def neu(art, name, kuerzel):
    return {"id": uuid.uuid4().hex[:8], "name": name, "art": art, "kuerzel": kuerzel, "aktiv": True,
            "ebenen": [], "familien": [], "gewerke": list(GEWERK_NAMEN) if art == TGA else [],
            "aus": [], "auch_ifc": False}


def ansicht_name(paket):
    return "DBK Paket – %s" % paket["name"]


def filter_text(paket):
    teile = []
    if paket["art"] == TGA:
        g = paket.get("gewerke") or []
        teile.append("alle Gewerke" if len(g) == len(GEWERK_NAMEN) else ", ".join(g) or "keine Gewerke")
    else:
        f = paket.get("familien") or []
        teile.append("alle Familien" if not f else "%d Typen" % len(f))
    e = paket.get("ebenen") or []
    teile.append("alle Ebenen" if not e else ", ".join(e))
    if paket.get("aus"):
        teile.append("%d abgewählt" % len(paket["aus"]))
    return " · ".join(teile)


# ------------------------------------------------------------------ Durchbruch-Pakete

def objekte(paket, plan, mit_aus=False):
    """Objekt-IDs des Plans, die zum Durchbruch-Paket gehören."""
    ebenen = set(paket.get("ebenen") or [])
    familien = set(tuple(f) for f in (paket.get("familien") or []))
    aus = set(paket.get("aus") or [])
    ergebnis = []
    for oid, d in plan.objekte.items():
        if ebenen and d.get("ebene") not in ebenen:
            continue
        if familien and (d.get("familie"), d.get("typ")) not in familien:
            continue
        if not mit_aus and oid in aus:
            continue
        ergebnis.append(oid)
    return ergebnis


def zaehlen(paket, plan):
    from .aktionen import NEU, GEOMETRIE, DATEN, UNVERAENDERT
    z = {NEU: 0, GEOMETRIE: 0, DATEN: 0, UNVERAENDERT: 0}
    for oid in objekte(paket, plan):
        z[plan.zustand[oid]] = z.get(plan.zustand[oid], 0) + 1
    return z


# ------------------------------------------------------------------ Ansichten

def _ansicht(doc, paket):
    name = ansicht_name(paket)
    for v in DB.FilteredElementCollector(doc).OfClass(DB.View3D):
        if not v.IsTemplate and v.Name == name:
            return v
    return None


def ansicht_finden(doc, paket):
    return _ansicht(doc, paket)


def _grundeinstellung(doc, v, sichtbare_kategorien):
    if v.ViewTemplateId != DB.ElementId.InvalidElementId:
        v.ViewTemplateId = DB.ElementId.InvalidElementId
    v.DetailLevel = DB.ViewDetailLevel.Medium
    for kat in doc.Settings.Categories:
        if not v.CanCategoryBeHidden(kat.Id):
            continue
        if kat.CategoryType == DB.CategoryType.Model:
            v.SetCategoryHidden(kat.Id, eid(kat.Id) not in sichtbare_kategorien)
        elif kat.CategoryType == DB.CategoryType.Annotation:
            v.SetCategoryHidden(kat.Id, True)
    links = DB.ElementId(B.OST_RvtLinks)
    if v.CanCategoryBeHidden(links):
        v.SetCategoryHidden(links, True)


def _orange(doc):
    from .ansichten import _vollfarbe
    o = DB.OverrideGraphicSettings()
    o.SetProjectionLineColor(DB.Color(133, 79, 11))
    voll = _vollfarbe(doc)
    if voll is not None:
        o.SetSurfaceForegroundPatternId(voll).SetSurfaceForegroundPatternColor(DB.Color(239, 159, 39))
    return o


def _box(punkte_min, punkte_max, rand_ft):
    b = DB.BoundingBoxXYZ()
    b.Min = DB.XYZ(min(p.X for p in punkte_min) - rand_ft, min(p.Y for p in punkte_min) - rand_ft,
                   min(p.Z for p in punkte_min) - rand_ft)
    b.Max = DB.XYZ(max(p.X for p in punkte_max) + rand_ft, max(p.Y for p in punkte_max) + rand_ft,
                   max(p.Z for p in punkte_max) + rand_ft)
    return b


def ansicht_aufbauen(doc, paket, plan, pruefset):
    """Legt die Paket-Ansicht an bzw. bringt sie auf den Stand des Pakets. Gibt die Ansicht zurück."""
    durch_ids = dict((oid, plan.element_ids[oid]) for oid in plan.objekte)
    durch_kats = set(eid(doc.GetElement(i).Category.Id) for i in durch_ids.values())
    with DB.Transaction(doc, "DBK: Paket-Ansicht") as t:
        t.Start()
        v = _ansicht(doc, paket)
        if v is None:
            vft = next(x for x in DB.FilteredElementCollector(doc).OfClass(DB.ViewFamilyType)
                       if x.ViewFamily == DB.ViewFamily.ThreeDimensional)
            v = DB.View3D.CreateIsometric(doc, vft.Id)
            v.Name = ansicht_name(paket)
        if v.IsTemporaryHideIsolateActive():
            v.DisableTemporaryViewMode(DB.TemporaryViewMode.TemporaryHideIsolate)
        orange = _orange(doc)

        if paket["art"] == DURCHBRUECHE:
            _grundeinstellung(doc, v, durch_kats)
            drin = set(objekte(paket, plan))
            # alles in den Durchbruch-Kategorien erst einblenden, dann Nicht-Mitglieder ausblenden
            alle = [e for e in DB.FilteredElementCollector(doc).WhereElementIsNotElementType()
                    if e.Category is not None and eid(e.Category.Id) in durch_kats and e.CanBeHidden(v)]
            versteckt = [e.Id for e in alle if e.IsHidden(v)]
            if versteckt:
                v.UnhideElements(_liste(versteckt))
            mitglieder = set(eid(durch_ids[o]) for o in drin)
            weg = [e.Id for e in alle if eid(e.Id) not in mitglieder]
            if weg:
                v.HideElements(_liste(weg))
            for o in drin:
                v.SetElementOverrides(durch_ids[o], orange)
            boxen = [doc.GetElement(durch_ids[o]).get_BoundingBox(None) for o in drin]
            boxen = [b for b in boxen if b is not None]
            if boxen:
                v.IsSectionBoxActive = True
                v.SetSectionBox(_box([b.Min for b in boxen], [b.Max for b in boxen], 2000 / FUSS_MM))
            else:
                v.IsSectionBoxActive = False
        else:
            kats = set()
            for name, liste in GEWERKE:
                if name in (paket.get("gewerke") or []):
                    kats.update(int(k) for k in liste)
            _grundeinstellung(doc, v, kats)
            for i in durch_ids.values():
                v.SetElementOverrides(i, orange)
            hoehen = _hoehenbereich(doc, paket.get("ebenen") or [])
            if hoehen:
                weit = 3000.0
                b = DB.BoundingBoxXYZ()
                b.Min = DB.XYZ(-weit, -weit, hoehen[0])
                b.Max = DB.XYZ(weit, weit, hoehen[1])
                v.IsSectionBoxActive = True
                v.SetSectionBox(b)
            else:
                v.IsSectionBoxActive = False
        t.Commit()
    return v


def _hoehenbereich(doc, ebenen_namen):
    """Höhenbereich (Fuß) von der untersten gewählten Ebene bis zur nächsten Ebene über der obersten."""
    if not ebenen_namen:
        return None
    lv = sorted(DB.FilteredElementCollector(doc).OfClass(DB.Level), key=lambda l: l.ProjectElevation)
    gewaehlt = [l for l in lv if l.Name in ebenen_namen]
    if not gewaehlt:
        return None
    unten = gewaehlt[0].ProjectElevation - 0.5
    oben_ebene = gewaehlt[-1]
    hoeher = [l for l in lv if l.ProjectElevation > oben_ebene.ProjectElevation + 0.1]
    oben = hoeher[0].ProjectElevation if hoeher else oben_ebene.ProjectElevation + 15.0
    return unten, oben


def aus_ansicht_uebernehmen(doc, paket, plan):
    """In der Ansicht von Hand ausgeblendete Durchbrüche als „abgewählt“ übernehmen. Gibt True bei Änderung."""
    if paket["art"] != DURCHBRUECHE:
        return False
    v = _ansicht(doc, paket)
    if v is None:
        return False
    aus = set(paket.get("aus") or [])
    vorher = set(aus)
    for oid in objekte(paket, plan, mit_aus=True):
        e = doc.GetElement(plan.element_ids[oid])
        if e is not None and e.IsHidden(v):
            aus.add(oid)
    paket["aus"] = sorted(aus)
    return aus != vorher


def tga_zaehlen(doc, paket, pruefset_ids):
    """Sichtbare Bauteile der TGA-Paket-Ansicht (ohne Durchbrüche): {Kategorie: Anzahl}."""
    v = _ansicht(doc, paket)
    if v is None:
        return None
    kats = {}
    for e in DB.FilteredElementCollector(doc, v.Id).WhereElementIsNotElementType():
        c = e.Category
        if c is None or c.CategoryType != DB.CategoryType.Model or eid(e.Id) in pruefset_ids:
            continue
        kats[c.Name] = kats.get(c.Name, 0) + 1
    return kats
