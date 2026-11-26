# -*- coding: utf-8 -*-
"""Einstellungen: persönlich (je Rechner) und je Revit-Modell.

Datei: %APPDATA%\\DBK\\einstellungen.json

- Persönlich: Name, Firma, Rolle, Darstellung.
- Je Revit-Modell (``dokumente[<Schlüssel>]``): Projektordner, Projekt-ID, Modellkürzel,
  Ansichtsvorlagen. Der Schlüssel ist der Pfad des Zentralmodells (bzw. der Datei) – damit
  landet jedes Modell immer im eigenen Projekt, auch wenn man mehrere Projekte bearbeitet.
- ``projekte[<Projekt-ID>]``: wo der Projektordner auf diesem Rechner liegt. Projekt-ID und
  Modellkürzel stehen zusätzlich im Revit-Modell (``modellbindung``) – Kollegen am selben
  Modell müssen dann nur noch den Ordner wählen, die Prüfung „gleiches Projekt?“ greift.
"""
from __future__ import unicode_literals

import io
import json
import os
import uuid

DATEI = os.path.join(os.environ.get("APPDATA", os.path.expanduser("~")), "DBK", "einstellungen.json")

STANDARD = {
    "projektordner": "",
    "projekt_id": "",
    "projekt_name": "",
    "name": "",
    "firma": "",
    "rolle": "",
    "modellkuerzel": "",      # Kürzel des eigenen Modells, z. B. "HLS"
    "plant_durchbrueche": False,
    "vorlage_2d": "",         # Name der Ansichtsvorlage für DBK-Grundrisse
    "vorlage_3d": "",         # Name der Ansichtsvorlage für die DBK-3D-Ansicht
    "rand_2d_m": 3.0,         # Ausschnitt um den Durchbruch im Grundriss
    "rand_3d_m": 1.5,         # Schnittbox-Rand im 3D
    "viewer_url": "http://127.0.0.1:8765/",
}

# Diese Werte gelten je Revit-Modell, nicht je Rechner
JE_MODELL = ("projektordner", "projekt_id", "modellkuerzel", "plant_durchbrueche", "vorlage_2d", "vorlage_3d")


def _datei_lesen():
    try:
        with io.open(DATEI, "r", encoding="utf-8-sig") as f:
            return json.load(f)
    except (IOError, OSError, ValueError):
        return {}


def _datei_schreiben(daten):
    ordner = os.path.dirname(DATEI)
    if not os.path.isdir(ordner):
        os.makedirs(ordner)
    text = json.dumps(daten, ensure_ascii=False, indent=2, sort_keys=True)
    if isinstance(text, bytes):
        text = text.decode("utf-8")
    tmp = DATEI + ".tmp"
    with io.open(tmp, "w", encoding="utf-8") as f:
        f.write(text)
    if os.path.exists(DATEI):
        os.remove(DATEI)
    os.rename(tmp, DATEI)


def dokument_schluessel(doc):
    """Stabiler Schlüssel des Revit-Modells: Zentralmodell-Pfad, sonst Dateipfad, sonst Titel."""
    if doc is None:
        return ""
    try:
        if doc.IsWorkshared:
            from Autodesk.Revit.DB import ModelPathUtils
            pfad = doc.GetWorksharingCentralModelPath()
            if pfad is not None:
                return ModelPathUtils.ConvertModelPathToUserVisiblePath(pfad)
    except Exception:
        pass
    return doc.PathName or doc.Title


def laden(doc=None):
    """Persönliche Einstellungen + die des Revit-Modells ``doc`` (falls angegeben).

    Ohne Eintrag für das Modell bleiben Projektordner und Kürzel leer – nie die eines
    anderen Projekts. Eine alte, rechnerweite Einstellung wird nur einmal als Vorschlag
    übernommen (``vorschlag_alt``)."""
    roh = _datei_lesen()
    daten = dict(STANDARD)
    daten.update(dict((k, v) for k, v in roh.items() if k not in ("dokumente", "projekte") and k not in JE_MODELL))
    alt = dict((k, roh.get(k)) for k in JE_MODELL if roh.get(k))
    if doc is None:
        daten.update(alt)
        return daten
    schluessel = dokument_schluessel(doc)
    eintrag = (roh.get("dokumente") or {}).get(schluessel)
    daten["dokument"] = schluessel
    daten["dokument_titel"] = doc.Title
    if eintrag:
        daten.update(eintrag)
    else:
        daten["vorschlag_alt"] = alt
    try:
        from . import modellbindung
        b = modellbindung.lesen(doc)
    except Exception:
        b = None
    daten["im_modell"] = b or {}
    if b and b.get("projekt_id"):
        ordner = (roh.get("projekte") or {}).get(b["projekt_id"])
        if not daten.get("projektordner") and ordner:
            daten["projektordner"] = ordner
            daten["projekt_id"] = b["projekt_id"]
        if not daten.get("modellkuerzel") and b.get("modellkuerzel"):
            daten["modellkuerzel"] = b["modellkuerzel"]
    if daten.get("projektordner"):
        p = projekt_info(daten["projektordner"])
        daten["projekt_name"] = p.get("name") or ""
        daten["projekt_id_ordner"] = p.get("id") or ""
    return daten


