#!/usr/bin/env python3
"""Local server for the deck site: static files plus the wants & trades API.

Mirrors web/worker.js — same routes, same validation, same JSON shapes — so the
site behaves on http://127.0.0.1:8000 the way it does on decks.otl.fi. Workers
KV is a JSON file here (WANTS_STORE, default web/wants.local.json, gitignored),
and the edit password comes from EDIT_PASSWORD.

Usage:
    python3 web/devserver.py [port]        # or: npm run preview
"""
import hmac
import json
import os
import re
import sys
import threading
import uuid
from datetime import datetime, timezone
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import unquote, urlparse

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PUBLIC = os.path.join(ROOT, "web", "public")
STORE = os.environ.get("WANTS_STORE") or os.path.join(ROOT, "web", "wants.local.json")
# The deployed password lives in wrangler.toml; this default only makes the
# local server usable without exporting anything first.
PASSWORD = os.environ.get("EDIT_PASSWORD", "sininenkollari0726")

MAX_ITEMS = 500
LISTS = {"want", "trade"}
# Both stored URLs are rendered by the browser, so they are pinned to Scryfall.
IMAGE_HOST = re.compile(r"^https://([a-z0-9-]+\.)*scryfall\.io/", re.I)
PAGE_HOST = re.compile(r"^https://([a-z0-9-]+\.)*scryfall\.com/", re.I)

_lock = threading.Lock()


def _text(value, limit):
    return value.strip()[:limit] if isinstance(value, str) else ""


def _url(value, pattern):
    raw = _text(value, 500)
    return raw if pattern.match(raw) else ""


def _quantity(value, fallback):
    try:
        return max(1, min(99, round(float(value))))
    except (TypeError, ValueError):
        return fallback


def sanitize(body, base=None):
    """Keep only the stored fields; absent ones keep the value they had."""
    base = base or {}
    name = _text(body.get("name"), 150) or base.get("name", "")
    if not name:
        return None

    def keep(field, clean, fallback=""):
        if field in body:
            return clean(body[field])
        return base.get(field, fallback)

    return {
        "id": base.get("id"),
        "added": base.get("added"),
        "name": name,
        "list": body["list"] if body.get("list") in LISTS else base.get("list", "want"),
        "count": _quantity(body["count"], base.get("count", 1)) if "count" in body
                 else base.get("count", 1),
        "note": keep("note", lambda v: _text(v, 200)),
        "image": keep("image", lambda v: _url(v, IMAGE_HOST)),
        "set": keep("set", lambda v: _text(v, 10)),
        "number": keep("number", lambda v: _text(v, 10)),
        "mana_cost": keep("mana_cost", lambda v: _text(v, 60)),
        "type_line": keep("type_line", lambda v: _text(v, 150)),
        "price_eur": keep("price_eur", lambda v: _text(v, 12)),
        "scryfall_uri": keep("scryfall_uri", lambda v: _url(v, PAGE_HOST)),
    }


def read_store():
    try:
        with open(STORE, encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        data = {}
    items = data.get("items")
    return {"items": items if isinstance(items, list) else [],
            "updated": data.get("updated") if isinstance(data.get("updated"), str) else None}


def write_store(items):
    store = {"items": items, "updated": datetime.now(timezone.utc).isoformat()}
    os.makedirs(os.path.dirname(STORE) or ".", exist_ok=True)
    tmp = STORE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(store, fh, indent=2)
    os.replace(tmp, STORE)
    return store


class Handler(SimpleHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    # --- plumbing ---

    def send_json(self, data, status=200):
        payload = json.dumps(data).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(payload)

    def read_body(self):
        """Read (and always consume) the request body.

        Every API path calls this, including the ones that answer 401 or 404
        without looking at it: on a keep-alive connection an unread body is
        parsed as the start of the next request.
        """
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length) if length > 0 else b""
        try:
            body = json.loads(raw or b"{}")
        except ValueError:
            return {}
        return body if isinstance(body, dict) else {}

    def authorized(self):
        given = self.headers.get("X-Edit-Password") or ""
        return bool(PASSWORD) and hmac.compare_digest(given, PASSWORD)

    def api_path(self):
        path = urlparse(self.path).path
        is_api = path in ("/api/wants", "/api/unlock") or path.startswith("/api/wants/")
        return path if is_api else None

    # --- routes ---

    def do_GET(self):
        path = self.api_path()
        if path is None:
            return super().do_GET()
        self.handle_api(path, "GET")

    def do_HEAD(self):
        if self.api_path() is None:
            return super().do_HEAD()
        self.send_json({"error": "method not allowed"}, 405)

    def do_POST(self):
        self.route_api("POST")

    def do_PATCH(self):
        self.route_api("PATCH")

    def do_DELETE(self):
        self.route_api("DELETE")

    def route_api(self, method):
        path = self.api_path()
        if path is None:
            return self.send_json({"error": "not found"}, 404)
        self.handle_api(path, method)

    def handle_api(self, path, method):
        body = self.read_body()
        if not (path == "/api/wants" and method == "GET") and not self.authorized():
            return self.send_json({"error": "wrong password"}, 401)
        if path == "/api/unlock":
            return self.send_json({"ok": True}) if method == "POST" \
                else self.send_json({"error": "not found"}, 404)

        with _lock:
            if path == "/api/wants":
                return self.collection(method, body)
            self.entry(unquote(path[len("/api/wants/"):]), method, body)

    def collection(self, method, body):
        store = read_store()
        if method == "GET":
            return self.send_json(store)
        if method != "POST":
            return self.send_json({"error": "method not allowed"}, 405)
        if len(store["items"]) >= MAX_ITEMS:
            return self.send_json({"error": f"list is full ({MAX_ITEMS} entries)"}, 409)
        item = sanitize(body)
        if item is None:
            return self.send_json({"error": "a card name is required"}, 400)
        item["id"] = str(uuid.uuid4())
        item["added"] = datetime.now(timezone.utc).isoformat()
        # Same card on the same list is one row with a bigger count.
        same = next((i for i in store["items"] if i.get("list") == item["list"]
                     and str(i.get("name", "")).lower() == item["name"].lower()), None)
        if same:
            same["count"] = _quantity(same.get("count", 1) + item["count"],
                                      same.get("count", 1))
            write_store(store["items"])
            return self.send_json({"item": same})
        store["items"].append(item)
        write_store(store["items"])
        self.send_json({"item": item}, 201)

    def entry(self, entry_id, method, body):
        store = read_store()
        at = next((n for n, i in enumerate(store["items"]) if i.get("id") == entry_id), -1)
        if at < 0:
            return self.send_json({"error": "no such entry"}, 404)
        if method == "PATCH":
            item = sanitize(body, store["items"][at])
            if item is None:
                return self.send_json({"error": "a card name is required"}, 400)
            store["items"][at] = item
            write_store(store["items"])
            return self.send_json({"item": item})
        if method == "DELETE":
            store["items"].pop(at)
            write_store(store["items"])
            return self.send_json({"ok": True})
        self.send_json({"error": "method not allowed"}, 405)


def main():
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8000
    server = ThreadingHTTPServer(("127.0.0.1", port),
                                 partial(Handler, directory=PUBLIC))
    print(f"deck site on http://127.0.0.1:{port}/  (wants store: {STORE})")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
