# -*- coding: utf-8 -*-
"""Erzeugt einen Demo-Projektordner und Prüf-Fixtures für die Web-App.

    py werkzeuge/demo_erzeugen.py

- testdaten/demo/            Projektordner mit Beispiel-Ereignissen (Schulmodell von That Open)
- web/test/fixtures.json     Szenarien + von Python berechnete Sollwerte; die
                             JavaScript-Statuslogik muss exakt dasselbe liefern.
"""
from __future__ import print_function, unicode_literals

import io
import json
import os
import shutil
import sys
import tempfile

WURZEL = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(WURZEL, "src"))

from dbk_core import Ablage, Absender, Projekt, berechne, geometrie_hash  # noqa: E402
from dbk_core import zeit  # noqa: E402

DEMO = os.path.join(WURZEL, "testdaten", "demo")
FIXTURES = os.path.join(WURZEL, "web", "test", "fixtures.json")

BEISPIEL = "https://thatopen.github.io/engine_components/resources/frags/"

PROJEKT = {
    "name": "Demo – Schule (That-Open-Beispiel)",
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
         "rollen": {"ARC": "pflicht", "TWP": "pflicht", "BS": "pflicht"}},
        {"name": "Groß", "zusatz": True, "wenn": {"flaeche_m2": {"gt": 1.0}},
         "rollen": {"BH": "pflicht"}},
    ],
    "viewer": {"versatz_mm": [0, 0, 0]},
}

# Geschosse des Beispielmodells (Name, OKFF in Modell-Höhe y in m)
EBENEN = {"01 - Entry Level": -0.65, "02 - Floor": 3.15, "03 - Floor": 6.95}


def geo_aus_three(mi, ma, form="rechteck"):
    """Box in Viewer-Koordinaten (m, Y oben) -> Projektkoordinaten (mm, Z oben)."""
    gmin = [round(mi[0] * 1000), round(-ma[2] * 1000), round(mi[1] * 1000)]
    gmax = [round(ma[0] * 1000), round(-mi[2] * 1000), round(ma[1] * 1000)]
    dx, dy = gmax[0] - gmin[0], gmax[1] - gmin[1]
    breite = max(dx, dy) if form == "rechteck" else min(dx, dy)
    hoehe = gmax[2] - gmin[2]
    masse = {"breite": breite, "hoehe": hoehe} if form == "rechteck" else {"durchmesser": hoehe}
    return {"min": gmin, "max": gmax, "form": form, "masse": masse}


def objekt(nr, ebene, mi, ma, wirt, gewerk, form="rechteck", kategorie_wand=True):
    g = geo_aus_three(mi, ma, form)
    m = g["masse"]
    if form == "rund":
        flaeche = 3.14159 * (m["durchmesser"] / 2000.0) ** 2
        groesse = "Ø%d" % m["durchmesser"]
    elif kategorie_wand:
        flaeche = m["breite"] * m["hoehe"] / 1e6
        groesse = "%d×%d" % (m["breite"], m["hoehe"])
    else:
        dx, dy = g["max"][0] - g["min"][0], g["max"][1] - g["min"][1]
        flaeche = dx * dy / 1e6
        groesse = "%d×%d" % (dx, dy)
    return {
        "nummer": nr, "ebene": ebene, "kategorie": "Allgemeines Modell",
        "familie": "IGF_Durchbruch_%s" % ("Rund" if form == "rund" else "Rechteck"),
        "typ": "Wand" if kategorie_wand else "Decke",
        "groesse": groesse, "uk_mm": g["min"][2], "geometrie": g, "flaeche_m2": round(flaeche, 3),
        "wirt": wirt, "gewerke": [gewerk], "modell": "HLS",
        "geometrie_hash": geometrie_hash(g),
    }


class Uhr(object):
    """Setzt den Zeitstempel für das jeweils nächste Ereignis."""

    def __init__(self):
        self._echt = zeit.jetzt_iso
        self.naechste = None
        zeit.jetzt_iso = lambda: self.naechste

    def zurueck(self):
        zeit.jetzt_iso = self._echt


