# Runs the tests or the evals in a clean, reproducible environment.
#
#   docker build -t nl2sql-evals .
#   docker run --rm nl2sql-evals                                   # unit tests (no key needed)
#   docker run --rm -e ANTHROPIC_API_KEY -v "$PWD/results:/app/results" \
#       nl2sql-evals evals.run_eval                                # real eval run
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# Dependencies first, so code changes don't invalidate this cached layer.
COPY requirements.txt .
RUN pip install -r requirements.txt

COPY . .

# Arguments after the image name are a module to run with `python -m`.
ENTRYPOINT ["python", "-m"]
CMD ["pytest", "-q"]
