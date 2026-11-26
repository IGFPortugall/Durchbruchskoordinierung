# Datenformat (Schema 1)

Verbindlich für alle Clients: pyRevit-Extension, Web-App, Berichte.
Referenz-Implementierung: [`src/dbk_core`](../src/dbk_core) (Python 2.7 / 3.x).

## Projektordner

```
<Projektordner>/
├── projekt.json
├── pruefsets/<Firma>.json
├── modelle/<Modell>/<Hash>.frag   + <Hash>.json
├── plaene/<Firma>/<Geschoss>_<Name>.svg   + .json
└── ereignisse/<Firma>/<Zeit>_<Seq>_<Id8>.json
```

Dateien unter `modelle/` und `plaene/` werden nie überschrieben; eine neue Version bekommt
einen neuen Namen (Hash der Quelldatei).

- `<Firma>`: Firmenname, alles außer Buchstaben, Ziffern, `-`, `_` wird zu `_`.
- Jede Firma schreibt **nur** in `ereignisse/<eigene Firma>/`. Dateien werden nie geändert.
- Schreiben: zuerst `<name>.json.tmp`, dann umbenennen.
- Lesen: `.tmp` ignorieren; nicht lesbare JSON-Dateien überspringen und später erneut versuchen;
  Ereignisse, deren `firma` nicht zum Ordner passt, verwerfen.

## Ereignis

```json
{
  "schema": 1,
  "id": "9f0c1a2b4e5d4c8f9a0b1c2d3e4f5a6b",
  "zeit": "2026-11-24T10:20:11.123Z",
  "seq": 17,
  "firma": "IGF",
  "name": "M. Muster",
  "rolle": "TGA",
  "art": "status",
  "objekt": "HLS:4f1c2e3d-...-0004a2b1",
  "daten": { "wert": "abgelehnt", "geometrie_hash": "a1b2c3d4e5f60718", "kommentar": "Zu nah an der Stütze" }
}
```

| Feld | Bedeutung |
|---|---|
| `zeit` | UTC, ISO 8601 mit Millisekunden |
| `seq` | fortlaufend je Firma, ab 1 |
| `objekt` | Prüfobjekt-ID, empfohlen `<Modellkürzel>:<Revit UniqueId>`; `null` bei `pruefrunde_gestartet` |

**Reihenfolge** aller Ereignisse: nach `zeit`, dann `firma`, dann `seq`.

### Arten

| `art` | `daten` | Wer |
|---|---|---|
| `pruefrunde_gestartet` | `{"runde", "name", "frist"}` | Ersteller |
| `eingereicht` | `{"objekt": Objektdaten, "runde", "stand"}` – `stand` = Name des Durchbruch-Stands (optional) | Besitzer (erste einreichende Firma) |
| `geaendert` | `{"objekt": Objektdaten}` | Besitzer |
| `geloescht` | `{}` | Besitzer |
| `status` | `{"wert", "geometrie_hash", "kommentar", "kontext"}` | jede Rolle |
| `nachricht` | `{"text"}` | jede Rolle |
| `modell_veroeffentlicht` | `{"modell", "datei", "hash", "format", "name", "quelle", "stand", "ebenen", "info", "revit_version"}` | Besitzer des Modells (erste veröffentlichende Firma) |
| `modell_ausrichtung` | `{"modell", "x_mm", "y_mm", "z_mm", "drehung_grad"}` – Verschiebung (Revit-Achsen) und Drehung um die senkrechte Achse durch die Modellmitte | nur Besitzer des Modells; alle anderen richten nur lokal im Browser aus |

`kontext` (optional) im Status: Modellversionen, gegen die geprüft wurde, z. B.
`{"ARC": "3f9a1c7e2b4d6a80", "TWP": "c01d..."}`.

Bei `modell_veroeffentlicht` ist `objekt` = `null`. Aktuelle Version eines Modells = letzte
Veröffentlichung seines Besitzers.

### Objektdaten

Pflicht ist nur `geometrie_hash`. Empfohlen:

```json
{
  "nummer": "TGA-2_OG01-0042",
  "kategorie": "Allgemeines Modell", "familie": "IGF_Durchbruch_Rechteck", "typ": "Wand",
  "ebene": "2_OG01",
  "revit_unique_id": "...", "ifc_guid": "...", "modell": "HLS",
  "geometrie": { "min": [x, y, z], "max": [x, y, z], "form": "rechteck",
                 "masse": { "breite": 400, "hoehe": 300 } },
  "flaeche_m2": 0.12,
  "wirt": { "kategorie": "Wände", "tragend": true, "brandwand": false },
  "gewerke": ["Lüftung"]
}
```

Koordinaten und Maße in **mm**, Projektkoordinaten.

### Geometrie-Hash

SHA-1 über kanonisches JSON (`sort_keys`, Trenner `,` `:`) von
`{"min": [...], "max": [...], "form": "...", "masse": {...}}`, alle Zahlen als
`round(wert / 5)` (Ganzzahl). Die ersten 16 Hex-Zeichen.

## Status-Berechnung

1. Ein Objekt gehört der Firma, die es zuerst eingereicht hat. `geaendert`/`geloescht`/`eingereicht`
   anderer Firmen werden ignoriert.
2. `geloescht` entfernt das Objekt aus allen Listen (neu `eingereicht` holt es zurück).
3. Je Rolle gilt die letzte `status`-Entscheidung – nur wenn ihr `geometrie_hash` zum aktuellen passt.
4. Beteiligung je Rolle (`pflicht` / `info`) aus `projekt.json` (siehe `projekt.py`).
5. Gesamtstatus:
   - eine Pflichtrolle mit Status der Wirkung `blockiert` → dieser Status (z. B. `abgelehnt`)
   - alle Pflichtrollen mit Wirkung `freigabe` → `freigegeben`
   - sonst `in_pruefung`
6. „Wartet auf mich“:
   - Prüfer: Pflichtrolle ohne gültige Entscheidung, oder nach nicht-freigebender
     Entscheidung wurde erneut eingereicht.
   - Ersteller: eigenes Objekt blockiert und seither nicht erneut eingereicht.

## projekt.json

```json
{
  "name": "Beispielprojekt",
  "rollen": [{"id": "ARC", "name": "Architektur"}, {"id": "TWP", "name": "Tragwerk"}],
  "status": [{"id": "zurueckgestellt", "name": "Zurückgestellt", "wirkung": "offen", "farbe": "#854F0B"}],
  "standard": {"ARC": "pflicht"},
  "regeln": [
    {"name": "Wand tragend", "wenn": {"wirt.kategorie": "Wände", "wirt.tragend": true},
     "rollen": {"ARC": "pflicht", "TWP": "pflicht", "TGA": "info"}},
    {"name": "Groß", "zusatz": true, "wenn": {"flaeche_m2": {"gt": 1.0}},
     "rollen": {"BH": "pflicht"}}
  ]
}
```

- `freigegeben` (Wirkung `freigabe`) und `abgelehnt` (Wirkung `blockiert`) sind immer vorhanden.
- Wirkungen: `freigabe`, `blockiert`, `offen`.
- Normale Regeln: alle passenden vereinigt; passt keine, gilt `standard`.
  Zusatz-Regeln gelten immer zusätzlich. `pflicht` schlägt `info`.
- Bedingungen: Punkt-Pfad in die Objektdaten; Wert = Gleichheit, oder
  `{"gt"|"gte"|"lt"|"lte"|"ne": x}`, `{"in": [...]}`.
