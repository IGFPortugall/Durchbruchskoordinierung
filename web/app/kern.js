// Statuslogik – JavaScript-Gegenstück zu src/dbk_core (projekt.py, zustand.py).
// Verbindliche Beschreibung: docs/DATENFORMAT.md. Beide Seiten werden mit
// web/test/fixtures.json (aus Python erzeugt) gegeneinander geprüft.

export const PFLICHT = "pflicht";
export const INFO = "info";
const STUFE = { info: 1, pflicht: 2 };

export const FREIGABE = "freigabe";
export const BLOCKIERT = "blockiert";
export const OFFEN = "offen";
const WIRKUNGEN = [FREIGABE, BLOCKIERT, OFFEN];

export const IN_PRUEFUNG = "in_pruefung";
export const FREIGEGEBEN = "freigegeben";

export const ARTEN = ["pruefrunde_gestartet", "eingereicht", "geaendert", "geloescht",
  "status", "nachricht", "modell_veroeffentlicht", "modell_ausrichtung", "modell_entfernt",
  "stand_eingereicht", "stand_zurueckgezogen"];
const PFLICHTFELDER = ["schema", "id", "zeit", "seq", "firma", "name", "rolle", "art", "objekt", "daten"];

export const STANDARD_STATUS = [
  { id: "freigegeben", name: "Freigegeben", wirkung: FREIGABE, farbe: "#3B6D11" },
  { id: "abgelehnt", name: "Abgelehnt", wirkung: BLOCKIERT, farbe: "#A32D2D" },
];

// ------------------------------------------------------------------ Ereignisse

export function ordnername(firma) {
  const s = firma.replace(/[^0-9A-Za-zÄÖÜäöüß_-]+/g, "_").replace(/^_+|_+$/g, "");
  return s || "_";
}

export function istGueltig(e) {
  if (!e || typeof e !== "object") return false;
  for (const f of PFLICHTFELDER) if (!(f in e)) return false;
  return ARTEN.includes(e.art) && e.daten !== null && typeof e.daten === "object";
}

/** Sortierschlüssel als Tupel; Vergleich mit vergleiche(). */
export function schluessel(e) {
  return [e.zeit, e.firma, e.seq];
}

// Vergleicht wie Python-Tupel (Strings per Codepunkt, nicht per Locale).
export function vergleiche(a, b) {
  for (let i = 0; i < a.length; i++) {
    if (a[i] < b[i]) return -1;
    if (a[i] > b[i]) return 1;
  }
  return 0;
}

export function sortiere(ereignisse) {
  return [...ereignisse].sort((a, b) => vergleiche(schluessel(a), schluessel(b)));
}

// -------------------------------------------------------------------- Projekt

export class Projekt {
  constructor(daten = {}) {
    this.name = daten.name || "";
    this.rollen = [...(daten.rollen || [])];
    this.standard = { ...(daten.standard || {}) };
    this.regeln = [...(daten.regeln || [])];
    this.viewer = { ...(daten.viewer || {}) };
    this.status = STANDARD_STATUS.map((s) => ({ ...s }));
    for (const s of daten.status || []) {
      if (!WIRKUNGEN.includes(s.wirkung)) throw new Error(`Status '${s.id}' hat keine gültige Wirkung.`);
      const vorhanden = this.status.find((x) => x.id === s.id);
      if (vorhanden) Object.assign(vorhanden, s);
      else this.status.push({ ...s });
    }
  }

  statusDef(id) {
    return this.status.find((s) => s.id === id) || null;
  }

  wirkung(id) {
    const s = this.statusDef(id);
    return s ? s.wirkung : OFFEN;
  }

  rollenName(id) {
    const r = this.rollen.find((x) => x.id === id);
    return r ? r.name : id;
  }

