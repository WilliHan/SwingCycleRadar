"""KRX Primary Adapter — krx_direct(웹 세션) 기반 시장 전체 일별매매정보 수집.

sugup-report의 src/sugup_pivot/collectors/krx_direct.py를 참조해 SwingCycle Radar
저장소 안으로 이식한 독립 구현이다(공용 import 금지, 통합 설계서 1.1항).

설계: docs/SwingCycle_Radar_Source_Level_Design_v1.1.md 6.4
"""
from __future__ import annotations

import hashlib
import json
from datetime import date
from typing import Any

import pandas as pd
import requests

from ..domain.models import KRXResponse
from ..settings import load_yaml_config, settings
from .krx_web_session import KRXWebSession, is_kdm_blocked_text


class KRXDirectError(RuntimeError):
    def __init__(self, message: str, *, error_code: str | None = None) -> None:
        super().__init__(message)
        self.error_code = error_code


def _market_to_mkt_id(market: str) -> str:
    key = market.upper()
    if key == "KOSPI":
        return "STK"
    if key == "KOSDAQ":
        return "KSQ"
    if key == "ALL":
        return "ALL"
    raise ValueError(f"unsupported market: {market}")


def _make_headers() -> dict[str, str]:
    return {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/122.0.0.0 Safari/537.36",
        "Accept": "*/*",
        "Origin": "https://data.krx.co.kr",
        "Connection": "keep-alive",
    }


def _ajax_headers(referer: str) -> dict[str, str]:
    headers = _make_headers()
    headers.update({
        "Referer": referer,
        "X-Requested-With": "XMLHttpRequest",
        "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
    })
    return headers


class KRXClient:
    """설계서 6.4 인터페이스. 내부 구현은 krx_direct."""

    def __init__(self, timeout: float | None = None) -> None:
        self._cfg = load_yaml_config("markets.yml")["krx_direct"]
        self.timeout = timeout or settings.http_timeout_sec

    def _get_authenticated_session(self, *, force_relogin: bool = False) -> requests.Session:
        session = KRXWebSession.instance().get_authenticated_session(force_relogin=force_relogin)
        return session if session is not None else requests.Session()

    def _is_blocked_response(self, text: str) -> bool:
        markers = self._cfg.get("kdm_block_markers") or []
        raw = str(text or "")
        return is_kdm_blocked_text(raw) or any(m in raw for m in markers)

    def fetch_daily_market(self, market: str, trade_date: date) -> KRXResponse:
        """시장 전체 일별매매정보를 1회 호출해 반환한다."""
        session = self._get_authenticated_session()
        mkt_id = _market_to_mkt_id(market)
        trd_dd = trade_date.strftime(self._cfg["request"]["date_format"])
        referer = f"{self._cfg['home_url']}?menuId={self._cfg['menu_id']}"

        payload = {
            "locale": "ko_KR",
            "mktId": mkt_id,
            "trdDd": trd_dd,
            "share": "1",
            "money": "1",
            "csvxls_isNo": "false",
            "bld": self._cfg["stat_bld"],
            "mnuId": self._cfg["menu_id"],
        }
        resp = session.post(self._cfg["json_url"], data=payload, headers=_ajax_headers(referer), timeout=self.timeout)
        text_head = (resp.text or "")[:200]
        if resp.status_code >= 400 or self._is_blocked_response(resp.text or ""):
            raise KRXDirectError(
                f"krx_direct rejected status={resp.status_code} head={text_head}",
                error_code="KDM_IP_BLOCKED" if self._is_blocked_response(resp.text or "") else "HTTP_ERROR",
            )

        try:
            data: dict[str, Any] = resp.json()
        except json.JSONDecodeError as exc:
            raise KRXDirectError(f"json decode failed: {exc}", error_code="JSON_DECODE_FAIL") from exc

        raw_rows: list[dict[str, Any]] = []
        for key in self._cfg["response"]["output_key_candidates"]:
            val = data.get(key)
            if isinstance(val, list):
                raw_rows = val
                break

        raw_hash = hashlib.sha256(resp.content).hexdigest()
        return KRXResponse(
            market=market,
            trade_date=trade_date,
            rows=raw_rows,
            raw_hash=raw_hash,
            endpoint=self._cfg["json_url"],
            source_mode="krx_direct",
        )


_KEY_MAP = {
    "ISU_SRT_CD": "symbol",
    "ISU_ABBRV": "name",
    "TDD_OPNPRC": "open",
    "TDD_HGPRC": "high",
    "TDD_LWPRC": "low",
    "TDD_CLSPRC": "close",
    "ACC_TRDVAL": "trade_value",
    "ACC_TRDVOL": "volume",
    "MKTCAP": "market_cap",
}


def _clean_numeric(series: pd.Series) -> pd.Series:
    return pd.to_numeric(series.astype(str).str.replace(",", "", regex=False), errors="coerce")


def krx_response_to_dataframe(response: KRXResponse) -> pd.DataFrame:
    """KRXResponse.rows(원본 dict 목록)를 정규화된 DataFrame으로 변환한다 (6.6 정규화 필드 일부)."""
    if not response.rows:
        return pd.DataFrame()
    df = pd.DataFrame(response.rows)
    rename_map = {src: dst for src, dst in _KEY_MAP.items() if src in df.columns}
    work = df.rename(columns=rename_map)
    for col in ("open", "high", "low", "close", "trade_value", "volume", "market_cap"):
        if col in work.columns:
            work[col] = _clean_numeric(work[col])
    if "symbol" in work.columns:
        work["symbol"] = work["symbol"].astype(str).str.strip().str.zfill(6)
    work["market"] = response.market
    work["trade_date"] = response.trade_date.isoformat()
    work["source"] = "KRX_DIRECT"
    work["source_raw_hash"] = response.raw_hash
    return work
