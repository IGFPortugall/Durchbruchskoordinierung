// Web-App: verbindet Ablage (Projektordner), Statuslogik und Viewer mit der Oberfläche.
import { Ablage, HttpZugang, OrdnerZugang } from "./ablage.js";
import { BLOCKIERT, FREIGABE, OFFEN, PFLICHT, Projekt, berechne } from "./kern.js";
import { Viewer, klassenName, NAVIGATION, NAV_STANDARD } from "./viewer.js";
import { THREE } from "./bibliotheken.js";

const $ = (id) => document.getElementById(id);
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const NACHLADEN_MS = 5000;

const app = {
  ablage: null, projekt: null, zustand: null, viewer: null, absender: null,
  auswahl: null, geladeneModelle: new Map(), sichtbareModelle: new Set(),
};
window.__dbk = app; // zur Fehlersuche in der Browser-Konsole

// ---------------------------------------------------------------- Einstellungen (nur lokal)

function lokal(name, wert) {
  try {
    if (wert === undefined) return JSON.parse(localStorage.getItem("dbk-" + name) || "null");
    localStorage.setItem("dbk-" + name, JSON.stringify(wert));
  } catch { return null; }
  return wert;
}

// ---------------------------------------------------------------- Start

async function start() {
  zeigeHinweis("Projekt wird geladen …");
  const zugang = (await HttpZugang.verfuegbar()) ? new HttpZugang() : await ordnerWaehlen();
  app.ablage = new Ablage(zugang);
  app.projekt = new Projekt(await app.ablage.ladeProjekt());
  $("projektname").textContent = app.projekt.name || zugang.name;
  document.title = (app.projekt.name || "Projekt") + " – Durchbruchskoordinierung";
  await app.ablage.ladeNeue();
  app.zustand = berechne(app.ablage.alle(), app.projekt);

  app.absender = lokal("absender");
  if (!app.absender || !app.projekt.rollen.some((r) => r.id === app.absender.rolle)) app.absender = await startDialog();
  zeigeBenutzer();

  app.viewer = new Viewer($("viewer"));
  app.viewer.versatz = app.projekt.viewer.versatz_mm || [0, 0, 0];
  await app.viewer.init();
  app.viewer.onAuswahl = (id) => waehle(id, false);
  app.viewer.onBauteil = (a) => {
    app.bauteil = a;
    if (a) {
      app.auswahl = null;
      app.viewer.waehle(null);
      document.querySelectorAll(".eintrag.aktiv").forEach((el) => el.classList.remove("aktiv"));
    }
    detailZeichnen();
  };
  app.viewer.onSchnitteGeaendert = () => {
    $("schnitt-anzahl").textContent = app.viewer.anzahlSchnitte;
    if (!$("panel").hidden && ansichtEinstellungen().reiter === "schnitte" && !document.activeElement?.dataset?.achse) panelZeichnen();
  };
  {
    const e = ansichtEinstellungen();
    app.viewer.navigation(e.nav);
    app.viewer.boxRahmen = e.boxRahmen;
    app.viewer.schnittGriffeZeigen(e.griffe);
  }
  bedienelemente();
  await modelleLaden();
  allesZeichnen();
  zeigeHinweis("");
  setInterval(nachladen, NACHLADEN_MS);
}

function ordnerWaehlen() {
  return new Promise((fertig) => {
    if (!OrdnerZugang.unterstuetzt()) {
      dialog(`<h2>Browser nicht unterstützt</h2><p>Bitte Chrome oder Edge verwenden – nur diese können einen Projektordner direkt öffnen.</p>`);
      return;
    }
    const d = dialog(`<h2>Projektordner öffnen</h2>
      <p>Wählen Sie den gemeinsamen Ordner der Durchbruchskoordinierung (der Ordner mit <code>projekt.json</code>).</p>
      <div class="reihe"><button id="ordner-knopf">Ordner wählen</button></div>
      <div id="ordner-fehler" class="fehlermeldung"></div>`);
    d.querySelector("#ordner-knopf").onclick = async () => {
      try {
        const z = await OrdnerZugang.waehlen();
        await z.lies("projekt.json");
        schliesseDialog();
        fertig(z);
      } catch (e) {
        d.querySelector("#ordner-fehler").textContent = e.name === "NotFoundError"
          ? "In diesem Ordner liegt keine projekt.json." : (e.name === "AbortError" ? "" : e.message);
      }
    };
  });
}

function startDialog() {
  return new Promise((fertig) => {
    const a = app.absender || {};
    const firmen = [...new Set(app.ablage.alle().map((e) => e.firma))].sort();
    const d = dialog(`<h2>Wer arbeitet?</h2>
      <label>Name<input id="d-name" value="${esc(a.name)}" placeholder="Vorname Nachname" autocomplete="name"></label>
      <label>Firma<input id="d-firma" value="${esc(a.firma)}" list="d-firmen" placeholder="Firma">
        <datalist id="d-firmen">${firmen.map((f) => `<option value="${esc(f)}">`).join("")}</datalist></label>
      <label>Rolle<select id="d-rolle">${app.projekt.rollen.map((r) =>
        `<option value="${esc(r.id)}" ${r.id === a.rolle ? "selected" : ""}>${esc(r.name)}</option>`).join("")}</select></label>
      <div id="d-fehler" class="fehlermeldung"></div>
      <div class="reihe"><button id="d-ok">Starten</button></div>`);
    const ok = () => {
      const w = { name: d.querySelector("#d-name").value.trim(), firma: d.querySelector("#d-firma").value.trim(), rolle: d.querySelector("#d-rolle").value };
      if (!w.name || !w.firma) { d.querySelector("#d-fehler").textContent = "Bitte Name und Firma eintragen."; return; }
      lokal("absender", w);
      schliesseDialog();
      fertig(w);
    };
    d.querySelector("#d-ok").onclick = ok;
    d.addEventListener("keydown", (e) => { if (e.key === "Enter") ok(); });
    d.querySelector("#d-name").focus();
  });
}

