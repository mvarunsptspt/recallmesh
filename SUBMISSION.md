# SUBMISSION FORM — copy-paste each field into the Graph Hacks form

> Replace the two bracketed links (Repository, Demo video) after you upload.
> Everything else is final.

---

## Project title

RecallMesh — Shared Agent Memory & Coordination, powered by FalkorDB

## Description  *(What problem does your project solve, and who is it for?)*

Multi-agent systems forget. Each agent keeps its own transcript, so switching agents, starting a new session, or adding a concurrent worker loses — or contradicts — what the user already said, and users are forced to repeat themselves while agents act on partial facts.

RecallMesh fixes this by putting agent memory in one shared FalkorDB graph. Memories (episodic, semantic and procedural) belong to the user, not to any agent, and are linked to the entities they are about. Any agent, in any later session, recalls them with a ranked Cypher traversal. Facts update by superseding old versions instead of duplicating them. Agents hand work to each other as graph edges with the relevant memories attached, shared tasks are claimed with a single conditional Cypher write so exactly one of many racing agents wins, and each tenant gets its own FalkorDB graph for structural isolation.

Built for teams building multi-agent products — support, ops, research and personal-assistant systems — that must survive restarts, agent swaps and concurrency with one consistent, auditable memory. Demo story: a Researcher learns in Session 1 that the user is allergic to peanuts, Atlas launches Nov 20 and Priya owns design; days later a Planner that never heard that session recalls all of it, plans around the allergy, and hands off to an Executor, which finishes the work and writes it back for every agent to see.

## What track are you submitting for?

☑ **Agent Memory and Coordination**  *(select only this one)*

## Repository

[PASTE YOUR PUBLIC GITHUB REPO URL HERE — e.g. https://github.com/<you>/recallmesh]

## Demo video  *(YouTube, public or unlisted)*

[PASTE YOUTUBE LINK HERE — record with DEMO_VIDEO_SCRIPT.md, ~2.5 minutes]

## Live demo or deployment

If deployed: [PASTE URL]
If not deployed, paste this line instead:
Local deployment — `docker compose up --build`, then open http://localhost:8000 (full instructions in README; FalkorDB Browser on http://localhost:3000)

## How did you use FalkorDB in your project?  *(technical problems solved)*

FalkorDB is the primary and only memory store — remove it and the agents have no memory, no recall, no handoffs and no task board.

1. Shared cross-session memory as a graph: (:User)-[:HAS_MEMORY]->(:Memory) with (:Memory)-[:ABOUT]->(:Entity), so recall is a ranked 2-hop Cypher traversal (confidence × recency decay + entity-match and shared-entity-neighbour boosts), not vector similarity. Because memories attach to the User rather than the writing agent, a Planner in a new session recalls what a Researcher heard days earlier.
2. Memory that updates: rewriting a semantic fact marks the previous node superseded and links the new version with a SUPERSEDES edge — one active truth, full history.
3. Coordination as edges: handoffs are (:Agent)-[:HANDED_OFF_TO]->(:Agent) relationships carrying the task id and note, with (:Task)-[:USES]->(:Memory) so context travels with the work; shortestPath audits how work travelled between agents.
4. Concurrency: MERGE upserts and an atomic task claim — a single conditional Cypher write (WHERE status='OPEN', or HANDED_OFF to that agent) — so 20 racing agents yield exactly one winner (verified: 1×200, 19×409; plus 60 parallel writes + 60 parallel reads).
5. Tenant isolation: one FalkorDB graph per tenant (recallmesh_<tenant>), so isolation is structural rather than a filter.
6. Graph algorithms: shortestPath for handoff auditing and entity degree ranking to surface memory hubs.

All queries are in queries.cypher in the repository.

## Blog link  *(optional, AirPods prize — post BLOG.md on dev.to / Hashnode / Medium)*

[PASTE BLOG URL HERE after publishing BLOG.md]

---

# Feedback section (Part 2 of the form)

## What did you like about FalkorDB?

The speed of going from a whiteboard graph model to working Cypher was the highlight — the Redis-based engine made traversals feel instant even with the recall query doing entity matching and a 2-hop neighbourhood count in one pass. Running it was painless: one Docker container, and the FalkorDB Browser made it easy to show judges the actual memory graph forming live. Using a separate graph per tenant turned multi-tenancy from a filtering chore into a one-line design decision, and being able to express the atomic task claim as a single conditional write kept the coordination logic entirely in the database, where it belongs.

## What improvements would you like to see in FalkorDB?

Three things would have made this build even smoother: (1) more worked examples and recipes for common agent-memory patterns — temporal facts, superseding/versioning, and ranking by recency — in the docs; (2) a lighter first-run experience for the Python client, especially clearer connection errors when the server is unreachable; and (3) built-in vector + graph hybrid helpers, so semantic similarity could be combined with traversal ranking in one query instead of layering two systems. A hosted free tier with one-click graph browser sharing would also help hackathon teams demo their graph to judges.
