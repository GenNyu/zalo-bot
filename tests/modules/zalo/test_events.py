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
