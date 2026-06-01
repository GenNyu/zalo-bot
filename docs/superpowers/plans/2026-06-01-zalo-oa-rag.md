# Zalo OA RAG Service Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a Python service that receives questions from Zalo OA via webhook, retrieves context from OpenSearch (hybrid search over Open WebUI indices), composes an answer with an internal LLM gateway, and replies via the Zalo OA Open API.

**Architecture:** Modular monolith with two entrypoints sharing one codebase/image — a FastAPI `web` process (verify signature, ack 200, enqueue) and an arq `worker` process (embed → hybrid search → LLM → send reply). Redis backs both the arq queue and the Zalo access-token cache. Stateless per question.

**Tech Stack:** Python 3.11+, FastAPI, arq (Redis), opensearch-py (AsyncOpenSearch), openai SDK (pointed at internal gateway), httpx, pydantic-settings, structlog, pytest + pytest-asyncio + respx + testcontainers.

---

## File Structure

```
zalo-bot/
├── pyproject.toml                      # deps + tooling (ruff, mypy, pytest)
├── .env.example                        # documented env vars
├── docker/
│   ├── Dockerfile                      # single image, two commands
│   └── docker-compose.yml              # web + worker + redis
├── src/zalo_bot/
│   ├── __init__.py
│   ├── config/
│   │   ├── __init__.py
│   │   └── settings.py                 # pydantic-settings Settings
│   ├── lib/
│   │   ├── __init__.py
│   │   ├── logging.py                  # structlog setup + correlation_id
│   │   └── errors.py                   # typed exceptions
│   ├── modules/
│   │   ├── __init__.py
│   │   ├── zalo/
│   │   │   ├── __init__.py
│   │   │   ├── signature.py            # verify_signature
│   │   │   ├── events.py               # ZaloEvent, parse_event
│   │   │   ├── token.py                # get_access_token (Redis cache + lock)
│   │   │   └── client.py               # send_text_message
│   │   ├── llm_gateway/
│   │   │   ├── __init__.py
│   │   │   └── client.py               # embed, chat
│   │   ├── opensearch/
│   │   │   ├── __init__.py
│   │   │   └── search.py               # SearchHit, hybrid_search, build_query
│   │   └── rag/
│   │       ├── __init__.py
│   │       ├── prompt.py               # build_prompt
│   │       └── orchestrator.py         # answer_question
│   ├── queue/
│   │   ├── __init__.py
│   │   └── jobs.py                     # AnswerJob, enqueue_answer_job, process_answer_job
│   └── entrypoints/
│       ├── __init__.py
│       ├── web.py                      # FastAPI app: /webhook/zalo, /health
│       └── worker.py                   # arq WorkerSettings
└── tests/
    ├── __init__.py
    ├── conftest.py
    ├── modules/
    │   ├── zalo/{test_signature.py,test_events.py,test_token.py,test_client.py}
    │   ├── llm_gateway/test_client.py
    │   ├── opensearch/test_search.py
    │   └── rag/{test_prompt.py,test_orchestrator.py}
    ├── queue/test_jobs.py
    └── entrypoints/test_web.py
```

---

## Task 0: Local environment & live verification (MANUAL — do first)

Stand up a local OpenSearch in Docker to develop/test against, expose the local web server to Zalo OA over an HTTPS tunnel, and confirm the assumptions baked into the code below. If a verification result differs, update the noted task before coding it.

**Local test flow:**
```
Zalo OA
  → HTTPS public URL (ngrok / cloudflared)
  → localhost:3000
  → POST /webhook/zalo
  → verify signature → log body → enqueue → worker handles event
```

### Part A — Local OpenSearch (Docker)

- [ ] **Step 1: Start single-node OpenSearch with kNN enabled**

Run:
```bash
docker run -d --name os-dev -p 9200:9200 \
  -e discovery.type=single-node \
  -e plugins.security.disabled=true \
  -e OPENSEARCH_INITIAL_ADMIN_PASSWORD=Dev_passw0rd! \
  opensearchproject/opensearch:2.13.0
```
Then verify (wait ~20s for boot):
```bash
curl -s http://localhost:9200 | python -m json.tool
```
Expected: cluster info JSON. Use `OPENSEARCH_URL=http://localhost:9200`, leave `OPENSEARCH_USER`/`OPENSEARCH_PASSWORD` blank (security disabled in dev).

- [ ] **Step 2: Create the hybrid search pipeline (score normalization)**

Run:
```bash
curl -s -X PUT http://localhost:9200/_search/pipeline/hybrid-pipeline \
  -H 'Content-Type: application/json' -d '{
  "phase_results_processors": [
    { "normalization-processor": {
        "normalization": { "technique": "min_max" },
        "combination": { "technique": "arithmetic_mean", "parameters": { "weights": [0.4, 0.6] } }
    }}
  ]
}'
```
Expected: `{"acknowledged":true}`. Set `OPENSEARCH_SEARCH_PIPELINE=hybrid-pipeline`.

- [ ] **Step 3: Create a sample index mirroring the Open WebUI layout + seed a doc**

`dimension` MUST equal your embedding model's size from Step 7 (example uses 1024 — adjust).
```bash
curl -s -X PUT http://localhost:9200/open_webui_file-sample \
  -H 'Content-Type: application/json' -d '{
  "settings": { "index.knn": true },
  "mappings": { "properties": {
    "text":     { "type": "text" },
    "vector":   { "type": "knn_vector", "dimension": 1024 },
    "metadata": { "type": "object" }
  }}
}'
```
Seed one doc (use a real embedding of the text, or zeros for a shape-only test):
```bash
curl -s -X POST http://localhost:9200/open_webui_file-sample/_doc \
  -H 'Content-Type: application/json' -d '{
  "text": "UrBox là nền tảng quà tặng điện tử.",
  "vector": [/* 1024 floats */],
  "metadata": {}
}'
```
Expected: doc indexed. `open_webui_file-*` now resolves locally for end-to-end testing.

### Part B — HTTPS tunnel to Zalo OA

- [ ] **Step 4: Expose the local web server (:3000) over HTTPS**

ngrok:
```bash
ngrok http 3000
```
or cloudflared:
```bash
cloudflared tunnel --url http://localhost:3000
```
Copy the public HTTPS URL it prints.

- [ ] **Step 5: Register the webhook in the Zalo OA dashboard**

Set the webhook URL to `https://<public-url>/webhook/zalo` and subscribe to the `user_send_text` event. Keep the tunnel process running for the whole test session (the URL changes each restart on the free tier).

### Part C — Verify assumptions against the REAL cluster (the one holding Open WebUI data)

- [ ] **Step 6: Inspect a real Open WebUI index mapping**

```bash
curl -s "$OPENSEARCH_URL/open_webui_file-<id>/_mapping" | python -m json.tool
```
**Record** the BM25 text field (assumed `text`), the knn vector field (assumed `vector`), and its `dimension`. If names differ, update `OPENSEARCH_TEXT_FIELD` / `OPENSEARCH_VECTOR_FIELD` defaults in Task 2 and the query in Task 9.

- [ ] **Step 7: Confirm embedding model + dimension on the gateway**

```bash
curl -s "$LLM_GATEWAY_BASE_URL/embeddings" \
  -H "Authorization: Bearer $LLM_GATEWAY_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"model":"<embedding-model>","input":"ping"}' \
  | python -c "import sys,json;print(len(json.load(sys.stdin)['data'][0]['embedding']))"
```
Expected: an integer equal to the index vector `dimension` from Step 6 (and used in Step 3). They MUST match.

- [ ] **Step 8: Confirm the real cluster's search pipeline**

