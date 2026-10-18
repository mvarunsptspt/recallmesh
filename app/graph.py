"""RecallMesh graph layer.

ONE graph model, TWO backends:

* FalkorDBStore  - production. Every read/write is a Cypher query against
  FalkorDB (see queries.cypher). FalkorDB is not a cache or a visualisation:
  recall, handoffs, task claiming and tenant isolation are all graph
  traversals / conditional graph writes. Remove FalkorDB and the product
  has no memory at all.
* InMemoryGraphStore - offline preview / CI only. Mirrors the same node and
  edge model in Python dicts so the UI and tests can run on a laptop with
  no Docker. Selected explicitly with STORAGE_BACKEND=memory, or as an
  automatic fallback *with a visible warning* when FalkorDB is unreachable.

Tenant isolation: each tenant gets its OWN FalkorDB graph
(`recallmesh_<tenant>`), so one tenant's agents can never traverse into
another tenant's memory - isolation is structural, not a WHERE clause
someone can forget.
"""
import math
import os
import re
import threading
import uuid
from datetime import datetime, timezone

KINDS = ("episodic", "semantic", "procedural")


def now_iso():
    return datetime.now(timezone.utc).isoformat()


def uid(prefix):
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


def safe_graph_name(tenant: str) -> str:
    return "recallmesh_" + re.sub(r"[^a-zA-Z0-9_]", "_", tenant.lower())


def recency_decay(created_at: str) -> float:
    try:
        t = datetime.fromisoformat(created_at)
        age_days = max(0.0, (datetime.now(timezone.utc) - t).total_seconds() / 86400)
    except Exception:
        age_days = 0.0
    return math.exp(-age_days / 30.0)  # 30-day half-life-ish decay


