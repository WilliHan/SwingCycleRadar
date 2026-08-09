"""jobs/daily_decide.py의 config 로딩 함수 테스트.

리뷰에서 발견된 문제: DerivationConfig/compute_all_indicators 파라미터 중 일부가
config/*.yml 값을 읽지 않고 조용히 dataclass/함수 기본값으로 남아있었다. 이 테스트는
YAML 내용을 바꾸면 실제로 로더의 반환값도 바뀌는지 직접 확인한다(load_yaml_config를
가짜로 바꿔치기해서 실제 파일에 의존하지 않고 격리 검증).
"""
from __future__ import annotations

import swingcycle.jobs.daily_decide as daily_decide_module


def test_load_derivation_config_reads_every_field(monkeypatch):
    fake_indicators = {"pivot": {"right_bars": 9}}
    fake_scoring = {
        "reversal": {"no_new_low_lookback_days": 7},
        "pullback": {"adx_min": 40.0, "rsi_support_band": 5.0, "rsi_support_lookback_days": 8},
        "late_stage": {"ma5_distance_z_min": 2.5, "rsi_lh_streak_min": 3, "near_prior_high_pct": 4.0},
    }

    def fake_load_yaml_config(name: str) -> dict:
        return fake_indicators if name == "indicators.yml" else fake_scoring

    monkeypatch.setattr(daily_decide_module, "load_yaml_config", fake_load_yaml_config)

    cfg = daily_decide_module._load_derivation_config()

    assert cfg.right_bars == 9
    assert cfg.no_new_low_lookback == 7
    assert cfg.pullback_adx_min == 40.0
    assert cfg.late_stage_ma5_z_min == 2.5
    assert cfg.rsi_lh_streak_min_for_accumulating == 3
    assert cfg.near_prior_high_pct == 4.0
    assert cfg.rsi_support_band == 5.0
    assert cfg.rsi_support_lookback == 8


def test_load_derivation_config_falls_back_to_defaults_when_yaml_empty(monkeypatch):
    monkeypatch.setattr(daily_decide_module, "load_yaml_config", lambda name: {})
    from swingcycle.scoring.signal_derivation import DerivationConfig

    cfg = daily_decide_module._load_derivation_config()
    assert cfg == DerivationConfig()


def test_load_indicator_kwargs_reads_every_field(monkeypatch):
    fake_indicators = {
        "adx_gate": {"flat_slope_abs_max": 0.5, "adx_slope_window": 5, "mdi_slope_window": 6},
        "volume_oscillator": {"method": "ema", "fast": 12, "slow": 26},
    }
    fake_scoring = {"reversal": {"rsi": {"min_entry": 30.0}}}

    def fake_load_yaml_config(name: str) -> dict:
        return fake_indicators if name == "indicators.yml" else fake_scoring

    monkeypatch.setattr(daily_decide_module, "load_yaml_config", fake_load_yaml_config)

    kwargs = daily_decide_module._load_indicator_kwargs()

    assert kwargs == {
        "rsi_allowed_threshold": 30.0,
        "adx_flat_slope_abs_max": 0.5,
        "adx_slope_window": 5,
        "mdi_slope_window": 6,
        "vo_method": "ema",
        "vo_fast": 12,
        "vo_slow": 26,
    }


def test_load_indicator_kwargs_matches_compute_all_indicators_signature(monkeypatch):
    """반환된 dict의 키가 전부 compute_all_indicators()가 실제로 받는 파라미터명과
    일치하는지 확인 — 이름이 어긋나면 TypeError로 바로 드러나야 한다(조용한 무시 방지)."""
    from swingcycle.indicators.technical import compute_all_indicators

    monkeypatch.setattr(daily_decide_module, "load_yaml_config", lambda name: {})
    kwargs = daily_decide_module._load_indicator_kwargs()

    import inspect
    sig = inspect.signature(compute_all_indicators)
    for key in kwargs:
        assert key in sig.parameters, f"{key} 는 compute_all_indicators()에 없는 파라미터"