```bash
curl -s "$OPENSEARCH_URL/_search/pipeline" | python -m json.tool
```
**Record** the production pipeline name → `OPENSEARCH_SEARCH_PIPELINE` for the real environment. If none exists, the hybrid query still runs but scores are not normalized.

- [ ] **Step 9: Record the Zalo signature formula**

Confirm against current Zalo OA docs the exact MAC formula and header. This plan implements `mac = SHA256(appId + rawBody + timeStamp + OASecretKey)` with header `X-ZEvent-Signature: mac=<hex>` (Task 4). If the current API differs, adjust Task 4 only.

No commit (setup + read-only investigation).

---

## Task 1: Project scaffolding & tooling

**Files:**
- Create: `pyproject.toml`, `.env.example`, `src/zalo_bot/__init__.py`, `tests/__init__.py`, `tests/conftest.py`

- [ ] **Step 1: Write `pyproject.toml`**

```toml
[project]
name = "zalo-bot"
version = "0.1.0"
requires-python = ">=3.11"
dependencies = [
    "fastapi>=0.111",
    "uvicorn[standard]>=0.30",
    "arq>=0.26",
    "redis>=5.0",
    "opensearch-py>=2.6",
    "openai>=1.40",
    "httpx>=0.27",
    "pydantic>=2.7",
    "pydantic-settings>=2.3",
    "structlog>=24.1",
]

[project.optional-dependencies]
dev = [
    "pytest>=8.2",
    "pytest-asyncio>=0.23",
    "respx>=0.21",
    "testcontainers>=4.5",
    "ruff>=0.5",
    "mypy>=1.10",
]

[tool.pytest.ini_options]
asyncio_mode = "auto"
pythonpath = ["src"]
testpaths = ["tests"]

[tool.ruff]
line-length = 100
target-version = "py311"

[tool.mypy]
python_version = "3.11"
packages = ["zalo_bot"]
mypy_path = "src"
ignore_missing_imports = true

[build-system]
requires = ["setuptools>=68"]
build-backend = "setuptools.build_meta"

[tool.setuptools.packages.find]
where = ["src"]
```

- [ ] **Step 2: Write `.env.example`**

```dotenv
# Zalo OA
ZALO_OA_SECRET=changeme
ZALO_APP_ID=changeme
ZALO_REFRESH_TOKEN=changeme
ZALO_APP_SECRET=changeme
ZALO_SEND_API_URL=https://openapi.zalo.me/v3.0/oa/message
ZALO_TOKEN_API_URL=https://oauth.zaloapp.com/v4/oa/access_token

# Redis
REDIS_URL=redis://localhost:6379/0

# OpenSearch
OPENSEARCH_URL=http://localhost:9200
OPENSEARCH_USER=
OPENSEARCH_PASSWORD=
OPENSEARCH_INDEX_PATTERN=open_webui_file-*
OPENSEARCH_SEARCH_PIPELINE=
OPENSEARCH_TEXT_FIELD=text
OPENSEARCH_VECTOR_FIELD=vector
OPENSEARCH_TOP_K=5
OPENSEARCH_MIN_SCORE=0.0

# LLM gateway (OpenAI-compatible)
LLM_GATEWAY_BASE_URL=http://localhost:8001/v1
LLM_GATEWAY_API_KEY=changeme
LLM_EMBEDDING_MODEL=changeme
LLM_CHAT_MODEL=changeme

# Behavior
RAG_MAX_CONTEXT_CHARS=6000
EXTERNAL_CALL_TIMEOUT_SECONDS=30
LOG_LEVEL=INFO
LOG_QUESTION_TEXT=false
```

- [ ] **Step 3: Write empty package markers + `tests/conftest.py`**

`src/zalo_bot/__init__.py`: empty.
`tests/__init__.py`: empty.
`tests/conftest.py`:
```python
import os
import pytest

# Provide deterministic env so config.Settings loads in unit tests.
_TEST_ENV = {
    "ZALO_OA_SECRET": "secret",
    "ZALO_APP_ID": "appid",
    "ZALO_REFRESH_TOKEN": "refresh",
    "ZALO_APP_SECRET": "appsecret",
    "REDIS_URL": "redis://localhost:6379/0",
    "OPENSEARCH_URL": "http://localhost:9200",
    "OPENSEARCH_INDEX_PATTERN": "open_webui_file-*",
    "OPENSEARCH_TEXT_FIELD": "text",
    "OPENSEARCH_VECTOR_FIELD": "vector",
    "LLM_GATEWAY_BASE_URL": "http://gateway.local/v1",
    "LLM_GATEWAY_API_KEY": "key",
    "LLM_EMBEDDING_MODEL": "embed-model",
    "LLM_CHAT_MODEL": "chat-model",
}


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    for k, v in _TEST_ENV.items():
        monkeypatch.setenv(k, v)
```

- [ ] **Step 4: Install deps**

Run:
```bash
python -m venv .venv && . .venv/bin/activate && pip install -e ".[dev]"
```
Expected: install succeeds.

- [ ] **Step 5: Commit**

```bash
git add pyproject.toml .env.example src/zalo_bot/__init__.py tests/__init__.py tests/conftest.py
git commit -m "chore: scaffold project, deps, and tooling"
```

---

## Task 2: Config module

**Files:**
- Create: `src/zalo_bot/config/__init__.py`, `src/zalo_bot/config/settings.py`
- Test: `tests/modules/__init__.py` (empty), `tests/test_config.py`

- [ ] **Step 1: Write the failing test**

`tests/test_config.py`:
```python
from zalo_bot.config.settings import get_settings


def test_settings_load_from_env():
    s = get_settings()
    assert s.opensearch_index_pattern == "open_webui_file-*"
    assert s.opensearch_top_k == 5
    assert s.llm_embedding_model == "embed-model"
    assert s.external_call_timeout_seconds == 30
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_config.py -v`
Expected: FAIL with `ModuleNotFoundError: zalo_bot.config.settings`.

- [ ] **Step 3: Write implementation**

`src/zalo_bot/config/__init__.py`: empty.
`src/zalo_bot/config/settings.py`:
```python
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    zalo_oa_secret: str
    zalo_app_id: str
    zalo_refresh_token: str
    zalo_app_secret: str
    zalo_send_api_url: str = "https://openapi.zalo.me/v3.0/oa/message"
    zalo_token_api_url: str = "https://oauth.zaloapp.com/v4/oa/access_token"

    redis_url: str = "redis://localhost:6379/0"

    opensearch_url: str
    opensearch_user: str = ""
    opensearch_password: str = ""
    opensearch_index_pattern: str = "open_webui_file-*"
    opensearch_search_pipeline: str = ""
    opensearch_text_field: str = "text"
    opensearch_vector_field: str = "vector"
    opensearch_top_k: int = 5
    opensearch_min_score: float = 0.0

    llm_gateway_base_url: str
    llm_gateway_api_key: str
    llm_embedding_model: str
    llm_chat_model: str

    rag_max_context_chars: int = 6000
    external_call_timeout_seconds: int = 30
    log_level: str = "INFO"
    log_question_text: bool = False


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_config.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/zalo_bot/config tests/test_config.py tests/modules/__init__.py
git commit -m "feat(config): typed settings from environment"
```

---

## Task 3: Lib — errors & logging

**Files:**
- Create: `src/zalo_bot/lib/__init__.py`, `src/zalo_bot/lib/errors.py`, `src/zalo_bot/lib/logging.py`
- Test: `tests/test_lib.py`

- [ ] **Step 1: Write the failing test**

