// 3D-/Grundriss-Viewer auf Basis von That Open Components.
//
// Koordinaten: Prüfobjekte liegen in Projektkoordinaten (mm, Z oben). Der Viewer
// arbeitet in Metern mit Y oben (wie Fragments aus IFC):
//   three.x =  X/1000,  three.y = Z/1000,  three.z = -Y/1000
import { THREE, OBC, WEB_IFC_WASM } from "./bibliotheken.js";
import CameraControls from "camera-controls";

const AKTION = CameraControls.ACTION;

// Navigation – Voreinstellungen wie in gängigen BIM-Viewern
export const NAVIGATION = {
  standard: { name: "Standard (wie BIM-Viewer)", hilfe: "Links ziehen = drehen um den Punkt unter der Maus · Mausrad gedrückt oder rechts = verschieben · Rad = zoomen zum Mauszeiger · Doppelklick = heranzoomen" },
  revit: { name: "Revit-Stil", hilfe: "Mausrad gedrückt = verschieben · Umschalt + Mausrad gedrückt = drehen · Rad = zoomen · Links = auswählen" },
};
export const NAV_STANDARD = { art: "standard", zoomZumCursor: true, drehpunkt: true, tempo: 1.0 };

// IFC-Klassen → Anzeigename und Gruppe für die Ebenen-Schalter
const KLASSEN = {
  IFCWALL: ["Wände", "Rohbau"], IFCWALLSTANDARDCASE: ["Wände", "Rohbau"], IFCSLAB: ["Decken", "Rohbau"],
  IFCBEAM: ["Träger", "Rohbau"], IFCCOLUMN: ["Stützen", "Rohbau"], IFCFOOTING: ["Fundamente", "Rohbau"],
  IFCROOF: ["Dächer", "Rohbau"], IFCSTAIR: ["Treppen", "Ausbau"], IFCSTAIRFLIGHT: ["Treppen", "Ausbau"],
  IFCRAILING: ["Geländer", "Ausbau"], IFCDOOR: ["Türen", "Ausbau"], IFCWINDOW: ["Fenster", "Ausbau"],
  IFCCURTAINWALL: ["Fassade", "Ausbau"], IFCPLATE: ["Fassade", "Ausbau"], IFCMEMBER: ["Fassade", "Ausbau"],
  IFCCOVERING: ["Bekleidungen", "Ausbau"], IFCFURNISHINGELEMENT: ["Möbel", "Ausbau"], IFCFURNITURE: ["Möbel", "Ausbau"],
  IFCSPACE: ["Räume", "Sonstiges"], IFCBUILDINGELEMENTPROXY: ["Sonstige Bauteile", "Sonstiges"],
  IFCDUCTSEGMENT: ["Luftkanäle", "TGA"], IFCDUCTFITTING: ["Luftkanäle", "TGA"], IFCAIRTERMINAL: ["Luftauslässe", "TGA"],
  IFCDAMPER: ["Klappen", "TGA"], IFCPIPESEGMENT: ["Rohre", "TGA"], IFCPIPEFITTING: ["Rohre", "TGA"],
  IFCVALVE: ["Armaturen", "TGA"], IFCSANITARYTERMINAL: ["Sanitär", "TGA"], IFCFLOWTERMINAL: ["Endgeräte", "TGA"],
  IFCFLOWSEGMENT: ["Leitungen", "TGA"], IFCFLOWFITTING: ["Leitungen", "TGA"], IFCFLOWCONTROLLER: ["Armaturen", "TGA"],
  IFCCABLECARRIERSEGMENT: ["Kabeltrassen", "TGA"], IFCCABLECARRIERFITTING: ["Kabeltrassen", "TGA"],
  IFCCABLESEGMENT: ["Kabel", "TGA"], IFCLIGHTFIXTURE: ["Leuchten", "TGA"], IFCELECTRICAPPLIANCE: ["Elektrogeräte", "TGA"],
  IFCDISTRIBUTIONELEMENT: ["TGA sonstig", "TGA"], IFCENERGYCONVERSIONDEVICE: ["Geräte", "TGA"],
  IFCUNITARYEQUIPMENT: ["Geräte", "TGA"], IFCFLOWMOVINGDEVICE: ["Geräte", "TGA"], IFCFLOWTREATMENTDEVICE: ["Geräte", "TGA"],
};
const STANDARD_AUS = new Set(["Räume"]);

export function klassenName(klasse) {
  return (KLASSEN[klasse] || [klasse.replace(/^IFC/, "").toLowerCase(), "Sonstiges"])[0];
}

export const FARBE = { freigabe: 0x639922, blockiert: 0xe24b4a, offen: 0xef9f27 };
const FARBE_AUSWAHL = 0x185fa5;
const SCHNITTHOEHE = 1.0; // Grundriss: Schnitt 1,00 m über OKFF