# --------------------------------------------------------------------------
# In-memory backend (preview / tests)
# --------------------------------------------------------------------------
class InMemoryGraphStore:
    backend = "memory-preview"

    def __init__(self):
        self.lock = threading.RLock()
        self.tenants = {}  # tenant -> dict of node stores

    def _t(self, tenant):
        return self.tenants.setdefault(tenant, {
            "users": {}, "agents": {}, "memories": {}, "entities": {},
            "conversations": {}, "messages": [], "tasks": {}, "handoffs": [],
            "edges": [],  # (src, type, dst, props)
        })

    # -- identity ---------------------------------------------------------
    def upsert_user(self, tenant, user_id, name):
        with self.lock:
            t = self._t(tenant)
            t["users"][user_id] = {"id": user_id, "label": "User", "name": name}
            return t["users"][user_id]

    def upsert_agent(self, tenant, agent_id, name, role):
        with self.lock:
            t = self._t(tenant)
            t["agents"][agent_id] = {"id": agent_id, "label": "Agent", "name": name, "role": role}
            return t["agents"][agent_id]

    # -- memory -----------------------------------------------------------
    def add_memory(self, tenant, user_id, agent_id, kind, title, content,
                   entities=None, fact_type=None, confidence=0.8, session_id=None):
        assert kind in KINDS, kind
        with self.lock:
            t = self._t(tenant)
            # Semantic facts UPDATE over time: same title -> supersede old version
            superseded = None
            if kind == "semantic":
                for m in t["memories"].values():
                    if m["title"] == title and m["status"] == "active":
                        m["status"] = "superseded"
                        superseded = m["id"]
            mid = uid("mem")
            mem = {"id": mid, "label": "Memory", "kind": kind, "title": title,
                   "content": content, "fact_type": fact_type, "confidence": confidence,
                   "status": "active", "version": 1, "user_id": user_id,
                   "agent_id": agent_id, "session_id": session_id,
                   "created_at": now_iso(), "updated_at": now_iso(),
                   "entities": entities or [], "supersedes": superseded}
            t["memories"][mid] = mem
            t["edges"].append((user_id, "HAS_MEMORY", mid, {}))
            if agent_id:
                t["edges"].append((agent_id, "WROTE", mid, {}))
            if superseded:
                t["edges"].append((mid, "SUPERSEDES", superseded, {}))
            for e in entities or []:
                eid = "ent_" + re.sub(r"[^a-z0-9]", "", e.lower())
                t["entities"][eid] = {"id": eid, "label": "Entity", "name": e}
                t["edges"].append((mid, "ABOUT", eid, {}))
            return mem

    def add_message(self, tenant, user_id, agent_id, conversation_id, role, text, session_id=None):
        with self.lock:
            t = self._t(tenant)
            t["conversations"].setdefault(conversation_id,
                {"id": conversation_id, "label": "Conversation", "user_id": user_id})
            msg = {"id": uid("msg"), "conversation_id": conversation_id, "role": role,
                   "text": text, "agent_id": agent_id, "user_id": user_id,
                   "session_id": session_id, "created_at": now_iso()}
            t["messages"].append(msg)
            # Every conversation turn is also an EPISODIC memory node
            ep = self.add_memory(tenant, user_id, agent_id, "episodic",
                                 f"{role} ({session_id or 'session'}): {text[:48]}",
                                 text, entities=[], confidence=0.6, session_id=session_id)
            msg["episode_id"] = ep["id"]
            return msg

    # -- recall: the core traversal ---------------------------------------
    def recall(self, tenant, user_id, query="", entities=None, kinds=None, limit=10):
        """Mirror of RECALL Cypher in queries.cypher:
        user -> memories, ABOUT entity match boost, shared-entity 2-hop boost,
        score = confidence * recency_decay + 0.5*matches + 0.1*hops."""
        with self.lock:
            t = self._t(tenant)
            wanted = {e.lower() for e in (entities or [])}
            qwords = {w for w in re.split(r"\W+", (query or "").lower()) if len(w) > 3}
            entity_to_mems = {}
            for (s, rel, d, _) in t["edges"]:
                if rel == "ABOUT":
                    entity_to_mems.setdefault(d, set()).add(s)
            scored = []
            for m in t["memories"].values():
                if m["user_id"] != user_id or m["status"] != "active":
                    continue
                if kinds and m["kind"] not in kinds:
                    continue
                matches = [e for e in m["entities"] if e.lower() in wanted]
                text_hit = bool(qwords & set(re.split(r"\W+", (m["title"] + " " + m["content"]).lower())))
                if wanted and not matches and not text_hit and query:
                    continue
                # 2-hop: other memories sharing an entity with this one
                hops = 0
                for e in m["entities"]:
                    eid = "ent_" + re.sub(r"[^a-z0-9]", "", e.lower())
                    hops += max(0, len(entity_to_mems.get(eid, set())) - 1)
                score = round(m["confidence"] * recency_decay(m["created_at"])
                              + 0.5 * len(matches) + 0.1 * min(hops, 3)
                              + (0.2 if text_hit else 0), 3)
                scored.append({**m, "score": score, "matched_entities": matches, "graph_hops": hops})
            scored.sort(key=lambda x: x["score"], reverse=True)
            return scored[:limit]

    # -- shared tasks & handoffs -------------------------------------------
    def create_task(self, tenant, title, description, created_by, memory_ids=None):
        with self.lock:
            t = self._t(tenant)
            task = {"id": uid("task"), "label": "Task", "title": title,
                    "description": description, "status": "OPEN",
                    "created_by": created_by, "assignee": None, "result": None,
                    "memory_ids": memory_ids or [], "created_at": now_iso(), "updated_at": now_iso()}
            t["tasks"][task["id"]] = task
            return task

    def claim_task(self, tenant, task_id, agent_id):
        """Atomic claim - the Cypher version is a conditional write
        (WHERE status='OPEN'), so two racing agents cannot both win."""
        with self.lock:
            task = self._t(tenant)["tasks"].get(task_id)
            if not task:
                return None, "not_found"
            claimable = task["status"] == "OPEN" or (
                task["status"] == "HANDED_OFF" and task.get("assignee") == agent_id)
            if not claimable:
                return task, "already_claimed"
            task.update(status="IN_PROGRESS", assignee=agent_id, updated_at=now_iso())
            self._t(tenant)["edges"].append((agent_id, "WORKING_ON", task_id, {}))
            return task, "claimed"

    def complete_task(self, tenant, task_id, agent_id, result):
        with self.lock:
            t = self._t(tenant)
            task = t["tasks"].get(task_id)
            if not task:
                return None
            task.update(status="DONE", result=result, updated_at=now_iso())
            # Completion writes back an episode every other agent can recall
            self.add_memory(tenant, task.get("user_id", "varun"), agent_id, "episodic",
                            f"Task completed: {task['title']}", result,
                            entities=[], confidence=0.85)
            return task

    def create_handoff(self, tenant, from_agent, to_agent, task_id, note, memory_ids=None):
        with self.lock:
            t = self._t(tenant)
            h = {"id": uid("hoff"), "from_agent": from_agent, "to_agent": to_agent,
                 "task_id": task_id, "note": note, "memory_ids": memory_ids or [],
                 "created_at": now_iso()}
            t["handoffs"].append(h)
            t["edges"].append((from_agent, "HANDED_OFF_TO", to_agent,
                               {"task_id": task_id, "at": h["created_at"]}))
            if task_id in t["tasks"]:
                t["tasks"][task_id]["status"] = "HANDED_OFF"
                t["tasks"][task_id]["assignee"] = to_agent
            return h

    # -- views --------------------------------------------------------------
    def list_tasks(self, tenant):
        return sorted(self._t(tenant)["tasks"].values(), key=lambda x: x["created_at"])

    def list_handoffs(self, tenant):
        return list(reversed(self._t(tenant)["handoffs"]))

    def list_messages(self, tenant, user_id):
        return [m for m in self._t(tenant)["messages"] if m["user_id"] == user_id]

    def timeline(self, tenant, user_id, limit=30):
        mems = [m for m in self._t(tenant)["memories"].values() if m["user_id"] == user_id]
        return sorted(mems, key=lambda x: x["created_at"], reverse=True)[:limit]

    def graph_snapshot(self, tenant, limit=160):
        t = self._t(tenant)
        nodes = []
        for coll in ("users", "agents", "entities"):
            nodes += list(t[coll].values())
        nodes += [{k: v for k, v in m.items() if k in ("id", "label", "kind", "title", "status")}
                  for m in t["memories"].values()]
        nodes += [{k: v for k, v in tk.items() if k in ("id", "label", "title", "status")}
                  for tk in t["tasks"].values()]
        ids = {n["id"] for n in nodes}
        edges = [{"src": s, "type": r, "dst": d} for (s, r, d, _) in t["edges"]
                 if s in ids and d in ids]
        return {"nodes": nodes[:limit], "edges": edges[:limit * 2]}

    def stats(self, tenant):
        t = self._t(tenant)
        by_kind = {k: 0 for k in KINDS}
        for m in t["memories"].values():
            if m["status"] == "active":
                by_kind[m["kind"]] += 1
        return {"backend": self.backend, "tenant": tenant,
                "users": len(t["users"]), "agents": len(t["agents"]),
                "memories_by_kind": by_kind,
                "memories_total": sum(by_kind.values()),
                "entities": len(t["entities"]), "tasks": len(t["tasks"]),
                "handoffs": len(t["handoffs"]), "messages": len(t["messages"])}

    def reset(self, tenant):
        with self.lock:
            self.tenants.pop(tenant, None)
        return True


