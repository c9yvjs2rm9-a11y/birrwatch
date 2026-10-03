#!/usr/bin/env python3
# Birrwatch robot collector v10.3 — 32 banks + FX bureaus + parallel USDT/ETB.
#
# TO FIX A FAILING SOURCE: open its rate page in your browser (numbers visible
# immediately, no clicking), copy the address, paste it as the FIRST url in
# that source's list. Commit, then Actions -> Run workflow.
# v10.3: PER-SOURCE PRIVATE BROWSER — each browser attempt launches its own
# Playwright inside its own watchdog thread and tears it down there. No shared
# browser state = no cross-thread Playwright deadlock (the v10.2 DBH freeze).
# Budget 15 min, per-source cap 180s, data written before exit, os._exit end.

import csv
import io
import json
import os
import re
import sys
import threading
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

WANT = ("USD", "EUR", "AED", "SAR", "GBP", "CNY")
MAX_JUMP = 0.15
MIN_SPREAD = 0.0008
TIME_BUDGET = 15 * 60
PER_SOURCE = 180
P2P_TIMEOUT = 120

UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
HEADERS = {"User-Agent": UA}

EBR_URL = "https://ebr.exchange/"

SOURCES = {
    "CBE": {"name": "Commercial Bank of Ethiopia", "type": "bank", "urls": [
        "https://combanketh.et/exchange-rates?srcPage=home",
        "https://combanketh.et/",
    ]},
    "AWB": {"name": "Awash Bank", "type": "bank", "urls": [
        "https://awashbank.com/exchange-historical/",
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
        "https://coopbankoromia.com.et/",
        "https://coopbankoromia.com.et/exchange-rate/",
    ]},
    "ORB": {"name": "Oromia Bank", "type": "bank", "urls": [
        "https://oromiabank.com/exchange-rate/",
        "https://oromiabank.com/",
    ]},
    "ABY": {"name": "Abay Bank", "type": "bank", "urls": [
        "https://abaybank.com.et/exchange-rate/",
        "https://abaybank.com.et/",
    ]},
    "NIB": {"name": "Nib International Bank", "type": "bank", "urls": [
        "https://nibbank.com.et/exchange-rate/",
        "https://nibbank.com.et/",
    ]},
    "WGB": {"name": "Wegagen Bank", "type": "bank", "urls": [
        "https://wegagenbank.com/exchange-rate/",
        "https://wegagenbank.com/",
    ]},
    "ZEM": {"name": "Zemen Bank", "type": "bank", "urls": [
        "https://zemenbank.com/exchange-rate/",
        "https://zemenbank.com/",
    ]},
    "HIB": {"name": "Hibret Bank", "type": "bank", "urls": [
        "https://hibretbank.com/exchange-rate/",
        "https://hibretbank.com/",
    ]},
    "BRH": {"name": "Berhan Bank", "type": "bank", "urls": [
        "https://berhanbank.com/exchange-rate/",
        "https://berhanbank.com/",
    ]},
    "BUN": {"name": "Bunna Bank", "type": "bank", "urls": [
        "https://bunnabank.com.et/exchange-rate/",
        "https://bunnabank.com.et/",
    ]},
    "ENB": {"name": "Enat Bank", "type": "bank", "urls": [
        "https://enatbank.com/exchange-rate/",
        "https://enatbank.com/",
    ]},
    "ZZB": {"name": "ZamZam Bank", "type": "bank", "urls": [
        "https://zamzambank.com.et/exchange-rate/",
        "https://zamzambank.com.et/",
    ]},
    "AIB": {"name": "Addis International Bank", "type": "bank", "urls": [
        "https://addisinternationalbank.com/exchange-rate/",
        "https://addisinternationalbank.com/",
    ]},
    "AHB": {"name": "Ahadu Bank", "type": "bank", "urls": [
        "https://ahadubank.com/exchange-rate/",
        "https://ahadubank.com/",
    ]},
    "AMB": {"name": "Amhara Bank", "type": "bank", "urls": [
        "https://amharabank.com/exchange-rate/",
        "https://amharabank.com/",
    ]},
    "ANB": {"name": "Anbesa Bank", "type": "bank", "urls": [
        "https://anbesabank.com/exchange-rate/",
        "https://anbesabank.com/",
    ]},
    "DBE": {"name": "Development Bank of Ethiopia", "type": "bank", "urls": [
        "https://dbe.com.et/exchange-rate/",
        "https://dbe.com.et/",
    ]},
    "GDB": {"name": "Gadaa Bank", "type": "bank", "urls": [
        "https://gadaabank.com/exchange-rate/",
        "https://gadaabank.com/",
    ]},
    "GLB": {"name": "Global Bank Ethiopia", "type": "bank", "urls": [
        "https://globalbankethiopia.com/exchange-rate/",
        "https://globalbankethiopia.com/",
    ]},
    "GOH": {"name": "Goh Betoch Bank", "type": "bank", "urls": [
        "https://gohbetochbank.com/exchange-rate/",
        "https://gohbetochbank.com/",
    ]},
    "HJB": {"name": "Hijra Bank", "type": "bank", "urls": [
        "https://hijrabank.com/exchange-rate/",
        "https://hijrabank.com/",
    ]},
    "OMO": {"name": "Omo Bank", "type": "bank", "urls": [
        "https://omobank.com/exchange-rate/",
        "https://omobank.com/",
    ]},
    "RMB": {"name": "Rammis Bank", "type": "bank", "urls": [
        "https://rammisbank.com/exchange-rate/",
        "https://rammisbank.com/",
    ]},
    "SHB": {"name": "Shabelle Bank", "type": "bank", "urls": [
        "https://shabellebank.com.et/exchange-rate/",
        "https://shabellebank.com.et/",
    ]},
    "SDB": {"name": "Sidama Bank", "type": "bank", "urls": [
        "https://sidamabank.com/exchange-rate/",
        "https://sidamabank.com/",
    ]},
    "SQB": {"name": "Siinqee Bank", "type": "bank", "urls": [
        "https://siinqeebank.com/exchange-rate/",
        "https://siinqeebank.com/",
    ]},
    "SKB": {"name": "Siket Bank", "type": "bank", "urls": [
        "https://siketbank.com/exchange-rate/",
        "https://siketbank.com/",
    ]},
    "TSB": {"name": "Tsedey Bank", "type": "bank", "urls": [
        "https://tsedeybank.com/exchange-rate/",
        "https://tsedeybank.com/",
    ]},
    "THB": {"name": "Tsehay Bank", "type": "bank", "urls": [
        "https://tsehaybank.com/exchange-rate/",
        "https://tsehaybank.com/",
    ]},
    "AMM": {"name": "Ammann Forex Bureau", "type": "bureau", "urls": [
        "https://ammannforexbureau.com/",
    ]},
    "AYO": {"name": "AYOTAN Forex Bureau", "type": "bureau", "urls": [
        "https://ayotanforextrading.com/",
    ]},
    "HAR": {"name": "Haron Forex Bureau", "type": "bureau", "urls": [
        "https://www.haronforex.com/",
    ]},
    "TAY": {"name": "Taypay Forex Bureau", "type": "bureau", "method": "csv", "urls": [
        "https://docs.google.com/spreadsheets/d/e/2PACX-1vT7rZVlNT4C3L7Big_5ZfnQOCB7dAmuY388AG0YJCDc3HB-xoVX8PtCbPJZngJHYbNeEFLSCMHGOvLN/pub?gid=0&single=true&output=csv",
    ]},
    "DBH": {"name": "DBH Forex Bureau", "type": "bureau", "urls": [
        "https://dbhforex.com/",
    ]},
    "ETH": {"name": "Ethio Forex Bureau", "type": "bureau", "urls": [
        "https://www.ethioforextrading.com/exchange-rates",
        "https://www.ethioforextrading.com/",
    ]},
}

