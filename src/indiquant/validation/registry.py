"""Trial registry for anti-overfitting harness."""
import functools
import hashlib
import inspect
import json
import uuid
from datetime import datetime
import pandas as pd
import structlog
import subprocess

from indiquant.config.settings import IndiQuantSettings

logger = structlog.get_logger(__name__)


def _get_git_sha():
    try:
        return subprocess.check_output(["git", "rev-parse", "HEAD"]).decode("utf-8").strip()
    except Exception:
        return "unknown"


def _hash_config(params: dict) -> str:
    j = json.dumps(params, sort_keys=True)
    return hashlib.sha256(j.encode()).hexdigest()


class TrialRegistry:
    def __init__(self, settings: IndiQuantSettings):
        self.settings = settings
        self.db_path = str(settings.data_dir / "registry.duckdb")
        self._init_db()

    def _init_db(self):
        import duckdb
        with duckdb.connect(self.db_path) as conn:
            conn.execute("""
                CREATE SEQUENCE IF NOT EXISTS trial_seq;
                CREATE TABLE IF NOT EXISTS trials (
                    run_id VARCHAR PRIMARY KEY,
                    timestamp TIMESTAMP,
                    git_sha VARCHAR,
                    config_hash VARCHAR,
                    strategy_name VARCHAR,
                    universe_spec VARCHAR,
                    start_date DATE,
                    end_date DATE,
                    params_json VARCHAR,
                    gross_sharpe DOUBLE,
                    net_sharpe DOUBLE,
                    net_cagr DOUBLE,
                    max_dd DOUBLE,
                    turnover DOUBLE,
                    n_trades INTEGER,
                    data_snapshot_hash VARCHAR,
                    tags VARCHAR,
                    notes VARCHAR
                );
            """)

    def record_trial(self, trial_data: dict):
        import duckdb
        trial_data["run_id"] = trial_data.get("run_id", str(uuid.uuid4()))
        trial_data["timestamp"] = datetime.now()
        trial_data["git_sha"] = _get_git_sha()
        
        # Hash params
        if "params" in trial_data:
            trial_data["params_json"] = json.dumps(trial_data["params"])
            trial_data["config_hash"] = _hash_config(trial_data["params"])
            del trial_data["params"]
            
        # Ensure all columns exist
        cols = [
            "run_id", "timestamp", "git_sha", "config_hash", "strategy_name", 
            "universe_spec", "start_date", "end_date", "params_json", 
            "gross_sharpe", "net_sharpe", "net_cagr", "max_dd", 
            "turnover", "n_trades", "data_snapshot_hash", "tags", "notes"
        ]
        
        row = {c: trial_data.get(c, None) for c in cols}
        
        with duckdb.connect(self.db_path) as conn:
            conn.execute(
                f"""
                INSERT INTO trials ({', '.join(cols)}) 
                VALUES ({', '.join(['?'] * len(cols))})
                """,
                [row[c] for c in cols]
            )
            
        logger.info("recorded_trial", run_id=row["run_id"], strategy=row["strategy_name"])

    def trial_count(self, strategy_name: str, since: datetime = None) -> int:
        import duckdb
        with duckdb.connect(self.db_path) as conn:
            query = "SELECT COUNT(*) FROM trials WHERE strategy_name = ?"
            args = [strategy_name]
            if since:
                query += " AND timestamp >= ?"
                args.append(since)
            res = conn.execute(query, args).fetchone()
            return res[0] if res else 0


def record_run(strategy_name: str):
    """Decorator to automatically record a backtest run to the registry."""
    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            # Extract bound arguments
            sig = inspect.signature(func)
            bound = sig.bind(*args, **kwargs)
            bound.apply_defaults()
            params = bound.arguments
            
            # Execute strategy
            metrics = func(*args, **kwargs)
            
            # Reconstruct trial data
            settings = IndiQuantSettings()
            registry = TrialRegistry(settings)
            
            trial_data = {
                "strategy_name": strategy_name,
                "universe_spec": params.get("index_name", "ALL"),
                "start_date": params.get("start_date"),
                "end_date": params.get("end_date"),
                "params": {k: str(v) for k, v in params.items() if k not in ["ctx"]},
                "gross_sharpe": metrics.get("gross_sharpe"),
                "net_sharpe": metrics.get("net_sharpe"),
                "net_cagr": metrics.get("net_cagr"),
                "max_dd": metrics.get("max_dd"),
                "turnover": metrics.get("turnover"),
                "n_trades": metrics.get("n_trades"),
                "tags": metrics.get("tags", ""),
                "notes": metrics.get("notes", ""),
            }
            registry.record_trial(trial_data)
            return metrics
        return wrapper
    return decorator
