# My agents kept forgetting — so I gave them one shared brain in FalkorDB

*Publish this on dev.to / Hashnode / Medium and paste the URL into the submission form (best blog post wins AirPods 5). Suggested tags: `falkordb` `ai` `hackathon` `python` `graphdatabase`*

---

Every multi-agent demo I built this year had the same embarrassing moment.

Agent A would have a perfectly good conversation with the user. Then Agent B would take over — new session, same user — and cheerfully ask everything again. Or worse, it wouldn't ask: it would just act, confidently, on half the facts. The user had told *someone* about their peanut allergy. Just not *this* agent.

The problem wasn't the models. It was that "memory" in my projects meant a transcript owned by one agent. Memory that isn't shared isn't memory — it's a diary nobody else can read.

So for **Graph Hacks 2026 (Track 2: Agent Memory & Coordination)** I built **RecallMesh**: three agents — a Researcher, a Planner and an Executor — that keep *nothing* in their heads. Everything they know lives in one **FalkorDB graph**, and everything they do to coordinate happens as graph writes and traversals.

## The model: memories belong to the user, not the agent

The one decision everything else follows from:

```cypher
(:User)-[:HAS_MEMORY]->(:Memory)-[:ABOUT]->(:Entity)
(:Agent)-[:WROTE]->(:Memory)
```

Memories hang off the **User**. The agent that wrote one is just an edge. That single choice means a Planner starting a brand-new session on Thursday recalls — with one traversal — what the Researcher heard on Monday.

Memory comes in the three flavours the track asks for:

- **Episodic** — every conversation turn and every completed task becomes an episode node.
- **Semantic** — facts extracted from conversation: *"allergic to peanuts"*, *"Atlas launches Nov 20"*, *"Priya owns design"*.
- **Procedural** — how things are done: *"standup is at 9:30 am"*.

## Facts should update, not duplicate

Tell an agent *"actually, the launch moved to Nov 22"* and a naive memory store now holds two contradictory facts. RecallMesh **supersedes**: the old node is marked `status:'superseded'`, the new one links to it with a `SUPERSEDES` edge, and recall only ever returns the active version. One truth, full history, nothing deleted.

## Recall is a traversal, not a similarity search

RecallMesh ranks memories with a Cypher query that combines confidence, recency decay, how many of the query's entities the memory is about, and a 2-hop boost for memories that share entities with other memories:

```cypher
MATCH (u:User {id: $user_id})-[:HAS_MEMORY]->(m:Memory {status: 'active'})
OPTIONAL MATCH (m)-[:ABOUT]->(e:Entity)
-- entity matches + shared-entity neighbours feed the score
RETURN m ORDER BY score DESC LIMIT 10
```

Why this matters: the Planner doesn't just need memories *similar* to "plan the launch". It needs the deadline, the owner — and the allergy, every time, whatever the goal was. Safety facts get recalled deliberately, not hopefully.

## Coordination is edges, all the way down

Agents in RecallMesh never call each other. The Planner hands work to the Executor by writing a relationship:

```cypher
(:Planner)-[:HANDED_OFF_TO {task_id, note}]->(:Executor)
(:Task)-[:USES]->(:Memory)   -- the context travels with the work
```

And when twenty agents race for one shared task, the claim is a **single conditional write** — the `status='OPEN'` predicate is inside the match, so exactly one writer wins and the other nineteen get a clean `409`. I tested it: 20 racers, 1 winner. Plus 60 parallel writes and 60 parallel reads against the API, all clean.

Multi-tenancy fell out of the database design too: **each tenant gets its own FalkorDB graph** (`recallmesh_<tenant>`), so isolation is structural. There is no `WHERE tenant = ...` clause to forget.

## The demo that sells it

1. **Session 1:** I tell the Researcher five things in one sentence.
2. **Session 2:** I ask a *different* agent, in a new session, to plan — and watch it recall the deadline, the owner, and the allergy it never heard.
3. **Handoff → Session 3:** the Executor picks the task up from the graph and writes its result back where the Researcher can see it.

Watching the graph light up in the FalkorDB Browser while this happened was the most convincing part of the whole build.

## What I'd do next

Swap the rule-based fact extractor for an LLM (the interface is one function), add vector-seeded entity linking, and put a decay job on episodic memory. The graph model doesn't change for any of that — which is kind of the point.

**Code, Cypher and setup:** [your GitHub repo link]

*Built for Graph Hacks 2026, powered by FalkorDB. An AI coding assistant helped scaffold parts of the code; the graph model, and every design decision above, are mine and documented in the repo.*