export class Viewer {
  constructor(container) {
    this.container = container;
    this.versatz = [0, 0, 0];
    this.ebenen = [];          // [{name, y}] aufsteigend
    this.geschoss = null;      // Name oder null = alle
    this.modus = "3d";
    this.meshes = new Map();   // objektId -> Mesh
    this.auswahl = null;
    this.beschriftung = true;
    this.onAuswahl = () => {};
    this.onSchnitteGeaendert = () => {};
    this._werkzeug = null;     // "ebene" während „Schnitt setzen“
    this._geschossEbene = new THREE.Plane(new THREE.Vector3(0, -1, 0), 1e6);
    this._schnittbox = [];
    this.fbx = new Map();      // Modell-ID -> {gruppe, info, meshes}
    this.nav = { ...NAV_STANDARD };
    this.box = { an: false, min: new THREE.Vector3(), max: new THREE.Vector3(), ebenen: [] };
    this.onBox = () => {};
  }

  // ------------------------------------------------------------- Aufbau

  async init() {
    const c = (this.components = new OBC.Components());
    const world = (this.world = c.get(OBC.Worlds).create());
    world.scene = new OBC.SimpleScene(c);
    world.scene.setup();
    world.scene.three.background = null;
    world.renderer = new OBC.SimpleRenderer(c, this.container);
    world.camera = new OBC.OrthoPerspectiveCamera(c);
    c.init();

    const fr = (this.fragments = c.get(OBC.FragmentsManager));
    fr.init(await OBC.FragmentsManager.getWorker());
    world.camera.controls.addEventListener("update", () => fr.core.update());
    world.onCameraChanged.add((camera) => {
      for (const [, m] of fr.list) m.useCamera(camera.three);
      fr.core.update(true);
    });
    fr.list.onItemSet.add(({ value: model }) => {
      model.useCamera(world.camera.three);
      world.scene.three.add(model.object);
      model.getClippingPlanesEvent = () => Array.from(world.renderer.three.clippingPlanes) || [];
      fr.core.update(true);
    });
    fr.core.models.materials.list.onItemSet.add(({ value: material }) => {
      if (!("isLodMaterial" in material && material.isLodMaterial)) {
        material.polygonOffset = true;
        material.polygonOffsetUnits = 1;
        material.polygonOffsetFactor = Math.random();
        // Beidseitig zeichnen: geschnittene Wände bleiben im Grundriss sichtbar
        material.side = THREE.DoubleSide;
      }
    });

    this.caster = c.get(OBC.Raycasters).get(world);
    this.clipper = c.get(OBC.Clipper);
    this.clipper.enabled = true;
    this.clipper.onAfterCreate.add(() => this.onSchnitteGeaendert());
    this.clipper.onAfterDelete.add(() => this.onSchnitteGeaendert());
    world.renderer.setPlane(true, this._geschossEbene);

    this.gruppe = new THREE.Group();
    this.gruppe.name = "Prüfobjekte";
    world.scene.three.add(this.gruppe);

    this.labels = document.createElement("div");
    this.labels.className = "labels";
    this.container.appendChild(this.labels);
    world.renderer.onAfterUpdate.add(() => this._labelsAktualisieren());

    // Schnittbox: sechs eigene Ebenen, per Regler verschiebbar
    this.box.ebenen = [[1, 0, 0], [-1, 0, 0], [0, 1, 0], [0, -1, 0], [0, 0, 1], [0, 0, -1]]
      .map(([x, y, z]) => new THREE.Plane(new THREE.Vector3(x, y, z), 1e6));
    this.boxHilfe = new THREE.Box3Helper(new THREE.Box3(), 0x185fa5);
    this.boxHilfe.visible = false;
    world.scene.three.add(this.boxHilfe);
    this.drehpunktMarke = new THREE.Mesh(new THREE.SphereGeometry(1, 16, 12),
      new THREE.MeshBasicMaterial({ color: 0xbe0a26, depthTest: false, transparent: true, opacity: 0.85 }));
    this.drehpunktMarke.renderOrder = 10;
    this.drehpunktMarke.visible = false;
    world.scene.three.add(this.drehpunktMarke);

    this._zeigerEreignisse();
    await world.camera.controls.setLookAt(60, 40, 70, 25, 0, 20);
    world.camera.three.far = 5000;
    this.navigation(this.nav);
  }

  // ------------------------------------------------------------- Navigation

  /** Maus- und Zoomverhalten setzen (siehe NAVIGATION). */
  navigation(nav) {
    this.nav = { ...NAV_STANDARD, ...nav };
    this._navAnwenden();
  }

  _navAnwenden(umschalt = false) {
    const c = this.world.camera.controls;
    const plan = this.modus === "plan";
    const n = this.nav;
    if (n.art === "revit") {
      c.mouseButtons.left = AKTION.NONE;
      c.mouseButtons.middle = umschalt && !plan ? AKTION.ROTATE : AKTION.TRUCK;
      c.mouseButtons.right = AKTION.NONE;
    } else {
      c.mouseButtons.left = plan ? AKTION.TRUCK : AKTION.ROTATE;
      c.mouseButtons.middle = AKTION.TRUCK;
      c.mouseButtons.right = AKTION.TRUCK;
    }
    c.mouseButtons.wheel = plan ? AKTION.ZOOM : AKTION.DOLLY;
    c.dollyToCursor = !!n.zoomZumCursor;
    c.dollySpeed = n.tempo;
    c.truckSpeed = 1.0;
    c.azimuthRotateSpeed = c.polarRotateSpeed = 0.8;
    c.smoothTime = 0.15;
    c.draggingSmoothTime = 0.06;
    c.infinityDolly = true;
    c.minDistance = 0.5;
  }

