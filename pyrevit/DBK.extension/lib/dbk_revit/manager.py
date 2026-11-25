# -*- coding: utf-8 -*-
"""Prüf-Manager: nicht-modales Fenster in Revit.

Lesen/Schreiben des Projektordners läuft direkt im Fenster. Alles, was die
Revit-API braucht (Ansichten, Auswahl), läuft über ein ExternalEvent.
"""
from __future__ import unicode_literals

import os
import webbrowser
from datetime import datetime

from System import TimeSpan
from System.Windows import Media, Thickness, TextWrapping, HorizontalAlignment, FontWeights
from System.Windows.Controls import Border, TextBlock, DockPanel, Dock
from System.Windows.Threading import DispatcherTimer
from Autodesk.Revit import UI
from pyrevit import forms

from dbk_core import Ablage, berechne
from dbk_core.projekt import BLOCKIERT, FREIGABE, OFFEN, PFLICHT
from . import aktionen, ansichten
from .einstellungen import absender

XAML = os.path.join(os.path.dirname(__file__), "ui", "manager.xaml")

FARBEN = {
    OFFEN: ("#FAEEDA", "#854F0B"),
    BLOCKIERT: ("#FCEBEB", "#A32D2D"),
    FREIGABE: ("#EAF3DE", "#3B6D11"),
    None: ("#F1EFE8", "#5F5E5A"),
}
_PINSEL = {}


def pinsel(farbe):
    if farbe not in _PINSEL:
        b = Media.SolidColorBrush(Media.ColorConverter.ConvertFromString(farbe))
        b.Freeze()
        _PINSEL[farbe] = b
    return _PINSEL[farbe]


class _Auftrag(UI.IExternalEventHandler):
    def __init__(self):
        self.aufgabe = None

    def Execute(self, uiapp):
        aufgabe, self.aufgabe = self.aufgabe, None
        if aufgabe is not None:
            try:
                aufgabe(uiapp)
            except Exception as e:
                UI.TaskDialog.Show("DBK", "Das hat nicht geklappt:\n%s" % e)

    def GetName(self):
        return "DBK Prüf-Manager"


class Zeile(object):
    def __init__(self, oid, o, gs, statusname, wartet):
        d = o.daten
        self.id = oid
        self.nummer = d.get("nummer", "")
        self.status = statusname
        self.ebene = d.get("ebene", "")
        w = d.get("wirt") or {}
        art = {"Wände": "Wand", "Geschossdecken": "Decke"}.get(w.get("kategorie"), w.get("kategorie") or "")
        self.wirt = ("%s %s" % (art, "tragend" if w.get("tragend") else "")).strip()
        self.groesse = d.get("groesse", "")
        self.pflicht = "%d/%d" % (gs["pflicht_erfuellt"], gs["pflicht_gesamt"])
        bg, fg = FARBEN.get(gs["wirkung"], FARBEN[None])
        self.farbe_bg, self.farbe_text = pinsel(bg), pinsel(fg)
        self.wartet = wartet
        self.wirkung = gs["wirkung"]
        self.suchtext = " ".join([self.nummer, self.groesse] + [
            (v["daten"].get("text") or v["daten"].get("kommentar") or "") for v in o.verlauf]).lower()


