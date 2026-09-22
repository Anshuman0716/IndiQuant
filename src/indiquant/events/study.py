import polars as pl
import numpy as np
import scipy.stats as stats

class EventStudyEngine:
    def __init__(self, returns_df: pl.DataFrame):
        """
        Initialize with a DataFrame of daily returns.
        Expected columns: ['symbol', 'date', 'ret']
        """
        # Ensure we have a strictly increasing trading day index per symbol
        self.returns = (
            returns_df
            .sort(["symbol", "date"])
            .with_columns([
                pl.int_range(1, pl.len() + 1).over("symbol").alias("td_idx")
            ])
        )

    def run(self, events_df: pl.DataFrame, window_start: int = -20, window_end: int = 60) -> dict:
        """
        Run the event study.
        events_df expected columns: ['symbol', 'date']
        """
        # 1. Join events to returns to get the base td_idx for each event
        events = events_df.join(
            self.returns.select(["symbol", "date", "td_idx"]).rename({"td_idx": "event_td_idx"}),
            on=["symbol", "date"],
            how="inner"
        )
        
        # 2. Add an event ID
        events = events.with_row_index("event_id")
        
        # 3. Create a dataframe of relative days [window_start, window_end]
        rel_days = pl.DataFrame({"rel_day": range(window_start, window_end + 1)})
        
        # 4. Cross join events with relative days
        event_windows = events.join(rel_days, how="cross")
        event_windows = event_windows.with_columns(
            (pl.col("event_td_idx") + pl.col("rel_day")).alias("target_td_idx")
        )
        
        # 5. Join back to returns to get the actual return on that relative day
        merged = event_windows.join(
            self.returns.select(["symbol", "td_idx", "ret"]),
            left_on=["symbol", "target_td_idx"],
            right_on=["symbol", "td_idx"],
            how="left"
        )
        
        # 6. Calculate cumulative returns per event
        # Fill missing returns with 0 to allow cumsum
        merged = merged.with_columns(pl.col("ret").fill_null(0.0))
        merged = merged.sort(["event_id", "rel_day"])
        
        # CAR = Cumulative sum of returns within the event window
        merged = merged.with_columns(
            pl.col("ret").cum_sum().over("event_id").alias("car")
        )
        
        # 7. Aggregate cross-sectional stats per relative day
        agg_stats = (
            merged.group_by("rel_day")
            .agg([
                pl.col("car").mean().alias("mean_car"),
                pl.col("car").std().alias("std_car"),
                pl.col("car").count().alias("n_events"),
            ])
            .sort("rel_day")
        )
        
        # 8. Bootstrap Confidence Intervals for the Mean CAR
        # We will do B=1000 cross-sectional resamples of the events
        # Note: A time-series block bootstrap could be used if event outcomes strongly overlap in calendar time,
        # but for cross-sectional event studies, resampling the event IDs is standard.
        B = 1000
        np.random.seed(42)
        unique_events = events["event_id"].to_numpy()
        n_ev = len(unique_events)
        
        # Convert merged to a pandas dataframe for faster resampling grouped by rel_day
        # Actually, Polars is fast: we can just construct a massive array of resampled event IDs
        # For simplicity and speed in python, we'll extract the CAR matrix: shape (n_events, n_rel_days)
        
        pivot_df = merged.pivot(values="car", index="event_id", on="rel_day").sort("event_id")
        car_matrix = pivot_df.drop("event_id").to_numpy() # shape: (n_events, n_rel_days)
        
        # Resample indices
        # shape: (B, n_events)
        resampled_idx = np.random.randint(0, n_ev, size=(B, n_ev))
        
        # Calculate mean for each bootstrap sample
        # car_matrix[resampled_idx] gives shape (B, n_events, n_rel_days)
        # .mean(axis=1) gives shape (B, n_rel_days)
        boot_means = car_matrix[resampled_idx].mean(axis=1)
        
        # Get 2.5th and 97.5th percentiles
        ci_lower = np.percentile(boot_means, 2.5, axis=0)
        ci_upper = np.percentile(boot_means, 97.5, axis=0)
        
        # Add to agg_stats
        agg_stats = agg_stats.with_columns([
            pl.Series("boot_ci_lower", ci_lower),
            pl.Series("boot_ci_upper", ci_upper),
        ])
        
        return {
            "stats": agg_stats,
            "raw_events": merged
        }
