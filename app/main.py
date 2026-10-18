"""RecallMesh - Shared Agent Memory & Coordination, powered by FalkorDB.

Graph Hacks 2026 - Track 2: Agent Memory and Coordination.
Run:  uvicorn app.main:app --reload --port 8000   (or docker compose up)
"""
import os
from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from .graph import get_store, KINDS
from .agents import AGENTS, ResearcherAgent, PlannerAgent, ExecutorAgent
from .extraction import extract_facts, guess_entities

store, store_warning = get_store()
app = FastAPI(title="RecallMesh", version="1.0.0",
              description="Agents that remember across sessions and share state through FalkorDB.")

STATIC = os.path.join(os.path.dirname(__file__), "..", "static")


class RememberIn(BaseModel):
    tenant: str = "demo"
    user_id: str = "varun"
    user_name: str = "Varun"
    agent_id: str = "researcher"
    kind: str = "semantic"
    title: str
    content: str
    entities: list[str] = []
    fact_type: str | None = None
    confidence: float = 0.85
    session_id: str | None = None


class MessageIn(BaseModel):
    tenant: str = "demo"
    user_id: str = "varun"
    user_name: str = "Varun"
    agent_id: str = "researcher"
    text: str
    session_id: str = "session-1"
    conversation_id: str = "main"


class TaskIn(BaseModel):
    tenant: str = "demo"
    title: str
    description: str = ""
    created_by: str = "planner"
    memory_ids: list[str] = []


class HandoffIn(BaseModel):
    tenant: str = "demo"
    from_agent: str
    to_agent: str
    task_id: str | None = None
    note: str = ""
    memory_ids: list[str] = []


class DemoIn(BaseModel):
    tenant: str = "demo"
    user_id: str = "varun"
    user_name: str = "Varun"


def agents_for(tenant):
    return {spec["id"]: cls(store, tenant, spec) for spec, cls in
            zip(AGENTS, (ResearcherAgent, PlannerAgent, ExecutorAgent))}


@app.get("/health")
def health():
    return {"ok": True, "backend": store.backend, "warning": store_warning}


@app.get("/api/agents")
def list_agents(tenant: str = "demo"):
    for spec in AGENTS:
        store.upsert_agent(tenant, spec["id"], spec["name"], spec["role"])
    return AGENTS


@app.post("/api/remember")
def remember(body: RememberIn):
    if body.kind not in KINDS:
        raise HTTPException(400, f"kind must be one of {KINDS}")
    store.upsert_user(body.tenant, body.user_id, body.user_name)
    return store.add_memory(body.tenant, body.user_id, body.agent_id, body.kind,
                            body.title, body.content, body.entities,
                            body.fact_type, body.confidence, body.session_id)


@app.post("/api/messages")
def post_message(body: MessageIn):
    """A conversation turn: stored as history + an episode, and any facts
    in it are extracted into semantic / procedural memory by the agent."""
    store.upsert_user(body.tenant, body.user_id, body.user_name)
    ag = agents_for(body.tenant)
    agent = ag.get(body.agent_id, ag["researcher"])
    if isinstance(agent, ResearcherAgent):
        return agent.hear(body.user_id, body.text, body.session_id, body.conversation_id)
    store.add_message(body.tenant, body.user_id, body.agent_id,
                      body.conversation_id, "user", body.text, body.session_id)
    return {"agent": body.agent_id, "heard": body.text,
            "facts_extracted": [store.add_memory(
                body.tenant, body.user_id, body.agent_id,
                "procedural" if f["fact_type"] == "Procedure" else "semantic",
                f["title"], f["content"], f["entities"], f["fact_type"], f["confidence"],
                body.session_id) for f in extract_facts(body.text)]}


@app.get("/api/recall")
def recall(tenant: str = "demo", user_id: str = "varun", q: str = "",
           agent_id: str = "", kinds: str = ""):
    return {"query": q, "agent_id": agent_id,
            "results": store.recall(tenant, user_id, query=q,
                                    entities=guess_entities(q),
                                    kinds=kinds.split(",") if kinds else None)}


