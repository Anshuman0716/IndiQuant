"""Exclusion flags for universe construction.

Handles filtering out securities under ASM/GSM, Trade-to-Trade (T2T),
suspended trading, or F&O ban.
"""

from dataclasses import dataclass
from datetime import date

import structlog

from indiquant.store.lakehouse import Lakehouse

logger = structlog.get_logger(__name__)


@dataclass
class FlagResult:
    """Result of flag screening."""

    passed: list[str]
    rejected: dict[str, str]  # ISIN -> Reason for rejection


def screen_flags(
    lakehouse: Lakehouse,
    isins: list[str],
    asof: date,
    exclude_t2t: bool = True,
    exclude_asm_gsm: bool = True,
    exclude_suspended: bool = True,
    exclude_fo_ban: bool = True,
) -> FlagResult:
    """Apply regulatory and exchange flags as of a specific date.

    Args:
        lakehouse: Lakehouse instance.
        isins: Initial universe of ISINs.
        asof: Point-in-time date.
        exclude_t2t: Exclude Trade-to-Trade segment (BE series).
        exclude_asm_gsm: Exclude Additional/Graded Surveillance Measure.
        exclude_suspended: Exclude suspended securities.
        exclude_fo_ban: Exclude securities in F&O ban period.

    Returns:
        FlagResult with passed ISINs and rejection reasons.
    """
    if not isins:
        return FlagResult(passed=[], rejected={})

    # TODO: Implement robust checks when the specific source files
    # (MWPL for F&O ban, Surveillance lists for ASM/GSM, series data for T2T)
    # are fully integrated into the lakehouse silver layer.

    passed = []
    rejected: dict[str, str] = {}

    # Placeholder: currently passes all ISINs until the underlying
    # surveillance and MWPL sources are added to Phase 1 ingestion.
    for isin in isins:
        passed.append(isin)

    return FlagResult(passed=passed, rejected=rejected)
