# -*- coding: utf-8 -*-
"""Persönliche Einstellungen (nur auf diesem Rechner): %APPDATA%\\DBK\\einstellungen.json."""
from __future__ import unicode_literals

import io
import json
import os

DATEI = os.path.join(os.environ.get("APPDATA", os.path.expanduser("~")), "DBK", "einstellungen.json")

STANDARD = {
    "projektordner": "",
    "name": "",
    "firma": "",
    "rolle": "",
    "modellkuerzel": "",      # Kürzel des eigenen Modells, z. B. "HLS"
    "vorlage_2d": "",         # Name der Ansichtsvorlage für DBK-Grundrisse
    "vorlage_3d": "",         # Name der Ansichtsvorlage für die DBK-3D-Ansicht
    "rand_2d_m": 3.0,         # Ausschnitt um den Durchbruch im Grundriss
    "rand_3d_m": 1.5,         # Schnittbox-Rand im 3D
    "viewer_url": "http://127.0.0.1:8765/",
}


def laden():
    daten = dict(STANDARD)
    try:
        with io.open(DATEI, "r", encoding="utf-8-sig") as f:
            daten.update(json.load(f))
    except (IOError, OSError, ValueError):
        pass
    return daten


def speichern(daten):
    ordner = os.path.dirname(DATEI)
    if not os.path.isdir(ordner):
        os.makedirs(ordner)
    text = json.dumps(daten, ensure_ascii=False, indent=2, sort_keys=True)
    if isinstance(text, bytes):
        text = text.decode("utf-8")
    with io.open(DATEI, "w", encoding="utf-8") as f:
        f.write(text)


def vollstaendig(e):
    return bool(e.get("projektordner") and e.get("name") and e.get("firma") and e.get("rolle")
                and os.path.isfile(os.path.join(e["projektordner"], "projekt.json")))


PROJEKT_VORLAGE = {
    "rollen": [
        {"id": "TGA", "name": "TGA"}, {"id": "ELT", "name": "Elektro"}, {"id": "LAB", "name": "Labor"},
        {"id": "ARC", "name": "Architektur"}, {"id": "TWP", "name": "Tragwerk"},
        {"id": "BS", "name": "Brandschutz"}, {"id": "BH", "name": "Bauherr"},
    ],
    "status": [{"id": "zurueckgestellt", "name": "Zurückgestellt", "wirkung": "offen", "farbe": "#854F0B"}],
    "standard": {"ARC": "pflicht"},
    "regeln": [
        {"name": "Wand tragend", "wenn": {"wirt.kategorie": "Wände", "wirt.tragend": True},
         "rollen": {"ARC": "pflicht", "TWP": "pflicht", "TGA": "info"}},
        {"name": "Decke", "wenn": {"wirt.kategorie": "Geschossdecken"},
         "rollen": {"ARC": "pflicht", "TWP": "pflicht"}},
        {"name": "Groß", "zusatz": True, "wenn": {"flaeche_m2": {"gt": 1.0}}, "rollen": {"BH": "pflicht"}},
    ],
    "viewer": {"versatz_mm": [0, 0, 0]},
}


def projekt_anlegen(ordner, name):
    """Legt projekt.json mit Standard-Rollen und -Regeln an. Überschreibt nichts."""
    pfad = os.path.join(ordner, "projekt.json")
    if os.path.exists(pfad):
        return pfad
    daten = dict(PROJEKT_VORLAGE)
    daten["name"] = name
    text = json.dumps(daten, ensure_ascii=False, indent=2)
    if isinstance(text, bytes):
        text = text.decode("utf-8")
    with io.open(pfad, "w", encoding="utf-8") as f:
        f.write(text)
    return pfad


_AUSWAHL = os.path.join(os.path.dirname(DATEI), "einreichen_auswahl.json")


def einreichen_auswahl_laden(modell):
    """Zwischengespeicherte Auswahl (für den Weg über die 3D-Kontrollansicht)."""
    try:
        with io.open(_AUSWAHL, "r", encoding="utf-8-sig") as f:
            return json.load(f).get(modell)
    except (IOError, OSError, ValueError):
        return None


def einreichen_auswahl_speichern(modell, daten):
    alles = {}
    try:
        with io.open(_AUSWAHL, "r", encoding="utf-8-sig") as f:
            alles = json.load(f)
    except (IOError, OSError, ValueError):
        pass
    if daten is None:
        alles.pop(modell, None)
    else:
        alles[modell] = daten
    if not os.path.isdir(os.path.dirname(_AUSWAHL)):
        os.makedirs(os.path.dirname(_AUSWAHL))
    text = json.dumps(alles, ensure_ascii=False)
    if isinstance(text, bytes):
        text = text.decode("utf-8")
    with io.open(_AUSWAHL, "w", encoding="utf-8") as f:
        f.write(text)


def kuerzel_bereinigen(text, laenge=12):
    """Kürzel für Viewer und IDs: Großbuchstaben, Ziffern, Bindestrich – z. B. „HLS“, „HLS-DB1“."""
    import re
    k = re.sub(r"[^A-Z0-9-]+", "-", (text or "").strip().upper().replace("Ä", "AE").replace("Ö", "OE")
               .replace("Ü", "UE").replace("ß", "SS")).strip("-")
    return k[:laenge].strip("-")


def absender(e):
    from dbk_core import Absender
    return Absender(e["firma"], e["name"], e["rolle"])
