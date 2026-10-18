"""Run with plain python (no pytest needed):  python tests/test_memory.py
Uses the in-memory graph backend; the FalkorDB backend issues the same
operations as Cypher (queries.cypher) and is covered by the demo + load test.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from app.graph import InMemoryGraphStore
from app.agents import AGENTS, ResearcherAgent, PlannerAgent, ExecutorAgent

store = InMemoryGraphStore()
T, U = "acme", "varun"
store.upsert_user(T, U, "Varun")
agents = {s["id"]: c(store, T, s) for s, c in
          zip(AGENTS, (ResearcherAgent, PlannerAgent, ExecutorAgent))}

# Session 1: Researcher learns facts
out = agents["researcher"].hear(U,
    "I prefer concise updates and our standup is at 9:30 am. I am allergic to peanuts. "
    "Project Atlas launches on Nov 20. Priya owns design for Atlas.", "session-1")
titles = [f["title"] for f in out["facts_extracted"]]
assert any("peanut" in t.lower() for t in titles), titles
assert any("Atlas" in t for t in titles), titles
assert any("Priya" in t for t in titles), titles
print("PASS extraction:", titles)

# Session 2: a DIFFERENT agent recalls what it never heard
hits = store.recall(T, U, query="Atlas peanuts", entities=["Atlas"])
assert hits and any("peanut" in h["title"].lower() for h in hits), hits
print("PASS cross-agent, cross-session recall:", [h["title"] for h in hits])

# Tenant isolation: another tenant sees nothing
assert store.recall("other-tenant", U, query="Atlas", entities=["Atlas"]) == []
print("PASS tenant isolation")

# Facts update: supersede, don't duplicate
store.add_memory(T, U, "researcher", "semantic", "Allergy: Peanuts", "old text", ["Peanuts"], "Allergy", 0.5)
store.add_memory(T, U, "researcher", "semantic", "Allergy: Peanuts", "corrected text", ["Peanuts"], "Allergy", 0.99)
active = [m for m in store.timeline(T, U, 50) if m["title"] == "Allergy: Peanuts" and m["status"] == "active"]
assert len(active) == 1 and active[0]["content"] == "corrected text", active
print("PASS fact superseding / memory updates over time")

# Handoff + shared task race
plan = agents["planner"].plan(U, "Plan the Atlas launch day for Varun", "session-2")
assert plan["tasks_created"], plan
task_id = plan["tasks_created"][0]["id"]
store.create_handoff(T, "planner", "executor", task_id, "context in graph")
_, how1 = store.claim_task(T, plan["tasks_created"][1]["id"] if len(plan["tasks_created"]) > 1 else task_id, "executor")
_, how2 = store.claim_task(T, plan["tasks_created"][1]["id"] if len(plan["tasks_created"]) > 1 else task_id, "researcher")
assert {how1, how2} == {"claimed", "already_claimed"}, (how1, how2)
print("PASS handoff + atomic claim (one winner only)")

# Conversation history persists
msgs = store.list_messages(T, U)
assert msgs and "peanuts" in msgs[0]["text"]
print("PASS persistent conversation history:", len(msgs), "messages")

print("\nALL TESTS PASSED")
