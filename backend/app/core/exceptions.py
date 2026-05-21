"""Domain exceptions raised by the service layer."""


class NotFoundError(Exception):
    """Raised when a requested resource does not exist."""


class ConflictError(Exception):
    """Raised on a uniqueness constraint violation."""


class MediaSizeError(Exception):
    """Raised when a media upload exceeds the size limit."""