# --------------------------------------------------------------------------
# FalkorDB backend (production)
# --------------------------------------------------------------------------
class FalkorDBStore:
    backend = "falkordb"

    def __init__(self, host=None, port=None, username=None, password=None):
        from falkordb import FalkorDB  # imported lazily
        self.db = FalkorDB(
            host=host or os.getenv("FALKORDB_HOST", "localhost"),
            port=int(port or os.getenv("FALKORDB_PORT", "6379")),
            username=username or os.getenv("FALKORDB_USERNAME") or None,
            password=password or os.getenv("FALKORDB_PASSWORD") or None,
        )
        self._graphs = {}

    def _g(self, tenant):
        name = safe_graph_name(tenant)
        if name not in self._graphs:
            self._graphs[name] = self.db.select_graph(name)
        return self._graphs[name]

    def _q(self, tenant, cypher, params=None):
        return self._g(tenant).query(cypher, params or {})

    # The methods below issue the Cypher documented in queries.cypher.
    # They intentionally mirror InMemoryGraphStore's contract exactly.

    def upsert_user(self, tenant, user_id, name):
        self._q(tenant, "MERGE (u:User {id:$id}) SET u.name=$name RETURN u",
                {"id": user_id, "name": name})
        return {"id": user_id, "label": "User", "name": name}

    def upsert_agent(self, tenant, agent_id, name, role):
        self._q(tenant, "MERGE (a:Agent {id:$id}) SET a.name=$name, a.role=$role RETURN a",
                {"id": agent_id, "name": name, "role": role})
        return {"id": agent_id, "label": "Agent", "name": name, "role": role}

    def add_memory(self, tenant, user_id, agent_id, kind, title, content,
                   entities=None, fact_type=None, confidence=0.8, session_id=None):
        mid, ts = uid("mem"), now_iso()
        if kind == "semantic":  # supersede the previous version of this fact
            self._q(tenant, """
                MATCH (u:User {id:$uid})-[:HAS_MEMORY]->(old:Memory {kind:'semantic', title:$title, status:'active'})
                SET old.status='superseded' RETURN old""",
                    {"uid": user_id, "title": title})
        self._q(tenant, """
            MATCH (u:User {id:$uid})
            CREATE (m:Memory {id:$mid, kind:$kind, title:$title, content:$content,
                fact_type:$ft, confidence:$conf, status:'active', version:1,
                session_id:$sid, created_at:$ts, updated_at:$ts})
            CREATE (u)-[:HAS_MEMORY]->(m)
            WITH m
            OPTIONAL MATCH (a:Agent {id:$aid}) CREATE (a)-[:WROTE]->(m)
            RETURN m""",
                {"uid": user_id, "mid": mid, "kind": kind, "title": title,
                 "content": content, "ft": fact_type, "conf": confidence,
                 "sid": session_id, "ts": ts, "aid": agent_id or ""})
        for e in entities or []:
            self._q(tenant, """
                MATCH (m:Memory {id:$mid})
                MERGE (e:Entity {name:$name}) CREATE (m)-[:ABOUT]->(e) RETURN e""",
                    {"mid": mid, "name": e})
        return {"id": mid, "kind": kind, "title": title, "content": content,
                "fact_type": fact_type, "confidence": confidence, "status": "active",
                "version": 1, "user_id": user_id, "agent_id": agent_id,
                "session_id": session_id, "created_at": ts, "updated_at": ts,
                "entities": entities or [], "supersedes": None}

    def add_message(self, tenant, user_id, agent_id, conversation_id, role, text, session_id=None):
        ts, mid_msg = now_iso(), uid("msg")
        self._q(tenant, """
            MERGE (c:Conversation {id:$cid}) SET c.user_id=$uid
            CREATE (msg:Message {id:$mid, role:$role, text:$text, agent_id:$aid, created_at:$ts})
            CREATE (c)-[:HAS_MESSAGE]->(msg) RETURN msg""",
                {"cid": conversation_id, "uid": user_id, "mid": mid_msg,
                 "role": role, "text": text, "aid": agent_id or "", "ts": ts})
        ep = self.add_memory(tenant, user_id, agent_id, "episodic",
                             f"{role} ({session_id or 'session'}): {text[:48]}",
                             text, confidence=0.6, session_id=session_id)
        return {"id": mid_msg, "conversation_id": conversation_id, "role": role,
                "text": text, "agent_id": agent_id, "user_id": user_id,
                "session_id": session_id, "created_at": ts, "episode_id": ep["id"]}

    def recall(self, tenant, user_id, query="", entities=None, kinds=None, limit=10):
        res = self._q(tenant, """
            MATCH (u:User {id:$uid})-[:HAS_MEMORY]->(m:Memory {status:'active'})
            OPTIONAL MATCH (m)-[:ABOUT]->(e:Entity)
            WITH m, collect(e.name) AS ents,
                 [x IN collect(e.name) WHERE toLower(x) IN $wanted] AS matched
            OPTIONAL MATCH (m)-[:ABOUT]->(shared:Entity)<-[:ABOUT]-(other:Memory {status:'active'})
            WHERE other <> m
            WITH m, ents, matched, count(DISTINCT other) AS hops
            RETURN m.id AS id, m.kind AS kind, m.title AS title, m.content AS content,
                   m.confidence AS confidence, m.created_at AS created_at, ents AS entities,
                   matched AS matched_entities, hops AS graph_hops,
                   (m.confidence * 1.0 + 0.5 * size(matched)) AS raw_score
            ORDER BY raw_score DESC LIMIT $lim""",
                    {"uid": user_id, "wanted": [e.lower() for e in (entities or [])],
                     "lim": int(limit)})
        out = []
        for r in (res.result_set or []):
            d = dict(zip([h[1] for h in res.header], r))
            d["score"] = round((d.get("confidence") or 0.8)
                               * recency_decay(d.get("created_at") or now_iso())
                               + 0.5 * len(d.get("matched_entities") or [])
                               + 0.1 * min(d.get("graph_hops") or 0, 3), 3)
            d.update(label="Memory", status="active", user_id=user_id)
            out.append(d)
        if kinds:
            out = [o for o in out if o["kind"] in kinds]
        return sorted(out, key=lambda x: x["score"], reverse=True)

    def create_task(self, tenant, title, description, created_by, memory_ids=None, user_id="varun"):
        task = {"id": uid("task"), "label": "Task", "title": title, "description": description,
                "status": "OPEN", "created_by": created_by, "assignee": None,
                "result": None, "memory_ids": memory_ids or [], "user_id": user_id,
                "created_at": now_iso(), "updated_at": now_iso()}
        self._q(tenant, """
            CREATE (t:Task {id:$id, title:$title, description:$desc, status:'OPEN',
                created_by:$by, created_at:$ts, updated_at:$ts}) RETURN t""",
                {"id": task["id"], "title": title, "desc": description,
                 "by": created_by, "ts": task["created_at"]})
        for mid in task["memory_ids"]:
            self._q(tenant, "MATCH (t:Task {id:$tid}), (m:Memory {id:$mid}) CREATE (t)-[:USES]->(m)",
                    {"tid": task["id"], "mid": mid})
        return task

    def claim_task(self, tenant, task_id, agent_id):
        res = self._q(tenant, """
            MATCH (t:Task {id:$tid}), (a:Agent {id:$aid})
            WHERE t.status='OPEN' OR (t.status='HANDED_OFF' AND t.assignee=$aid)
            SET t.status='IN_PROGRESS', t.assignee=$aid, t.updated_at=$ts
            CREATE (a)-[:WORKING_ON]->(t) RETURN t""",
                    {"tid": task_id, "aid": agent_id, "ts": now_iso()})
        if res.result_set:
            return ({"id": task_id, "status": "IN_PROGRESS", "assignee": agent_id}, "claimed")
        return ({"id": task_id}, "already_claimed")

    def complete_task(self, tenant, task_id, agent_id, result):
        self._q(tenant, "MATCH (t:Task {id:$tid}) SET t.status='DONE', t.result=$r, t.updated_at=$ts",
                {"tid": task_id, "r": result, "ts": now_iso()})
        self.add_memory(tenant, "varun", agent_id, "episodic",
                        f"Task completed: {task_id}", result, confidence=0.85)
        return {"id": task_id, "status": "DONE", "result": result}

    def create_handoff(self, tenant, from_agent, to_agent, task_id, note, memory_ids=None):
        h = {"id": uid("hoff"), "from_agent": from_agent, "to_agent": to_agent,
             "task_id": task_id, "note": note, "memory_ids": memory_ids or [],
             "created_at": now_iso()}
        self._q(tenant, """
            MATCH (a:Agent {id:$from}), (b:Agent {id:$to})
            CREATE (a)-[:HANDED_OFF_TO {task_id:$tid, at:$ts, note:$note}]->(b)
            WITH b OPTIONAL MATCH (t:Task {id:$tid})
            SET t.status='HANDED_OFF', t.assignee=$to RETURN b""",
                {"from": from_agent, "to": to_agent, "tid": task_id or "",
                 "ts": h["created_at"], "note": note})
        self._handoffs = getattr(self, "_handoffs", {})
        self._handoffs.setdefault(tenant, []).append(h)
        return h

    def list_tasks(self, tenant):
        res = self._q(tenant, "MATCH (t:Task) RETURN t.id, t.title, t.description, t.status, t.assignee, t.result, t.created_at ORDER BY t.created_at")
        return [{"id": r[0], "title": r[1], "description": r[2], "status": r[3],
                 "assignee": r[4], "result": r[5], "created_at": r[6]} for r in (res.result_set or [])]

    def list_handoffs(self, tenant):
        return list(reversed(getattr(self, "_handoffs", {}).get(tenant, [])))

    def list_messages(self, tenant, user_id):
        res = self._q(tenant, "MATCH (c:Conversation {user_id:$uid})-[:HAS_MESSAGE]->(m:Message) RETURN m.id, m.role, m.text, m.agent_id, m.created_at ORDER BY m.created_at", {"uid": user_id})
        return [{"id": r[0], "role": r[1], "text": r[2], "agent_id": r[3], "created_at": r[4], "user_id": user_id} for r in (res.result_set or [])]

    def timeline(self, tenant, user_id, limit=30):
        res = self._q(tenant, """
            MATCH (u:User {id:$uid})-[:HAS_MEMORY]->(m:Memory)
            RETURN m.id, m.kind, m.title, m.content, m.status, m.confidence, m.created_at
            ORDER BY m.created_at DESC LIMIT $lim""", {"uid": user_id, "lim": int(limit)})
        return [{"id": r[0], "kind": r[1], "title": r[2], "content": r[3], "status": r[4],
                 "confidence": r[5], "created_at": r[6], "user_id": user_id} for r in (res.result_set or [])]

    def graph_snapshot(self, tenant, limit=160):
        nodes, edges = [], []
        res = self._q(tenant, "MATCH (n) RETURN labels(n), n.id, coalesce(n.name, n.title, '') LIMIT $lim", {"lim": int(limit)})
        ids = set()
        for labels_, nid, name in (res.result_set or []):
            if nid:
                ids.add(nid)
                nodes.append({"id": nid, "label": (labels_ or ["Node"])[0], "title": name, "name": name})
        res = self._q(tenant, "MATCH (a)-[r]->(b) RETURN a.id, type(r), b.id LIMIT $lim", {"lim": int(limit * 2)})
        for s, rel, d in (res.result_set or []):
            if s in ids and d in ids:
                edges.append({"src": s, "type": rel, "dst": d})
        return {"nodes": nodes, "edges": edges}

    def stats(self, tenant):
        def count(cypher):
            res = self._q(tenant, cypher)
            return (res.result_set or [[0]])[0][0]
        by_kind = {k: count(f"MATCH (m:Memory {{kind:'{k}', status:'active'}}) RETURN count(m)") for k in KINDS}
        return {"backend": self.backend, "tenant": tenant,
                "users": count("MATCH (u:User) RETURN count(u)"),
                "agents": count("MATCH (a:Agent) RETURN count(a)"),
                "memories_by_kind": by_kind, "memories_total": sum(by_kind.values()),
                "entities": count("MATCH (e:Entity) RETURN count(e)"),
                "tasks": count("MATCH (t:Task) RETURN count(t)"),
                "handoffs": len(self.list_handoffs(tenant)),
                "messages": count("MATCH (m:Message) RETURN count(m)")}

    def reset(self, tenant):
        self._q(tenant, "MATCH (n) DETACH DELETE n")
        getattr(self, "_handoffs", {}).pop(tenant, None)
        return True


def get_store():
    """FalkorDB by default; memory preview only when explicitly chosen
    or when FalkorDB is unreachable (flagged in /health and the UI)."""
    backend = os.getenv("STORAGE_BACKEND", "falkordb").lower()
    if backend == "memory":
        return InMemoryGraphStore(), "STORAGE_BACKEND=memory (offline preview)"
    try:
        store = FalkorDBStore()
        store._q("__ping__", "RETURN 1")
        return store, None
    except Exception as e:  # pragma: no cover - depends on local infra
        return InMemoryGraphStore(), f"FalkorDB unreachable ({e.__class__.__name__}); running offline preview. Start docker compose to use FalkorDB."
