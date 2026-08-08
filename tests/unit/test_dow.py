from swingcycle.domain.enums import DowState
from swingcycle.structure.dow import DowStateConfig, Pivot, classify_dow_state


def test_downtrend_requires_confirm_run_on_both_sides():
    highs = [Pivot("d1", "LH", 100), Pivot("d2", "LH", 95)]
    lows = [Pivot("d1", "LL", 80), Pivot("d2", "LL", 75)]
    assert classify_dow_state(highs, lows, None, 90) == DowState.DOWNTREND


def test_uptrend_needs_only_latest_pair_by_default_config():
    highs = [Pivot("d1", "LH", 90), Pivot("d2", "HH", 110)]
    lows = [Pivot("d1", "LL", 70), Pivot("d2", "HL", 85)]
    assert classify_dow_state(highs, lows, None, 111) == DowState.UPTREND


def test_reversal_candidate_compares_against_last_LH_not_last_pivot():
    """전문가 리뷰에서 발견한 버그의 회귀 테스트.

    last_highs[-1]은 이미 HH(=100, 돌파된 새 고점)이고, 진짜 저항선이었던
    마지막 LH는 그 앞의 90이다. 저점은 아직 HL로 확정되지 않아 UPTREND는
    아니다. 종가 95는 예전 LH(90)는 넘었지만 새 HH(100)는 못 넘었다.

    버그 버전(last_highs[-1]을 "마지막 LH"로 오인)은 95 > 100 이 False라서
    REVERSAL_CANDIDATE를 놓친다. 수정 버전은 _last_labeled로 진짜 LH(90)를
    찾아 95 > 90 이 True이므로 REVERSAL_CANDIDATE를 정확히 반환해야 한다.
    """
    highs = [Pivot("d0", "LH", 90), Pivot("d1", "HH", 100)]
    lows = [Pivot("d0", "LL", 70), Pivot("d1", "LL", 65)]  # 아직 HL 없음 -> UPTREND 아님

    result = classify_dow_state(highs, lows, unconfirmed_low_price=None, latest_close=95)

    assert result == DowState.REVERSAL_CANDIDATE


def test_default_is_range_when_no_pivots_yet():
    assert classify_dow_state([], [], None, 100) == DowState.RANGE


def test_default_is_range_when_nothing_matches():
    # last_highs[-1]=EH(동일가), last_lows[-1]=EL -> UPTREND/DOWNTREND 라벨 조건 불충족,
    # LH/LL도 못 찾으므로 REVERSAL_CANDIDATE도 아님 -> 명시적 default RANGE
    highs = [Pivot("d1", "EH", 100)]
    lows = [Pivot("d1", "EL", 90)]
    assert classify_dow_state(highs, lows, None, 95) == DowState.RANGE