`tests/test_lib.py`:
```python
from zalo_bot.lib.errors import ExternalServiceError, SignatureError
from zalo_bot.lib.logging import configure_logging, get_logger


def test_errors_are_exceptions():
    assert issubclass(ExternalServiceError, Exception)
    assert issubclass(SignatureError, Exception)


def test_logger_binds_correlation_id():
    configure_logging("INFO")
    log = get_logger("test").bind(correlation_id="abc")
    # bound value is retrievable from the context
    assert log._context.get("correlation_id") == "abc"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_lib.py -v`
Expected: FAIL with `ModuleNotFoundError: zalo_bot.lib.errors`.

- [ ] **Step 3: Write implementation**

`src/zalo_bot/lib/__init__.py`: empty.
`src/zalo_bot/lib/errors.py`:
```python
class AppError(Exception):
    """Base for application errors."""


class SignatureError(AppError):
    """Webhook signature verification failed."""


class ExternalServiceError(AppError):
    """An upstream call (gateway, OpenSearch, Zalo) failed."""
```

`src/zalo_bot/lib/logging.py`:
```python
import logging

import structlog


def configure_logging(level: str = "INFO") -> None:
    logging.basicConfig(format="%(message)s", level=getattr(logging, level.upper(), logging.INFO))
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(
            getattr(logging, level.upper(), logging.INFO)
        ),
        cache_logger_on_first_use=True,
    )


def get_logger(name: str) -> structlog.stdlib.BoundLogger:
    return structlog.get_logger(name)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_lib.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/zalo_bot/lib tests/test_lib.py
git commit -m "feat(lib): typed errors and structlog setup"
```

---

## Task 4: Zalo signature verification

**Files:**
- Create: `src/zalo_bot/modules/__init__.py`, `src/zalo_bot/modules/zalo/__init__.py`, `src/zalo_bot/modules/zalo/signature.py`
- Test: `tests/modules/zalo/__init__.py` (empty), `tests/modules/zalo/test_signature.py`

> Formula (confirm in Task 0 Step 4): `mac = SHA256(app_id + raw_body + timestamp + oa_secret)`, compared constant-time against the hex in header `X-ZEvent-Signature: mac=<hex>`.

- [ ] **Step 1: Write the failing test**

`tests/modules/zalo/test_signature.py`:
```python
import hashlib

from zalo_bot.modules.zalo.signature import verify_signature


def _mac(app_id, body, ts, secret):
    return hashlib.sha256((app_id + body.decode() + ts + secret).encode()).hexdigest()


def test_valid_signature_passes():
    body = b'{"event_name":"user_send_text"}'
    mac = _mac("appid", body, "1700000000000", "secret")
    assert verify_signature(
        raw_body=body, header=f"mac={mac}",
        app_id="appid", timestamp="1700000000000", oa_secret="secret",
    )


def test_tampered_body_fails():
    body = b'{"event_name":"user_send_text"}'
    mac = _mac("appid", body, "1700000000000", "secret")
    assert not verify_signature(
        raw_body=b'{"event_name":"hacked"}', header=f"mac={mac}",
        app_id="appid", timestamp="1700000000000", oa_secret="secret",
    )


def test_missing_or_malformed_header_fails():
    assert not verify_signature(
        raw_body=b"{}", header="", app_id="a", timestamp="1", oa_secret="s"
    )
    assert not verify_signature(
        raw_body=b"{}", header="garbage", app_id="a", timestamp="1", oa_secret="s"
    )
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/modules/zalo/test_signature.py -v`
Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 3: Write implementation**

`src/zalo_bot/modules/__init__.py`: empty.
`src/zalo_bot/modules/zalo/__init__.py`: empty.
`src/zalo_bot/modules/zalo/signature.py`:
```python
import hashlib
import hmac


def verify_signature(
    *, raw_body: bytes, header: str, app_id: str, timestamp: str, oa_secret: str
) -> bool:
    if not header or not header.startswith("mac="):
        return False
    provided = header[len("mac=") :]
    payload = (app_id + raw_body.decode("utf-8") + timestamp + oa_secret).encode("utf-8")
    expected = hashlib.sha256(payload).hexdigest()
    return hmac.compare_digest(provided, expected)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/modules/zalo/test_signature.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/zalo_bot/modules/__init__.py src/zalo_bot/modules/zalo/__init__.py src/zalo_bot/modules/zalo/signature.py tests/modules/zalo/__init__.py tests/modules/zalo/test_signature.py
git commit -m "feat(zalo): webhook signature verification"
```

---

## Task 5: Zalo event parsing

**Files:**
- Create: `src/zalo_bot/modules/zalo/events.py`
- Test: `tests/modules/zalo/test_events.py`

- [ ] **Step 1: Write the failing test**

`tests/modules/zalo/test_events.py`:
```python
from zalo_bot.modules.zalo.events import parse_event


def test_parse_user_send_text():
    body = {
        "event_name": "user_send_text",
        "sender": {"id": "u1"},
        "message": {"msg_id": "m1", "text": "xin chào"},
        "timestamp": "1700000000000",
    }
    ev = parse_event(body)
    assert ev.event_name == "user_send_text"
    assert ev.user_id == "u1"
    assert ev.msg_id == "m1"
    assert ev.text == "xin chào"
    assert ev.is_text_question is True


def test_parse_non_text_event():
    body = {
        "event_name": "user_send_image",
        "sender": {"id": "u2"},
        "message": {"msg_id": "m2"},
        "timestamp": "1700000000001",
    }
    ev = parse_event(body)
    assert ev.is_text_question is False
    assert ev.text == ""
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/modules/zalo/test_events.py -v`
Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 3: Write implementation**

`src/zalo_bot/modules/zalo/events.py`:
```python
from dataclasses import dataclass


@dataclass(frozen=True)
class ZaloEvent:
    event_name: str
    user_id: str
    msg_id: str
    text: str
    timestamp: str

    @property
    def is_text_question(self) -> bool:
        return self.event_name == "user_send_text" and bool(self.text.strip())


def parse_event(body: dict) -> ZaloEvent:
    message = body.get("message") or {}
    sender = body.get("sender") or {}
    return ZaloEvent(
        event_name=str(body.get("event_name", "")),
        user_id=str(sender.get("id", "")),
        msg_id=str(message.get("msg_id", "")),
        text=str(message.get("text", "") or ""),
        timestamp=str(body.get("timestamp", "")),
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/modules/zalo/test_events.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/zalo_bot/modules/zalo/events.py tests/modules/zalo/test_events.py
git commit -m "feat(zalo): event parsing"
```

---

## Task 6: Zalo access-token cache + refresh

**Files:**
- Create: `src/zalo_bot/modules/zalo/token.py`
- Test: `tests/modules/zalo/test_token.py`

> Caches token in Redis with TTL. Refreshes via the Zalo OAuth endpoint when missing/expiring, guarded by a Redis lock to avoid concurrent refresh.

- [ ] **Step 1: Write the failing test**