function dialog(html) {
  const h = $("dialog");
  h.innerHTML = `<div class="dialog">${html}</div>`;
  h.hidden = false;
  return h.firstElementChild;
}
function schliesseDialog() { $("dialog").hidden = true; $("dialog").innerHTML = ""; }

function zeigeBenutzer() {
  const a = app.absender;
  $("benutzer").textContent = `${a.name} · ${app.projekt.rollenName(a.rolle)}`;
  $("benutzer").title = `${a.firma} – klicken zum Ändern`;
}

function zeigeHinweis(text) { $("hinweis").textContent = text; }

// ---------------------------------------------------------------- Modelle

async function modelleLaden() {
  const ebenen = [];
  const ansicht = ansichtEinstellungen();
  for (const [id, m] of Object.entries(app.zustand.modelle)) {
    const v = m.aktuell;
    if (v.ebenen && (!ebenen.length || id === "ARC")) ebenen.splice(0, ebenen.length, ...v.ebenen);
    if (ansicht.nichtLaden.includes(id)) continue;          // „nur bei mir nicht laden“
    if (app.geladeneModelle.get(id) === v.hash) continue;
    zeigeHinweis(`Modell ${id} wird geladen …`);
    try {
      if (/\.ifc$/i.test(v.datei)) await ifcLaden(id, v);
      else if (/\.fbx$/i.test(v.datei)) {
        const info = v.info ? JSON.parse(new TextDecoder("utf-8").decode(await app.ablage.liesBinaer(v.info))) : null;
        await app.viewer.ladeFbx(id, await app.ablage.liesBinaer(v.datei), info);
      } else await app.viewer.ladeModell(id, await app.ablage.liesBinaer(v.datei));
      app.geladeneModelle.set(id, v.hash);
      app.sichtbareModelle.add(id);
    } catch (e) {
      console.error(e);
      zeigeHinweis(`Modell ${id} konnte nicht geladen werden: ${e.message}`);
    }
  }
  if (!app.ersteAnsicht && app.geladeneModelle.size) { app.ersteAnsicht = true; await app.viewer.allesZeigen(); }
  if (!ebenen.length && app.viewer.ifcEbenen?.size) {
    for (const [name, hoehe_mm] of app.viewer.ifcEbenen) ebenen.push({ name, hoehe_mm });
  }
  app.viewer.setzeEbenen(ebenen);
  const g = $("geschoss"), vorher = g.value;
  g.innerHTML = `<option value="">Alle Geschosse</option>` +
    [...app.viewer.ebenen].reverse().map((e) => `<option>${esc(e.name)}</option>`).join("");
  g.value = vorher;
  ebenenSchalter();
  zeigeHinweis(app.geladeneModelle.size ? "" :
    "Noch kein Modell. Oben „Modell hinzufügen“ (IFC) oder in Revit: DBK → Modell veröffentlichen.");
}

/** IFC: vorhandene Fragments nutzen, sonst einmal umwandeln und für alle ablegen. */
async function ifcLaden(id, v) {
  const frag = v.datei.replace(/\.ifc$/i, ".frag");
  try {
    await app.viewer.ladeModell(id, await app.ablage.liesBinaer(frag));
    return;
  } catch { /* noch nicht umgewandelt */ }
  zeigeHinweis(`Modell ${id}: IFC wird in Fragments umgewandelt (einmalig) …`);
  const puffer = await app.viewer.ladeIfc(id, await app.ablage.liesBinaer(v.datei),
    (p) => zeigeHinweis(`Modell ${id}: Umwandlung ${Math.round((p.progress ?? p) * 100) || ""} % …`));
  try {
    await app.ablage.zugang.schreibe(frag, puffer);
  } catch (e) {
    console.warn("Fragments konnten nicht abgelegt werden (evtl. schon vorhanden):", e.message);
  }
}

