"""Bounded, source-specific public metadata ingestion. Never invoked on a recommendation request."""
from .adapters import MediaWikiAdapter, WikidataAdapter, OpenAlexAdapter, SourceError

__all__ = ["MediaWikiAdapter", "WikidataAdapter", "OpenAlexAdapter", "SourceError"]
