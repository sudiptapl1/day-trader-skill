"""India (NSE) mode: the shared market block, the NSE clock and calendar, rupees,
.NS symbols, and one trade end to end on synthetic NSE charts (tests/nse_synthetic.py).
The US tests elsewhere check that the default market is unchanged."""

import datetime
import io
import json
import os
import re
import shutil
import tempfile
import unittest
from contextlib import redirect_stdout, redirect_stderr

import nse_synthetic
from _load import load, ROOT

SCRIPTS = [("trader-alerts", "alerts"), ("trader-entry", "entry"), ("trader-exit", "exit"),
           ("trader-risk", "check"), ("trader-budget", "size"), ("trader-broker", "ticket"),
           ("trader-news", "news"), ("trader-scanner", "scan"), ("trader-timemachine", "timemachine")]
NSE_2026 = sorted(nse_synthetic.NSE_2026)
DT = datetime.datetime


def source(folder, name):
    with open(os.path.join(ROOT, folder, name + ".py"), encoding="utf-8") as fh:
        return fh.read()


def block(src):
    """The shared market block, minus the per-script INDIA_SCRIPT overrides."""
    start = src.index("# ---------------------------------------------------------------- market: US (NYSE)")
    end = src.index("def run_localized(")
    end = src.index("\n\n\n", end)
    text = src[start:end]
    return re.sub(r"\nINDIA_SCRIPT = .*?\n(?=\n\ndef _ist_offset)", "\n", text, flags=re.S)


def run(mod, argv):
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        code = mod.main(argv)
    return code, out.getvalue(), err.getvalue()


class SharedBlock(unittest.TestCase):
    def test_every_script_carries_the_same_market_block(self):
        first = block(source(*SCRIPTS[0]))
        for folder, name in SCRIPTS[1:]:
            self.assertEqual(block(source(folder, name)), first, "%s/%s.py" % (folder, name))

    def test_the_nse_2026_holidays(self):
        alerts = load("trader-alerts", "alerts")
        self.assertEqual(sorted(alerts.NSE_HOLIDAYS), NSE_2026)
        self.assertEqual(len(alerts.NSE_HOLIDAYS), 16)
        for d in alerts.NSE_HOLIDAYS:
            self.assertLess(datetime.date.fromisoformat(d).weekday(), 5, d)   # weekday closures only

    def test_us_is_the_default_and_comes_back(self):
        alerts = load("trader-alerts", "alerts")
        self.assertEqual(alerts.MARKET, "us")
        us_open, us_hols = alerts.OPEN, alerts.NYSE_HOLIDAYS
        alerts.set_market("in")
        self.assertEqual(alerts.OPEN, datetime.time(9, 15))
        alerts.set_market("us")
        self.assertIs(alerts.OPEN, us_open)
        self.assertIs(alerts.NYSE_HOLIDAYS, us_hols)
        self.assertEqual(alerts.eastern_offset(DT(2026, 10, 19, 14, 0)), -4)

    def test_market_names(self):
        alerts = load("trader-alerts", "alerts")
        for word in ("in", "IN", "india", "NSE"):
            self.assertEqual(alerts.market_code(word), "in")
        for word in (None, "", "us", "NYSE"):
            self.assertEqual(alerts.market_code(word), "us")
        with self.assertRaises(ValueError):
            alerts.market_code("lse")

    def test_pick_market(self):
        alerts = load("trader-alerts", "alerts")
        self.assertEqual(alerts.pick_market(), "us")
        self.assertEqual(alerts.pick_market("in"), "in")
        self.assertEqual(alerts.pick_market(None, docs=[{"market": "in"}]), "in")
        self.assertEqual(alerts.pick_market(None, symbols=["RELIANCE.NS", "TCS.NS"]), "in")
        self.assertEqual(alerts.pick_market(None, symbols=["RELIANCE.NS", "TSLA"]), "us")
        self.assertEqual(alerts.pick_market("us", docs=[{"market": "in"}]), "us")