/** IFC-Datei hochladen: ablegen unter modelle/<Kürzel>/<Hash>.ifc und veröffentlichen. */
function modellDialog() {
  const vorschlag = { ARC: "Architektur", TWP: "Tragwerk", HLS: "TGA HLS", ELT: "Elektro", LAB: "Labor" };
  const d = dialog(`<h2>Modell hinzufügen</h2>
    <p style="margin:0;color:var(--text-2)">IFC-Datei wählen. Sie wird einmalig in Fragments umgewandelt und liegt danach für alle im Projektordner.</p>
    <label>IFC-Datei<input id="m-datei" type="file" accept=".ifc"></label>
    <label>Kürzel<input id="m-kuerzel" list="m-kuerzel-liste" value="ARC" title="Unter diesem Namen erscheint das Modell im Viewer">
      <datalist id="m-kuerzel-liste">${Object.entries(vorschlag).map(([k, n]) => `<option value="${k}">${n}</option>`).join("")}</datalist></label>
    <div id="m-fehler" class="fehlermeldung"></div>
    <div class="reihe"><button id="m-abbrechen">Abbrechen</button><button id="m-ok">Hochladen</button></div>`);
  d.querySelector("#m-abbrechen").onclick = schliesseDialog;
  d.querySelector("#m-ok").onclick = async () => {
    const datei = d.querySelector("#m-datei").files[0];
    const kuerzel = d.querySelector("#m-kuerzel").value.trim().toUpperCase().replace(/[^A-Z0-9_-]/g, "");
    const fehler = (t) => { d.querySelector("#m-fehler").textContent = t; };
    if (!datei) return fehler("Bitte eine IFC-Datei wählen.");
    if (!kuerzel) return fehler("Bitte ein Kürzel angeben, z. B. ARC.");
    const besitzer = app.zustand.modelle[kuerzel]?.besitzer;
    if (besitzer && besitzer !== app.absender.firma) return fehler(`Das Modell ${kuerzel} gehört ${besitzer}. Bitte ein anderes Kürzel wählen.`);
    d.querySelector("#m-ok").disabled = true;
    try {
      fehler("Datei wird gelesen …");
      const daten = await datei.arrayBuffer();
      const hash = [...new Uint8Array(await crypto.subtle.digest("SHA-1", daten))]
        .map((b) => b.toString(16).padStart(2, "0")).join("").slice(0, 16);
      const pfad = `modelle/${kuerzel}/${hash}.ifc`;
      fehler("Datei wird in den Projektordner kopiert …");
      try { await app.ablage.zugang.schreibe(pfad, daten); } catch (e) { if (!/existiert|409/.test(e.message)) throw e; }
      await app.ablage.schreibe(app.absender, "modell_veroeffentlicht", null, {
        modell: kuerzel, datei: pfad, hash, format: "ifc", quelle: datei.name,
        stand: new Date().toLocaleString("de-DE"), groesse_mb: Math.round(daten.byteLength / 1e4) / 100,
      });
      schliesseDialog();
      app.zustand = berechne(app.ablage.alle(), app.projekt);
      await modelleLaden();
      allesZeichnen();
    } catch (e) {
      console.error(e);
      fehler("Hochladen fehlgeschlagen: " + e.message);
      d.querySelector("#m-ok").disabled = false;
    }
  };
}

// ---------------------------------------------------------------- Einstellungsfenster „Ansicht“

function ansichtEinstellungen(neu) {
  const alt = lokal("ansicht") || {};
  const e = { reiter: "modelle", nav: { ...NAV_STANDARD }, nichtLaden: [], boxRahmen: true, griffe: true, ...alt };
  if (neu) { Object.assign(e, neu); lokal("ansicht", e); }
  return e;
}

function ebenenSchalter() { if (!$("panel").hidden) panelZeichnen(); }

function panelUmschalten() {
  const p = $("panel");
  p.hidden = !p.hidden;
  $("einstellungen").classList.toggle("an", !p.hidden);
  if (!p.hidden) panelZeichnen();
}