  // ------------------------------------------------------------- Modelle

  async ladeModell(id, buffer) {
    if (this.fragments.list.has(id)) await this.fragments.core.disposeModel(id);
    await this.fragments.core.load(buffer, { modelId: id });
    return this._nachLaden(id);
  }

  /** IFC → Fragments im Browser. Gibt den Fragments-Puffer zum Ablegen zurück. */
  async ladeIfc(id, bytes, fortschritt) {
    if (!this._ifc) {
      this._ifc = this.components.get(OBC.IfcLoader);
      await this._ifc.setup({ autoSetWasm: false, wasm: { path: WEB_IFC_WASM, absolute: true },
        webIfc: { COORDINATE_TO_ORIGIN: false } });
    }
    if (this.fragments.list.has(id)) await this.fragments.core.disposeModel(id);
    const model = await this._ifc.load(new Uint8Array(bytes), false, id, {
      processData: { progressCallback: (p) => fortschritt && fortschritt(p) },
    });
    await this._nachLaden(id);
    return model.getBuffer(false);
  }

  async _nachLaden(id) {
    const model = this.fragments.list.get(id);
    const kats = (await model.getItemsWithGeometryCategories()).filter(Boolean);
    const gruppen = new Map();
    for (const k of kats) {
      const name = klassenName(k);
      if (!gruppen.has(name)) gruppen.set(name, { name, gruppe: (KLASSEN[k] || [0, "Sonstiges"])[1], klassen: [], an: !STANDARD_AUS.has(name) });
      gruppen.get(name).klassen.push(k);
    }
    this.kategorien = this.kategorien || new Map();
    this.kategorien.set(id, [...gruppen.values()].sort((a, b) => a.gruppe.localeCompare(b.gruppe) || a.name.localeCompare(b.name)));
    for (const g of this.kategorien.get(id)) if (!g.an) await this.setzeKategorieSichtbar(id, g.name, false);
    // Geschosse aus dem IFC – falls Revit keine Ebenen mitgeschickt hat
    try {
      const st = Object.values(await model.getItemsOfCategories([/^IFCBUILDINGSTOREY$/])).flat();
      if (st.length) {
        this.ifcEbenen = this.ifcEbenen || new Map();
        for (const d of await model.getItemsData(st, { attributesDefault: true })) {
          const el = d.Elevation?.value, name = d.Name?.value;
          if (typeof el === "number" && name) this.ifcEbenen.set(name, Math.round(Math.abs(el) > 200 ? el : el * 1000));
        }
      }
    } catch (e) { console.warn("Geschosse nicht lesbar", e); }
    return this.kategorien.get(id);
  }

  async setzeKategorieSichtbar(id, name, sichtbar) {
    const g = this.kategorien?.get(id)?.find((x) => x.name === name);
    if (!g) return;
    g.an = sichtbar;
    const f = this.fbx.get(id);
    if (f) {
      for (const m of f.nachKategorie.get(name) || []) m.visible = sichtbar;
      return;
    }
    const model = this.fragments.list.get(id);
    if (!model) return;
    const items = await model.getItemsOfCategories(g.klassen.map((k) => new RegExp(`^${k}$`)));
    const ids = Object.values(items).flat();
    if (ids.length) await this.components.get(OBC.Hider).set(sichtbar, { [id]: new Set(ids) });
    this.fragments.core.update(true);
  }

  setzeModellSichtbar(id, sichtbar) {
    const f = this.fbx.get(id);
    if (f) { f.gruppe.visible = sichtbar; return; }
    const m = this.fragments.list.get(id);
    if (m) { m.object.visible = sichtbar; this.fragments.core.update(true); }
  }

  modellSichtbar(id) {
    const f = this.fbx.get(id);
    if (f) return f.gruppe.visible;
    const m = this.fragments.list.get(id);
    return m ? m.object.visible : false;
  }

  // ------------------------------------------------------------- FBX (Revit-eigener Export)

  /**
   * FBX aus Revit laden. ``info`` (vom Revit-Werkzeug) liefert Kategorie, Familie, Typ, Ebene, System
   * je Bauteil-ID und die Bounding Box in mm – daraus werden Maßstab, Achsen und Lage bestimmt.
   */
  async ladeFbx(id, buffer, info) {
    const { FBXLoader } = await import("three/examples/jsm/loaders/FBXLoader.js");
    this.entferneFbx(id);
    const gruppe = new FBXLoader().parse(buffer, "");
    gruppe.name = "FBX " + id;
    this._fbxAusrichten(gruppe, info);
    const nachKategorie = new Map(), meshes = [];
    gruppe.traverse((o) => {
      if (!o.isMesh) return;
      const mats = Array.isArray(o.material) ? o.material : [o.material];
      for (const m of mats) { m.side = THREE.DoubleSide; }
      let eid = null;
      for (let p = o; p && !eid; p = p.parent) {
        const t = p.name && p.name.match(/\[(\d+)\]|(?:^|\D)(\d{4,})(?:\D|$)/);
        if (t) eid = t[1] || t[2];
      }
      const d = eid && info?.bauteile?.[eid];
      o.userData.dbk = { modell: id, eid, info: d || null };
      const kat = d?.k || "Ohne Zuordnung";
      if (!nachKategorie.has(kat)) nachKategorie.set(kat, []);
      nachKategorie.get(kat).push(o);
      meshes.push(o);
    });
    this.world.scene.three.add(gruppe);
    this.fbx.set(id, { gruppe, info, nachKategorie, meshes });
    this.kategorien = this.kategorien || new Map();
    this.kategorien.set(id, [...nachKategorie.keys()].sort().map((k) => ({
      name: k, gruppe: "Revit", klassen: [], an: true, anzahl: nachKategorie.get(k).length })));
    return this.kategorien.get(id);
  }

