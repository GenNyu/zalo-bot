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
        text = hit.text.strip()
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
