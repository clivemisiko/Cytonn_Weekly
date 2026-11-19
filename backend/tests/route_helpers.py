def every_route(app):
    """Every route of the app, those of included routers (FastAPI's _IncludedRouter has no path) flattened in."""
    def walk(routes):
        for r in routes:
            inner = getattr(r, "original_router", None)
            yield from walk(inner.routes) if inner is not None else [r]

    return list(walk(app.routes))