  beteiligung(objektdaten) {
    const ergebnis = {};
    let normalePassend = false;
    for (const regel of this.regeln) {
      if (regel.zusatz) continue;
      if (passt(regel.wenn || {}, objektdaten)) {
        normalePassend = true;
        vereinige(ergebnis, regel.rollen || {});
      }
    }
    if (!normalePassend) vereinige(ergebnis, this.standard);
    for (const regel of this.regeln) {
      if (regel.zusatz && passt(regel.wenn || {}, objektdaten)) vereinige(ergebnis, regel.rollen || {});
    }
    return ergebnis;
  }

  pflichtrollen(objektdaten) {
    return Object.entries(this.beteiligung(objektdaten))
      .filter(([, s]) => s === PFLICHT).map(([r]) => r).sort();
  }
}

function vereinige(ziel, rollen) {
  for (const [rolle, stufe] of Object.entries(rollen)) {
    if (!(stufe in STUFE)) continue;
    if (STUFE[stufe] > (STUFE[ziel[rolle]] || 0)) ziel[rolle] = stufe;
  }
}

const FEHLT = Symbol("fehlt");

function wert(objekt, pfad) {
  for (const teil of pfad.split(".")) {
    if (objekt && typeof objekt === "object" && !Array.isArray(objekt) && teil in objekt) objekt = objekt[teil];
    else return FEHLT;
  }
  return objekt;
}

function gleich(a, b) {
  return JSON.stringify(a) === JSON.stringify(b);
}

function passt(bedingung, objektdaten) {
  for (const [pfad, erwartet] of Object.entries(bedingung)) {
    const w = wert(objektdaten, pfad);
    if (erwartet !== null && typeof erwartet === "object" && !Array.isArray(erwartet)) {
      if (w === FEHLT) return false;
      for (const [op, x] of Object.entries(erwartet)) {
        const zahl = typeof w === "number" && typeof x === "number";
        if (["gt", "gte", "lt", "lte"].includes(op) && !zahl && typeof w !== typeof x) return false;
        if (op === "gt" && !(w > x)) return false;
        if (op === "gte" && !(w >= x)) return false;
        if (op === "lt" && !(w < x)) return false;
        if (op === "lte" && !(w <= x)) return false;
        if (op === "ne" && gleich(w, x)) return false;
        if (op === "in" && !x.some((y) => gleich(w, y))) return false;
      }
    } else if (w === FEHLT || !gleich(w, erwartet)) {
      return false;
    }
  }
  return true;
}

// -------------------------------------------------------------------- Zustand

export class ObjektZustand {
  constructor(id) {
    this.id = id;
    this.daten = null;
    this.besitzer = null;
    this.erstellerRolle = null;
    this.geloescht = false;
    this.runden = [];
    this.stand = null;
    this.einreichung = null;
    this.letzteEinreichung = null;
    this.entscheidungen = {};
    this.verlauf = [];
  }

  get geometrieHash() {
    return (this.daten || {}).geometrie_hash;
  }

  gueltigeEntscheidung(rolle) {
    const e = this.entscheidungen[rolle];
    return e && e.daten.geometrie_hash === this.geometrieHash ? e : null;
  }
}

export class Zustand {
  constructor(projekt) {
    this.projekt = projekt;
    this.objekte = new Map();
    this.runden = {};
    this.modelle = {};
    this.staende = {};
    this.ignoriert = [];
  }

