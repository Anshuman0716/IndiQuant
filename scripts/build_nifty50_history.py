import io
import json
import httpx
import pandas as pd
import polars as pl
from datetime import datetime, UTC
from pathlib import Path
import duckdb

def map_symbol(name, symbols_list):
    """Simple heuristic mapping."""
    name = name.lower()
    for sym in symbols_list:
        if sym.lower() in name or name.split()[0] in sym.lower():
            return sym
    return None

def build_nifty50_history():
    print("Fetching Wikipedia NIFTY 50...")
    r = httpx.get("https://en.wikipedia.org/wiki/NIFTY_50", headers={"User-Agent": "IndiQuant/1.0"})
    dfs = pd.read_html(io.StringIO(r.text))
    
    current_df = dfs[1]
    replacements_df = dfs[2]
    replacements_df.columns = replacements_df.columns.droplevel(0)
    
    # Extract current constituents
    current_symbols = [str(x) for x in current_df["Symbol"].tolist() if pd.notna(x)]
    
    # We need a list of all symbols in our lakehouse to map excluded/included names
    base_dir = Path("data/silver")
    eq_path = (base_dir / "equity_daily" / "**/*.parquet").as_posix()
    
    print("Fetching available symbols from lakehouse...")
    try:
        with duckdb.connect() as con:
            lakehouse_symbols = con.execute(f"SELECT DISTINCT symbol, isin FROM read_parquet('{eq_path}')").pl()
    except duckdb.IOException:
        print("equity_daily not found!")
        return
        
    symbol_isin_map = dict(zip(lakehouse_symbols["symbol"].to_list(), lakehouse_symbols["isin"].to_list()))
    all_symbols = list(symbol_isin_map.keys())
    
    # Manual mapping for some tricky names in Wikipedia
    manual_map = {
        "Indian Hotels Company": "INDHOTEL",
        "Colgate-Palmolive India": "COLPAL",
        "Shipping Corporation of India": "SCI",
        "Tata Chemicals": "TATACHEM",
        "Tata Tea": "TATACONSUM",
        "Jet Airways": "JETAIRWAYS",
        "Oriental Bank of Commerce": "OBC",
        "Dabur": "DABUR",
        "IPCL": "IPCL",
        "Hindustan Petroleum": "HINDPETRO",
        "GlaxoSmithKline Pharmaceuticals": "GLAXO",
        "National Aluminium Company": "NATIONALUM",
        "Tribhovandas Bhimji Zaveri": "TBZ",
        "Ambuja Cements": "AMBUJACEM",
        "Siemens": "SIEMENS",
        "Vedanta": "VEDL",
        "Cairn India": "CAIRN",
        "Zee Entertainment Enterprises": "ZEEL",
        "Yes Bank": "YESBANK",
        "Indiabulls Housing Finance": "IBULHSGFIN",
        "Gail (India)": "GAIL",
        "L&T Finance": "LTF",
        "Shriram Transport Finance": "SRTRANSFIN",
        "HDFC": "HDFC",
        "HDFC Bank": "HDFCBANK",
        "UPL": "UPL",
        "Shree Cement": "SHREECEM",
        "Divi's Laboratories": "DIVISLAB",
        "Apollo Hospitals": "APOLLOHOSP",
        "Info Edge": "NAUKRI",
        "LTIMindtree": "LTIM",
        "Jio Financial Services": "JIOFIN",
        "Shriram Finance": "SHRIRAMFIN",
        "Bharat Electronics": "BEL",
        "Trent": "TRENT",
        "Housing Development Finance Corporation": "HDFC",
        "Grasim Industries": "GRASIM",
        "BHEL": "BHEL",
        "Idea Cellular": "IDEA",
        "Jindal Steel & Power": "JINDALSTEL",
        "Punjab National Bank": "PNB",
        "Bank of Baroda": "BANKBARODA",
        "Tata Power": "TATAPOWER",
        "DLF": "DLF",
        "Ambuja Cement": "AMBUJACEM",
        "Aurobindo Pharma": "AUROPHARMA",
        "Bosch": "BOSCHLTD",
        "ACC": "ACC",
        "Tata Motors DVR": "TATAMTRDVR",
        "Infratel": "INFRATEL",
        "Bharti Infratel": "INFRATEL",
        "IndusInd Bank": "INDUSINDBK",
        "Bajaj Finserv": "BAJAJFINSV",
        "Bajaj Finance": "BAJFINANCE",
        "Kotak Mahindra Bank": "KOTAKBANK",
        "Hero MotoCorp": "HEROMOTOCO",
        "Coal India": "COALINDIA",
        "Asian Paints": "ASIANPAINT",
        "Titan Company": "TITAN",
        "Eicher Motors": "EICHERMOT",
        "JSW Steel": "JSWSTEEL",
        "Nestle India": "NESTLEIND",
        "SBI Life Insurance Company": "SBILIFE",
        "HDFC Life": "HDFCLIFE",
        "Tata Consumer Products": "TATACONSUM",
    }
    
    def resolve_symbol(name):
        if pd.isna(name): return None
        if name in manual_map: return manual_map[name]
        for sym in current_symbols:
            if sym.lower() in name.lower() or name.lower().startswith(sym.lower()[:5]):
                return sym
        return None
        
    records = []
    
    # We will assume a base date of 2012-01-01 where the index was exactly the current constituents
    # MINUS all the included ones since 2012, PLUS all the excluded ones since 2012.
    
    # Parse replacements
    replacements = []
    for _, row in replacements_df.iterrows():
        date_str = str(row["Date of replacement"])
        try:
            repl_date = pd.to_datetime(date_str).date().isoformat()
        except:
            continue
            
        if repl_date < "2012-01-01":
            continue
            
        excl = resolve_symbol(row["Constituent excluded"])
        incl = resolve_symbol(row["Constituent included"])
        
        if excl: replacements.append({"date": repl_date, "symbol": excl, "type": "exclusion"})
        if incl: replacements.append({"date": repl_date, "symbol": incl, "type": "inclusion"})
        
    # Start with current set
    current_set = set(current_symbols)
    
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
                intervals.append({
                    "symbol": sym, "valid_from": valid_from, "valid_to": dt
                })
        elif r["type"] == "inclusion":
            if sym not in active:
                active[sym] = dt
                
    # Close open intervals
    for sym, valid_from in active.items():
        intervals.append({
            "symbol": sym, "valid_from": valid_from, "valid_to": ""
        })
        
    final_records = []
    for i in intervals:
        isin = symbol_isin_map.get(i["symbol"], "")
        final_records.append({
            "isin": isin,
            "index_name": "NIFTY 50",
            "valid_from": i["valid_from"],
            "valid_to": i["valid_to"],
            "knowledge_date": i["valid_from"],
            "source": "wikipedia_nifty50_history",
            "ingested_at": datetime.now(UTC).isoformat(),
            "raw_hash": "static_hash"
        })
        
    df = pl.DataFrame(final_records)
    
    out_dir = base_dir / "index_membership" / "year=2012"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_file = out_dir / "data_wikipedia.parquet"
    df.write_parquet(out_file)
    print(f"Wrote {len(df)} NIFTY 50 intervals to {out_file}")

if __name__ == "__main__":
    build_nifty50_history()