function panelZeichnen() {
  const e = ansichtEinstellungen();
  const reiter = [["modelle", "Modelle"], ["schnitte", "Schnitte"], ["navigation", "Navigation"], ["darstellung", "Darstellung"]];
  const kopf = `<div class="p-kopf">${reiter.map(([k, n]) => `<button data-reiter="${k}" class="${e.reiter === k ? "an" : ""}">${n}</button>`).join("")}
    <button class="p-zu" title="Schließen">✕</button></div>`;
  let inhalt = "";
  const v = app.viewer;
  if (e.reiter === "modelle") {
    const alle = Object.entries(app.zustand.modelle);
    inhalt = alle.length ? alle.map(([id, m]) => {
      const geladen = app.geladeneModelle.has(id), sichtbar = geladen && v.modellSichtbar(id);
      const kats = v.kategorien?.get(id) || [];
      const nicht = e.nichtLaden.includes(id);
      return `<div class="p-modell">
        <div class="p-zeile"><label class="p-haupt"><input type="checkbox" data-modell="${esc(id)}" ${sichtbar ? "checked" : ""} ${geladen ? "" : "disabled"}> <b>${esc(id)}</b></label>
          <span class="p-klein">${esc((m.aktuell.format || "frag").toUpperCase())} · ${esc(m.aktuell.stand || "")} · ${esc(m.besitzer)}</span></div>
        ${kats.length ? `<details><summary>${kats.length} Kategorien</summary><div class="p-kats">${kats.map((k) =>
          `<label><input type="checkbox" data-modell="${esc(id)}" data-kat="${esc(k.name)}" ${k.an ? "checked" : ""}> ${esc(k.name)}${k.anzahl ? ` <span class="p-klein">${k.anzahl}</span>` : ""}</label>`).join("")}</div></details>` : ""}
        <label class="p-klein" title="Wird bei Ihnen nicht geladen – spart Zeit bei vielen oder alten Modellen. Für andere ändert sich nichts.">
          <input type="checkbox" data-nicht="${esc(id)}" ${nicht ? "checked" : ""}> bei mir nicht laden</label>
      </div>`;
    }).join("") : `<p class="p-klein">Noch keine Modelle im Projekt.</p>`;
  } else if (e.reiter === "schnitte") {
    const g = v.modellGrenzen(), b = v.box;
    const regler = (achse, name) => {
      const lo = g.min[achse], hi = g.max[achse], schritt = Math.max(0.05, (hi - lo) / 400);
      const wmin = b.an ? b.min[achse] : lo, wmax = b.an ? b.max[achse] : hi;
      return `<div class="p-regler"><span>${name}</span>
        <input type="range" data-achse="${achse}" data-seite="min" min="${lo}" max="${hi}" step="${schritt}" value="${wmin}">
        <input type="range" data-achse="${achse}" data-seite="max" min="${lo}" max="${hi}" step="${schritt}" value="${wmax}"></div>`;
    };
    const frei = v.freieSchnitte();
    inhalt = `<div class="p-abschnitt">Schnittbox</div>
      <label class="p-haupt"><input type="checkbox" id="p-box" ${b.an ? "checked" : ""}> Schnittbox ein</label>
      ${regler("x", "Ost–West")}${regler("z", "Nord–Süd")}${regler("y", "Höhe")}
      <div class="p-knoepfe"><button id="p-box-auswahl" title="Um den gewählten Durchbruch bzw. das gewählte Bauteil">Um Auswahl</button>
        <button id="p-box-geschoss" title="Höhe auf das gewählte Geschoss begrenzen">Auf Geschoss</button>
        <button id="p-box-alles">Zurücksetzen</button></div>
      <label class="p-klein"><input type="checkbox" id="p-rahmen" ${e.boxRahmen ? "checked" : ""}> Rahmen der Box zeigen</label>
      <div class="p-abschnitt">Schnittebenen</div>
      ${frei.length ? frei.map((s) => `<div class="p-zeile"><label><input type="checkbox" data-schnitt="${esc(s.id)}" ${s.an ? "checked" : ""}> ${esc(s.beschreibung)}</label>
        <span><button data-umdrehen="${esc(s.id)}" title="Andere Seite wegschneiden">⇅</button><button data-loeschen="${esc(s.id)}" title="Löschen">✕</button></span></div>`).join("")
        : `<p class="p-klein">Keine. Oben „Schnitt setzen“, dann auf eine Fläche klicken; die Ebene am Pfeil ziehen.</p>`}
      <label class="p-klein"><input type="checkbox" id="p-griffe" ${e.griffe ? "checked" : ""}> Ebenen und Pfeile anzeigen</label>`;
  } else if (e.reiter === "navigation") {
    inhalt = `<div class="p-abschnitt">Maussteuerung</div>
      ${Object.entries(NAVIGATION).map(([k, n]) => `<label class="p-wahl"><input type="radio" name="p-nav" value="${k}" ${e.nav.art === k ? "checked" : ""}>
        <span><b>${esc(n.name)}</b><br><span class="p-klein">${esc(n.hilfe)}</span></span></label>`).join("")}
      <label class="p-haupt"><input type="checkbox" id="p-drehpunkt" ${e.nav.drehpunkt ? "checked" : ""}> Drehen um den Punkt unter der Maus</label>
      <label class="p-haupt"><input type="checkbox" id="p-cursor" ${e.nav.zoomZumCursor ? "checked" : ""}> Zoomen zum Mauszeiger</label>
      <div class="p-regler"><span>Zoom-Tempo</span><input type="range" id="p-tempo" min="0.3" max="3" step="0.1" value="${e.nav.tempo}"></div>
      <p class="p-klein">Doppelklick auf ein Bauteil zoomt heran. „Alles zeigen“ oben setzt die Ansicht zurück.</p>`;
  } else {
    inhalt = `<div class="p-abschnitt">Darstellung</div>
      <label class="p-haupt"><input type="checkbox" id="p-beschriftung" ${v.beschriftung ? "checked" : ""}> Beschriftung der Durchbrüche (Nummer · Größe)</label>`;
  }
  const p = $("panel");
  p.innerHTML = kopf + `<div class="p-inhalt">${inhalt}</div>`;

  p.querySelectorAll("[data-reiter]").forEach((b) => b.onclick = () => { ansichtEinstellungen({ reiter: b.dataset.reiter }); panelZeichnen(); });
  p.querySelector(".p-zu").onclick = panelUmschalten;
  p.querySelectorAll("input[data-modell]").forEach((i) => i.onchange = () => {
    if (i.dataset.kat) v.setzeKategorieSichtbar(i.dataset.modell, i.dataset.kat, i.checked);
    else v.setzeModellSichtbar(i.dataset.modell, i.checked);
  });
  p.querySelectorAll("input[data-nicht]").forEach((i) => i.onchange = () => {
    const liste = new Set(ansichtEinstellungen().nichtLaden);
    i.checked ? liste.add(i.dataset.nicht) : liste.delete(i.dataset.nicht);
    ansichtEinstellungen({ nichtLaden: [...liste] });
    if (i.checked) { v.setzeModellSichtbar(i.dataset.nicht, false); zeigeHinweis("Wird beim nächsten Öffnen nicht mehr geladen."); }
    else modelleLaden();
  });
  const box = p.querySelector("#p-box");
  if (box) {
    box.onchange = () => { box.checked ? v.schnittboxSetzen(v.modellGrenzen().min, v.modellGrenzen().max) : v.schnittboxAus(); panelZeichnen(); };
    p.querySelectorAll("input[data-achse]").forEach((r) => r.oninput = () => {
      if (!v.box.an) { const g = v.modellGrenzen(); v.schnittboxSetzen(g.min, g.max); p.querySelector("#p-box").checked = true; }
      v.schnittboxSeite(r.dataset.achse, r.dataset.seite, parseFloat(r.value));
    });
    p.querySelector("#p-box-auswahl").onclick = () => { v.schnittboxUm(app.auswahl); panelZeichnen(); };
    p.querySelector("#p-box-alles").onclick = () => { v.schnittboxAus(); panelZeichnen(); };
    p.querySelector("#p-box-geschoss").onclick = () => {
      const i = v.ebenen.findIndex((x) => x.name === v.geschoss);
      if (i < 0) { zeigeHinweis("Oben zuerst ein Geschoss wählen."); return; }
      const g = v.modellGrenzen(), lo = v.ebenen[i].y - 0.3, hi = v.ebenen[i + 1] ? v.ebenen[i + 1].y : g.max.y;
      v.schnittboxSetzen(new THREE.Vector3(g.min.x, lo, g.min.z), new THREE.Vector3(g.max.x, hi, g.max.z));
      panelZeichnen();
    };
    p.querySelector("#p-rahmen").onchange = (ev) => { ansichtEinstellungen({ boxRahmen: ev.target.checked }); v.boxRahmen = ev.target.checked; v._boxAnwenden(v.box.an); };
    p.querySelector("#p-griffe").onchange = (ev) => { ansichtEinstellungen({ griffe: ev.target.checked }); v.schnittGriffeZeigen(ev.target.checked); };
    p.querySelectorAll("input[data-schnitt]").forEach((c) => c.onchange = () => v.schnittUmschalten(c.dataset.schnitt, c.checked));
    p.querySelectorAll("[data-umdrehen]").forEach((b) => b.onclick = async () => { await v.schnittUmdrehen(b.dataset.umdrehen); panelZeichnen(); });
    p.querySelectorAll("[data-loeschen]").forEach((b) => b.onclick = async () => { await v.schnittLoeschen(b.dataset.loeschen); panelZeichnen(); });
  }
  const nav = () => {
    const n = { art: p.querySelector("input[name=p-nav]:checked").value, drehpunkt: p.querySelector("#p-drehpunkt").checked,
      zoomZumCursor: p.querySelector("#p-cursor").checked, tempo: parseFloat(p.querySelector("#p-tempo").value) };
    ansichtEinstellungen({ nav: n });
    v.navigation(n);
    hinweisModus();
  };
  p.querySelectorAll("input[name=p-nav], #p-drehpunkt, #p-cursor, #p-tempo").forEach((i) => i.onchange = nav);
  const beschr = p.querySelector("#p-beschriftung");
  if (beschr) beschr.onchange = () => { v.beschriftung = beschr.checked; };
}

