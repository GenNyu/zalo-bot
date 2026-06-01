# Zalo OA RAG Service — Design

- Date: 2026-06-01
- Status: Approved (design); pending implementation plan
- Owner: phancaonguyen58@gmail.com

## 1. Mục tiêu

Xây dựng một service nhận câu hỏi từ người dùng qua **Zalo OA webhook**, dùng
**OpenSearch (hybrid search)** để truy xuất thông tin liên quan, dùng một **agent
LLM** tổng hợp kết quả thành câu trả lời, rồi gửi trả lại người dùng qua **Zalo OA
Open API**.

## 2. Quyết định đã chốt

| Khía cạnh | Quyết định |
|---|---|
| Runtime | Python (3.11+) |
| Web framework | FastAPI (async) |
| Queue | arq (Redis-backed, async-native) |
| OpenSearch | Index có sẵn + data sẵn; **hybrid** (BM25 + vector) |
| Index target | Pattern cấu hình được, mặc định `open_webui_file-*` (index do Open WebUI tạo, 1 index / file) |
| Embedding câu hỏi | Qua LLM gateway nội bộ; model **khớp** với model Open WebUI đã index |
| Agent LLM | Qua LLM gateway nội bộ (OpenAI-compatible, API key); dùng `openai` SDK với `base_url` nội bộ |
| Webhook flow | Async: ack 200 ngay → enqueue → worker xử lý → gửi trả Zalo |
| Hội thoại | Stateless (mỗi câu hỏi độc lập, không nhớ lịch sử) |
| Deploy | Docker / docker-compose (web + worker + redis) |
| Kiến trúc | Modular monolith, 2 entrypoint (web + worker) chung codebase/image |

## 3. Kiến trúc

```
Zalo Platform ──webhook POST──▶ web (FastAPI)
                                  1. verify chữ ký X-ZEvent-Signature (raw body)
                                  2. parse event (user_send_text)
              ◀──── 200 OK ────── 3. enqueue job
                                        │
                                        ▼
                                   Redis (arq queue)
                                        │
                                        ▼
                                 worker (arq)
                                  4. embed câu hỏi (gateway)
                                  5. hybrid search OpenSearch
                                  6. agent tổng hợp câu trả lời (LLM)
                                  7. Zalo Send API ──▶ Zalo ──▶ User
```

### Cấu trúc thư mục

```
zalo-bot/
├── src/zalo_bot/
│   ├── entrypoints/
│   │   ├── web.py            # FastAPI app (webhook)
│   │   └── worker.py         # arq worker
│   ├── modules/
│   │   ├── zalo/             # verify chữ ký, parse event, Send API, token refresh
│   │   ├── opensearch/       # client + hybrid search query
│   │   ├── llm_gateway/      # OpenAI-compatible: embeddings + chat
│   │   └── rag/              # orchestrator: embed → search → prompt → answer
│   ├── queue/                # định nghĩa job, producer/consumer
│   ├── config/               # load + validate env (pydantic-settings)
│   └── lib/                  # logger (structlog), http (httpx), errors
├── tests/
├── docker/                   # Dockerfile, docker-compose.yml
├── pyproject.toml
└── .env.example
```

**Nguyên tắc tách module:** mỗi module một nhiệm vụ, interface gọn, test độc lập.
`rag` là nơi duy nhất biết "quy trình"; `zalo` / `opensearch` / `llm_gateway`
không biết về nhau.

## 4. Component & Interface

### modules/zalo
- `verify_signature(raw_body: bytes, mac: str) -> bool` — HMAC-SHA256 với appsecret, chạy trên raw body.
- `parse_event(body: dict) -> ZaloEvent` — chuẩn hóa thành `{ event_name, user_id, text, msg_id, timestamp }`.
- `send_text_message(user_id: str, text: str) -> None` — gọi Zalo OA Open API.
- `get_access_token() -> str` — cache trong Redis + auto refresh khi còn < 1h; dùng Redis lock chống thundering herd.