NUM = re.compile(r"\d[\d,]*(?:\.\d+)?")
BUY_W = ("BUY", "BUYING", "BID", "PURCHAS")
SELL_W = ("SELL", "SELLING", "OFFER", "ASK", "SOLD")
CASH_W = ("CASH", "NOTE", "BANKNOTE")


def run_with_timeout(fn, args=(), timeout=180, label=""):
    """Run fn(*args) in a daemon thread; abandon it if it exceeds timeout."""
    box = {}

    def worker():
        try:
            box["result"] = fn(*args)
        except BaseException as e:
            box["error"] = f"{type(e).__name__}: {e}"

    t = threading.Thread(target=worker, daemon=True)
    t.start()
    t.join(timeout)
    if t.is_alive():
        return None, f"⏳ stalled >{timeout}s ({label})"
    if "error" in box:
        return None, box["error"]
    return box.get("result"), None


def norm(s):
    return re.sub(r"\s+", " ", re.sub(r"[^A-Za-z]", " ", (s or ""))).strip().upper()


def match_currency(text):
    t = norm(text)
    toks = set(t.split())
    for code in ("USD", "EUR", "GBP", "AED", "SAR", "CNY", "USDT"):
        if code in toks:
            return code
    if "UNITED STATES" in t or "US DOLLAR" in t:
        return "USD"
    if "EURO" in t and "BOND" not in t:
        return "EUR"
    if "POUND" in t and "STERLING" in t:
        return "GBP"
    if "DIRHAM" in t:
        return "AED"
    if "RIYAL" in t:
        return "SAR"
    if "YUAN" in t or "RENMINBI" in t:
        return "CNY"
    if "TETHER" in t:
        return "USDT"
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
    return bool(b and s and 0.5 < b < 5000 and 0.5 < s < 5000
                and b <= s < b * 1.25 and (s - b) / b >= MIN_SPREAD)


