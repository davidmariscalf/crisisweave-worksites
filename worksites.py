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
    "requested": {"triaged", "cancelled"}, "triaged": {"ready", "cancelled"},
    "ready": {"cancelled"}, "assigned": {"in_progress", "cancelled"},
    "in_progress": {"completed", "cancelled"}, "completed": set(), "cancelled": set(),
}


def now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def validate_worksite(w: dict[str, Any]) -> None:
    required = ("id", "title", "work_type", "state", "priority", "people_needed", "skills", "hazards", "area", "geometry", "source")
    missing = [k for k in required if k not in w]
    if missing: raise ValueError("missing required fields: " + ", ".join(missing))
    if not isinstance(w["id"], str) or not w["id"].strip(): raise ValueError("id must be a non-empty string")
    if not isinstance(w["title"], str) or not w["title"].strip(): raise ValueError("title must be a non-empty string")
    if w["work_type"] not in WORK_TYPES: raise ValueError("unsupported work_type")
    if w["state"] not in STATES: raise ValueError("unsupported state")
    if w["priority"] not in PRIORITIES: raise ValueError("unsupported priority")
    if not isinstance(w["people_needed"], int) or isinstance(w["people_needed"], bool) or not 1 <= w["people_needed"] <= 1000:
        raise ValueError("people_needed must be an integer from 1 to 1000")
    for field in ("skills", "hazards"):
        if not isinstance(w[field], list) or not all(isinstance(x, str) for x in w[field]): raise ValueError(f"{field} must be a list of strings")
        if len(set(w[field])) != len(w[field]): raise ValueError(f"{field} must not contain duplicates")
    if not isinstance(w["area"], str) or not w["area"].strip(): raise ValueError("area must be a non-empty string")
    g = w["geometry"]
    if not isinstance(g, dict) or g.get("type") != "Point": raise ValueError("geometry must be a GeoJSON Point")
    c = g.get("coordinates")
    if not isinstance(c, list) or len(c) != 2: raise ValueError("geometry.coordinates must contain [longitude, latitude]")
    try: lon, lat = float(c[0]), float(c[1])
    except (TypeError, ValueError): raise ValueError("coordinates must be numeric") from None
    if not (-180 <= lon <= 180 and -90 <= lat <= 90): raise ValueError("coordinates outside valid bounds")
    s = w["source"]
    if not isinstance(s, dict) or s.get("type") not in {"request", "assessment", "partner_import", "synthetic"}:
        raise ValueError("source must represent an explicit request, assessment, partner import or synthetic demo")
    if not str(s.get("name") or "").strip() or not str(s.get("source_id") or "").strip(): raise ValueError("source.name and source.source_id are required")
    if w["state"] == "assigned" and not str(w.get("assigned_team") or "").strip(): raise ValueError("assigned state requires assigned_team")


