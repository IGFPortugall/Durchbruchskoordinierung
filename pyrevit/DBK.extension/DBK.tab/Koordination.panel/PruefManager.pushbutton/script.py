# -*- coding: utf-8 -*-
"""Durchbrüche prüfen, kommentieren, freigeben oder ablehnen."""
from pyrevit import forms
import dbk_revit
from dbk_revit import einstellungen, manager

einst = einstellungen.laden()
if not einstellungen.vollstaendig(einst):
    forms.alert(u"Bitte zuerst „Anmelden“.", title="DBK", exitscript=True)
manager.zeigen(einst)
