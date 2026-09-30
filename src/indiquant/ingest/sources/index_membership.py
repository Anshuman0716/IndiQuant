"""Historical NIFTY 50 index membership.

THIS IS THE SURVIVORSHIP FIX — AGENTS.md Rule #2.

Sources:
  - Wikipedia: https://en.wikipedia.org/wiki/NIFTY_50
    (NSE's official IndexInclExcl.csv endpoint is permanently 404).

Output: (index_name, isin, valid_from, valid_to) with valid_to=NULL for current.
"""

import io
from datetime import date

import pandas as pd
import polars as pl
import structlog

from indiquant.ingest.base import Source
from indiquant.ingest.models import RawPayload, ValidationIssue

logger = structlog.get_logger(__name__)

# Master historical inclusion/exclusion file
_WIKI_URL = "https://en.wikipedia.org/wiki/NIFTY_50"

# Manual mapping for tricky Wikipedia names that don't match simple substring searches
_MANUAL_MAP = {
    "ABB India": "ABB",
    "ACC": "ACC",
    "Adani Enterprises": "ADANIENT",
    "Adani Ports & SEZ": "ADANIPORTS",
    "Ambuja Cements": "AMBUJACEM",
    "Apollo Hospitals": "APOLLOHOSP",
    "Asian Paints": "ASIANPAINT",
    "Aurobindo Pharma": "AUROPHARMA",
    "Axis Bank": "AXISBANK",
    "BHEL": "BHEL",
    "Bajaj Auto": "BAJAJ-AUTO",
    "Bajaj Finance": "BAJFINANCE",
    "Bajaj Finserv": "BAJAJFINSV",
    "Bank of Baroda": "BANKBARODA",
    "Bharat Electronics": "BEL",
    "Bharat Petroleum": "BPCL",
    "Bharti Airtel": "BHARTIARTL",
    "Bharti Infratel": "INFRATEL",
    "Bosch India": "BOSCHLTD",
    "Britannia Industries": "BRITANNIA",
    "Cairn India": "CAIRN",
    "Cipla": "CIPLA",
    "Coal India": "COALINDIA",
    "Colgate-Palmolive India": "COLPAL",
    "DLF": "DLF",
    "Dabur": "DABUR",
    "Divi's Laboratories": "DIVISLAB",
    "Dr. Reddy's Laboratories": "DRREDDY",
    "Eicher Motors": "EICHERMOT",
    "Eternal": "ETERNAL",
    "GAIL": "GAIL",
    "GlaxoSmithKline Pharmaceuticals": "GLAXO",
    "Grasim Industries": "GRASIM",
    "HCLTech": "HCLTECH",
    "HDFC": "HDFC",
    "HDFC Bank": "HDFCBANK",
    "HDFC Life": "HDFCLIFE",
    "Hero MotoCorp": "HEROMOTOCO",
    "Hindalco Industries": "HINDALCO",
    "Hindustan Petroleum": "HINDPETRO",
    "Hindustan Unilever": "HINDUNILVR",
    "ICICI Bank": "ICICIBANK",
    "IDFC": "IDFC",
    "IPCL": "IPCL",
    "ITC": "ITC",
    "Idea Cellular": "IDEA",
    "IndiGo": "INDIGO",
    "Indiabulls Housing Finance": "IBULHSGFIN",
    "Indian Hotels Company": "INDHOTEL",
    "Indian Oil Corporation": "IOC",
    "IndusInd Bank": "INDUSINDBK",
    "Infosys": "INFY",
    "JP Associates": "JPASSOCIAT",
    "JSW Steel": "JSWSTEEL",
    "Jaiprakash Associates": "JPASSOCIAT",
    "Jet Airways": "JETAIRWAYS",
    "Jindal Steel & Power": "JINDALSTEL",
    "Jio Financial Services": "JIOFIN",
    "Kotak Mahindra Bank": "KOTAKBANK",
    "LTIMindtree": "LTIM",
    "Larsen & Toubro": "LT",
    "Lupin": "LUPIN",
    "MTNL": "MTNL",
    "Mahindra & Mahindra": "M&M",
    "Maruti Suzuki": "MARUTI",
    "Max Healthcare": "MAXHEALTH",
    "NALCO": "NATIONALUM",
    "NMDC": "NMDC",
    "NTPC": "NTPC",
    "Nestl India": "NESTLEIND",
    "Nestlé India": "NESTLEIND",
    "Oil and Natural Gas Corporation": "ONGC",
    "Oriental Bank of Commerce": "OBC",
    "Power Grid": "POWERGRID",
    "Punjab National Bank": "PNB",
    "Ranbaxy Laboratories": "RANBAXY",
    "Reliance Capital": "RELCAPITAL",
    "Reliance Communications": "RCOM",
    "Reliance Industries": "RELIANCE",
    "Reliance Infrastructure": "RELINFRA",
    "Reliance Petroleum": "RPL",
    "Reliance Power": "RPOWER",
    "SBI Life Insurance Company": "SBILIFE",
    "Satyam Computer Services": "SATYAMCOMP",
    "Sesa Goa": "VEDL",
    "Shipping Corporation of India": "SCI",
    "Shree Cement": "SHREECEM",
    "Shriram Finance": "SHRIRAMFIN",
    "Siemens India": "SIEMENS",
    "State Bank of India": "SBIN",
    "Steel Authority of India": "SAIL",
    "Sterlite Industries": "STERLITE",
    "Sun Pharma": "SUNPHARMA",
    "Suzlon": "SUZLON",
    "Tata Chemicals": "TATACHEM",
    "Tata Communications": "TATACOMM",
    "Tata Consultancy Services": "TCS",
    "Tata Consumer Products": "TATACONSUM",
    "Tata Motors": "TATAMOTORS",
    "Tata Motors Passenger Vehicles": "TATAMOTORS",
    "Tata Power": "TATAPOWER",
    "Tata Steel": "TATASTEEL",
    "Tata Tea": "TATATEA",
    "Tech Mahindra": "TECHM",
    "Titan Company": "TITAN",
    "Trent": "TRENT",
    "UPL": "UPL",
    "UltraTech Cement": "ULTRACEMCO",
    "Unitech": "UNITECH",
    "United Spirits": "MCDOWELL-N",
    "Vedanta": "VEDL",
    "Wipro": "WIPRO",
    "Yes Bank": "YESBANK",
    "Zee Entertainment Enterprises": "ZEEL",
}


