# -*- coding: utf-8 -*-
"""Modelle zum Viewer: 3D-Ansichten als FBX/IFC in den Projektordner stellen."""
from pyrevit import revit
import dbk_revit
from dbk_revit import modelle

modelle.zeigen(revit.doc)
