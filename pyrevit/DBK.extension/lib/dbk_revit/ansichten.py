# -*- coding: utf-8 -*-
"""2D- und 3D-Ansichten zum Prüfen eines Durchbruchs.

Es werden eigene Arbeitsansichten je Benutzer angelegt bzw. wiederverwendet
("DBK 3D – <Name>", "DBK 2D – <Ebene> – <Name>"). Bestehende Ansichten des
Projekts werden nicht verändert. Die Ansichtsvorlagen kommen aus den Einstellungen.
"""
from __future__ import unicode_literals

from Autodesk.Revit import DB

from . import FUSS_MM
from .sammeln import _liste

STRICH = "–"


def _vorlage(doc, name):
    if not name:
        return None
    for v in DB.FilteredElementCollector(doc).OfClass(DB.View):
        if v.IsTemplate and v.Name == name:
            return v
    return None


def vorlagen(doc, plan=True):
    typ = DB.ViewType.FloorPlan if plan else DB.ViewType.ThreeD
    return sorted(v.Name for v in DB.FilteredElementCollector(doc).OfClass(DB.View) if v.IsTemplate and v.ViewType == typ)


def transform_fuer(doc, objekt):
    """Objekt-Koordinaten (Modell des Erstellers) -> Koordinaten des aktiven Modells."""
    quelle = objekt.get("revit_modell")
    if not quelle or quelle == doc.Title:
        return DB.Transform.Identity, True
    for li in DB.FilteredElementCollector(doc).OfClass(DB.RevitLinkInstance):
        ld = li.GetLinkDocument()
        if ld is not None and ld.Title == quelle:
            return li.GetTotalTransform(), True
    return DB.Transform.Identity, False


def box(doc, objekt, rand_m):
    g = objekt["geometrie"]
    t, gefunden = transform_fuer(doc, objekt)
    r = rand_m * 1000.0
    ecken = [t.OfPoint(DB.XYZ(x / FUSS_MM, y / FUSS_MM, z / FUSS_MM))
             for x in (g["min"][0] - r, g["max"][0] + r)
             for y in (g["min"][1] - r, g["max"][1] + r)
             for z in (g["min"][2] - r, g["max"][2] + r)]
    bb = DB.BoundingBoxXYZ()
    bb.Min = DB.XYZ(min(p.X for p in ecken), min(p.Y for p in ecken), min(p.Z for p in ecken))
    bb.Max = DB.XYZ(max(p.X for p in ecken), max(p.Y for p in ecken), max(p.Z for p in ecken))
    return bb, gefunden


def _finde_ansicht(doc, klasse, name):
    for v in DB.FilteredElementCollector(doc).OfClass(klasse):
        if not v.IsTemplate and v.Name == name:
            return v
    return None


def _element(doc, objekt):
    uid = objekt.get("revit_unique_id")
    if uid and objekt.get("revit_modell") == doc.Title:
        return doc.GetElement(uid)
    return None


def _auswaehlen(uidoc, objekt):
    """Durchbruch markieren – im eigenen Modell oder in der Verknüpfung, aus der er stammt."""
    doc = uidoc.Document
    e = _element(doc, objekt)
    if e is not None:
        uidoc.Selection.SetElementIds(_liste([e.Id]))
        return e
    uid, quelle = objekt.get("revit_unique_id"), objekt.get("revit_modell")
    if not uid or not quelle:
        return None
    for li in DB.FilteredElementCollector(doc).OfClass(DB.RevitLinkInstance):
        ld = li.GetLinkDocument()
        if ld is None or ld.Title != quelle:
            continue
        le = ld.GetElement(uid)
        if le is None:
            continue
        try:
            from System.Collections.Generic import List
            refs = List[DB.Reference]()
            refs.Add(DB.Reference(le).CreateLinkReference(li))
            uidoc.Selection.SetReferences(refs)
        except Exception:
            pass
        return le
    return None


def zeige_3d(uiapp, objekt, einst):
    uidoc = uiapp.ActiveUIDocument
    doc = uidoc.Document
    name = "DBK 3D %s %s" % (STRICH, einst.get("name") or "Prüfung")
    bb, gefunden = box(doc, objekt, float(einst.get("rand_3d_m") or 1.5))
    with DB.Transaction(doc, "DBK: 3D-Ansicht") as t:
        t.Start()
        v = _finde_ansicht(doc, DB.View3D, name)
        if v is None:
            vft = next(x for x in DB.FilteredElementCollector(doc).OfClass(DB.ViewFamilyType)
                       if x.ViewFamily == DB.ViewFamily.ThreeDimensional)
            v = DB.View3D.CreateIsometric(doc, vft.Id)
            v.Name = name
        vorlage = _vorlage(doc, einst.get("vorlage_3d"))
        if vorlage is not None:
            v.ViewTemplateId = vorlage.Id
        v.IsSectionBoxActive = True
        v.SetSectionBox(bb)
        t.Commit()
    uidoc.ActiveView = v
    e = _auswaehlen(uidoc, objekt)
    for ui in uidoc.GetOpenUIViews():
        if ui.ViewId == v.Id:
            ui.ZoomAndCenterRectangle(bb.Min, bb.Max)
    return gefunden, e is not None