class Symbols(unittest.TestCase):
    def setUp(self):
        self.m = load("trader-risk", "check")

    def test_us_symbols_pass_through(self):
        self.assertEqual(self.m.market_symbol("tsla"), "TSLA")
        self.assertEqual(self.m.yahoo_ticker("BRK.B"), "BRK-B")

    def test_nse_symbols(self):
        self.m.set_market("in")
        self.assertEqual(self.m.market_symbol("reliance"), "RELIANCE.NS")
        self.assertEqual(self.m.market_symbol("NSE:TCS"), "TCS.NS")
        self.assertEqual(self.m.market_symbol("INFY.NS"), "INFY.NS")
        self.assertEqual(self.m.market_symbol("500325.BO"), "500325.BO")
        self.assertEqual(self.m.yahoo_ticker("BAJAJ-AUTO.NS"), "BAJAJ-AUTO.NS")
        for ok in ("RELIANCE.NS", "M&M.NS", "BAJAJ-AUTO.NS", "HDFCBANK.NS"):
            self.assertTrue(self.m.TICKER.match(ok), ok)
        self.assertFalse(self.m.TICKER.match("TSLA"))

    def test_rupees_and_lakhs(self):
        self.assertEqual(self.m.localize("max loss $50 in New York"), "max loss $50 in New York")
        self.m.set_market("in")
        self.assertEqual(self.m.lakh("500,000"), "5,00,000")
        self.assertEqual(self.m.lakh("12,345,678"), "1,23,45,678")
        self.assertEqual(self.m.localize("cash $450,000.50 at 10:05 ET (New York), NYSE open"),
                         u"cash ₹4,50,000.50 at 10:05 IST (India time), NSE open")


class Clock(unittest.TestCase):
    def setUp(self):
        self.a = load("trader-alerts", "alerts")
        self.a.set_market("in")

    def status(self, text):
        return self.a.market_status(self.a.parse_now(text))

    def test_india_time_is_utc_plus_5_30_all_year(self):
        self.assertEqual(self.a.parse_now("2026-10-23 09:15"), DT(2026, 10, 23, 3, 45))
        self.assertEqual(self.a.parse_now("2026-01-05 09:15"), DT(2026, 1, 5, 3, 45))   # no daylight saving
        self.assertEqual(self.a.to_eastern(DT(2026, 10, 23, 10, 0)), DT(2026, 10, 23, 15, 30))

    def test_session_9_15_to_15_30(self):
        self.assertFalse(self.status("2026-10-23 09:14")["open"])
        self.assertTrue(self.status("2026-10-23 09:15")["open"])
        self.assertTrue(self.status("2026-10-23 15:29")["open"])
        st = self.status("2026-10-23 15:30")
        self.assertFalse(st["open"])
        self.assertEqual((st["opens"], st["closes"]), ("09:15", "15:30"))
        self.assertEqual(st["next_open"], "2026-10-26 09:15")   # Friday -> Monday

    def test_nse_holidays_close_the_market(self):
        st = self.status("2026-11-10 11:00")
        self.assertFalse(st["open"])
        self.assertEqual(st["reason"], "NSE holiday: Diwali Balipratipada")
        self.assertEqual(st["next_open"], "2026-11-11 09:15")
        self.assertTrue(self.status("2026-11-26 11:00")["open"])   # US Thanksgiving is a normal NSE day
        self.assertFalse(self.status("2026-01-15 11:00")["open"])  # the Maharashtra election closure

    def test_the_holiday_list_says_when_it_runs_out(self):
        code, out, _ = run(self.a, ["clock", "--market", "in", "--now", "2027-01-04 10:00"])
        self.assertIn("covers 2026 only: check nseindia.com", out)