  gesamtstatus(objektId) {
    const o = this.objekte.get(objektId);
    const p = this.projekt;
    const beteiligung = p.beteiligung(o.daten);
    const pflicht = Object.keys(beteiligung).filter((r) => beteiligung[r] === PFLICHT).sort();
    const rollen = {};
    const alle = [...new Set([...Object.keys(beteiligung), ...Object.keys(o.entscheidungen)])].sort();
    for (const rolle of alle) {
      const g = o.gueltigeEntscheidung(rolle);
      rollen[rolle] = {
        stufe: beteiligung[rolle] || null,
        status: g ? g.daten.wert : null,
        wirkung: g ? p.wirkung(g.daten.wert) : null,
        veraltet: o.entscheidungen[rolle] != null && g == null,
      };
    }
    const blockierend = pflicht.filter((r) => rollen[r].wirkung === BLOCKIERT).map((r) => o.gueltigeEntscheidung(r));
    const erfuellt = pflicht.filter((r) => rollen[r].wirkung === FREIGABE).length;
    let status, wirkung;
    if (blockierend.length) {
      const letzte = sortiere(blockierend).at(-1);
      status = letzte.daten.wert;
      wirkung = BLOCKIERT;
    } else if (pflicht.length && erfuellt === pflicht.length) {
      status = FREIGEGEBEN; wirkung = FREIGABE;
    } else {
      status = IN_PRUEFUNG; wirkung = OFFEN;
    }
    return {
      status, wirkung,
      pflicht_erfuellt: erfuellt,
      pflicht_gesamt: pflicht.length,
      geaendert: Object.values(rollen).some((r) => r.veraltet),
      rollen,
    };
  }

  wartetAuf({ firma = null, rolle = null } = {}) {
    const ergebnis = [];
    for (const oid of [...this.objekte.keys()].sort()) {
      const o = this.objekte.get(oid);
      if (rolle !== null && this._wartetAufPruefer(o, rolle)) ergebnis.push(oid);
      else if (firma !== null && o.besitzer === firma && this._wartetAufErsteller(o)) ergebnis.push(oid);
    }
    return ergebnis;
  }

  _wartetAufPruefer(o, rolle) {
    if (this.projekt.beteiligung(o.daten)[rolle] !== PFLICHT) return false;
    const g = o.gueltigeEntscheidung(rolle);
    if (!g) return true;
    if (this.projekt.wirkung(g.daten.wert) === FREIGABE) return false;
    return o.letzteEinreichung !== null && vergleiche(o.letzteEinreichung, schluessel(g)) > 0;
  }

  _wartetAufErsteller(o) {
    const gs = this.gesamtstatus(o.id);
    if (gs.wirkung !== BLOCKIERT) return false;
    let letzte = null;
    for (const [r, info] of Object.entries(gs.rollen)) {
      if (info.wirkung === BLOCKIERT && info.stufe === PFLICHT) {
        const k = schluessel(o.gueltigeEntscheidung(r));
        if (!letzte || vergleiche(k, letzte) > 0) letzte = k;
      }
    }
    return o.letzteEinreichung === null || vergleiche(o.letzteEinreichung, letzte) < 0;
  }
}

/** Momentaufnahme eines Stands – gleiche Regeln wie zustand._stand_eingereicht (Python). */
function standEingereicht(z, alle, e) {
  const firma = e.firma, d = e.daten, stand = d.stand || null;
  const objekte = d.objekte || {}, mitglieder = new Set(d.mitglieder || []);
  const sk = schluessel(e), runde = d.runde ?? null;
  let anzahl = 0;
  for (const oid of [...mitglieder].sort()) {
    let o = alle.get(oid);
    const neu = objekte[oid];
    if (neu !== undefined && neu !== null) {
      if (!o) { o = new ObjektZustand(oid); alle.set(oid, o); }
      if (o.besitzer === null) { o.besitzer = firma; o.erstellerRolle = e.rolle; }
      if (o.besitzer !== firma) continue;
      const warAktiv = o.daten !== null && !o.geloescht;
      if (warAktiv && o.geometrieHash === neu.geometrie_hash) {
        o.einreichung = "unveraendert";
      } else {
        o.einreichung = warAktiv ? "geaendert" : "neu";
        o.letzteEinreichung = sk;
        if (runde && !o.runden.includes(runde)) o.runden.push(runde);
        o.verlauf.push({ ...e, art: "eingereicht", objekt: oid,
          daten: { objekt: neu, runde, stand: d.stand, einreichung: o.einreichung } });
      }
      o.daten = { ...neu };
      o.geloescht = false;
    } else {
      if (!o || o.besitzer !== firma || o.daten === null || o.geloescht) continue;
      o.einreichung = "unveraendert";
    }
    o.stand = stand;
    anzahl++;
  }
  for (const [oid, o] of alle) {
    if (o.besitzer === firma && o.stand === stand && !o.geloescht && !mitglieder.has(oid)) o.geloescht = true;
  }
  z.staende[`${firma}|${d.stand}`] = { firma, stand: d.stand, zeit: e.zeit, runde, anzahl };
}

