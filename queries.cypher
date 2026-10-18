// ============================================================================
// RecallMesh — the Cypher the product actually depends on
// Graph: one FalkorDB graph per tenant, named recallmesh_<tenant>
// Nodes: (:User) (:Agent) (:Memory {kind, status, confidence, version})
//        (:Entity) (:Conversation) (:Message) (:Task)
// Edges: (:User)-[:HAS_MEMORY]->(:Memory)   (:Agent)-[:WROTE]->(:Memory)
//        (:Memory)-[:ABOUT]->(:Entity)      (:Memory)-[:SUPERSEDES]->(:Memory)
//        (:Conversation)-[:HAS_MESSAGE]->(:Message)
//        (:Agent)-[:HANDED_OFF_TO {task_id, at, note}]->(:Agent)
//        (:Agent)-[:WORKING_ON]->(:Task)   (:Task)-[:USES]->(:Memory)
// ============================================================================

// --- 1. WRITE A MEMORY (episodic / semantic / procedural) -------------------
MATCH (u:User {id: $user_id})
CREATE (m:Memory {id: $id, kind: $kind, title: $title, content: $content,
                  fact_type: $fact_type, confidence: $confidence,
                  status: 'active', version: 1, session_id: $session_id,
                  created_at: $ts, updated_at: $ts})
CREATE (u)-[:HAS_MEMORY]->(m)
WITH m
OPTIONAL MATCH (a:Agent {id: $agent_id})
CREATE (a)-[:WROTE]->(m)
RETURN m;

// Link a memory to the entities it is about (MERGE = safe under concurrency)
MATCH (m:Memory {id: $memory_id})
MERGE (e:Entity {name: $entity_name})
CREATE (m)-[:ABOUT]->(e)
RETURN e;

// --- 2. FACTS UPDATE OVER TIME (supersede, never silently overwrite) --------
MATCH (u:User {id: $user_id})-[:HAS_MEMORY]->
      (old:Memory {kind: 'semantic', title: $title, status: 'active'})
SET old.status = 'superseded'
RETURN old;
// ...then write the new version (query 1) and link it:
// CREATE (new)-[:SUPERSEDES]->(old)

// --- 3. RECALL — the core traversal ------------------------------------------
// Ranked by confidence x recency, boosted by entity matches with the query
// and by 2-hop neighbours: memories that share an entity with this one.
MATCH (u:User {id: $user_id})-[:HAS_MEMORY]->(m:Memory {status: 'active'})
OPTIONAL MATCH (m)-[:ABOUT]->(e:Entity)
WITH m, collect(e.name) AS entities,
     [x IN collect(e.name) WHERE toLower(x) IN $wanted_entities] AS matched
OPTIONAL MATCH (m)-[:ABOUT]->(shared:Entity)<-[:ABOUT]-(other:Memory {status: 'active'})
WHERE other <> m
WITH m, entities, matched, count(DISTINCT other) AS graph_hops
RETURN m, entities, matched, graph_hops,
       m.confidence + 0.5 * size(matched) + 0.1 * graph_hops AS score
ORDER BY score DESC
LIMIT 10;

// Cross-agent recall is the SAME query: memories are attached to the User,
// not to the agent that wrote them, so a Planner-session traversal returns
// what the Researcher heard in an earlier session. That is by design.

// --- 4. HANDOFF — Planner -> Executor, context travels as graph edges -------
MATCH (a:Agent {id: $from_agent}), (b:Agent {id: $to_agent})
CREATE (a)-[:HANDED_OFF_TO {task_id: $task_id, at: $ts, note: $note}]->(b)
WITH b
OPTIONAL MATCH (t:Task {id: $task_id})
SET t.status = 'HANDED_OFF', t.assignee = $to_agent
RETURN b;

// What has been handed to me, and with what context?
MATCH (other:Agent)-[h:HANDED_OFF_TO]->(me:Agent {id: $agent_id})
OPTIONAL MATCH (t:Task {id: h.task_id})-[:USES]->(m:Memory)
RETURN other.id AS from_agent, h.task_id AS task_id, h.note AS note,
       collect(m) AS context_memories
ORDER BY h.at DESC;

// --- 5. ATOMIC TASK CLAIM — high-concurrency safe -----------------------------
// The status predicate is INSIDE the match: under a race, only the first
// writer matches status='OPEN'. Everyone else matches nothing -> HTTP 409.
MATCH (t:Task {id: $task_id}), (a:Agent {id: $agent_id})
WHERE t.status = 'OPEN' OR (t.status = 'HANDED_OFF' AND t.assignee = $agent_id)
SET t.status = 'IN_PROGRESS', t.assignee = $agent_id, t.updated_at = $ts
CREATE (a)-[:WORKING_ON]->(t)
RETURN t;

// --- 6. CONVERSATION HISTORY (persistent, per user) --------------------------
MERGE (c:Conversation {id: $conversation_id}) SET c.user_id = $user_id
CREATE (msg:Message {id: $id, role: $role, text: $text,
                     agent_id: $agent_id, created_at: $ts})
CREATE (c)-[:HAS_MESSAGE]->(msg)
RETURN msg;

MATCH (c:Conversation {user_id: $user_id})-[:HAS_MESSAGE]->(m:Message)
RETURN m ORDER BY m.created_at;

// --- 7. PROCEDURAL MEMORY — how the team does a thing ------------------------
MATCH (u:User {id: $user_id})-[:HAS_MEMORY]->
      (p:Memory {kind: 'procedural', status: 'active'})
RETURN p ORDER BY p.confidence DESC;

// --- 8. GRAPH ALGORITHMS WE RELY ON ------------------------------------------
// (a) Shortest path between two agents through handoffs/tasks — used to audit
//     "how did this work reach this agent, and what context travelled with it?"
MATCH p = shortestPath((a:Agent {id: $from})-[*..6]-(b:Agent {id: $to}))
RETURN p;

// (b) Entity hubs: the entities connecting the most memories are what the
//     user talks about most — surfaced on the dashboard as memory hubs.
MATCH (e:Entity)<-[:ABOUT]-(m:Memory {status: 'active'})
RETURN e.name AS entity, count(m) AS memories
ORDER BY memories DESC LIMIT 10;

// (c) Duplicate / near-duplicate fact detection before writing a new fact:
MATCH (u:User {id: $user_id})-[:HAS_MEMORY]->(m:Memory {status: 'active'})
WHERE toLower(m.title) CONTAINS toLower($keyword)
RETURN m;

// --- 9. TENANT ISOLATION ------------------------------------------------------
// Structural, not a filter: GRAPH.LIST shows one graph per tenant and every
// query above runs inside exactly one tenant's graph.
//   GRAPH.LIST
//   GRAPH.QUERY recallmesh_acme "MATCH (n) RETURN n"   // acme only, ever
