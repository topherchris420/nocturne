"""`nocturne app`: the restoration planner in a browser, served from this computer only.

    nocturne app                      # start with the examples or a blank project
    nocturne app my-district.json     # open (and save back to) a project file

The page edits a project in forms and tables (places and targets, weather and
surface conditions, sources and their options, the light each contributes),
checks it as you type, finds the plan, and writes the printable brief. The
planning, checking and report code is the same Python the command line runs.

Nothing leaves the computer: the server listens on 127.0.0.1 only, answers
only requests that carry this session's random token and a local Host header
(so a web page elsewhere cannot drive it), and can write only the one file it
was started with, keeping the previous version as a .bak beside it. It sends
no commands to lights.
"""
from __future__ import annotations

import json
import os
import secrets
import shutil
import stat
import sys
import tempfile
import threading
import webbrowser
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from .restore import ProjectError, check, read_project, solve

HERE = Path(__file__).resolve().parent
PAGE = HERE / "planner.html"
EXAMPLES = HERE.parent / "examples" / "restoration"
MAX_BODY = 5 * 1024 * 1024
CSP = ("default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; img-src 'self' data:; "
       "connect-src 'self'; frame-src blob:; base-uri 'none'; form-action 'none'")


def blank_project():
    """The smallest project the planner accepts, ready to be filled in."""
    return {"schema_version": 2, "title": "New restoration plan", "synthetic": False,
            "evidence": "Say where every number comes from: measurements, quotations, owner letters, engineering reviews.",
            "budget_usd": 0,
            "receptors": [{"id": "place-1", "label": "Observation point 1", "target_mcd_m2": 1.0}],
            "sources": [{"id": "source-1", "label": "Source 1", "owner": "Owner to be confirmed", "authorized": False,
                         "minimum_service_fraction": 1,
                         "options": [{"id": "option-1", "label": "Option 1", "cost_usd": 0, "service_fraction": 1,
                                      "reviewed": False, "remaining_fraction": {"typical": 1},
                                      "evidence": "Describe the measurement or calculation behind this effect."}]}],
            "scenarios": [{"id": "typical", "label": "Typical clear night", "unmanaged_mcd_m2": {"place-1": 0},
                           "contributions_mcd_m2": {"source-1": {"place-1": 0}}}]}


def examples():
    """id -> (title, loader) for the bundled examples that exist in this installation."""
    out = {"blank": ("Blank project", blank_project)}
    district = EXAMPLES / "district.json"
    if district.exists():
        out["district"] = ("Example: invented district (fixed fractions)", lambda: read_project(district))
    physical = EXAMPLES / "physical-district.json"
    if physical.exists():
        def derived():
            from .derive import derive
            return derive(read_project(physical))
        out["derived"] = ("Example: district derived from geometry, haze and snow", derived)
    return out


def _load(path):
    """A project from disk; a physical district is derived (and must be saved under a new name)."""
    raw = read_project(path)
    if isinstance(raw, dict) and "schema" in raw:
        from .derive import derive
        return derive(raw), (f"{path.name} is a physical district: the coefficients were derived from it. "
                             "Download the derived project to keep it; Save is off so the physical file is not replaced.")
    return raw, ""


def save_atomically(path, project):
    """Replace `path` with the project, keeping the previous version as path.bak."""
    text = json.dumps(project, indent=2, allow_nan=False) + "\n"
    fd, tmp = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            stream.write(text)
        # mkstemp makes the file private (0600); the saved project keeps the original's permissions.
        os.chmod(tmp, stat.S_IMODE(os.stat(path).st_mode) if path.exists() else 0o644)
        backup = None
        if path.exists():
            backup = path.with_name(path.name + ".bak")
            shutil.copy2(path, backup)
        os.replace(tmp, path)
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise
    return backup


class Session:
    def __init__(self, path=None):
        self.token = secrets.token_urlsafe(24)
        self.path = Path(path).resolve() if path else None
        self.project, self.notice, self.writable = None, "", False
        if self.path is not None:
            if self.path.exists():
                self.project, self.notice = _load(self.path)
                self.writable = not self.notice
            else:
                self.project, self.writable = blank_project(), True
                self.notice = f"{self.path.name} does not exist yet: Save will create it."


