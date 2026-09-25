#!/usr/bin/env python3
# Birrwatch robot collector — visits bank rate pages, updates data/rates.json.
#
# TO FIX OR ADD A BANK:
#   1. Open the bank's exchange-rate page in your browser (numbers visible
#      immediately, without clicking any button) and copy its address.
#   2. In SOURCES below, paste that address as the FIRST entry in that bank's
#      "urls" list. Keep the quotation marks and commas exactly as they are.
#   3. Commit, then run: Actions tab -> collector -> Run workflow.
# If a bank keeps failing, nothing breaks — its previous numbers remain and
# you can still type that bank's rates by hand into data/rates.json.

import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

import requests
from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parents[1]
RATES = ROOT / "data" / "rates.json"

WANT = ("USD", "EUR")      # currencies the robot collects
MAX_JUMP = 0.15            # ignore a fetched value that moved >15% vs stored (parse-error guard)

HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; BirrwatchBot/1.0)"}

SOURCES = {
    "CBE": {"name": "Commercial Bank of Ethiopia", "type": "bank", "urls": [
        "https://combanketh.et/exchange-rate",
        "https://combanketh.et/",
    ]},
    "AWB": {"name": "Awash Bank", "type": "bank", "urls": [
        "https://www.awashbank.com/exchange-rate/",
        "https://www.awashbank.com/",
    ]},
    "DBL": {"name": "Dashen Bank", "type": "bank", "urls": [
        "https://dashenbanksc.com/exchange-rate/",
        "https://dashenbanksc.com/",
    ]},
    "BOA": {"name": "Bank of Abyssinia", "type": "bank", "urls": [
        "https://www.bankofabyssinia.com/exchange-rate-2/",
        "https://bankofabyssinia.com/",
    ]},
    "CBO": {"name": "Cooperative Bank of Oromia", "type": "bank", "urls": [
        "https://coopbankoromia.com.et/daily-exchange-rates/?er_date=2026-09-25&utm_source=exchange.et&utm_medium=referral&utm_campaign=data-sources",
        "https://coopbankoromi.com.et/",
    ]},
}

# ---------- parsing ----------
NUM = re.compile(r"\d[\d,]*(?:\.\d+)?")
BUY_W = ("BUY", "BUYING", "BID", "PURCHAS")
SELL_W = ("SELL", "SELLING", "OFFER", "ASK", "SOLD")
CASH_W = ("CASH", "NOTE", "BANKNOTE")


def norm(s):
    return re.sub(r"\s+", " ", re.sub(r"[^A-Za-z]", " ", (s or ""))).strip().upper()


def match_currency(text):
    t = norm(text)
    toks = set(t.split())
    if "USD" in toks:
        return "USD"
    if "EUR" in toks:
        return "EUR"
    if "UNITED STATES" in t or ("US DOLLAR" in t and "AUSTRALIAN" not in t):
        return "USD"
    if "EURO" in t and "BOND" not in t:
        return "EUR"
    return None


def role(text):
    t = norm(text)
    if any(w in t for w in BUY_W):
        return "buy"
    if any(w in t for w in SELL_W):
        return "sell"
    return None


def is_cash(text):
    t = norm(text)
    return any(w in t for w in CASH_W)


def number(cell):
    m = NUM.search(cell or "")
    if not m:
        return None
    try:
        return float(m.group().replace(",", ""))
    except ValueError:
        return None


def table_rows(table):
    rows = []
    for tr in table.find_all("tr"):
        cells = []
        for c in tr.find_all(["th", "td"]):
            try:
                span = int(c.get("colspan", 1) or 1)
            except (TypeError, ValueError):
                span = 1
            span = max(1, min(span, 8))
            txt = c.get_text(" ", strip=True)
            cells.extend([txt] * span)
        if cells:
            rows.append(cells)
    return rows


def detect_header(rows):
    # find the header row: a row whose cells (combined with the row below,
    # to handle two-row headers like "Buying | Cash | Transactional") contain
    # both buy and sell words. Prefer the cash columns.
    for i, row in enumerate(rows):
        nxt = rows[i + 1] if i + 1 < len(rows) else []
        width = max(len(row), len(nxt))
        buys, sells = [], []
        for j in range(width):
            combo = (row[j] if j < len(row) else "") + " " + (nxt[j] if j < len(nxt) else "")
            r = role(combo)
            if r == "buy":
                buys.append((j, is_cash(combo)))
            elif r == "sell":
                sells.append((j, is_cash(combo)))
        if buys and sells:
            b = next((j for j, cash in buys if cash), buys[0][0])
            s = next((j for j, cash in sells if cash), sells[0][0])
            if b != s:
                return i, b, s
    return None


