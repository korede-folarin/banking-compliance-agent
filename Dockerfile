# Banking Compliance Agent: the review screen and monitoring dashboard (Streamlit).
# Serves the saved evaluation results in docs/; makes no model calls, so it needs no API key.
#
#   docker build -t compliance-review .
#   docker run --rm -p 127.0.0.1:8510:8501 -v "${PWD}/reviews:/app/reviews" -v "${PWD}/logs:/app/logs" compliance-review
#
# Then open http://localhost:8510. reviews/ (decisions) and logs/ (audit log) are mounted so they
# outlive the container; without the mounts they are lost when it stops.

FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    HF_HUB_OFFLINE=1

WORKDIR /app

# CPU-only PyTorch first: the default Linux wheel bundles CUDA and adds gigabytes the app never uses.
RUN pip install --index-url https://download.pytorch.org/whl/cpu torch
COPY requirements.txt .
RUN pip install -r requirements.txt

COPY .streamlit/ .streamlit/
COPY src/ src/
COPY tests/fixtures/ tests/fixtures/
COPY data/synthetic_docs/ data/synthetic_docs/
COPY data/fixtures_v2/ data/fixtures_v2/
COPY docs/ docs/

# Run as a non-root user; reviews/ and logs/ are the only places the app writes.
RUN useradd --create-home app && mkdir -p reviews logs && chown -R app:app /app
USER app

EXPOSE 8501
HEALTHCHECK --interval=30s --timeout=5s --start-period=30s \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8501/_stcore/health')"

CMD ["streamlit", "run", "src/app.py", "--server.address=0.0.0.0", "--server.port=8501", "--server.headless=true"]
