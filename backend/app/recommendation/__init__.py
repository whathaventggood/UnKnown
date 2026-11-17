"""Pure, deterministic recommendation; no database, network or LLM dependency."""

from .engine import DEFAULT_CONFIG, STRATEGY_VERSION, diversity, learnability, novelty, recommend

__all__ = ["DEFAULT_CONFIG", "STRATEGY_VERSION", "diversity", "learnability", "novelty", "recommend"]
