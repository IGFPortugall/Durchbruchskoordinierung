# -*- coding: utf-8 -*-
"""Durchbruchsprüfung in Revit – andockbare Leiste wie Eigenschaften/Projektbrowser.

Gleicher Inhalt wie rechts im Viewer: Suche, Filter, Liste, Detail mit Freigeben/Ablehnen und
Verlauf (Chat). Schreibt dieselben Ereignisse in denselben Projektordner – eine Freigabe hier
erscheint im Viewer (und umgekehrt), sobald der Ordner abgeglichen ist.

Die Leiste wird beim Start von pyRevit angemeldet (``startup.py`` der Erweiterung); Revit
erlaubt das nur beim Start. Der Knopf „Durchbruchsprüfung“ blendet sie ein/aus.

Laden: die Ereignisse werden im Hintergrund gelesen (Tausende kleine Dateien sollen Revit nicht
blockieren) und alle 20 Sekunden nachgeladen. Was die Revit-API braucht (Zeigen, Projekt des
aktiven Modells lesen), läuft über ein ExternalEvent.
"""
from __future__ import unicode_literals

import os
import time
import traceback

import System
from System import Action, TimeSpan
from System.Threading import Thread, ThreadStart
from System.Windows import Thickness, TextWrapping, FontWeights, Visibility
from System.Windows.Controls import StackPanel, TextBlock, Orientation, ListBoxItem
from System.Windows.Media import SolidColorBrush, ColorConverter
from System.Windows.Threading import DispatcherTimer
from Autodesk.Revit import UI
from pyrevit import forms

from dbk_core import Ablage, Projekt, berechne
from . import ansichten, einstellungen

PANEL_ID = "8d4f6a2e-1c3b-4e5f-9a7d-2b6c8e0f4a13"
XAML = os.path.join(os.path.dirname(__file__), "ui", "pruefleiste.xaml")
SCHLUESSEL = "DBK_Pruefleiste"           # AppDomain: die eine lebende Leiste (überlebt pyRevit-Neuladen)
MAX_ZEILEN = 400
NACHLADEN_S = 20

STATUS_FILTER = [("", "Alle Status"), ("offen", "In Prüfung"), ("blockiert", "Abgelehnt"), ("freigabe", "Freigegeben")]
WIRKUNG_TEXT = {"offen": "In Prüfung", "blockiert": "Abgelehnt", "freigabe": "Freigegeben"}


def _pinsel(farbe):
    b = SolidColorBrush(ColorConverter.ConvertFromString(farbe))
    b.Freeze()
    return b


FARBE = {"offen": _pinsel("#854F0B"), "blockiert": _pinsel("#A32D2D"), "freigabe": _pinsel("#3B6D11")}
GRAU, TEXT, ORANGE = _pinsel("#71717a"), _pinsel("#18181b"), _pinsel("#854F0B")


def masse_text(od):
    """Wie im Viewer: „Decke B × L 335 × 270 mm · Tiefe 300 · UK −0,18 m · OK +0,12 m“."""
    m = (od.get("geometrie") or {}).get("masse") or {}

    def mm(v):
        return "{:,}".format(int(round(v))).replace(",", ".")

    def meter(v):
        return ("+" if v >= 0 else "−") + ("%.2f m" % (abs(v) / 1000.0)).replace(".", ",")
    if m.get("durchmesser"):
        teil = "Ø %s mm" % mm(m["durchmesser"])
    elif m.get("laenge"):
        teil = "B × L %s × %s mm" % (mm(m.get("breite", 0)), mm(m["laenge"]))
    elif m.get("breite"):
        teil = "B × H %s × %s mm" % (mm(m["breite"]), mm(m.get("hoehe", 0)))
    else:
        teil = od.get("groesse") or ""
    art = {"decke": "Decke", "wand": "Wand"}.get(od.get("lage"), "")
    teile = [(" ".join(x for x in (art, teil) if x))]
    if m.get("tiefe"):
        teile.append("Tiefe %s" % mm(m["tiefe"]))
    if od.get("uk_mm") is not None:
        teile.append("UK " + meter(od["uk_mm"]))
    if od.get("ok_mm") is not None:
        teile.append("OK " + meter(od["ok_mm"]))
    return " · ".join(t for t in teile if t)


