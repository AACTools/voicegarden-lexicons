#!/usr/bin/env python3
"""Print the results/metrics.json leaderboard."""
import json

rows = json.load(open("results/metrics.json"))
print(f"{'lang':5} {'entries':>7} {'G2P exact%':>10} {'PER%':>5} | {'P2G exact%':>10} {'CER%':>5} {'cov%':>5}")
for r in sorted(rows, key=lambda r: -r.get("entries", 0)):
    g, p = r.get("g2p", {}), r.get("p2g", {})
    print(f"{r['lang']:5} {r.get('entries', 0):>7} {g.get('exact', 0):>10.1f} {g.get('per', 0):>5.1f} "
          f"| {p.get('exact', 0):>10.1f} {p.get('cer', 0):>5.1f} {p.get('coverage', 0):>5.1f}")