def speichern(daten):
    """Persönliches in die Wurzel, Modellbezogenes unter ``dokumente[daten['dokument']]``."""
    roh = _datei_lesen()
    for k in JE_MODELL:
        roh.pop(k, None)          # alte rechnerweite Werte nicht mehr verwenden
    for k, v in daten.items():
        if k in STANDARD and k not in JE_MODELL and k not in ("projekt_name",):
            roh[k] = v
    schluessel = daten.get("dokument")
    if schluessel:
        roh.setdefault("dokumente", {})[schluessel] = dict((k, daten.get(k)) for k in JE_MODELL)
    if daten.get("projekt_id") and daten.get("projektordner"):
        roh.setdefault("projekte", {})[daten["projekt_id"]] = daten["projektordner"]
    _datei_schreiben(roh)


def projekt_info(ordner):
    try:
        with io.open(os.path.join(ordner, "projekt.json"), "r", encoding="utf-8-sig") as f:
            return json.load(f)
    except (IOError, OSError, ValueError):
        return {}


def projekt_id_sichern(ordner):
    """Projekt-ID aus projekt.json; ältere Projekte bekommen einmalig eine (wird ergänzt, nichts überschrieben)."""
    pfad = os.path.join(ordner, "projekt.json")
    daten = projekt_info(ordner)
    if not daten:
        return ""
    if daten.get("id"):
        return daten["id"]
    daten["id"] = uuid.uuid4().hex
    text = json.dumps(daten, ensure_ascii=False, indent=2)
    if isinstance(text, bytes):
        text = text.decode("utf-8")
    with io.open(pfad + ".tmp", "w", encoding="utf-8") as f:
        f.write(text)
    if projekt_info(ordner).get("id"):          # inzwischen von jemand anderem ergänzt
        os.remove(pfad + ".tmp")
        return projekt_info(ordner)["id"]
    os.remove(pfad)
    os.rename(pfad + ".tmp", pfad)
    return daten["id"]


def projekt_umbenennen(ordner, name):
    """Projektnamen in projekt.json ändern (alles andere bleibt). Gilt für alle Beteiligten."""
    pfad = os.path.join(ordner, "projekt.json")
    daten = projekt_info(ordner)
    if not daten or not name or daten.get("name") == name:
        return False
    daten["name"] = name
    text = json.dumps(daten, ensure_ascii=False, indent=2)
    if isinstance(text, bytes):
        text = text.decode("utf-8")
    with io.open(pfad + ".tmp", "w", encoding="utf-8") as f:
        f.write(text)
    os.remove(pfad)
    os.rename(pfad + ".tmp", pfad)
    return True


def projekt_konflikt(e):
    """Text, wenn Projektordner und Revit-Modell nicht zusammenpassen – sonst None."""
    im_modell = (e.get("im_modell") or {}).get("projekt_id")
    im_ordner = e.get("projekt_id_ordner")
    if im_modell and im_ordner and im_modell != im_ordner:
        return ("Dieses Revit-Modell gehört zu Projekt „%s“, der gewählte Ordner ist aber „%s“. "
                "Bitte den richtigen Projektordner wählen." % ((e.get("im_modell") or {}).get("projekt_name") or "?",
                                                             e.get("projekt_name") or "?"))
    if e.get("projekt_id") and im_ordner and e["projekt_id"] != im_ordner:
        return ("Im Projektordner liegt inzwischen ein anderes Projekt („%s“). Bitte den Ordner prüfen."
                % (e.get("projekt_name") or "?"))
    return None


def vollstaendig(e):
    return bool(e.get("projektordner") and e.get("name") and e.get("firma") and e.get("rolle")
                and os.path.isfile(os.path.join(e["projektordner"], "projekt.json"))
                and not projekt_konflikt(e))


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
    daten["id"] = uuid.uuid4().hex
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
