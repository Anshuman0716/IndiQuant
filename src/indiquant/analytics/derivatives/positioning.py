import polars as pl

class PositioningAnalytics:
    def __init__(self, oi_df: pl.DataFrame):
        """
        oi_df: The participant_oi DataFrame containing daily positions by client_type.
        """
        self.oi = oi_df.sort(["date", "client_type"])
        
    def get_fii_index_futures_ratio(self) -> pl.DataFrame:
        """
        FII long/short ratio in index futures over time.
        """
        fii = self.oi.filter(pl.col("client_type") == "FII")
        return fii.select([
            "date",
            (pl.col("fut_idx_long") / (pl.col("fut_idx_short") + 1)).alias("fii_ls_ratio_idx_fut")
        ])
        
    def get_positioning_divergence(self) -> pl.DataFrame:
        """
        Client vs Pro vs DII positioning divergence.
        Uses net index futures position (Long - Short) for each category over time.
        """
        net_pos = self.oi.with_columns(
            (pl.col("fut_idx_long") - pl.col("fut_idx_short")).alias("net_idx_fut")
        ).select(["date", "client_type", "net_idx_fut"])
        
        # Pivot to have client types as columns
        divergence = net_pos.pivot(
            values="net_idx_fut",
            index="date",
            on="client_type",
            aggregate_function="sum"
        ).sort("date")
        
        return divergence
        
    def get_percentile_extremes(self, lookback: int = 252) -> pl.DataFrame:
        """
        Percentile-ranked positioning extremes for FII index futures ratio.
        """
        fii_ratio = self.get_fii_index_futures_ratio()
        
        # Calculate rolling percentile
        # A simple approximation: rank over rolling window / window size
        def rolling_rank(s: pl.Series) -> pl.Series:
            return s.rolling_map(lambda x: (x.rank()[-1] / len(x)), window_size=lookback)
            
        fii_ratio = fii_ratio.with_columns(
            pl.col("fii_ls_ratio_idx_fut")
            .rolling_map(
                lambda s: (s.to_pandas().rank(pct=True).iloc[-1]) if len(s) == lookback else None,
                window_size=lookback
            ).alias("fii_ls_ratio_percentile")
        )
        return fii_ratio
