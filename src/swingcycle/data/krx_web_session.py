"""KRX 웹 로그인 세션 관리 (krx_direct 인증 계층).

sugup-report의 src/sugup_pivot/market/pykrx_session.py를 참조해 SwingCycle Radar
저장소 안으로 이식한 독립 구현이다. sugup-report 모듈을 직접 import하지 않는다
(통합 설계서 1.1항 — 코드 재사용은 복사만, 공용 패키지/import 금지).

설계: docs/SwingCycle_Radar_Source_Level_Design_v1.1.md 6장
"""
from __future__ import annotations

import logging
import random
import threading
import time
from typing import Any

import requests

from ..settings import settings
from .krx_login_lock import KRXLoginCoordinator

logger = logging.getLogger("krx_web_session")

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
LOGIN_PAGE = "https://data.krx.co.kr/contents/MDC/COMS/client/MDCCOMS001.cmd"
LOGIN_JSP = "https://data.krx.co.kr/contents/MDC/COMS/client/view/login.jsp?site=mdc"
LOGIN_URL = "https://data.krx.co.kr/contents/MDC/COMS/client/MDCCOMS001D1.cmd"

_KDM_BLOCK_MARKERS = (
    "이용 제한 안내",
    "자동화 수단을 통한 비정상 대량 조회",
    "해당 ip의 접속이 일시적으로 제한",
    "탐지일로부터 1일간 접속이 제한",
)


def is_kdm_blocked_text(text: str) -> bool:
    raw = str(text or "")
    return any(marker in raw for marker in _KDM_BLOCK_MARKERS)


class KRXWebSession:
    """싱글턴 + lazy login. 최초 데이터 요청 시점에만 로그인한다."""

    _instance: "KRXWebSession | None" = None
    _lock = threading.Lock()

    def __init__(self) -> None:
        self._session: requests.Session | None = None
        self._login_result: dict[str, Any] | None = None
        self._coordinator = KRXLoginCoordinator(
            settings.krx_login_shared_state_path_resolved,
            settings.krx_login_min_interval_sec,
        )

    @classmethod
    def instance(cls) -> "KRXWebSession":
        with cls._lock:
            if cls._instance is None:
                cls._instance = cls()
            return cls._instance

    def get_authenticated_session(self, *, force_relogin: bool = False) -> requests.Session | None:
        with self._lock:
            if force_relogin:
                self._reset()
            if self._login_result is not None:
                return self._session if self._login_result.get("status") == "ok" else None

            if not settings.krx_web_login_enabled:
                self._login_result = {"status": "skipped", "reason": "login_disabled"}
                return None
            if not settings.krx_web_id or not settings.krx_web_password:
                self._login_result = {"status": "skipped", "reason": "no_credentials"}
                return None

            self._coordinator.wait_for_turn()
            result = self._do_login(settings.krx_web_id, settings.krx_web_password)
            self._coordinator.record_attempt(status=result["status"])
            self._login_result = result
            return self._session if result.get("status") == "ok" else None

    def _reset(self) -> None:
        if self._session is not None:
            try:
                self._session.close()
            except Exception:
                pass
        self._session = None
        self._login_result = None

    def _do_login(self, krx_id: str, krx_pw: str) -> dict[str, Any]:
        max_retry = settings.krx_login_cd003_max_retry
        backoff_base = settings.krx_login_cd003_backoff_base
        for attempt in range(max_retry + 1):
            sess = requests.Session()
            try:
                sess.get(LOGIN_PAGE, headers={"User-Agent": UA}, timeout=15)
                sess.get(LOGIN_JSP, headers={"User-Agent": UA, "Referer": LOGIN_PAGE}, timeout=15)
                payload = {"mbrId": krx_id, "pw": krx_pw, "mbrNm": "", "telNo": "", "di": "", "certType": ""}
                resp = sess.post(LOGIN_URL, data=payload, headers={"User-Agent": UA, "Referer": LOGIN_PAGE}, timeout=15)
                if is_kdm_blocked_text(resp.text):
                    sess.close()
                    return {"status": "kdm_blocked", "reason": "kdm_ip_blocked"}
                code = str(resp.json().get("_error_code", "") or "-").strip().upper()

                if code == "CD011":  # 중복 로그인 -> 강제 로그인
                    payload["skipDup"] = "Y"
                    resp = sess.post(LOGIN_URL, data=payload, headers={"User-Agent": UA, "Referer": LOGIN_PAGE}, timeout=15)
                    if is_kdm_blocked_text(resp.text):
                        sess.close()
                        return {"status": "kdm_blocked", "reason": "kdm_ip_blocked"}
                    code = str(resp.json().get("_error_code", "") or "-").strip().upper()
            except Exception as exc:
                sess.close()
                return {"status": "error", "reason": f"{type(exc).__name__}:{exc}"}

            if code == "CD001":
                self._session = sess
                logger.info("[krx_web_session] KRX 로그인 성공")
                return {"status": "ok"}
            if code == "CD005":
                sess.close()
                return {"status": "login_fail_credentials", "reason": "CD005"}
            if code == "CD003" and attempt < max_retry:
                sess.close()
                delay = backoff_base * (2**attempt) + random.uniform(0.0, 0.3)
                logger.info("[krx_web_session] transient CD003, retry in %.2fs", delay)
                time.sleep(delay)
                continue
            sess.close()
            return {"status": "login_fail", "reason": f"code={code}"}
        return {"status": "login_fail", "reason": "retries_exhausted"}