def parse_csv_rates(text):
    out = {}
    for row in csv.reader(io.StringIO(text)):
        cells = [(c or "").strip() for c in row]
        if not any(cells):
            continue
        cur = None
        for c in cells:
            m = match_currency(c)
            if m:
                cur = m
                break
        if not cur or cur in out:
            continue
        nums = []
        for c in cells:
            if not c:
                continue
            try:
                v = float(c.replace(",", ""))
            except ValueError:
                continue
            if 0.5 < v < 5000:
                nums.append(v)
        if len(nums) < 2:
            continue
        b, s = nums[0], nums[1]
        if b > s:
            b, s = s, b
        if plausible(b, s):
            out[cur] = (b, s)
    return out


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
            if buy and sell and buy > sell:
                buy, sell = sell, buy
            if plausible(buy, sell):
                out[cur] = (buy, sell)
        if len(out) > len(best):
            best = out
    return best


def parse_cards(html):
    soup = BeautifulSoup(html, "html.parser")
    page_text = norm(soup.get_text(" ", strip=True))
    exchange_page = "EXCHANGE" in page_text
    cands = []
    for el in soup.find_all(["div", "section", "article", "li", "span", "p"]):
        t = el.get_text(" ", strip=True)
        if not t or len(t) > 160:
            continue
        u = norm(t)
        cur = match_currency(u)
        if not cur:
            continue
        nums = []
        for m in NUM.findall(t):
            try:
                v = float(m.replace(",", ""))
            except ValueError:
                continue
            if 0.5 < v < 5000:
                nums.append(v)
        if len(nums) < 2:
            continue
        has_bs = any(w in u for w in BUY_W) and any(w in u for w in SELL_W)
        if not has_bs and (not exchange_page or len(nums) != 2):
            continue
        buy, sell = nums[0], nums[1]
        if buy > sell:
            buy, sell = sell, buy
        cands.append((len(t), cur, buy, sell, has_bs))
    cands.sort(key=lambda c: (0 if c[4] else 1, c[0]))
    out = {}
    for _, cur, b, s, _ in cands:
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


def browser_worth_it(err):
    if err is None:
        return True
    e = err.lower()
    if "http 404" in e or "http 410" in e:
        return False
    if "timeout" in e or "connection" in e or "nameresolution" in e or "connect" in e:
        return False
    if "http 403" in e or "ssl" in e or "http 200" in e:
        return True
    return False


def _num_ok(v):
    try:
        f = float(str(v).replace(",", ""))
    except (TypeError, ValueError):
        return None
    return f if 20.0 < f < 5000.0 else None


PRICE_KEYS = ("price", "rate", "buy", "sell", "bid", "ask", "etb")


