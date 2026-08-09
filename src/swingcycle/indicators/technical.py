"""기술 지표 계산. 설계: docs/SwingCycle_Radar_Source_Level_Design_v1.1.md 8장.

파일명을 `engine.py`로 하지 않은 이유: `scoring/engine.py`와 이름이 중복되는 것을
전문가 리뷰(2026-08-08)에서 지적받았기 때문 — 모듈은 각자 구체적인 이름을 쓴다.

모든 함수는 `trade_date` 오름차순으로 정렬된 DataFrame을 입력으로 받는다.
"""
from __future__ import annotations

import numpy as np
import pandas as pd


def ema(series: pd.Series, span: int) -> pd.Series:
    return series.ewm(span=span, adjust=False).mean()


def wilder_smooth(series: pd.Series, period: int) -> pd.Series:
    """Wilder smoothing — 첫 `period`개는 단순평균으로 시드하고, 이후는
    avg[t] = avg[t-1] + (value[t] - avg[t-1]) / period 로 재귀 계산한다.
    (일반 EMA(span=2*period-1)과 동일한 공식이지만, 시드 방식이 달라 첫 구간
    수치가 다르므로 반드시 이 함수로 별도 구현한다.)
    """
    values = series.to_numpy(dtype=float)
    n = len(values)
    out = np.full(n, np.nan)
    if n < period:
        return pd.Series(out, index=series.index)
    seed = np.nanmean(values[:period])
    out[period - 1] = seed
    for t in range(period, n):
        out[t] = out[t - 1] + (values[t] - out[t - 1]) / period
    return pd.Series(out, index=series.index)


def linear_slope(series: pd.Series) -> float:
    """window 구간의 단순 선형회귀 기울기. NaN이 섞여 있으면 NaN 반환."""
    values = series.to_numpy(dtype=float)
    if np.isnan(values).any() or len(values) < 2:
        return float("nan")
    x = np.arange(len(values), dtype=float)
    slope, _ = np.polyfit(x, values, 1)
    return float(slope)


def rolling_slope(series: pd.Series, window: int) -> pd.Series:
    return series.rolling(window).apply(lambda w: linear_slope(pd.Series(w)), raw=False)


def zscore(series: pd.Series, window: int) -> pd.Series:
    mean = series.rolling(window).mean()
    std = series.rolling(window).std(ddof=0)
    return (series - mean) / std.replace(0.0, np.nan)


# ── 8.1 MACD ─────────────────────────────────────────────────────────────
def compute_macd(close: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9) -> pd.DataFrame:
    macd_line = ema(close, fast) - ema(close, slow)
    signal_line = ema(macd_line, signal)
    histogram = macd_line - signal_line

    macd_above_signal = macd_line > signal_line
    macd_cross_up = (macd_line > signal_line) & (macd_line.shift(1) <= signal_line.shift(1))
    macd_above_zero = macd_line > 0
    macd_slope_3 = rolling_slope(macd_line, 3)

    return pd.DataFrame({
        "macd": macd_line,
        "macd_signal": signal_line,
        "macd_histogram": histogram,
        "macd_above_signal": macd_above_signal,
        "macd_cross_up": macd_cross_up,
        "macd_above_zero": macd_above_zero,
        "macd_slope_3": macd_slope_3,
    })


# ── 8.2 RSI ──────────────────────────────────────────────────────────────
def compute_rsi(close: pd.Series, period: int = 14, allowed_threshold: float = 25.0) -> pd.DataFrame:
    delta = close.diff()
    gain = delta.clip(lower=0.0)
    loss = (-delta).clip(lower=0.0)

    avg_gain = wilder_smooth(gain, period)
    avg_loss = wilder_smooth(loss, period)
    rs = avg_gain / avg_loss.replace(0.0, np.nan)
    rsi = 100 - 100 / (1 + rs)
    # avg_loss == 0 (연속 상승)이면 RS가 정의되지 않지만 RSI는 100이 되어야 한다.
    rsi = rsi.where(avg_loss != 0.0, 100.0)
    # avg_gain == 0 and avg_loss == 0 (완전 무변동 구간) → RS가 0/0으로 미정의.
    # 상승/하락 어느 쪽도 아니므로 중립값 50으로 둔다(위 두 줄과 순서가 중요 —
    # avg_loss==0만으로 100을 먼저 깔고, 그중 avg_gain도 0인 완전 무변동만 50으로 덮어쓴다).
    rsi = rsi.where(~((avg_gain == 0.0) & (avg_loss == 0.0)), 50.0)

    rsi_allowed = rsi > allowed_threshold
    rsi_turn_up = rsi > rsi.shift(1)
    rsi_slope_3 = rolling_slope(rsi, 3)
    rsi_above_50 = rsi > 50.0

    return pd.DataFrame({
        "rsi14": rsi,
        "rsi_allowed": rsi_allowed,
        "rsi_turn_up": rsi_turn_up,
        "rsi_slope_3": rsi_slope_3,
        "rsi_above_50": rsi_above_50,
    })