// ---------------------------------------------------------------- Daten aufbereiten

function eintraege() {
  const z = app.zustand, a = app.absender;
  const warten = new Set(z.wartetAuf({ firma: a.firma, rolle: a.rolle }));
  return [...z.objekte.values()].map((o) => {
    const gs = z.gesamtstatus(o.id);
    return { id: o.id, o, gs, wartet: warten.has(o.id) };
  }).sort((x, y) => String(x.o.daten.nummer).localeCompare(String(y.o.daten.nummer), "de", { numeric: true }));
}

function gefiltert(alle) {
  const suche = $("suche").value.trim().toLowerCase();
  const status = $("filter-status").value;
  const ich = $("filter-ich").checked;
  const geschoss = $("geschoss").value;
  return alle.filter((e) => {
    if (ich && !e.wartet) return false;
    if (status && e.gs.wirkung !== status) return false;
    if (geschoss && e.o.daten.ebene !== geschoss) return false;
    if (suche) {
      const text = [e.o.daten.nummer, e.o.daten.groesse, ...(e.o.daten.gewerke || []),
        ...e.o.verlauf.map((v) => v.daten.text || v.daten.kommentar || "")].join(" ").toLowerCase();
      if (!text.includes(suche)) return false;
    }
    return true;
  });
}

function statusName(gs) {
  if (gs.status === "in_pruefung") return gs.geaendert ? "Geändert – in Prüfung" : "In Prüfung";
  return app.projekt.statusDef(gs.status)?.name || gs.status;
}

