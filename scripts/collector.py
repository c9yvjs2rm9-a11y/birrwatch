#!/usr/bin/env python3
# Birrwatch robot collector v10 — 32 banks + FX bureaus + parallel USDT/ETB.
#
# TO FIX A FAILING SOURCE: open its rate page in your browser (numbers visible
# immediately, no clicking), copy the address, paste it as the FIRST url in
# that source's list. Commit, then Actions -> Run workflow.
# v10: TIME BUDGET — the run always finishes and commits, even if sources hang.
#      Browser fallback only for pages that exist (200/SSL/403) — never for
#      dead domains or 404s. Keeps all v9 sources and parsers.

import csv
import io
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

WANT = ("USD", "EUR", "AED", "SAR", "GBP", "CNY")
MAX_JUMP = 0.15
MIN_SPREAD = 0.0008
TIME_BUDGET = 30 * 60          # seconds — after this, remaining sources are skipped
                               # and everything collected so far is committed.

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
    # ---------- FX bureaus ----------
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
    # Rooha (ROO) and Robust (ROB): add entries here once URLs arrive.
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
    """Browser fallback helps for JS-rendered pages, SSL problems, 403 blocks.
    It can never help for 404s, timeouts or unreachable domains."""
    if err is None:
        return True                      # page fetched but parsed 0 — JS likely
    e = err.lower()
    if "http 404" in e or "http 410" in e:
        return False
    if "timeout" in e or "connection" in e or "nameresolution" in e or "connect" in e:
        return False
    if "http 403" in e or "ssl" in e or "http 200" in e:
        return True
    return False


# ---------- parallel helpers ----------
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


# ---------- fetching ----------
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
            last = "timeout"
            break                            # second attempt won't be faster
        except Exception as e:
            last = type(e).__name__
            break                            # connection-level: fail fast
        if attempt < 1:
            time.sleep(2)
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
        return None, "browser unavailable", [], []
    ctx = None
    info = []
    caps = []
    try:
        ctx = browser.new_context(user_agent=UA, viewport={"width": 1280, "height": 900},
                                  ignore_https_errors=True)
        page = ctx.new_page()

        def _on_response(resp):
            try:
                ct = (resp.headers or {}).get("content-type", "") or ""
                if "json" in ct.lower() and resp.status == 200 and len(caps) < 20:
                    body = resp.text()
                    if body and len(body) <= 200000:
                        caps.append((resp.url or "", body))
            except Exception:
                pass

        try:
            page.on("response", _on_response)
        except Exception:
            pass
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=30000)
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
                return html, None, info, caps
            return None, "empty render", info, caps
        finally:
            try:
                page.close()
            except Exception:
                pass
    except Exception as e:
        return None, type(e).__name__, info, caps
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


# ---------- parallel sources ----------
def fetch_ebr(notes, budget):
    all_prices, buys, sells = [], [], []
    html, err = attempt_static(EBR_URL)
    if html:
        soup = BeautifulSoup(html, "html.parser")
        nd = soup.find("script", id="__NEXT_DATA__")
        if nd:
            try:
                walk_prices(json.loads(nd.get_text() or ""), all_prices)
            except Exception:
                pass
        all_prices.extend(text_candidates(html))
        for cur, (b, s) in (parse_any(html) or {}).items():
            if cur in ("USD", "USDT"):
                buys.append(b)
                sells.append(s)
        notes.append(f"ebr static: {len(all_prices)} candidates")
    else:
        notes.append(f"ebr static: {err}")
    if budget() and browser_worth_it(err):
        bhtml, berr, binfo, caps = attempt_dynamic(EBR_URL)
        if bhtml:
            for _u, body in caps:
                try:
                    walk_prices(json.loads(body), all_prices)
                except Exception:
                    continue
            all_prices.extend(text_candidates(bhtml))
            for cur, (b, s) in (parse_any(bhtml) or {}).items():
                if cur in ("USD", "USDT"):
                    buys.append(b)
                    sells.append(s)
            notes.append(f"ebr browser: {len(caps)} json endpoints · {len(all_prices)} candidates")
        else:
            notes.append(f"ebr browser: {berr} (" + "; ".join(binfo) + ")")
    r = decide_from_candidates(buys, sells, all_prices, "ebr.exchange")
    if r:
        return r[0], r[1], r[2]
    return None


