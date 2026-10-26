"""Synthetic NSE charts for the India tests, built in memory (no files in the repo).

NOT market data. The prices are a seeded random walk shaped like Yahoo's chart
JSON for NSE stocks (RELIANCE.NS and friends): 5-minute bars from 9:15 to 15:30
India time (UTC+5:30), rupees, the NSE 2026 holidays skipped. The test day,
Friday 2026-10-23, has a clean opening-range breakout: the 9:15 to 9:30 range,
then the 9:45 bar closes above its high (the trigger shows at 9:50).
"""

import datetime
import json
import os
import random

IST = datetime.timedelta(hours=5, minutes=30)
EPOCH = datetime.datetime(1970, 1, 1)
DAY = datetime.date(2026, 10, 23)
BASES = {"RELIANCE.NS": 1450.0, "TCS.NS": 3050.0, "INFY.NS": 1480.0, "HDFCBANK.NS": 990.0}
NSE_2026 = {"2026-01-15", "2026-01-26", "2026-03-03", "2026-03-26", "2026-03-31", "2026-04-03", "2026-04-14",
            "2026-05-01", "2026-05-28", "2026-06-26", "2026-09-14", "2026-10-02", "2026-10-20", "2026-11-10",
            "2026-11-24", "2026-12-25"}
BARS = 75   # 9:15 to 15:30


def trading_days(end, n):
    """The n NSE sessions up to and including end, oldest first."""
    out, d = [], end
    while len(out) < n:
        if d.weekday() < 5 and d.isoformat() not in NSE_2026:
            out.append(d)
        d -= datetime.timedelta(days=1)
    return out[::-1]


def ts(day, minutes_after_open):
    local = datetime.datetime.combine(day, datetime.time(9, 15)) + datetime.timedelta(minutes=minutes_after_open)
    return int((local - IST - EPOCH).total_seconds())


def _session(rng, start, breakout=False):
    """75 bars (o, h, l, c, v). With breakout, a tight 15-minute range, then the 9:45 bar breaks out."""
    bars, p = [], start
    for i in range(BARS):
        if breakout and i < 3:
            o, c = p, start * (1 + (0.002, -0.003, 0.001)[i])
            h, lo = start * 1.004, start * 0.995
        elif breakout and i in (3, 4, 5):
            o, c = p, start * (1.002, 1.001, 1.003)[i - 3]
            h, lo = max(o, c) * 1.0005, min(o, c) * 0.9995
        elif breakout and i == 6:
            o, c = p, start * 1.0075
            h, lo = c * 1.0005, o * 0.9995
        else:
            o = p
            c = p * (1 + rng.gauss(0.0001 if breakout else 0, 0.0018))
            h = max(o, c) * (1 + abs(rng.gauss(0, 0.0008)))
            lo = min(o, c) * (1 - abs(rng.gauss(0, 0.0008)))
        v = int(rng.uniform(40000, 120000) * (2.5 if i < 3 else 1))
        bars.append((round(o, 2), round(h, 2), round(lo, 2), round(c, 2), v))
        p = c
    return bars


def chart(sym, days=60, upto=None, seed=19):
    """Yahoo-shaped chart JSON (a dict) for sym: the last `days` of 60 sessions ending on DAY, 5-minute bars.
    upto = minutes after 9:15 on DAY to cut the last session at (None = the whole day)."""
    rng = random.Random("%s-%d" % (sym, seed))
    base = BASES.get(sym, 1000.0)
    stamps, cols = [], {"open": [], "high": [], "low": [], "close": [], "volume": []}
    p = base
    prev_close = None
    keep = set(trading_days(DAY, days))
    for d in trading_days(DAY, 60):          # one walk, so the 1-day chart is the 60-day chart's last session
        if d == DAY:
            prev_close = p
        p = p * (1 + rng.gauss(0, 0.006))      # overnight gap
        last = d == DAY
        for i, (o, h, lo, c, v) in enumerate(_session(rng, p, breakout=last)):
            p = c
            if d not in keep or (last and upto is not None and 5 * i + 5 > upto):
                continue
            stamps.append(ts(d, 5 * i))
            for k, x in zip(("open", "high", "low", "close", "volume"), (o, h, lo, c, v)):
                cols[k].append(x)
    end = stamps[-1] + 300
    meta = {"currency": "INR", "symbol": sym, "exchangeName": "NSI", "fullExchangeName": "NSE",
            "instrumentType": "EQUITY", "regularMarketTime": end, "gmtoffset": 19800, "timezone": "IST",
            "exchangeTimezoneName": "Asia/Kolkata", "regularMarketPrice": cols["close"][-1],
            "regularMarketDayHigh": max(cols["high"][-3:]), "regularMarketDayLow": min(cols["low"][-3:]),
            "chartPreviousClose": round(prev_close, 2), "previousClose": round(prev_close, 2),
            "dataGranularity": "5m", "range": "60d" if days > 1 else "1d", "synthetic": True}
    return {"chart": {"result": [{"meta": meta, "timestamp": stamps,
                                  "indicators": {"quote": [cols]}}], "error": None}}


def quote(sym, upto=None):
    """A Yahoo 1d quote (the shape trader-alerts reads)."""
    c = chart(sym, days=1, upto=upto)
    r = c["chart"]["result"][0]
    r["meta"]["dataGranularity"] = "1d"
    return c


def write_all(folder, symbols=tuple(BASES), upto=None):
    """Write every file the India tests read offline into folder:
    <SYM>.json (today's bars, trader-entry / trader-exit), <SYM>-60d5m.json (trader-timemachine)
    and yahoo-<SYM>.json (trader-alerts)."""
    os.makedirs(folder, exist_ok=True)
    for s in symbols:
        for name, doc in (("%s.json" % s, chart(s, days=1, upto=upto)),
                          ("%s-60d5m.json" % s, chart(s, days=60)),
                          ("yahoo-%s.json" % s, quote(s, upto=upto))):
            with open(os.path.join(folder, name), "w", encoding="utf-8") as fh:
                json.dump(doc, fh)
    return folder
