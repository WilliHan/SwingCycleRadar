"""swingcycle decide — 설계서 17장/20장 2단계. daily_collect.py 다음 단계로 실행한다.

daily_collect.py가 이미 upsert해둔 daily_bars를 읽기만 한다 — 이 잡은 수집을 하지
않는다(수집/분석 단계 분리로 둘을 독립적으로 재실행할 수 있게 한다, 사용자 권장 순서 1번).

종목+날짜 단위로 idempotent하다: scores_daily에 이미 해당 (trade_date, symbol) 행이
있으면 기본적으로 건너뛴다(`force=True`면 재처리, 그래도 trade_events 중복은 나지
않는다 — decision_repo/risk.reset 쪽에서 이미 보장).
"""
from __future__ import annotations

import logging
from dataclasses import replace
from datetime import date

from ..domain.enums import Action

from ..data.trading_calendar import NoTradingDayError, ensure_trading_day
from ..indicators.technical import compute_all_indicators
from ..repositories import daily_bar_repo, decision_repo, symbol_repo
from ..repositories.db import get_connection, run_migrations
from ..scoring.context import DailyContext
from ..scoring.decision_engine import evaluate
from ..scoring.signal_derivation import DerivationConfig, derive_dow_state
from ..settings import load_yaml_config
from ..structure.pivots import PivotConfig, detect_and_label_pivots

logger = logging.getLogger("daily_decide")

_MIN_BARS_FOR_ANALYSIS = 30  # RSI14/ADX14 등이 워밍업을 마쳤다고 볼 최소 바 수


def _load_pivot_config() -> PivotConfig:
    cfg = load_yaml_config("indicators.yml").get("pivot", {})
    return PivotConfig(
        left_bars=cfg.get("left_bars", 2), right_bars=cfg.get("right_bars", 2),
        price_mode=cfg.get("price_mode", "wick"),
        pivot_equal_tolerance_pct=cfg.get("pivot_equal_tolerance_pct", 0.20),
    )


def _load_derivation_config() -> DerivationConfig:
    indicators_cfg = load_yaml_config("indicators.yml")
    scoring_cfg = load_yaml_config("scoring.yml")
    return DerivationConfig(
        right_bars=indicators_cfg.get("pivot", {}).get("right_bars", 2),
        pullback_adx_min=scoring_cfg.get("pullback", {}).get("adx_min", 30.0),
        late_stage_ma5_z_min=scoring_cfg.get("late_stage", {}).get("ma5_distance_z_min", 1.5),
    )


def _process_symbol(conn, symbol: str, trade_date: date, pivot_cfg: PivotConfig, deriv_cfg: DerivationConfig, stop_buffer_pct: float) -> str:
    """반환값: "processed" | "skipped_no_data" | "stopped" | "error:<msg>" (daily_decide.run이 집계)."""
    bars = daily_bar_repo.fetch_bars(conn, symbol, end_date=trade_date)
    if bars.empty:
        return "skipped_no_data"

    latest_bar = bars.iloc[-1]
    if str(latest_bar["trade_date"])[:10] != trade_date.isoformat():
        return "skipped_no_data"  # 오늘자 bar가 아직 수집 안 됨

    # 먼저 확인만 하고(플랜 종료/이벤트 기록은 여기서 실제로 일어남), 스코어링은 아래에서
    # 정상적으로 계속 진행한다 — STOP이 감지돼도 그날의 indicators/pivots/cycle_daily/
    # scores_daily 기록 자체는 남아야 21장 리포트가 STOP 카드를 보여줄 수 있다.
    # 17.1 "STOP이 항상 이긴다"는 원칙은 아래에서 action을 덮어쓰는 것으로 보장한다.
    stop_triggered = decision_repo.check_and_apply_stop(conn, symbol=symbol, trade_date=trade_date, bar=latest_bar)

    if len(bars) < _MIN_BARS_FOR_ANALYSIS:
        return "stopped" if stop_triggered else "skipped_no_data"  # 신규상장 등 — 지표 워밍업 부족

    indicators = compute_all_indicators(
        bars,
        rsi_allowed_threshold=25.0,
        adx_flat_slope_abs_max=0.25, adx_slope_window=3, mdi_slope_window=3,
    )
    pivots = detect_and_label_pivots(bars, pivot_cfg)
    ctx = DailyContext(symbol=symbol, trade_date=trade_date, bars=bars, indicators=indicators, pivots=pivots)

    symbol_row = symbol_repo.get_symbol(conn, symbol)
    name = symbol_row["name"] if symbol_row else symbol
    friend_group = symbol_row["friend_group"] if symbol_row else None

    prior_cycle_state = decision_repo.get_prior_cycle_state(conn, symbol, trade_date)
    has_active_plan = symbol_repo.has_active_trade_plan(conn, symbol)

    decision = evaluate(
        ctx, name=name, friend_group=friend_group,
        prior_cycle_state=prior_cycle_state, has_active_plan=has_active_plan,
        cfg=deriv_cfg, stop_buffer_pct=stop_buffer_pct,
    )
    if stop_triggered:
        # 17.1 — STOP은 항상 최우선. has_active_plan은 check_and_apply_stop이 이미 플랜을
        # STOPPED로 닫은 *뒤*의 값이라 여기선 신규 ENTRY 판단에 영향 없이 action만 덮어쓴다.
        decision = replace(decision, action=Action.STOP, stop_price=None, entry_type=None)

    dow_state = derive_dow_state(ctx, deriv_cfg)

    decision_repo.save_analysis(
        conn, decision=decision, indicators_row=ctx.latest_indicators, pivots=pivots,
        dow_state=dow_state.value, pivot_config=pivot_cfg,
    )
    return "stopped" if stop_triggered else "processed"


def run_decide(trade_date: date, force: bool = False, stop_buffer_pct: float = 1.0) -> dict:
    run_migrations()
    conn = get_connection()
    try:
        try:
            ensure_trading_day(trade_date)
        except NoTradingDayError as exc:
            logger.info("[daily_decide] %s", exc)
            return {"status": "NO_TRADING_DAY", "trade_date": trade_date.isoformat()}

        universe = symbol_repo.collectable_symbols(conn)
        if not universe:
            return {"status": "EMPTY_UNIVERSE", "trade_date": trade_date.isoformat()}

        pivot_cfg = _load_pivot_config()
        deriv_cfg = _load_derivation_config()

        counts = {"processed": 0, "skipped_no_data": 0, "skipped_already_done": 0, "stopped": 0}
        errors: list[dict] = []

        for symbol in universe:
            try:
                if not force and decision_repo.has_scores_row(conn, symbol, trade_date):
                    counts["skipped_already_done"] += 1
                    continue
                outcome = _process_symbol(conn, symbol, trade_date, pivot_cfg, deriv_cfg, stop_buffer_pct)
                counts[outcome] = counts.get(outcome, 0) + 1
            except Exception as exc:  # noqa: BLE001 — 종목 하나 실패가 나머지를 막으면 안 됨
                logger.exception("[daily_decide] symbol=%s 처리 실패", symbol)
                errors.append({"symbol": symbol, "error": str(exc)})

        return {
            "status": "OK", "trade_date": trade_date.isoformat(),
            **counts, "errors": errors,
        }
    finally:
        conn.close()
