"""The detector library for "Notable this week": plain functions over a series that return suggestions.

See library.py for each detector, its parameters and defaults, the freshness and minimum-history rules, and the rank formulas;
wording.py for every headline; verify.py for the independent check each suggestion passes before it is returned. Nothing here
reads a database, a file or the network, and nothing here is registered in the real registry.
"""

from cytonn_weekly.notable.detectors.library import (
    drift,
    expected_range,
    pace,
    since,
    streak,
    threshold_cross,
    trailing_compare,
)
from cytonn_weekly.notable.detectors.series import Provenance, Series, SeriesError
from cytonn_weekly.notable.detectors.verify import DetectorSelfCheckError

__all__ = ["DetectorSelfCheckError", "Provenance", "Series", "SeriesError", "drift", "expected_range", "pace", "since", "streak",
           "threshold_cross", "trailing_compare"]
