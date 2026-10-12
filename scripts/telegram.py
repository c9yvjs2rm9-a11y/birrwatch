#!/usr/bin/env python3
"""Birrwatch Telegram bot — posts the daily rate summary to the channel."""
import json, os, sys
from pathlib import Path
import requests

ROOT = Path(__file__).resolve().parents[1]
RATES = ROOT / "data" / "rates.json"
TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
CHAT = os.environ.get("TELEGRAM_CHAT_ID", "")


def bank_mids(doc):
    bank = {}
    for r in doc.get("rates", []):
        src = doc.get("sources", {}).get(r.get("source"), {})
        if src.get("type") != "bank" or r.get("flag") == "stale":
            continue
        try:
            bank.setdefault(r["currency"], []).append((float(r["buy"]) + float(r["sell"])) / 2)
        except (KeyError, TypeError, ValueError):
            continue
    return {c: sum(v) / len(v) for c, v in bank.items() if v}


def best(doc, cur, side):
    rows = [r for r in doc.get("rates", [])
            if r.get("currency") == cur
            and (doc.get("sources") or {}).get(r.get("source"), {}).get("type") == "bank"
            and not r.get("flag")]
    if not rows:
        return None
    pick = (max if side == "buy" else min)(rows, key=lambda r: float(r[side]))
    return pick.get("source"), float(pick[side])


def by_type(doc, cur, ttype):
    for r in doc.get("rates", []):
        src = doc.get("sources", {}).get(r.get("source"), {})
        if src.get("type") == ttype and r.get("currency") == cur:
            try:
                return (float(r["buy"]) + float(r["sell"])) / 2
            except (TypeError, ValueError):
                return None
    return None


def main():
    if not TOKEN or not CHAT:
        print("[telegram] TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID not set — skipping", flush=True)
        return 0
    doc = json.loads(RATES.read_text(encoding="utf-8"))
    bank = bank_mids(doc)
    usd = bank.get("USD")
    lines = ["🇪🇹 Birrwatch — የዕለቱ ዋጋዎች | Daily rates", ""]
    if usd:
        lines.append(f"💵 USD/ETB  {usd:.2f} (bank avg)")
        bb, bs = best(doc, "USD", "buy"), best(doc, "USD", "sell")
        if bb: lines.append(f"  Best buy: {bb[0]} — {bb[1]:.2f}")
        if bs: lines.append(f"  Best sell: {bs[0]} — {bs[1]:.2f}")
    for cur, flag in (("EUR", "🇪🇺"), ("AED", "🇦🇪"), ("SAR", "🇸🇦"), ("GBP", "🇬🇧")):
        if cur in bank:
            lines.append(f"{flag} {cur}/ETB  {bank[cur]:.2f}")
    nbe = by_type(doc, "USD", "official")
    if nbe: lines.append(f"🏛 NBE official: {nbe:.2f}")
    par = by_type(doc, "USDT", "market")
    if par and usd:
        lines.append(f"📈 Parallel (USDT/ETB): {par:.2f}  ({(par / usd - 1) * 100:+.1f}%)")
    cus = by_type(doc, "USD", "customs")
    if cus: lines.append(f"🛃 Customs (ERCA): {cus:.2f}")
    lines += ["", "Full rates — all 32 banks & bureaus:", "https://birrwatch.et"]
    r = requests.post(f"https://api.telegram.org/bot{TOKEN}/sendMessage",
                      json={"chat_id": CHAT, "text": "\n".join(lines)}, timeout=30)
    if r.status_code != 200:
        print(f"[telegram] FAILED {r.status_code}: {r.text[:300]}", flush=True)
        return 1
    print("[telegram] posted daily summary", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())