### modules/llm_gateway (OpenAI-compatible, `openai` SDK với base_url nội bộ)
- `embed(text: str) -> list[float]` — `POST /v1/embeddings`, model khớp Open WebUI.
- `chat(messages, **opts) -> str` — `POST /v1/chat/completions`.
- Timeout + retry giới hạn cho lỗi mạng/5xx.

### modules/opensearch
- `hybrid_search(query_text: str, query_vector: list[float], top_k: int, indices: str | None = None) -> list[SearchHit]`
  - `indices` mặc định lấy từ config (`open_webui_file-*`).
  - `SearchHit = { id, score, source }` với `source` chứa field cần cho context.
  - Dùng `hybrid` query (match BM25 + knn) qua `search_pipeline` cấu hình được.

### modules/rag (orchestrator)
- `answer_question(question: str) -> str`
  1. `vector = llm_gateway.embed(question)`
  2. `hits = opensearch.hybrid_search(question, vector, top_k)`
  3. nếu `hits` rỗng / điểm dưới ngưỡng → trả fallback, **không gọi LLM**.
  4. `prompt = build_prompt(question, hits)` — ghép context (cắt theo giới hạn token/ký tự cấu hình) + chỉ dẫn "chỉ trả lời dựa trên context".
  5. `answer = llm_gateway.chat(prompt)` → return.

### queue (arq)
- Job payload: `{ user_id, text, msg_id, received_at }`.
- `enqueue_answer_job(job)` — producer (web gọi).
- `process_answer_job(ctx, job)` — consumer (worker): `rag.answer_question` → `zalo.send_text_message`.
- Idempotency: set `job_id = msg_id` và/hoặc check SET key Redis trước khi xử lý (arq không khử trùng sẵn như BullMQ).

## 5. Data Flow & Contract

### 5.1 Webhook payload (user_send_text)
```jsonc
{
  "app_id": "...",
  "event_name": "user_send_text",
  "sender":    { "id": "<user_id>" },
  "recipient": { "id": "<oa_id>" },
  "message":   { "msg_id": "...", "text": "câu hỏi của user" },
  "timestamp": "1700000000000"
}
```
Header `X-ZEvent-Signature: mac=...` → verify `HMAC-SHA256(appsecret, appId + rawBody + timestamp)` trên raw body.

### 5.2 Job (arq)
```python
class AnswerJob(TypedDict):
    user_id: str       # sender.id
    text: str          # message.text
    msg_id: str        # idempotency key
    received_at: int
```

### 5.3 Hybrid search request
```jsonc
POST /open_webui_file-*/_search?search_pipeline=<config>
{
  "size": <top_k>,
  "query": {
    "hybrid": {
      "queries": [
        { "match": { "text": { "query": "<question>" } } },
        { "knn":   { "vector": { "vector": [/* embedding */], "k": <top_k> } } }
      ]
    }
  },
  "_source": ["text", "metadata"]
}
```

### 5.4 Prompt
```
system: Bạn là trợ lý. CHỈ trả lời dựa trên "Ngữ cảnh" bên dưới.
        Nếu ngữ cảnh không chứa thông tin, trả lời "Mình chưa có thông tin về vấn đề này".
        Trả lời ngắn gọn, tiếng Việt.
user:   Ngữ cảnh:
        [1] <text hit 1>
        [2] <text hit 2>
        Câu hỏi: <question>
```

### 5.5 Trả về Zalo
```jsonc
POST https://openapi.zalo.me/v3.0/oa/message
header: access_token: <token>
body:   { "recipient": { "user_id": "<user_id>" },
          "message": { "text": "<câu trả lời>" } }
```

### Quy tắc
- **Idempotency** theo `msg_id` (Zalo có thể retry webhook).
- **Fallback** khi không có hit phù hợp → trả thẳng câu "chưa có thông tin", không gọi LLM.
- **Giới hạn độ dài context** ghép vào prompt (cấu hình được).

