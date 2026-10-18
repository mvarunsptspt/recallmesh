const $ = id => document.getElementById(id);
const tenant = () => $("tenant").value.trim() || "demo";
const api = async (path, opts={}) => {
  const r = await fetch(path, {headers: {"Content-Type": "application/json"}, ...opts});
  if (!r.ok) throw new Error(await r.text());
  return r.json();
};
const esc = s => String(s ?? "").replace(/[&<>"]/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c]));
const memCard = m => `<div class="mem ${esc(m.kind)}"><span class="score">score ${m.score ?? "—"} · conf ${m.confidence}</span><b>${esc(m.title)}</b><br/><span class="pill">${esc(m.kind)}</span> <span class="pill">${esc(m.fact_type || "note")}</span><br/>${esc(m.content)}</div>`;

async function refresh() {
  const [stats, tasks, handoffs, timeline, graph] = await Promise.all([
    api(`/api/stats?tenant=${tenant()}`), api(`/api/tasks?tenant=${tenant()}`),
    api(`/api/handoffs?tenant=${tenant()}`), api(`/api/timeline?tenant=${tenant()}`),
    api(`/api/graph?tenant=${tenant()}`)]);
  $("stats").innerHTML = `Backend: <b>${esc(stats.backend)}</b> · Memories: <b>${stats.memories_total}</b> ` +
    `(episodic ${stats.memories_by_kind.episodic} · semantic ${stats.memories_by_kind.semantic} · procedural ${stats.memories_by_kind.procedural}) · ` +
    `Entities: ${stats.entities} · Agents: ${stats.agents} · Tasks: ${stats.tasks} · Handoffs: ${stats.handoffs} · Messages: ${stats.messages}`;
  $("tasks").innerHTML = tasks.length ? tasks.map(t =>
    `<div class="task"><b>${esc(t.title)}</b> <span class="pill">${esc(t.status)}</span> ${t.assignee ? `<span class="pill">@${esc(t.assignee)}</span>` : ""}<br/>${esc(t.description || "")}${t.result ? `<br/>✅ ${esc(t.result)}` : ""}</div>`).join("") : "No tasks yet — run the demo or ask the Planner to build a plan.";
  $("handoffs").innerHTML = handoffs.length ? handoffs.map(h =>
    `<div class="task">🤝 <b>${esc(h.from_agent)}</b> → <b>${esc(h.to_agent)}</b> · ${esc(h.created_at)}<br/>${esc(h.note)}<br/><span class="pill">${(h.memory_ids||[]).length} memories attached</span></div>`).join("") : "No handoffs yet.";
  $("timeline").innerHTML = timeline.slice(0, 12).map(memCard).join("") || "Nothing remembered yet.";
  drawGraph(graph);
}

function drawGraph({nodes, edges}) {
  const svg = $("viz"), W = svg.clientWidth || 600, H = 420;
  const colors = {User:"#fbbf24", Agent:"#4ade80", Memory:"#8b7cf6", Entity:"#e86ea8", Task:"#60a5fa", Conversation:"#9a97b5"};
  const kindColor = {episodic:"#60a5fa", semantic:"#e86ea8", procedural:"#4ade80"};
  const pos = new Map();
  nodes.forEach((n, i) => {
    const a = (i / Math.max(nodes.length, 1)) * Math.PI * 2;
    const r = 90 + (i % 3) * 55;
    pos.set(n.id, {x: W/2 + Math.cos(a)*r*1.35, y: H/2 + Math.sin(a)*r*0.8, n});
  });
  let html = edges.map(e => {
    const a = pos.get(e.src), b = pos.get(e.dst); if (!a || !b) return "";
    return `<line x1="${a.x}" y1="${a.y}" x2="${b.x}" y2="${b.y}" stroke="#33334d" stroke-width="1"/>`;
  }).join("");
  html += [...pos.values()].map(({x, y, n}) => {
    const c = n.label === "Memory" ? (kindColor[n.kind] || colors.Memory) : (colors[n.label] || "#aaa");
    const label = esc((n.name || n.title || n.id || "").slice(0, 22));
    return `<circle cx="${x}" cy="${y}" r="9" fill="${c}"><title>${esc(n.label)}: ${label}</title></circle><text x="${x+12}" y="${y+4}" fill="#cfcbe8" font-size="10.5">${label}</text>`;
  }).join("");
  svg.innerHTML = html || `<text x="20" y="30" fill="#9a97b5">No graph yet — run the demo.</text>`;
}

$("runDemo").onclick = async () => {
  $("runDemo").textContent = "Running…";
  try {
    const d = await api("/api/demo/run", {method: "POST", body: JSON.stringify({tenant: tenant()})});
    $("teachOut").textContent = d.steps.map(s => `▸ ${s.step}`).join("\n") + `\n\nFinal stats: ${JSON.stringify(d.stats.memories_by_kind)} · ${d.stats.handoffs} handoff · ${d.stats.tasks} tasks`;
    await refresh();
  } catch (e) { $("teachOut").textContent = "Error: " + e.message; }
  $("runDemo").textContent = "▶ Run the 3-session demo";
};

$("teach").onclick = async () => {
  try {
    const d = await api("/api/messages", {method: "POST", body: JSON.stringify({
      tenant: tenant(), agent_id: $("teachAgent").value, text: $("teachText").value, session_id: $("session").value})});
    $("teachOut").textContent = `Heard by ${d.agent}. Extracted ${d.facts_extracted.length} memor${d.facts_extracted.length === 1 ? "y" : "ies"}:\n` +
      d.facts_extracted.map(f => `• [${f.kind}] ${f.title}`).join("\n");
    await refresh();
  } catch (e) { $("teachOut").textContent = "Error: " + e.message; }
};

const doRecall = async () => {
  const q = $("recallQ").value;
  const d = await api(`/api/recall?tenant=${tenant()}&q=${encodeURIComponent(q)}&agent_id=planner`);
  $("recallOut").innerHTML = d.results.length ? d.results.map(memCard).join("") : "No matching memories. Teach an agent first (box 1).";
};
$("recall").onclick = doRecall;

$("plan").onclick = async () => {
  const q = $("recallQ").value;
  const rec = await api(`/api/recall?tenant=${tenant()}&q=${encodeURIComponent(q)}`);
  const t = await api("/api/tasks", {method: "POST", body: JSON.stringify({tenant: tenant(), title: "Plan: " + q, description: `Built by Planner from ${rec.results.length} recalled memories.`, created_by: "planner", memory_ids: rec.results.slice(0,5).map(r => r.id)})});
  const h = await api("/api/handoffs", {method: "POST", body: JSON.stringify({tenant: tenant(), from_agent: "planner", to_agent: "executor", task_id: t.id, note: "Context is in the graph — do not re-ask the user.", memory_ids: rec.results.slice(0,5).map(r => r.id)})});
  $("recallOut").innerHTML = `<div class="task">🧭 Planner created task <b>${esc(t.title)}</b> from ${rec.results.length} recalled memories and handed it to Executor (handoff ${esc(h.id)}).</div>` + rec.results.map(memCard).join("");
  await refresh();
};

$("workNext").onclick = async () => {
  // Claim + complete the next open task as Executor, via the public API flow
  const tasks = await api(`/api/tasks?tenant=${tenant()}`);
  const next = tasks.find(t => ["OPEN", "HANDED_OFF"].includes(t.status));
  if (!next) { $("tasks").innerHTML = "No open tasks. Ask the Planner to build a plan first."; return; }
  if (next.status === "OPEN") await api(`/api/tasks/${next.id}/claim?tenant=${tenant()}&agent_id=executor`, {method: "POST"});
  await api(`/api/tasks/${next.id}/complete?tenant=${tenant()}&agent_id=executor&result=${encodeURIComponent("Executor completed '" + next.title + "' using shared graph context — no context was re-asked from the user.")}`, {method: "POST"});
  await refresh();
};

$("refresh").onclick = refresh;
$("reset").onclick = async () => { await api(`/api/reset?tenant=${tenant()}`, {method: "POST"}); await refresh(); };

(async () => {
  const h = await api("/health");
  $("backend").textContent = h.backend === "falkordb" ? "● FalkorDB connected" : "● Offline preview (start docker compose for FalkorDB)";
  $("backend").style.color = h.backend === "falkordb" ? "#4ade80" : "#fbbf24";
  await api("/api/agents?tenant=" + tenant());
  await refresh();
})();