# Demo-Tage liegen in der Vergangenheit, damit neue Einträge aus der App danach einsortiert werden.
TAGE = {"11-28": "11-10", "12-01": "11-12", "12-02": "11-13", "12-03": "11-14"}


def schreibe(uhr, ablage, wann, art, objekt_id=None, daten=None):
    tag, uhrzeit = wann.split(" ")
    uhr.naechste = "2026-%sT%s:00.000Z" % (TAGE.get(tag, tag), uhrzeit)
    return ablage.schreibe(art, objekt_id, daten)


def demo_fuellen(ordner, uhr):
    tga = Ablage(ordner, Absender("IGF", "T. Planer", "TGA"))
    elt = Ablage(ordner, Absender("IGF", "S. Elektra", "ELT"))
    arc = Ablage(ordner, Absender("Architekt XY", "A. Klein", "ARC"))
    twp = Ablage(ordner, Absender("Tragwerk Z", "M. Weber", "TWP"))
    bs = Ablage(ordner, Absender("Brandschutz B", "K. Feuer", "BS"))

    schreibe(uhr, arc, "11-28 08:00", "modell_veroeffentlicht", None, {
        "modell": "ARC", "datei": BEISPIEL + "school_arq.frag", "hash": "school-arq-demo",
        "quelle": "school_arq.ifc", "stand": "2026-11-10",
        "ebenen": [{"name": n, "hoehe_mm": int(round(y * 1000))} for n, y in
                   sorted(EBENEN.items(), key=lambda kv: kv[1])] + [{"name": "Roof", "hoehe_mm": 10750}]})
    schreibe(uhr, twp, "11-28 08:30", "modell_veroeffentlicht", None, {
        # Tragwerk als IFC: der Viewer wandelt es beim Öffnen in Fragments um
        "modell": "TWP", "datei": BEISPIEL.replace("/frags/", "/ifc/") + "school_str.ifc", "hash": "school-str-demo",
        "quelle": "school_str.ifc", "stand": "2026-11-10"})

    wand_t = {"kategorie": "Wände", "tragend": True}
    wand_n = {"kategorie": "Wände", "tragend": False}
    decke = {"kategorie": "Geschossdecken", "tragend": True}
    E0, E1, E2 = "01 - Entry Level", "02 - Floor", "03 - Floor"
    obj = {
        "HLS:db-0001": objekt("TGA-EG-0001", E0, [18.0, 2.2, 6.90], [18.4, 2.5, 7.18], wand_t, "Lüftung"),
        "HLS:db-0002": objekt("TGA-EG-0002", E0, [15.92, 2.3, 2.0], [16.20, 2.6, 2.6], wand_t, "Lüftung"),
        "HLS:db-0003": objekt("TGA-EG-0003", E0, [1.9, 2.3, 26.82], [2.1, 2.5, 27.10], wand_n, "Sanitär", "rund"),
        "HLS:db-0004": objekt("TGA-EG-0004", E0, [27.0, 2.4, 1.26], [27.5, 2.65, 1.54], wand_n, "Heizung"),
        "HLS:db-0005": objekt("TGA-EG-0005", E0, [24.0, 2.8, 4.0], [24.6, 3.25, 4.5], decke, "Lüftung", kategorie_wand=False),
        "HLS:db-0006": objekt("TGA-OG1-0006", E1, [14.0, 5.6, 46.47], [14.4, 5.9, 46.75], wand_t, "Lüftung"),
        "HLS:db-0007": objekt("TGA-OG2-0007", E2, [17.0, 9.4, 46.47], [17.5, 9.7, 46.75], wand_t, "Heizung"),
        "ELT:db-0101": objekt("ELT-OG1-0101", E1, [-2.25, 5.8, 15.0], [-1.78, 6.1, 15.5], wand_t, "Elektro"),
    }

    schreibe(uhr, tga, "12-01 09:00", "pruefrunde_gestartet", None,
             {"runde": "R1", "name": "Runde 1 – Rohbau EG–2.OG", "frist": "2026-12-12"})
    t = 10
    for oid, o in obj.items():
        ablage = elt if oid.startswith("ELT") else tga
        schreibe(uhr, ablage, "12-01 09:%02d" % t, "eingereicht", oid, {"objekt": o, "runde": "R1"})
        t += 1

    def entscheide(ablage, wann, oid, wert, kommentar=None):
        schreibe(uhr, ablage, wann, "status", oid, {
            "wert": wert, "geometrie_hash": obj[oid]["geometrie_hash"], "kommentar": kommentar,
            "kontext": {"ARC": "school-arq-demo", "TWP": "school-str-demo"}})

    def nachricht(ablage, wann, oid, text):
        schreibe(uhr, ablage, wann, "nachricht", oid, {"text": text})

    entscheide(arc, "12-02 10:00", "HLS:db-0001", "freigegeben")
    entscheide(twp, "12-02 11:00", "HLS:db-0001", "freigegeben")

    nachricht(twp, "12-02 11:20", "HLS:db-0002", "Liegt direkt neben dem Unterzug in Achse 3.")
    entscheide(twp, "12-02 11:21", "HLS:db-0002", "abgelehnt", "Abstand zum Unterzug min. 25 cm.")
    nachricht(tga, "12-02 14:05", "HLS:db-0002", "Prüfen wir, ggf. Kanal nach unten verziehen.")

    entscheide(arc, "12-02 10:10", "HLS:db-0004", "freigegeben")

    entscheide(twp, "12-02 11:40", "HLS:db-0005", "abgelehnt", "Durchbruch schneidet Bewehrungszone Stütze.")
    neu = objekt("TGA-EG-0005", E0, [24.6, 2.8, 4.0], [25.2, 3.25, 4.5], decke, "Lüftung", kategorie_wand=False)
    obj["HLS:db-0005"] = neu
    nachricht(tga, "12-03 08:30", "HLS:db-0005", "Um 60 cm nach Osten verschoben.")
    schreibe(uhr, tga, "12-03 08:31", "eingereicht", "HLS:db-0005", {"objekt": neu, "runde": "R1"})
    entscheide(bs, "12-03 09:15", "HLS:db-0005", "freigegeben")

    entscheide(arc, "12-02 10:20", "HLS:db-0006", "zurueckgestellt", "Klärung Fassadenanschluss offen.")
    entscheide(arc, "12-02 10:30", "ELT:db-0101", "freigegeben")
    entscheide(twp, "12-02 11:50", "ELT:db-0101", "freigegeben")


