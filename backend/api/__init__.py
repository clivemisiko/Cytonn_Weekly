"""HTTP layer over the Digital Payments analyst review (replaces the Streamlit screen).

A thin wrapper around cytonn_weekly.review.store, review_run and
review.model.  It holds no review logic of its own; see api/main.py for the
endpoints and api/serialize.py for the JSON shape the web app consumes.
"""
