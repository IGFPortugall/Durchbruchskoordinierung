// Lesen und Schreiben des gemeinsamen Projektordners – Gegenstück zu src/dbk_core/ablage.py.
//
// Zwei Zugänge:
//   OrdnerZugang – echter Ordner über die File System Access API (Chrome/Edge)
//   HttpZugang   – Entwicklungs-Server (werkzeuge/devserver.py)
import { istGueltig, ordnername, sortiere } from "./kern.js";

const SCHEMA = 1;

// ------------------------------------------------------------------ Zugänge

export class HttpZugang {
  constructor(basis = "") { this.basis = basis; this.name = "Entwicklungs-Server"; }

  static async verfuegbar() {
    try { return (await fetch("/api/liste", { method: "GET" })).ok; } catch { return false; }
  }

  async liste() {
    const r = await fetch(this.basis + "/api/liste");
    return (await r.json()).dateien.map((d) => d.pfad);
  }

  async lies(pfad) {
    const r = await fetch(this.basis + "/projekt/" + pfad.split("/").map(encodeURIComponent).join("/"));
    if (!r.ok) throw new Error(`${pfad}: ${r.status}`);
    return r.arrayBuffer();
  }

  async schreibe(pfad, inhalt) {
    const r = await fetch(this.basis + "/projekt/" + pfad.split("/").map(encodeURIComponent).join("/"),
      { method: "PUT", body: inhalt });
    if (!r.ok) throw new Error(`Schreiben fehlgeschlagen (${r.status}): ${pfad}`);
  }
}

export class OrdnerZugang {
  constructor(handle) { this.handle = handle; this.name = handle.name; }

  static unterstuetzt() { return "showDirectoryPicker" in window; }

  static async waehlen() {
    const handle = await window.showDirectoryPicker({ id: "dbk-projekt", mode: "readwrite" });
    return new OrdnerZugang(handle);
  }

  async _ordner(teile, anlegen = false) {
    let h = this.handle;
    for (const t of teile) h = await h.getDirectoryHandle(t, { create: anlegen });
    return h;
  }

  async liste() {
    const ergebnis = [];
    const laufe = async (h, praefix, tiefe) => {
      for await (const [name, kind] of h.entries()) {
        if (kind === "file" && !name.endsWith(".tmp") && !name.endsWith(".crswap")) ergebnis.push(praefix + name);
        else if (kind === "directory" && tiefe < 3) await laufe(await h.getDirectoryHandle(name), praefix + name + "/", tiefe + 1);
      }
    };
    for (const sub of ["ereignisse", "modelle", "plaene", "pruefsets"]) {
      try { await laufe(await this._ordner([sub]), sub + "/", 1); } catch { /* Ordner fehlt */ }
    }
    try { await this.handle.getFileHandle("projekt.json"); ergebnis.push("projekt.json"); } catch { /* fehlt */ }
    return ergebnis;
  }

  async lies(pfad) {
    const teile = pfad.split("/");
    const datei = teile.pop();
    const h = await (await this._ordner(teile)).getFileHandle(datei);
    return (await h.getFile()).arrayBuffer();
  }

  async schreibe(pfad, inhalt) {
    const teile = pfad.split("/");
    const datei = teile.pop();
    const ordner = await this._ordner(teile, true);
    try {
      await ordner.getFileHandle(datei);
      throw new Error("Datei existiert bereits: " + pfad);
    } catch (e) {
      if (e.name !== "NotFoundError") throw e;
    }
    const h = await ordner.getFileHandle(datei, { create: true });
    const w = await h.createWritable();   // schreibt in eine Hilfsdatei, ersetzt erst beim Schließen
    await w.write(inhalt);
    await w.close();
  }
}

// ------------------------------------------------------------------ Ablage

const text = (buffer) => new TextDecoder("utf-8").decode(buffer).replace(/^﻿/, "");

export class Ablage {
  constructor(zugang) {
    this.zugang = zugang;
    this._gelesen = new Set();
    this._ereignisse = [];
    this.unvollstaendig = new Set();
    this.verworfen = new Set();
    this._seq = new Map();
  }

  async ladeProjekt() {
    return JSON.parse(text(await this.zugang.lies("projekt.json")));
  }

  async ladeNeue() {
    const neu = [];
    const pfade = (await this.zugang.liste()).filter((p) => /^ereignisse\/[^/]+\/[^/]+\.json$/.test(p)).sort()
      .filter((p) => !this._gelesen.has(p) && !this.verworfen.has(p));
    // Viele kleine Dateien: parallel lesen (bei Tausenden Ereignissen sonst Sekunden bis Minuten)
    const ergebnisse = new Array(pfade.length);
    let naechste = 0;
    const arbeiter = async () => {
      while (naechste < pfade.length) {
        const i = naechste++;
        try { ergebnisse[i] = JSON.parse(text(await this.zugang.lies(pfade[i]))); } catch { ergebnisse[i] = undefined; }
      }
    };
    await Promise.all(Array.from({ length: Math.min(24, pfade.length) }, arbeiter));
    pfade.forEach((pfad, i) => {
      const e = ergebnisse[i];
      if (e === undefined) { this.unvollstaendig.add(pfad); return; }
      this.unvollstaendig.delete(pfad);
      const ordner = pfad.split("/")[1];
      if (!istGueltig(e) || ordnername(e.firma) !== ordner) { this.verworfen.add(pfad); return; }
      this._gelesen.add(pfad);
      this._ereignisse.push(e);
      neu.push(e);
    });
    return neu;
  }

  alle() { return sortiere(this._ereignisse); }

  async liesBinaer(pfadOderUrl) {
    if (/^https?:\/\//.test(pfadOderUrl)) {
      const r = await fetch(pfadOderUrl);
      if (!r.ok) throw new Error(`${pfadOderUrl}: ${r.status}`);
      return r.arrayBuffer();
    }
    return this.zugang.lies(pfadOderUrl);
  }

  async _naechsteSeq(firma) {
    if (!this._seq.has(firma)) {
      const ordner = ordnername(firma);
      let hoechste = 0;
      for (const p of await this.zugang.liste()) {
        const m = p.match(/^ereignisse\/([^/]+)\/[^_]+_(\d+)_[^/]+\.json$/);
        if (m && m[1] === ordner) hoechste = Math.max(hoechste, parseInt(m[2], 10));
      }
      this._seq.set(firma, hoechste);
    }
    return this._seq.get(firma) + 1;
  }

  /** absender: {firma, name, rolle} */
  async schreibe(absender, art, objekt, daten) {
    if (!absender || !absender.firma || !absender.name || !absender.rolle) throw new Error("Absender unvollständig.");
    const seq = await this._naechsteSeq(absender.firma);
    const e = {
      schema: SCHEMA,
      id: crypto.randomUUID().replace(/-/g, ""),
      zeit: new Date().toISOString(),
      seq,
      firma: absender.firma, name: absender.name, rolle: absender.rolle,
      art, objekt: objekt ?? null, daten: daten || {},
    };
    if (!istGueltig(e)) throw new Error("Ungültiges Ereignis.");
    const name = `${e.zeit.replace(/[-:.]/g, "")}_${String(seq).padStart(6, "0")}_${e.id.slice(0, 8)}.json`;
    const pfad = `ereignisse/${ordnername(absender.firma)}/${name}`;
    await this.zugang.schreibe(pfad, JSON.stringify(e, null, 1));
    this._seq.set(absender.firma, seq);
    this._gelesen.add(pfad);
    this._ereignisse.push(e);
    return e;
  }
}
