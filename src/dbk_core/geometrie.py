# -*- coding: utf-8 -*-
"""Geometrie-Hash: erkennt, ob ein Bauteil in Lage oder Größe verändert wurde.

Werte werden in Millimetern (Projektkoordinaten) übergeben und auf ein Raster
gerundet, damit Rechenrauschen keine Freigaben ungültig macht.
"""
from __future__ import unicode_literals

import hashlib
import json

RASTER_MM = 5.0


def _runde(wert, raster):
    return int(round(float(wert) / raster))


def geometrie_hash(geometrie, raster=RASTER_MM):
    """Kurzer Hash über Lage und Größe.

    ``geometrie`` ist ein dict mit
      - ``min``: [x, y, z] in mm (Bounding Box, Projektkoordinaten)
      - ``max``: [x, y, z] in mm
      - optional ``form``: z. B. "rechteck" oder "rund"
      - optional ``masse``: dict mit Maßen in mm, z. B. {"breite": 400, "hoehe": 300}
    """
    kanonisch = {
        "min": [_runde(w, raster) for w in geometrie["min"]],
        "max": [_runde(w, raster) for w in geometrie["max"]],
        "form": geometrie.get("form") or "",
        "masse": dict((k, _runde(v, raster)) for k, v in (geometrie.get("masse") or {}).items()),
    }
    text = json.dumps(kanonisch, sort_keys=True, separators=(",", ":"))
    return hashlib.sha1(text.encode("utf-8")).hexdigest()[:16]
