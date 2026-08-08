"""프로세스/서비스 간 KRX 로그인 조율.

설계: docs/SwingCycle_Radar_Source_Level_Design_v1.1.md 6.1.1

sugup-report와 SwingCycle Radar가 같은 서버에서 각자 KRX 웹 로그인을 수행하면
로그인 빈도가 합산되어 자동화 탐지(IP 차단) 위험이 커진다(2026-08-04 sugup-report
실제 장애). 이 모듈은 로그인 "시도 빈도"만 조율한다 — 세션 자체는 공유하지 않는다
(서비스 간 코드/세션 비공유 원칙, 통합 설계서 1.1항).
"""
from __future__ import annotations

import fcntl
import json
import logging
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger("krx_login_lock")

_LOCK_ACQUIRE_TIMEOUT_SEC = 5.0
SERVICE_NAME = "scr"


def _now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat()


def _read_state(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return {}


def _write_state(path: Path, state: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)


class KRXLoginCoordinator:
    """공유 상태 파일 + flock 기반 로그인 빈도 조율.

    사용법::

        coordinator = KRXLoginCoordinator(state_path, min_interval_sec=300)
        coordinator.wait_for_turn()   # 필요시 대기
        result = do_login(...)
        coordinator.record_attempt(status="ok" if result else "fail")
    """

    def __init__(self, state_path: Path, min_interval_sec: int) -> None:
        self.state_path = state_path
        self.min_interval_sec = min_interval_sec

    def _with_lock(self, fn):
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        lock_path = self.state_path.with_suffix(".lock")
        try:
            with open(lock_path, "w") as lock_file:
                start = time.monotonic()
                while True:
                    try:
                        fcntl.flock(lock_file, fcntl.LOCK_EX | fcntl.LOCK_NB)
                        break
                    except BlockingIOError:
                        if time.monotonic() - start > _LOCK_ACQUIRE_TIMEOUT_SEC:
                            logger.warning(
                                "[krx_login_lock] lock 획득 실패(%.1fs 초과) — 조율 없이 진행",
                                _LOCK_ACQUIRE_TIMEOUT_SEC,
                            )
                            return fn(coordinated=False)
                        time.sleep(0.1)
                try:
                    return fn(coordinated=True)
                finally:
                    fcntl.flock(lock_file, fcntl.LOCK_UN)
        except OSError as exc:
            logger.warning("[krx_login_lock] lock 파일 접근 실패(%s) — 조율 없이 진행", exc)
            return fn(coordinated=False)

    def wait_for_turn(self) -> None:
        """다른 서비스가 최소 간격 이내에 로그인했다면 잔여 시간만큼 대기."""

        def _check(coordinated: bool) -> None:
            state = _read_state(self.state_path)
            last_at = state.get("last_login_at")
            last_status = state.get("last_login_status")
            if not (coordinated and last_at and last_status == "ok"):
                return
            try:
                last_dt = datetime.fromisoformat(last_at)
            except ValueError:
                return
            elapsed = (datetime.now(timezone.utc).astimezone() - last_dt).total_seconds()
            remaining = self.min_interval_sec - elapsed
            if remaining > 0:
                logger.info(
                    "[krx_login_lock] 최근 로그인(%s, %s) 후 %.0f초 미경과 — %.0f초 대기",
                    state.get("last_login_service"), last_at, elapsed, remaining,
                )
                time.sleep(min(remaining, self.min_interval_sec))

        self._with_lock(_check)

    def record_attempt(self, *, status: str) -> None:
        def _write(coordinated: bool) -> None:
            _write_state(
                self.state_path,
                {
                    "last_login_at": _now_iso(),
                    "last_login_service": SERVICE_NAME,
                    "last_login_status": status,
                },
            )

        self._with_lock(_write)
