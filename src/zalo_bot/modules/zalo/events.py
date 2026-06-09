from dataclasses import dataclass

_TEXT_EVENT_NAMES = {"user_send_text", "message.text.received"}


@dataclass(frozen=True)
class ZaloEvent:
    event_name: str
    user_id: str
    msg_id: str
    text: str
    timestamp: str

    @property
    def is_text_question(self) -> bool:
        return self.event_name in _TEXT_EVENT_NAMES and bool(self.text.strip())


def parse_event(body: dict) -> ZaloEvent:
    message = body.get("message") or {}
    sender = body.get("sender") or {}
    message_from = message.get("from") or {}
    chat = message.get("chat") or {}
    return ZaloEvent(
        event_name=str(body.get("event_name", "")),
        user_id=str(sender.get("id") or message_from.get("id") or chat.get("id") or ""),
        msg_id=str(message.get("msg_id") or message.get("message_id") or ""),
        text=str(message.get("text", "") or ""),
        timestamp=str(body.get("timestamp") or message.get("date") or ""),
    )