def kanten_fuellen(ordner, uhr):
    """Sonderfälle für den Abgleich Python ↔ JavaScript."""
    tga = Ablage(ordner, Absender("IGF", "T", "TGA"))
    arc = Ablage(ordner, Absender("Architekt XY", "A", "ARC"))
    twp = Ablage(ordner, Absender("Tragwerk Z", "W", "TWP"))
    bh = Ablage(ordner, Absender("Bauherr", "B", "BH"))
    gross = objekt("G", "E", [0, 0, 0], [1.5, 1.0, 0.3], {"kategorie": "Wände", "tragend": False}, "L")
    a = objekt("A", "E", [0, 0, 0], [0.4, 0.3, 0.3], {"kategorie": "Wände", "tragend": True}, "L")
    b = objekt("A", "E", [1, 0, 0], [1.4, 0.3, 0.3], {"kategorie": "Wände", "tragend": True}, "L")
    schreibe(uhr, tga, "12-01 08:00", "eingereicht", "X:a", {"objekt": a})
    schreibe(uhr, tga, "12-01 08:00", "eingereicht", "X:g", {"objekt": gross})
    schreibe(uhr, arc, "12-01 08:00", "status", "X:a", {"wert": "abgelehnt", "geometrie_hash": a["geometrie_hash"]})
    schreibe(uhr, arc, "12-01 08:05", "geloescht", "X:a", {})            # fremde Firma: ignoriert
    schreibe(uhr, arc, "12-01 08:06", "geaendert", "X:g", {"objekt": a})   # fremde Firma: ignoriert
    schreibe(uhr, twp, "12-01 08:07", "status", "X:a", {"wert": "freigegeben", "geometrie_hash": a["geometrie_hash"]})
    schreibe(uhr, tga, "12-01 08:10", "geaendert", "X:a", {"objekt": b})    # macht alte Entscheidungen ungültig
    schreibe(uhr, twp, "12-01 08:11", "status", "X:a", {"wert": "freigegeben", "geometrie_hash": b["geometrie_hash"]})
    schreibe(uhr, arc, "12-01 08:12", "status", "X:g", {"wert": "freigegeben", "geometrie_hash": gross["geometrie_hash"]})
    schreibe(uhr, bh, "12-01 08:13", "status", "X:g", {"wert": "zurueckgestellt", "geometrie_hash": gross["geometrie_hash"]})
    schreibe(uhr, tga, "12-01 08:14", "eingereicht", "X:d", {"objekt": a})
    schreibe(uhr, tga, "12-01 08:15", "geloescht", "X:d", {})
    schreibe(uhr, tga, "12-01 08:16", "eingereicht", "X:e", {"objekt": a})
    schreibe(uhr, tga, "12-01 08:17", "geloescht", "X:e", {})
    schreibe(uhr, tga, "12-01 08:18", "eingereicht", "X:e", {"objekt": b})   # neu eingereicht nach Löschen
    schreibe(uhr, arc, "12-01 08:19", "status", "X:e", {"wert": "abgelehnt", "geometrie_hash": b["geometrie_hash"]})
    schreibe(uhr, arc, "12-01 08:19", "modell_veroeffentlicht", None, {"modell": "ARC", "datei": "x", "hash": "1"})
    schreibe(uhr, twp, "12-01 08:20", "modell_veroeffentlicht", None, {"modell": "ARC", "datei": "y", "hash": "2"})


