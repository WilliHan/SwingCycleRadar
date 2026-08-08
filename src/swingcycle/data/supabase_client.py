"""Supabase 클라이언트 헬퍼.

sugup-report의 webapp/common/supabase_helper.py 관례(환경변수 이름)를 참조하되
독립 구현이다(공용 import 금지, 통합 설계서 1.1항/6.2).
"""
from __future__ import annotations

from functools import lru_cache

from ..settings import settings


@lru_cache(maxsize=1)
def get_supabase_client():
    from supabase import create_client

    if not settings.supabase_url or not settings.supabase_service_key:
        raise RuntimeError("SUPABASE_URL / SUPABASE_SERVICE_KEY가 설정되지 않았습니다 (.env 확인)")
    return create_client(settings.supabase_url, settings.supabase_service_key)


def fetch_all_symbols() -> list[dict]:
    client = get_supabase_client()
    resp = client.table("swingcycle_symbols").select("*").execute()
    return resp.data or []