function zeit(iso) {
  return new Date(iso).toLocaleString("de-DE", { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" });
}

function wirtText(d) {
  const w = d.wirt || {};
  return [w.kategorie === "Wände" ? "Wand" : w.kategorie === "Geschossdecken" ? "Decke" : w.kategorie,
    w.tragend ? "tragend" : w.tragend === false ? "nicht tragend" : ""].filter(Boolean).join(" ");
}

// ---------------------------------------------------------------- Zeichnen

function allesZeichnen() {
  const alle = eintraege();
  const sichtbar = gefiltert(alle);
  const ids = new Set(sichtbar.map((e) => e.id));
  if (app.auswahl && !app.zustand.objekte.has(app.auswahl)) app.auswahl = null;
  if (app.auswahl) ids.add(app.auswahl);   // Auswahl bleibt sichtbar, auch wenn der Filter sie ausblendet

  const zahl = (f) => alle.filter(f).length;
  $("kennzahlen").innerHTML = [
    ["", "In Prüfung", zahl((e) => e.gs.wirkung === OFFEN), "Alle Durchbrüche in Prüfung"],
    ["#ich", "Für mich", zahl((e) => e.wartet), "Hier müssen Sie als Nächstes etwas tun"],
    [BLOCKIERT, "Abgelehnt", zahl((e) => e.gs.wirkung === BLOCKIERT), "Abgelehnt – Nacharbeit oder Klärung nötig"],
    [FREIGABE, "Frei", zahl((e) => e.gs.wirkung === FREIGABE), "Von allen Pflichtrollen freigegeben"],
  ].map(([f, n, z, t]) => `<button data-filter="${f}" title="${t}"><b>${z}</b><span>${n}</span></button>`).join("");
  $("kennzahlen").querySelectorAll("button").forEach((b) => b.onclick = () => {
    const f = b.dataset.filter;
    $("filter-ich").checked = f === "#ich";
    $("filter-status").value = f === "#ich" ? "" : (f || OFFEN);
    allesZeichnen();
  });

  $("liste").innerHTML = sichtbar.length ? sichtbar.map((e) => `
    <div class="eintrag ${e.id === app.auswahl ? "aktiv" : ""}" data-id="${esc(e.id)}">
      <span class="nr">${esc(e.o.daten.nummer)}</span>
      <span class="pill ${e.gs.wirkung}">${esc(statusName(e.gs))}</span>
      <span class="info">${esc([e.o.daten.ebene, wirtText(e.o.daten), e.o.daten.groesse].filter(Boolean).join(" · "))}
        · ${e.gs.pflicht_erfuellt}/${e.gs.pflicht_gesamt}</span>
    </div>`).join("")
    : `<div class="leer">${!app.zustand.objekte.size
      ? "Noch keine Durchbrüche eingereicht. In Revit: DBK → Prüfset, dann Einreichen."
      : $("filter-ich").checked ? "Nichts zu tun – alles erledigt." : "Keine Durchbrüche für diesen Filter."}</div>`;
  $("liste").querySelectorAll(".eintrag").forEach((el) => el.onclick = () => waehle(el.dataset.id, true));

  app.viewer.setzeObjekte(alle.map((e) => ({ id: e.id, daten: e.o.daten, wirkung: e.gs.wirkung, sichtbar: ids.has(e.id) })));
  app.viewer.waehle(app.auswahl);
  detailZeichnen();
}

function waehle(id, fokus) {
  if (id && app.bauteil) { app.bauteil = null; app.viewer.bauteilWaehlen(null); }
  app.auswahl = id;
  app.viewer.waehle(id, fokus);
  document.querySelectorAll(".eintrag").forEach((el) => el.classList.toggle("aktiv", el.dataset.id === id));
  const el = document.querySelector(`.eintrag[data-id="${CSS.escape(id || "")}"]`);
  if (el) el.scrollIntoView({ block: "nearest" });
  detailZeichnen();
}

function detailZeichnen() {
  const d = $("detail");
  const o = app.auswahl && app.zustand.objekte.get(app.auswahl);
  if (!o) {
    if (app.bauteil) return bauteilZeichnen(d, app.bauteil);
    d.innerHTML = `<div class="leer">Durchbruch in der Liste oder im Modell anklicken.<br><br>
      Ein Klick auf ein anderes Bauteil zeigt dessen Eigenschaften.</div>`;
    return;
  }
  const gs = app.zustand.gesamtstatus(o.id), od = o.daten, a = app.absender, p = app.projekt;
  const meineStufe = gs.rollen[a.rolle]?.stufe;
  const istBesitzer = o.besitzer === a.firma;
  const rollen = Object.entries(gs.rollen).filter(([, r]) => r.stufe || r.status);
  const weitere = p.status.filter((s) => !["freigegeben", "abgelehnt"].includes(s.id));

  d.innerHTML = `
    <div class="detail-kopf"><h2>${esc(od.nummer)}</h2><span class="pill ${gs.wirkung}">${esc(statusName(gs))}</span></div>
    <div class="meta">${esc([od.ebene, wirtText(od), od.groesse, od.uk_mm != null ? "UK " + (od.uk_mm / 1000).toFixed(2) + " m" : "",
      (od.gewerke || []).join(", ")].filter(Boolean).join(" · "))}<br>
      <span title="Firma, die den Durchbruch eingereicht hat">${esc(o.besitzer)}</span> · Runde ${esc(o.runden.map((r) => app.zustand.runden[r]?.name || r).join(", ") || "–")}</div>
    <div class="knoepfe">
      <button id="k-zoom" title="Im Modell heranzoomen">Zeigen</button>
      <button id="k-box" title="Schnittbox um diesen Durchbruch">Schnittbox</button>
    </div>
    <div class="abschnitt">Freigaben</div>
    <div class="rollen">${rollen.map(([id, r]) => `
      <div><span>${esc(p.rollenName(id))} <span class="stufe">${r.stufe === PFLICHT ? "Pflicht" : r.stufe === "info" ? "Info" : ""}</span></span>
      <span class="pill ${r.wirkung || "grau"}" title="${r.veraltet ? "Frühere Entscheidung gilt nicht mehr – Geometrie wurde geändert" : ""}">${
        esc(r.status ? (p.statusDef(r.status)?.name || r.status) : r.veraltet ? "neu prüfen" : "offen")}</span></div>`).join("")}</div>
    <div class="abschnitt">Verlauf</div>
    <div class="verlauf">${o.verlauf.map(verlaufZeile).join("")}</div>
    <div class="eingabe">
      <textarea id="k-text" placeholder="${meineStufe ? "Kommentar (optional bei Freigabe)" : "Nachricht schreiben"}"></textarea>
      <div class="reihe">
        ${meineStufe ? `<button id="k-frei" class="ja" title="Für Ihre Rolle freigeben">Freigeben</button>
        <button id="k-ab" class="nein" title="Ablehnen – bitte Grund angeben">Ablehnen</button>
        ${weitere.length ? `<select id="k-weitere" title="Weiterer Status"><option value="">Weitere …</option>${weitere.map((s) => `<option value="${esc(s.id)}">${esc(s.name)}</option>`).join("")}</select>` : ""}` : ""}
        <button id="k-senden" title="Nur Nachricht senden">Senden</button>
        ${istBesitzer && gs.wirkung === BLOCKIERT ? `<button id="k-erneut" title="Unverändert erneut zur Prüfung einreichen (z. B. nach Klärung im Chat)">Erneut einreichen</button>` : ""}
      </div>
      <div id="k-fehler" class="fehlermeldung"></div>
    </div>`;

  $("k-zoom").onclick = () => app.viewer.fokus(o.id);
  $("k-box").onclick = () => app.viewer.schnittboxUm(o.id);
  const text = () => $("k-text").value.trim();
  const fehler = (m) => { $("k-fehler").textContent = m; };
  const entscheide = async (wert) => {
    if (wert === "abgelehnt" && !text()) return fehler("Bitte einen Grund für die Ablehnung angeben.");
    const kontext = Object.fromEntries(Object.entries(app.zustand.modelle).map(([m, v]) => [m, v.aktuell.hash]));
    await schreibe("status", o.id, { wert, geometrie_hash: o.geometrieHash, kommentar: text() || null, kontext });
  };
  if (meineStufe) {
    $("k-frei").onclick = () => entscheide("freigegeben");
    $("k-ab").onclick = () => entscheide("abgelehnt");
    if ($("k-weitere")) $("k-weitere").onchange = (e) => e.target.value && entscheide(e.target.value);
  }
  $("k-senden").onclick = () => text() ? schreibe("nachricht", o.id, { text: text() }) : fehler("Bitte zuerst eine Nachricht schreiben.");
  if ($("k-erneut")) $("k-erneut").onclick = () => schreibe("eingereicht", o.id, { objekt: o.daten, runde: o.runden.at(-1) || null });
  $("k-text").oninput = () => fehler("");
  const v = d.querySelector(".verlauf");
  v.lastElementChild?.scrollIntoView({ block: "nearest" });
}

/** Eigenschaften eines Modellbauteils (aus Fragments). */
async function bauteilZeichnen(d, auswahl) {
  if (auswahl.fbx) {
    const f = app.viewer.fbxDaten(auswahl);
    d.innerHTML = `<div class="detail-kopf"><h2>${esc(f.titel)}</h2><span class="pill grau">Modell ${esc(auswahl.modelId)}</span></div>
      <div class="eigenschaften">${f.zeilen.map(([n, v]) => `<div class="eig"><span>${esc(n)}</span><span>${esc(v)}</span></div>`).join("")}</div>
      <p class="leer">Eigenschaften aus Revit (FBX-Export). Volle IFC-Eigenschaften gibt es, wenn das Modell als IFC veröffentlicht wird.</p>
      <div class="knoepfe" style="margin-top:10px"><button id="b-box">Schnittbox</button><button id="b-weg">Auswahl aufheben</button></div>`;
    $("b-weg").onclick = () => app.viewer.bauteilWaehlen(null);
    $("b-box").onclick = () => app.viewer.schnittboxUm(null);
    return;
  }
  d.innerHTML = `<div class="leer">Eigenschaften werden geladen …</div>`;
  let daten;
  try { daten = await app.viewer.bauteilDaten(auswahl); } catch (e) { d.innerHTML = `<div class="leer">Eigenschaften nicht lesbar: ${esc(e.message)}</div>`; return; }
  if (app.bauteil !== auswahl) return;   // inzwischen etwas anderes gewählt
  const w = (x) => (x && typeof x === "object" && "value" in x ? x.value : x);
  const klasse = w(daten._category) || "";
  const geschoss = (daten.ContainedInStructure || []).map((s) => w(s.Name)).filter(Boolean).join(", ");
  const kopf = [
    ["Modell", auswahl.modelId], ["Klasse", `${klassenName(klasse)} (${klasse})`], ["Geschoss", geschoss],
    ["Typ", w(daten.ObjectType)], ["Kennzeichen", w(daten.Tag)], ["GlobalId", w(daten._guid) || w(daten.GlobalId)],
  ].filter(([, v]) => v);
  const saetze = (daten.IsDefinedBy || []).map((s) => {
    const eintraege = (s.HasProperties || s.Quantities || []).map((p) => {
      const wert = w(p.NominalValue) ?? w(p.LengthValue) ?? w(p.AreaValue) ?? w(p.VolumeValue) ?? w(p.CountValue) ?? w(p.WeightValue);
      return [w(p.Name), typeof wert === "number" ? Math.round(wert * 1000) / 1000 : wert];
    }).filter(([n, v]) => n && v !== undefined && v !== null && v !== "");
    return { name: w(s.Name) || "Eigenschaften", eintraege };
  }).filter((s) => s.eintraege.length);
  const zeilen = (liste) => liste.map(([n, v]) => `<div class="eig"><span>${esc(n)}</span><span>${esc(v)}</span></div>`).join("");
  d.innerHTML = `
    <div class="detail-kopf"><h2>${esc(w(daten.Name) || "Bauteil")}</h2><span class="pill grau">Modell ${esc(auswahl.modelId)}</span></div>
    <div class="eigenschaften">${zeilen(kopf)}</div>
    ${saetze.map((s, i) => `<details class="satz" ${i === 0 ? "open" : ""}><summary>${esc(s.name)} <span>${s.eintraege.length}</span></summary>
      <div class="eigenschaften">${zeilen(s.eintraege)}</div></details>`).join("") || `<div class="leer">Keine Eigenschaftssätze im IFC.</div>`}
    <div class="knoepfe" style="margin-top:10px"><button id="b-weg" title="Auswahl aufheben">Auswahl aufheben</button></div>`;
  $("b-weg").onclick = () => app.viewer.bauteilWaehlen(null);
}

function verlaufZeile(e) {
  const eigen = e.firma === app.absender.firma && e.name === app.absender.name;
  const wer = `${esc(e.name)} · ${esc(app.projekt.rollenName(e.rolle))} · ${zeit(e.zeit)}`;
  if (e.art === "nachricht") {
    return `<div class="blase ${eigen ? "eigen" : ""}">${esc(e.daten.text)}</div><div class="wer ${eigen ? "eigen" : ""}">${wer}</div>`;
  }
  let pill = "grau", text = e.art;
  if (e.art === "status") {
    const w = app.projekt.wirkung(e.daten.wert);
    pill = w; text = `${app.projekt.statusDef(e.daten.wert)?.name || e.daten.wert}`;
  } else if (e.art === "eingereicht") { pill = OFFEN; text = "eingereicht"; }
  else if (e.art === "geaendert") { text = "geändert"; }
  const zeile = `<div class="ereignis"><span class="pill ${pill}">${esc(text)}</span> <span class="wer">${wer}</span></div>`;
  return e.daten.kommentar
    ? zeile + `<div class="blase ${eigen ? "eigen" : ""}">${esc(e.daten.kommentar)}</div>`
    : zeile;
}

async function schreibe(art, objekt, daten) {
  try {
    await app.ablage.schreibe(app.absender, art, objekt, daten);
    app.zustand = berechne(app.ablage.alle(), app.projekt);
    allesZeichnen();
  } catch (e) {
    console.error(e);
    const f = $("k-fehler");
    if (f) f.textContent = "Speichern fehlgeschlagen: " + e.message;
  }
}

// ---------------------------------------------------------------- Nachladen (nahezu live)

let laedt = false;
async function nachladen() {
  if (laedt || document.hidden) return;
  laedt = true;
  try {
    const neu = await app.ablage.ladeNeue();
    if (neu.length) {
      const text = document.activeElement?.id === "k-text" ? $("k-text").value : null;
      app.zustand = berechne(app.ablage.alle(), app.projekt);
      if (neu.some((e) => e.art === "modell_veroeffentlicht")) await modelleLaden();
      allesZeichnen();
      if (text !== null && $("k-text")) { $("k-text").value = text; $("k-text").focus(); }
    }
  } catch (e) {
    console.warn("Nachladen fehlgeschlagen", e);
  } finally {
    laedt = false;
  }
}

// ---------------------------------------------------------------- Bedienelemente

function bedienelemente() {
  const modus = async (m) => {
    $("modus-3d").classList.toggle("an", m === "3d");
    $("modus-plan").classList.toggle("an", m === "plan");
    await app.viewer.setzeModus(m);
    if (m === "plan" && $("geschoss").value !== (app.viewer.geschoss || "")) {
      $("geschoss").value = app.viewer.geschoss || "";
      allesZeichnen();
    }
    hinweisModus();
  };
  $("modus-3d").onclick = () => modus("3d");
  $("modus-plan").onclick = () => modus("plan");
  $("geschoss").onchange = async () => { await app.viewer.setzeGeschoss($("geschoss").value); allesZeichnen(); hinweisModus(); };
  $("schnitt-ebene").onclick = () => { app.viewer.schnittEbeneSetzen(); zeigeHinweis("Auf eine Fläche klicken, um dort zu schneiden (Esc bricht ab)"); $("viewer").focus(); };
  $("schnitt-box").onclick = () => app.viewer.schnittboxUm(app.auswahl);
  $("schnitt-weg").onclick = () => app.viewer.schnitteLoeschen();
  $("viewer").addEventListener("pointerup", () => setTimeout(hinweisModus, 50));
  for (const id of ["suche", "filter-status", "filter-ich"]) $(id).addEventListener("input", allesZeichnen);
  $("benutzer").onclick = async () => { app.absender = await startDialog(); zeigeBenutzer(); allesZeichnen(); };
  $("modell-neu").onclick = modellDialog;
  $("einstellungen").onclick = panelUmschalten;
  $("alles").onclick = () => app.viewer.allesZeigen();
  hinweisModus();
}

function hinweisModus() {
  if (app.viewer._werkzeug) return;
  const g = app.viewer.geschoss;
  const nav = NAVIGATION[app.viewer.nav.art] || NAVIGATION.standard;
  zeigeHinweis(app.viewer.modus === "plan"
    ? `Grundriss ${g || ""} · Schnitt 1,00 m über OKFF · ziehen = verschieben, Rad = zoomen`
    : `3D${g ? " bis " + g : ""} · ${nav.hilfe}`);
}

start().catch((e) => {
  console.error(e);
  zeigeHinweis("Start fehlgeschlagen: " + e.message);
});