# ── 8.3 DMI/ADX ──────────────────────────────────────────────────────────
def compute_dmi_adx(
    high: pd.Series, low: pd.Series, close: pd.Series, period: int = 14,
    flat_slope_abs_max: float = 0.25, adx_slope_window: int = 3, mdi_slope_window: int = 3,
) -> pd.DataFrame:
    up_move = high.diff()
    down_move = -low.diff()

    plus_dm = np.where((up_move > down_move) & (up_move > 0), up_move, 0.0)
    minus_dm = np.where((down_move > up_move) & (down_move > 0), down_move, 0.0)
    plus_dm = pd.Series(plus_dm, index=high.index)
    minus_dm = pd.Series(minus_dm, index=high.index)

    prev_close = close.shift(1)
    tr = pd.concat([
        high - low,
        (high - prev_close).abs(),
        (low - prev_close).abs(),
    ], axis=1).max(axis=1)

    smoothed_tr = wilder_smooth(tr, period)
    plus_di = 100 * wilder_smooth(plus_dm, period) / smoothed_tr.replace(0.0, np.nan)
    minus_di = 100 * wilder_smooth(minus_dm, period) / smoothed_tr.replace(0.0, np.nan)

    di_sum = (plus_di + minus_di).replace(0.0, np.nan)
    dx = 100 * (plus_di - minus_di).abs() / di_sum
    adx = wilder_smooth(dx, period)

    adx_slope_1 = adx.diff(1)
    adx_slope_3 = rolling_slope(adx, adx_slope_window)
    mdi_slope_1 = minus_di.diff(1)
    mdi_slope_3 = rolling_slope(minus_di, mdi_slope_window)

    adx_falling = adx_slope_3 < 0
    adx_flattening = adx_slope_3.abs() <= flat_slope_abs_max
    adx_turn_up = (adx > adx.shift(1)) & (adx.shift(1) <= adx.shift(2))
    mdi_falling = mdi_slope_3 < 0

    return pd.DataFrame({
        "plus_di": plus_di,
        "minus_di": minus_di,
        "adx": adx,
        "adx_slope_1": adx_slope_1,
        "adx_slope_3": adx_slope_3,
        "mdi_slope_1": mdi_slope_1,
        "mdi_slope_3": mdi_slope_3,
        "adx_falling": adx_falling,
        "adx_flattening": adx_flattening,
        "adx_turn_up": adx_turn_up,
        "mdi_falling": mdi_falling,
    })


# ── 8.4 MA5 이격 ─────────────────────────────────────────────────────────
def compute_ma5_distance(close: pd.Series, zscore_window: int = 20) -> pd.DataFrame:
    sma5 = close.rolling(5).mean()
    ma5_distance_pct = (close / sma5 - 1.0) * 100.0
    ma5_distance_delta_1 = ma5_distance_pct.diff(1)
    ma5_distance_z20 = zscore(ma5_distance_pct, zscore_window)

    return pd.DataFrame({
        "sma5": sma5,
        "ma5_distance_pct": ma5_distance_pct,
        "ma5_distance_delta_1": ma5_distance_delta_1,
        "ma5_distance_z20": ma5_distance_z20,
    })


# ── 8.5 Volume Oscillator (관찰 필드) ────────────────────────────────────
def compute_volume_oscillator(volume: pd.Series, method: str = "sma", fast: int = 10, slow: int = 20) -> pd.Series:
    if method == "ema":
        fast_ma = ema(volume, fast)
        slow_ma = ema(volume, slow)
    else:
        fast_ma = volume.rolling(fast).mean()
        slow_ma = volume.rolling(slow).mean()
    return (fast_ma - slow_ma) / slow_ma.replace(0.0, np.nan) * 100.0


# ── 통합 ─────────────────────────────────────────────────────────────────
def compute_all_indicators(
    bars: pd.DataFrame,
    *,
    rsi_allowed_threshold: float = 25.0,
    adx_flat_slope_abs_max: float = 0.25,
    adx_slope_window: int = 3,
    mdi_slope_window: int = 3,
    ma5_zscore_window: int = 20,
    vo_method: str = "sma",
    vo_fast: int = 10,
    vo_slow: int = 20,
) -> pd.DataFrame:
    """`bars`는 trade_date 오름차순, open/high/low/close/volume 컬럼을 가진 DataFrame.
    반환값은 입력과 같은 index에 모든 지표 컬럼이 추가된 DataFrame(원본은 복사돼서 보존됨).
    """
    out = bars.copy()
    macd_df = compute_macd(out["close"])
    rsi_df = compute_rsi(out["close"], allowed_threshold=rsi_allowed_threshold)
    dmi_df = compute_dmi_adx(
        out["high"], out["low"], out["close"],
        flat_slope_abs_max=adx_flat_slope_abs_max,
        adx_slope_window=adx_slope_window, mdi_slope_window=mdi_slope_window,
    )
    ma5_df = compute_ma5_distance(out["close"], zscore_window=ma5_zscore_window)
    vo = compute_volume_oscillator(out["volume"], method=vo_method, fast=vo_fast, slow=vo_slow)

    for df in (macd_df, rsi_df, dmi_df, ma5_df):
        out = out.join(df)
    out["volume_oscillator"] = vo
    return out
