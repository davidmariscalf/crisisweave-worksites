from __future__ import annotations

import argparse
import json
import os
import sqlite3
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

STATES = ("requested", "triaged", "ready", "assigned", "in_progress", "completed", "cancelled")
PRIORITIES = ("urgent", "high", "normal", "low")
WORK_TYPES = ("debris_removal", "muck_out", "tree_removal", "tarping", "gutting", "delivery", "assessment", "other")
TRANSITIONS = {
    "requested": {"triaged", "cancelled"},
    "triaged": {"ready", "cancelled"},
    "ready": {"cancelled"},
    "assigned": {"in_progress", "cancelled"},
    "in_progress": {"completed", "cancelled"},
    "completed": set(),
    "cancelled": set(),
}
LOCKED_IMPORT_STATES = {"assigned", "in_progress", "completed", "cancelled"}


def now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def validate_worksite(w: dict[str, Any]) -> None:
    required = ("id", "title", "work_type", "state", "priority", "people_needed", "skills", "hazards", "area", "geometry", "source")
    missing = [k for k in required if k not in w]
    if missing:
        raise ValueError("missing required fields: " + ", ".join(missing))
    if not isinstance(w["id"], str) or not w["id"].strip():
        raise ValueError("id must be a non-empty string")
    if not isinstance(w["title"], str) or not w["title"].strip():
        raise ValueError("title must be a non-empty string")
    if w["work_type"] not in WORK_TYPES:
        raise ValueError("unsupported work_type")
    if w["state"] not in STATES:
        raise ValueError("unsupported state")
    if w["priority"] not in PRIORITIES:
        raise ValueError("unsupported priority")
    if not isinstance(w["people_needed"], int) or isinstance(w["people_needed"], bool) or not 1 <= w["people_needed"] <= 1000:
        raise ValueError("people_needed must be an integer from 1 to 1000")
    for field in ("skills", "hazards"):
        if not isinstance(w[field], list) or not all(isinstance(x, str) for x in w[field]):
            raise ValueError(f"{field} must be a list of strings")
        if len(set(w[field])) != len(w[field]):
            raise ValueError(f"{field} must not contain duplicates")
    if not isinstance(w["area"], str) or not w["area"].strip():
        raise ValueError("area must be a non-empty string")
    g = w["geometry"]
    if not isinstance(g, dict) or g.get("type") != "Point":
        raise ValueError("geometry must be a GeoJSON Point")
    c = g.get("coordinates")
    if not isinstance(c, list) or len(c) != 2:
        raise ValueError("geometry.coordinates must contain [longitude, latitude]")
    try:
        lon, lat = float(c[0]), float(c[1])
    except (TypeError, ValueError):
        raise ValueError("coordinates must be numeric") from None
    if not (-180 <= lon <= 180 and -90 <= lat <= 90):
        raise ValueError("coordinates outside valid bounds")
    s = w["source"]
    if not isinstance(s, dict) or s.get("type") not in {"request", "assessment", "partner_import", "synthetic"}:
        raise ValueError("source must represent an explicit request, assessment, partner import or synthetic demo")
    if not str(s.get("name") or "").strip() or not str(s.get("source_id") or "").strip():
        raise ValueError("source.name and source.source_id are required")
    if w["state"] == "assigned" and not str(w.get("assigned_team") or "").strip():
        raise ValueError("assigned state requires assigned_team")


