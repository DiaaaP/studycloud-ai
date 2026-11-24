class StorageError(Exception):
    """Base exception for storage-related errors."""


class DuplicateUserError(StorageError):
    """Raised when username or email is already registered."""


class RecordNotFoundError(StorageError):
    """Raised when a requested record does not exist."""


class StorageConfigurationError(StorageError):
    """Raised when storage configuration is invalid."""