def fetch_json(url, payload=None):
    try:
        h = {**HEADERS, "Accept": "application/json"}
        if payload is None:
            r = requests.get(url, headers=h, timeout=20)
        else:
            h["Content-Type"] = "application/json"
            r = requests.post(url, headers=h, data=json.dumps(payload), timeout=20)
        if r.status_code == 200:
            return r.json(), None
        return None, f"HTTP {r.status_code}"
    except Exception as e:
        return None, type(e).__name__


def p2p_prices(doc, price_path):
    out = []
    for item in (doc.get("data") or [])[:10]:
        try:
            node = item
            for k in price_path:
                node = node[k]
            p = float(str(node).replace(",", ""))
            if 20 < p < 5000:
                out.append(p)
        except (KeyError, TypeError, ValueError, IndexError):
            continue
    return out


def p2p_binance(notes):
    sides = {}
    for side in ("BUY", "SELL"):
        doc, err = fetch_json(
            "https://p2p.binance.com/bapi/c2c/v2/friendly/c2c/adv/search",
            {"page": 1, "rows": 10, "asset": "USDT", "fiat": "ETB",
             "tradeType": side, "payTypes": [], "publisherType": None})
        if doc is None:
            notes.append(f"binance {side}: {err}")
            return None
        prices = p2p_prices(doc, ["adv", "price"])
        if len(prices) < 3:
            notes.append(f"binance {side}: thin book")
            return None
        sides[side] = median(prices)
    return sides["BUY"], sides["SELL"], "binance p2p"


def p2p_kucoin(notes):
    sides = {}
    for side in ("BUY", "SELL"):
        doc, err = fetch_json(
            f"https://www.kucoin.com/_api/otc/ad/list?currency=USDT&legalCurrency=ETB&page=1&pageSize=10&side={side}&status=PUTUP")
        if doc is None:
            notes.append(f"kucoin {side}: {err}")
            return None
        prices = []
        for item in (((doc.get("data") or {}).get("list")) or [])[:10]:
            try:
                p = float(str(item.get("price")).replace(",", ""))
                if 20 < p < 5000:
                    prices.append(p)
            except (TypeError, ValueError):
                continue
        if len(prices) < 3:
            notes.append(f"kucoin {side}: thin book")
            return None
        sides[side] = median(prices)
    return sides["BUY"], sides["SELL"], "kucoin p2p"


def p2p_bybit(notes):
    doc, err = fetch_json(
        "https://api2.bybit.com/fiat/otc/item/online",
        {"tokenId": "USDT", "currency": "ETB", "side": "1", "page": "", "size": "10"})
    if doc is None:
        notes.append(f"bybit: {err}")
        return None
    prices = []
    for item in (((doc.get("result") or {}).get("item")) or [])[:10]:
        try:
            p = float(str(item.get("price")).replace(",", ""))
            if 20 < p < 5000:
                prices.append(p)
        except (TypeError, ValueError):
            continue
    if len(prices) < 3:
        notes.append("bybit: thin book")
        return None
    m = median(prices)
    return m * 0.997, m * 1.003, "bybit (indicative spread)"


def fetch_parallel(budget):
    notes = []
    for fn in (fetch_ebr, p2p_binance, p2p_kucoin, p2p_bybit):
        try:
            got = fn(notes, budget) if fn is fetch_ebr else fn(notes)
        except TypeError:
            got = fn(notes)
        if got:
            buy, sell, src = got
            if buy > sell:
                buy, sell = sell, buy
            return buy, sell, src
    return None, None, None


# ---------- main ----------
def write_summary(text):
    p = os.environ.get("GITHUB_STEP_SUMMARY")
    if p:
        with open(p, "a", encoding="utf-8") as f:
            f.write(text + "\n")


