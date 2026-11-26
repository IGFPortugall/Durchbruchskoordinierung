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
    this._basisVergessen(id);
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
    this._basisVergessen(id);
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
    const p = this.plaene?.get(id);
    if (p) { p.visible = sichtbar; return; }
    const f = this.fbx.get(id);
    if (f) { f.gruppe.visible = sichtbar; return; }
    const m = this.fragments.list.get(id);
    if (m) { m.object.visible = sichtbar; this.fragments.core.update(true); }
  }

  modellSichtbar(id) {
    const p = this.plaene?.get(id);
    if (p) return p.visible;
    const f = this.fbx.get(id);
    if (f) return f.gruppe.visible;
    const m = this.fragments.list.get(id);
    return m ? m.object.visible : false;
  }

  _modellObjekt(id) {
    return this.fbx.get(id)?.gruppe || this.fragments.list.get(id)?.object || null;
  }

  // ------------------------------------------------------------- Pläne (2D aus Revit)

  /**
   * Grundriss/Schnitt als Bild mit Lage: ``plan.ecken_mm`` = vier Ecken (unten links, unten rechts, oben rechts,
   * oben links) in Revit-Koordinaten. Grundrisse liegen knapp über der Geschossebene, Schnitte stehen senkrecht.
   * Anfangs ausgeblendet.
   */
  async ladePlan(id, bytes, plan) {
    this.entfernePlan(id);
    const url = URL.createObjectURL(new Blob([bytes], { type: "image/png" }));
    const textur = await new THREE.TextureLoader().loadAsync(url);
    URL.revokeObjectURL(url);
    textur.colorSpace = THREE.SRGBColorSpace;
    textur.anisotropy = this.world.renderer.three.capabilities.getMaxAnisotropy();
    const hoch = plan.art === "grundriss" ? 15 : 0;          // 15 mm über der Ebene, damit nichts flimmert
    const e = plan.ecken_mm.map(([x, y, z]) => this.zuThree([x, y, z + hoch]));
    const geo = new THREE.BufferGeometry();
    geo.setAttribute("position", new THREE.Float32BufferAttribute([e[0], e[1], e[2], e[0], e[2], e[3]].flatMap((p) => p.toArray()), 3));
    geo.setAttribute("uv", new THREE.Float32BufferAttribute([0, 0, 1, 0, 1, 1, 0, 0, 1, 1, 0, 1], 2));
    geo.computeVertexNormals();
    const mat = new THREE.MeshBasicMaterial({ map: textur, side: THREE.DoubleSide, transparent: true, opacity: 0.92,
      depthWrite: false, polygonOffset: true, polygonOffsetFactor: -2 });
    const mesh = new THREE.Mesh(geo, mat);
    mesh.name = "Plan " + id;
    mesh.renderOrder = 5;
    mesh.visible = false;
    mesh.userData.plan = plan;
    this.world.scene.three.add(mesh);
    this.plaene = this.plaene || new Map();
    this.plaene.set(id, mesh);
    this._planTiefe();
  }

  entfernePlan(id) {
    const m = this.plaene?.get(id);
    if (!m) return;
    this.world.scene.three.remove(m);
    m.geometry.dispose();
    m.material.map?.dispose();
    m.material.dispose();
    this.plaene.delete(id);
  }

  /**
   * Modell verschieben/drehen, falls es nicht zu den anderen passt.
   * a = {x_mm, y_mm, z_mm, drehung_grad} in Revit-Achsen (x Ost, y Nord, z oben); gedreht wird
   * um die senkrechte Achse durch die Modellmitte. null = Ursprungslage.
   */
  ausrichten(id, a) {
    const o = this._modellObjekt(id);
    if (!o) return;
    this._basis = this._basis || new Map();
    if (!this._basis.has(id)) {
      o.updateMatrixWorld(true);
      const box = new THREE.Box3().setFromObject(o);
      this._basis.set(id, { matrix: o.matrix.clone(), mitte: box.isEmpty() ? new THREE.Vector3() : box.getCenter(new THREE.Vector3()) });
    }
    const { matrix, mitte } = this._basis.get(id);
    const x = (a?.x_mm || 0) / 1000, y = (a?.y_mm || 0) / 1000, z = (a?.z_mm || 0) / 1000;
    const winkel = ((a?.drehung_grad || 0) * Math.PI) / 180;
    const m = new THREE.Matrix4().makeTranslation(mitte.x + x, mitte.y + z, mitte.z - y)
      .multiply(new THREE.Matrix4().makeRotationY(winkel))
      .multiply(new THREE.Matrix4().makeTranslation(-mitte.x, -mitte.y, -mitte.z))
      .multiply(matrix);
    m.decompose(o.position, o.quaternion, o.scale);
    o.updateMatrixWorld(true);
    if (this.fragments.list.has(id)) this.fragments.core.update(true);
  }

  /** Nach einem Neuladen: alte Basis verwerfen (neues Objekt). */
  _basisVergessen(id) { this._basis?.delete(id); }

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
    const meshes = [];
    gruppe.traverse((o) => {
      if (!o.isMesh) return;
      let eid = null;
      for (let p = o; p && !eid; p = p.parent) {
        // Revit hängt die Element-ID ans Ende („Familie_Typ_416654“ oder „[416654]“) – nicht die erste
        // Zahl nehmen, sonst greift z. B. eine Norm-Nummer im Typnamen („DIN_18379“).
        const t = p.name && (p.name.match(/\[(\d+)\]\s*$/) || p.name.match(/(\d{3,})\D*$/));
        if (t) eid = t[1];
      }
      const d = eid && info?.bauteile?.[eid];
      o.userData.dbk = { modell: id, eid, info: d || null };
      meshes.push(o);
    });
    if (!this._fbxAusrichtenNachBauteilen(gruppe, meshes)) this._fbxAusrichten(gruppe, info);
    const kern = this._kernBox(gruppe, meshes);
    const zusammen = await this._fbxZusammenlegen(id, gruppe, meshes);
    this.world.scene.three.add(gruppe);
    this.fbx.set(id, { gruppe, info, nachKategorie: zusammen.nachKategorie, meshes: zusammen.meshes, kern });
    this.kategorien = this.kategorien || new Map();
    this.kategorien.set(id, [...zusammen.anzahl.keys()].sort().map((k) => ({
      name: k, gruppe: "Revit", klassen: [], an: true, anzahl: zusammen.anzahl.get(k) })));
    return this.kategorien.get(id);
  }

  /**
   * Revit-FBX hat je Bauteil eigene Meshes (Zehntausende Zeichenaufträge → ruckelt). Hier werden alle Teile
   * gleicher Kategorie und gleicher Farbe zu einem Mesh zusammengelegt. Welches Bauteil getroffen wurde,
   * ergibt sich aus dem Dreieck: je Mesh eine sortierte Liste „ab Dreieck n → Bauteil-ID“.
   * Normalen entfallen (flache Schattierung) – halbiert den Speicher.
   */
  async _fbxZusammenlegen(id, gruppe, meshes) {
    const { mergeGeometries } = await import("three/examples/jsm/utils/BufferGeometryUtils.js");
    gruppe.updateMatrixWorld(true);
    const zurueck = new THREE.Matrix4().copy(gruppe.matrixWorld).invert();
    const toepfe = new Map(), anzahl = new Map(), gezaehlt = new Set();
    for (const m of meshes) {
      const quelle = m.geometry;
      if (!quelle?.attributes?.position) continue;
      const mat = Array.isArray(m.material) ? m.material[0] : m.material;
      const d = m.userData.dbk || {};
      const kat = d.info?.k || "Ohne Zuordnung";
      const farbe = mat?.color ? mat.color.getHexString() : "a1a1aa";
      const deckkraft = mat?.transparent ? Math.round((mat.opacity ?? 1) * 10) / 10 : 1;
      const schluessel = `${kat}|${farbe}|${deckkraft}`;
      let g = new THREE.BufferGeometry();
      g.setAttribute("position", quelle.attributes.position.clone());
      if (quelle.index) { g.setIndex(quelle.index.clone()); g = g.toNonIndexed(); }
      g.applyMatrix4(new THREE.Matrix4().multiplyMatrices(zurueck, m.matrixWorld));
      quelle.dispose();
      if (!toepfe.has(schluessel)) toepfe.set(schluessel, { kat, farbe, deckkraft, teile: [], ab: [], eids: [], dreiecke: 0 });
      const t = toepfe.get(schluessel);
      t.teile.push(g);
      t.ab.push(t.dreiecke);
      t.eids.push(d.eid || null);
      t.dreiecke += g.attributes.position.count / 3;
      const z = `${kat}|${d.eid || m.uuid}`;
      if (!gezaehlt.has(z)) { gezaehlt.add(z); anzahl.set(kat, (anzahl.get(kat) || 0) + 1); }
    }
    gruppe.clear();
    const nachKategorie = new Map(), neu = [];
    for (const t of toepfe.values()) {
      const geo = mergeGeometries(t.teile, false);
      t.teile.forEach((g) => g.dispose());
      if (!geo) continue;
      geo.computeBoundingSphere();
      geo.computeBoundingBox();
      const mat = new THREE.MeshLambertMaterial({ color: new THREE.Color("#" + t.farbe), side: THREE.DoubleSide,
        flatShading: true, transparent: t.deckkraft < 1, opacity: t.deckkraft });
      const mesh = new THREE.Mesh(geo, mat);
      mesh.name = `FBX ${id} – ${t.kat}`;
      mesh.userData.dbk = { modell: id, kategorie: t.kat, ab: Uint32Array.from(t.ab), eids: t.eids };
      gruppe.add(mesh);
      neu.push(mesh);
      if (!nachKategorie.has(t.kat)) nachKategorie.set(t.kat, []);
      nachKategorie.get(t.kat).push(mesh);
    }
    return { meshes: neu, nachKategorie, anzahl };
  }

  /** Aus einem Treffer auf einem zusammengelegten FBX-Mesh: Bauteil-ID und Dreiecksbereich. */
  _fbxBauteil(mesh, dreieck) {
    const d = mesh.userData.dbk, ab = d.ab;
    let lo = 0, hi = ab.length - 1;
    while (lo < hi) { const mitte = (lo + hi + 1) >> 1; if (ab[mitte] <= dreieck) lo = mitte; else hi = mitte - 1; }
    const ende = lo + 1 < ab.length ? ab[lo + 1] : mesh.geometry.attributes.position.count / 3;
    return { eid: d.eids[lo], von: ab[lo], bis: ende };
  }

  /** Box ohne Ausreißer: 1.–99. Perzentil der Bauteilmitten (je Achse). Für „Alles zeigen“. */
  _kernBox(gruppe, meshes) {
    gruppe.updateMatrixWorld(true);
    const schritt = Math.max(1, Math.floor(meshes.length / 5000));
    const ax = [[], [], []], b = new THREE.Box3(), c = new THREE.Vector3();
    for (let i = 0; i < meshes.length; i += schritt) {
      b.setFromObject(meshes[i]);
      if (b.isEmpty()) continue;
      b.getCenter(c);
      ax[0].push(c.x); ax[1].push(c.y); ax[2].push(c.z);
    }
    if (!ax[0].length) return new THREE.Box3().setFromObject(gruppe);
    const p = (a, q) => a[Math.min(a.length - 1, Math.floor(q * a.length))];
    for (const a of ax) a.sort((x, y) => x - y);
    return new THREE.Box3(new THREE.Vector3(p(ax[0], 0.01), p(ax[1], 0.01), p(ax[2], 0.01)),
      new THREE.Vector3(p(ax[0], 0.99), p(ax[1], 0.99), p(ax[2], 0.99)));
  }

  /** Modell (FBX oder Fragments) ganz aus der Szene nehmen. */
  async entferneModell(id) {
    this.entfernePlan(id);
    this.entferneFbx(id);
    if (this.fragments.list.has(id)) {
      this._basisVergessen(id);
      await this.fragments.core.disposeModel(id);
      this.fragments.core.update(true);
    }
    this.kategorien?.delete(id);
  }

  entferneFbx(id) {
    const f = this.fbx.get(id);
    if (!f) return;
    this._basisVergessen(id);
    this.world.scene.three.remove(f.gruppe);
    f.gruppe.traverse((o) => { if (o.isMesh) { o.geometry.dispose(); } });
    this.fbx.delete(id);
  }

  /**
   * Maßstab, Hochachse und Lage aus den einzelnen Bauteilen bestimmen: je Bauteil-ID die Box im FBX mit der
   * Box aus Revit vergleichen und jeweils den Median nehmen. So stören einzelne Ausreißer (Bauteile mit
   * kaputter, kilometergroßer Box) nicht. Mit zu wenigen zugeordneten Bauteilen: Gesamtbox wie bisher.
   */
  _fbxAusrichtenNachBauteilen(gruppe, meshes) {
    const nachId = new Map();
    for (const m of meshes) {
      const d = m.userData.dbk;
      if (!d?.info?.b) continue;
      if (!nachId.has(d.eid)) nachId.set(d.eid, { b: d.info.b, meshes: [] });
      nachId.get(d.eid).meshes.push(m);
    }
    if (nachId.size < 20) return false;
    const proben = [...nachId.values()];
    const schritt = Math.max(1, Math.floor(proben.length / 4000));
    const auswahl = proben.filter((_, i) => i % schritt === 0);
    const median = (a) => { const s = [...a].sort((x, y) => x - y); return s.length ? s[s.length >> 1] : NaN; };
    const sollBox = (b) => new THREE.Box3(new THREE.Vector3(b[0] / 1000, b[2] / 1000, -b[4] / 1000),
      new THREE.Vector3(b[3] / 1000, b[5] / 1000, -b[1] / 1000));
    let bester = null;
    for (const drehung of [0, -Math.PI / 2]) {          // Y oben bzw. Z oben
      gruppe.rotation.set(drehung, 0, 0);
      gruppe.scale.setScalar(1);
      gruppe.position.set(0, 0, 0);
      gruppe.updateMatrixWorld(true);
      const paare = [], verhaeltnisse = [];
      for (const p of auswahl) {
        const ist = new THREE.Box3();
        for (const m of p.meshes) ist.expandByObject(m);
        if (ist.isEmpty()) continue;
        const soll = sollBox(p.b);
        const gi = ist.getSize(new THREE.Vector3()), gs = soll.getSize(new THREE.Vector3());
        for (const k of ["x", "y", "z"]) if (gi[k] > 1e-9 && gs[k] > 0.05) verhaeltnisse.push(gs[k] / gi[k]);
        paare.push([ist.getCenter(new THREE.Vector3()), soll.getCenter(new THREE.Vector3())]);
      }
      const faktor = median(verhaeltnisse);
      if (!(faktor > 0) || !isFinite(faktor)) continue;
      const fehler = median(verhaeltnisse.map((v) => Math.abs(Math.log(v / faktor))));
      if (!bester || fehler < bester.fehler) bester = { drehung, faktor, fehler, paare };
    }
    if (!bester) return false;
    const { drehung, faktor, paare } = bester;
    const versatz = ["x", "y", "z"].map((k) => median(paare.map(([i, s]) => s[k] - faktor * i[k])));
    gruppe.rotation.set(drehung, 0, 0);
    gruppe.scale.setScalar(faktor);
    gruppe.position.set(...versatz);
    gruppe.updateMatrixWorld(true);
    return true;
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
    for (const [, f] of this.fbx) if (f.gruppe.visible) box.union(f.kern || new THREE.Box3().setFromObject(f.gruppe));
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
      const form = this._durchbruchForm(o.daten);
      const geo = form.geo;
      const farbe = FARBE[o.wirkung] ?? FARBE.offen;
      const mat = new THREE.MeshLambertMaterial({ color: farbe, emissive: farbe, emissiveIntensity: 0.25 });
      const mesh = new THREE.Mesh(geo, mat);
      mesh.position.copy(form.mitte);
      mesh.quaternion.copy(form.drehung);
      const groesse = form.grundriss;
      mesh.userData = { id: o.id, nummer: o.daten.nummer, groesse: o.daten.groesse || "", ebene: o.daten.ebene };
      const kante = new THREE.LineSegments(new THREE.EdgesGeometry(geo),
        new THREE.LineBasicMaterial({ color: 0x2c2c2a, transparent: true, opacity: 0.6 }));
      mesh.add(kante);
      // Grundriss-Umriss: liegt knapp unter der Schnitthöhe, damit er nie weggeschnitten wird
      const fuss = new THREE.Mesh(new THREE.PlaneGeometry(Math.max(groesse[0], 0.08), Math.max(groesse[1], 0.08)),
        new THREE.MeshBasicMaterial({ color: farbe, transparent: true, opacity: 0.85, depthTest: false, side: THREE.DoubleSide }));
      fuss.quaternion.copy(form.fussDrehung);
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

  /**
   * Form eines Durchbruchs: gedrehte Box aus ``ausrichtung`` (Exemplar-Achsen aus Revit), sonst achsparallel
   * aus min/max. Rund: Zylinder entlang der Achse, deren Querschnitt am rundesten ist (Decke → senkrecht).
   * Liefert {geo, mitte, drehung, grundriss: [b, t] (Umriss von oben), fussDrehung}.
   */
  _durchbruchForm(d) {
    const g = d.geometrie, a = d.ausrichtung;
    const revitZuThree = (v) => new THREE.Vector3(v[0], v[2], -v[1]);
    let mitte, achsen, s;
    if (a && a.achsen && a.groesse_mm) {
      mitte = this.zuThree(a.mitte_mm);
      achsen = a.achsen.map(revitZuThree);
      s = a.groesse_mm.map((v) => Math.max(v, 5) / 1000);
    } else {
      const p = this.zuThree(g.min), q = this.zuThree(g.max);
      mitte = p.clone().add(q).multiplyScalar(0.5);
      achsen = [[1, 0, 0], [0, 1, 0], [0, 0, 1]].map(revitZuThree);
      s = [0, 1, 2].map((k) => Math.max(Math.abs(g.max[k] - g.min[k]), 5) / 1000);
    }
    // Rechtshändig machen (gespiegelte Exemplare), sonst lässt sich keine Drehung bilden
    if (achsen[0].clone().cross(achsen[1]).dot(achsen[2]) < 0) achsen[2].negate();
    const drehung = new THREE.Quaternion().setFromRotationMatrix(new THREE.Matrix4().makeBasis(...achsen));
    let geo;
    if (g.form === "rund") {
      // Achse k: die beiden anderen Maße sind (fast) gleich = Kreisquerschnitt
      let k = [0, 1, 2].sort((i, j) => {
        const q = (n) => { const r = [0, 1, 2].filter((x) => x !== n).map((x) => s[x]); return Math.abs(r[0] - r[1]) / Math.max(r[0], r[1]); };
        return q(i) - q(j);
      })[0];
      if (!a && d.lage === "decke") k = 2;                  // alte Daten: Deckendurchbruch senkrecht
      const quer = [0, 1, 2].filter((x) => x !== k).map((x) => s[x]);
      const r = (quer[0] + quer[1]) / 4;
      geo = new THREE.CylinderGeometry(r, r, s[k], 28);
      if (k === 0) geo.rotateZ(Math.PI / 2);
      if (k === 2) geo.rotateX(Math.PI / 2);
    } else {
      geo = new THREE.BoxGeometry(s[0], s[1], s[2]);
    }
    // Umriss von oben: Ebene in der lokalen Achsen-Ebene, die am waagerechtesten liegt
    const oben = new THREE.Vector3(0, 1, 0);
    const senk = [0, 1, 2].sort((i, j) => Math.abs(achsen[j].dot(oben)) - Math.abs(achsen[i].dot(oben)))[0];
    const [u, w] = [0, 1, 2].filter((x) => x !== senk);
    const fussDrehung = new THREE.Quaternion();
    if (senk === 1) fussDrehung.setFromEuler(new THREE.Euler(-Math.PI / 2, 0, 0));
    if (senk === 0) fussDrehung.setFromEuler(new THREE.Euler(0, Math.PI / 2, 0));
    return { geo, mitte, drehung, grundriss: [s[u], s[w]], fussDrehung };
  }

  /** Im Grundriss: Durchbrüche des Geschosses als Umriss auf Schnitthöhe zeigen. */
  _grundrissMarken() {
    const y = this._geschossEbene.constant - 0.02;
    for (const m of this.meshes.values()) {
      const fuss = m.getObjectByName("grundriss");
      const an = this.modus === "plan" && m.userData.ebene === this.geschoss;
      fuss.visible = an;
      if (an) {
        m.updateMatrixWorld(true);
        fuss.position.set(0, 0, 0);
        fuss.position.copy(m.worldToLocal(new THREE.Vector3(m.position.x, y, m.position.z)));
      }
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
    this._planTiefe();
  }

  /** Grundriss-Modus: Pläne liegen wie ein Blatt über dem Modell (unter den Durchbrüchen); 3D: normal im Raum. */
  _planTiefe() {
    for (const m of this.plaene?.values() || []) {
      const oben = this.modus === "plan" && m.userData.plan.art === "grundriss";
      m.material.depthTest = !oben;
      m.renderOrder = oben ? -10 : 5;
      m.material.needsUpdate = true;
    }
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
    for (const [, f] of this.fbx) box.union(f.kern || new THREE.Box3().setFromObject(f.gruppe));
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

  /** Die (eine) aktive Schnittebene als {normal, punkt} (Viewer-Koordinaten) oder null. */
  ebeneLesen() {
    const p = [...this.clipper.list.values()][0];
    return p ? { normal: p.normal.toArray(), punkt: p.origin.toArray() } : null;
  }

  /** Genau diese Schnittebene zeigen (alle anderen weg); null = keine Ebene. */
  ebeneSetzen(e) {
    this.clipper.deleteAll();
    if (e) this.clipper.createFromNormalAndCoplanarPoint(this.world, new THREE.Vector3(...e.normal), new THREE.Vector3(...e.punkt));
    this.fragments.core.update(true);
  }

  // ------------------------------------------------------------- Punkte wählen (Ausrichten)

  /**
   * Nächster Klick liefert {punkt, modell}: Punkt auf einem Modell, eingerastet auf die nächste Ecke des
   * getroffenen Dreiecks (FBX) – so lassen sich gleiche Punkte in zwei Modellen genau treffen. Esc → null.
   */
  punktWaehlen(auchDurchbrueche = false) {
    this._punktAuchDurchbrueche = auchDurchbrueche;
    this._werkzeug = "punkt";
    this.container.classList.add("werkzeug-aktiv");
    return new Promise((fertig) => { this._punktFertig = fertig; });
  }

  async _punktTreffer() {
    let bester = null;
    if (this._punktAuchDurchbrueche) {
      const td = this.caster.castRayToObjects([...this.meshes.values()].filter((m) => m.visible));
      if (td && this._nichtWeggeschnitten(td.point)) bester = { punkt: td.point.clone(), modell: "durchbruch", abstand: td.distance };
    }
    const gruppen = [...this.fbx.values()].filter((f) => f.gruppe.visible).map((f) => f.gruppe);
    const t = gruppen.length ? this.caster.castRayToObjects(gruppen) : null;
    if (t && t.object?.userData?.dbk && this._nichtWeggeschnitten(t.point)) {
      let punkt = t.point.clone();
      if (t.faceIndex != null) {
        const pos = t.object.geometry.attributes.position;
        let nah = null;
        for (let k = 0; k < 3; k++) {
          const v = new THREE.Vector3().fromBufferAttribute(pos, t.faceIndex * 3 + k).applyMatrix4(t.object.matrixWorld);
          if (!nah || v.distanceTo(t.point) < nah.distanceTo(t.point)) nah = v;
        }
        if (nah && nah.distanceTo(t.point) < 0.6) punkt = nah;
      }
      if (!bester || t.distance < bester.abstand) bester = { punkt, modell: t.object.userData.dbk.modell, abstand: t.distance };
    }
    try {
      const r = await this.caster.castRay();
      if (r && r.point && r.fragments && this._nichtWeggeschnitten(r.point)) {
        const d = r.point.distanceTo(this.world.camera.three.position);
        if (!bester || d < bester.abstand) bester = { punkt: r.point.clone(), modell: r.fragments.modelId, abstand: d };
      }
    } catch { /* kein Treffer */ }
    return bester;
  }

  /** Kleine Kugel als Marke für gewählte Punkte (farbe: Zahl). */
  punktMarke(punkt, farbe = 0x185fa5) {
    const d = this.world.camera.three.position.distanceTo(punkt);
    const m = new THREE.Mesh(new THREE.SphereGeometry(Math.max(0.05, d * 0.008), 16, 12),
      new THREE.MeshBasicMaterial({ color: farbe, depthTest: false }));
    m.renderOrder = 20;
    m.position.copy(punkt);
    this.world.scene.three.add(m);
    (this._punktMarken = this._punktMarken || []).push(m);
  }

  punktMarkenWeg() {
    for (const m of this._punktMarken || []) { this.world.scene.three.remove(m); m.geometry.dispose(); }
    this._punktMarken = [];
  }

  /** Drehpunkt und Mitte, um die ``ausrichten`` dreht (Viewer-Koordinaten). */
  ausrichtungsMitte(id) {
    if (!this._basis?.has(id)) this.ausrichten(id, null);
    return this._basis?.get(id)?.mitte?.clone() || new THREE.Vector3();
  }

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
        this.clipper.deleteAll();                      // immer nur eine Ebene – Schnitte werden in der Liste umgeschaltet
        await this.clipper.create(this.world);
        this.onEbeneErstellt?.(this.ebeneLesen());
        return;
      }
      if (this._werkzeug === "punkt") {
        const t = await this._punktTreffer();
        if (!t) return;                                // daneben geklickt: weiter warten
        this._werkzeug = null;
        el.classList.remove("werkzeug-aktiv");
        const fertig = this._punktFertig;
        this._punktFertig = null;
        fertig?.(t);
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
      if (tf && tf.object?.userData?.dbk?.ab && tf.faceIndex != null && this._nichtWeggeschnitten(tf.point)) {
        const b = this._fbxBauteil(tf.object, tf.faceIndex);
        await this.bauteilWaehlen({ modelId: tf.object.userData.dbk.modell, fbx: tf.object, ...b });
        return;
      }
      const r = await this.caster.castRay();
      const ok = r && r.localId !== undefined && r.fragments && this._nichtWeggeschnitten(r.point);
      await this.bauteilWaehlen(ok ? { modelId: r.fragments.modelId, localId: r.localId } : null);
      if (!ok) { this.waehle(null); this.onAuswahl(null); }
    });
    el.addEventListener("keydown", (e) => {
      if (e.key === "Escape" && this._werkzeug) {
        if (this._werkzeug === "punkt") { const f = this._punktFertig; this._punktFertig = null; f?.(null); }
        this._werkzeug = null;
        el.classList.remove("werkzeug-aktiv");
        this.onWerkzeugEnde?.();
      }
    });
  }

  /** Modellbauteil hervorheben (oder Auswahl aufheben mit null) und melden. */
  async bauteilWaehlen(auswahl) {
    const alt = this.bauteil;
    if (alt?.fbx) {
      if (this._fbxMarke) {
        this._fbxMarke.parent?.remove(this._fbxMarke);
        this._fbxMarke.geometry.dispose();
        this._fbxMarke = null;
      }
    } else if (alt) {
      const m = this.fragments.list.get(alt.modelId);
      if (m) await m.resetHighlight([alt.localId]);
    }
    this.bauteil = auswahl;
    this._bauteilBox = null;
    if (auswahl?.fbx) {
      // Nur die Dreiecke dieses Bauteils als eigenes, eingefärbtes Mesh darüberlegen
      const pos = auswahl.fbx.geometry.attributes.position;
      const teil = new THREE.BufferGeometry();
      teil.setAttribute("position", new THREE.BufferAttribute(pos.array.slice(auswahl.von * 9, auswahl.bis * 9), 3));
      const marke = new THREE.Mesh(teil, new THREE.MeshLambertMaterial({ color: FARBE_AUSWAHL, side: THREE.DoubleSide,
        flatShading: true, polygonOffset: true, polygonOffsetFactor: -1 }));
      auswahl.fbx.add(marke);
      this._fbxMarke = marke;
      marke.updateMatrixWorld(true);
      this._bauteilBox = new THREE.Box3().setFromObject(marke);
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
    const f = this.fbx.get(auswahl.modelId);
    const i = (auswahl.eid && f?.info?.bauteile?.[auswahl.eid]) || {};
    return {
      titel: i.t ? `${i.f || ""} : ${i.t}` : (auswahl.fbx.userData.dbk?.kategorie || "Bauteil"),
      zeilen: [["Modell", auswahl.modelId], ["Kategorie", i.k], ["Familie", i.f], ["Typ", i.t], ["Ebene", i.e],
        ["System", i.s], ["Größe", i.g], ["Revit-ID", auswahl.eid]].filter(([, v]) => v),
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
    this._messTexteAktualisieren(cam, breite, hoehe);
  }

  // ------------------------------------------------------------- Messen

  /** Strecke a–b (Viewer-Koordinaten, m) mit Beschriftung „3,45 m“ (+ Δ waagerecht/senkrecht) einzeichnen. */
  messungHinzu(a, b) {
    if (!this.messTexte) {
      this.messTexte = document.createElement("div");
      this.messTexte.className = "labels";
      this.container.appendChild(this.messTexte);
    }
    const farbe = 0x185fa5;
    const linie = new THREE.Line(new THREE.BufferGeometry().setFromPoints([a, b]),
      new THREE.LineBasicMaterial({ color: farbe, depthTest: false, linewidth: 2 }));
    linie.renderOrder = 30;
    const kugeln = [a, b].map((p) => {
      const d = this.world.camera.three.position.distanceTo(p);
      const k = new THREE.Mesh(new THREE.SphereGeometry(Math.max(0.03, d * 0.005), 12, 8),
        new THREE.MeshBasicMaterial({ color: farbe, depthTest: false }));
      k.position.copy(p);
      k.renderOrder = 31;
      return k;
    });
    for (const o of [linie, ...kugeln]) this.world.scene.three.add(o);
    const m = (x) => (x).toFixed(2).replace(".", ",") + " m";
    const d = a.distanceTo(b), dh = Math.hypot(b.x - a.x, b.z - a.z), dv = Math.abs(b.y - a.y);
    const div = document.createElement("div");
    div.className = "mess-text";
    div.textContent = m(d) + (dh > 0.01 && dv > 0.01 ? `  (waagerecht ${m(dh)} · senkrecht ${m(dv)})` : "");
    this.messTexte.appendChild(div);
    (this.messungen = this.messungen || []).push({ objekte: [linie, ...kugeln], div, mitte: a.clone().add(b).multiplyScalar(0.5) });
  }

  messungenWeg() {
    for (const m of this.messungen || []) {
      for (const o of m.objekte) { this.world.scene.three.remove(o); o.geometry.dispose(); }
      m.div.remove();
    }
    this.messungen = [];
  }

  _messTexteAktualisieren(cam, breite, hoehe) {
    const v = new THREE.Vector3();
    for (const m of this.messungen || []) {
      v.copy(m.mitte).project(cam);
      const sichtbar = v.z <= 1 && Math.abs(v.x) <= 1.1 && Math.abs(v.y) <= 1.1;
      m.div.style.display = sichtbar ? "" : "none";
      if (sichtbar) { m.div.style.left = ((v.x + 1) / 2) * breite + "px"; m.div.style.top = ((1 - v.y) / 2) * hoehe + "px"; }
    }
  }
}