class WorksiteStore:
    def __init__(self, db_path: str | Path):
        self.db_path = str(db_path)
        self.init()

    def connect(self) -> sqlite3.Connection:
        con = sqlite3.connect(self.db_path, timeout=10)
        con.row_factory = sqlite3.Row
        con.execute("PRAGMA foreign_keys=ON")
        return con

    def init(self) -> None:
        with self.connect() as con:
            con.executescript("""
            CREATE TABLE IF NOT EXISTS worksites(
                id TEXT PRIMARY KEY,
                payload TEXT NOT NULL,
                state TEXT NOT NULL,
                assigned_team TEXT,
                version INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS audit(
                seq INTEGER PRIMARY KEY AUTOINCREMENT,
                worksite_id TEXT NOT NULL,
                at TEXT NOT NULL,
                actor TEXT NOT NULL,
                action TEXT NOT NULL,
                from_state TEXT,
                to_state TEXT,
                note TEXT,
                details TEXT NOT NULL DEFAULT '{}',
                FOREIGN KEY(worksite_id) REFERENCES worksites(id)
            );
            CREATE INDEX IF NOT EXISTS idx_worksites_state ON worksites(state);
            CREATE INDEX IF NOT EXISTS idx_audit_worksite ON audit(worksite_id,seq);
            """)

    @staticmethod
    def _decode(row: sqlite3.Row) -> dict[str, Any]:
        d = json.loads(row["payload"])
        d.update(
            state=row["state"], assigned_team=row["assigned_team"], version=row["version"],
            created_at=row["created_at"], updated_at=row["updated_at"]
        )
        return d

    def _audit(self, con, wid, actor, action, old_state, new_state, note="", details=None):
        con.execute(
            "INSERT INTO audit(worksite_id,at,actor,action,from_state,to_state,note,details) VALUES(?,?,?,?,?,?,?,?)",
            (wid, now(), actor or "unknown", action, old_state, new_state, note or "", json.dumps(details or {})),
        )

    def upsert(self, w: dict[str, Any], actor: str = "import") -> dict[str, Any]:
        incoming = dict(w)
        incoming.setdefault("assigned_team", None)
        validate_worksite(incoming)
        created = str(incoming.get("created_at") or now())
        updated = now()
        payload = dict(incoming)
        for key in ("state", "assigned_team", "version", "created_at", "updated_at"):
            payload.pop(key, None)

        with self.connect() as con:
            con.execute("BEGIN IMMEDIATE")
            prev = con.execute("SELECT state,assigned_team FROM worksites WHERE id=?", (incoming["id"],)).fetchone()
            if prev:
                old_state = prev["state"]
                locked = old_state in LOCKED_IMPORT_STATES
                state = old_state if locked else incoming["state"]
                assigned_team = prev["assigned_team"] if locked else incoming.get("assigned_team")
                con.execute(
                    "UPDATE worksites SET payload=?,state=?,assigned_team=?,version=version+1,updated_at=? WHERE id=?",
                    (json.dumps(payload, ensure_ascii=False), state, assigned_team, updated, incoming["id"]),
                )
                action = "import_refresh_locked" if locked else "import_update"
                details = {"incoming_state": incoming["state"], "preserved_state": state} if locked else {}
                self._audit(con, incoming["id"], actor, action, old_state, state, details=details)
            else:
                state = incoming["state"]
                con.execute(
                    "INSERT INTO worksites(id,payload,state,assigned_team,created_at,updated_at) VALUES(?,?,?,?,?,?)",
                    (incoming["id"], json.dumps(payload, ensure_ascii=False), state, incoming.get("assigned_team"), created, updated),
                )
                self._audit(con, incoming["id"], actor, "created", None, state)
        return self.get(incoming["id"])

    def get(self, wid: str) -> dict[str, Any]:
        with self.connect() as con:
            row = con.execute("SELECT * FROM worksites WHERE id=?", (wid,)).fetchone()
        if not row:
            raise KeyError(wid)
        return self._decode(row)

    def list(self, state: str | None = None) -> list[dict[str, Any]]:
        with self.connect() as con:
            if state:
                rows = con.execute("SELECT * FROM worksites WHERE state=? ORDER BY updated_at DESC", (state,)).fetchall()
            else:
                rows = con.execute("SELECT * FROM worksites ORDER BY updated_at DESC").fetchall()
        return [self._decode(r) for r in rows]

    def transition(self, wid: str, target: str, actor: str, note: str = "") -> dict[str, Any]:
        if target not in STATES:
            raise ValueError("unknown target state")
        with self.connect() as con:
            con.execute("BEGIN IMMEDIATE")
            row = con.execute("SELECT * FROM worksites WHERE id=?", (wid,)).fetchone()
            if not row:
                raise KeyError(wid)
            current = row["state"]
            if target == "assigned":
                raise ValueError("use assign operation to enter assigned state")
            if target not in TRANSITIONS[current]:
                raise ValueError(f"invalid transition: {current} -> {target}")
            con.execute("UPDATE worksites SET state=?,version=version+1,updated_at=? WHERE id=?", (target, now(), wid))
            self._audit(con, wid, actor, "transition", current, target, note)
        return self.get(wid)

    def assign(self, wid: str, team_id: str, actor: str) -> dict[str, Any]:
        if not str(team_id).strip():
            raise ValueError("team_id is required")
        with self.connect() as con:
            con.execute("BEGIN IMMEDIATE")
            row = con.execute("SELECT * FROM worksites WHERE id=?", (wid,)).fetchone()
            if not row:
                raise KeyError(wid)
            if row["state"] != "ready":
                if row["state"] in {"assigned", "in_progress"}:
                    raise ValueError(f"worksite already allocated to {row['assigned_team'] or 'another team'}")
                raise ValueError(f"worksite must be ready before assignment; current state is {row['state']}")
            con.execute(
                "UPDATE worksites SET state='assigned',assigned_team=?,version=version+1,updated_at=? WHERE id=?",
                (team_id, now(), wid),
            )
            self._audit(con, wid, actor, "assigned", "ready", "assigned", details={"team_id": team_id})
        return self.get(wid)

    def release(self, wid: str, actor: str) -> dict[str, Any]:
        with self.connect() as con:
            con.execute("BEGIN IMMEDIATE")
            row = con.execute("SELECT * FROM worksites WHERE id=?", (wid,)).fetchone()
            if not row:
                raise KeyError(wid)
            if row["state"] != "assigned":
                raise ValueError("only an assigned worksite can be released")
            team = row["assigned_team"]
            con.execute("UPDATE worksites SET state='ready',assigned_team=NULL,version=version+1,updated_at=? WHERE id=?", (now(), wid))
            self._audit(con, wid, actor, "released", "assigned", "ready", details={"team_id": team})
        return self.get(wid)

    def audit(self, wid: str) -> list[dict[str, Any]]:
        with self.connect() as con:
            rows = con.execute("SELECT * FROM audit WHERE worksite_id=? ORDER BY seq", (wid,)).fetchall()
        return [{**dict(r), "details": json.loads(r["details"])} for r in rows]