class IndexMembershipSource(Source):
    """Historical NIFTY 50 index constituency.

    Scrapes Wikipedia since NSE's official CSV is dead.
    Constructs validity-dated intervals by parsing the current list
    and rolling backwards through historical changes.
    """

    name = "nse_index_membership"
    prime_url = "https://en.wikipedia.org"
    silver_table = "index_membership"
    rate_limit_rps = 1.0
    min_rows = 1

    class _MinimalSchema:
        """Placeholder until full schema is defined."""

        @classmethod
        def validate(cls, df: pl.DataFrame, lazy: bool = False) -> pl.DataFrame:
            return df

    schema = _MinimalSchema  # type: ignore[assignment]

    def _build_url(self, target_date: date) -> str:
        return _WIKI_URL

    def _http_get(self, url: str):
        self._throttle()
        resp = self.client.get(url, timeout=30)
        resp.raise_for_status()
        return resp

    def _parse(self, raw: RawPayload) -> pl.DataFrame:
        """Parse Wikipedia NIFTY 50 tables into intervals."""
        # Using pandas read_html to parse the tables from the HTML body
        dfs = pd.read_html(io.StringIO(raw.body.decode("utf-8", errors="ignore")))

        # Table 1 is usually Current Constituents
        # Table 2 is usually Historical Changes
        current_df = dfs[1]
        replacements_df = dfs[2]
        if isinstance(replacements_df.columns, pd.MultiIndex):
            replacements_df.columns = replacements_df.columns.droplevel(0)

        current_symbols = []
        for x in current_df["Symbol"].tolist():
            if pd.notna(x):
                sym = str(x).strip()
                if sym == "TMPV":
                    sym = "TATAMOTORS"
                current_symbols.append(sym)

        def resolve_symbol(name: str) -> str | None:
            if pd.isna(name):
                return None
            name = str(name).strip()
            # Handle non-breaking spaces or strange characters from Wikipedia
            name = name.replace("\xa0", " ")
            if name in _MANUAL_MAP:
                return _MANUAL_MAP[name]

            # If not explicitly mapped, try exact match
            for sym in current_symbols:
                if name.upper() == sym.upper():
                    return sym

            logger.warning("Unmapped Wikipedia constituent name", name=name)
            return None

        replacements = []
        for _, row in replacements_df.iterrows():
            date_col = row.get("Date of replacement")
            if pd.isna(date_col):
                continue

            try:
                dt_obj = pd.to_datetime(str(date_col))
                repl_date = dt_obj.date().isoformat()
            except Exception:
                continue

            # We only track back to 2012-01-01
            if repl_date < "2012-01-01":
                continue

            excl = resolve_symbol(row.get("Constituent excluded"))
            incl = resolve_symbol(row.get("Constituent included"))

            if excl:
                replacements.append({"date": repl_date, "symbol": excl, "type": "exclusion"})
            if incl:
                replacements.append({"date": repl_date, "symbol": incl, "type": "inclusion"})

        # Start with current set
        current_set = set()
        for _, row in current_df.iterrows():
            sym = resolve_symbol(row.get("Company name"))
            if sym:
                current_set.add(sym)

        # Roll back to 2012-01-01
        for r in sorted(replacements, key=lambda x: x["date"], reverse=True):
            if r["type"] == "inclusion":
                if r["symbol"] in current_set:
                    current_set.remove(r["symbol"])
            elif r["type"] == "exclusion":
                current_set.add(r["symbol"])

        # Now we have the set at 2012-01-01. Build forward intervals
        active = {sym: "2012-01-01" for sym in current_set}
        intervals = []

        for r in sorted(replacements, key=lambda x: x["date"]):
            sym = r["symbol"]
            dt = r["date"]

            if r["type"] == "exclusion":
                if sym in active:
                    valid_from = active.pop(sym)
                    intervals.append({"symbol": sym, "valid_from": valid_from, "valid_to": dt})
            elif r["type"] == "inclusion" and sym not in active:
                active[sym] = dt

        # Close open intervals
        for sym, valid_from in active.items():
            intervals.append({"symbol": sym, "valid_from": valid_from, "valid_to": None})

        import hashlib

        records = []
        for i in intervals:
            sym = i["symbol"]
            sec_id = hashlib.md5(sym.encode("utf-8")).hexdigest()[:16] if sym else ""
            records.append(
                {
                    "index_name": "NIFTY 50",
                    "security_id": sec_id,
                    "symbol": sym,
                    "valid_from": i["valid_from"],
                    "valid_to": i["valid_to"],
                    "knowledge_date": i["valid_from"],
                }
            )

        return pl.DataFrame(records)

    def _validate_rules(self, df: pl.DataFrame) -> list[ValidationIssue]:
        return []

    def _promote_transform(self, bronze: pl.DataFrame) -> pl.DataFrame:
        """No transformations needed for index_membership."""
        return bronze
