"""Notable this week: suggestions computed by code from history, shown to the analyst with their working.

The analyst accepts, edits or dismisses each one.  Nothing a suggestion says is ever written into a draft, a figure, a
review item, the analyst inputs form or the Word export; the only thing saved is the analyst's decision (store.py).
This package imports nothing that drafts, checks, exports, fetches or calls a model, and a test keeps it so.
"""

from cytonn_weekly.notable.registry import REGISTRY

__all__ = ["REGISTRY"]
