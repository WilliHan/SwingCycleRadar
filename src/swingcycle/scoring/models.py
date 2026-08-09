"""점수 모델 공용 타입. 설계: 11장, 28장, 29장(Reason Code)."""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class ScorePart:
    """개별 배점 항목 하나의 결과 — 사람이 신뢰할 수 있도록 항상 reason code를 동반한다(29장)."""
    points: float
    max_points: float
    reasons: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class ScoreResult:
    """여러 ScorePart를 합산한 최종 점수. reasons는 모든 파트의 reason을 순서대로 이어붙인다."""
    total: float
    max_total: float
    parts: dict[str, ScorePart]

    @property
    def reasons(self) -> list[str]:
        out: list[str] = []
        for part in self.parts.values():
            out.extend(part.reasons)
        return out