def collect_source(cfg):
    if cfg.get("method") == "csv":
        notes = []
        for url in cfg["urls"]:
            try:
                r = requests.get(url, headers=HEADERS, timeout=25)
                if r.status_code != 200:
                    notes.append(f"csv: HTTP {r.status_code}")
                    continue
                got = parse_csv_rates(r.text)
                if got:
                    return got, "csv", notes
                notes.append("csv: no usable rows")
            except Exception as e:
                notes.append(f"csv: {type(e).__name__}")
        return {}, "", notes
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
        if not browser_worth_it(err):
            continue                         # dead domain / 404 — browser can't help
        dhtml, derr, dinfo, _caps = attempt_dynamic(url)
        if dhtml:
            got = parse_any(dhtml)
            if got:
                return got, "browser", notes
            notes.append("browser: parsed 0 (" + "; ".join(dinfo) + ")")
        else:
            notes.append(f"browser: {derr} (" + "; ".join(dinfo) + ")")
    return got, via, notes


def apply_quote(quotes, rates, sid, cur, buy, sell):
    prev = quotes.get((sid, cur))
    if prev and prev.get("buy"):
        try:
            if abs(buy / float(prev["buy"]) - 1) > MAX_JUMP:
                return f"⚠ {cur} skipped — fetched {buy:g} vs stored {prev['buy']} (>15% jump)"
        except (TypeError, ZeroDivisionError):
            pass
    q = quotes.get((sid, cur))
    if q:
        q["buy"], q["sell"] = buy, sell
    else:
        row = {"source": sid, "currency": cur, "buy": buy, "sell": sell}
        rates.append(row)
        quotes[(sid, cur)] = row
    return f"✓ {cur} {buy:g}/{sell:g}"


def main():
    if not RATES.exists():
        print("data/rates.json not found — nothing to update.")
        cleanup()
        return 1
    t0 = time.monotonic()
    def budget_left():
        return (time.monotonic() - t0) < TIME_BUDGET

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
    skipped = []

    try:
        for sid, cfg in SOURCES.items():
            if not budget_left():
                skipped.append(sid)
                continue
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
                res = apply_quote(quotes, rates, sid, cur, buy, sell)
                if res.startswith("⚠"):
                    summary.append(f"| {sid} | {res} |")
                    warned = True
                else:
                    kept.append(res[2:])
            if kept:
                applied_any = True
                s = sources.setdefault(sid, {"name": cfg["name"], "type": cfg["type"]})
                s["name"], s["type"] = cfg["name"], cfg["type"]
                s["fetched_at"] = now
                summary.append(f"| {sid} | ✓ {', '.join(kept)} ({via}) |")
            elif not warned:
                summary.append(f"| {sid} | ⚠ nothing usable — kept previous values |")
            time.sleep(2)

        if budget_left():
            buy, sell, src = fetch_parallel(budget_left)
            if buy and sell:
                res = apply_quote(quotes, rates, "P2P", "USDT", round(buy, 2), round(sell, 2))
                if res.startswith("⚠"):
                    summary.append(f"| P2P | {res} |")
                else:
                    applied_any = True
                    sources["P2P"] = {"name": f"USDT/ETB — parallel market ({src}; indicative)",
                                      "type": "market", "fetched_at": now}
                    summary.append(f"| P2P | ✓ USDT {buy:.2f}/{sell:.2f} ({src}) |")
            else:
                summary.append("| P2P | ✗ ebr + fallbacks failed — kept previous values |")
        elif skipped:
            summary.append("| P2P | ⏳ skipped — time budget reached |")
    finally:
        cleanup()

    if skipped:
        summary.append(f"| ⏳ | {len(skipped)} source(s) skipped — time budget reached: {', '.join(skipped)} |")

    if not applied_any:
        text = ("## Robot collection — FAILED\n\nNo source could be read. rates.json was not changed.\n\n"
                "| Source | Result |\n|---|---|\n" + "\n".join(summary))
        print(text)
        write_summary(text)
        return 1

    doc.setdefault("meta", {})["generated_at"] = now
    RATES.write_text(json.dumps(doc, indent=1) + "\n", encoding="utf-8")

    ok = sum(1 for line in summary if line.startswith("| ") and "✓" in line)
    text = (f"## Robot collection — {ok} sources updated\n\n"
            "| Source | Result |\n|---|---|\n" + "\n".join(summary))
    print(text)
    write_summary(text)
    return 0


if __name__ == "__main__":
    sys.exit(main()) 