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
