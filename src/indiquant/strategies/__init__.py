"""Reference strategies."""

from .momentum import generate_momentum_weights
from .quality_value import generate_quality_value_weights
from .mean_reversion import generate_mean_reversion_weights
from .tapetide_composite import generate_tapetide_composite_weights

__all__ = [
    "generate_momentum_weights",
    "generate_quality_value_weights",
    "generate_mean_reversion_weights",
    "generate_tapetide_composite_weights",
]