class Scripts(unittest.TestCase):
    """Each script's India specifics, with no files around."""

    def test_entry_defaults_and_the_open(self):
        entry = load("trader-entry", "entry")
        entry.set_market("in")
        self.assertEqual(entry.DEFAULTS, {"no_entries_before": "09:30", "no_entries_after": "15:00"})
        self.assertEqual(entry.next_open(datetime.date(2026, 10, 19)), "2026-10-21 09:15")   # skips Dussehra
        entry.set_market("us")
        self.assertEqual(entry.DEFAULTS, {"no_entries_before": "09:45", "no_entries_after": "15:30"})

    def test_timemachine_session_is_75_bars(self):
        tm = load("trader-timemachine", "timemachine")
        tm.set_market("in")
        self.assertEqual((tm.SESSION_BARS, tm.OPEN_MIN, tm.CLOSE_MIN), (75, 555, 930))
        plan = tm.normalize_plan({"symbol": "RELIANCE", "date": "2026-10-23", "entry": 100, "stop": 99,
                                  "target": 101, "entry_time": "9:50 AM"})
        self.assertEqual((plan["symbol"], plan["entry_bar"]), ("RELIANCE.NS", 6))

    def test_broker_offset_is_plus_5_30(self):
        ticket = load("trader-broker", "ticket")
        self.assertEqual(ticket.ny_iso(DT(2026, 10, 19, 14, 15)), "2026-10-19T10:15:00-04:00")
        ticket.set_market("in")
        self.assertEqual(ticket.ny_iso(DT(2026, 10, 23, 4, 35)), "2026-10-23T10:05:00+05:30")

    def test_a_yes_naming_another_nse_stock_is_refused(self):
        ticket = load("trader-broker", "ticket")
        ticket.set_market("in")
        order = {"symbol": "RELIANCE.NS", "side": "buy", "qty": "10", "type": "market", "time_in_force": "day"}
        ok, _ = ticket.parse_yes("yes RELIANCE", order, ["RELIANCE.NS", "TCS.NS"])
        self.assertTrue(ok)
        ok, why = ticket.parse_yes("yes TCS", order, ["RELIANCE.NS", "TCS.NS"])
        self.assertFalse(ok)
        self.assertIn("TCS.NS", why)

    def test_scanner_reads_nse_equity_list(self):
        scan = load("trader-scanner", "scan")
        text = ("SYMBOL,NAME OF COMPANY, SERIES, DATE OF LISTING, PAID UP VALUE, MARKET LOT, ISIN NUMBER, FACE VALUE\n"
                "RELIANCE,Reliance Industries Limited,EQ,29-NOV-1995,10,1,INE002A01018,10\n"
                "BAJAJ-AUTO,Bajaj Auto Limited,EQ,26-MAY-2008,10,1,INE917I01010,10\n"
                "SOMEBE,Some Ltd,BE,01-JAN-2020,10,1,INE000000001,10\n")
        self.assertEqual(scan.parse_nse_equities(text), [("RELIANCE.NS", "Reliance Industries Limited"),
                                                         ("BAJAJ-AUTO.NS", "Bajaj Auto Limited")])