`tests/modules/zalo/test_token.py`:
```python
import json

import httpx
import pytest
import respx

from zalo_bot.modules.zalo.token import TokenManager


class FakeRedis:
    def __init__(self):
        self.store = {}

    async def get(self, key):
        return self.store.get(key)

    async def set(self, key, value, ex=None):
        self.store[key] = value

    def lock(self, *_a, **_k):
        class _L:
            async def __aenter__(self_):
                return self_
            async def __aexit__(self_, *exc):
                return False
        return _L()


@pytest.mark.asyncio
@respx.mock
async def test_returns_cached_token_without_refresh():
    redis = FakeRedis()
    redis.store["zalo:access_token"] = "cached-token"
    tm = TokenManager(
        redis=redis, token_url="https://oauth.local/token",
        app_id="app", app_secret="sec", refresh_token="ref",
    )
    assert await tm.get_access_token() == "cached-token"


@pytest.mark.asyncio
@respx.mock
async def test_refreshes_when_missing():
    redis = FakeRedis()
    route = respx.post("https://oauth.local/token").mock(
        return_value=httpx.Response(
            200, json={"access_token": "new-token", "refresh_token": "r2", "expires_in": "90000"}
        )
    )
    tm = TokenManager(
        redis=redis, token_url="https://oauth.local/token",
        app_id="app", app_secret="sec", refresh_token="ref",
    )
    token = await tm.get_access_token()
    assert token == "new-token"
    assert route.called
    assert redis.store["zalo:access_token"] == "new-token"


@pytest.mark.asyncio
@respx.mock
async def test_force_refresh_ignores_cache():
    redis = FakeRedis()
    redis.store["zalo:access_token"] = "old"
    respx.post("https://oauth.local/token").mock(
        return_value=httpx.Response(
            200, json={"access_token": "fresh", "refresh_token": "r2", "expires_in": "90000"}
        )
    )
    tm = TokenManager(
        redis=redis, token_url="https://oauth.local/token",
        app_id="app", app_secret="sec", refresh_token="ref",
    )
    assert await tm.get_access_token(force_refresh=True) == "fresh"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/modules/zalo/test_token.py -v`
Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 3: Write implementation**

`src/zalo_bot/modules/zalo/token.py`:
```python
from typing import Any

import httpx

_TOKEN_KEY = "zalo:access_token"
_REFRESH_KEY = "zalo:refresh_token"
_LOCK_KEY = "zalo:token:lock"
# Refresh a bit before the ~25h expiry; subtract a 1h safety margin from expires_in.
_SAFETY_MARGIN_SECONDS = 3600


class TokenManager:
    def __init__(
        self, *, redis: Any, token_url: str, app_id: str, app_secret: str, refresh_token: str
    ) -> None:
        self._redis = redis
        self._token_url = token_url
        self._app_id = app_id
        self._app_secret = app_secret
        self._fallback_refresh_token = refresh_token

    async def get_access_token(self, *, force_refresh: bool = False) -> str:
        if not force_refresh:
            cached = await self._redis.get(_TOKEN_KEY)
            if cached:
                return cached.decode() if isinstance(cached, bytes) else cached
        return await self._refresh()

    async def _refresh(self) -> str:
        async with self._redis.lock(_LOCK_KEY, timeout=30):
            cached = await self._redis.get(_TOKEN_KEY)
            if cached:
                return cached.decode() if isinstance(cached, bytes) else cached
            stored_refresh = await self._redis.get(_REFRESH_KEY)
            refresh_token = (
                stored_refresh.decode() if isinstance(stored_refresh, bytes) else stored_refresh
            ) or self._fallback_refresh_token

            async with httpx.AsyncClient(timeout=30) as client:
                resp = await client.post(
                    self._token_url,
                    headers={"secret_key": self._app_secret},
                    data={
                        "app_id": self._app_id,
                        "grant_type": "refresh_token",
                        "refresh_token": refresh_token,
                    },
                )
                resp.raise_for_status()
                payload = resp.json()

            access_token = payload["access_token"]
            ttl = max(int(payload.get("expires_in", "90000")) - _SAFETY_MARGIN_SECONDS, 60)
            await self._redis.set(_TOKEN_KEY, access_token, ex=ttl)
            if payload.get("refresh_token"):
                await self._redis.set(_REFRESH_KEY, payload["refresh_token"])
            return access_token
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/modules/zalo/test_token.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/zalo_bot/modules/zalo/token.py tests/modules/zalo/test_token.py
git commit -m "feat(zalo): access-token cache and refresh with redis lock"
```

---

## Task 7: Zalo send-message client

**Files:**
- Create: `src/zalo_bot/modules/zalo/client.py`
- Test: `tests/modules/zalo/test_client.py`

- [ ] **Step 1: Write the failing test**

`tests/modules/zalo/test_client.py`:
```python
import httpx
import pytest
import respx

from zalo_bot.modules.zalo.client import ZaloClient


class _Tokens:
    def __init__(self):
        self.calls = []

    async def get_access_token(self, *, force_refresh: bool = False):
        self.calls.append(force_refresh)
        return "tok-refreshed" if force_refresh else "tok"


@pytest.mark.asyncio
@respx.mock
async def test_send_text_ok():
    route = respx.post("https://send.local/msg").mock(
        return_value=httpx.Response(200, json={"error": 0, "message": "Success"})
    )
    client = ZaloClient(send_url="https://send.local/msg", tokens=_Tokens(), timeout=5)
    await client.send_text_message("u1", "hello")
    assert route.called
    sent = route.calls[0].request
    assert sent.headers["access_token"] == "tok"


@pytest.mark.asyncio
@respx.mock
async def test_send_text_refreshes_on_token_error():
    respx.post("https://send.local/msg").mock(
        side_effect=[
            httpx.Response(200, json={"error": -216, "message": "access token expired"}),
            httpx.Response(200, json={"error": 0, "message": "Success"}),
        ]
    )
    tokens = _Tokens()
    client = ZaloClient(send_url="https://send.local/msg", tokens=tokens, timeout=5)
    await client.send_text_message("u1", "hi")
    assert tokens.calls == [False, True]  # second attempt forced a refresh
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/modules/zalo/test_client.py -v`
Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 3: Write implementation**

`src/zalo_bot/modules/zalo/client.py`:
```python
from typing import Any, Protocol

import httpx

from zalo_bot.lib.errors import ExternalServiceError

_TOKEN_ERROR_CODES = {-216, -124}  # expired / invalid token


class TokenProvider(Protocol):
    async def get_access_token(self, *, force_refresh: bool = False) -> str: ...


class ZaloClient:
    def __init__(self, *, send_url: str, tokens: TokenProvider, timeout: int = 30) -> None:
        self._send_url = send_url
        self._tokens = tokens
        self._timeout = timeout

    async def send_text_message(self, user_id: str, text: str) -> None:
        if await self._post(user_id, text, force_refresh=False):
            return
        # One retry after a forced token refresh.
        if await self._post(user_id, text, force_refresh=True):
            return
        raise ExternalServiceError("zalo send failed after token refresh")

    async def _post(self, user_id: str, text: str, *, force_refresh: bool) -> bool:
        token = await self._tokens.get_access_token(force_refresh=force_refresh)
        body: dict[str, Any] = {
            "recipient": {"user_id": user_id},
            "message": {"text": text},
        }
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            resp = await client.post(self._send_url, headers={"access_token": token}, json=body)
            resp.raise_for_status()
            data = resp.json()
        return data.get("error", 0) not in _TOKEN_ERROR_CODES
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/modules/zalo/test_client.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/zalo_bot/modules/zalo/client.py tests/modules/zalo/test_client.py
git commit -m "feat(zalo): send-text client with token-refresh retry"
```

---

## Task 8: LLM gateway client (embed + chat)

**Files:**
- Create: `src/zalo_bot/modules/llm_gateway/__init__.py`, `src/zalo_bot/modules/llm_gateway/client.py`
- Test: `tests/modules/llm_gateway/__init__.py` (empty), `tests/modules/llm_gateway/test_client.py`

- [ ] **Step 1: Write the failing test**

