"""DailyContext(지표/피벗) -> 각 스코어러가 요구하는 *Signals 매핑.

이 파일은 의도적으로 "지저분한" 부분을 전부 모아둔다 — decision_engine.py는
이 함수들이 반환한 Signals만 조립하고, indicators/pivots를 직접 들여다보지 않는다.

**중요한 한계**: 설계서 v1.1이 "구체화"했다고 명시한 항목(9.3.1/10.1.1)은 여기서
문서 정의를 그대로 따른다. 하지만 설계서가 여전히 정성적으로만 서술한 하위 조건
(예: 14.1 "20일선/주요 지지선 부근", "조정 거래량 감소 후 반등 거래량 회복")은
합리적인 근사치로 구현했고 코드 주석에 `# 근사:`로 표시한다 — 22장 백테스트로
검증/조정이 필요한 가설값이다.
"""
from __future__ import annotations

from dataclasses import dataclass

from ..cycle.state_machine import CycleSignals
from ..divergence.bearish_divergence import DivergenceResult, PivotHighObservation, bearish_divergence
from ..domain.enums import DowState
from ..structure.dow import _last_labeled, classify_dow_state
from .add_signal import AddConfirmationSignals
from .context import DailyContext
from .late_stage import LateStageSignals
from .pullback import PullbackAdxSignals, PullbackDowSignals, PullbackMacdSignals, PullbackQualitySignals, PullbackRsiSignals
from .reversal import AdxGateSignals, ReversalDowSignals, ReversalMacdSignals, ReversalRsiSignals


@dataclass(frozen=True)
class DerivationConfig:
    """전부 config/{indicators,scoring}.yml 값으로 채워야 하는 임계값들.
    기본값은 두 yml의 현재 기본값과 맞춰뒀다."""
    right_bars: int = 2
    no_new_low_lookback: int = 5
    pullback_adx_min: float = 30.0
    late_stage_ma5_z_min: float = 1.5
    rsi_lh_streak_min_for_accumulating: int = 2
    near_prior_high_pct: float = 2.0  # 전고점 대비 이 % 이내면 "근접"
    rsi_support_band: float = 3.0     # RSI가 50 "부근"으로 볼 밴드 폭 (47~53)
    rsi_support_lookback: int = 5     # 이 기간(오늘 포함) 내 50 부근 접촉 여부를 확인


def _unconfirmed_low_price(ctx: DailyContext, right_bars: int) -> float | None:
    """아직 확정되지 않은(=우측 right_bars 대기 중인) 최근 저점 후보의 저가.
    9.3.1 조건 B(REVERSAL_CANDIDATE)에 쓰인다."""
    tail = ctx.bars["low"].iloc[-right_bars:]
    if tail.empty:
        return None
    return float(tail.min())


def _rsi_touched_50_support_recently(ctx: DailyContext, band: float, lookback: int) -> bool:
    """최근 `lookback`일(오늘 포함) 중 RSI가 50 부근(|RSI-50| <= band)을 찍은 적이 있는지.
    "50 부근 지지 후 재상승"(14.1)의 "지지" 부분 — rsi_turn_up과 AND로 묶어야
    "재상승"까지 포함된 온전한 조건이 된다(derive_pullback_signals에서 결합)."""
    window = ctx.indicators["rsi14"].iloc[-lookback:]
    if window.empty:
        return False
    return bool((window.sub(50.0).abs() <= band).any())


def _pivot_high_observations(ctx: DailyContext) -> list[PivotHighObservation]:
    """confirmed HIGH pivot마다 그 pivot_date 시점의 RSI/ADX 로컬 최댓값을 찾아 묶는다.
    ADX local max는 "이전 confirmed pivot high ~ 이번 pivot high" 구간의 최댓값(10.1.1 정의 재사용)."""
    highs = ctx.confirmed_highs
    if not highs:
        return []

    indicators = ctx.indicators
    dates = indicators["trade_date"].astype(str)
    observations: list[PivotHighObservation] = []
    prev_pivot_date: str | None = None

    for p in highs:
        rsi_row = indicators.loc[dates == p.pivot_date]
        rsi_at_pivot = float(rsi_row["rsi14"].iloc[0]) if not rsi_row.empty else float("nan")

        if prev_pivot_date is not None:
            window = indicators.loc[(dates > prev_pivot_date) & (dates <= p.pivot_date)]
            adx_local_max = float(window["adx"].max()) if not window.empty else None
        else:
            adx_local_max = None

        observations.append(PivotHighObservation(
            confirm_date=p.confirm_date, price=p.price, rsi_at_pivot=rsi_at_pivot, adx_local_max=adx_local_max,
        ))
        prev_pivot_date = p.pivot_date

    return observations


