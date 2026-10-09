"""The weekly report's own inputs: the files a coordinator uploads each Friday, and their parsers.

Nothing here drafts anything.  Each module reads one kind of input (a KCB IB trading report,
the CBK Weekly Bulletin, the NSE daily price list, the NSE yield curve, Cytonn's equities and
fixed income workbooks, the previous issue on cytonnreport.com) and returns plain values with
where each one was read from.  The section builders (fixed_income/weekly.py,
equities/weekly.py) turn those into the report's paragraphs and tables.
"""
