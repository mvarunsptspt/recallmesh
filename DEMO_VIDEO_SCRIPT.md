# DEMO VIDEO — record this today (target 2:30, max 3:00)

**Before recording**
1. `docker compose up --build` → open http://localhost:8000 and http://localhost:3000 (FalkorDB Browser) in two tabs.
2. Click **Reset**, then rehearse once with **▶ Run the 3-session demo**.
3. Record screen with OBS / Loom / Screenity, 1080p, mic close. Upload to YouTube as **Unlisted**, title: `RecallMesh — Shared Agent Memory & Coordination | Graph Hacks 2026 (FalkorDB)`.

---

**[0:00–0:20 — Problem, show the dashboard]**
> "Multi-agent systems forget. Each agent keeps its own transcript, so a new agent or a new session starts from zero — and the user repeats themselves, or the agent acts on half the facts. RecallMesh gives a team of agents one shared memory, in a FalkorDB graph."

**[0:20–0:55 — Session 1, Box 1]**
Type/paste the pre-filled sentence and click **Remember this**.
> "Session one. I tell the Researcher — once — that I prefer concise updates, standup is 9:30, I'm allergic to peanuts, Atlas launches Nov 20, and Priya owns design. Watch: those become semantic and procedural memories, linked to entities in the graph."
*(Scroll to the graph / timeline. Switch to FalkorDB Browser tab, run: `MATCH (n) RETURN n LIMIT 50`)*

**[0:55–1:35 — Session 2, Box 2 — the money shot]**
Change the session field story by narrating "days later", keep agent = Planner flow: click **Recall**, then **Planner: build plan + tasks**.
> "Session two, days later, a completely different agent — the Planner never heard session one. But its context is a Cypher traversal over the user's memory graph, so it recalls the deadline, Priya's ownership — and the peanut allergy — and it flags that allergy as a safety check before planning anything."

**[1:35–2:00 — Handoff + Executor, Box 3]**
Show the handoff card, click **Executor: work next task**.
> "The Planner hands off to the Executor as a graph edge, with the memories attached to the task. The Executor claims it atomically and finishes it — without asking me anything again — and writes the result back as a new episode, which every agent can now recall."

**[2:00–2:20 — Under the hood, FalkorDB Browser]**
Run the recall query from queries.cypher §3, then `GRAPH.LIST`.
> "All of this is FalkorDB: recall is a ranked two-hop traversal, facts update by superseding instead of duplicating, task claims are a single conditional write — twenty racing agents, exactly one winner — and every tenant gets its own graph, so isolation is structural."

**[2:20–2:30 — Close, back to dashboard stats]**
> "RecallMesh: episodic, semantic and procedural memory that persists across sessions, is shared by every agent, and is safe under concurrency. The code and every Cypher query are in the repo. Thanks to FalkorDB and Graph Hacks."

---

**If Docker isn't available while recording:** run `STORAGE_BACKEND=memory uvicorn app.main:app --port 8000` for the UI flow, and show FalkorDB via the FalkorDB Cloud browser instead. Still record it today — an unlisted video link can be replaced in the form later only until the deadline (Oct 18, 11:59 PM IST), so don't wait.
