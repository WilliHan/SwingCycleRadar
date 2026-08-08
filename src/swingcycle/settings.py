from pathlib import Path

import yaml
from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parents[2]
CONFIG_DIR = PROJECT_ROOT / "config"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=PROJECT_ROOT / ".env", extra="ignore")

    krx_web_id: str = ""
    krx_web_password: str = ""
    krx_web_login_enabled: bool = True
    krx_login_cd003_max_retry: int = 3
    krx_login_cd003_backoff_base: float = 1.0
    krx_login_min_interval_sec: int = 300
    krx_login_shared_state_path: str = "~/.krx_shared/login_state.json"

    db_path: str = "./data/swingcycle.db"
    log_level: str = "INFO"
    http_timeout_sec: float = 20.0
    http_max_retries: int = 3

    supabase_url: str = ""
    supabase_service_key: str = ""

    mfgr_url: str = "http://localhost:8503"

    @property
    def db_path_resolved(self) -> Path:
        p = Path(self.db_path)
        return p if p.is_absolute() else (PROJECT_ROOT / p)

    @property
    def krx_login_shared_state_path_resolved(self) -> Path:
        return Path(self.krx_login_shared_state_path).expanduser()


def load_yaml_config(name: str) -> dict:
    """config/<name>.yml 을 읽어 dict로 반환한다."""
    path = CONFIG_DIR / name
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


settings = Settings()
