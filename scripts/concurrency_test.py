"""High-concurrency check: 60 parallel writers + readers against the API,
plus 20 agents racing to claim ONE task (exactly one must win).

Usage:  python scripts/concurrency_test.py [base_url]
"""
import concurrent.futures as cf
import json
import sys
import time
import urllib.request

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://localhost:8000"
TENANT = "loadtest"


def call(path, payload=None, method=None):
    req = urllib.request.Request(BASE + path,
        data=json.dumps(payload).encode() if payload is not None else None,
        headers={"Content-Type": "application/json"},
        method=method or ("POST" if payload is not None else "GET"))
    try:
        with urllib.request.urlopen(req) as r:
            return r.status, json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        return e.code, {}


def write(i):
    return call("/api/remember", {"tenant": TENANT, "kind": "semantic",
        "title": f"Concurrent fact {i}", "content": f"Written in parallel, writer {i}",
        "entities": ["Atlas"]})[0]


def read(i):
    return call(f"/api/recall?tenant={TENANT}&q=Atlas")[0]


if __name__ == "__main__":
    call(f"/api/reset?tenant={TENANT}", {}, method="POST")
    t0 = time.time()
    with cf.ThreadPoolExecutor(max_workers=30) as ex:
        writes = list(ex.map(write, range(60)))
        reads = list(ex.map(read, range(60)))
    dt = time.time() - t0
    print(f"60 writes + 60 reads in {dt:.2f}s — writes ok: {writes.count(200)}, reads ok: {reads.count(200)}")

    _, task = call("/api/tasks", {"tenant": TENANT, "title": "One task, twenty racers", "created_by": "planner"})
    with cf.ThreadPoolExecutor(max_workers=20) as ex:
        results = list(ex.map(lambda i: call(
            f"/api/tasks/{task['id']}/claim?tenant={TENANT}&agent_id=racer-{i}", {}, method="POST")[0],
            range(20)))
    print(f"Claim race: 200 (won) x{results.count(200)} · 409 (lost, correctly) x{results.count(409)}")
    assert results.count(200) == 1, "Exactly one agent must win the claim"
    print("PASS: exactly one winner — claims are atomic.")
