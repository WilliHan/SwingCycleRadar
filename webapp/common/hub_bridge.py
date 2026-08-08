"""Hub 신원 확인 브리지.

설계: docs/SwingCycle_Radar_MoneyFlowHub_Integration_Design_v0.2.md 4.4

- 운영: nginx가 /scr/ auth_request 통과 후 X-Hub-User-Email 헤더를 지우고 재주입하므로
  이 헤더를 그대로 신뢰한다 (8505 포트가 외부에 직접 노출되지 않는다는 전제).
- 로컬 dev: dev_server.py가 프록시가 아니라 302 리다이렉트라 헤더가 주입되지 않는다.
  대신 브라우저가 보낸 hub_token 쿠키를 MFGR /hub/auth/me 에 그대로 전달해
  서버사이드로 신원을 확인한다.
"""
from __future__ import annotations

import os
from dataclasses import dataclass

import requests
import streamlit as st

MFGR_URL = os.getenv("MFGR_URL", "http://localhost:8503")
IS_PRODUCTION = os.getenv("ENV", "local") == "production"


@dataclass(frozen=True)
class HubIdentity:
    email: str
    source: str  # "nginx_header" | "dev_cookie_bridge"


def resolve_hub_identity() -> HubIdentity | None:
    headers = st.context.headers or {}
    email = headers.get("X-Hub-User-Email")
    if email:
        return HubIdentity(email=email, source="nginx_header")

    if IS_PRODUCTION:
        # 운영에서는 쿠키 브리지 경로를 열지 않는다 — nginx 헤더만 신뢰 (위조 방지).
        return None

    cookies = st.context.cookies or {}
    hub_token = cookies.get("hub_token")
    if not hub_token:
        return None

    try:
        resp = requests.get(f"{MFGR_URL}/hub/auth/me", cookies={"hub_token": hub_token}, timeout=3)
        if resp.status_code == 200:
            return HubIdentity(email=resp.json()["email"], source="dev_cookie_bridge")
    except requests.RequestException:
        pass
    return None
