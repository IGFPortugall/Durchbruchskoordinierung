# -*- coding: utf-8 -*-
"""Welches Koordinationsprojekt zu diesem Revit-Modell gehört – gespeichert im Modell selbst.

Extensible Storage an den Projektinformationen: Projekt-ID, Projektname, Modellkürzel.
Der Ordnerpfad steht bewusst nicht im Modell (er ist auf jedem Rechner anders, z. B. der
synchronisierte SharePoint-Ordner); den merkt sich jeder Rechner selbst (``einstellungen``).

Schreiben braucht eine Transaktion (also einen API-Kontext) und bei Worksharing die
Projektinformationen ausleihbar. Klappt das nicht, bleibt die Zuordnung nur lokal – kein Fehler.
"""
from __future__ import unicode_literals

from System import Guid, String
from Autodesk.Revit import DB
from Autodesk.Revit.DB.ExtensibleStorage import AccessLevel, Entity, Schema, SchemaBuilder

SCHEMA_GUID = Guid("6f1b0d52-3c4e-4a7a-9d0e-2b8f5c1a7e31")
FELDER = ("projekt_id", "projekt_name", "modellkuerzel")


def _schema():
    s = Schema.Lookup(SCHEMA_GUID)
    if s is not None:
        return s
    b = SchemaBuilder(SCHEMA_GUID)
    b.SetSchemaName("DBK_Projektbindung")
    b.SetReadAccessLevel(AccessLevel.Public)
    b.SetWriteAccessLevel(AccessLevel.Public)
    b.SetDocumentation("Durchbruchskoordination: zugehöriges Projekt und Modellkürzel")
    for f in FELDER:
        b.AddSimpleField(f, String)
    return b.Finish()


def lesen(doc):
    """{projekt_id, projekt_name, modellkuerzel} oder None."""
    s = Schema.Lookup(SCHEMA_GUID)
    if s is None:
        return None
    ent = doc.ProjectInformation.GetEntity(s)
    if ent is None or not ent.IsValid():
        return None
    return dict((f, ent.Get[String](f) or "") for f in FELDER)


def schreiben(doc, projekt_id, projekt_name, modellkuerzel):
    """Muss im API-Kontext laufen. Gibt (ok, meldung) zurück."""
    alt = lesen(doc) or {}
    if alt.get("projekt_id") == projekt_id and alt.get("modellkuerzel") == modellkuerzel \
            and alt.get("projekt_name") == projekt_name:
        return True, None
    if doc.IsWorkshared:
        status = DB.WorksharingUtils.GetCheckoutStatus(doc, doc.ProjectInformation.Id)
        if status == DB.CheckoutStatus.OwnedByOtherUser:
            return False, "Projektinformationen sind von jemand anderem ausgeliehen – Zuordnung nur auf diesem Rechner gespeichert."
    s = _schema()
    t = DB.Transaction(doc, "DBK: Projektzuordnung")
    try:
        t.Start()
        ent = Entity(s)
        for f, v in zip(FELDER, (projekt_id, projekt_name, modellkuerzel)):
            ent.Set[String](f, v or "")
        doc.ProjectInformation.SetEntity(ent)
        t.Commit()
        return True, "Zuordnung im Revit-Modell gespeichert (wird mit dem Modell synchronisiert)."
    except Exception as e:
        if t.HasStarted() and not t.HasEnded():
            t.RollBack()
        return False, "Zuordnung nur auf diesem Rechner gespeichert (%s)." % e