  entferneFbx(id) {
    const f = this.fbx.get(id);
    if (!f) return;
    this.world.scene.three.remove(f.gruppe);
    f.gruppe.traverse((o) => { if (o.isMesh) { o.geometry.dispose(); } });
    this.fbx.delete(id);
  }

  _fbxAusrichten(gruppe, info) {
    gruppe.updateMatrixWorld(true);
    const ist = new THREE.Box3().setFromObject(gruppe);
    if (!info?.bbox_mm || ist.isEmpty()) return;
    const [x0, y0, z0, x1, y1, z1] = info.bbox_mm;
    const soll = new THREE.Box3(new THREE.Vector3(x0 / 1000, z0 / 1000, -y1 / 1000),
      new THREE.Vector3(x1 / 1000, z1 / 1000, -y0 / 1000));
    const sollG = soll.getSize(new THREE.Vector3());
    let bester = null;
    for (const drehung of [0, -Math.PI / 2]) {          // Y oben bzw. Z oben
      gruppe.rotation.set(drehung, 0, 0);
      gruppe.scale.setScalar(1);
      gruppe.position.set(0, 0, 0);
      gruppe.updateMatrixWorld(true);
      const g = new THREE.Box3().setFromObject(gruppe).getSize(new THREE.Vector3());
      const f = [sollG.x / g.x, sollG.y / g.y, sollG.z / g.z].filter((v) => isFinite(v) && v > 0);
      if (!f.length) continue;
      const mittel = f.reduce((a, b) => a + b, 0) / f.length;
      const fehler = f.reduce((a, b) => a + Math.abs(Math.log(b / mittel)), 0);
      if (!bester || fehler < bester.fehler) bester = { drehung, faktor: mittel, fehler };
    }
    if (!bester) return;
    gruppe.rotation.set(bester.drehung, 0, 0);
    gruppe.scale.setScalar(bester.faktor);
    gruppe.position.set(0, 0, 0);
    gruppe.updateMatrixWorld(true);
    const neu = new THREE.Box3().setFromObject(gruppe);
    gruppe.position.copy(soll.min.clone().sub(neu.min));
    gruppe.updateMatrixWorld(true);
  }

  /** Kamera auf alles Geladene ausrichten (Blick schräg von Südost). */
  async allesZeigen() {
    const box = new THREE.Box3();
    for (const [, m] of this.fragments.list) if (m.box && !m.box.isEmpty()) box.union(m.box);
    for (const [, f] of this.fbx) if (f.gruppe.visible) box.expandByObject(f.gruppe);
    for (const m of this.meshes.values()) box.expandByObject(m);
    if (box.isEmpty()) return;
    const mitte = box.getCenter(new THREE.Vector3()), r = box.getSize(new THREE.Vector3()).length() / 2;
    await this.world.camera.controls.setLookAt(mitte.x + r, mitte.y + r * 0.8, mitte.z + r, mitte.x, mitte.y, mitte.z, false);
  }

  setzeEbenen(ebenen) {
    this.ebenen = ebenen
      .map((e) => ({ name: e.name, y: (e.hoehe_mm + this.versatz[2]) / 1000 }))
      .sort((a, b) => a.y - b.y);
  }

  // ------------------------------------------------------------- Prüfobjekte

  zuThree([x, y, z]) {
    const [vx, vy, vz] = this.versatz;
    return new THREE.Vector3((x + vx) / 1000, (z + vz) / 1000, -(y + vy) / 1000);
  }

