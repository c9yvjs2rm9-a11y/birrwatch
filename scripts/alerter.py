#!/usr/bin/env python3
# Birrwatch alerter — evaluates armed alerts against rates.json, emails via
# Resend, marks triggered alerts done. Runs after the collector.
import json, os, re, sys
from pathlib import Path
import requests

ROOT = Path(__file__).resolve().parents[1]
RATES = ROOT / "data" / "rates.json"
ALERTS = ROOT / "data" / "alerts.json"
STATE = ROOT / "data" / "alerts_state.json"

API_KEY = os.environ.get("RESEND_API_KEY", "")
FROM = os.environ.get("ALERT_FROM", "Birrwatch Alerts <alerts@birrwatch.et>")

def mids(doc):
    m = {}
    for r in doc.get("rates", []):
        try:
            m[r["currency"]] = (float(r["buy"]) + float(r["sell"])) / 2
        except (KeyError, TypeError, ValueError):
            continue
    return m
def clean_email(e):
    """Strip whitespace and any non-ASCII characters (invisible copy-paste
    artifacts from phone keyboards), then keep only plain printable ASCII."""
    return "".join(ch for ch in str(e or "") if 32 <= ord(ch) < 127).strip()
def send(to, subject, body):
    if not API_KEY:
        print(f"[dry-run] would email {to}: {subject}")
        return True
    r = requests.post("https://api.resend.com/emails",
        headers={"Authorization": f"Bearer {API_KEY}", "Content-Type": "application/json"},
        json={"from": FROM, "to": [to], "subject": subject,
              "text": body}, timeout=30)
    if r.status_code not in (200, 202):
        print(f"[send] FAILED {r.status_code}: {r.text[:300]}", flush=True)
        return r.status_code in (200, 202)

def main():
    doc = json.loads(RATES.read_text(encoding="utf-8"))
    alerts = json.loads(ALERTS.read_text(encoding="utf-8")) if ALERTS.exists() else []
    state = json.loads(STATE.read_text(encoding="utf-8")) if STATE.exists() else {}
    m = mids(doc)
    changed = False
    for a in alerts:
        if a.get("status") != "armed":
            continue
        cur = a["pair"]; mid = m.get(cur)
        if mid is None:
            continue
        hit = (a["dir"] == "above" and mid >= a["target"]) or \
              (a["dir"] == "below" and mid <= a["target"])
        if not hit:
            continue
        addr = clean_email(a.get("email"))
        if not re.fullmatch(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}", addr):
            a["status"] = "invalid"
            changed = True
            print(f"[alert] {a['id']} skipped — email invalid after cleaning", flush=True)
            continue
        ok = send(addr,
            f"Birrwatch alert: {cur}/ETB is {mid:.2f}",
            f"Your alert triggered.\n\n{cur}/ETB is now {mid:.2f} ETB "
            f"(you asked for {'≥' if a['dir']=='above' else '≤'} {a['target']}).\n\n"
            f"Source mid across collected banks. Indicative only — confirm with your bank.\n"
            f"https://birrwatch.pages.dev/")
        if ok:
            a["status"] = "done"
            a["triggered_at"] = doc.get("meta", {}).get("generated_at", "")
            state[a["id"]] = a["triggered_at"]
            changed = True
            print(f"[alert] {a['id']} {cur} {a['dir']} {a['target']} -> {a['email']}")
    if changed:
        ALERTS.write_text(json.dumps(alerts, indent=1) + "\n", encoding="utf-8")
        STATE.write_text(json.dumps(state, indent=1) + "\n", encoding="utf-8")
    print(f"[alerter] {len([a for a in alerts if a.get('status')=='armed'])} armed · done")

if __name__ == "__main__":
    sys.exit(main())