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
