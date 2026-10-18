"""Three specialist agents that coordinate ONLY through the shared graph.

No agent calls another agent directly and none keeps a private copy of the
user's history. They read and write the same FalkorDB graph, hand work off
with HANDED_OFF_TO edges, and race to claim shared tasks. Kill any agent,
start a new one, and it picks up full context from the graph - that is the
whole point of Track 2.
"""

AGENTS = [
    {"id": "researcher", "name": "Researcher", "role": "Listens, extracts facts, builds semantic memory"},
    {"id": "planner", "name": "Planner", "role": "Recalls memory across sessions and turns it into a plan / tasks"},
    {"id": "executor", "name": "Executor", "role": "Claims tasks, does the work, writes results back as episodes"},
]


class BaseAgent:
    def __init__(self, store, tenant, spec):
        self.store, self.tenant = store, tenant
        self.id, self.name, self.role = spec["id"], spec["name"], spec["role"]
        store.upsert_agent(tenant, self.id, self.name, self.role)


class ResearcherAgent(BaseAgent):
    def hear(self, user_id, text, session_id, conversation_id="main"):
        from .extraction import extract_facts
        self.store.add_message(self.tenant, user_id, self.id, conversation_id, "user", text, session_id)
        facts = extract_facts(text)
        written = []
        for f in facts:
            kind = "procedural" if f["fact_type"] == "Procedure" else "semantic"
            written.append(self.store.add_memory(
                self.tenant, user_id, self.id, kind, f["title"], f["content"],
                entities=f["entities"], fact_type=f["fact_type"],
                confidence=f["confidence"], session_id=session_id))
        return {"agent": self.id, "heard": text, "facts_extracted": written}


class PlannerAgent(BaseAgent):
    def plan(self, user_id, goal, session_id=None):
        from .extraction import guess_entities
        context = self.store.recall(self.tenant, user_id, query=goal,
                                    entities=guess_entities(goal), limit=12)
        # Safety memories are ALWAYS recalled, whatever the goal is: an
        # allergy learned in session 1 must constrain a plan in session 9.
        seen = {c["id"] for c in context}
        for c in self.store.recall(self.tenant, user_id, query="allergy allergic health",
                                   entities=["Peanuts", "Health"], limit=5):
            if c["id"] not in seen:
                context.append(c); seen.add(c["id"])
        allergy = next((c for c in context if c.get("fact_type") == "Allergy"
                        or "allerg" in c["title"].lower()), None)
        tasks, notes = [], []
        t = self.store.create_task(
            self.tenant, f"Plan: {goal}", f"Created by Planner from recalled memory. "
            f"Context used: {len(context)} memories.", self.id,
            memory_ids=[c["id"] for c in context[:5]])
        tasks.append(t)
        if allergy:
            notes.append(f"Safety check from memory: {allergy['content']}")
            t2 = self.store.create_task(
                self.tenant, "Verify plan against allergy / health memory",
                allergy["content"], self.id, memory_ids=[allergy["id"]])
            tasks.append(t2)
        return {"agent": self.id, "goal": goal, "recalled": context,
                "tasks_created": tasks, "notes": notes}


class ExecutorAgent(BaseAgent):
    def work_next(self, user_id):
        done = []
        for task in self.store.list_tasks(self.tenant):
            if task["status"] in ("OPEN", "HANDED_OFF"):
                claimed, how = self.store.claim_task(self.tenant, task["id"], self.id)
                if how != "claimed" and task["status"] != "HANDED_OFF":
                    continue
                result = (f"Executor completed '{task['title']}' using shared graph context "
                          f"(no context was re-asked from the user).")
                self.store.complete_task(self.tenant, task["id"], self.id, result)
                done.append({"task": task["title"], "result": result})
                break  # one task per call keeps the demo observable
        return {"agent": self.id, "completed": done}
