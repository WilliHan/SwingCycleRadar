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
    """DerivationConfig의 모든 필드를 config/{indicators,scoring}.yml에서 채운다.
    필드가 하나라도 여기 안 채워지면 YAML을 바꿔도 조용히 dataclass 기본값으로
    남는 문제가 있었다(리뷰에서 발견) — 새 필드를 추가할 땐 반드시 여기도 같이 채울 것."""
    indicators_cfg = load_yaml_config("indicators.yml")
    scoring_cfg = load_yaml_config("scoring.yml")
    pivot_cfg = indicators_cfg.get("pivot", {})
    reversal_cfg = scoring_cfg.get("reversal", {})
    pullback_cfg = scoring_cfg.get("pullback", {})
    late_stage_cfg = scoring_cfg.get("late_stage", {})

    defaults = DerivationConfig()
    return DerivationConfig(
        right_bars=pivot_cfg.get("right_bars", defaults.right_bars),
        no_new_low_lookback=reversal_cfg.get("no_new_low_lookback_days", defaults.no_new_low_lookback),
        pullback_adx_min=pullback_cfg.get("adx_min", defaults.pullback_adx_min),
        late_stage_ma5_z_min=late_stage_cfg.get("ma5_distance_z_min", defaults.late_stage_ma5_z_min),
        rsi_lh_streak_min_for_accumulating=late_stage_cfg.get("rsi_lh_streak_min", defaults.rsi_lh_streak_min_for_accumulating),
        near_prior_high_pct=late_stage_cfg.get("near_prior_high_pct", defaults.near_prior_high_pct),
        rsi_support_band=pullback_cfg.get("rsi_support_band", defaults.rsi_support_band),
        rsi_support_lookback=pullback_cfg.get("rsi_support_lookback_days", defaults.rsi_support_lookback),
    )


def _load_indicator_kwargs() -> dict:
    """compute_all_indicators() 호출 파라미터를 config/{indicators,scoring}.yml에서 채운다.
    이전엔 이 4개(+ vo 3개)가 함수 호출부에 직접 하드코딩돼 있어서, YAML의
    indicators.yml `adx_gate.*`/`volume_oscillator.*`, scoring.yml `reversal.rsi.min_entry`를
    바꿔도 실제 배치 결과가 안 바뀌는 조용한 설정 미적용 문제가 있었다(리뷰에서 발견)."""
    indicators_cfg = load_yaml_config("indicators.yml")
    scoring_cfg = load_yaml_config("scoring.yml")
    adx_gate_cfg = indicators_cfg.get("adx_gate", {})
    vo_cfg = indicators_cfg.get("volume_oscillator", {})
    rsi_cfg = scoring_cfg.get("reversal", {}).get("rsi", {})

    return {
        "rsi_allowed_threshold": rsi_cfg.get("min_entry", 25.0),
        "adx_flat_slope_abs_max": adx_gate_cfg.get("flat_slope_abs_max", 0.25),
        "adx_slope_window": adx_gate_cfg.get("adx_slope_window", 3),
        "mdi_slope_window": adx_gate_cfg.get("mdi_slope_window", 3),
        "vo_method": vo_cfg.get("method", "sma"),
        "vo_fast": vo_cfg.get("fast", 10),
        "vo_slow": vo_cfg.get("slow", 20),
    }