def zeige_2d(uiapp, objekt, einst):
    uidoc = uiapp.ActiveUIDocument
    doc = uidoc.Document
    ebenen = sorted(DB.FilteredElementCollector(doc).OfClass(DB.Level), key=lambda l: l.ProjectElevation)
    bb, gefunden = box(doc, objekt, float(einst.get("rand_2d_m") or 3.0))
    ebene = next((l for l in ebenen if l.Name == objekt.get("ebene")), None)
    if ebene is None:
        z = (bb.Min.Z + bb.Max.Z) / 2.0
        kandidaten = [l for l in ebenen if l.ProjectElevation <= z] or ebenen
        ebene = kandidaten[-1]
    name = "DBK 2D %s %s %s %s" % (STRICH, ebene.Name, STRICH, einst.get("name") or "Prüfung")
    with DB.Transaction(doc, "DBK: Grundriss") as t:
        t.Start()
        v = _finde_ansicht(doc, DB.ViewPlan, name)
        if v is None:
            vft = next(x for x in DB.FilteredElementCollector(doc).OfClass(DB.ViewFamilyType)
                       if x.ViewFamily == DB.ViewFamily.FloorPlan)
            v = DB.ViewPlan.Create(doc, vft.Id, ebene.Id)
            v.Name = name
        vorlage = _vorlage(doc, einst.get("vorlage_2d"))
        if vorlage is not None:
            v.ViewTemplateId = vorlage.Id
        crop = v.CropBox
        crop.Min = DB.XYZ(bb.Min.X, bb.Min.Y, crop.Min.Z)
        crop.Max = DB.XYZ(bb.Max.X, bb.Max.Y, crop.Max.Z)
        v.CropBoxActive = True
        v.CropBox = crop
        t.Commit()
    uidoc.ActiveView = v
    e = _auswaehlen(uidoc, objekt)
    for ui in uidoc.GetOpenUIViews():
        if ui.ViewId == v.Id:
            ui.ZoomToFit()
    return gefunden, e is not None


def _vollfarbe(doc):
    for fp in DB.FilteredElementCollector(doc).OfClass(DB.FillPatternElement):
        if fp.GetFillPattern().IsSolidFill:
            return fp.Id
    return None


def kontrollansicht(uidoc, einst, alle_ids, gewaehlte_ids, rand_m=1.0):
    """3D-Ansicht „DBK Einreichen – Name“: nur Prüfset-Bauteile (temporär isoliert),
    gewählte orange, abgewählte grau/transparent, Schnittbox um die gewählten.

    Legt die Ansicht beim ersten Mal an; ändert sonst keine Bauteile des Modells.
    """
    doc = uidoc.Document
    name = "DBK Einreichen %s %s" % (STRICH, einst.get("name") or "Kontrolle")
    alle = list(alle_ids)
    gewaehlt = set(sammeln_eid(i) for i in gewaehlte_ids)
    with DB.Transaction(doc, "DBK: Kontrollansicht") as t:
        t.Start()
        v = _finde_ansicht(doc, DB.View3D, name)
        if v is None:
            vft = next(x for x in DB.FilteredElementCollector(doc).OfClass(DB.ViewFamilyType)
                       if x.ViewFamily == DB.ViewFamily.ThreeDimensional)
            v = DB.View3D.CreateIsometric(doc, vft.Id)
            v.Name = name
        if v.ViewTemplateId != DB.ElementId.InvalidElementId:
            v.ViewTemplateId = DB.ElementId.InvalidElementId
        v.DetailLevel = DB.ViewDetailLevel.Fine
        if v.IsTemporaryHideIsolateActive():
            v.DisableTemporaryViewMode(DB.TemporaryViewMode.TemporaryHideIsolate)

        voll = _vollfarbe(doc)
        an = DB.OverrideGraphicSettings()
        aus = DB.OverrideGraphicSettings()
        orange, grau = DB.Color(239, 159, 39), DB.Color(160, 158, 150)
        an.SetProjectionLineColor(DB.Color(133, 79, 11)).SetProjectionLineWeight(3)
        aus.SetProjectionLineColor(grau).SetHalftone(True).SetSurfaceTransparency(70)
        if voll is not None:
            an.SetSurfaceForegroundPatternId(voll).SetSurfaceForegroundPatternColor(orange)
            aus.SetSurfaceForegroundPatternId(voll).SetSurfaceForegroundPatternColor(grau)
        box_ids = []
        for i in alle:
            if sammeln_eid(i) in gewaehlt:
                v.SetElementOverrides(i, an)
                box_ids.append(i)
            else:
                v.SetElementOverrides(i, aus)
        if alle:
            v.IsolateElementsTemporary(_liste(alle))
        bb = _box_um(doc, box_ids or alle, rand_m)
        if bb is not None:
            v.IsSectionBoxActive = True
            v.SetSectionBox(bb)
        t.Commit()
    uidoc.ActiveView = v
    for ui in uidoc.GetOpenUIViews():
        if ui.ViewId == v.Id:
            ui.ZoomToFit()
    return v


def _box_um(doc, ids, rand_m):
    mins, maxs = [], []
    for i in ids:
        bb = doc.GetElement(i).get_BoundingBox(None)
        if bb is not None:
            mins.append(bb.Min)
            maxs.append(bb.Max)
    if not mins:
        return None
    r = rand_m * 1000.0 / FUSS_MM
    box = DB.BoundingBoxXYZ()
    box.Min = DB.XYZ(min(p.X for p in mins) - r, min(p.Y for p in mins) - r, min(p.Z for p in mins) - r)
    box.Max = DB.XYZ(max(p.X for p in maxs) + r, max(p.Y for p in maxs) + r, max(p.Z for p in maxs) + r)
    return box


def sammeln_eid(element_id):
    from .sammeln import eid
    return eid(element_id)


def auswaehlen(uiapp, objekt):
    uidoc = uiapp.ActiveUIDocument
    e = _auswaehlen(uidoc, objekt)
    if e is not None:
        uidoc.ShowElements(e.Id)
    return e is not None
