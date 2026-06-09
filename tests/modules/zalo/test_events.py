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


def test_parse_message_text_received():
    body = {
        "event_name": "message.text.received",
        "message": {
            "date": 1780973847282,
            "chat": {"chat_type": "PRIVATE", "id": "chat1"},
            "message_id": "m-new",
            "from": {"id": "u-new", "is_bot": False, "display_name": "Nguyen"},
            "text": "Hi",
        },
    }
    ev = parse_event(body)
    assert ev.event_name == "message.text.received"
    assert ev.user_id == "u-new"
    assert ev.msg_id == "m-new"
    assert ev.text == "Hi"
    assert ev.timestamp == "1780973847282"
    assert ev.is_text_question is True


def test_parse_message_sticker_received_is_not_text_question():
    body = {
        "event_name": "message.sticker.received",
        "message": {
            "date": 1780973198321,
            "chat": {"chat_type": "PRIVATE", "id": "chat1"},
            "sticker": "5cb6159929dcc08299cd",
            "message_id": "m-sticker",
            "message_type": "CHAT_STICKER",
            "from": {"id": "u-new", "is_bot": False, "display_name": "Nguyen"},
            "url": "https://zalo-api.zadn.vn/api/emoticon/oasticker?eid=1&size=130",
        },
    }
    ev = parse_event(body)
    assert ev.event_name == "message.sticker.received"
    assert ev.user_id == "u-new"
    assert ev.msg_id == "m-sticker"
    assert ev.timestamp == "1780973198321"
    assert ev.is_text_question is False
    assert ev.text == ""