def wirt_text(od):
    w = od.get("wirt") or {}
    k = {"Wände": "Wand", "Geschossdecken": "Decke", "Dächer": "Dach"}.get(w.get("kategorie"), w.get("kategorie") or "")
    if w.get("tragend"):
        k += " tragend"
    elif w.get("tragend") is False:
        k += " nicht tragend"
    return k


def _zeit(iso):
    try:
        return "%s.%s. %s" % (iso[8:10], iso[5:7], iso[11:16])
    except Exception:
        return iso or ""


class _Warteschlange(UI.IExternalEventHandler):
    def __init__(self, leiste):
        self.leiste = leiste
        self.auftraege = []

    def Execute(self, uiapp):
        while self.auftraege:
            titel, f = self.auftraege.pop(0)
            try:
                f(uiapp)
            except Exception as e:
                self.leiste.melden("Fehler bei „%s“: %s" % (titel, e), fehler=True)
                print(traceback.format_exc())

    def GetName(self):
        return "DBK Durchbruchsprüfung"


def _zustand_rechts():
    s = UI.DockablePaneState()
    s.DockPosition = UI.DockPosition.Right
    return s


class Pruefleiste(forms.WPFPanel):
    panel_id = PANEL_ID
    panel_title = "Durchbruchsprüfung"
    panel_source = XAML
    initial_state = _zustand_rechts()

    def __init__(self):
        forms.WPFPanel.__init__(self)
        self.einst = {}
        self.dok_schluessel = None
        self.ablage = None
        self.projekt = None
        self.zustand = None
        self.auswahl = None
        self._laedt = False
        self._sperre = False
        self._handler = _Warteschlange(self)
        self._ereignis = UI.ExternalEvent.Create(self._handler)
        self.l_status.ItemsSource = [t for _, t in STATUS_FILTER]
        self.l_status.SelectedIndex = 0
        self.l_stand.ItemsSource = ["Alle Stände"]
        self.l_stand.SelectedIndex = 0
        self.l_suche.TextChanged += lambda s, a: self.liste_zeichnen()
        self.l_status.SelectionChanged += lambda s, a: self.liste_zeichnen()
        self.l_stand.SelectionChanged += lambda s, a: self.liste_zeichnen()
        self.l_ich.Click += lambda s, a: self.liste_zeichnen()
        self.l_liste.SelectionChanged += lambda s, a: self._gewaehlt()
        self.l_neu.Click += lambda s, a: self.auftrag("Neu laden", lambda uiapp: self.dokument(uiapp.ActiveUIDocument.Document, True))
        self.d_3d.Click += lambda s, a: self._zeigen("3d")
        self.d_2d.Click += lambda s, a: self._zeigen("2d")
        self.d_markieren.Click += lambda s, a: self._zeigen("markieren")
        self.d_frei.Click += lambda s, a: self._entscheiden("freigegeben")
        self.d_ab.Click += lambda s, a: self._entscheiden("abgelehnt")
        self.d_senden.Click += lambda s, a: self._nachricht()
        self.d_weitere.SelectionChanged += lambda s, a: self._weitere()
        self._timer = DispatcherTimer()
        self._timer.Interval = TimeSpan.FromSeconds(NACHLADEN_S)
        self._timer.Tick += lambda s, a: self.nachladen()
        self._timer.Start()
        self.detail_zeichnen()
        self.melden("Ein Revit-Modell öffnen – die Leiste lädt dessen Projekt.")

    # ---------------------------------------------------------------- Grundlagen

    def auftrag(self, titel, f):
        self._handler.auftraege.append((titel, f))
        self._ereignis.Raise()

    def melden(self, text, fehler=False):
        self.l_meldung.Text = text or ""
        self.l_meldung.Foreground = FARBE["blockiert"] if fehler else GRAU

    def _im_ui(self, f):
        self.Dispatcher.BeginInvoke(Action(f))

    # ---------------------------------------------------------------- Projekt des aktiven Modells

    def dokument(self, doc, erzwingen=False):
        """Im API-Kontext aufrufen (Knopf, Ansicht gewechselt): Einstellungen des Modells lesen, laden."""
        if doc is None or doc.IsFamilyDocument:
            return
        schluessel = einstellungen.dokument_schluessel(doc)
        if schluessel == self.dok_schluessel and not erzwingen and self.ablage is not None:
            return
        self.dok_schluessel = schluessel
        self.einst = einstellungen.laden(doc)
        self.ablage, self.zustand, self.auswahl = None, None, None
        e = self.einst
        if not einstellungen.vollstaendig(e):
            self.l_projekt.Text = "Kein Projekt"
            self.l_wer.Text = einstellungen.projekt_konflikt(e) or (
                "„%s“ ist noch mit keinem Projekt verbunden – im Werkzeug Durchbruchskoordination › Projekt einrichten."
                % doc.Title)
            self.l_liste.Items.Clear()
            self.detail_zeichnen()
            return
        self.l_projekt.Text = "Projekt „%s“" % (e.get("projekt_name") or "?")
        self.l_wer.Text = "%s · %s · %s" % (e.get("name"), e.get("rolle"), e.get("firma"))
        self.projekt = Projekt.laden(os.path.join(e["projektordner"], "projekt.json"))
        self.ablage = Ablage(e["projektordner"], einstellungen.absender(e))
        self.nachladen(erst=True)

    def nachladen(self, erst=False):
        """Neue Ereignisse im Hintergrund lesen, dann im UI-Thread neu zeichnen."""
        if self._laedt or self.ablage is None:
            return
        if not erst and not self.IsVisible:
            return
        self._laedt = True
        ablage = self.ablage
        if erst:
            self.melden("Lade Ereignisse …")

        def lesen():
            neu, fehler = [], None
            try:
                neu = ablage.lade_neue()
            except Exception as ex:
                fehler = ex

            def fertig():
                self._laedt = False
                if ablage is not self.ablage:
                    return                      # inzwischen anderes Modell
                if fehler is not None:
                    self.melden("Lesen fehlgeschlagen: %s" % fehler, fehler=True)
                    return
                if neu or erst or self.zustand is None:
                    self.zustand = berechne(ablage.alle(), self.projekt)
                    self.alles_zeichnen()
                if erst:
                    self.melden("%d Durchbrüche im Projekt." % len(self.zustand.objekte))
            self._im_ui(fertig)
        t = Thread(ThreadStart(lesen))
        t.IsBackground = True
        t.Start()

    # ---------------------------------------------------------------- Liste

    def alles_zeichnen(self):
        if self.zustand is None:
            return
        staende = sorted(set((o.stand or "Ohne Stand") for o in self.zustand.objekte.values()))
        alt = self.l_stand.SelectedItem
        self._sperre = True
        self.l_stand.ItemsSource = ["Alle Stände"] + staende
        self.l_stand.SelectedItem = alt if alt in staende else "Alle Stände"
        weitere = [s for s in self.projekt.status if s["id"] not in ("freigegeben", "abgelehnt")]
        self.d_weitere.ItemsSource = ["Weitere …"] + [s.get("name") or s["id"] for s in weitere]
        self.d_weitere.SelectedIndex = 0
        self._weitere_ids = [None] + [s["id"] for s in weitere]
        self._sperre = False
        self.liste_zeichnen()

    def _eintraege(self):
        z = self.zustand
        e = self.einst
        warten = set(z.wartet_auf(firma=e.get("firma"), rolle=e.get("rolle")))
        filt = STATUS_FILTER[self.l_status.SelectedIndex][0] if self.l_status.SelectedIndex >= 0 else ""
        stand = self.l_stand.SelectedItem if self.l_stand.SelectedIndex > 0 else None
        such = (self.l_suche.Text or "").strip().lower()
        ich = bool(self.l_ich.IsChecked)
        ergebnis, zahlen = [], {"offen": 0, "blockiert": 0, "freigabe": 0, "ich": len(warten)}
        for oid, o in z.objekte.items():
            gs = z.gesamtstatus(oid)
            zahlen[gs["wirkung"]] = zahlen.get(gs["wirkung"], 0) + 1
            if ich and oid not in warten:
                continue
            if filt and gs["wirkung"] != filt:
                continue
            if stand and (o.stand or "Ohne Stand") != stand:
                continue
            d = o.daten or {}
            if such:
                text = " ".join([d.get("nummer") or "", d.get("groesse") or "", d.get("ebene") or ""] +
                                [(v["daten"].get("text") or v["daten"].get("kommentar") or "") for v in o.verlauf]).lower()
                if such not in text:
                    continue
            ergebnis.append((oid, o, gs))
        ergebnis.sort(key=lambda x: (x[1].daten or {}).get("nummer") or "")
        return ergebnis, zahlen

    def liste_zeichnen(self):
        if self._sperre:
            return
        self.l_liste.Items.Clear()
        if self.zustand is None:
            return
        eintraege, zahlen = self._eintraege()
        self.l_zahlen.Text = "%d in Prüfung · %d abgelehnt · %d frei · %d für mich  –  %d angezeigt" % (
            zahlen.get("offen", 0), zahlen.get("blockiert", 0), zahlen.get("freigabe", 0), zahlen["ich"], len(eintraege))
        auswahl_item = None
        for oid, o, gs in eintraege[:MAX_ZEILEN]:
            d = o.daten or {}
            p = StackPanel()
            p.Margin = Thickness(2, 3, 2, 3)
            oben = StackPanel()
            oben.Orientation = Orientation.Horizontal
            nr = TextBlock()
            nr.Text = d.get("nummer") or oid
            nr.FontWeight = FontWeights.SemiBold
            st = TextBlock()
            st.Text = "   " + self._status_name(gs)
            st.Foreground = FARBE.get(gs["wirkung"], GRAU)
            oben.Children.Add(nr)
            oben.Children.Add(st)
            if o.einreichung in ("neu", "geaendert"):
                m = TextBlock()
                m.Text = "   " + ("neu" if o.einreichung == "neu" else "geändert")
                m.Foreground = ORANGE
                oben.Children.Add(m)
            info = TextBlock()
            info.Text = " · ".join(x for x in (d.get("ebene"), wirt_text(d), d.get("groesse"),
                                               "%d/%d" % (gs["pflicht_erfuellt"], gs["pflicht_gesamt"])) if x)
            info.Foreground = GRAU
            info.FontSize = 11.5
            p.Children.Add(oben)
            p.Children.Add(info)
            item = ListBoxItem()
            item.Content = p
            item.Tag = oid
            self.l_liste.Items.Add(item)
            if oid == self.auswahl:
                auswahl_item = item
        if len(eintraege) > MAX_ZEILEN:
            t = TextBlock()
            t.Text = "… %d weitere – bitte filtern oder suchen" % (len(eintraege) - MAX_ZEILEN)
            t.Foreground = GRAU
            self.l_liste.Items.Add(t)
        if not eintraege:
            t = TextBlock()
            t.Text = "Nichts zu tun – alles erledigt." if self.l_ich.IsChecked else "Keine Durchbrüche für diesen Filter."
            t.Foreground = GRAU
            t.Margin = Thickness(4, 8, 4, 8)
            self.l_liste.Items.Add(t)
        if auswahl_item is not None:
            self._sperre = True
            self.l_liste.SelectedItem = auswahl_item
            self._sperre = False
        self.detail_zeichnen()

    def _status_name(self, gs):
        if gs["status"] == "in_pruefung":
            return "Geändert – in Prüfung" if gs.get("geaendert") else "In Prüfung"
        for s in self.projekt.status:
            if s["id"] == gs["status"]:
                return s.get("name") or s["id"]
        return gs["status"]

    def _gewaehlt(self):
        if self._sperre:
            return
        item = self.l_liste.SelectedItem
        if isinstance(item, ListBoxItem):
            self.auswahl = item.Tag
            self.detail_zeichnen()

    # ---------------------------------------------------------------- Detail

    def _rollen_name(self, rid):
        for r in (self.projekt.rollen if self.projekt else []):
            if r["id"] == rid:
                return r.get("name") or rid
        return rid

    def detail_zeichnen(self):
        o = self.zustand.objekte.get(self.auswahl) if (self.zustand and self.auswahl) else None
        aktiv = o is not None
        for k in (self.d_3d, self.d_2d, self.d_markieren, self.d_frei, self.d_ab, self.d_weitere, self.d_senden, self.d_text):
            k.IsEnabled = aktiv
        self.d_verlauf.Children.Clear()
        if not aktiv:
            self.d_nummer.Text = "Kein Durchbruch gewählt"
            self.d_status.Text = ""
            self.d_meta.Text = "Durchbruch in der Liste anklicken."
            self.d_rollen.Text = ""
            return
        d = o.daten or {}
        gs = self.zustand.gesamtstatus(o.id)
        self.d_nummer.Text = d.get("nummer") or o.id
        self.d_status.Text = self._status_name(gs)
        self.d_status.Foreground = FARBE.get(gs["wirkung"], GRAU)
        zeilen = [masse_text(d), " · ".join(x for x in (d.get("ebene"), wirt_text(d)) if x),
                  "Stand „%s“ · %s%s" % (o.stand or "Ohne Stand", o.besitzer,
                                         (" · " + d["revit_modell"]) if d.get("revit_modell") else "")]
        self.d_meta.Text = "\n".join(z for z in zeilen if z)
        rollen = []
        for rid, r in sorted(gs["rollen"].items()):
            if not (r.get("stufe") or r.get("status")):
                continue
            wert = (self._status_name({"status": r["status"]}) if r.get("status")
                    else ("neu prüfen" if r.get("veraltet") else "offen"))
            rollen.append("%s%s: %s" % (self._rollen_name(rid), " (Pflicht)" if r.get("stufe") == "pflicht" else "", wert))
        self.d_rollen.Text = "Freigaben:  " + "  ·  ".join(rollen) if rollen else ""
        for ev in o.verlauf:
            self.d_verlauf.Children.Add(self._verlauf_zeile(ev))

    def _verlauf_zeile(self, ev):
        t = TextBlock()
        t.TextWrapping = TextWrapping.Wrap
        t.Margin = Thickness(0, 0, 0, 6)
        d = ev.get("daten") or {}
        kopf = "%s · %s · %s" % (ev.get("name"), ev.get("rolle"), _zeit(ev.get("zeit")))
        if ev["art"] == "status":
            text = "%s%s" % (self._status_name({"status": d.get("wert")}), (": " + d["kommentar"]) if d.get("kommentar") else "")
            farbe = FARBE.get(self.projekt.wirkung(d.get("wert")), TEXT)
        elif ev["art"] == "nachricht":
            text, farbe = d.get("text") or "", TEXT
        elif ev["art"] == "eingereicht":
            text = {"neu": "eingereicht", "geaendert": "geändert eingereicht"}.get(d.get("einreichung"), "eingereicht")
            farbe = GRAU
        else:
            text, farbe = ev["art"], GRAU
        k = TextBlock()
        k.Text = kopf
        k.Foreground = GRAU
        k.FontSize = 11
        p = StackPanel()
        p.Children.Add(k)
        t.Text = text
        t.Foreground = farbe
        p.Children.Add(t)
        return p

    # ---------------------------------------------------------------- Handeln

    def _objekt(self):
        return self.zustand.objekte.get(self.auswahl) if (self.zustand and self.auswahl) else None

    def _schreiben(self, art, daten):
        o = self._objekt()
        if o is None or self.ablage is None:
            return
        try:
            self.ablage.schreibe(art, o.id, daten)
        except Exception as e:
            self.melden("Speichern fehlgeschlagen: %s" % e, fehler=True)
            return
        self.d_text.Text = ""
        self.zustand = berechne(self.ablage.alle(), self.projekt)
        self.liste_zeichnen()
        self.melden("Gespeichert – erscheint im Viewer, sobald der Ordner abgeglichen ist.")

    def _entscheiden(self, wert):
        o = self._objekt()
        if o is None:
            return
        kommentar = (self.d_text.Text or "").strip() or None
        if wert == "abgelehnt" and not kommentar:
            self.melden("Bitte beim Ablehnen kurz begründen (Textfeld).", fehler=True)
            return
        self._schreiben("status", {"wert": wert, "geometrie_hash": o.geometrie_hash, "kommentar": kommentar})

    def _weitere(self):
        if self._sperre or self.d_weitere.SelectedIndex <= 0:
            return
        wert = self._weitere_ids[self.d_weitere.SelectedIndex]
        self._sperre = True
        self.d_weitere.SelectedIndex = 0
        self._sperre = False
        self._entscheiden(wert)

    def _nachricht(self):
        text = (self.d_text.Text or "").strip()
        if not text:
            self.melden("Bitte erst eine Nachricht eingeben.", fehler=True)
            return
        self._schreiben("nachricht", {"text": text})

    def _zeigen(self, art):
        o = self._objekt()
        if o is None:
            return
        objekt, einst = dict(o.daten or {}), dict(self.einst)

        def f(uiapp):
            if art == "3d":
                gefunden, markiert = ansichten.zeige_3d(uiapp, objekt, einst)
            elif art == "2d":
                gefunden, markiert = ansichten.zeige_2d(uiapp, objekt, einst)
            else:
                gefunden = markiert = ansichten.auswaehlen(uiapp, objekt)
            if not gefunden:
                self.melden("Das Revit-Modell „%s“ ist hier weder geöffnet noch verknüpft – Lage ist ggf. versetzt."
                            % objekt.get("revit_modell"), fehler=True)
            elif not markiert:
                self.melden("Ansicht gezeigt; den Durchbruch selbst gibt es im Modell nicht (mehr).")
            else:
                self.melden("")
        self.auftrag("In Revit zeigen", f)


