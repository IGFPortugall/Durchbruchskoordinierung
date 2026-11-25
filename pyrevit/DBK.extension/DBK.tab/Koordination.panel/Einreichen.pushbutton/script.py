# -*- coding: utf-8 -*-
"""Einreichen-Assistent: Pakete festlegen, prüfen, einreichen und veröffentlichen."""
from pyrevit import forms
import dbk_revit
from dbk_revit import assistent, einstellungen, sammeln

einst = einstellungen.laden()
if not einstellungen.vollstaendig(einst):
    forms.alert(u"Bitte zuerst „Anmelden“.", title="DBK", exitscript=True)
if not sammeln.pruefset_laden(einst["projektordner"], einst["firma"]).get("typen"):
    forms.alert(u"Das Prüfset ist leer. Bitte zuerst unter „Prüfset“ die Durchbruch-Familien anhaken.",
                title="DBK", exitscript=True)
assistent.zeigen(einst)
