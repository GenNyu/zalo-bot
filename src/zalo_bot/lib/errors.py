class AppError(Exception):
    """Base for application errors."""


class SignatureError(AppError):
    """Webhook signature verification failed."""


class ExternalServiceError(AppError):
    """An upstream call (gateway, OpenSearch, Zalo) failed."""