  /** objekte: [{id, daten, wirkung, sichtbar}] */
  setzeObjekte(objekte) {
    for (const m of this.meshes.values()) { this.gruppe.remove(m); m.geometry.dispose(); }
    this.meshes.clear();
    for (const o of objekte) {
      const g = o.daten.geometrie;
      if (!g || !g.min || !g.max) continue;
      const a = this.zuThree(g.min), b = this.zuThree(g.max);
      const min = a.clone().min(b), max = a.clone().max(b);
      const groesse = max.clone().sub(min), mitte = min.clone().add(max).multiplyScalar(0.5);
      let geo;
      if (g.form === "rund") {
        const durchX = groesse.x < groesse.z;          // Rohr läuft durch die dünne Richtung
        const laenge = durchX ? groesse.x : groesse.z;
        geo = new THREE.CylinderGeometry(groesse.y / 2, groesse.y / 2, laenge, 24);
        geo.rotateZ(durchX ? Math.PI / 2 : 0);
        if (!durchX) geo.rotateX(Math.PI / 2);
      } else {
        geo = new THREE.BoxGeometry(groesse.x, groesse.y, groesse.z);
      }
      const farbe = FARBE[o.wirkung] ?? FARBE.offen;
      const mat = new THREE.MeshLambertMaterial({ color: farbe, emissive: farbe, emissiveIntensity: 0.25 });
      const mesh = new THREE.Mesh(geo, mat);
      mesh.position.copy(mitte);
      mesh.userData = { id: o.id, nummer: o.daten.nummer, groesse: o.daten.groesse || "", ebene: o.daten.ebene };
      const kante = new THREE.LineSegments(new THREE.EdgesGeometry(geo),
        new THREE.LineBasicMaterial({ color: 0x2c2c2a, transparent: true, opacity: 0.6 }));
      mesh.add(kante);
      // Grundriss-Umriss: liegt knapp unter der Schnitthöhe, damit er nie weggeschnitten wird
      const fuss = new THREE.Mesh(new THREE.PlaneGeometry(Math.max(groesse.x, 0.08), Math.max(groesse.z, 0.08)),
        new THREE.MeshBasicMaterial({ color: farbe, transparent: true, opacity: 0.85, depthTest: false }));
      fuss.rotation.x = -Math.PI / 2;
      fuss.renderOrder = 5;
      fuss.visible = false;
      fuss.name = "grundriss";
      mesh.add(fuss);
      mesh.visible = o.sichtbar !== false;
      this.gruppe.add(mesh);
      this.meshes.set(o.id, mesh);
    }
    this._auswahlZeigen();
    this._grundrissMarken();
  }

  /** Im Grundriss: Durchbrüche des Geschosses als Umriss auf Schnitthöhe zeigen. */
  _grundrissMarken() {
    const y = this._geschossEbene.constant - 0.02;
    for (const m of this.meshes.values()) {
      const fuss = m.getObjectByName("grundriss");
      const an = this.modus === "plan" && m.userData.ebene === this.geschoss;
      fuss.visible = an;
      if (an) fuss.position.y = (y - m.position.y) / m.scale.y;
    }
  }

  _anker(m) {
    const fuss = m.getObjectByName("grundriss");
    return fuss.visible ? fuss.getWorldPosition(new THREE.Vector3()) : m.position.clone();
  }

  waehle(id, fokus = false) {
    this.auswahl = id && this.meshes.has(id) ? id : null;
    this._auswahlZeigen();
    if (fokus && this.auswahl) this.fokus(this.auswahl);
  }

  _auswahlZeigen() {
    for (const [id, m] of this.meshes) {
      const an = id === this.auswahl;
      m.children[0].material.color.setHex(an ? FARBE_AUSWAHL : 0x2c2c2a);
      m.children[0].material.opacity = an ? 1 : 0.6;
      m.scale.setScalar(an ? 1.25 : 1);
      m.getObjectByName("grundriss").material.opacity = an ? 1 : 0.85;
    }
    this._grundrissMarken?.();
  }

  async fokus(id) {
    const m = this.meshes.get(id);
    if (!m) return;
    const ctl = this.world.camera.controls;
    if (this.modus === "plan") {
      await ctl.moveTo(m.position.x, ctl.getTarget(new THREE.Vector3()).y, m.position.z, true);
    } else {
      // Blickrichtung beibehalten, nur Ziel und Abstand ändern
      const p = ctl.getPosition(new THREE.Vector3()), t = ctl.getTarget(new THREE.Vector3());
      const richtung = p.sub(t).normalize();
      const neu = m.position.clone().addScaledVector(richtung, 12);
      await ctl.setLookAt(neu.x, neu.y, neu.z, m.position.x, m.position.y, m.position.z, true);
    }
  }

  // ------------------------------------------------------------- Geschoss und Modus

  async setzeGeschoss(name) {
    this.geschoss = name || null;
    this._geschossSchnitt();
    const e = this.ebenen.find((x) => x.name === this.geschoss);
    if (e) {
      const ctl = this.world.camera.controls;
      const t = ctl.getTarget(new THREE.Vector3());
      const p = ctl.getPosition(new THREE.Vector3());
      const dy = e.y + SCHNITTHOEHE - t.y;
      await ctl.setLookAt(p.x, p.y + dy, p.z, t.x, t.y + dy, t.z, true);
    }
  }

  _geschossSchnitt() {
    const i = this.ebenen.findIndex((x) => x.name === this.geschoss);
    let h = 1e6;
    if (i >= 0) {
      h = this.modus === "plan"
        ? this.ebenen[i].y + SCHNITTHOEHE
        : (this.ebenen[i + 1] ? this.ebenen[i + 1].y - 0.05 : 1e6);
    } else if (this.modus === "plan" && this.ebenen.length) {
      h = this.ebenen[0].y + SCHNITTHOEHE;
    }
    this._geschossEbene.constant = h;
    this.world.renderer.updateClippingPlanes?.();
    this.fragments.core.update(true);
    this._grundrissMarken();
  }