def parse_page(html):
    soup = BeautifulSoup(html, "html.parser")
    best = {}
    for table in soup.find_all("table"):
        rows = table_rows(table)
        head = detect_header(rows)
        if not head:
            continue
        hi, bcol, scol = head
        out = {}
        for r in rows[hi + 1:]:
            if len(r) <= max(bcol, scol):
                continue
            cur = match_currency(r[0]) or match_currency(" ".join(r[:2]))
            if not cur or cur in out:
                continue
            buy, sell = number(r[bcol]), number(r[scol])
            if buy and sell and 20 < buy < 5000 and 20 < sell < 5000 and buy <= sell < buy * 1.25:
                out[cur] = (buy, sell)
        if len(out) > len(best):
            best = out
    return best


def fetch(url):
    for _ in range(2):
        try:
            r = requests.get(url, headers=HEADERS, timeout=30)
            if r.status_code == 200 and len(r.text) > 500:
                return r.text
        except Exception:
            pass
    return None


# ---------- main ----------
def write_summary(text):
    p = os.environ.get("GITHUB_STEP_SUMMARY")
    if p:
        with open(p, "a", encoding="utf-8") as f:
            f.write(text + "\n")


def main():
    if not RATES.exists():
        print("data/rates.json not found — nothing to update.")
        return 1
    doc = json.loads(RATES.read_text(encoding="utf-8"))
    sources = doc.setdefault("sources", {})
    rates = doc.setdefault("rates", [])
    old_gen = (doc.get("meta") or {}).get("generated_at", "")
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")

    # every source gets an honest freshness stamp; unknown ones inherit the file's old timestamp
    for s in sources.values():
        if not s.get("fetched_at"):
            s["fetched_at"] = old_gen or now

    quotes = {(r.get("source"), r.get("currency")): r for r in rates}

    summary = []
    applied_any = False

    for sid, cfg in SOURCES.items():
        got, err = {}, "page unreachable"
        for url in cfg["urls"]:
            html = fetch(url)
            if not html:
                continue
            try:
                got = parse_page(html)
            except Exception:
                got = {}
            if got:
                err = None
                break
            err = "no rate table found"
        if not got:
            summary.append(f"| {sid} | ✗ {err} — kept previous values |")
            continue
        kept = []
        for cur in WANT:
            if cur not in got:
                continue
            buy, sell = got[cur]
            prev = quotes.get((sid, cur))
            if prev and prev.get("buy"):
                try:
                    if abs(buy / float(prev["buy"]) - 1) > MAX_JUMP:
                        summary.append(f"| {sid} | ⚠ {cur} skipped — fetched {buy} vs stored {prev['buy']} (>15%) |")
                        continue
                except (TypeError, ZeroDivisionError):
                    pass
            q = quotes.get((sid, cur))
            if q:
                q["buy"], q["sell"] = buy, sell
            else:
                row = {"source": sid, "currency": cur, "buy": buy, "sell": sell}
                rates.append(row)
                quotes[(sid, cur)] = row
            kept.append(f"{cur} {buy}/{sell}")
        if kept:
            applied_any = True
            s = sources.setdefault(sid, {"name": cfg["name"], "type": cfg["type"]})
            s["name"], s["type"] = cfg["name"], cfg["type"]
            s["fetched_at"] = now
            summary.append(f"| {sid} | ✓ {', '.join(kept)} |")
        else:
            summary.append(f"| {sid} | ⚠ nothing usable — kept previous values |")

    if not applied_any:
        text = ("## Robot collection — FAILED\n\nNo bank could be read. "
                "rates.json was not changed.\n\n| Source | Result |\n|---|---|\n" + "\n".join(summary))
        print(text)
        write_summary(text)
        return 1

    doc.setdefault("meta", {})["generated_at"] = now
    RATES.write_text(json.dumps(doc, indent=1) + "\n", encoding="utf-8")

    ok = sum(1 for line in summary if "✓" in line)
    text = f"## Robot collection — {ok}/{len(SOURCES)} banks updated\n\n| Source | Result |\n|---|---|\n" + "\n".join(summary)
    print(text)
    write_summary(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())