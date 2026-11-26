# -*- coding: utf-8 -*-
"""Beim Start von pyRevit: Leiste „Durchbruchsprüfung“ bei Revit anmelden.

Revit erlaubt andockbare Leisten nur beim Start – nach einem Update der Erweiterung
deshalb Revit einmal neu starten.
"""
try:
    from dbk_revit import pruefleiste
    pruefleiste.anmelden()
except Exception as e:      # Start von Revit nie blockieren
    print("DBK: Leiste Durchbruchsprüfung nicht angemeldet: %s" % e)
