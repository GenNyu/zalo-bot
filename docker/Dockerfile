FROM python:3.11-slim
WORKDIR /app
ENV PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
COPY pyproject.toml ./
COPY src ./src
RUN pip install --upgrade pip && pip install -e .
# Default command runs the web server; compose overrides for the worker.
CMD ["uvicorn", "zalo_bot.entrypoints.web:app", "--host", "0.0.0.0", "--port", "3000"]
