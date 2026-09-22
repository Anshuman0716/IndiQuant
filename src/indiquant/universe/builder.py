"""Universe orchestrator and snapshot builder.

Produces survivorship-free universes as of a specific point in time,
applying index membership, liquidity gates, and exclusion flags.
"""

from dataclasses import dataclass
from datetime import date

import structlog

from indiquant.store.lakehouse import Lakehouse
from indiquant.universe.delisting import get_delisting_info
from indiquant.universe.flags import screen_flags
from indiquant.universe.liquidity import screen_liquidity
from indiquant.universe.membership import constituents

logger = structlog.get_logger(__name__)


@dataclass
class UniverseMember:
    """A single security in the universe snapshot."""

    isin: str
    delisting_date: date | None
    terminal_haircut: float | None
    delisting_reason: str = "unknown"


@dataclass
class UniverseSnapshot:
    """A point-in-time universe snapshot with full audit trail."""

    asof: date
    index_name: str
    members: list[UniverseMember]
    audit_trail: dict[str, str]  # ISIN -> Rejection Reason
    flags_status: dict[str, str]  # System status checks (e.g. {"asm_gsm": "unchecked"})


def build_universe(
    lakehouse: Lakehouse,
    index_name: str,
    asof: date,
    min_price: float = 10.0,
    min_turnover: float = 1_000_000.0,
    terminal_haircut: float = -0.30,
) -> UniverseSnapshot:
    """Build a survivorship-free universe.

    Args:
        lakehouse: Lakehouse instance.
        index_name: The index to base the universe on (e.g. 'NIFTY 500').
        asof: The point-in-time date.
        min_price: Minimum median close price (Rs).
        min_turnover: Minimum median daily turnover.
        terminal_haircut: Default return applied on delisting (-30%).

    Returns:
        UniverseSnapshot containing active members and exclusion audit trail.
    """
    logger.info(
        "building_universe",
        index=index_name,
        asof=asof.isoformat(),
    )

    audit_trail: dict[str, str] = {}

    # 1. Base index membership (Point in time)
    base_isins = constituents(index_name, asof, lakehouse)
    if len(base_isins) == 0:
        logger.warning("universe_empty_base", index=index_name, asof=asof.isoformat())
        return UniverseSnapshot(
            asof=asof, 
            index_name=index_name, 
            members=[], 
            audit_trail={},
            flags_status={},
        )

    # 2. Liquidity screening
    liq_res = screen_liquidity(
        lakehouse,
        base_isins["isin"].tolist(),
        asof,
        min_price=min_price,
        min_turnover=min_turnover,
    )
    audit_trail.update(liq_res.rejected)

    # 3. Regulatory flags (ASM/GSM, T2T)
    flag_res = screen_flags(lakehouse, liq_res.passed, asof)
    audit_trail.update(flag_res.rejected)

    active_isins = flag_res.passed

    # 4. Delisting information for active names
    delisting_info = get_delisting_info(
        lakehouse,
        active_isins,
        asof,
        terminal_haircut=terminal_haircut,
    )

    members = []
    for isin in active_isins:
        info = delisting_info.get(isin, {})
        members.append(
            UniverseMember(
                isin=isin,
                delisting_date=info.get("delisting_date"),
                terminal_haircut=info.get("haircut"),
                delisting_reason=info.get("delisting_reason", "unknown"),
            )
        )

    logger.info(
        "universe_built",
        index=index_name,
        asof=asof.isoformat(),
        base_size=len(base_isins),
        final_size=len(members),
    )

    return UniverseSnapshot(
        asof=asof,
        index_name=index_name,
        members=members,
        audit_trail=audit_trail,
        flags_status=flag_res.status,
    )
