#!/usr/bin/env python3
# Birrwatch alerter v2 — evaluates armed alerts against rates.json, emails via
# Resend, marks triggered alerts done. v2: normalizes pair/dir casing, validates
# target + email, and LOGS every evaluation so nothing is ever silent.

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
    """Alert mids match the website's convention: USD/EUR/... = average across
    BANK sources only (bureaus are cash, a different market); USDT = the P2P
    parallel source."""
    sums = {}
    for r in doc.get("rates", []):
        try:
            cur = str(r["currency"]).upper()
            src = doc.get("sources", {}).get(r.get("source"), {})
            stype = src.get("type", "bank")
            mid = (float(r["buy"]) + float(r["sell"])) / 2
        except (KeyError, TypeError, ValueError):
            continue
        if r.get("flag") == "stale":
            continue
        if cur == "USDT":
            if stype == "market":
                sums.setdefault(cur, []).append(mid)
        elif stype == "bank":
            sums.setdefault(cur, []).append(mid)
    return {cur: sum(v) / len(v) for cur, v in sums.items() if v}


def clean_email(e):
    """Strip whitespace and any non-ASCII characters (invisible copy-paste
    artifacts from phone keyboards)."""
    return "".join(ch for ch in str(e or "") if 32 <= ord(ch) < 127).strip()


def send(to, subject, body):
    if not API_KEY:
        print(f"[dry-run] would email {to}: {subject}", flush=True)
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
        aid = a.get("id", "?")
        if a.get("status") != "armed":
            continue

        # ---- normalize everything; never trust hand-typed input ----
        cur = str(a.get("pair", "")).strip().upper()
        direction = str(a.get("dir", "")).strip().lower()
        try:
            target = float(str(a.get("target", "")).strip())
        except (TypeError, ValueError):
            a["status"] = "invalid"; changed = True
            print(f"[eval] {aid}: INVALID target ({a.get('target')!r}) — quarantined", flush=True)
            continue
        addr = clean_email(a.get("email"))
        if not re.fullmatch(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}", addr):
            a["status"] = "invalid"; changed = True
            print(f"[eval] {aid}: INVALID email after cleaning — quarantined", flush=True)
            continue
        if direction not in ("above", "below"):
            a["status"] = "invalid"; changed = True
            print(f"[eval] {aid}: INVALID direction ({a.get('dir')!r}) — must be above/below", flush=True)
            continue

        mid = m.get(cur)
        hit = (mid is not None) and (
            (direction == "above" and mid >= target) or
            (direction == "below" and mid <= target))
        print(f"[eval] {aid}: {cur} mid={mid if mid is not None else 'NONE'} "
              f"{direction} {target:g} -> hit={hit}", flush=True)

        if mid is None:
            print(f"[eval] {aid}: no rate available for {cur} this run", flush=True)
            continue
        if not hit:
            continue

        ok = send(addr,
            f"Birrwatch alert: {cur}/ETB is {mid:.2f}",
            f"Your alert triggered.\n\n{cur}/ETB is now {mid:.2f} ETB "
            f"(you asked for {'>=' if direction=='above' else '<='} {target:g}).\n\n"
            f"Source mid across collected banks. Indicative only — confirm with your bank.\n"
            f"https://birrwatch.et/")
        if ok:
            a["status"] = "done"
            a["triggered_at"] = doc.get("meta", {}).get("generated_at", "")
            state[aid] = a["triggered_at"]
            changed = True
            print(f"[alert] {aid} fired -> {addr}", flush=True)

    if changed:
        ALERTS.write_text(json.dumps(alerts, indent=1) + "\n", encoding="utf-8")
        STATE.write_text(json.dumps(state, indent=1) + "\n", encoding="utf-8")
    print(f"[alerter] {len([x for x in alerts if x.get('status')=='armed'])} armed · done", flush=True)


if __name__ == "__main__":
    sys.exit(main())