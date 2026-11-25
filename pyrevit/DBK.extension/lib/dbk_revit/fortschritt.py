# -*- coding: utf-8 -*-
"""Fortschrittsfenster für lange Abläufe (Einreichen, Modell exportieren).

Läuft im Revit-Hauptthread (ExternalEvent). Damit sich das Fenster trotzdem
aktualisiert, wird nach jeder Änderung die WPF-Nachrichtenschleife kurz abgearbeitet.
Während eines einzelnen Revit-Exports kann Revit selbst keinen Zwischenstand melden –
dann steht dort „läuft …“, und Revit zeigt unten seinen eigenen Fortschrittsbalken.
"""
from __future__ import unicode_literals

import time

from System import Action
from System.Windows import (Window, Thickness, WindowStartupLocation, SizeToContent, FontWeights, ResizeMode,
                            TextWrapping, VerticalAlignment)
from System.Windows.Controls import StackPanel, TextBlock, Button, ProgressBar, DockPanel, Dock, Border
from System.Windows.Media import SolidColorBrush, ColorConverter
from System.Windows.Threading import Dispatcher, DispatcherPriority


def _p(f):
    return SolidColorBrush(ColorConverter.ConvertFromString(f))


ROT, GRAU, TEXT, GRUEN = _p("#be0a26"), _p("#71717a"), _p("#18181b"), _p("#3B6D11")


class Abgebrochen(Exception):
    pass


class Fortschritt(object):
    """Mit ``with Fortschritt(titel, schritte) as f:`` verwenden; ``f.schritt(i)``, ``f.detail(text)``."""

    def __init__(self, titel, schritte):
        self.titel = titel
        self.schritte = list(schritte)
        self.abbrechen = False
        self._start = time.time()
        self._schritt_start = time.time()
        self._aktuell = -1
        self._bau()

    def _bau(self):
        w = Window()
        w.Title = self.titel
        w.Width = 460
        w.SizeToContent = SizeToContent.Height
        w.WindowStartupLocation = WindowStartupLocation.CenterScreen
        w.ResizeMode = ResizeMode.NoResize
        w.Topmost = True
        w.FontFamily = __import__("System").Windows.Media.FontFamily("Segoe UI")
        w.Background = _p("#fafafa")
        rahmen = StackPanel()
        rahmen.Margin = Thickness(20)
        kopf = TextBlock()
        kopf.Text = self.titel
        kopf.FontSize = 16
        kopf.FontWeight = FontWeights.SemiBold
        kopf.Margin = Thickness(0, 0, 0, 12)
        rahmen.Children.Add(kopf)
        self._zeilen = []
        for s in self.schritte:
            t = TextBlock()
            t.Text = "○   " + s
            t.Foreground = GRAU
            t.Margin = Thickness(0, 3, 0, 3)
            rahmen.Children.Add(t)
            self._zeilen.append(t)
        self._balken = ProgressBar()
        self._balken.Height = 6
        self._balken.Margin = Thickness(0, 14, 0, 6)
        self._balken.Foreground = ROT
        self._balken.IsIndeterminate = True
        rahmen.Children.Add(self._balken)
        self._detail = TextBlock()
        self._detail.Foreground = GRAU
        self._detail.TextWrapping = TextWrapping.Wrap
        rahmen.Children.Add(self._detail)
        unten = DockPanel()
        unten.Margin = Thickness(0, 14, 0, 0)
        self._zeit = TextBlock()
        self._zeit.Foreground = GRAU
        self._zeit.VerticalAlignment = VerticalAlignment.Center
        self._knopf = Button()
        self._knopf.Content = "Abbrechen"
        self._knopf.Padding = Thickness(12, 4, 12, 4)
        self._knopf.ToolTip = "Bricht nach dem laufenden Schritt ab (ein laufender Revit-Export lässt sich nicht unterbrechen)"
        self._knopf.Click += self._abbrechen
        DockPanel.SetDock(self._knopf, Dock.Right)
        unten.Children.Add(self._knopf)
        unten.Children.Add(self._zeit)
        rahmen.Children.Add(unten)
        w.Content = rahmen
        self.fenster = w

    def __enter__(self):
        self.fenster.Show()
        self._pumpen()
        return self

    def __exit__(self, typ, wert, tb):
        if typ is None:
            self._knopf.Content = "Schließen"
            self._detail.Text = "Fertig nach %s." % self._dauer(time.time() - self._start)
            self._balken.IsIndeterminate = False
            self._balken.Value = 100
            self._knopf.Click -= self._abbrechen
            self._knopf.Click += lambda s, a: self.fenster.Close()
            self.fenster.Topmost = False
        else:
            self._detail.Text = ("Abgebrochen." if typ is Abgebrochen else "Fehler: %s" % wert)
            self._detail.Foreground = ROT
            if 0 <= self._aktuell < len(self._zeilen):
                self._zeilen[self._aktuell].Text = "✗   " + self.schritte[self._aktuell]
                self._zeilen[self._aktuell].Foreground = ROT
            self._knopf.Content = "Schließen"
            self._knopf.Click -= self._abbrechen
            self._knopf.Click += lambda s, a: self.fenster.Close()
        self._pumpen()
        return False

    def _abbrechen(self, sender, args):
        self.abbrechen = True
        self._knopf.IsEnabled = False
        self._knopf.Content = "Wird abgebrochen …"

    @staticmethod
    def _dauer(s):
        return "%d:%02d min" % (int(s) // 60, int(s) % 60)

    def _pumpen(self):
        self._zeit.Text = "Gesamt %s" % self._dauer(time.time() - self._start)
        Dispatcher.CurrentDispatcher.Invoke(DispatcherPriority.Background, Action(lambda: None))

    def pruefen(self):
        """Zwischen Schritten aufrufen: wirft Abgebrochen, wenn der Benutzer abgebrochen hat."""
        self._pumpen()
        if self.abbrechen:
            raise Abgebrochen()

    def schritt(self, i, detail=""):
        self.pruefen()
        for j in range(len(self._zeilen)):
            if j < i:
                self._zeilen[j].Text = "✓   " + self.schritte[j]
                self._zeilen[j].Foreground = GRUEN
            elif j == i:
                self._zeilen[j].Text = "●   " + self.schritte[j]
                self._zeilen[j].Foreground = TEXT
        self._aktuell = i
        self._schritt_start = time.time()
        self._balken.IsIndeterminate = True
        self._detail.Text = detail
        self._pumpen()

    def ueberspringen(self, i, grund):
        self._zeilen[i].Text = "–   %s (%s)" % (self.schritte[i], grund)
        self._zeilen[i].Foreground = GRAU
        self._pumpen()

    def detail(self, text):
        self._detail.Text = text
        self._pumpen()

    def menge(self, aktuell, gesamt, einheit=""):
        """Fortschritt innerhalb eines Schritts (z. B. kopierte MB)."""
        if gesamt:
            self._balken.IsIndeterminate = False
            self._balken.Maximum = gesamt
            self._balken.Value = aktuell
        if einheit == "MB":
            self._detail.Text = "%.0f von %.0f MB" % (aktuell / 1e6, gesamt / 1e6)
        elif einheit:
            self._detail.Text = "%d von %d %s" % (aktuell, gesamt, einheit)
        self._pumpen()

    def fertig(self):
        for j in range(len(self._zeilen)):
            if not self._zeilen[j].Text.startswith("–"):
                self._zeilen[j].Text = "✓   " + self.schritte[j]
                self._zeilen[j].Foreground = GRUEN
        self._pumpen()