# ------------------------------------------------------------------ Anmelden / Zeigen

def _lebend():
    return System.AppDomain.CurrentDomain.GetData(SCHLUESSEL)


def anmelden():
    """Aus startup.py: Leiste bei Revit anmelden (nur beim Start möglich)."""
    if _lebend() is not None:
        return _lebend()
    leiste = forms.register_dockable_panel(Pruefleiste, default_visible=False)
    System.AppDomain.CurrentDomain.SetData(SCHLUESSEL, leiste)

    def gewechselt(sender, args):
        try:
            if args.Document is not None and leiste.IsVisible:
                leiste.dokument(args.Document)
        except Exception:
            print(traceback.format_exc())
    leiste._ansicht_handler = gewechselt
    from pyrevit import HOST_APP
    HOST_APP.uiapp.ViewActivated += gewechselt
    return leiste


def umschalten(doc):
    """Aus dem Knopf: Leiste ein-/ausblenden und auf das aktive Modell setzen."""
    leiste = _lebend()
    if leiste is None:
        forms.alert("Die Leiste „Durchbruchsprüfung“ wird beim Start von Revit angemeldet.\n\n"
                    "Bitte Revit einmal neu starten (nach der Installation oder einem Update der Erweiterung).",
                    title="Durchbruchsprüfung")
        return
    pane = forms.get_dockable_panel(PANEL_ID)
    if pane.IsShown():
        pane.Hide()
        return
    pane.Show()
    leiste.dokument(doc, erzwingen=leiste.ablage is None)
