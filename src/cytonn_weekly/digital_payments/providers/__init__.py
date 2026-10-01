"""Swappable drafting providers for the Digital Payments highlights drafter."""

from cytonn_weekly.digital_payments.providers.base import (
    DraftingProvider,
    HighlightResult,
    OutlookResult,
)

__all__ = ["DraftingProvider", "HighlightResult", "OutlookResult"]
