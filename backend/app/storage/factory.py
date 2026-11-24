import os

from backend.app.storage.errors import StorageConfigurationError


def create_storage():
    storage_type = os.getenv("STUDYCLOUD_STORAGE", "sqlite").strip().lower()

    if storage_type == "sqlite":
        from backend.app.storage.sqlite_store import SQLiteStorage

        return SQLiteStorage()

    raise StorageConfigurationError(
        f"Unsupported storage type: {storage_type!r}"
    )
