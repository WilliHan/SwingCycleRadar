import os
from pathlib import Path

import yaml
from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parents[2]
CONFIG_DIR = PROJECT_ROOT / "config"

def strip_pykrx_legacy_env() -> None:
    """pykrx는 모듈 import 시점에 KRX_ID/KRX_PW 환경변수를 읽어 우리 로그인 조율 락
    (krx_login_lock.py 6.1.1)과 무관하게 즉시 자체 로그인을 시도한다
    (pykrx/website/comm/auth.py의 build_krx_session 기본 인자가 os.getenv(...)로
    평가되는 시점 = webio.py import 시점). 이 프로세스에서는 KRX_WEB_ID/PASSWORD만
    쓰고 KRX_ID/KRX_PW는 절대 쓰지 않으므로, 운영 환경에 우연히 남아있더라도
    pykrx가 보기 전에 여기서 제거한다.
    """
    os.environ.pop("KRX_ID", None)
    os.environ.pop("KRX_PW", None)


# settings 모듈은 pykrx를 import하는 pykrx_client.py보다 항상 먼저 로드되므로
# 여기서 즉시 1회 호출한다.
strip_pykrx_legacy_env()


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