class WorksiteStore:
    def __init__(self, db_path: str | Path): self.db_path = str(db_path); self.init()
    def connect(self) -> sqlite3.Connection:
        con = sqlite3.connect(self.db_path, timeout=10); con.row_factory = sqlite3.Row; con.execute("PRAGMA foreign_keys=ON"); return con
    def init(self) -> None:
        with self.connect() as con:
            con.executescript("""
            CREATE TABLE IF NOT EXISTS worksites(id TEXT PRIMARY KEY,payload TEXT NOT NULL,state TEXT NOT NULL,assigned_team TEXT,version INTEGER NOT NULL DEFAULT 1,created_at TEXT NOT NULL,updated_at TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS audit(seq INTEGER PRIMARY KEY AUTOINCREMENT,worksite_id TEXT NOT NULL,at TEXT NOT NULL,actor TEXT NOT NULL,action TEXT NOT NULL,from_state TEXT,to_state TEXT,note TEXT,details TEXT NOT NULL DEFAULT '{}',FOREIGN KEY(worksite_id) REFERENCES worksites(id));
            CREATE INDEX IF NOT EXISTS idx_worksites_state ON worksites(state); CREATE INDEX IF NOT EXISTS idx_audit_worksite ON audit(worksite_id,seq);
            """)
    @staticmethod
    def _decode(row: sqlite3.Row) -> dict[str, Any]:
        d = json.loads(row["payload"]); d.update(state=row["state"], assigned_team=row["assigned_team"], version=row["version"], created_at=row["created_at"], updated_at=row["updated_at"]); return d
    def _audit(self, con, wid, actor, action, f, t, note="", details=None):
        con.execute("INSERT INTO audit(worksite_id,at,actor,action,from_state,to_state,note,details) VALUES(?,?,?,?,?,?,?,?)", (wid,now(),actor or "unknown",action,f,t,note or "",json.dumps(details or {})))
    def upsert(self, w: dict[str, Any], actor="import") -> dict[str, Any]:
        w=dict(w); w.setdefault("assigned_team",None); validate_worksite(w); created=str(w.get("created_at") or now()); updated=now(); payload=dict(w)
        for k in ("state","assigned_team","version","created_at","updated_at"): payload.pop(k,None)
        with self.connect() as con:
            prev=con.execute("SELECT state FROM worksites WHERE id=?",(w["id"],)).fetchone()
            if prev:
                con.execute("UPDATE worksites SET payload=?,state=?,assigned_team=?,version=version+1,updated_at=? WHERE id=?",(json.dumps(payload,ensure_ascii=False),w["state"],w.get("assigned_team"),updated,w["id"])); action="import_update"; old=prev["state"]
            else:
                con.execute("INSERT INTO worksites(id,payload,state,assigned_team,created_at,updated_at) VALUES(?,?,?,?,?,?)",(w["id"],json.dumps(payload,ensure_ascii=False),w["state"],w.get("assigned_team"),created,updated)); action="created"; old=None
            self._audit(con,w["id"],actor,action,old,w["state"])
        return self.get(w["id"])
    def get(self, wid):
        with self.connect() as con: row=con.execute("SELECT * FROM worksites WHERE id=?",(wid,)).fetchone()
        if not row: raise KeyError(wid)
        return self._decode(row)
    def list(self, state=None):
        with self.connect() as con: rows=con.execute("SELECT * FROM worksites"+(" WHERE state=?" if state else "")+" ORDER BY updated_at DESC",((state,) if state else ())).fetchall()
        return [self._decode(r) for r in rows]
    def transition(self,wid,target,actor,note=""):
        if target not in STATES: raise ValueError("unknown target state")
        with self.connect() as con:
            con.execute("BEGIN IMMEDIATE"); row=con.execute("SELECT * FROM worksites WHERE id=?",(wid,)).fetchone()
            if not row: raise KeyError(wid)
            cur=row["state"]
            if target=="assigned": raise ValueError("use assign operation to enter assigned state")
            if target not in TRANSITIONS[cur]: raise ValueError(f"invalid transition: {cur} -> {target}")
            con.execute("UPDATE worksites SET state=?,version=version+1,updated_at=? WHERE id=?",(target,now(),wid)); self._audit(con,wid,actor,"transition",cur,target,note)
        return self.get(wid)
    def assign(self,wid,team_id,actor):
        if not str(team_id).strip(): raise ValueError("team_id is required")
        with self.connect() as con:
            con.execute("BEGIN IMMEDIATE"); row=con.execute("SELECT * FROM worksites WHERE id=?",(wid,)).fetchone()
            if not row: raise KeyError(wid)
            if row["state"]!="ready":
                if row["state"] in {"assigned","in_progress"}: raise ValueError(f"worksite already allocated to {row['assigned_team'] or 'another team'}")
                raise ValueError(f"worksite must be ready before assignment; current state is {row['state']}")
            con.execute("UPDATE worksites SET state='assigned',assigned_team=?,version=version+1,updated_at=? WHERE id=?",(team_id,now(),wid)); self._audit(con,wid,actor,"assigned","ready","assigned",details={"team_id":team_id})
        return self.get(wid)
    def release(self,wid,actor):
        with self.connect() as con:
            con.execute("BEGIN IMMEDIATE"); row=con.execute("SELECT * FROM worksites WHERE id=?",(wid,)).fetchone()
            if not row: raise KeyError(wid)
            if row["state"]!="assigned": raise ValueError("only an assigned worksite can be released")
            team=row["assigned_team"]; con.execute("UPDATE worksites SET state='ready',assigned_team=NULL,version=version+1,updated_at=? WHERE id=?",(now(),wid)); self._audit(con,wid,actor,"released","assigned","ready",details={"team_id":team})
        return self.get(wid)
    def audit(self,wid):
        with self.connect() as con: rows=con.execute("SELECT * FROM audit WHERE worksite_id=? ORDER BY seq",(wid,)).fetchall()
        return [{**dict(r),"details":json.loads(r["details"])} for r in rows]


