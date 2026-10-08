from functools import lru_cache
from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict
from cryptography.fernet import Fernet
import os
import secrets


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")
    openai_api_key: str = ""
    openai_model: str = "gpt-4.1-mini"
    encryption_key: str = ""
    data_dir: Path = Path(".data")
    database_url: str = "sqlite:///.data/app.sqlite3"
    browser_headless: bool = False
    enable_mock_portal: bool = False
    frontend_origins: str = "http://localhost:5173,http://127.0.0.1:5173"

    @property
    def origins(self):
        return self.frontend_origins.split(",")


@lru_cache
def settings():
    return Settings()


@lru_cache
def cipher():
    cfg = settings()
    cfg.data_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    cfg.data_dir.chmod(0o700)
    if cfg.encryption_key:
        return Fernet(cfg.encryption_key.encode())
    path = cfg.data_dir / "key"
    if not path.exists():
        # Never silently replace a missing key for an existing database.
        if cfg.database_url.startswith("sqlite:///"):
            db = Path(cfg.database_url.removeprefix("sqlite:///"))
            if db.exists() and db.stat().st_size:
                raise RuntimeError("Database exists but encryption key is missing. Restore the original key.")
        fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        with os.fdopen(fd, "wb") as stream:
            stream.write(Fernet.generate_key())
    return Fernet(path.read_bytes())


@lru_cache
def access_code():
    """Private local pairing secret; never delivered by a public HTTP endpoint."""
    folder = settings().data_dir
    folder.mkdir(parents=True, exist_ok=True, mode=0o700)
    folder.chmod(0o700)
    path = folder / "access-code"
    if not path.exists():
        fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        with os.fdopen(fd, "w") as stream:
            stream.write(secrets.token_urlsafe(32))
    path.chmod(0o600)
    value = path.read_text().strip()
    if len(value) < 32:
        raise RuntimeError(
            "Local access code is invalid. Restore it or remove only the access-code file and restart."
        )
    return value
