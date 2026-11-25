# -*- coding: utf-8 -*-
"""Lokaler Entwicklungs-Server für die Web-App.

Liefert ``web/`` aus und stellt einen Projektordner unter ``/projekt/`` bereit
(lesen, auflisten, neue Dateien schreiben). Damit lässt sich die Web-App auch
ohne die Ordner-Auswahl des Browsers testen.

    py werkzeuge/devserver.py --projekt testdaten/demo --port 8765

Nur für die Entwicklung: lauscht ausschließlich auf 127.0.0.1.
"""
from __future__ import print_function, unicode_literals

import argparse
import json
import mimetypes
import os
import posixpath
import sys

try:
    from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
    from urllib.parse import unquote, urlparse
except ImportError:  # pragma: no cover
    sys.exit("Bitte mit Python 3 starten.")

WURZEL = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WEB = os.path.join(WURZEL, "web")
SCHREIBBAR = ("ereignisse/", "modelle/", "plaene/", "pruefsets/")

mimetypes.add_type("application/javascript", ".js")
mimetypes.add_type("application/javascript", ".mjs")
mimetypes.add_type("application/wasm", ".wasm")


def sicherer_pfad(basis, relativ):
    relativ = posixpath.normpath(unquote(relativ)).lstrip("/")
    if relativ.startswith("..") or os.path.isabs(relativ):
        return None
    ziel = os.path.abspath(os.path.join(basis, *relativ.split("/")))
    if not (ziel == basis or ziel.startswith(basis + os.sep)):
        return None
    return ziel


class Handler(SimpleHTTPRequestHandler):
    projekt = None

    def __init__(self, *args, **kwargs):
        SimpleHTTPRequestHandler.__init__(self, *args, directory=WEB, **kwargs)

    def end_headers(self):
        self.send_header("Cache-Control", "no-store")
        SimpleHTTPRequestHandler.end_headers(self)

    def _json(self, code, daten):
        roh = json.dumps(daten, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(roh)))
        self.end_headers()
        self.wfile.write(roh)

    def do_GET(self):
        url = urlparse(self.path)
        if url.path == "/api/liste":
            return self._liste()
        if url.path == "/api/info":
            return self._json(200, {"projekt": self.projekt})
        if url.path.startswith("/projekt/"):
            return self._projektdatei(url.path[len("/projekt/"):])
        return SimpleHTTPRequestHandler.do_GET(self)

    def _liste(self):
        dateien = []
        for wurzel, _ordner, namen in os.walk(self.projekt):
            for name in namen:
                if name.endswith(".tmp"):
                    continue
                voll = os.path.join(wurzel, name)
                rel = os.path.relpath(voll, self.projekt).replace(os.sep, "/")
                st = os.stat(voll)
                dateien.append({"pfad": rel, "groesse": st.st_size, "geaendert": st.st_mtime})
        self._json(200, {"dateien": dateien})

    def _projektdatei(self, rel):
        ziel = sicherer_pfad(self.projekt, rel)
        if not ziel or not os.path.isfile(ziel):
            return self._json(404, {"fehler": "nicht gefunden"})
        with open(ziel, "rb") as f:
            roh = f.read()
        self.send_response(200)
        self.send_header("Content-Type", mimetypes.guess_type(ziel)[0] or "application/octet-stream")
        self.send_header("Content-Length", str(len(roh)))
        self.end_headers()
        self.wfile.write(roh)

    def do_PUT(self):
        url = urlparse(self.path)
        if not url.path.startswith("/projekt/"):
            return self._json(404, {"fehler": "nicht gefunden"})
        rel = posixpath.normpath(unquote(url.path[len("/projekt/"):]))
        if not rel.startswith(SCHREIBBAR):
            return self._json(403, {"fehler": "hier darf nicht geschrieben werden"})
        ziel = sicherer_pfad(self.projekt, rel)
        if not ziel:
            return self._json(403, {"fehler": "ungültiger Pfad"})
        if os.path.exists(ziel):
            return self._json(409, {"fehler": "Datei existiert bereits"})
        laenge = int(self.headers.get("Content-Length", "0"))
        roh = self.rfile.read(laenge)
        if not os.path.isdir(os.path.dirname(ziel)):
            os.makedirs(os.path.dirname(ziel))
        with open(ziel + ".tmp", "wb") as f:
            f.write(roh)
        os.replace(ziel + ".tmp", ziel)
        self._json(201, {"pfad": rel})

    def log_message(self, fmt, *args):
        if "/api/liste" not in (str(args[0]) if args else ""):
            sys.stderr.write("%s\n" % (fmt % args))


def main():
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--projekt", required=True, help="Projektordner (wird angelegt, falls nicht vorhanden)")
    p.add_argument("--port", type=int, default=8765)
    a = p.parse_args()
    Handler.projekt = os.path.abspath(a.projekt)
    if not os.path.isdir(Handler.projekt):
        os.makedirs(Handler.projekt)
    server = ThreadingHTTPServer(("127.0.0.1", a.port), Handler)
    print("Web-App:     http://127.0.0.1:%d/" % a.port)
    print("Projektordner: %s" % Handler.projekt)
    server.serve_forever()


if __name__ == "__main__":
    main()
