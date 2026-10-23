# The review API (FastAPI). Build context: backend/.
# 3.12 is the version the project is developed on (pyproject asks for >=3.11, which matplotlib 3.11.2 needs).
FROM python:3.12-slim AS runtime

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    CYTONN_DATA_DIR=/app/data

WORKDIR /app

# The one pair of system packages: OpenCV (pulled in by rapidocr-onnxruntime, which reads the scanned
# NSE daily price list) loads libGL and GLib even though nothing is ever displayed.
RUN apt-get update \
    && apt-get install -y --no-install-recommends libgl1 libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

# Dependencies first, from pyproject alone, so this layer is rebuilt only when it changes.
# The package is installed editable against an empty stub; the real source is copied below.
# Every Python dependency installs from a wheel on this image (the OCR models are inside their wheel; psycopg[binary]
# bundles libpq). The playwright package is a pinned dependency but nothing imports it: no browsers are installed.
COPY pyproject.toml ./
RUN mkdir -p src/cytonn_weekly \
    && touch src/cytonn_weekly/__init__.py \
    && pip install --no-cache-dir -e .

COPY src ./src
COPY api ./api
COPY scripts ./scripts

# Fixed UID, no root, with a home folder so matplotlib's font cache (~/.cache/matplotlib) is writable. /app/data is
# where docker-compose.yml bind-mounts backend/data.
RUN useradd --uid 10001 --create-home --shell /usr/sbin/nologin cytonn \
    && mkdir -p /app/data \
    && chown cytonn:cytonn /app/data
USER cytonn

EXPOSE 8000

HEALTHCHECK --interval=15s --timeout=5s --retries=5 --start-period=20s \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/health', timeout=4)"]

CMD ["uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8000"]

# The test suite, kept out of the runtime image: docker compose build does not build this stage (compose names target:
# runtime). Build and run it on its own, never with env_file or the data mount:
#   docker build --target test -t cytonn-api-test backend && docker run --rm --network none cytonn-api-test
FROM runtime AS test
USER root
RUN pip install --no-cache-dir -e ".[test]"
COPY tests ./tests
USER cytonn
ENV PYTEST_ADDOPTS="-p no:cacheprovider"
CMD ["python", "-m", "pytest", "-q", "--tb=line", "--deselect", "tests/test_postgres_smoke.py"]
