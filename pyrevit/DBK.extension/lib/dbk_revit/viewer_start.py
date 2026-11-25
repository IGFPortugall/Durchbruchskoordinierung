# -*- coding: utf-8 -*-
"""Startet den lokalen Viewer-Server für den eigenen Projektordner und öffnet den Browser.

Läuft auf einem Port schon ein Server für denselben Ordner, wird nur der Browser
geöffnet. Sonst wird ein freier Port ab 8766 gesucht. Nur Python-Standardbibliothek
(socket, urllib2) – keine .NET-Netzwerkbibliotheken, die in Revit nicht geladen sind.
"""
from __future__ import unicode_literals

import json
import os
import socket
import time
import webbrowser

try:
    from urllib2 import urlopen          # IronPython 2.7
except ImportError:                      # CPython 3
    from urllib.request import urlopen

from System.Diagnostics import Process, ProcessStartInfo

from . import REPO

SERVER = os.path.join(REPO, "werkzeuge", "devserver.py")


def _belegt(port):
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(0.3)
    try:
        return s.connect_ex(("127.0.0.1", port)) == 0
    except Exception:
        return False
    finally:
        s.close()


def _info(port):
    """Projektordner des Servers auf diesem Port oder None (kein bzw. fremder Server)."""
    if not _belegt(port):
        return None
    try:
        antwort = urlopen("http://127.0.0.1:%d/api/info" % port, timeout=2)
        return json.loads(antwort.read().decode("utf-8"))
    except Exception:
        return {}


def _gleich(a, b):
    return os.path.normcase(os.path.normpath(a or "")) == os.path.normcase(os.path.normpath(b or ""))


def oeffnen(projektordner):
    for port in range(8766, 8786):
        info = _info(port)
        if info is not None and not _gleich(info.get("projekt"), projektordner):
            continue                      # Port belegt – anderer Ordner oder fremder Dienst
        if info is None:
            psi = ProcessStartInfo("py", '"%s" --projekt "%s" --port %d' % (SERVER, projektordner, port))
            psi.UseShellExecute = False
            psi.CreateNoWindow = True
            psi.WorkingDirectory = REPO
            Process.Start(psi)
            for _ in range(40):
                time.sleep(0.25)
                if _belegt(port):
                    break
            else:
                raise RuntimeError("Der Viewer-Server startet nicht. Ist Python 3 (Befehl „py“) installiert?")
        url = "http://127.0.0.1:%d/" % port
        webbrowser.open(url)
        return url
    raise RuntimeError("Kein freier Port zwischen 8766 und 8785 gefunden.")