export function berechne(ereignisse, projekt) {
  const z = new Zustand(projekt);
  const alle = new Map();
  for (const e of sortiere(ereignisse)) {
    const art = e.art;
    if (art === "pruefrunde_gestartet") {
      const d = { ...e.daten, firma: e.firma, gestartet: e.zeit };
      if (d.runde) z.runden[d.runde] = d;
      continue;
    }
    if (art === "modell_veroeffentlicht") {
      const d = { ...e.daten, firma: e.firma, veroeffentlicht: e.zeit };
      if (!z.modelle[d.modell]) z.modelle[d.modell] = { besitzer: e.firma, aktuell: null, versionen: [], ausrichtung: null };
      const m = z.modelle[d.modell];
      if (m.besitzer !== e.firma) { z.ignoriert.push(e); continue; }
      m.versionen.push(d);
      m.aktuell = d;
      continue;
    }
    if (art === "modell_ausrichtung") {
      const m = z.modelle[e.daten.modell];
      if (!m || m.besitzer !== e.firma) { z.ignoriert.push(e); continue; }
      m.ausrichtung = { ...e.daten };
      continue;
    }
    if (art === "modell_entfernt") {
      const m = z.modelle[e.daten.modell];
      if (!m || m.besitzer !== e.firma) { z.ignoriert.push(e); continue; }
      delete z.modelle[e.daten.modell];   // gelöscht ist gelöscht; neu veröffentlichen beginnt von vorn
      continue;
    }
    if (art === "stand_eingereicht") { standEingereicht(z, alle, e); continue; }
    if (art === "stand_zurueckgezogen") {
      const stand = e.daten.stand || null;
      for (const o of alle.values()) {
        if (o.besitzer === e.firma && !o.geloescht && o.stand === stand) {
          o.geloescht = true;
          o.entscheidungen = {};      // zurückgezogen: erneutes Einreichen beginnt von vorn
        }
      }
      delete z.staende[`${e.firma}|${stand || ""}`];
      continue;
    }
    let o = alle.get(e.objekt);
    if (!o) { o = new ObjektZustand(e.objekt); alle.set(e.objekt, o); }

    if (art === "eingereicht" || art === "geaendert" || art === "geloescht") {
      if (o.besitzer === null && art === "eingereicht") {
        o.besitzer = e.firma;
        o.erstellerRolle = e.rolle;
      }
      if (o.besitzer !== e.firma) { z.ignoriert.push(e); continue; }
      if (art === "geloescht") {
        o.geloescht = true;
      } else {
        o.daten = { ...e.daten.objekt };
        if (art === "eingereicht") {
          o.geloescht = false;
          o.letzteEinreichung = schluessel(e);
          const runde = e.daten.runde;
          if (runde && !o.runden.includes(runde)) o.runden.push(runde);
          if (e.daten.stand) o.stand = e.daten.stand;
        }
      }
      o.verlauf.push(e);
    } else if (art === "status") {
      o.entscheidungen[e.rolle] = e;
      o.verlauf.push(e);
    } else if (art === "nachricht") {
      o.verlauf.push(e);
    }
  }
  for (const [oid, o] of alle) {
    if (o.daten !== null && !o.geloescht) z.objekte.set(oid, o);
  }
  return z;
}