def make_handler(session, port_box):
    class Handler(BaseHTTPRequestHandler):
        server_version = "Nocturne"
        sys_version = ""

        def log_message(self, *args):                      # keep the terminal for the URL and errors
            pass

        def _send(self, status, body, content_type="application/json; charset=utf-8"):
            data = body if isinstance(body, bytes) else (
                json.dumps(body, allow_nan=False).encode() if not isinstance(body, str) else body.encode())
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header("Content-Security-Policy", CSP)
            self.end_headers()
            self.wfile.write(data)

        def _local(self):
            host = self.headers.get("Host", "")
            return host in (f"127.0.0.1:{port_box[0]}", f"localhost:{port_box[0]}")

        def _authorized(self):
            return self._local() and secrets.compare_digest(self.headers.get("X-Nocturne-Token", ""), session.token)

        def do_GET(self):
            if not self._local():
                return self._send(HTTPStatus.FORBIDDEN, {"error": "unexpected Host"})
            route = self.path.split("?", 1)[0]
            if route in ("/", "/index.html"):
                return self._send(HTTPStatus.OK, PAGE.read_bytes(), "text/html; charset=utf-8")
            if route == "/tonight":
                return self._send(HTTPStatus.OK, (HERE / "tonight.html").read_bytes(), "text/html; charset=utf-8")
            if not self._authorized():
                return self._send(HTTPStatus.FORBIDDEN, {"error": "missing or wrong session token"})
            if route == "/api/session":
                return self._send(HTTPStatus.OK, {
                    "file": str(self.path_name()), "writable": session.writable, "notice": session.notice,
                    "project": session.project, "examples": [{"id": k, "title": t} for k, (t, _) in examples().items()]})
            if route in ("/api/tonight/blank", "/api/tonight/example"):
                from .tonight import blank_project, example_project
                return self._send(HTTPStatus.OK, example_project() if route.endswith("example") else blank_project())
            if route.startswith("/api/example/"):
                found = examples().get(route.rsplit("/", 1)[1])
                if not found:
                    return self._send(HTTPStatus.NOT_FOUND, {"error": "no such example"})
                return self._send(HTTPStatus.OK, found[1]())
            return self._send(HTTPStatus.NOT_FOUND, {"error": "not found"})

        def path_name(self):
            return session.path.name if session.path else ""

        def do_POST(self):
            if not self._authorized():
                return self._send(HTTPStatus.FORBIDDEN, {"error": "missing or wrong session token"})
            if self.headers.get("Content-Type", "").split(";")[0].strip() != "application/json":
                return self._send(HTTPStatus.UNSUPPORTED_MEDIA_TYPE, {"error": "send JSON"})
            try:
                length = int(self.headers.get("Content-Length", "0"))
            except ValueError:
                length = -1
            if not 0 < length <= MAX_BODY:
                return self._send(HTTPStatus.REQUEST_ENTITY_TOO_LARGE, {"error": f"body must be 1 byte to {MAX_BODY:,} bytes"})
            try:
                body = json.loads(self.rfile.read(length).decode("utf-8"))
            except (UnicodeDecodeError, ValueError):
                return self._send(HTTPStatus.BAD_REQUEST, {"error": "body is not JSON"})
            if not isinstance(body, dict):
                return self._send(HTTPStatus.BAD_REQUEST, {"error": "body must be an object"})
            route = self.path.split("?", 1)[0]
            try:
                if route == "/api/tonight":
                    from .tonight import plan, render, calendar, receipt_template, read_receipts, reconcile
                    project = body.get("project")
                    result = plan(project)
                    response = {"plan": result, "report": render(result), "calendar": calendar(result),
                                "receipts_csv": receipt_template(result)}
                    if "receipts_csv" in body:
                        if not isinstance(body["receipts_csv"], str):
                            raise ValueError("receipts_csv: expected CSV text")
                        response["completion"] = reconcile(project, read_receipts(body["receipts_csv"]))
                    return self._send(HTTPStatus.OK, response)
                if route == "/api/check":
                    return self._send(HTTPStatus.OK, check(body.get("project")))
                if route in ("/api/solve", "/api/report"):
                    budget = body.get("budget_usd")
                    result = solve(body.get("project"), budget)
                    if route == "/api/solve":
                        return self._send(HTTPStatus.OK, result)
                    from .restoration_report import render
                    return self._send(HTTPStatus.OK, render(result), "text/html; charset=utf-8")
                if route == "/api/derive":
                    from .derive import derive
                    return self._send(HTTPStatus.OK, derive(body.get("physical")))
                if route == "/api/save":
                    if not session.writable:
                        return self._send(HTTPStatus.CONFLICT, {"error": "this session has no file to save to: download instead"})
                    if not isinstance(body.get("project"), dict):
                        return self._send(HTTPStatus.BAD_REQUEST, {"error": "nothing to save"})
                    backup = save_atomically(session.path, body["project"])
                    session.project = body["project"]
                    return self._send(HTTPStatus.OK, {"saved": session.path.name,
                                                      "backup": backup.name if backup else None})
            except ProjectError as e:
                return self._send(HTTPStatus.UNPROCESSABLE_ENTITY,
                                  {"error": "the project has problems", "problems": [{"path": p, "message": m} for p, m in e.problems]})
            except (ValueError, TypeError, OSError) as e:
                return self._send(HTTPStatus.BAD_REQUEST, {"error": str(e) or type(e).__name__})
            return self._send(HTTPStatus.NOT_FOUND, {"error": "not found"})

    return Handler


def start(path=None, port=0, page="planner"):
    """Start the server in a background thread; returns (server, url, session)."""
    session = Session(path)
    port_box = [port]
    server = ThreadingHTTPServer(("127.0.0.1", port), make_handler(session, port_box))
    server.daemon_threads = True
    port_box[0] = server.server_address[1]
    threading.Thread(target=server.serve_forever, daemon=True).start()
    route = "tonight" if page == "tonight" else ""
    return server, f"http://127.0.0.1:{port_box[0]}/{route}#token={session.token}", session


def run(path=None, port=0, open_browser=True, page="planner"):
    if page == "tonight" and path is not None:
        raise ValueError("open DC Tonight with --tonight, then use Open project in the page")
    server, url, session = start(path, port, page)
    print("Nocturne planner is running on this computer only.", file=sys.stderr)
    print(f"Open: {url}", file=sys.stderr)
    if session.path:
        print(f"File: {session.path}" + ("" if session.writable else " (read only in this session)"), file=sys.stderr)
    print("Press Ctrl+C here to stop.", file=sys.stderr)
    if open_browser:
        webbrowser.open(url)
    try:
        threading.Event().wait()
    except KeyboardInterrupt:
        pass
    finally:
        server.shutdown()
    return 0