`tests/modules/llm_gateway/test_client.py`:
```python
import httpx
import pytest
import respx

from zalo_bot.modules.llm_gateway.client import LlmGateway


@pytest.mark.asyncio
@respx.mock
async def test_embed_returns_vector():
    respx.post("http://gw.local/v1/embeddings").mock(
        return_value=httpx.Response(200, json={"data": [{"embedding": [0.1, 0.2, 0.3]}]})
    )
    gw = LlmGateway(
        base_url="http://gw.local/v1", api_key="k",
        embedding_model="e", chat_model="c", timeout=5,
    )
    assert await gw.embed("hello") == [0.1, 0.2, 0.3]


@pytest.mark.asyncio
@respx.mock
async def test_chat_returns_text():
    respx.post("http://gw.local/v1/chat/completions").mock(
        return_value=httpx.Response(
            200, json={"choices": [{"message": {"content": "câu trả lời"}}]}
        )
    )
    gw = LlmGateway(
        base_url="http://gw.local/v1", api_key="k",
        embedding_model="e", chat_model="c", timeout=5,
    )
    out = await gw.chat([{"role": "user", "content": "hi"}])
    assert out == "câu trả lời"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/modules/llm_gateway/test_client.py -v`
Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 3: Write implementation**

`src/zalo_bot/modules/llm_gateway/__init__.py`: empty.
`src/zalo_bot/modules/llm_gateway/client.py`:
```python
from openai import AsyncOpenAI


class LlmGateway:
    def __init__(
        self, *, base_url: str, api_key: str, embedding_model: str, chat_model: str,
        timeout: int = 30,
    ) -> None:
        self._client = AsyncOpenAI(
            base_url=base_url, api_key=api_key, timeout=timeout, max_retries=2
        )
        self._embedding_model = embedding_model
        self._chat_model = chat_model

    async def embed(self, text: str) -> list[float]:
        resp = await self._client.embeddings.create(model=self._embedding_model, input=text)
        return list(resp.data[0].embedding)

    async def chat(self, messages: list[dict], *, temperature: float = 0.2) -> str:
        resp = await self._client.chat.completions.create(
            model=self._chat_model, messages=messages, temperature=temperature
        )
        return (resp.choices[0].message.content or "").strip()
```

> Note: the `openai` SDK posts to `{base_url}/embeddings` and `{base_url}/chat/completions`. Tests mock those exact URLs; `max_retries=2` covers transient 5xx.

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/modules/llm_gateway/test_client.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/zalo_bot/modules/llm_gateway tests/modules/llm_gateway
git commit -m "feat(llm): gateway client for embeddings and chat"
```

---

## Task 9: OpenSearch hybrid search

**Files:**
- Create: `src/zalo_bot/modules/opensearch/__init__.py`, `src/zalo_bot/modules/opensearch/search.py`
- Test: `tests/modules/opensearch/__init__.py` (empty), `tests/modules/opensearch/test_search.py`

- [ ] **Step 1: Write the failing test**

`tests/modules/opensearch/test_search.py`:
```python
import pytest

from zalo_bot.modules.opensearch.search import OpenSearchRetriever, build_hybrid_query


def test_build_hybrid_query_shape():
    q = build_hybrid_query(
        query_text="hỏi gì đó", query_vector=[0.1, 0.2],
        top_k=3, text_field="text", vector_field="vector",
    )
    assert q["size"] == 3
    hybrid = q["query"]["hybrid"]["queries"]
    assert hybrid[0] == {"match": {"text": {"query": "hỏi gì đó"}}}
    assert hybrid[1] == {"knn": {"vector": {"vector": [0.1, 0.2], "k": 3}}}
    assert q["_source"] == ["text", "metadata"]


class _FakeClient:
    def __init__(self, hits):
        self._hits = hits
        self.last_call = None

    async def search(self, **kwargs):
        self.last_call = kwargs
        return {"hits": {"hits": self._hits}}


@pytest.mark.asyncio
async def test_hybrid_search_maps_hits_and_filters_min_score():
    fake = _FakeClient(
        [
            {"_id": "a", "_score": 0.9, "_source": {"text": "A", "metadata": {}}},
            {"_id": "b", "_score": 0.1, "_source": {"text": "B", "metadata": {}}},
        ]
    )
    retriever = OpenSearchRetriever(
        client=fake, index_pattern="open_webui_file-*", search_pipeline="hp",
        text_field="text", vector_field="vector", min_score=0.5,
    )
    hits = await retriever.hybrid_search("q", [0.1], top_k=5)
    assert [h.id for h in hits] == ["a"]  # b filtered out by min_score
    assert fake.last_call["index"] == "open_webui_file-*"
    assert fake.last_call["params"] == {"search_pipeline": "hp"}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/modules/opensearch/test_search.py -v`
Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 3: Write implementation**

`src/zalo_bot/modules/opensearch/__init__.py`: empty.
`src/zalo_bot/modules/opensearch/search.py`:
```python
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class SearchHit:
    id: str
    score: float
    source: dict[str, Any]


def build_hybrid_query(
    *, query_text: str, query_vector: list[float], top_k: int, text_field: str, vector_field: str
) -> dict[str, Any]:
    return {
        "size": top_k,
        "query": {
            "hybrid": {
                "queries": [
                    {"match": {text_field: {"query": query_text}}},
                    {"knn": {vector_field: {"vector": query_vector, "k": top_k}}},
                ]
            }
        },
        "_source": [text_field, "metadata"],
    }


class OpenSearchRetriever:
    def __init__(
        self, *, client: Any, index_pattern: str, search_pipeline: str,
        text_field: str, vector_field: str, min_score: float = 0.0,
    ) -> None:
        self._client = client
        self._index_pattern = index_pattern
        self._search_pipeline = search_pipeline
        self._text_field = text_field
        self._vector_field = vector_field
        self._min_score = min_score

    async def hybrid_search(
        self, query_text: str, query_vector: list[float], *, top_k: int
    ) -> list[SearchHit]:
        body = build_hybrid_query(
            query_text=query_text, query_vector=query_vector, top_k=top_k,
            text_field=self._text_field, vector_field=self._vector_field,
        )
        params = {"search_pipeline": self._search_pipeline} if self._search_pipeline else {}
        resp = await self._client.search(index=self._index_pattern, body=body, params=params)
        hits = []
        for h in resp["hits"]["hits"]:
            score = float(h.get("_score") or 0.0)
            if score < self._min_score:
                continue
            hits.append(SearchHit(id=h["_id"], score=score, source=h.get("_source", {})))
        return hits
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/modules/opensearch/test_search.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/zalo_bot/modules/opensearch tests/modules/opensearch
git commit -m "feat(opensearch): hybrid search retriever"
```

---

## Task 10: RAG prompt builder

**Files:**
- Create: `src/zalo_bot/modules/rag/__init__.py`, `src/zalo_bot/modules/rag/prompt.py`
- Test: `tests/modules/rag/__init__.py` (empty), `tests/modules/rag/test_prompt.py`

- [ ] **Step 1: Write the failing test**

`tests/modules/rag/test_prompt.py`:
```python
from zalo_bot.modules.opensearch.search import SearchHit
from zalo_bot.modules.rag.prompt import FALLBACK_ANSWER, build_messages


def _hit(text):
    return SearchHit(id="x", score=1.0, source={"text": text})


def test_build_messages_includes_context_and_question():
    msgs = build_messages("Giá bao nhiêu?", [_hit("Sản phẩm A giá 100k")], max_context_chars=1000)
    assert msgs[0]["role"] == "system"
    assert "Giá bao nhiêu?" in msgs[1]["content"]
    assert "Sản phẩm A giá 100k" in msgs[1]["content"]


def test_context_is_truncated_to_limit():
    long_hit = _hit("x" * 5000)
    msgs = build_messages("q", [long_hit], max_context_chars=100)
    assert len(msgs[1]["content"]) < 400  # context portion bounded