  async setzeModus(modus) {
    if (modus === this.modus) return;
    const cam = this.world.camera, ctl = cam.controls;
    const t = ctl.getTarget(new THREE.Vector3());
    if (modus === "plan") {
      this._blick3d = { p: ctl.getPosition(new THREE.Vector3()), t: t.clone() };
      this.modus = "plan";
      if (!this.geschoss && this.ebenen.length) this.geschoss = this.ebenen[0].name;
      this._geschossSchnitt();
      cam.set("Plan");
      this._navAnwenden();
      await cam.projection.set("Orthographic");
      const e = this.ebenen.find((x) => x.name === this.geschoss);
      const y = e ? e.y : t.y;
      // Ausschnitt etwa so groß wie vorher im 3D sichtbar (fitToBox würde die Kamera drehen)
      const abstand = this._blick3d.p.distanceTo(this._blick3d.t);
      const halb = Math.max(12, Math.min(80, abstand * 0.45));
      ctl.stop?.();
      await ctl.setLookAt(t.x, y + 80, t.z + 0.001, t.x, y, t.z, false);
      const h = cam.three.top - cam.three.bottom;
      if (h > 0) await ctl.zoomTo(h / (2 * halb), true);
    } else {
      this.modus = "3d";
      this._geschossSchnitt();
      ctl.stop?.();
      await cam.projection.set("Perspective");
      cam.set("Orbit");
      this._navAnwenden();
      await ctl.zoomTo(1, false);
      const b = this._blick3d;
      if (b) {
        const d = t.clone().sub(b.t);   // im Grundriss verschoben → 3D-Blick mitnehmen
        await ctl.setLookAt(b.p.x + d.x, b.p.y, b.p.z + d.z, t.x, b.t.y, t.z, true);
      }
    }
    this.fragments.core.update(true);
  }

  // ------------------------------------------------------------- Schnitte

  /** Nächster Klick auf eine Fläche erzeugt eine verschiebbare Schnittebene. */
  schnittEbeneSetzen() { this._werkzeug = "ebene"; this.container.classList.add("werkzeug-aktiv"); }

  /** Grenzen aller geladenen Inhalte – Rahmen für die Schnittbox-Regler. */
  modellGrenzen() {
    const box = new THREE.Box3();
    for (const [, m] of this.fragments.list) if (m.box && !m.box.isEmpty()) box.union(m.box);
    for (const [, f] of this.fbx) box.expandByObject(f.gruppe);
    for (const m of this.meshes.values()) box.expandByObject(m);
    if (box.isEmpty()) box.set(new THREE.Vector3(-10, -10, -10), new THREE.Vector3(10, 10, 10));
    return box.expandByScalar(1);
  }

  /** Schnittbox um einen Durchbruch, das gewählte Bauteil oder die Bildmitte. */
  schnittboxUm(id, rand = 1.5) {
    let box;
    if (id && this.meshes.has(id)) box = new THREE.Box3().setFromObject(this.meshes.get(id)).expandByScalar(rand);
    else if (this._bauteilBox) box = this._bauteilBox.clone().expandByScalar(rand);
    else {
      const t = this.world.camera.controls.getTarget(new THREE.Vector3());
      box = new THREE.Box3(t.clone().subScalar(5), t.clone().addScalar(5));
    }
    this.schnittboxSetzen(box.min, box.max);
  }

  /** Schnittbox auf min/max (Viewer-Koordinaten) setzen und einschalten. */
  schnittboxSetzen(min, max) {
    this.box.min.copy(min);
    this.box.max.copy(max);
    this._boxAnwenden(true);
  }

  schnittboxAus() { this._boxAnwenden(false); }

  /** Eine Seite der Box verschieben: achse "x"|"y"|"z", seite "min"|"max". */
  schnittboxSeite(achse, seite, wert) {
    this.box[seite][achse] = wert;
    if (this.box.min[achse] > this.box.max[achse] - 0.05) {
      if (seite === "min") this.box.min[achse] = this.box.max[achse] - 0.05;
      else this.box.max[achse] = this.box.min[achse] + 0.05;
    }
    this._boxAnwenden(true);
  }

  _boxAnwenden(an) {
    const r = this.world.renderer;
    const { min, max, ebenen } = this.box;
    const werte = [-min.x, max.x, -min.y, max.y, -min.z, max.z];
    ebenen.forEach((p, i) => { p.constant = werte[i]; });
    if (an !== this.box.an) ebenen.forEach((p) => r.setPlane(an, p));
    this.box.an = an;
    this.boxHilfe.box.set(min, max);
    this.boxHilfe.visible = an && this.boxRahmen !== false;
    r.updateClippingPlanes?.();
    this.fragments.core.update(true);
    this.onBox(this.box);
    this.onSchnitteGeaendert();
  }

  /** Freie Schnittebenen (aus „Schnitt setzen“) als Liste [{id, an, beschreibung}]. */
  freieSchnitte() {
    return [...this.clipper.list].map(([id, p], i) => {
      const n = p.normal;
      const achse = Math.abs(n.y) > 0.9 ? "waagrecht" : "senkrecht";
      return { id, an: p.enabled, beschreibung: `Schnitt ${i + 1} · ${achse}` };
    });
  }

  schnittUmschalten(id, an) {
    const p = this.clipper.list.get(id);
    if (p) { p.enabled = an; this.fragments.core.update(true); this.onSchnitteGeaendert(); }
  }

