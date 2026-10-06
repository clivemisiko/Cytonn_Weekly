"""HTTP layer over the Digital Payments coordinator review (replaces the Streamlit screen).

A thin wrapper around cytonn_weekly.digital_payments.review_store, review_run and
coordinator_review.  It holds no review logic of its own; see api/main.py for the
endpoints and api/serialize.py for the JSON shape the web app consumes.
"""
