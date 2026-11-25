# -*- coding: utf-8 -*-
"""Kern der Durchbruchskoordinierung.

Reines Python ohne Abhängigkeiten. Läuft unter IronPython 2.7 (pyRevit)
und CPython 3.x (Berichte, Tests). Deshalb: keine f-Strings, keine
Typannotationen, keine dataclasses.

Prinzip: Jede Firma schreibt Ereignisse als einzelne JSON-Dateien in ihren
eigenen Unterordner des gemeinsamen Projektordners. Der aktuelle Stand wird
aus allen Ereignissen berechnet (siehe ``zustand.berechne``).
"""
from __future__ import unicode_literals

from .ablage import Ablage
from .ereignisse import Absender, ARTEN
from .geometrie import geometrie_hash
from .projekt import Projekt
from .zustand import berechne

__all__ = ["Ablage", "Absender", "ARTEN", "geometrie_hash", "Projekt", "berechne"]
__version__ = "0.1.0"
