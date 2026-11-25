# -*- coding: utf-8 -*-
"""Festlegen, welche Familien und Typen zur Prüfung eingereicht werden."""
from pyrevit import revit, forms
import dbk_revit
from dbk_revit import ansichten, dialoge, einstellungen, sammeln

einst = einstellungen.laden()
if not einstellungen.vollstaendig(einst):
    forms.alert(u"Bitte zuerst „Anmelden“.", title="DBK", exitscript=True)
fenster = dialoge.Pruefset(revit.doc, einst)
fenster.ShowDialog()

if fenster.gespeichert:
    pruefset = sammeln.pruefset_laden(einst["projektordner"], einst["firma"])
    elemente = sammeln.elemente_im_pruefset(revit.doc, pruefset)
    if elemente and forms.alert(
            u"Prüfset gespeichert: {} Exemplare.\n\nZur Kontrolle eine 3D-Ansicht mit genau diesen Bauteilen öffnen?\n"
            u"(Ansicht „DBK Einreichen – Name“. Einzelne Exemplare wählst du dann beim Einreichen ab.)"
            .format(len(elemente)), title="DBK – Prüfset", yes=True, no=True):
        ids = [e.Id for e in elemente]
        ausgeschlossen = set(pruefset.get("ausgeschlossen", []))
        gewaehlt = [e.Id for e in elemente if "%s:%s" % (einst["modellkuerzel"], e.UniqueId) not in ausgeschlossen]
        ansichten.kontrollansicht(revit.uidoc, einst, ids, gewaehlt)
