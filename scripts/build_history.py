#!/usr/bin/env python3
"""Birrwatch history builder: appends today's rates to history.jsonl
and rebuilds trends.json for the website. Standard library only."""
import json
from datetime import date, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
RATES, HIST, TRENDS = DATA / "rates.json", DATA / "history.jsonl", DATA / "trends.json"

doc = json.loads(RATES.read_text(encoding="utf-8"))
mids, offs, n = {}, {}, 0
for r in doc.get("rates") or []:
    try:
        buy, sell = float(r["buy"]), float(r["sell"])
    except (KeyError, TypeError, ValueError):
        continue
    if not (0 < buy < 1_000_000 and 0 < sell < 1_000_000):
        continue
    n += 1
    mid = (buy + sell) / 2
    cur = str(r.get("currency", "")).upper()
    stype = (doc.get("sources") or {}).get(r.get("source"), {}).get("type", "bank")
    if stype == "official":
        offs[cur] = mid
    else:
        mids.setdefault(cur, []).append(mid)

if n == 0:
    raise SystemExit("rates.json has no usable quotes — nothing recorded. (Leftover 0.00?)")

day = (doc.get("meta") or {}).get("generated_at", "")[:10] or date.today().isoformat()
rec = {"date": day,
       "mid": {c: sum(v) / len(v) for c, v in mids.items()},
       "official": offs}

recs = [json.loads(l) for l in (HIST.read_text(encoding="utf-8").splitlines() if HIST.exists() else []) if l.strip()]
recs = [r for r in recs if r.get("date") != day]  # re-running same day = safe corrections
recs.append(rec)
recs.sort(key=lambda r: r["date"])
HIST.write_text("\n".join(json.dumps(r, separators=(",", ":")) for r in recs) + "\n", encoding="utf-8")

if len(recs) < 2:
    print(f"recorded {day} — trends.json starts with the 2nd day of data")
else:
    def fill(vals):
        prev = next((v for v in vals if v is not None), None)
        out = []
        for v in vals:
            if v is not None:
                prev = v
            out.append(prev)
        return out
    currencies = sorted({c for r in recs for c in (r.get("mid") or {})})
    series = {c: {"mid": fill([(r.get("mid") or {}).get(c) for r in recs]),
                  "official": fill([(r.get("official") or {}).get(c) for r in recs])}
              for c in currencies}
    trends = {"meta": {"generated_at": datetime.utcnow().isoformat(timespec="seconds") + "Z"},
              "dates": [r["date"] for r in recs], "series": series}
    TRENDS.write_text(json.dumps(trends, separators=(",", ":")), encoding="utf-8")
    print(f"history: {len(recs)} days · {', '.join(currencies)}")