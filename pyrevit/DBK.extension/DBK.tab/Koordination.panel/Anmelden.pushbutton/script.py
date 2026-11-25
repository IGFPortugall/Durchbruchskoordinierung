# -*- coding: utf-8 -*-
"""Projektordner, Name, Firma, Rolle und Modellkürzel festlegen."""
from pyrevit import revit, forms
import dbk_revit
from dbk_revit import dialoge

fenster = dialoge.Anmelden(revit.doc)
fenster.ShowDialog()
if fenster.ergebnis:
    e = fenster.ergebnis
    forms.alert(u"Angemeldet als {} ({}, {}).\nModell: {}".format(e["name"], e["firma"], e["rolle"], e["modellkuerzel"]),
                title="DBK")