def sollwerte(ordner, projekt):
    leser = Ablage(ordner)
    leser.lade_neue()
    ereignisse = leser.alle()
    z = berechne(ereignisse, projekt)
    rollen = [r["id"] for r in projekt.rollen] + ["TGA", "ARC", "TWP", "BH", "BS"]
    firmen = sorted(set(e["firma"] for e in ereignisse))
    return {
        "projekt": projekt.als_dict(),
        "ereignisse": ereignisse,
        "erwartet": {
            "objekte": sorted(z.objekte),
            "gesamtstatus": dict((oid, z.gesamtstatus(oid)) for oid in sorted(z.objekte)),
            "wartet_auf_rolle": dict((r, z.wartet_auf(rolle=r)) for r in sorted(set(rollen))),
            "wartet_auf_firma": dict((f, z.wartet_auf(firma=f)) for f in firmen),
            "modelle": dict((m, v["aktuell"]["hash"]) for m, v in z.modelle.items()),
            "ignoriert": len(z.ignoriert),
            "verlauf_laengen": dict((oid, len(o.verlauf)) for oid, o in z.objekte.items()),
            "runden": sorted(z.runden),
        },
    }


def json_schreiben(pfad, daten):
    if not os.path.isdir(os.path.dirname(pfad)):
        os.makedirs(os.path.dirname(pfad))
    with io.open(pfad, "w", encoding="utf-8") as f:
        f.write(json.dumps(daten, ensure_ascii=False, indent=1, sort_keys=True))


def main():
    uhr = Uhr()
    try:
        projekt = Projekt(PROJEKT)
        if os.path.isdir(DEMO):
            shutil.rmtree(DEMO)
        os.makedirs(DEMO)
        projekt.speichern(os.path.join(DEMO, "projekt.json"))
        demo_fuellen(DEMO, uhr)

        kanten = tempfile.mkdtemp(prefix="dbk_kanten_")
        try:
            kanten_fuellen(kanten, uhr)
            fixtures = {"szenarien": {
                "demo": sollwerte(DEMO, projekt),
                "kanten": sollwerte(kanten, projekt),
            }}
        finally:
            shutil.rmtree(kanten, ignore_errors=True)
        json_schreiben(FIXTURES, fixtures)
    finally:
        uhr.zurueck()
    print("Demo:     %s" % DEMO)
    print("Fixtures: %s" % FIXTURES)


if __name__ == "__main__":
    main()