## 6. Error Handling, Retry, Observability

| Tầng | Lỗi | Xử lý |
|---|---|---|
| web | Sai chữ ký | `401`, không enqueue, log cảnh báo |
| web | Body lỗi / event không hỗ trợ | `200`, bỏ qua hoặc trả lời mặc định |
| web | Enqueue Redis lỗi | `500` → Zalo retry |
| worker: embed | Gateway timeout/5xx | Retry backoff |
| worker: search | OpenSearch lỗi | Retry; cạn → câu xin lỗi |
| worker: chat | Gateway timeout/5xx | Retry; cạn → câu xin lỗi |
| worker: send | Token hết hạn | Refresh token + gửi lại 1 lần; lỗi khác → retry |

- **Retry (arq):** `max_tries = 3`, backoff lũy thừa (~2s, 4s, 8s); job thất bại cuối → gửi user câu fallback (không im lặng).
- **Timeout cứng** mỗi external call (mặc định ~30s, cấu hình được).
- **Token refresh:** Redis lock chống thundering herd; token + expiry lưu Redis.
- **Logging:** structlog, `correlation_id = msg_id` xuyên suốt web → queue → worker. Log mốc: nhận webhook / enqueue / search (số hit, điểm) / LLM (latency, token) / gửi Zalo.
- **Health endpoint** `/health` (web): kiểm tra Redis + OpenSearch + gateway.
- Không log nội dung nhạy cảm quá mức; text câu hỏi ở mức debug, tắt được.
- Metrics Prometheus: tùy chọn, thêm sau khi cần (YAGNI).

## 7. Test Strategy

| Loại | Phạm vi | Cách |
|---|---|---|
| Unit `zalo` | verify_signature, parse_event, build payload | Vector cố định, không gọi mạng |
| Unit `llm_gateway` | map req/resp, retry, timeout | respx mock HTTP |
| Unit `opensearch` | dựng đúng hybrid query body | mock client, assert body |
| Unit `rag` | orchestration; fallback 0 hit; cắt context | mock 3 module phụ thuộc; trọng tâm TDD |
| Unit `queue` | enqueue đúng; idempotency theo msg_id | mock redis/arq |
| Integration | webhook giả → verify → enqueue (Redis testcontainer) | httpx ASGI client |
| Integration (tùy chọn) | worker chạy job với OpenSearch testcontainer seed doc | nặng hơn, chỉ khi cần |
| E2E thủ công | Zalo OA sandbox → nhận trả lời | checklist trước launch |

- **Công cụ:** pytest + pytest-asyncio + respx + httpx ASGI client + testcontainers-python.
- **Cổng chất lượng:** type check (mypy/pyright) + lint (ruff) + unit test pass trước khi coi 1 slice là xong; integration ở CI.

## 8. Việc cần xác minh TRƯỚC khi code

1. **Mapping index Open WebUI:** `GET /open_webui_file-<id>/_mapping` để xác nhận tên field thật (kỳ vọng `text`, `vector` knn_vector, `metadata`) và **số chiều vector**.
2. **Search pipeline:** xác nhận cluster có `search_pipeline` (normalization-processor) hay phải dùng `hybrid` query inline; thử 1 query hybrid bằng tay.
3. **Embedding model:** xác nhận tên model + số chiều mà gateway phục vụ **đúng** với model đã index.
4. **Zalo OA credentials:** có sẵn `access_token` / `refresh_token` / `appsecret`; xác nhận công thức chữ ký webhook theo phiên bản API hiện hành.

## 9. Out of scope (giai đoạn này)

- Ingestion / index dữ liệu (đã có sẵn, do Open WebUI quản lý).
- Hội thoại nhiều lượt (stateless).
- Xử lý ảnh/file/sticker (trả lời mặc định "chưa hỗ trợ").
- Multi-index động theo routing; rerank tầng app — chỉ thêm khi đo thấy cần.
- Metrics/alerting nâng cao.