def test_fallback_constant_exists():
    assert "chưa có thông tin" in FALLBACK_ANSWER.lower()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/modules/rag/test_prompt.py -v`
Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 3: Write implementation**

`src/zalo_bot/modules/rag/__init__.py`: empty.
`src/zalo_bot/modules/rag/prompt.py`:
```python
from zalo_bot.modules.opensearch.search import SearchHit

FALLBACK_ANSWER = "Mình chưa có thông tin về vấn đề này."

_SYSTEM = (
    "Bạn là trợ lý. CHỈ trả lời dựa trên \"Ngữ cảnh\" bên dưới. "
    "Nếu ngữ cảnh không chứa thông tin, trả lời: \"" + FALLBACK_ANSWER + "\". "
    "Trả lời ngắn gọn, bằng tiếng Việt."
)


def build_messages(question: str, hits: list[SearchHit], *, max_context_chars: int) -> list[dict]:
    blocks: list[str] = []
    used = 0
    for i, hit in enumerate(hits, start=1):
        text = str(hit.source.get("text", "")).strip()
        if not text:
            continue
        block = f"[{i}] {text}"
        if used + len(block) > max_context_chars:
            block = block[: max_context_chars - used]
            blocks.append(block)
            break
        blocks.append(block)
        used += len(block)
    context = "\n".join(blocks)
    user = f"Ngữ cảnh:\n{context}\n\nCâu hỏi: {question}"
    return [{"role": "system", "content": _SYSTEM}, {"role": "user", "content": user}]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/modules/rag/test_prompt.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/zalo_bot/modules/rag/__init__.py src/zalo_bot/modules/rag/prompt.py tests/modules/rag/__init__.py tests/modules/rag/test_prompt.py
git commit -m "feat(rag): prompt builder with context truncation"
```

---

## Task 11: RAG orchestrator

**Files:**
- Create: `src/zalo_bot/modules/rag/orchestrator.py`
- Test: `tests/modules/rag/test_orchestrator.py`

- [ ] **Step 1: Write the failing test**

`tests/modules/rag/test_orchestrator.py`:
```python
import pytest

from zalo_bot.modules.opensearch.search import SearchHit
from zalo_bot.modules.rag.orchestrator import RagOrchestrator
from zalo_bot.modules.rag.prompt import FALLBACK_ANSWER


class _Gateway:
    def __init__(self, answer="đáp án"):
        self.answer = answer
        self.chat_called = False

    async def embed(self, text):
        return [0.1, 0.2]

    async def chat(self, messages, **kwargs):
        self.chat_called = True
        return self.answer


class _Retriever:
    def __init__(self, hits):
        self._hits = hits

    async def hybrid_search(self, text, vector, *, top_k):
        return self._hits


@pytest.mark.asyncio
async def test_answer_returns_llm_output_when_hits_exist():
    gw = _Gateway("đáp án từ context")
    rag = RagOrchestrator(
        gateway=gw, retriever=_Retriever([SearchHit("a", 0.9, {"text": "ctx"})]),
        top_k=5, max_context_chars=1000,
    )
    out = await rag.answer_question("hỏi gì")
    assert out == "đáp án từ context"
    assert gw.chat_called is True


@pytest.mark.asyncio
async def test_answer_returns_fallback_without_calling_llm_when_no_hits():
    gw = _Gateway()
    rag = RagOrchestrator(
        gateway=gw, retriever=_Retriever([]), top_k=5, max_context_chars=1000
    )
    out = await rag.answer_question("hỏi gì")
    assert out == FALLBACK_ANSWER
    assert gw.chat_called is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/modules/rag/test_orchestrator.py -v`
Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 3: Write implementation**

`src/zalo_bot/modules/rag/orchestrator.py`:
```python
from typing import Any

from zalo_bot.modules.rag.prompt import FALLBACK_ANSWER, build_messages


class RagOrchestrator:
    def __init__(
        self, *, gateway: Any, retriever: Any, top_k: int, max_context_chars: int
    ) -> None:
        self._gateway = gateway
        self._retriever = retriever
        self._top_k = top_k
        self._max_context_chars = max_context_chars

    async def answer_question(self, question: str) -> str:
        vector = await self._gateway.embed(question)
        hits = await self._retriever.hybrid_search(question, vector, top_k=self._top_k)
        if not hits:
            return FALLBACK_ANSWER
        messages = build_messages(question, hits, max_context_chars=self._max_context_chars)
        answer = await self._gateway.chat(messages)
        return answer or FALLBACK_ANSWER
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/modules/rag/test_orchestrator.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/zalo_bot/modules/rag/orchestrator.py tests/modules/rag/test_orchestrator.py
git commit -m "feat(rag): orchestrator embed->search->answer with fallback"
```

---

## Task 12: Composition root (shared dependency wiring)

**Files:**
- Create: `src/zalo_bot/deps.py`
- Test: `tests/test_deps.py`

> A single place that builds the concrete clients from `Settings`, so web and worker share identical wiring.

- [ ] **Step 1: Write the failing test**

`tests/test_deps.py`:
```python
from zalo_bot.deps import build_redis, build_rag


def test_build_rag_returns_orchestrator():
    rag = build_rag()
    assert hasattr(rag, "answer_question")


def test_build_redis_returns_client():
    r = build_redis()
    assert r is not None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_deps.py -v`
Expected: FAIL with `ModuleNotFoundError: zalo_bot.deps`.

- [ ] **Step 3: Write implementation**

`src/zalo_bot/deps.py`:
```python
from functools import lru_cache

from opensearchpy import AsyncOpenSearch
from redis.asyncio import Redis

from zalo_bot.config.settings import get_settings
from zalo_bot.modules.llm_gateway.client import LlmGateway
from zalo_bot.modules.opensearch.search import OpenSearchRetriever
from zalo_bot.modules.rag.orchestrator import RagOrchestrator
from zalo_bot.modules.zalo.client import ZaloClient
from zalo_bot.modules.zalo.token import TokenManager


@lru_cache
def build_redis() -> Redis:
    return Redis.from_url(get_settings().redis_url)


@lru_cache
def build_gateway() -> LlmGateway:
    s = get_settings()
    return LlmGateway(
        base_url=s.llm_gateway_base_url, api_key=s.llm_gateway_api_key,
        embedding_model=s.llm_embedding_model, chat_model=s.llm_chat_model,
        timeout=s.external_call_timeout_seconds,
    )


@lru_cache
def build_retriever() -> OpenSearchRetriever:
    s = get_settings()
    http_auth = (s.opensearch_user, s.opensearch_password) if s.opensearch_user else None
    client = AsyncOpenSearch(
        hosts=[s.opensearch_url], http_auth=http_auth,
        timeout=s.external_call_timeout_seconds,
    )
    return OpenSearchRetriever(
        client=client, index_pattern=s.opensearch_index_pattern,
        search_pipeline=s.opensearch_search_pipeline,
        text_field=s.opensearch_text_field, vector_field=s.opensearch_vector_field,
        min_score=s.opensearch_min_score,
    )


@lru_cache
def build_rag() -> RagOrchestrator:
    s = get_settings()
    return RagOrchestrator(
        gateway=build_gateway(), retriever=build_retriever(),
        top_k=s.opensearch_top_k, max_context_chars=s.rag_max_context_chars,
    )


