# -*- coding: utf-8 -*-
"""Durchbruchsprüfung: andockbare Leiste ein-/ausblenden (Prüfen, Freigeben, Chat – wie im Viewer)."""
from pyrevit import revit
import dbk_revit
from dbk_revit import pruefleiste

pruefleiste.umschalten(revit.doc)