  async schnittUmdrehen(id) {
    const p = this.clipper.list.get(id);
    if (!p) return;
    const normal = p.normal.clone().negate(), punkt = p.origin.clone();
    await this.clipper.delete(this.world, id);
    this.clipper.createFromNormalAndCoplanarPoint(this.world, normal, punkt);
    this.onSchnitteGeaendert();
  }

  async schnittLoeschen(id) {
    await this.clipper.delete(this.world, id);
    this.onSchnitteGeaendert();
  }

  schnittGriffeZeigen(an) {
    this.clipper.visible = an;
    this.fragments.core.update(true);
  }

  schnitteLoeschen() {
    this.clipper.deleteAll();
    this._schnittbox = [];
    this._boxAnwenden(false);
  }

  get anzahlSchnitte() { return this.clipper.list.size + (this.box.an ? 1 : 0); }

  // ------------------------------------------------------------- Maus

  /** Punkt unter der Maus (Modell, FBX oder Durchbruch) – für Drehpunkt und Doppelklick. */
  async _punktUnterMaus() {
    const objekte = [...this.meshes.values()].filter((m) => m.visible);
    for (const [, f] of this.fbx) if (f.gruppe.visible) objekte.push(f.gruppe);
    let bester = null;
    const t = objekte.length ? this.caster.castRayToObjects(objekte) : null;
    if (t && this._nichtWeggeschnitten(t.point)) bester = t.point.clone();
    try {
      const r = await this.caster.castRay();
      if (r && r.point && this._nichtWeggeschnitten(r.point)) {
        const cam = this.world.camera.three.position;
        if (!bester || r.point.distanceTo(cam) < bester.distanceTo(cam)) bester = r.point.clone();
      }
    } catch { /* kein Treffer */ }
    return bester;
  }

  _zeigerEreignisse() {
    const el = this.container;
    const ctl = this.world.camera.controls;
    let start = null, letzte = 0, laeuft = false;
    // Drehpunkt: Punkt unter der Maus laufend (gedrosselt) bestimmen
    el.addEventListener("pointermove", async (e) => {
      if (e.buttons || laeuft || !this.nav.drehpunkt) return;
      const jetzt = performance.now();
      if (jetzt - letzte < 150) return;
      letzte = jetzt;
      laeuft = true;
      try { this._mausPunkt = await this._punktUnterMaus(); } finally { laeuft = false; }
    });
    el.addEventListener("pointerdown", (e) => {
      start = { x: e.clientX, y: e.clientY };
      const dreht = (e.button === 0 && this.nav.art !== "revit") || (e.button === 1 && e.shiftKey && this.nav.art === "revit");
      if (dreht && this.modus !== "plan" && this.nav.drehpunkt && this._mausPunkt) {
        const p = this._mausPunkt;
        ctl.setOrbitPoint(p.x, p.y, p.z);
        const d = this.world.camera.three.position.distanceTo(p);
        this.drehpunktMarke.position.copy(p);
        this.drehpunktMarke.scale.setScalar(Math.max(0.03, d * 0.006));
        this.drehpunktMarke.visible = true;
      }
    });
    window.addEventListener("pointerup", () => { this.drehpunktMarke.visible = false; });
    window.addEventListener("keydown", (e) => { if (e.key === "Shift") this._navAnwenden(true); });
    window.addEventListener("keyup", (e) => { if (e.key === "Shift") this._navAnwenden(false); });
    el.addEventListener("dblclick", async () => {
      const p = await this._punktUnterMaus();
      if (!p) return;
      const pos = ctl.getPosition(new THREE.Vector3()), ziel = ctl.getTarget(new THREE.Vector3());
      const richtung = pos.sub(ziel).normalize();
      const abstand = Math.max(4, Math.min(15, this.world.camera.three.position.distanceTo(p) * 0.4));
      const neu = p.clone().addScaledVector(richtung, abstand);
      await ctl.setLookAt(neu.x, neu.y, neu.z, p.x, p.y, p.z, true);
    });
    el.addEventListener("pointerup", async (e) => {
      if (!start || Math.abs(e.clientX - start.x) + Math.abs(e.clientY - start.y) > 4) { start = null; return; }
      start = null;
      if (e.button !== 0) return;
      if (this._werkzeug === "ebene") {
        this._werkzeug = null;
        el.classList.remove("werkzeug-aktiv");
        await this.clipper.create(this.world);
        return;
      }
      const treffer = this.caster.castRayToObjects([...this.meshes.values()].filter((m) => m.visible));
      let obj = treffer?.object;
      while (obj && !obj.userData.id) obj = obj.parent;
      const marke = treffer?.object.name === "grundriss";
      const id = obj && (marke || this._nichtWeggeschnitten(treffer.point)) ? obj.userData.id : null;
      if (id) {
        await this.bauteilWaehlen(null);
        this.waehle(id);
        this.onAuswahl(id);
        return;
      }
      // Kein Durchbruch getroffen → FBX-Bauteil oder Modellbauteil (Fragments)
      const fbxGruppen = [...this.fbx.values()].filter((f) => f.gruppe.visible).map((f) => f.gruppe);
      const tf = fbxGruppen.length ? this.caster.castRayToObjects(fbxGruppen) : null;
      if (tf && tf.object?.userData?.dbk && this._nichtWeggeschnitten(tf.point)) {
        await this.bauteilWaehlen({ modelId: tf.object.userData.dbk.modell, fbx: tf.object });
        return;
      }
      const r = await this.caster.castRay();
      const ok = r && r.localId !== undefined && r.fragments && this._nichtWeggeschnitten(r.point);
      await this.bauteilWaehlen(ok ? { modelId: r.fragments.modelId, localId: r.localId } : null);
      if (!ok) { this.waehle(null); this.onAuswahl(null); }
    });
    el.addEventListener("keydown", (e) => {
      if (e.key === "Escape" && this._werkzeug) { this._werkzeug = null; el.classList.remove("werkzeug-aktiv"); }
    });
  }

