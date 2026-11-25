# -*- coding: utf-8 -*-
"""Revit-Teil der Durchbruchskoordinierung (pyRevit, IronPython 2.7).

Bindet den gemeinsamen Kern ``dbk_core`` aus ``<repo>/src`` ein, damit Revit,
Tests und Web-App dieselbe Logik verwenden.
"""
from __future__ import unicode_literals

import os
import sys

_HIER = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.normpath(os.path.join(_HIER, "..", "..", "..", ".."))
_SRC = os.path.join(REPO, "src")
if _SRC not in sys.path:
    sys.path.insert(0, _SRC)

FUSS_MM = 304.8
