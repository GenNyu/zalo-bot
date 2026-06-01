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