class APIHandler(BaseHTTPRequestHandler):
    store: WorksiteStore
    token: str | None = None

    def log_message(self, fmt, *args):
        return

    def _json(self, status: int, data: Any) -> None:
        body = json.dumps(data, ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Authorization, Content-Type")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self):
        self._json(204, {})

    def _parts(self) -> list[str]:
        return [p for p in urlparse(self.path).path.split("/") if p]

    def _auth(self) -> bool:
        return not self.token or self.headers.get("Authorization") == f"Bearer {self.token}"

    def _body(self) -> dict[str, Any]:
        n = int(self.headers.get("Content-Length") or 0)
        if n > 100000:
            raise ValueError("request body too large")
        data = json.loads(self.rfile.read(n) if n else b"{}")
        if not isinstance(data, dict):
            raise ValueError("JSON body must be an object")
        return data

    def do_GET(self):
        try:
            parts = self._parts()
            if parts == ["api", "health"]:
                return self._json(200, {"ok": True, "service": "crisisweave-worksites"})
            if parts == ["api", "worksites"]:
                return self._json(200, {"worksites": self.store.list()})
            if len(parts) == 3 and parts[:2] == ["api", "worksites"]:
                return self._json(200, self.store.get(parts[2]))
            if len(parts) == 4 and parts[:2] == ["api", "worksites"] and parts[3] == "audit":
                return self._json(200, {"audit": self.store.audit(parts[2])})
            self._json(404, {"error": "not found"})
        except KeyError:
            self._json(404, {"error": "worksite not found"})
        except Exception as exc:
            self._json(400, {"error": str(exc)})

    def do_POST(self):
        if not self._auth():
            return self._json(401, {"error": "unauthorised"})
        try:
            parts = self._parts()
            data = self._body()
            if len(parts) != 4 or parts[:2] != ["api", "worksites"]:
                return self._json(404, {"error": "not found"})
            wid, op = parts[2], parts[3]
            actor = str(data.get("actor") or "coordinator")
            if op == "assign":
                out = self.store.assign(wid, str(data.get("team_id") or ""), actor)
            elif op == "release":
                out = self.store.release(wid, actor)
            elif op == "transition":
                out = self.store.transition(wid, str(data.get("state") or ""), actor, str(data.get("note") or ""))
            else:
                return self._json(404, {"error": "not found"})
            self._json(200, out)
        except KeyError:
            self._json(404, {"error": "worksite not found"})
        except Exception as exc:
            self._json(409, {"error": str(exc)})


def load_jsonl(path: str | Path) -> list[dict[str, Any]]:
    with Path(path).open(encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def main() -> None:
    parser = argparse.ArgumentParser(description="CrisisWeave worksite coordination store")
    parser.add_argument("--db", default="worksites.db")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("init")
    imp = sub.add_parser("import"); imp.add_argument("path")
    listing = sub.add_parser("list"); listing.add_argument("--state", choices=STATES)
    val = sub.add_parser("validate"); val.add_argument("path")
    ass = sub.add_parser("assign"); ass.add_argument("id"); ass.add_argument("--team", required=True); ass.add_argument("--actor", default="cli")
    transition = sub.add_parser("transition"); transition.add_argument("id"); transition.add_argument("state", choices=STATES); transition.add_argument("--actor", default="cli"); transition.add_argument("--note", default="")
    release = sub.add_parser("release"); release.add_argument("id"); release.add_argument("--actor", default="cli")
    export = sub.add_parser("export"); export.add_argument("--state", choices=STATES)
    serve = sub.add_parser("serve"); serve.add_argument("--host", default="127.0.0.1"); serve.add_argument("--port", type=int, default=8787)
    args = parser.parse_args()
    store = WorksiteStore(args.db)

    if args.cmd == "init":
        print(json.dumps({"ok": True, "db": args.db}))
    elif args.cmd == "validate":
        rows = load_jsonl(args.path)
        for row in rows:
            validate_worksite(row)
        print(json.dumps({"ok": True, "worksites": len(rows)}))
    elif args.cmd == "import":
        rows = load_jsonl(args.path)
        for row in rows:
            store.upsert(row)
        print(json.dumps({"imported": len(rows)}))
    elif args.cmd == "list":
        print(json.dumps(store.list(args.state), ensure_ascii=False, indent=2))
    elif args.cmd == "assign":
        print(json.dumps(store.assign(args.id, args.team, args.actor), ensure_ascii=False, indent=2))
    elif args.cmd == "transition":
        print(json.dumps(store.transition(args.id, args.state, args.actor, args.note), ensure_ascii=False, indent=2))
    elif args.cmd == "release":
        print(json.dumps(store.release(args.id, args.actor), ensure_ascii=False, indent=2))
    elif args.cmd == "export":
        for worksite in store.list(args.state):
            print(json.dumps(worksite, ensure_ascii=False))
    elif args.cmd == "serve":
        APIHandler.store = store
        APIHandler.token = os.getenv("CW_COORDINATOR_TOKEN") or None
        server = ThreadingHTTPServer((args.host, args.port), APIHandler)
        print(f"CrisisWeave worksites API on http://{args.host}:{args.port}")
        server.serve_forever()


if __name__ == "__main__":
    main()