class APIHandler(BaseHTTPRequestHandler):
    store: WorksiteStore; token: str|None=None
    def log_message(self, fmt, *args): return
    def _json(self,status,data):
        body=json.dumps(data,ensure_ascii=False).encode(); self.send_response(status); self.send_header("Content-Type","application/json; charset=utf-8"); self.send_header("Content-Length",str(len(body))); self.send_header("Access-Control-Allow-Origin","*"); self.send_header("Access-Control-Allow-Headers","Authorization, Content-Type"); self.send_header("Access-Control-Allow-Methods","GET, POST, OPTIONS"); self.end_headers(); self.wfile.write(body)
    def do_OPTIONS(self): self._json(204,{})
    def _parts(self): return [p for p in urlparse(self.path).path.split("/") if p]
    def _auth(self): return not self.token or self.headers.get("Authorization")==f"Bearer {self.token}"
    def _body(self):
        n=int(self.headers.get("Content-Length") or 0)
        if n>100000: raise ValueError("request body too large")
        d=json.loads(self.rfile.read(n) if n else b"{}")
        if not isinstance(d,dict): raise ValueError("JSON body must be an object")
        return d
    def do_GET(self):
        try:
            p=self._parts()
            if p==["api","health"]: return self._json(200,{"ok":True,"service":"crisisweave-worksites"})
            if p==["api","worksites"]: return self._json(200,{"worksites":self.store.list()})
            if len(p)==3 and p[:2]==["api","worksites"]: return self._json(200,self.store.get(p[2]))
            if len(p)==4 and p[:2]==["api","worksites"] and p[3]=="audit": return self._json(200,{"audit":self.store.audit(p[2])})
            self._json(404,{"error":"not found"})
        except KeyError: self._json(404,{"error":"worksite not found"})
        except Exception as e: self._json(400,{"error":str(e)})
    def do_POST(self):
        if not self._auth(): return self._json(401,{"error":"unauthorised"})
        try:
            p=self._parts(); d=self._body()
            if len(p)!=4 or p[:2]!=["api","worksites"]: return self._json(404,{"error":"not found"})
            wid,op=p[2],p[3]; actor=str(d.get("actor") or "coordinator")
            if op=="assign": out=self.store.assign(wid,str(d.get("team_id") or ""),actor)
            elif op=="release": out=self.store.release(wid,actor)
            elif op=="transition": out=self.store.transition(wid,str(d.get("state") or ""),actor,str(d.get("note") or ""))
            else: return self._json(404,{"error":"not found"})
            self._json(200,out)
        except KeyError: self._json(404,{"error":"worksite not found"})
        except Exception as e: self._json(409,{"error":str(e)})


def load_jsonl(path):
    with Path(path).open(encoding="utf-8") as f: return [json.loads(line) for line in f if line.strip()]

def main():
    ap=argparse.ArgumentParser(description="CrisisWeave worksite coordination store"); ap.add_argument("--db",default="worksites.db"); sub=ap.add_subparsers(dest="cmd",required=True)
    sub.add_parser("init"); imp=sub.add_parser("import"); imp.add_argument("path"); ls=sub.add_parser("list"); ls.add_argument("--state",choices=STATES); val=sub.add_parser("validate"); val.add_argument("path"); ass=sub.add_parser("assign"); ass.add_argument("id"); ass.add_argument("--team",required=True); ass.add_argument("--actor",default="cli"); tr=sub.add_parser("transition"); tr.add_argument("id"); tr.add_argument("state",choices=STATES); tr.add_argument("--actor",default="cli"); tr.add_argument("--note",default=""); rel=sub.add_parser("release"); rel.add_argument("id"); rel.add_argument("--actor",default="cli"); ex=sub.add_parser("export"); ex.add_argument("--state",choices=STATES); sv=sub.add_parser("serve"); sv.add_argument("--host",default="127.0.0.1"); sv.add_argument("--port",type=int,default=8787)
    a=ap.parse_args(); store=WorksiteStore(a.db)
    if a.cmd=="init": print(json.dumps({"ok":True,"db":a.db}))
    elif a.cmd=="validate":
        rows=load_jsonl(a.path); [validate_worksite(x) for x in rows]; print(json.dumps({"ok":True,"worksites":len(rows)}))
    elif a.cmd=="import":
        rows=load_jsonl(a.path); [store.upsert(x) for x in rows]; print(json.dumps({"imported":len(rows)}))
    elif a.cmd=="list": print(json.dumps(store.list(a.state),ensure_ascii=False,indent=2))
    elif a.cmd=="assign": print(json.dumps(store.assign(a.id,a.team,a.actor),ensure_ascii=False,indent=2))
    elif a.cmd=="transition": print(json.dumps(store.transition(a.id,a.state,a.actor,a.note),ensure_ascii=False,indent=2))
    elif a.cmd=="release": print(json.dumps(store.release(a.id,a.actor),ensure_ascii=False,indent=2))
    elif a.cmd=="export":
        for w in store.list(a.state): print(json.dumps(w,ensure_ascii=False))
    elif a.cmd=="serve":
        APIHandler.store=store; APIHandler.token=os.getenv("CW_COORDINATOR_TOKEN") or None; server=ThreadingHTTPServer((a.host,a.port),APIHandler); print(f"CrisisWeave worksites API on http://{a.host}:{a.port}"); server.serve_forever()

if __name__=="__main__": main()