def walk_prices(node, out, depth=0):
    if depth > 9 or len(out) > 400:
        return
    if isinstance(node, dict):
        for k, v in node.items():
            kl = str(k).lower()
            if isinstance(v, (int, float)) or (isinstance(v, str) and _num_ok(v) is not None):
                f = _num_ok(v)
                if f is not None and any(w in kl for w in PRICE_KEYS):
                    out.append(f)
                continue
            walk_prices(v, out, depth + 1)
    elif isinstance(node, list):
        for v in node[:60]:
            walk_prices(v, out, depth + 1)


def text_candidates(html):
    try:
        soup = BeautifulSoup(html, "html.parser")
        txt = soup.get_text(" ", strip=True)
    except Exception:
        return []
    out = []
    for m in re.finditer(r"USDT|ETB", txt, re.I):
        n = NUM.search(txt[m.end():m.end() + 60])
        if n:
            v = _num_ok(n.group())
            if v is not None:
                out.append(v)
    return out


def median(vals):
    v = sorted(vals)
    n = len(v)
    return v[n // 2] if n % 2 else (v[n // 2 - 1] + v[n // 2]) / 2


def decide_from_candidates(buys, sells, prices, label):
    if len(buys) >= 2 and len(sells) >= 2:
        b, s = median(buys), median(sells)
        if b > s:
            b, s = s, b
        if plausible(b, s) and s / b <= 1.10:
            return b, s, label
    if len(prices) >= 3:
        m = median(prices)
        return m * 0.997, m * 1.003, label + " (indicative spread)"
    return None


def attempt_static(url):
    last = "failed"
    for attempt in range(2):
        try:
            r = requests.get(url, headers=HEADERS, timeout=15)
            if r.status_code == 200 and len(r.text) > 500:
                return r.text, None
            last = f"HTTP {r.status_code}"
            if r.status_code in (404, 410):
                return None, last
        except requests.exceptions.SSLError:
            try:
                r = requests.get(url, headers=HEADERS, timeout=15, verify=False)
                if r.status_code == 200 and len(r.text) > 500:
                    return r.text, None
                last = f"HTTP {r.status_code} (ssl-relaxed)"
            except Exception as e:
                last = f"SSL ({type(e).__name__})"
        except requests.exceptions.Timeout:
            return None, "timeout"
        except Exception as e:
            return None, type(e).__name__
        if attempt < 1:
            time.sleep(2)
    return None, last


def attempt_dynamic(url):
    """Self-contained: launches its own Playwright + Chromium inside the calling
    (watchdog) thread and tears them down there. No shared browser state —
    Playwright's sync API is thread-bound, so sharing caused the v10.2 freeze."""
    info = []
    pw = None
    browser = None
    ctx = None
    try:
        from playwright.sync_api import sync_playwright
        pw = sync_playwright().start()
        browser = pw.chromium.launch(args=["--no-sandbox"])
        ctx = browser.new_context(user_agent=UA, viewport={"width": 1280, "height": 900},
                                  ignore_https_errors=True)
        page = ctx.new_page()
        try:
            page.set_default_timeout(15000)
        except Exception:
            pass
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=25000)
            page.wait_for_timeout(4000)
            try:
                page.mouse.wheel(0, 1200)
                page.wait_for_timeout(1000)
                page.mouse.wheel(0, -1200)
                page.wait_for_timeout(500)
            except Exception:
                pass
            try:
                btn = page.locator("input[type=submit], button[type=submit], "
                                   "button:has-text('Search'), a:has-text('Search'), "
                                   "button:has-text('Go')").first
                if btn.count() > 0:
                    btn.click(timeout=2000)
                    page.wait_for_timeout(2500)
                    info.append("clicked search")
            except Exception:
                pass
            html = page.content() or ""
            try:
                ntab = len(BeautifulSoup(html, "html.parser").find_all("table"))
                info.append(f"main: {ntab} tables")
            except Exception:
                pass
            try:
                for f in page.frames:
                    if f == page.main_frame:
                        continue
                    try:
                        fh = f.content()
                        if fh and len(fh) > 500:
                            html += "\n" + fh
                    except Exception:
                        pass
            except Exception:
                pass
            if html and len(html) > 500:
                return html, None, info
            return None, "empty render", info
        finally:
            try:
                page.close()
            except Exception:
                pass
            try:
                if ctx:
                    ctx.close()
            except Exception:
                pass
    except Exception as e:
        return None,