@app.get("/api/conversations")
def conversations(tenant: str = "demo", user_id: str = "varun"):
    return store.list_messages(tenant, user_id)


@app.get("/api/timeline")
def timeline(tenant: str = "demo", user_id: str = "varun"):
    return store.timeline(tenant, user_id)


@app.post("/api/tasks")
def create_task(body: TaskIn):
    return store.create_task(body.tenant, body.title, body.description,
                             body.created_by, body.memory_ids)


@app.get("/api/tasks")
def list_tasks(tenant: str = "demo"):
    return store.list_tasks(tenant)


@app.post("/api/tasks/{task_id}/claim")
def claim_task(task_id: str, tenant: str = "demo", agent_id: str = "executor"):
    task, how = store.claim_task(tenant, task_id, agent_id)
    if how == "not_found":
        raise HTTPException(404, "task not found")
    if how == "already_claimed":
        raise HTTPException(409, f"task already claimed by {task.get('assignee')}")
    return task


@app.post("/api/tasks/{task_id}/complete")
def complete_task(task_id: str, tenant: str = "demo", agent_id: str = "executor",
                  result: str = "Done"):
    task = store.complete_task(tenant, task_id, agent_id, result)
    if not task:
        raise HTTPException(404, "task not found")
    return task


@app.post("/api/handoffs")
def handoff(body: HandoffIn):
    return store.create_handoff(body.tenant, body.from_agent, body.to_agent,
                                body.task_id, body.note, body.memory_ids)


@app.get("/api/handoffs")
def list_handoffs(tenant: str = "demo"):
    return store.list_handoffs(tenant)


@app.get("/api/graph")
def graph(tenant: str = "demo"):
    return store.graph_snapshot(tenant)


@app.get("/api/stats")
def stats(tenant: str = "demo"):
    return store.stats(tenant)


@app.post("/api/reset")
def reset(tenant: str = "demo"):
    store.reset(tenant)
    return {"reset": tenant}


@app.post("/api/demo/run")
def run_demo(body: DemoIn):
    """The full Track-2 story, end to end, in one call:

    Session 1: Varun teaches the Researcher facts (different session).
    Session 2: a DIFFERENT agent (Planner) - who never heard session 1 -
               recalls them from the graph and builds a plan.
    Handoff:   Planner -> Executor through the graph, with memory attached.
    Session 3: Executor finishes and writes back; Researcher can see it.
    """
    tenant, uid = body.tenant, body.user_id
    store.reset(tenant)
    store.upsert_user(tenant, uid, body.user_name)
    ag = agents_for(tenant)
    steps = []

    s1 = ag["researcher"].hear(uid,
        "I prefer concise updates and our standup is at 9:30 am. I am allergic to peanuts. "
        "Project Atlas launches on Nov 20. Priya owns design for Atlas.",
        session_id="session-1")
    steps.append({"step": "Session 1 - Researcher listens (Mon)", "result": s1})

    plan = ag["planner"].plan(uid, "Plan the Atlas launch day for Varun",
                              session_id="session-2")
    steps.append({"step": "Session 2 - Planner recalls across sessions (Thu, new agent, new session)",
                  "result": plan})

    task_id = plan["tasks_created"][0]["id"] if plan["tasks_created"] else None
    h = store.create_handoff(tenant, "planner", "executor", task_id,
        "Context is in the graph: Atlas deadline, Priya owns design, peanut allergy, 9:30 standup. Do not re-ask the user.",
        memory_ids=[c["id"] for c in plan["recalled"][:5]])
    steps.append({"step": "Handoff - Planner -> Executor via graph edge", "result": h})

    work = ag["executor"].work_next(uid)
    steps.append({"step": "Session 3 - Executor picks up handed-off work", "result": work})

    verify = store.recall(tenant, uid, query="Atlas peanuts Priya", entities=["Atlas", "Priya"])
    steps.append({"step": "Verify - any agent can now recall the full shared state",
                  "result": verify})
    return {"tenant": tenant, "steps": steps, "stats": store.stats(tenant)}


@app.get("/")
def index():
    return FileResponse(os.path.join(STATIC, "index.html"))


app.mount("/static", StaticFiles(directory=STATIC), name="static")
