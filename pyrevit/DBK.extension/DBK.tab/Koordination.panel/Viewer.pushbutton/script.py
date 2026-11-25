# -*- coding: utf-8 -*-
"""Web-Viewer für den eigenen Projektordner im Browser öffnen."""
from pyrevit import forms
import dbk_revit
from dbk_revit import einstellungen, viewer_start

einst = einstellungen.laden()
if not einstellungen.vollstaendig(einst):
    forms.alert(u"Bitte zuerst „Anmelden“ – der Viewer zeigt den dort gewählten Projektordner.", title="DBK", exitscript=True)
try:
    viewer_start.oeffnen(einst["projektordner"])
except Exception as e:
    forms.alert(u"Viewer konnte nicht gestartet werden:\n{}".format(e), title="DBK")