  /** Modellbauteil hervorheben (oder Auswahl aufheben mit null) und melden. */
  async bauteilWaehlen(auswahl) {
    const alt = this.bauteil;
    if (alt?.fbx) {
      alt.fbx.material = alt.fbxMaterial;
    } else if (alt) {
      const m = this.fragments.list.get(alt.modelId);
      if (m) await m.resetHighlight([alt.localId]);
    }
    this.bauteil = auswahl;
    this._bauteilBox = null;
    if (auswahl?.fbx) {
      auswahl.fbxMaterial = auswahl.fbx.material;
      auswahl.fbx.material = new THREE.MeshLambertMaterial({ color: FARBE_AUSWAHL, side: THREE.DoubleSide });
      this._bauteilBox = new THREE.Box3().setFromObject(auswahl.fbx);
    } else if (auswahl) {
      const m = this.fragments.list.get(auswahl.modelId);
      await m.highlight([auswahl.localId], {
        color: new THREE.Color(FARBE_AUSWAHL), renderedFaces: 1, opacity: 1, transparent: false,
      });
      try {
        const boxer = this.components.get(OBC.BoundingBoxer);
        boxer.list.clear();
        await boxer.addFromModelIdMap({ [auswahl.modelId]: new Set([auswahl.localId]) });
        this._bauteilBox = boxer.get();
        boxer.list.clear();
      } catch { /* Box nicht ermittelbar */ }
    }
    await this.fragments.core.update(true);
    this.onBauteil?.(auswahl);
  }

  /** Eigenschaften eines FBX-Bauteils (aus den Revit-Infos). */
  fbxDaten(auswahl) {
    const d = auswahl.fbx.userData.dbk || {};
    const i = d.info || {};
    return {
      titel: i.t ? `${i.f || ""} : ${i.t}` : (auswahl.fbx.name || "Bauteil"),
      zeilen: [["Modell", auswahl.modelId], ["Kategorie", i.k], ["Familie", i.f], ["Typ", i.t], ["Ebene", i.e],
        ["System", i.s], ["Größe", i.g], ["Revit-ID", d.eid]].filter(([, v]) => v),
    };
  }

  /** Attribute und Eigenschaftssätze eines Modellbauteils. */
  async bauteilDaten({ modelId, localId }) {
    const m = this.fragments.list.get(modelId);
    const [d] = await m.getItemsData([localId], {
      attributesDefault: true,
      relations: { IsDefinedBy: { attributes: true, relations: true }, ContainedInStructure: { attributes: true, relations: false } },
    });
    return d || {};
  }

  _nichtWeggeschnitten(punkt) {
    return this.world.renderer.three.clippingPlanes.every((p) => p.distanceToPoint(punkt) >= -1e-3);
  }

  // ------------------------------------------------------------- Beschriftung

  _labelsAktualisieren() {
    if (!this.labels) return;
    const cam = this.world.camera.three;
    const breite = this.container.clientWidth, hoehe = this.container.clientHeight;
    const vorhanden = new Map([...this.labels.children].map((d) => [d.dataset.id, d]));
    const v = new THREE.Vector3();
    for (const [id, m] of this.meshes) {
      let d = vorhanden.get(id);
      vorhanden.delete(id);
      const anker = this._anker(m);
      const zeigen = this.beschriftung && m.visible && this._nichtWeggeschnitten(anker);
      if (zeigen) {
        v.copy(anker);
        if (this.modus !== "plan") v.y += 0.35;
        v.project(cam);
        if (v.z > 1 || v.x < -1.1 || v.x > 1.1 || v.y < -1.1 || v.y > 1.1) { if (d) d.style.display = "none"; continue; }
        if (!d) {
          d = document.createElement("div");
          d.className = "label";
          d.dataset.id = id;
          d.addEventListener("click", (ev) => { ev.stopPropagation(); this.waehle(id); this.onAuswahl(id); });
          this.labels.appendChild(d);
        }
        const txt = `${m.userData.nummer} · ${m.userData.groesse}`;
        if (d.textContent !== txt) d.textContent = txt;
        d.classList.toggle("aktiv", id === this.auswahl);
        d.style.display = "";
        d.style.transform = `translate(${((v.x + 1) / 2) * breite}px, ${((1 - v.y) / 2) * hoehe}px) translate(-50%, -100%)`;
      } else if (d) d.style.display = "none";
    }
    for (const d of vorhanden.values()) d.remove();
  }
}