class PruefManager(forms.WPFWindow):

    def __init__(self, einst):
        forms.WPFWindow.__init__(self, XAML)
        self.einst = einst
        self.ich = absender(einst)
        self.ablage = Ablage(einst["projektordner"], self.ich)
        self.projekt = aktionen.projekt_laden(einst["projektordner"])
        self.zustand = None
        self.auswahl = None
        self._handler = _Auftrag()
        self._ereignis = UI.ExternalEvent.Create(self._handler)

        self.kopf.Text = "%s · %s · %s" % (self.ich.name, self._rollenname(self.ich.rolle), self.ich.firma)
        self.filter_status.ItemsSource = ["Alle Status", "In Prüfung", "Abgelehnt", "Freigegeben"]
        self.filter_status.SelectedIndex = 0
        self.weitere.ItemsSource = ["Weitere …"] + [s["name"] for s in self.projekt.status
                                                    if s["id"] not in ("freigegeben", "abgelehnt")]
        self.weitere.SelectedIndex = 0

        self.suche.TextChanged += lambda s, e: self.liste_zeichnen()
        self.filter_status.SelectionChanged += lambda s, e: self.liste_zeichnen()
        self.filter_ebene.SelectionChanged += lambda s, e: self.liste_zeichnen()
        self.filter_ich.Click += lambda s, e: self.liste_zeichnen()
        self.liste.SelectionChanged += self._liste_auswahl
        self.knopf_neu.Click += lambda s, e: self.laden(True)
        self.knopf_viewer.Click += lambda s, e: self._viewer()
        self.knopf_2d.Click += lambda s, e: self._revit(ansichten.zeige_2d)
        self.knopf_3d.Click += lambda s, e: self._revit(ansichten.zeige_3d)
        self.knopf_auswahl.Click += lambda s, e: self._revit(lambda app, o, _e: ansichten.auswaehlen(app, o))
        self.knopf_frei.Click += lambda s, e: self._entscheiden("freigegeben")
        self.knopf_ab.Click += lambda s, e: self._entscheiden("abgelehnt")
        self.weitere.SelectionChanged += self._weitere
        self.knopf_senden.Click += lambda s, e: self._senden()
        self.knopf_erneut.Click += lambda s, e: self._erneut()

        self.laden(True)
        self._timer = DispatcherTimer()
        self._timer.Interval = TimeSpan.FromSeconds(5)
        self._timer.Tick += lambda s, e: self.laden(False)
        self._timer.Start()
        self.Closed += lambda s, e: self._timer.Stop()

    # ------------------------------------------------------------ Daten

    def laden(self, immer):
        try:
            neu = self.ablage.lade_neue()
        except Exception as e:
            self.meldung.Text = "Projektordner nicht lesbar: %s" % e
            return
        if neu or immer or self.zustand is None:
            self.zustand = berechne(self.ablage.alle(), self.projekt)
            ebenen = sorted(set(o.daten.get("ebene", "") for o in self.zustand.objekte.values()))
            alt = self.filter_ebene.SelectedItem
            self.filter_ebene.ItemsSource = ["Alle Geschosse"] + ebenen
            self.filter_ebene.SelectedItem = alt if alt in ebenen else "Alle Geschosse"
            self.liste_zeichnen()

    def _statusname(self, gs):
        if gs["status"] == "in_pruefung":
            return "Geändert – in Prüfung" if gs["geaendert"] else "In Prüfung"
        s = self.projekt_status(gs["status"])
        return s

    def projekt_status(self, sid):
        for s in self.projekt.status:
            if s["id"] == sid:
                return s["name"]
        return sid

    def liste_zeichnen(self):
        if self.zustand is None:
            return
        z = self.zustand
        warten = set(z.wartet_auf(firma=self.ich.firma, rolle=self.ich.rolle))
        such = (self.suche.Text or "").strip().lower()
        status = {1: OFFEN, 2: BLOCKIERT, 3: FREIGABE}.get(self.filter_status.SelectedIndex)
        ebene = self.filter_ebene.SelectedItem if self.filter_ebene.SelectedIndex > 0 else None
        nur_ich = bool(self.filter_ich.IsChecked)
        zeilen = []
        for oid in sorted(z.objekte, key=lambda k: z.objekte[k].daten.get("nummer", "")):
            o = z.objekte[oid]
            gs = z.gesamtstatus(oid)
            zl = Zeile(oid, o, gs, self._statusname(gs), oid in warten)
            if nur_ich and not zl.wartet:
                continue
            if status and zl.wirkung != status:
                continue
            if ebene and zl.ebene != ebene:
                continue
            if such and such not in zl.suchtext:
                continue
            zeilen.append(zl)
        self.liste.ItemsSource = zeilen
        for zl in zeilen:
            if zl.id == self.auswahl:
                self.liste.SelectedItem = zl
        self.detail_zeichnen()

    def _liste_auswahl(self, sender, args):
        zl = self.liste.SelectedItem
        if zl is not None and zl.id != self.auswahl:
            self.auswahl = zl.id
            self.kommentar.Text = ""
            self.detail_zeichnen()

    # ------------------------------------------------------------ Detail

    def detail_zeichnen(self):
        self.meldung.Text = ""
        o = self.zustand.objekte.get(self.auswahl) if (self.zustand and self.auswahl) else None
        self.rollen.Children.Clear()
        self.verlauf.Children.Clear()
        aktiv = o is not None
        for k in (self.knopf_2d, self.knopf_3d, self.knopf_auswahl, self.knopf_frei, self.knopf_ab,
                  self.weitere, self.knopf_senden, self.knopf_erneut):
            k.IsEnabled = aktiv
        if not aktiv:
            self.titel.Text = "Durchbruch auswählen"
            self.meta.Text = ""
            self.status_rahmen.Background = pinsel("#FFFFFF")
            self.status_text.Text = ""
            return
        d = o.daten
        gs = self.zustand.gesamtstatus(o.id)
        self.titel.Text = d.get("nummer", o.id)
        bg, fg = FARBEN.get(gs["wirkung"], FARBEN[None])
        self.status_rahmen.Background = pinsel(bg)
        self.status_text.Foreground = pinsel(fg)
        self.status_text.Text = self._statusname(gs)
        w = d.get("wirt") or {}
        teile = [d.get("ebene"), "%s %s" % (w.get("kategorie", ""), "tragend" if w.get("tragend") else ""),
                 d.get("groesse"), "UK %.2f m" % (d["uk_mm"] / 1000.0) if d.get("uk_mm") is not None else None,
                 d.get("familie")]
        self.meta.Text = " · ".join(t.strip() for t in teile if t and t.strip()) + "\nEingereicht von %s" % o.besitzer
        meine_stufe = gs["rollen"].get(self.ich.rolle, {}).get("stufe")
        self.knopf_frei.IsEnabled = self.knopf_ab.IsEnabled = self.weitere.IsEnabled = bool(meine_stufe)
        self.knopf_erneut.IsEnabled = o.besitzer == self.ich.firma and gs["wirkung"] == BLOCKIERT

        for rolle, r in sorted(gs["rollen"].items()):
            if not (r["stufe"] or r["status"]):
                continue
            zeile = DockPanel()
            zeile.Margin = Thickness(0, 1, 0, 1)
            name = self._rollenname(rolle) + ("  Pflicht" if r["stufe"] == PFLICHT else "  Info" if r["stufe"] else "")
            text = self.projekt_status(r["status"]) if r["status"] else ("neu prüfen" if r["veraltet"] else "offen")
            pill = self._pill(text, r["wirkung"])
            DockPanel.SetDock(pill, Dock.Right)
            zeile.Children.Add(pill)
            tb = TextBlock()
            tb.Text = name
            zeile.Children.Add(tb)
            self.rollen.Children.Add(zeile)

        for e in o.verlauf:
            self._verlauf_zeile(e)
        self.verlauf_scroll.ScrollToEnd()

    def _rollenname(self, rid):
        for r in self.projekt.rollen:
            if r["id"] == rid:
                return r["name"]
        return rid

    def _pill(self, text, wirkung):
        bg, fg = FARBEN.get(wirkung, FARBEN[None])
        b = Border()
        b.Background = pinsel(bg)
        b.CornerRadius = System_CornerRadius(6)
        b.Padding = Thickness(6, 0, 6, 1)
        t = TextBlock()
        t.Text = text
        t.Foreground = pinsel(fg)
        b.Child = t
        return b

    def _verlauf_zeile(self, e):
        eigen = e["firma"] == self.ich.firma and e["name"] == self.ich.name
        try:
            wann = datetime.strptime(e["zeit"][:19], "%Y-%m-%dT%H:%M:%S").strftime("%d.%m. %H:%M") + " UTC"
        except ValueError:
            wann = e["zeit"]
        wer = "%s · %s · %s" % (e["name"], self._rollenname(e["rolle"]), wann)
        if e["art"] in ("status", "eingereicht", "geaendert"):
            if e["art"] == "status":
                text, wirkung = self.projekt_status(e["daten"]["wert"]), self.projekt.wirkung(e["daten"]["wert"])
            else:
                text, wirkung = ("eingereicht", OFFEN) if e["art"] == "eingereicht" else ("geändert", None)
            p = self._pill(text, wirkung)
            p.HorizontalAlignment = HorizontalAlignment.Center
            p.Margin = Thickness(0, 6, 0, 0)
            self.verlauf.Children.Add(p)
            self.verlauf.Children.Add(self._wer(wer, HorizontalAlignment.Center))
        text = e["daten"].get("text") or e["daten"].get("kommentar")
        if text:
            b = Border()
            b.Background = pinsel("#E6F1FB" if eigen else "#F1EFE8")
            b.CornerRadius = System_CornerRadius(8)
            b.Padding = Thickness(8, 4, 8, 4)
            b.Margin = Thickness(30 if eigen else 0, 6, 0 if eigen else 30, 0)
            b.HorizontalAlignment = HorizontalAlignment.Right if eigen else HorizontalAlignment.Left
            t = TextBlock()
            t.Text = text
            t.TextWrapping = TextWrapping.Wrap
            b.Child = t
            self.verlauf.Children.Add(b)
            if e["art"] == "nachricht":
                self.verlauf.Children.Add(self._wer(wer, HorizontalAlignment.Right if eigen else HorizontalAlignment.Left))

    def _wer(self, text, ausrichtung):
        t = TextBlock()
        t.Text = text
        t.FontSize = 10.5
        t.Foreground = pinsel("#888780")
        t.HorizontalAlignment = ausrichtung
        return t

    # ------------------------------------------------------------ Aktionen

    def _viewer(self):
        from . import viewer_start
        try:
            viewer_start.oeffnen(self.einst["projektordner"])
        except Exception as e:
            self.meldung.Text = "Viewer konnte nicht gestartet werden: %s" % e

    def _objekt(self):
        return self.zustand.objekte.get(self.auswahl) if self.auswahl else None

    def _schreiben(self, art, daten):
        o = self._objekt()
        if o is None:
            return
        try:
            self.ablage.schreibe(art, o.id, daten)
        except Exception as e:
            self.meldung.Text = "Speichern fehlgeschlagen: %s" % e
            return
        self.kommentar.Text = ""
        self.laden(True)

    def _entscheiden(self, wert):
        o = self._objekt()
        text = (self.kommentar.Text or "").strip()
        if wert == "abgelehnt" and not text:
            self.meldung.Text = "Bitte einen Grund für die Ablehnung angeben."
            return
        kontext = dict((m, v["aktuell"]["hash"]) for m, v in self.zustand.modelle.items())
        self._schreiben("status", {"wert": wert, "geometrie_hash": o.geometrie_hash,
                                   "kommentar": text or None, "kontext": kontext})

    def _weitere(self, sender, args):
        i = self.weitere.SelectedIndex
        if i <= 0:
            return
        name = self.weitere.SelectedItem
        self.weitere.SelectedIndex = 0
        sid = next((s["id"] for s in self.projekt.status if s["name"] == name), None)
        if sid:
            self._entscheiden(sid)

    def _senden(self):
        text = (self.kommentar.Text or "").strip()
        if not text:
            self.meldung.Text = "Bitte zuerst eine Nachricht schreiben."
            return
        self._schreiben("nachricht", {"text": text})

    def _erneut(self):
        o = self._objekt()
        self._schreiben("eingereicht", {"objekt": o.daten, "runde": o.runden[-1] if o.runden else None})

    def _revit(self, funktion):
        o = self._objekt()
        if o is None:
            return
        objekt = dict(o.daten)
        einst = self.einst
        fenster = self

        def aufgabe(uiapp):
            ergebnis = funktion(uiapp, objekt, einst)
            if isinstance(ergebnis, tuple) and not ergebnis[0]:
                fenster.meldung.Text = ("Das Modell „%s“ ist hier nicht verknüpft – Lage ist evtl. verschoben."
                                        % objekt.get("revit_modell"))
            elif ergebnis is False:
                fenster.meldung.Text = "Der Durchbruch liegt in einem anderen Modell und kann hier nicht ausgewählt werden."

        self._handler.aufgabe = aufgabe
        self._ereignis.Raise()


def System_CornerRadius(r):
    from System.Windows import CornerRadius
    return CornerRadius(r)


def zeigen(einst):
    fenster = PruefManager(einst)
    fenster.show()
    return fenster
