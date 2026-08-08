# SwingCycle Radar

KRX 기반 절친종목 사이클·진입점수 시스템.

- 설계 문서: [`docs/SwingCycle_Radar_Source_Level_Design_v1.1.md`](docs/SwingCycle_Radar_Source_Level_Design_v1.1.md)
- Hub 통합 설계: [`docs/SwingCycle_Radar_MoneyFlowHub_Integration_Design_v0.2.md`](docs/SwingCycle_Radar_MoneyFlowHub_Integration_Design_v0.2.md)
- `docs/` 안의 `v1.0`/`v0.1` 파일은 SUPERSEDED — 구현 기준 문서가 아니다.

## 설치

```bash
uv venv
uv pip install -e ".[dev]"
cp .env.example .env  # 값 채우기
```

## 로컬 실행

```bash
swingcycle collect --date 2026-08-08
python scripts/seed_friend_universe.py   # 최초 1회만
streamlit run webapp/app.py
```

## 디렉터리 구조

원 설계서 5장 참고. 최상위 디렉터리는 `SwingCycleRadar`가 아니라 이 저장소(`SwingCycle/`) 자체다(통합 설계서 2장).
