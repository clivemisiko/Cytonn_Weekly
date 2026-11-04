GREEN = "#006C5B"   # Word takes these without the "#"
YELLOW = "#FFFF00"
RED = "#FF0000"
BLACK = "#000000"
WHITE = "#FFFFFF"

# Charts
CHART_LINE, CHART_LINE_PT = GREEN, 2.25
AVERAGE_LINE, AVERAGE_LINE_PT = RED, 1.5
CHART_TEXT = BLACK
CHART_AXIS_LINE = "#5B6B7A"   # the axis lines and tick marks as before: the published colour is not confirmed
CHART_FONTS = ("Calibri", "Carlito")   # Carlito has Calibri's metrics; neither is a dependency
CHART_TEXT_PT = 9
CHART_TITLE_PT = 11
CHART_TITLE_PREFIX = "Cytonn Report: "
# For charts not built yet.
BAR, BAR_CYTONN = GREEN, YELLOW
TBILL_LINES = {"91-day": GREEN, "182-day": YELLOW, "364-day": RED}
LEGEND_LOC = "lower center"

# Word tables, as the table cells of cytonnreport.com issues 862 to 892 print them (checked 2026-11-04)
TABLE_FONT = "Calibri"
HEADER_FILL, HEADER_TEXT = GREEN, WHITE
BODY_FILL, BODY_TEXT = WHITE, BLACK
SUMMARY_FILL, SUMMARY_TEXT = YELLOW, BLACK
SUMMARY_ROWS = ("Average", "Total")
CHANGE_ROWS = ("Weekly Change", "MTD Change", "YTD Change")
CHANGE_TEXT = RED                      # the published Eurobond change rows: yellow, with red text
CYTONN_ROW_PREFIX = "Cytonn"           # Cytonn's own row (its fund in the money market table)
RECOMMENDATION_FILLS = {"Buy": "#00FF00", "Accumulate": "#ED7D31", "Hold": "#A6A6A6", "Lighten": "#0070C0", "Sell": RED}
RECOMMENDATION_TEXT = BLACK
RATING_FILL = "#F5F5F5"
RATING_COLUMNS = ("rating", "outlook")   # a column whose header holds one of these words
BORDER, BORDER_EIGHTHS_PT = BLACK, 4     # thin single lines (0.5 pt)