def derive_dow_state(ctx: DailyContext, cfg: DerivationConfig) -> DowState:
    unconfirmed_low = _unconfirmed_low_price(ctx, cfg.right_bars)
    latest_close = float(ctx.latest_bar["close"])
    return classify_dow_state(
        ctx.confirmed_highs, ctx.confirmed_lows, unconfirmed_low, latest_close,
    )


def derive_divergence(ctx: DailyContext) -> DivergenceResult:
    return bearish_divergence(_pivot_high_observations(ctx))


def derive_cycle_signals(ctx: DailyContext, dow_state: DowState, divergence: DivergenceResult, cfg: DerivationConfig) -> CycleSignals:
    ind = ctx.latest_indicators
    highs, lows = ctx.confirmed_highs, ctx.confirmed_lows
    last_high = highs[-1] if highs else None
    last_low = lows[-1] if lows else None
    close = float(ctx.latest_bar["close"])

    hh_hl_confirmed = bool(last_high and last_high.dow_label == "HH" and last_low and last_low.dow_label == "HL")
    hl_intact = bool(last_low and float(ctx.latest_bar["low"]) >= last_low.price)

    return CycleSignals(
        dow_state=dow_state,
        adx_falling=bool(ind["adx_falling"]), adx_flattening=bool(ind["adx_flattening"]),
        adx_turn_up=bool(ind["adx_turn_up"]), mdi_falling=bool(ind["mdi_falling"]),
        macd_above_signal=bool(ind["macd_above_signal"]), macd_above_zero=bool(ind["macd_above_zero"]),
        rsi_allowed=bool(ind["rsi_allowed"]), rsi_above_50=bool(ind["rsi_above_50"]),
        hh_hl_confirmed=hh_hl_confirmed,
        pullback_in_progress=bool(last_high and close < last_high.price),  # 근사: HH 대비 현재가 하회
        hl_intact=hl_intact,
        hl_holding_or_confirmed=hl_intact,
        adx_strong_or_rising=bool(ind["adx"] >= cfg.pullback_adx_min or ind["adx_turn_up"]),
        price_new_hh=bool(last_high and close > last_high.price),
        rsi_lh_accumulating=divergence.rsi_lh_streak >= cfg.rsi_lh_streak_min_for_accumulating,
        adx_peak_declining=bool(divergence.adx_peak_declining),
        ma5_distance_extreme=bool(ind["ma5_distance_z20"] >= cfg.late_stage_ma5_z_min) if pd_notna(ind["ma5_distance_z20"]) else False,
        lh_candidate=bool(last_high and last_high.dow_label == "LH"),
        major_hl_breached=bool(last_low and close < last_low.price),
        new_ll_confirmed=bool(last_low and last_low.dow_label == "LL"),
    )


def pd_notna(value) -> bool:
    import math
    try:
        return not math.isnan(value)
    except TypeError:
        return value is not None


def derive_reversal_dow_signals(ctx: DailyContext, dow_state: DowState, cfg: DerivationConfig) -> ReversalDowSignals:
    lows = ctx.confirmed_lows
    last_lh = _last_labeled(ctx.confirmed_highs, "LH")
    last_ll = _last_labeled(lows, "LL")
    close = float(ctx.latest_bar["close"])
    unconfirmed_low = _unconfirmed_low_price(ctx, cfg.right_bars)

    lookback = ctx.bars["low"].iloc[-(cfg.no_new_low_lookback + 1):-1]
    no_new_low = bool(not lookback.empty and float(ctx.latest_bar["low"]) > lookback.min())
    recovering = bool(float(ctx.latest_bar["close"]) > float(ctx.latest_bar["open"]))

    return ReversalDowSignals(
        breaking_downtrend=(dow_state == DowState.REVERSAL_CANDIDATE),
        last_lh_broken=bool(last_lh and close > last_lh.price),
        hl_forming=bool(last_ll and unconfirmed_low is not None and unconfirmed_low > last_ll.price),
        no_new_low_and_recovering=no_new_low and recovering,
    )


def derive_reversal_macd_signals(ctx: DailyContext) -> ReversalMacdSignals:
    ind = ctx.latest_indicators
    recent = ctx.indicators.iloc[-5:]
    return ReversalMacdSignals(
        above_signal=bool(ind["macd_above_signal"]),
        slope_3_positive=bool(ind["macd_slope_3"] > 0) if pd_notna(ind["macd_slope_3"]) else False,
        cross_up_recent=bool(recent["macd_cross_up"].any()),
    )


def derive_reversal_rsi_signals(ctx: DailyContext) -> ReversalRsiSignals:
    ind = ctx.latest_indicators
    return ReversalRsiSignals(
        above_25=bool(ind["rsi_allowed"]),
        turning_up_or_reversing=bool(ind["rsi_turn_up"]),
        higher_low_structure=bool(ind["rsi_slope_3"] > 0) if pd_notna(ind["rsi_slope_3"]) else False,  # 근사
    )


