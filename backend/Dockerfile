# The review API (FastAPI). Build context: backend/.
# 3.12 is the version the project is developed on (pyproject asks for >=3.10).
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    CYTONN_DATA_DIR=/app/data \
    PYTEST_ADDOPTS="-p no:cacheprovider"

WORKDIR /app

# The one pair of system packages: OpenCV (pulled in by rapidocr-onnxruntime, which reads the scanned
# NSE daily price list) loads libGL and GLib even though nothing is ever displayed.
RUN apt-get update \
    && apt-get install -y --no-install-recommends libgl1 libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

# Dependencies first, from pyproject alone, so this layer is rebuilt only when it changes.
# The package is installed editable against an empty stub; the real source is copied below.
# Every Python dependency installs from a wheel on this image (the OCR models are inside their wheel).
# The playwright package is a pinned dependency but nothing imports it: no browsers are installed.
COPY pyproject.toml ./
RUN mkdir -p src/cytonn_weekly \
    && touch src/cytonn_weekly/__init__.py \
    && pip install --no-cache-dir -e ".[test]"

COPY src ./src
COPY api ./api
COPY scripts ./scripts
COPY tests ./tests

# Fixed UID, no root. /app/data is where the cytonn_data volume is mounted; a new volume
# takes this folder's owner, so the app can write its database there.
RUN useradd --uid 10001 --create-home --shell /usr/sbin/nologin cytonn \
    && mkdir -p /app/data \
    && chown cytonn:cytonn /app/data
USER cytonn

EXPOSE 8000

HEALTHCHECK --interval=15s --timeout=5s --retries=5 --start-period=20s \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/health', timeout=4)"]

CMD ["uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8000"]
