"""ISIN Chain mapping for identity resolution.

Maps a stable security_id (hash of canonical symbol) to validity-dated ISINs.
"""

import hashlib

import duckdb
import pandas as pd
import polars as pl
import structlog

from indiquant.ingest.base import Source
from indiquant.ingest.calendar import TradingCalendar
from indiquant.ingest.models import RawPayload, ValidationIssue

logger = structlog.get_logger(__name__)


def generate_security_id(symbol: str) -> str:
    """Generate a stable security_id from the canonical symbol."""
    return hashlib.md5(symbol.encode("utf-8")).hexdigest()[:16]


class IsinChainSource(Source):
    """Maps security_id to validity-dated ISIN intervals.
    
    Reads from equity_daily to discover the exact dates each ISIN
    was active for each canonical symbol.
    """

    name = "nse_isin_chain"
    prime_url = "local://equity_daily"
    silver_table = "isin_chain"

    class _MinimalSchema:
        @classmethod
        def validate(cls, df: pl.DataFrame, lazy: bool = False) -> pl.DataFrame:
            return df

    schema = _MinimalSchema  # type: ignore[assignment]

    def _build_url(self, target_date):
        return "local://equity_daily"

    def _http_get(self, url):
        class LakehouseResponse:
            def __init__(self, content):
                self.content = content
                self.status_code = 200
                self.headers = {}
            def raise_for_status(self): pass

        try:
            with self.lakehouse.connection() as cur:
                eq_path = (self.lakehouse.silver_dir / "equity_daily" / "**/*.parquet").as_posix()
                query = f"""
                    SELECT symbol, isin, MIN(date) as first_seen, MAX(date) as last_seen
                    FROM read_parquet('{eq_path}', hive_partitioning = true, union_by_name = true)
                    GROUP BY symbol, isin
                    ORDER BY symbol, isin
                """
                df = cur.execute(query).df()
                content = b"empty" if df.empty else df.to_csv(index=False).encode('utf-8')
        except duckdb.IOException:
            logger.warning("isin_chain_failed", msg="equity_daily not found.")
            content = b"empty"

        return LakehouseResponse(content)

    def _parse(self, raw: RawPayload) -> pl.DataFrame:
        """Parse isin chains from the serialized lakehouse payload."""
        if not raw.body or raw.body == b"empty":
            return pl.DataFrame()
            
        import io
        segments_df = pd.read_csv(io.BytesIO(raw.body))
            
        cal = TradingCalendar()
        adj = {i: set() for i in segments_df.index}

        def add_edges(group_col):
            groups = segments_df.groupby(group_col)
            for name, group in groups:
                sorted_group = group.sort_values('first_seen')
                indices = sorted_group.index.tolist()
                for i in range(len(indices) - 1):
                    idx1 = indices[i]
                    idx2 = indices[i+1]
                    end_date = pd.to_datetime(segments_df.loc[idx1, 'last_seen']).date()
                    start_date = pd.to_datetime(segments_df.loc[idx2, 'first_seen']).date()
                    if start_date <= end_date:
                        adj[idx1].add(idx2)
                        adj[idx2].add(idx1)
                    else:
                        tdays = cal.trading_days(end_date, start_date)
                        if len(tdays) <= 2:
                            adj[idx1].add(idx2)
                            adj[idx2].add(idx1)
                        else:
                            logger.warning(
                                "adjacency_check_failed", 
                                col=group_col, 
                                val=name, 
                                end=end_date.isoformat(), 
                                start=start_date.isoformat(), 
                                gap=len(tdays)-2
                            )
                            
        # Build edges based on shared symbol or shared ISIN
        add_edges('symbol')
        add_edges('isin')

        # Find connected components (BFS)
        visited = set()
        components = []
        for node in adj:
            if node not in visited:
                comp = []
                q = [node]
                visited.add(node)
                while q:
                    curr = q.pop(0)
                    comp.append(curr)
                    for neighbor in adj[curr]:
                        if neighbor not in visited:
                            visited.add(neighbor)
                            q.append(neighbor)
                components.append(comp)

        # Assign a single security_id to each connected component
        segments_df['security_id'] = ""
        for component in components:
            comp_df = segments_df.loc[component]
            # Canonical symbol is the earliest symbol in the component
            canonical_symbol = comp_df.sort_values('first_seen').iloc[0]['symbol']
            sec_id = generate_security_id(canonical_symbol)
            segments_df.loc[component, 'security_id'] = sec_id

        # Calculate valid_to by looking ahead within each security_id
        segments_df = segments_df.sort_values(['security_id', 'first_seen'])
        segments_df['valid_from'] = segments_df['first_seen']
        segments_df['valid_to'] = segments_df.groupby(['security_id'])['first_seen'].shift(-1)
        segments_df['valid_to'] = segments_df['valid_to'].fillna(pd.to_datetime('9999-12-31').date())

        records = []
        for _, row in segments_df.iterrows():
            if not row['symbol']: continue
            records.append({
                "security_id": row['security_id'],
                "symbol": row['symbol'],
                "isin": row['isin'],
                "valid_from": pd.to_datetime(row['valid_from']).date(),
                "valid_to": pd.to_datetime(row['valid_to']).date(),
                "knowledge_date": pd.to_datetime(row['valid_from']).date()
            })
            
        return pl.DataFrame(records)

    def _validate_rules(self, df: pl.DataFrame) -> list[ValidationIssue]:
        return []

    def _promote_transform(self, bronze: pl.DataFrame) -> pl.DataFrame:
        return bronze
