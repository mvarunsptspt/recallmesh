"""Seed + run the demo against a running RecallMesh server.

Usage:  python scripts/seed_demo.py [base_url] [tenant]
"""
import json
import sys
import urllib.request

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://localhost:8000"
TENANT = sys.argv[2] if len(sys.argv) > 2 else "demo"


def call(path, payload=None):
    req = urllib.request.Request(BASE + path,
        data=json.dumps(payload).encode() if payload is not None else None,
        headers={"Content-Type": "application/json"},
        method="POST" if payload is not None else "GET")
    with urllib.request.urlopen(req) as r:
        return json.loads(r.read())


if __name__ == "__main__":
    print("Health:", call("/health"))
    result = call("/api/demo/run", {"tenant": TENANT})
    for s in result["steps"]:
        print("\n▸", s["step"])
    print("\nStats:", json.dumps(result["stats"], indent=2))
    print(f"\nOpen {BASE} in a browser to explore the graph.")
