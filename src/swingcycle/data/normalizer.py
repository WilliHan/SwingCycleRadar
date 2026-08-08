"""정규화 검증 규칙. 설계: docs/SwingCycle_Radar_Source_Level_Design_v1.1.md 6.6"""
from __future__ import annotations

import pandas as pd


class NormalizationError(ValueError):
    pass


def validate_daily_bars(df: pd.DataFrame) -> pd.DataFrame:
    """OHLC 불변식을 검증한다. 위반 row는 예외 대신 별도 로그 후 제외한다(거래정지 등 특수상황 존재)."""
    if df.empty:
        return df

    valid = (
        (df["low"] <= df["open"])
        & (df["open"] <= df["high"])
        & (df["low"] <= df["close"])
        & (df["close"] <= df["high"])
        & (df["volume"] >= 0)
        & (df["close"] > 0)
    )
    if "trade_value" in df.columns:
        valid &= df["trade_value"].isna() | (df["trade_value"] >= 0)

    invalid_count = int((~valid).sum())
    if invalid_count:
        import logging

        logging.getLogger("normalizer").warning(
            "[normalizer] OHLC 불변식 위반 %d건 제외 (거래정지/특수상황 가능)", invalid_count
        )
    return df[valid].reset_index(drop=True)