@lru_cache
def build_zalo_client() -> ZaloClient:
    s = get_settings()
    tokens = TokenManager(
        redis=build_redis(), token_url=s.zalo_token_api_url,
        app_id=s.zalo_app_id, app_secret=s.zalo_app_secret,
        refresh_token=s.zalo_refresh_token,
    )
    return ZaloClient(
        send_url=s.zalo_send_api_url, tokens=tokens,
        timeout=s.external_call_timeout_seconds,
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_deps.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/zalo_bot/deps.py tests/test_deps.py
git commit -m "feat: composition root wiring shared dependencies"
```

---

## Task 13: Queue job (process + enqueue)

**Files:**
- Create: `src/zalo_bot/queue/__init__.py`, `src/zalo_bot/queue/jobs.py`
- Test: `tests/queue/__init__.py` (empty), `tests/queue/test_jobs.py`

- [ ] **Step 1: Write the failing test**

`tests/queue/test_jobs.py`:
```python
import pytest

from zalo_bot.queue.jobs import enqueue_answer_job, process_answer_job


class _Arq:
    def __init__(self):
        self.calls = []

    async def enqueue_job(self, name, payload, _job_id=None):
        self.calls.append((name, payload, _job_id))


@pytest.mark.asyncio
async def test_enqueue_uses_msg_id_as_job_id():
    arq = _Arq()
    job = {"user_id": "u1", "text": "hi", "msg_id": "m1", "received_at": 1}
    await enqueue_answer_job(arq, job)
    name, payload, job_id = arq.calls[0]
    assert name == "process_answer_job"
    assert job_id == "m1"
    assert payload == job


@pytest.mark.asyncio
async def test_process_answers_and_sends(monkeypatch):
    sent = {}

    class _Rag:
        async def answer_question(self, q):
            return f"ans:{q}"

    class _Zalo:
        async def send_text_message(self, user_id, text):
            sent["user_id"] = user_id
            sent["text"] = text

    monkeypatch.setattr("zalo_bot.queue.jobs.build_rag", lambda: _Rag())
    monkeypatch.setattr("zalo_bot.queue.jobs.build_zalo_client", lambda: _Zalo())

    job = {"user_id": "u1", "text": "câu hỏi", "msg_id": "m1", "received_at": 1}
    await process_answer_job({}, job)
    assert sent == {"user_id": "u1", "text": "ans:câu hỏi"}


@pytest.mark.asyncio
async def test_process_sends_fallback_on_error(monkeypatch):
    sent = {}

    class _Rag:
        async def answer_question(self, q):
            raise RuntimeError("boom")

    class _Zalo:
        async def send_text_message(self, user_id, text):
            sent["text"] = text

    monkeypatch.setattr("zalo_bot.queue.jobs.build_rag", lambda: _Rag())
    monkeypatch.setattr("zalo_bot.queue.jobs.build_zalo_client", lambda: _Zalo())

    job = {"user_id": "u1", "text": "q", "msg_id": "m1", "received_at": 1}
    with pytest.raises(RuntimeError):
        await process_answer_job({"job_try": 3, "max_tries": 3}, job)
    assert "đang bận" in sent["text"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/queue/test_jobs.py -v`
Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 3: Write implementation**

`src/zalo_bot/queue/__init__.py`: empty.
`src/zalo_bot/queue/jobs.py`:
```python
from typing import Any, TypedDict

from zalo_bot.deps import build_rag, build_zalo_client
from zalo_bot.lib.logging import get_logger

log = get_logger("queue")
_BUSY_MESSAGE = "Hệ thống đang bận, bạn vui lòng thử lại sau ít phút nhé."


class AnswerJob(TypedDict):
    user_id: str
    text: str
    msg_id: str
    received_at: int


async def enqueue_answer_job(arq: Any, job: AnswerJob) -> None:
    await arq.enqueue_job("process_answer_job", job, _job_id=job["msg_id"])


async def process_answer_job(ctx: dict, job: AnswerJob) -> None:
    correlation_id = job["msg_id"]
    try:
        rag = build_rag()
        answer = await rag.answer_question(job["text"])
        await build_zalo_client().send_text_message(job["user_id"], answer)
        log.info("answered", correlation_id=correlation_id)
    except Exception:
        log.exception("process_failed", correlation_id=correlation_id)
        # On the final attempt, tell the user instead of going silent.
        if ctx.get("job_try", 1) >= ctx.get("max_tries", 1):
            try:
                await build_zalo_client().send_text_message(job["user_id"], _BUSY_MESSAGE)
            except Exception:
                log.exception("fallback_send_failed", correlation_id=correlation_id)
        raise
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/queue/test_jobs.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/zalo_bot/queue tests/queue
git commit -m "feat(queue): answer job with idempotent enqueue and fallback"
```

---

## Task 14: Web entrypoint (FastAPI)

**Files:**
- Create: `src/zalo_bot/entrypoints/__init__.py`, `src/zalo_bot/entrypoints/web.py`
- Test: `tests/entrypoints/__init__.py` (empty), `tests/entrypoints/test_web.py`

- [ ] **Step 1: Write the failing test**

`tests/entrypoints/test_web.py`:
```python
import hashlib

import pytest
from httpx import ASGITransport, AsyncClient

from zalo_bot.entrypoints.web import create_app


def _mac(app_id, body, ts, secret):
    return hashlib.sha256((app_id + body.decode() + ts + secret).encode()).hexdigest()


@pytest.mark.asyncio
async def test_health_ok():
    app = create_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://t") as c:
        r = await c.get("/health")
    assert r.status_code == 200


@pytest.mark.asyncio
async def test_webhook_rejects_bad_signature():
    app = create_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://t") as c:
        r = await c.post(
            "/webhook/zalo", content=b'{"event_name":"user_send_text"}',
            headers={"X-ZEvent-Signature": "mac=bad", "X-ZEvent-Timestamp": "1"},
        )
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_webhook_enqueues_text_event(monkeypatch):
    enqueued = {}

    async def _fake_enqueue(arq, job):
        enqueued.update(job)

    class _FakePool:
        pass

    monkeypatch.setattr("zalo_bot.entrypoints.web.enqueue_answer_job", _fake_enqueue)
    monkeypatch.setattr("zalo_bot.entrypoints.web.get_arq_pool", lambda: _FakePool())

    body = b'{"event_name":"user_send_text","sender":{"id":"u1"},"message":{"msg_id":"m1","text":"hi"},"timestamp":"1"}'
    mac = _mac("appid", body, "1", "secret")

    app = create_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://t") as c:
        r = await c.post(
            "/webhook/zalo", content=body,
            headers={"X-ZEvent-Signature": f"mac={mac}", "X-ZEvent-Timestamp": "1"},
        )
    assert r.status_code == 200
    assert enqueued["user_id"] == "u1"
    assert enqueued["msg_id"] == "m1"
```

> Note: `conftest.py` sets `ZALO_APP_ID=appid` and `ZALO_OA_SECRET=secret`, matching the `_mac` inputs above.

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/entrypoints/test_web.py -v`
Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 3: Write implementation**

`src/zalo_bot/entrypoints/__init__.py`: empty.
`src/zalo_bot/entrypoints/web.py`:
```python
import json

from arq import create_pool
from arq.connections import RedisSettings
from fastapi import FastAPI, Request, Response

from zalo_bot.config.settings import get_settings
from zalo_bot.lib.logging import configure_logging, get_logger
from zalo_bot.modules.zalo.events import parse_event
from zalo_bot.modules.zalo.signature import verify_signature
from zalo_bot.queue.jobs import enqueue_answer_job

log = get_logger("web")
_pool = None


async def _init_pool() -> None:
    global _pool
    if _pool is None:
        _pool = await create_pool(RedisSettings.from_dsn(get_settings().redis_url))


def get_arq_pool():
    return _pool


def create_app() -> FastAPI:
    settings = get_settings()
    configure_logging(settings.log_level)
    app = FastAPI(title="zalo-oa-rag")

    @app.on_event("startup")
    async def _startup() -> None:
        await _init_pool()

    @app.get("/health")
    async def health() -> dict:
        return {"status": "ok"}

    @app.post("/webhook/zalo")
    async def webhook(request: Request) -> Response:
        raw = await request.body()
        mac_header = request.headers.get("X-ZEvent-Signature", "")
        timestamp = request.headers.get("X-ZEvent-Timestamp", "")
        if not verify_signature(
            raw_body=raw, header=mac_header, app_id=settings.zalo_app_id,
            timestamp=timestamp, oa_secret=settings.zalo_oa_secret,
        ):
            log.warning("invalid_signature")
            return Response(status_code=401)

        body = json.loads(raw or b"{}")
        event = parse_event(body)
        if not event.is_text_question:
            return Response(status_code=200)  # ack non-text events, nothing to do

        await enqueue_answer_job(
            get_arq_pool(),
            {
                "user_id": event.user_id, "text": event.text,
                "msg_id": event.msg_id, "received_at": int(event.timestamp or 0),
            },
        )
        log.info("enqueued", correlation_id=event.msg_id)
        return Response(status_code=200)

    return app


app = create_app()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/entrypoints/test_web.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/zalo_bot/entrypoints/__init__.py src/zalo_bot/entrypoints/web.py tests/entrypoints
git commit -m "feat(web): FastAPI webhook + health endpoints"
```

---

## Task 15: Worker entrypoint (arq)

**Files:**
- Create: `src/zalo_bot/entrypoints/worker.py`
- Test: `tests/entrypoints/test_worker.py`

- [ ] **Step 1: Write the failing test**

`tests/entrypoints/test_worker.py`:
```python
from zalo_bot.entrypoints.worker import WorkerSettings
from zalo_bot.queue.jobs import process_answer_job


def test_worker_registers_job_and_retries():
    assert process_answer_job in WorkerSettings.functions
    assert WorkerSettings.max_tries == 3
    assert WorkerSettings.redis_settings is not None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/entrypoints/test_worker.py -v`
Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 3: Write implementation**

`src/zalo_bot/entrypoints/worker.py`:
```python
from arq.connections import RedisSettings

from zalo_bot.config.settings import get_settings
from zalo_bot.lib.logging import configure_logging
from zalo_bot.queue.jobs import process_answer_job

_settings = get_settings()
configure_logging(_settings.log_level)


class WorkerSettings:
    functions = [process_answer_job]
    redis_settings = RedisSettings.from_dsn(_settings.redis_url)
    max_tries = 3
    job_timeout = _settings.external_call_timeout_seconds * 3
    # arq retries failed jobs with exponential backoff by default.
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/entrypoints/test_worker.py -v`
Expected: PASS.

- [ ] **Step 5: Run the full suite + lint + types**

Run:
```bash
pytest -q && ruff check src tests && mypy
```
Expected: all green.

- [ ] **Step 6: Commit**

```bash
git add src/zalo_bot/entrypoints/worker.py tests/entrypoints/test_worker.py
git commit -m "feat(worker): arq worker settings with retries"
```

---

## Task 16: Docker & compose

**Files:**
- Create: `docker/Dockerfile`, `docker/docker-compose.yml`, `.dockerignore`

- [ ] **Step 1: Write `docker/Dockerfile`**

```dockerfile
FROM python:3.11-slim
WORKDIR /app
ENV PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
COPY pyproject.toml ./
COPY src ./src
RUN pip install --upgrade pip && pip install -e .
# Default command runs the web server; compose overrides for the worker.
CMD ["uvicorn", "zalo_bot.entrypoints.web:app", "--host", "0.0.0.0", "--port", "3000"]
```

- [ ] **Step 2: Write `.dockerignore`**

```
.venv
__pycache__
*.pyc
tests
docs
.git
.env
```

- [ ] **Step 3: Write `docker/docker-compose.yml`**

```yaml
services:
  redis:
    image: redis:7-alpine
    ports: ["6379:6379"]

  opensearch:
    image: opensearchproject/opensearch:2.13.0
    environment:
      discovery.type: single-node
      plugins.security.disabled: "true"
      OPENSEARCH_INITIAL_ADMIN_PASSWORD: Dev_passw0rd!
    ports: ["9200:9200"]

  web:
    build:
      context: ..
      dockerfile: docker/Dockerfile
    env_file: ../.env
    environment:
      REDIS_URL: redis://redis:6379/0
      OPENSEARCH_URL: http://opensearch:9200
    ports: ["3000:3000"]
    depends_on: [redis, opensearch]

  worker:
    build:
      context: ..
      dockerfile: docker/Dockerfile
    env_file: ../.env
    environment:
      REDIS_URL: redis://redis:6379/0
      OPENSEARCH_URL: http://opensearch:9200
    command: ["arq", "zalo_bot.entrypoints.worker.WorkerSettings"]
    depends_on: [redis, opensearch]
```

> Note: when running via this compose, recreate the search pipeline (Task 0 Step 2) and seed index (Step 3) against `http://localhost:9200` after `opensearch` is healthy, since the container starts empty.

- [ ] **Step 4: Verify the image builds**

Run:
```bash
docker compose -f docker/docker-compose.yml build
```
Expected: both `web` and `worker` images build successfully.

- [ ] **Step 5: Commit**

```bash
git add docker/Dockerfile docker/docker-compose.yml .dockerignore
git commit -m "chore(docker): image and compose for web + worker + redis"
```

---

## Task 17: End-to-end smoke (MANUAL, against live deps)

- [ ] **Step 1: Fill `.env`** from real Zalo OA + OpenSearch + gateway values (using Task 0 results).

- [ ] **Step 2: Start the stack**

Run: `docker compose -f docker/docker-compose.yml up`
Expected: web on :3000, worker connected to redis, opensearch healthy, no startup errors. Then re-apply Task 0 Step 2 (pipeline) + Step 3 (seed index) against `http://localhost:9200`.

- [ ] **Step 3: Send a real question** from a Zalo user through the webhook registered in Task 0 (`https://<public-url>/webhook/zalo`, tunnel pointing at :3000).
Expected: user receives a context-grounded answer; logs show one `enqueued` (web) and one `answered` (worker) with the same `correlation_id`.

- [ ] **Step 4: Negative check** — send a non-text message (image/sticker).
Expected: webhook returns 200, no job enqueued, no reply.

No commit (manual verification).

---

## Self-Review (completed during authoring)

- **Spec coverage:** webhook+signature (T4,T14), event parse (T5), token refresh (T6), send (T7), gateway embed/chat (T8), hybrid search (T9), prompt+fallback (T10,T11), async queue+idempotency (T13), web/worker split (T14,T15), error/retry/observability (T6,T7,T13,T15 + structlog T3), docker (T16), tests per module (each task), verification items (T0), out-of-scope respected (no ingestion, stateless, non-text acked). All spec sections map to a task.
- **Type consistency:** `LlmGateway.embed/chat`, `OpenSearchRetriever.hybrid_search(text, vector, *, top_k)`, `RagOrchestrator.answer_question`, `AnswerJob` keys (`user_id/text/msg_id/received_at`), `verify_signature(*, raw_body, header, app_id, timestamp, oa_secret)`, and `build_messages(question, hits, *, max_context_chars)` are used identically across tasks and tests.
- **Placeholders:** none — every code step has full code; the only manual tasks (T0, T17) are explicitly read-only/live-verification with concrete commands.
```