class OneTrade(unittest.TestCase):
    """Scanner -> entry -> exit -> time machine -> budget -> risk -> broker -> alerts on RELIANCE.NS,
    Friday 2026-10-23, synthetic bars, with the India config."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp()
        cls.data = nse_synthetic.write_all(os.path.join(cls.tmp, "nse"))
        cls.cwd = os.getcwd()
        os.chdir(cls.tmp)
        os.makedirs("trader")
        shutil.copy(os.path.join(ROOT, "trader-budget", "config.india.example.json"), "trader/config.json")
        cls.m = {name: load(folder, name) for folder, name in SCRIPTS}

    @classmethod
    def tearDownClass(cls):
        os.chdir(cls.cwd)
        shutil.rmtree(cls.tmp)

    def test_the_whole_trade(self):
        m, d = self.m, self.data
        orb = os.path.join(self.tmp, "orb")
        os.makedirs(orb)
        for s in nse_synthetic.BASES:
            shutil.copy(os.path.join(d, s + ".json"), orb)

        code, out, err = run(m["scan"], ["orb", "--offline", orb, "--now", "2026-10-23 10:15"])
        self.assertEqual(code, 0, err)
        self.assertIn("10:15 AM IST: 15-minute range (9:15 to 9:30 AM)", out)
        self.assertRegex(out, u"RELIANCE.NS +₹1,196.95")
        wl = json.load(open("trader/watchlist.json"))
        self.assertEqual(wl["market"], "in")
        self.assertEqual(len(wl["hits"]), 4)

        code, out, err = run(m["entry"], ["check", "RELIANCE", "--offline", d, "--now", "2026-10-23 10:05",
                                          "--write"])
        self.assertEqual(code, 0, err)
        self.assertIn(u"Opening range 9:15-9:30: high ₹1192.79, low ₹1182.10", out)
        self.assertIn("TRIGGERED 9:50 AM", out)
        entry = json.load(open("trader/entry.json"))
        self.assertEqual((entry["symbol"], entry["market"], entry["price"]), ("RELIANCE.NS", "in", 1196.95))

        code, out, err = run(m["exit"], ["plan", "--now", "2026-10-23 10:05", "--target", "1R", "--write"])
        self.assertEqual(code, 0, err)
        self.assertIn("Flat by       15:15 IST", out)
        plan = json.load(open("trader/plan.json"))
        self.assertEqual((plan["stop"], plan["target"], plan["flat_by"], plan["market"]),
                         (1187.44, 1206.46, "15:15", "in"))

        code, out, err = run(m["timemachine"], ["run", "--offline", os.path.join(d, "RELIANCE.NS-60d5m.json"),
                                                "--now", "2026-10-23 10:05", "--write"])
        self.assertEqual(code, 0, err)
        self.assertIn("9:50 AM to 3:30 PM (68 five-minute bars)", out)
        self.assertIn("last 59 full sessions", out)

        code, out, err = run(m["size"], ["--now", "2026-10-23 10:05", "--write"])
        self.assertEqual(code, 0, err)
        self.assertIn(u"position cap  75% of ₹5,00,000", out)
        self.assertIn("Flat by 15:15 India time", out)
        orders = json.load(open("trader/orders.json"))
        self.assertEqual(orders["market"], "in")
        self.assertEqual(orders["orders"][0]["qty"], "313")

        code, out, err = run(m["check"], ["--now", "2026-10-23 10:05"])
        self.assertEqual(code, 0, out + err)
        self.assertIn(u"max loss ₹2,976.63 (limit ₹5,000)", out)
        code, out, _ = run(m["check"], ["--now", "2026-10-23 15:10", "--no-write"])
        self.assertIn("no new entries after 15:00 India time", out)

        code, out, err = run(m["ticket"], ["show", "--now", "2026-10-23 10:06"])
        self.assertIn("your NSE broker", out)
        self.assertIn("Alpaca does not trade the NSE", out)
        self.assertNotIn("place_stock_order with exactly", out)

        code, out, err = run(m["alerts"], ["add", "--from-plan"])
        self.assertEqual(code, 0, err)
        self.assertIn('"at": "15:15"', out)
        code, out, err = run(m["alerts"], ["check", "--offline", d, "--now", "2026-10-23 15:16"])
        self.assertIn("NSE OPEN (2026-10-23 15:16 India time", out)
        self.assertIn("ALERT RELIANCE.NS is", out)
        self.assertIn("Flat by close: it is 15:16 India time (set for 15:15)", out)

    def test_news_skips_the_sec_for_nse_stocks(self):
        folder = os.path.join(self.tmp, "news")
        os.makedirs(folder, exist_ok=True)
        with open(os.path.join(folder, "yahoo-RELIANCE.NS.xml"), "w") as fh:
            fh.write('<?xml version="1.0"?><rss version="2.0"><channel><item>'
                     "<title>Q2 results: NSE: RELIANCE beats estimates</title><link>https://example.com/r</link>"
                     "<pubDate>Fri, 23 Oct 2026 03:00:00 +0000</pubDate><guid>r1</guid></item></channel></rss>")
        code, out, err = run(self.m["news"], ["--tickers", "RELIANCE.NS", "--offline", folder, "--no-moves",
                                              "--now", "2026-10-23T05:00:00Z", "--dry-run", "--state",
                                              os.path.join(folder, "state.json")])
        self.assertEqual(code, 0, err)
        self.assertIn("2026-10-23 08:30 IST  RELIANCE.NS", out)
        self.assertIn("SEC filings skipped: they cover US companies only", out)
        self.assertIn("Checked 2026-10-23 10:30 IST", out)


if __name__ == "__main__":
    unittest.main()