def derive_adx_gate_signals(ctx: DailyContext, dow_state: DowState, reversal_dow: ReversalDowSignals, macd: ReversalMacdSignals, rsi: ReversalRsiSignals) -> AdxGateSignals:
    ind = ctx.latest_indicators
    mdi_slope = ind["mdi_slope_3"]
    adx_slope = ind["adx_slope_3"]
    core_bullish = (dow_state != DowState.DOWNTREND) and macd.above_signal and rsi.above_25

    return AdxGateSignals(
        mdi_slope_negative=bool(pd_notna(mdi_slope) and mdi_slope < 0),
        adx_slope_negative=bool(pd_notna(adx_slope) and adx_slope < 0),
        adx_flattening=bool(ind["adx_flattening"]),
        adx_turn_up=bool(ind["adx_turn_up"]),
        core_already_bullish=core_bullish,
        mdi_rising=bool(pd_notna(mdi_slope) and mdi_slope > 0),
        adx_rising=bool(pd_notna(adx_slope) and adx_slope > 0),
        rsi_below_25=not rsi.above_25,
        dow_downtrend_no_lh_break=(dow_state == DowState.DOWNTREND and not reversal_dow.last_lh_broken),
    )


def derive_pullback_signals(
    ctx: DailyContext, cycle: CycleSignals, cfg: DerivationConfig,
) -> tuple[PullbackDowSignals, PullbackMacdSignals, PullbackRsiSignals, PullbackAdxSignals, PullbackQualitySignals]:
    ind = ctx.latest_indicators
    bars = ctx.bars
    prev_close = float(bars["close"].iloc[-2]) if len(bars) >= 2 else None
    close = float(ctx.latest_bar["close"])

    dow = PullbackDowSignals(
        uptrend_hh_hl=cycle.hh_hl_confirmed,
        hl_intact=cycle.hl_intact,
        bounced_or_broke_recent_high=bool(prev_close is not None and close > prev_close),
    )
    macd = PullbackMacdSignals(
        above_zero=bool(ind["macd_above_zero"]),
        above_signal_or_hist_rising=bool(ind["macd_above_signal"]),
    )
    rsi = PullbackRsiSignals(
        above_50=bool(ind["rsi_above_50"]),
        # "50 부근 지지"(최근 lookback일 내 |RSI-50|<=band) + "재상승"(오늘 rsi_turn_up)을
        # 둘 다 명시적으로 확인한다 — 이전엔 rsi_turn_up 단독이라 50 근처가 아니어도
        # (예: RSI 70에서 살짝 더 올라도) 참이 되는 오탐이 있었다.
        support_then_rebound=bool(ind["rsi_turn_up"]) and _rsi_touched_50_support_recently(
            ctx, cfg.rsi_support_band, cfg.rsi_support_lookback,
        ),
    )
    adx = PullbackAdxSignals(
        strong=bool(ind["adx"] >= cfg.pullback_adx_min),
        stopped_falling_or_rising=bool(ind["adx_turn_up"] or not ind["adx_falling"]),
    )
    sma20 = ind.get("sma20")
    near_support = bool(sma20 is not None and pd_notna(sma20) and abs(close / sma20 - 1.0) <= 0.02)
    vo = ind.get("volume_oscillator")
    volume_recovered = bool(vo is not None and pd_notna(vo) and vo > 0)  # 근사
    quality = PullbackQualitySignals(near_support=near_support, volume_recovered_after_dry_up=volume_recovered)

    return dow, macd, rsi, adx, quality


def derive_add_signals(ctx: DailyContext, cycle: CycleSignals, has_active_plan: bool) -> AddConfirmationSignals:
    ind = ctx.latest_indicators
    mdi_slope = ind["mdi_slope_3"]
    return AddConfirmationSignals(
        has_active_plan=has_active_plan,
        price_progressing=cycle.price_new_hh or cycle.hh_hl_confirmed,
        macd_above_signal=bool(ind["macd_above_signal"]),
        rsi_above_25=bool(ind["rsi_allowed"]),
        adx_turn_up=bool(ind["adx_turn_up"]),
        mdi_not_rising=not bool(pd_notna(mdi_slope) and mdi_slope > 0),
    )


def derive_late_stage_signals(ctx: DailyContext, divergence: DivergenceResult, cfg: DerivationConfig) -> LateStageSignals:
    ind = ctx.latest_indicators
    ma5_z = ind["ma5_distance_z20"]
    highs = ctx.confirmed_highs
    close = float(ctx.latest_bar["close"])
    near_prior_high = bool(
        highs and close >= highs[-1].price * (1 - cfg.near_prior_high_pct / 100.0)
    )
    return LateStageSignals(
        divergence=divergence,
        ma5_distance_extreme=bool(pd_notna(ma5_z) and ma5_z >= cfg.late_stage_ma5_z_min),
        near_prior_high_or_box_top=near_prior_high,
    )
