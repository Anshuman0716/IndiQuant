import polars as pl

class OIAnalytics:
    def __init__(self, fo_df: pl.DataFrame):
        """
        fo_df: NSE F&O daily bhavcopy DataFrame
        """
        self.fo = fo_df
        
    def buildup_classification(self) -> pl.DataFrame:
        """
        OI build-up classification from sign(Δprice) × sign(ΔOI)
        Long Buildup: +Price, +OI
        Short Buildup: -Price, +OI
        Short Covering: +Price, -OI
        Long Unwinding: -Price, -OI
        """
        return self.fo.with_columns([
            pl.when((pl.col("close") > pl.col("open")) & (pl.col("change_in_oi") > 0))
            .then(pl.lit("Long Buildup"))
            .when((pl.col("close") < pl.col("open")) & (pl.col("change_in_oi") > 0))
            .then(pl.lit("Short Buildup"))
            .when((pl.col("close") > pl.col("open")) & (pl.col("change_in_oi") < 0))
            .then(pl.lit("Short Covering"))
            .when((pl.col("close") < pl.col("open")) & (pl.col("change_in_oi") < 0))
            .then(pl.lit("Long Unwinding"))
            .otherwise(pl.lit("Neutral"))
            .alias("buildup_type")
        ])

    def put_call_ratio(self) -> pl.DataFrame:
        """
        Put-call ratio, OI-based and volume-based, stock and index level
        """
        # separate options
        options = self.fo.filter(pl.col("option_type").is_in(["CE", "PE"]))
        
        agg = options.group_by(["date", "symbol", "instrument"]).agg([
            pl.col("open_interest").filter(pl.col("option_type") == "PE").sum().alias("total_pe_oi"),
            pl.col("open_interest").filter(pl.col("option_type") == "CE").sum().alias("total_ce_oi"),
            pl.col("volume").filter(pl.col("option_type") == "PE").sum().alias("total_pe_vol"),
            pl.col("volume").filter(pl.col("option_type") == "CE").sum().alias("total_ce_vol")
        ])
        
        return agg.with_columns([
            (pl.col("total_pe_oi") / (pl.col("total_ce_oi") + 1)).alias("pcr_oi"),
            (pl.col("total_pe_vol") / (pl.col("total_ce_vol") + 1)).alias("pcr_vol")
        ])
