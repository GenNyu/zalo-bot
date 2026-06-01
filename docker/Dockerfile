FROM python:3.11-slim
WORKDIR /app
ENV PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
COPY pyproject.toml ./
COPY src ./src
RUN pip install --upgrade pip && pip install -e .
# Default command runs the web server; compose overrides for the worker.
# Factory form: web.py exposes create_app(), not a module-level `app`.
CMD ["uvicorn", "zalo_bot.entrypoints.web:create_app", "--factory", "--host", "0.0.0.0", "--port", "3000"]
