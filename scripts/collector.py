#!/usr/bin/env python3
# Birrwatch robot collector v4 — visits bank rate pages, updates data/rates.json.
#
# TO FIX OR ADD A BANK:
#   1. Open the bank's rate page in your browser (numbers visible immediately,
#      without clicking anything) and copy its address.
#   2. In SOURCES below, paste that address as the FIRST entry in that bank's
#      "urls" list. Keep quotes and commas exactly as they are.
#   3. Commit, then run: Actions tab -> collector -> Run workflow.
# v4: tolerates broken site certificates (BOA), parses card-style layouts as
#     well as tables (AWB), retries flaky sites (CBO), skips average tables.

import json
import os
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import requests
from bs4 import BeautifulSoup

try:
    import urllib3
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
except Exception:
    pass

ROOT = Path(__file__).resolve().parents[1]
RATES = ROOT / "data" / "rates.json"

WANT = ("USD", "EUR")      # currencies the robot collects
MAX_JUMP = 0.15            # ignore a fetched value that moved >15% vs stored
MIN_SPREAD = 0.0008        # real quotes have >=0.08% spread; averages are flat

UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
HEADERS = {"User-Agent": UA}

SOURCES = {
    "CBE": {"name": "Commercial Bank of Ethiopia", "type": "bank", "urls": [
        "https://combanketh.et/exchange-rate/",
        "https://combanketh.et/exchange-rates/",
        "https://combanketh.et/exchange-rate",
        "https://combanketh.et/",
    ]},
    "AWB": {"name": "Awash Bank", "type": "bank", "urls": [
        "https://www.awashbank.com/exchange-rates/",
        "https://www.awashbank.com/exchange-rate/",
        "https://www.awashbank.com/rates/",
        "https://www.awashbank.com/",
    ]},
    "DBL": {"name": "Dashen Bank", "type": "bank", "urls": [
        "https://dashenbanksc.com/exchange-rate/",
        "https://dashenbanksc.com/",
    ]},
    "BOA": {"name": "Bank of Abyssinia", "type": "bank", "urls": [
        "https://bankofabyssinia.com/exchange-rate/",
        "https://bankofabyssinia.com/",
    ]},
    "CBO": {"name": "Cooperative Bank of Oromia", "type": "bank", "urls": [
        "https://coopbankoromi.com.et/exchange-rate/",
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


def plausible(b, s):
    return bool(b and s and 20 < b < 5000 and 20 < s < 5000
                and b <= s < b * 1.25 and (s - b) / b >= MIN_SPREAD)


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
        header_txt = norm(" ".join(rows[hi]) + " " + (" ".join(rows[hi + 1]) if hi + 1 < len(rows) else ""))
        if "AVERAGE" in header_txt:
            continue
        out = {}
        for r in rows[hi + 1:]:
            if len(r) <= max(bcol, scol):
                continue
            cur = match_currency(r[0]) or match_currency(" ".join(r[:2]))
            if not cur or cur in out:
                continue
            buy, sell = number(r[bcol]), number(r[scol])
            if plausible(buy, sell):
                out[cur] = (buy, sell)
        if len(out) > len(best):
            best = out
    return best


def parse_cards(html):
    """Fallback for banks that show rates as styled cards/tickers, not tables.
    Looks for small elements that mention a currency AND both a buy and a sell
    word, with at least two plausible numbers. Guards filter bad matches."""
    soup = BeautifulSoup(html, "html.parser")
    cands = []
    for el in soup.find_all(["div", "section", "article", "li", "span", "p"]):
        t = el.get_text(" ", strip=True)
        if not t or len(t) > 160:
            continue
        u = norm(t)
        cur = match_currency(u)
        if not cur:
            continue
        if not (any(w in u for w in BUY_W) and any(w in u for w in SELL_W)):
            continue
        nums = []
        for m in NUM.findall(t):
            try:
                v = float(m.replace(",", ""))
            except ValueError:
                continue
            if 20 < v < 5000:
                nums.append(v)
        if len(nums) < 2:
            continue
        buy, sell = nums[0], nums[1]
        if buy > sell:
            buy, sell = sell, buy
        cands.append((len(t), cur, buy, sell))
    cands.sort()          # prefer the most specific (smallest) card
    out = {}
    for _, cur, b, s in cands:
        if cur in out or not plausible(b, s):
            continue
        out[cur] = (b, s)
    return out


def parse_any(html):
    try:
        got = parse_page(html)
    except Exception:
        got = {}
    if not got:
        try:
            got = parse_cards(html)
        except Exception:
            got = {}
    return got


def diagnose(html):
    soup = BeautifulSoup(html, "html.parser")
    text = soup.get_text(" ", strip=True).upper()
    n = len(soup.find_all("table"))
    kw = any(w in text for w in BUY_W) and any(w in text for w in SELL_W)
    return n, kw


def short(url):
    return re.sub(r"^https?://(www\.)?", "", url).rstrip("/")[:34]


# ---------- fetching ----------
def attempt_static(url):
    last = "failed"
    for attempt in range(3):                     # retries for flaky sites (CBO)
        try:
            r = requests.get(url, headers=HEADERS, timeout=30)
            if r.status_code == 200 and len(r.text) > 500:
                return r.text, None
            last = f"HTTP {r.status_code}"
            if r.status_code == 404:
                return None, last                # wrong address — don't retry
        except requests.exceptions.SSLError:
            try:                                 # tolerate broken certificates (BOA)
                r = requests.get(url, headers=HEADERS, timeout=30, verify=False)
                if r.status_code == 200 and len(r.text) > 500:
                    return r.text, None
                last = f"HTTP {r.status_code} (ssl-relaxed)"
            except Exception as e:
                last = f"SSL ({type(e).__name__})"
        except requests.exceptions.Timeout:
            last = "timeout"
        except Exception as e:
            last = type(e).__name__
        if attempt < 2:
            time.sleep(5)
    return None, last


_PW = None
_BROWSER = None


def get_browser():
    global _PW, _BROWSER
    if _BROWSER is None:
        from playwright.sync_api import sync_playwright
        _PW = sync_playwright().start()
        _BROWSER = _PW.chromium.launch(args=["--no-sandbox"])
    return _BROWSER


def attempt_dynamic(url):
    try:
        browser = get_browser()
    except Exception:
        return None, "browser unavailable"
    ctx = None
    try:
        ctx = browser.new_context(user_agent=UA, viewport={"width": 1280, "height": 900},
                                  ignore_https_errors=True)   # handles cert problems too
        page = ctx.new_page()
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=40000)
            page.wait_for_timeout(5000)          # let JavaScript paint the numbers
            html = page.content()
            return (html, None) if html and len(html) > 500 else (None, "empty render")
        finally:
            page.close()
    except Exception as e:
        return None, type(e).__name__
    finally:
        try:
            if ctx:
                ctx.close()
        except Exception:
            pass


def cleanup():
    try:
        if _BROWSER:
            _BROWSER.close()
        if _PW:
            _PW.stop()
    except Exception:
        pass


# ---------- main ----------
def write_summary(text):
    p = os.environ.get("GITHUB_STEP_SUMMARY")
    if p:
        with open(p, "a", encoding="utf-8") as f:
            f.write(text + "\n")


def collect_source(cfg):
    got, via, notes = {}, "", []
    for url in cfg["urls"]:
        html, err = attempt_static(url)
        if html:
            got = parse_any(html)
            if got:
                return got, "static", notes
            n, kw = diagnose(html)
            notes.append(f"{short(url)}: HTTP 200 · {n} tables · {'rate words found' if kw else 'no rate words'}")
        else:
            notes.append(f"{short(url)}: {err}")
        dhtml, derr = attempt_dynamic(url)       # browser also fixes SSL/bot issues
        if dhtml:
            got = parse_any(dhtml)
            if got:
                return got, "browser", notes
            notes.append("browser: parsed 0")
        else:
            notes.append(f"browser: {derr}")
    return got, via, notes


def main():
    if not RATES.exists():
        print("data/rates.json not found — nothing to update.")
        cleanup()
        return 1
    doc = json.loads(RATES.read_text(encoding="utf-8"))
    sources = doc.setdefault("sources", {})
    rates = doc.setdefault("rates", [])
    old_gen = (doc.get("meta") or {}).get("generated_at", "")
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")

    for s in sources.values():
        if not s.get("fetched_at"):
            s["fetched_at"] = old_gen or now

    quotes = {(r.get("source"), r.get("currency")): r for r in rates}

    summary = []
    applied_any = False

    try:
        for sid, cfg in SOURCES.items():
            got, via, notes = collect_source(cfg)
            if not got:
                detail = "; ".join(notes) if notes else "unknown"
                summary.append(f"| {sid} | ✗ {detail} — kept previous values |")
                continue
            kept, warned = [], False
            for cur in WANT:
                if cur not in got:
                    continue
                buy, sell = got[cur]
                prev = quotes.get((sid, cur))
                if prev and prev.get("buy"):
                    try:
                        if abs(buy / float(prev["buy"]) - 1) > MAX_JUMP:
                            summary.append(f"| {sid} | ⚠ {cur} skipped — fetched {buy} vs stored {prev['buy']} (>15% jump, likely misread) |")
                            warned = True
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
                kept.append(f"{cur} {buy:g}/{sell:g}")
            if kept:
                applied_any = True
                s = sources.setdefault(sid, {"name": cfg["name"], "type": cfg["type"]})
                s["name"], s["type"] = cfg["name"], cfg["type"]
                s["fetched_at"] = now
                summary.append(f"| {sid} | ✓ {', '.join(kept)} ({via}) |")
            elif not warned:
                summary.append(f"| {sid} | ⚠ nothing usable — kept previous values |")
            time.sleep(4)                        # polite pause between banks
    finally:
        cleanup()

    if not applied_any:
        text = ("## Robot collection — FAILED\n\nNo bank could be read. rates.json was not changed.\n\n"
                "| Source | Result |\n|---|---|\n" + "\n".join(summary))
        print(text)
        write_summary(text)
        return 1

    doc.setdefault("meta", {})["generated_at"] = now
    RATES.write_text(json.dumps(doc, indent=1) + "\n", encoding="utf-8")

    ok = sum(1 for line in summary if line.startswith("| ") and "✓" in line)
    text = (f"## Robot collection — {ok}/{len(SOURCES)} banks updated\n\n"
            "| Source | Result |\n|---|---|\n" + "\n".join(summary))
    print(text)
    write_summary(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())