def _process_symbol(
    conn, symbol: str, trade_date: date, pivot_cfg: PivotConfig, deriv_cfg: DerivationConfig,
    indicator_kwargs: dict, stop_buffer_pct: float,
) -> str:
    """반환값: "processed" | "skipped_no_data" | "stopped" (daily_decide.run이 집계)."""
    bars = daily_bar_repo.fetch_bars(conn, symbol, end_date=trade_date)
    if bars.empty:
        logger.debug("[daily_decide] symbol=%s skip=no_bars", symbol)
        return "skipped_no_data"

    latest_bar = bars.iloc[-1]
    if str(latest_bar["trade_date"])[:10] != trade_date.isoformat():
        logger.debug(
            "[daily_decide] symbol=%s skip=today_bar_not_collected latest_bar_date=%s",
            symbol, str(latest_bar["trade_date"])[:10],
        )
        return "skipped_no_data"  # 오늘자 bar가 아직 수집 안 됨

    # 먼저 확인만 하고(플랜 종료/이벤트 기록은 여기서 실제로 일어남), 스코어링은 아래에서
    # 정상적으로 계속 진행한다 — STOP이 감지돼도 그날의 indicators/pivots/cycle_daily/
    # scores_daily 기록 자체는 남아야 21장 리포트가 STOP 카드를 보여줄 수 있다.
    # 17.1 "STOP이 항상 이긴다"는 원칙은 아래에서 action을 덮어쓰는 것으로 보장한다.
    stop_triggered = decision_repo.check_and_apply_stop(conn, symbol=symbol, trade_date=trade_date, bar=latest_bar)
    if stop_triggered:
        logger.warning("[daily_decide] symbol=%s STOP 감지 — 플랜 종료+이벤트 기록됨(아직 커밋 전)", symbol)

    # bar 수가 워밍업 기준(_MIN_BARS_FOR_ANALYSIS) 미만이면 지표가 대부분 NaN이라
    # 신규 ENTRY 판단용으로는 못 쓰지만, STOP이 감지된 경우는 예외다 — 신규상장 직후나
    # 수동 이관 등으로 히스토리가 짧아도 이미 ACTIVE인 플랜의 STOP은 리포트에 반드시
    # 남아야 한다(리뷰에서 발견: 이 gate가 STOP까지 걸러버려서 scores_daily가 안 남는
    # 버그가 있었음). indicators/derive_* 쪽은 짧은 데이터에도 NaN을 안전하게 다루도록
    # 이미 방어돼 있다(pd_notna 가드) — evaluate()가 낮은/0점짜리 결과를 내도 무방하다,
    # 어차피 아래에서 action은 STOP으로 덮어쓴다.
    if len(bars) < _MIN_BARS_FOR_ANALYSIS and not stop_triggered:
        logger.debug(
            "[daily_decide] symbol=%s skip=insufficient_bars bar_count=%d min=%d",
            symbol, len(bars), _MIN_BARS_FOR_ANALYSIS,
        )
        return "skipped_no_data"  # 신규상장 등 — 지표 워밍업 부족

    indicators = compute_all_indicators(bars, **indicator_kwargs)
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

    logger.debug(
        "[daily_decide] symbol=%s trade_date=%s action=%s cycle=%s dow=%s reversal=%.1f pullback=%.1f late=%.1f bar_count=%d",
        symbol, trade_date.isoformat(), decision.action.value, decision.cycle_state.value, dow_state.value,
        decision.reversal_core_score, decision.pullback_score, decision.late_stage_score, len(bars),
    )

    decision_repo.save_analysis(
        conn, decision=decision, indicators_row=ctx.latest_indicators, pivots=pivots,
        dow_state=dow_state.value, pivot_config=pivot_cfg,
    )
    return "stopped" if stop_triggered else "processed"


def run_decide(trade_date: date, force: bool = False, stop_buffer_pct: float = 1.0) -> dict:
    logger.info("[daily_decide] 시작 trade_date=%s force=%s", trade_date.isoformat(), force)
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
            logger.warning("[daily_decide] EMPTY_UNIVERSE trade_date=%s — seed_friend_universe.py 실행 여부 확인", trade_date.isoformat())
            return {"status": "EMPTY_UNIVERSE", "trade_date": trade_date.isoformat()}
        logger.info("[daily_decide] universe_size=%d", len(universe))

        pivot_cfg = _load_pivot_config()
        deriv_cfg = _load_derivation_config()
        indicator_kwargs = _load_indicator_kwargs()

        counts = {"processed": 0, "skipped_no_data": 0, "skipped_already_done": 0, "stopped": 0}
        errors: list[dict] = []

        for symbol in universe:
            try:
                if not force and decision_repo.has_scores_row(conn, symbol, trade_date):
                    counts["skipped_already_done"] += 1
                    continue
                # _process_symbol 안의 check_and_apply_stop/save_analysis는 전부 commit을
                # 안 하는 계약이다(repo 모듈 docstring 참고) — 여기서 한 종목의 하루치 작업을
                # 통째로 하나의 트랜잭션으로 묶는다. 중간에 예외가 나면 rollback해서 "플랜은
                # STOP으로 닫혔는데 그날 분석 결과는 없는" 부분 반영 상태를 방지한다 —
                # 그래야 재실행 시 플랜이 여전히 ACTIVE라 STOP이 다시 정상 감지된다.
                outcome = _process_symbol(conn, symbol, trade_date, pivot_cfg, deriv_cfg, indicator_kwargs, stop_buffer_pct)
                conn.commit()
                counts[outcome] = counts.get(outcome, 0) + 1
            except Exception as exc:  # noqa: BLE001 — 종목 하나 실패가 나머지를 막으면 안 됨
                conn.rollback()
                logger.exception("[daily_decide] symbol=%s 처리 실패 — 롤백됨(플랜/이벤트/scores 전부 미반영)", symbol)
                errors.append({"symbol": symbol, "error": str(exc)})

        logger.info(
            "[daily_decide] 종료 trade_date=%s processed=%d stopped=%d skipped_no_data=%d skipped_already_done=%d errors=%d",
            trade_date.isoformat(), counts["processed"], counts["stopped"],
            counts["skipped_no_data"], counts["skipped_already_done"], len(errors),
        )
        return {
            "status": "OK", "trade_date": trade_date.isoformat(),
            **counts, "errors": errors,
        }
    finally:
        conn.close()
