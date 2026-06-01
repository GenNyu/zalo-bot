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
