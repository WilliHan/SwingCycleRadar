# SwingCycle Radar

## KRX 기반 절친종목 사이클·진입점수 시스템 소스 레벨 상세 설계서 v1.1

* 작성 기준일: 2026-08-08 (v1.0) / 개정: 2026-08-08 (v1.1)
* 목적: 절친 종목(universe)을 미리 선정해두고, **좋은 종목을 다시 고르는 것이 아니라 좋은 진입 시점과 사이클을 자동 판정**한다.
* 1차 데이터 소스: **KRX 웹 세션 기반 직접 수집 (krx_direct)** — v1.0의 "KRX Data Marketplace OPEN API(AUTH_KEY)" 가정을 대체함 (6장 참고, 사유는 v1.1 변경 이력 참고)
* 2차 백업 데이터 소스: **pykrx**
* 운용 주기: 일봉 EOD 기준
* 핵심 철학: **가격(다우) -> MACD -> RSI -> ADX/MDI 최종 확인 -> 분할진입 -> 손절/RESET -> 재평가**
* 범위: 스캐닝/점수/상태/리포트/백테스트/검증까지. 실제 증권사 주문 연동은 v1 범위 밖.

### v1.1 변경 이력 (v1.0 대비)

MoneyFlow Hub 통합 설계 검토 과정에서 발견된 전략 엔진 공백을 닫기 위한 개정. 코드는 아직 없으므로 하위호환 이슈 없음.

| # | 변경 항목 | v1.0 문제 | v1.1 조치 | 위치 |
|---|---|---|---|---|
| 1 | KRX 연동 방식 | Open API Marketplace(AUTH_KEY, 미승인 상태, `TBD_FROM_KRX_SPEC` 플레이스홀더)와, 통합 설계서가 전제한 `sugup-report`의 실제 작동 방식(웹 로그인 세션)이 서로 다른 두 방식을 동시에 가리켜 충돌 | `krx_direct`(웹 세션 기반) 를 1차로 확정, Open API Marketplace 경로는 승인 완료 시 대체 어댑터로만 남김 | 6장 전체 재작성 |
| 2 | Pullback Entry 액션 결정 | 배점만 있고 Reversal Entry(12.5)처럼 score→action 매핑이 없음, ADX Gate 적용 여부 불명확 | 14.2 신설 — 임계값/게이트 상호작용 명문화 | 14.2 |
| 3 | Dow/Cycle 상태 전이 | "반복", "의미 있는 LH" 등 정성적 서술만 존재 | 구체적 window/count 파라미터로 재정의 | 9.3, 10.1 |
| 4 | ADX/MDI Gate 미정의 분기 | "MDI 상승 + ADX 하락" 케이스가 PASS/CAUTION/BLOCK 어디에도 안 걸림 | 명시적 default(CAUTION) 규칙 추가 | 12.4 |
| 5 | trade_plans 활성 플랜 제약 | 종목당 ACTIVE 플랜 1개 제약이 DB 레벨에 없음 | 부분 유니크 인덱스 추가 | 7.7 |

**v1.1 후속 수정 (같은 날, 교차 일관성 리뷰 반영):**

| # | 문제 | 조치 | 위치 |
|---|---|---|---|
| 6 | `symbols.market NOT NULL`이 Supabase의 nullable 시드 방식과 충돌 — 첫 동기화에서 insert 실패 | `market` NOT NULL 제거 + 역보정 규칙 추가 | 7.1, 6.6 |
| 7 | 3장 아키텍처 다이어그램이 여전히 `KRX Open API`/`config/friend_universe.yml`을 운영 입력처럼 표기 | 다이어그램을 KRX Direct/Supabase 기준으로 수정 | 3장 |
| 8 | 18장이 YAML을 운영 설정처럼 서술 | "최초 시드 전용" 명시, Supabase가 운영 source of truth임을 명문화 | 18장 |
| 9 | KRX 로그인 조율이 "필요하다"는 원칙 수준에 머묾 | 공유 상태 파일 경로/락 방식/최소 간격/장애 시 동작까지 구체 규격화 | 6.1.1 신설 |

\---



* 파일 이름은 일반적인 이름이 아니고, 각 기능과 역할에 맞도록 파일 이름을 생성한다.
* 절친 종목 등 관리가 필요한 항목(유니버스 마스터 데이터)은 Supabase DB에 관리한다. 시세/지표/점수/트레이드 데이터는 7장의 SQLite 설계를 그대로 따른다 (2-DB 구조 — 상세는 `SwingCycle_Radar_MoneyFlowHub_Integration_Design_v0.2.md` 5장 참고).



# 1\. 프로젝트 목표와 비목표

## 1.1 목표

1. KRX에서 절친 종목의 일별 OHLCV를 안정적으로 수집한다.
2. 가격 변곡점과 다우 구조(HH/HL/LH/LL)를 **미래 데이터 누출 없이** 계산한다.
3. MACD, RSI, ADX, -DI(MDI)를 동일 계산 규칙으로 산출한다.
4. 각 종목을 `DOWNTREND -> BOTTOMING -> REVERSAL -> UPTREND -> PULLBACK -> REACCELERATION -> LATE\_STAGE -> DOWNTREND` 상태로 분류한다.
5. 초기 반전 진입과 상승추세 눌림 재진입을 **서로 다른 점수 모델**로 관리한다.
6. ADX를 주 진입신호로 쓰지 않고 **최종 ON/OFF 확인 및 진입 후 비중확대 확인**에 사용한다.
7. 손절이 발생하면 해당 트레이드만 종료하고 `RESET`하여 동일 종목을 처음부터 재평가한다.
8. 매일 `READY/ENTRY/ADD/TAKE\_PROFIT/EXIT/RESET` 후보를 생성한다.
9. 과거 데이터로 성공/실패 사례를 재현하고, 룰별 성과와 오류를 검증한다.
10. 이후 Codex가 바로 구현할 수 있도록 모듈/함수/DB/CLI/테스트 수준까지 규정한다.

## 1.2 비목표

* v1에서 뉴스·실적·수급으로 종목을 새로 선정하지 않는다.
* v1에서 초단타/분봉 자동매매를 지원하지 않는다.
* v1에서 증권사 주문 API를 직접 호출하지 않는다.
* v1에서 머신러닝으로 점수를 학습하지 않는다. 먼저 규칙 기반 시스템을 안정화한다.
* PDI(+DI)는 기본 차트/UI에 표시하지 않는다. 필요 시 디버그 필드로 계산 가능하게만 둔다.
* V.O(Volume Oscillator)는 v1 핵심 점수에서 제외하고 관찰 필드로만 저장한다.

\---

# 2\. 핵심 매매 철학을 시스템 규칙으로 변환

## 2.1 최상위 우선순위

```text
종목선정(절친 Universe)
    -> 가격구조(다우)
    -> MACD 방향
    -> RSI 과매도 탈출/반전
    -> ADX/MDI 추세환경 최종 확인
    -> 분할진입
    -> ADX 상승전환 + 가격구조 강화 시 비중확대
    -> 손절선 이탈 시 자동 STOP/RESET
    -> 약세 다이버전스 및 고점권 급가속 시 일부 익절
    -> 하락추세 전환 시 청산
```

## 2.2 초기 반전 진입과 눌림 진입을 분리

### A. 초기 반전 진입(REVERSAL ENTRY)

목적: 큰 하락 이후 하락추세가 무너지고 상승추세가 태어나는 **초기 구간을 너무 늦지 않게 포착**한다.

핵심:

* 다우 구조가 먼저 하락추세 종료/반전을 보여야 한다.
* `MACD > Signal` 확인.
* RSI는 25 이하에서 매수하지 않는다. 최소한 `RSI > 25`로 과매도 영역을 벗어나고 상승 방향이어야 한다.
* `MACD > 0`, `ADX > 30`까지 기다리지 않는다. 초기 진입이 늦어질 수 있기 때문이다.
* ADX/MDI는 **마지막 필터**다. 강한 하락추세가 아직 강화 중이면 진입을 차단한다.

### B. 상승추세 눌림 진입(PULLBACK ENTRY)

목적: 이미 강한 상승추세가 만들어진 후 정상 조정(HL)에서 다시 상승하는 구간을 잡는다.

핵심:

* 가격구조가 HH-HL 상승추세.
* `MACD > 0`.
* `RSI > 50` 또는 50 부근 지지 후 재상승.
* `ADX >= 30` 또는 강한 영역에서 유지/재상승.
* 눌림 저점이 HL로 유지되고 가격이 재상승해야 한다.

## 2.3 손절의 의미

```text
손절 = 종목 포기 X
손절 = 이번 진입 시나리오 종료 O
```

STOP 발생 시:

1. 포지션 종료 이벤트 기록.
2. 상태를 `RESET\_PENDING`으로 변경.
3. 다음 영업일부터 신규 시그널 생성 허용.
4. 이전 진입가격/손실에 앵커링하지 않는다.
5. 동일 종목이 다시 조건을 만족하면 재진입 가능.

\---

# 3\. 시스템 전체 아키텍처

> **v1.1에서 변경**: v1.0 다이어그램은 `config/friend_universe.yml`이 운영 입력인 것처럼, `KRX Open API`가 데이터 소스인 것처럼 그려져 있었다. 실제로는 (1) 유니버스의 운영 중 source of truth는 **Supabase**이고 YAML은 최초 시드 1회용 파일일 뿐이며(18장, `SwingCycle_Radar_MoneyFlowHub_Integration_Design_v0.2.md` 7.2), (2) 1차 데이터 소스는 **KRX Direct(웹 세션)**로 확정됐다(6장). 아래 다이어그램은 이 두 가지를 반영해 수정했다.

```text
                    +-----------------------------+
                    |  Supabase swingcycle_symbols |
                    |  (최초 시드: config/friend_universe.yml,  |
                    |   운영 중 변경: 8장 CRUD 화면)              |
                    +--------------+--------------+
                                   |  (배치 시작 시 SQLite symbols로 동기화, 7.3)
                                   v
+---------------+      +----------------------+      +---------------------+
| KRX Direct    | ---> | KRX Primary Adapter  | ---> | Raw OHLCV Store     |
| (웹 세션 기반) |      | (krx_direct 구현)     |      |                     |
+---------------+      +----------------------+      +---------------------+
                             | failure                       |
                             v                               v
                       +-----------+                 +---------------------+
                       | pykrx     |                 | Normalized Daily Bar|
                       | fallback  |                 +----------+----------+
                       +-----------+                            |
                                                              v
                                                   +-----------------------+
                                                   | Indicator Engine      |
                                                   | MACD/RSI/ADX/DI/MA    |
                                                   +-----------+-----------+
                                                               |
                                                               v
                                                   +-----------------------+
                                                   | Pivot/Dow Engine      |
                                                   | HH/HL/LH/LL           |
                                                   +-----------+-----------+
                                                               |
                                                               v
                                                   +-----------------------+
                                                   | Cycle State Machine   |
                                                   +-----------+-----------+
                                                               |
                                     +-------------------------+--------------------+
                                     |                         |                    |
                                     v                         v                    v
                             +---------------+        +---------------+     +----------------+
                             | Entry Scoring |        | Exit Scoring  |     | Risk/Stop      |
                             +-------+-------+        +-------+-------+     +--------+-------+
                                     |                        |                      |
                                     +------------------------+----------------------+
                                                              |
                                                              v
                                                   +-----------------------+
                                                   | Daily Decision Engine |
                                                   +-----------+-----------+
                                                               |
                               +-------------------------------+------------------+
                               |                               |                  |
                               v                               v                  v
                        +-------------+                 +-------------+   +----------------+
                        | HTML Report |                 | CSV/JSON    |   | Backtest/Audit |
                        +-------------+                 +-------------+   +----------------+
```

\---

# 4\. 권장 기술 스택

```text
Python      3.12+
Package     uv 또는 pip + requirements.lock
DB          SQLite (v1), PostgreSQL 전환 가능하도록 Repository 패턴
HTTP        httpx
DataFrame   pandas
Numeric     numpy
Config      pydantic-settings + PyYAML
CLI         typer
Logging     structlog 또는 stdlib logging(JSON formatter)
Test        pytest + pytest-cov + hypothesis(선택)
Report      Jinja2 + Plotly(offline) 또는 lightweight-chart/echarts
Lint        ruff
Type        mypy 또는 pyright
```

v1은 설치/운영 단순성을 위해 SQLite를 기본으로 한다.

\---

# 5\. 프로젝트 디렉터리 구조

```text
swingcycle-radar/
├─ pyproject.toml
├─ README.md
├─ .env.example
├─ config/
│  ├─ app.yml
│  ├─ scoring.yml
│  ├─ indicators.yml
│  ├─ friend\_universe.yml
│  └─ markets.yml
├─ data/
│  ├─ cache/
│  └─ exports/
├─ src/swingcycle/
│  ├─ \_\_init\_\_.py
│  ├─ cli.py
│  ├─ settings.py
│  ├─ domain/
│  │  ├─ enums.py
│  │  ├─ models.py
│  │  └─ events.py
│  ├─ data/
│  │  ├─ krx\_client.py
│  │  ├─ pykrx\_client.py
│  │  ├─ market\_data\_service.py
│  │  ├─ normalizer.py
│  │  └─ trading\_calendar.py
│  ├─ repositories/
│  │  ├─ db.py
│  │  ├─ symbol\_repo.py
│  │  ├─ daily\_bar\_repo.py
│  │  ├─ indicator\_repo.py
│  │  ├─ signal\_repo.py
│  │  ├─ trade\_repo.py
│  │  └─ audit\_repo.py
│  ├─ indicators/
│  │  ├─ moving\_average.py
│  │  ├─ macd.py
│  │  ├─ rsi.py
│  │  ├─ dmi\_adx.py
│  │  ├─ volume\_osc.py
│  │  └─ engine.py
│  ├─ structure/
│  │  ├─ pivots.py
│  │  ├─ dow.py
│  │  └─ trendlines.py
│  ├─ cycle/
│  │  ├─ classifier.py
│  │  └─ state\_machine.py
│  ├─ scoring/
│  │  ├─ reversal\_entry.py
│  │  ├─ pullback\_entry.py
│  │  ├─ late\_stage.py
│  │  ├─ adx\_gate.py
│  │  └─ engine.py
│  ├─ risk/
│  │  ├─ stop.py
│  │  ├─ position.py
│  │  └─ reset.py
│  ├─ divergence/
│  │  ├─ bearish.py
│  │  └─ acceleration.py
│  ├─ backtest/
│  │  ├─ simulator.py
│  │  ├─ metrics.py
│  │  └─ datasets.py
│  ├─ reports/
│  │  ├─ html\_report.py
│  │  ├─ templates/
│  │  └─ export.py
│  └─ jobs/
│     ├─ daily\_collect.py
│     ├─ daily\_analyze.py
│     ├─ daily\_report.py
│     └─ backfill.py
├─ migrations/
│  └─ 001\_init.sql
├─ tests/
│  ├─ unit/
│  ├─ integration/
│  ├─ regression/
│  └─ fixtures/
└─ scripts/
   ├─ init\_db.py
   ├─ seed\_friend\_universe.py
   └─ verify\_krx\_access.py
```

\---

# 6\. KRX 데이터 수집 설계

## 6.1 데이터 소스 원칙 (v1.1 개정)

> **v1.0에서 변경**: v1.0은 "KRX Data Marketplace OPEN API(AUTH_KEY 인증)"를 primary로 가정했으나, 이 API는 인증키 승인이 완료되지 않았고 `markets.yml`의 API ID/path가 전부 `TBD_FROM_KRX_SPEC` 플레이스홀더였다. 반면 같은 wt 워크스페이스의 `sugup-report`는 이미 운영 중인 **`krx_direct`(웹 세션 기반 직접 수집)** 방식을 갖고 있다. v1.1은 이 **검증된 방식을 1차 소스로 확정**한다. Open API Marketplace 승인이 완료되면 `KRXClient` 인터페이스는 그대로 두고 내부 구현만 교체 가능하도록 어댑터 경계를 유지한다(6.4).

v1.1 구현 원칙:

1. **`krx_direct`(웹 세션 기반)가 primary** — `data.krx.co.kr`의 OTP 발급→CSV 다운로드 경로 또는 JSON 엔드포인트를 세션 인증 상태로 호출. `sugup-report/src/sugup_pivot/collectors/krx_direct.py`, `sugup_pivot/market/pykrx_session.py`를 **참조해 SwingCycle Radar 저장소 안으로 복사**한다(공용 import 금지 — `SwingCycle_Radar_MoneyFlowHub_Integration_Design_v0.2.md` 1.1항 원칙과 동일).
2. **pykrx는 primary 호출 실패 또는 누락 데이터 보완용 fallback**.
3. 동일 영업일/종목에 두 소스가 모두 있으면 `krx_direct`를 authoritative source로 저장.
4. 원본 응답(raw payload)의 hash와 source를 기록하여 데이터 계보(lineage)를 보존.
5. KRX 웹 엔드포인트/OTP 경로는 코드에 박지 말고 `markets.yml`로 분리.
6. **자동화 탐지/IP 차단 방지 (신규, 필수)** — `sugup-report`는 2026-08-04에 별도 프로세스가 각자 로그인하다 중복 로그인으로 KRX 자동화 탐지에 걸려 IP가 1일간 차단된 실제 장애가 있었다(`sugup-report/docs/history/2026-08-04_krx_ip_block_double_login_fix.md`). 원 설계서 20.1장은 `collect`/`analyze`/`report`/`run-daily`를 별도 CLI(별도 프로세스)로 나누므로 동일 사고가 재현될 수 있다. 따라서:
   - 로그인 세션은 프로세스 간에 재사용 가능한 **싱글턴 + lazy login**으로 구현한다(`sugup-report`의 `get_krx_authenticated_session()` 패턴).
   - 모든 KRX 응답은 `is_kdm_blocked_text()` 방식의 차단 문구 검사를 거친다.
   - `run-daily`(20.1)처럼 여러 단계를 한 번에 실행하는 경로에서는 **단계 간 세션을 공유**하여 로그인이 실행당 최대 1회만 발생하게 한다.

### 6.1.1 프로세스/서비스 간 로그인 조율 — 구체 규격 (v1.1 신설)

> **v1.1에서 변경**: "파일/락 기반 메커니즘이 필요하다"는 필요성만 적혀 있어 구현자마다 다른 방식을 만들 위험이 있었다. `sugup-report`(별도 저장소)와 SwingCycle Radar가 같은 서버에서 동시에 KRX에 로그인하는 상황까지 포함해 아래로 확정한다.

**공유 상태 파일**: 두 서비스 모두 접근 가능하도록 **어느 저장소에도 속하지 않는 경로**에 둔다.

```text
~/.krx_shared/login_state.json
```

```json
{
  "last_login_at": "2026-08-08T09:00:03+09:00",
  "last_login_service": "sugup-report",
  "last_login_status": "ok"
}
```

**동시성 제어**: `fcntl.flock`(POSIX advisory lock)으로 read-modify-write를 원자화한다. lock 획득 대기는 최대 5초 — 그 이상이면 **조율 없이 로그인을 진행**하고 경고 로그만 남긴다(가용성을 코디네이션보다 우선 — 조율 실패가 데이터 수집 전체를 막으면 안 된다).

**최소 재로그인 간격**: `KRX_LOGIN_MIN_INTERVAL_SEC`(기본 300초, `config/markets.yml`에서 조정 가능). 로그인 시도 전 상태 파일을 읽어 `now - last_login_at < KRX_LOGIN_MIN_INTERVAL_SEC`이고 `last_login_status == "ok"`이면:
  - 이미 프로세스 내에 유효한(만료 안 된) 세션이 있으면 그 세션을 그대로 쓴다(추가 로그인 안 함).
  - 세션이 없는데 다른 서비스가 방금 로그인했다면, 그 서비스의 세션을 직접 재사용할 수는 없으므로(코드/세션 비공유 원칙, 1.1항) **잔여 시간만큼 대기 후 재확인**한다(최대 대기 `KRX_LOGIN_MIN_INTERVAL_SEC`, 그 이상 기다리지 않고 스스로 로그인 시도).
  - 로그인 시도(성공/실패 무관) 후에는 항상 상태 파일을 갱신한다.

**조율 범위**: 이 메커니즘은 **로그인 시도 자체의 빈도**만 조절한다 — 로그인 이후의 일반 API 호출(시세 조회 등)까지 두 서비스 간에 속도 제한을 걸지는 않는다. 2026-08-04 사고 원인이 "짧은 간격 내 반복 로그인"이었지 "많은 API 호출" 자체가 아니었기 때문이다(`sugup-report` 장애 분석 참고).

이 규격은 `SwingCycle_Radar_MoneyFlowHub_Integration_Design_v0.2.md` 10장 열린 질문 #5의 구체 구현안이다 — 실제로 `sugup-report` 쪽에도 동일 파일 경로/프로토콜을 반영해야 조율이 성립하므로, `sugup-report` 저장소에 대한 별도 변경 작업(이 문서 범위 밖)이 필요하다.

## 6.2 환경변수

`.env.example`

```dotenv
KRX_WEB_ID=
KRX_WEB_PASSWORD=
KRX_WEB_LOGIN_ENABLED=true
KRX_LOGIN_CD003_MAX_RETRY=3
KRX_LOGIN_CD003_BACKOFF_BASE=1.0
DB_PATH=./data/swingcycle.db
LOG_LEVEL=INFO
HTTP_TIMEOUT_SEC=20
HTTP_MAX_RETRIES=3
```

`sugup-report`의 `pykrx_session.py`와 동일한 변수명을 그대로 쓴다(운영자가 이미 익숙한 이름 재사용, 6.1-1항의 "복사 후 독립 보유" 원칙과는 별개로 **환경변수 이름 자체는 관례 재사용**). `KRX_AUTH_KEY`/`KRX_BASE_URL`(Open API Marketplace용)은 승인 완료 후 대체 어댑터를 추가할 때 별도로 정의한다.

## 6.3 config/markets.yml 예시

```yaml
krx_direct:
  home_url: https://data.krx.co.kr/contents/MDC/MDI/outerLoader/index.cmd
  otp_url: https://data.krx.co.kr/comm/fileDn/GenerateOTP/generate.cmd
  download_url: https://data.krx.co.kr/comm/fileDn/download_csv/download.cmd
  json_url: https://data.krx.co.kr/comm/bldAttendant/getJsonData.cmd
  stat_bld: dbms/MDC/STAT/standard/MDCSTAT01501
  menu_id: MDC0201020101
  login_page: https://data.krx.co.kr/contents/MDC/COMS/client/MDCCOMS001.cmd
  login_url: https://data.krx.co.kr/contents/MDC/COMS/client/MDCCOMS001D1.cmd
  request:
    date_param: trdDd
    date_format: "%Y%m%d"
  response:
    output_key_candidates: [OutBlock_1, output, block1]
  kdm_block_markers:
    - "이용 제한 안내"
    - "자동화 수단을 통한 비정상 대량 조회"
    - "해당 ip의 접속이 일시적으로 제한"

open_api_marketplace:   # 승인 완료 후 대체 어댑터용, v1.1 시점에는 미사용
  enabled: false
  base_url: ${KRX_BASE_URL}
  auth_header: AUTH_KEY
  services:
    kospi_daily: {api_id: TBD_FROM_KRX_SPEC, path: TBD_FROM_KRX_SPEC}
    kosdaq_daily: {api_id: TBD_FROM_KRX_SPEC, path: TBD_FROM_KRX_SPEC}

fallback:
  enabled: true
  provider: pykrx
```

## 6.4 KRXClient 인터페이스

`src/swingcycle/data/krx_client.py`

인터페이스는 원 설계서와 동일하게 유지하되(향후 Open API Marketplace 승인 시 내부 구현만 교체할 수 있도록), 내부 구현은 `krx_direct` 방식을 쓴다.

```python
from dataclasses import dataclass
from datetime import date
from typing import Any

@dataclass(frozen=True)
class KRXResponse:
    market: str
    trade_date: date
    rows: list[dict[str, Any]]
    raw_hash: str
    endpoint: str
    source_mode: str  # "krx_direct" | "open_api_marketplace" (향후 대비)

class KRXClient:
    def __init__(self, base_config: dict[str, Any], timeout: float = 20.0): ...

    def fetch_daily_market(self, market: str, trade_date: date) -> KRXResponse:
        """시장 전체 일별매매정보를 1회 호출해 반환한다. 내부적으로 krx_direct 세션을 사용한다."""

    def _get_authenticated_session(self, *, force_relogin: bool = False):
        """싱글턴 세션 반환. 로그인 필요 시 lazy login. sugup-report get_krx_authenticated_session 패턴 포팅."""

    def _is_blocked_response(self, text: str) -> bool:
        """is_kdm_blocked_text 패턴 포팅 — IP 차단/자동화 탐지 문구 검사."""

    def _request_json(self, path: str, params: dict[str, str]) -> dict[str, Any]: ...
    def _extract_rows(self, payload: dict[str, Any]) -> list[dict[str, Any]]: ...
```

### 요청 정책

* retry: 429/5xx/network timeout에 exponential backoff `1s, 2s, 4s`. **차단 문구(`_is_blocked_response`) 감지 시에는 즉시 중단하고 재시도하지 않는다** — 재시도가 차단 시간을 연장시킬 수 있다(sugup-report 실제 장애 교훈).
* `LOGOUT`/`CD003`(일시 장애) 등 세션 관련 에러 코드는 sugup-report의 `_do_login` 재시도/백오프 정책을 그대로 포팅한다.
* 4xx 인증오류는 즉시 실패 처리.
* 한 날짜의 KOSPI/KOSDAQ 전체 시장 데이터를 먼저 수집한 뒤 절친 universe만 필터링.
* 동일 날짜 재실행은 idempotent upsert.

## 6.5 pykrx fallback

`src/swingcycle/data/pykrx_client.py`

```python
class PykrxClient:
    def fetch_symbol_ohlcv(self, symbol: str, start: date, end: date) -> pd.DataFrame: ...
```

fallback 조건:

```python
if krx_request_failed:
    fallback(symbols_missing, trade_date)
elif krx_rows_missing_friend_symbols:
    fallback(missing_symbols, trade_date)
```

저장 시 `source = 'KRX_DIRECT' | 'PYKRX'`를 반드시 기록한다(v1.0의 `'KRX'` 라벨을 `'KRX_DIRECT'`로 변경 — 6.1의 소스 전환을 lineage 값에도 반영).

pykrx 자체도 내부적으로 KRX 웹 로그인이 필요한 호출이 있으므로(`sugup-report`의 `pykrx_session.py`가 `webio.Post/Get.read`를 monkey-patch하는 이유), **primary(`krx_direct`)와 fallback(pykrx)이 같은 로그인 세션을 공유**하도록 구현한다 — 각자 독립 로그인하면 6.1-6항의 IP 차단 위험이 두 배가 된다.

## 6.6 정규화 필드

```text
trade\_date
symbol
market
open
high
low
close
volume
trade\_value
market\_cap         nullable
shares\_outstanding nullable
source
source\_raw\_hash
collected\_at
```

검증 규칙:

```text
low <= open <= high
low <= close <= high
volume >= 0
trade\_value >= 0
close > 0 (거래정지/특수상황은 별도 status)
```

### v1.1 신설 — symbols.market 역보정 규칙

`daily_bars` 정규화는 항상 `market`을 채운다(KRX 응답 자체가 시장 구분을 포함). 반면 7.1의 `symbols.market`은 Supabase 시드 시점에는 비어 있을 수 있다(위 7.1 참고). `daily_collect` 잡은 종목별로 **첫 정규화된 `daily_bars` row가 생성되는 시점에, 그 row의 `market` 값으로 `symbols.market`이 NULL인 경우에만 채워 넣는다**(이미 값이 있으면 덮어쓰지 않음 — 수동 보정을 존중). 이 역보정 로직이 없으면 `symbols.market`이 영구히 NULL로 남는다.

\---

# 7\. 데이터베이스 설계

## 7.1 symbols

```sql
CREATE TABLE symbols (
    symbol TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    market TEXT,  -- v1.1: NOT NULL 제거. Supabase 초기 시드는 market을 채우지 않고
                  -- 최초 배치 수집(KRX 응답)에서 역보정하므로(통합 설계서 v0.2 7.2),
                  -- NOT NULL이면 첫 Supabase->SQLite 동기화에서 insert가 즉시 실패한다.
    sector\_group TEXT,
    friend\_group TEXT,
    enabled INTEGER NOT NULL DEFAULT 1,
    deleted\_upstream INTEGER NOT NULL DEFAULT 0,  -- v1.1 신설: Supabase 원본에서 하드 삭제됐으나
                                                    -- 로컬 이력 보존을 위해 이 테이블에서는 삭제하지 않은 경우 1
    note TEXT,
    created\_at TEXT NOT NULL,
    updated\_at TEXT NOT NULL
);
```

> **v1.1 신설**: `symbols`는 이제 로컬 원본이 아니라 Supabase `swingcycle_symbols`(운영 중 추가/삭제/변경의 source of truth)를 매 배치 실행 시 동기화해오는 캐시다. 동기화 규칙(삭제/비활성/활성 플랜 보유 종목 처리)은 `SwingCycle_Radar_MoneyFlowHub_Integration_Design_v0.2.md` 7.3장을 따른다 — 이 표는 로컬 캐시의 스키마만 정의하며, 원본 관리 정책은 통합 설계서를 단일 기준으로 한다.

## 7.2 daily\_bars

```sql
CREATE TABLE daily\_bars (
    trade\_date TEXT NOT NULL,
    symbol TEXT NOT NULL,
    open REAL NOT NULL,
    high REAL NOT NULL,
    low REAL NOT NULL,
    close REAL NOT NULL,
    volume INTEGER NOT NULL,
    trade\_value REAL,
    market\_cap REAL,
    source TEXT NOT NULL,
    source\_raw\_hash TEXT,
    collected\_at TEXT NOT NULL,
    PRIMARY KEY (trade\_date, symbol)
);
CREATE INDEX idx\_daily\_bars\_symbol\_date ON daily\_bars(symbol, trade\_date);
```

## 7.3 indicators\_daily

```sql
CREATE TABLE indicators\_daily (
    trade\_date TEXT NOT NULL,
    symbol TEXT NOT NULL,
    sma5 REAL,
    sma20 REAL,
    sma60 REAL,
    sma120 REAL,
    sma240 REAL,
    ema12 REAL,
    ema26 REAL,
    macd REAL,
    macd\_signal REAL,
    macd\_hist REAL,
    rsi14 REAL,
    rsi\_signal REAL,
    pdi14 REAL,
    mdi14 REAL,
    adx14 REAL,
    vo10\_20 REAL,
    ma5\_distance\_pct REAL,
    PRIMARY KEY (trade\_date, symbol)
);
```

## 7.4 pivots

```sql
CREATE TABLE pivots (
    symbol TEXT NOT NULL,
    pivot\_date TEXT NOT NULL,
    confirm\_date TEXT NOT NULL,
    pivot\_type TEXT NOT NULL,       -- HIGH / LOW
    price REAL NOT NULL,
    left\_bars INTEGER NOT NULL,
    right\_bars INTEGER NOT NULL,
    dow\_label TEXT,                 -- HH/HL/LH/LL after classification
    PRIMARY KEY(symbol, pivot\_date, pivot\_type)
);
```

**중요:** `pivot\_date`와 `confirm\_date`를 분리한다. 백테스트/실시간 판정에는 `confirm\_date` 이전에 해당 pivot을 사용할 수 없다.

## 7.5 cycle\_daily

```sql
CREATE TABLE cycle\_daily (
    trade\_date TEXT NOT NULL,
    symbol TEXT NOT NULL,
    cycle\_state TEXT NOT NULL,
    dow\_state TEXT NOT NULL,
    last\_pivot\_high\_date TEXT,
    last\_pivot\_high REAL,
    last\_pivot\_low\_date TEXT,
    last\_pivot\_low REAL,
    PRIMARY KEY(trade\_date, symbol)
);
```

## 7.6 scores\_daily

```sql
CREATE TABLE scores\_daily (
    trade\_date TEXT NOT NULL,
    symbol TEXT NOT NULL,
    reversal\_core\_score REAL,
    adx\_gate TEXT,                  -- PASS/CAUTION/BLOCK
    pullback\_score REAL,
    late\_stage\_score REAL,
    action TEXT,                    -- WAIT/READY/ENTRY/ADD/TAKE\_PROFIT/EXIT/RESET
    reasons\_json TEXT NOT NULL,
    PRIMARY KEY(trade\_date, symbol)
);
```

## 7.7 trade\_plans / trade\_events

```sql
CREATE TABLE trade\_plans (
    plan\_id TEXT PRIMARY KEY,
    symbol TEXT NOT NULL,
    created\_date TEXT NOT NULL,
    entry\_type TEXT NOT NULL,       -- REVERSAL/PULLBACK
    planned\_entry REAL,
    stop\_price REAL NOT NULL,
    stop\_basis\_pivot\_date TEXT,
    status TEXT NOT NULL            -- ACTIVE/STOPPED/CLOSED/RESET
);

CREATE TABLE trade\_events (
    event\_id TEXT PRIMARY KEY,
    plan\_id TEXT NOT NULL,
    trade\_date TEXT NOT NULL,
    event\_type TEXT NOT NULL,       -- ENTRY/ADD/STOP/TAKE\_PROFIT/EXIT/RESET
    price REAL,
    qty\_weight REAL,
    note TEXT,
    created\_at TEXT NOT NULL
);

-- v1.1 신설: 종목당 ACTIVE 플랜은 최대 1개만 허용한다 (부분 유니크 인덱스).
-- v1.0에는 이 제약이 없어 애플리케이션 버그로 동일 종목에 중복 ACTIVE 플랜이
-- 생성될 수 있었다 (RESET/재진입 흐름이 STOPPED/CLOSED/RESET으로 전이하지 못한 채
-- 새 ENTRY를 만드는 경우 등). SQLite는 WHERE절 있는 부분 유니크 인덱스를 지원한다.
CREATE UNIQUE INDEX idx\_trade\_plans\_one\_active\_per\_symbol
    ON trade\_plans(symbol)
    WHERE status = 'ACTIVE';
```

이 인덱스가 걸려 있으면, 이미 ACTIVE 플랜이 있는 종목에 새 ENTRY를 insert하려는 시도는 DB 레벨에서 즉시 실패한다 — 애플리케이션 코드는 "insert 실패 시 기존 ACTIVE 플랜 조회 후 로직 재검토" 흐름을 반드시 갖는다(23.1 Stop 유닛테스트에 회귀 케이스로 추가).

\---

# 8\. 지표 계산 엔진

모든 지표는 일봉 기준이며 **데이터가 수정되면 전체 연관 구간 재계산** 가능해야 한다.

## 8.1 MACD

기본:

```text
fast = EMA(12)
slow = EMA(26)
MACD = EMA12 - EMA26
Signal = EMA(MACD, 9)
Histogram = MACD - Signal
```

파생 boolean:

```python
macd\_above\_signal = macd > macd\_signal
macd\_cross\_up = macd\[t] > signal\[t] and macd\[t-1] <= signal\[t-1]
macd\_above\_zero = macd > 0
macd\_slope\_3 = linear\_slope(macd\[t-2:t+1])
```

## 8.2 RSI

기본 14일 Wilder smoothing.

```text
AvgGain\_t = WilderSmooth(gain, 14)
AvgLoss\_t = WilderSmooth(loss, 14)
RS = AvgGain / AvgLoss
RSI = 100 - 100/(1+RS)
```

v1 전략용 조건:

```python
rsi\_allowed = rsi14 > 25.0
rsi\_turn\_up = rsi14\[t] > rsi14\[t-1]
rsi\_slope\_3 > 0
rsi\_above\_50 = rsi14 > 50.0
```

**주의:** 25는 이 프로젝트의 전략 임계값으로 config화한다.

`rsi\_signal`은 시각화/연구용 EMA(예: 9)로 두되, v1 핵심 진입 점수에는 기본적으로 미사용 가능하도록 flag를 둔다.

## 8.3 DMI/ADX

Wilder 원식으로 계산한다.

```text
UpMove   = High\_t - High\_(t-1)
DownMove = Low\_(t-1) - Low\_t

+DM = UpMove   if UpMove > DownMove and UpMove > 0 else 0
-DM = DownMove if DownMove > UpMove and DownMove > 0 else 0

TR = max(
    High-Low,
    abs(High-PrevClose),
    abs(Low-PrevClose)
)

+DI = 100 \* WilderSmooth(+DM,14) / WilderSmooth(TR,14)
-DI = 100 \* WilderSmooth(-DM,14) / WilderSmooth(TR,14)
DX  = 100 \* abs(+DI - -DI) / (+DI + -DI)
ADX = WilderSmooth(DX,14)
```

UI에서는 기본적으로 `ADX`, `MDI(-DI)`만 표시한다. `PDI(+DI)`는 DB에는 저장하되 기본 UI는 off.

파생값:

```python
adx\_slope\_1 = adx\[t] - adx\[t-1]
adx\_slope\_3 = linear\_slope(adx\[t-2:t+1])
mdi\_slope\_1 = mdi\[t] - mdi\[t-1]
mdi\_slope\_3 = linear\_slope(mdi\[t-2:t+1])

adx\_falling = adx\_slope\_3 < 0
adx\_flattening = abs(adx\_slope\_3) <= ADX\_FLAT\_SLOPE
adx\_turn\_up = adx\[t] > adx\[t-1] and adx\[t-1] <= adx\[t-2]
mdi\_falling = mdi\_slope\_3 < 0
```

## 8.4 MA5 이격

```python
ma5\_distance\_pct = (close / sma5 - 1.0) \* 100.0
ma5\_distance\_delta\_1 = dist\[t] - dist\[t-1]
ma5\_distance\_z20 = zscore(dist, window=20)
```

고점권 급가속은 절대 이격보다 **최근 자기 자신 대비 급팽창**을 우선한다.

## 8.5 Volume Oscillator

관찰 필드로만 구현.

```text
VO = (MA(volume,10) - MA(volume,20)) / MA(volume,20) \* 100
```

SMA/EMA 방식은 config로 선택 가능하되 default SMA.

\---

# 9\. Pivot 및 다우 구조 엔진

## 9.1 가장 중요한 요구사항: look-ahead 방지

과거 차트에서는 pivot이 쉽게 보이지만 실시간에서는 우측 봉이 만들어지기 전 알 수 없다.

v1 기본 pivot:

```yaml
pivot:
  left\_bars: 2
  right\_bars: 2
  price\_mode: wick    # high/low 사용
```

Pivot High:

```python
high\[t] == max(high\[t-left:t+right+1])
```

Pivot Low:

```python
low\[t] == min(low\[t-left:t+right+1])
```

실시간에서 t일 pivot은 `t + right\_bars`일에 확정된다.

## 9.2 Dow label

최근 동일 유형의 pivot과 비교:

```python
if pivot\_type == HIGH:
    label = "HH" if price > prev\_high.price else "LH"
else:
    label = "HL" if price > prev\_low.price else "LL"
```

동일가 처리 tolerance:

```yaml
pivot\_equal\_tolerance\_pct: 0.20
```

허용 범위 내 동일가는 `EH/EL`로 내부 저장할 수 있으나 UI에서는 이전 label 유지 또는 NEUTRAL 처리.

## 9.3 Dow 상태

```python
class DowState(str, Enum):
    DOWNTREND = "DOWNTREND"
    REVERSAL\_CANDIDATE = "REVERSAL\_CANDIDATE"
    UPTREND = "UPTREND"
    RANGE = "RANGE"
```

### 9.3.1 v1.1 구체화 규칙 (v1.0의 정성적 서술 대체)

> **v1.0에서 변경**: "반복", "의미 있는 LH" 같은 정성적 표현은 구현자마다 다르게 해석될 수 있어, `confirm_date` 순으로 정렬된 pivot 시퀀스에 대한 **결정적 함수**로 재정의한다. 파라미터는 `config/indicators.yml`의 `dow_state` 블록으로 뺀다.

```yaml
dow_state:
  downtrend_confirm_run: 2   # 연속 LH·LL 개수 (양쪽 모두 이 수 이상이면 DOWNTREND)
  uptrend_confirm_run: 1     # 연속 HH·HL 개수 (양쪽 모두 이 수 이상이면 UPTREND)
  range_lookback_pivots: 4   # RANGE 판정에 사용할 최근 pivot 개수(고점+저점 합산)
  range_amplitude_shrink_pct: 20.0  # 직전 대비 진폭 축소율(%) 이상이면 RANGE 후보
```

pivot 시퀀스는 `confirm_date` 순으로 정렬된 pivot 목록에서 타입별(HIGH/LOW)로 각각 슬라이스한다. `last_highs = 최근 확정 HIGH pivot 목록 (최신이 마지막)`, `last_lows = 최근 확정 LOW pivot 목록`.

> **구현 시 주의(전문가 리뷰에서 발견)**: 아래 REVERSAL_CANDIDATE 조건 A의 "마지막 확정 LH"는 `last_highs[-1]`(가장 최근 고점 pivot, 라벨 무관)과 **다르다**. `last_highs[-1]`은 이미 HH일 수도 있다. 반드시 `last_highs`를 뒤에서부터 순회해 `dow_label == "LH"`인 **첫 번째(=가장 최근) pivot**을 찾아야 한다 — 아래 `_last_labeled()` 헬퍼로 명시한다. 또한 DowState 판정은 **다음 순서로 배타적 평가**한다(동시 만족 시 상단이 우선), 마지막에 **명시적 default**를 둔다 — 아래 어느 조건도 안 걸리는 경우(예: pivot이 아직 부족한 backfill 초기 구간)를 미정의로 남기지 않기 위함이다.

```python
def _last_labeled(pivots: list[Pivot], label: str) -> Pivot | None:
    """뒤에서부터 순회해 해당 label을 가진 가장 최근 pivot을 반환. 없으면 None."""
    for p in reversed(pivots):
        if p.dow_label == label:
            return p
    return None

def classify_dow_state(last_highs, last_lows, unconfirmed_low, cfg) -> DowState:
    if not last_highs or not last_lows:
        return DowState.RANGE  # pivot 부족(backfill 초기 구간) — 명시적 default

    if (_all_labeled(last_highs[-cfg.uptrend_confirm_run:], "HH")
            and _all_labeled(last_lows[-cfg.uptrend_confirm_run:], "HL")):
        return DowState.UPTREND

    if (_all_labeled(last_highs[-cfg.downtrend_confirm_run:], "LH")
            and _all_labeled(last_lows[-cfg.downtrend_confirm_run:], "LL")):
        return DowState.DOWNTREND

    last_lh = _last_labeled(last_highs, "LH")   # last_highs[-1] 아님 — 라벨로 탐색
    last_ll = _last_labeled(last_lows, "LL")
    cond_a = last_lh is not None and latest_close_or_high_breaks(last_lh)
    cond_b = unconfirmed_low is not None and last_ll is not None and unconfirmed_low.price > last_ll.price
    if cond_a or cond_b:
        return DowState.REVERSAL_CANDIDATE

    if _is_range(last_highs, last_lows, cfg):  # 9.3.1 RANGE 정의 그대로
        return DowState.RANGE

    return DowState.RANGE  # 명시적 default — 위 어느 것도 아니면 RANGE로 귀결시켜 미정의 분기를 없앤다
```

```text
UPTREND:
  last_highs[-uptrend_confirm_run:] 이 전부 dow_label == "HH"
  AND last_lows[-uptrend_confirm_run:] 이 전부 dow_label == "HL"

DOWNTREND:
  last_highs[-downtrend_confirm_run:] 이 전부 dow_label == "LH"
  AND last_lows[-downtrend_confirm_run:] 이 전부 dow_label == "LL"

REVERSAL_CANDIDATE (UPTREND/DOWNTREND 둘 다 아닐 때만 평가):
  A) 최근 종가/고가가, _last_labeled(last_highs, "LH")로 찾은 가장 최근 LH pivot의 고가 또는 종가를 상회
  B) 아직 확정되지 않은 미확정 저점(right_bars 대기 중)이 _last_labeled(last_lows, "LL")로 찾은 가장 최근 LL pivot보다 높음

RANGE (위 셋 다 아닐 때, 그리고 명시적 default):
  최근 range_lookback_pivots개 pivot(고점+저점 합산, confirm_date 역순) 중
  dow_label이 HH/LL(갱신)인 pivot이 하나도 없음 (전부 EH/EL/LH/HL 혼재)
  AND 최근 고점-저점 진폭이 그 이전 동일 개수 구간 진폭 대비 range_amplitude_shrink_pct 이상 축소
  (이 조건도 안 맞으면 그래도 RANGE — 데이터 부족/모호 상태의 기본값)
```

> 실제 전략상 \*\*다우가 핵심 게이트\*\*이므로 이 모듈은 회귀테스트를 가장 많이 확보한다. 위 파라미터(`downtrend_confirm_run` 등)는 24.3 회귀 fixture 20개 구간으로 확정한다 — 초기값은 가설값이며 fixture 검증 후 조정 가능. `classify_dow_state`의 우선순위 순서(UPTREND→DOWNTREND→REVERSAL_CANDIDATE→RANGE) 자체도 fixture로 검증할 회귀 대상이다.

\---

# 10\. Cycle State Machine

```python
class CycleState(str, Enum):
    DOWNTREND = "DOWNTREND"
    BOTTOMING = "BOTTOMING"
    REVERSAL = "REVERSAL"
    UPTREND = "UPTREND"
    PULLBACK = "PULLBACK"
    REACCELERATION = "REACCELERATION"
    LATE\_STAGE = "LATE\_STAGE"
    DOWNTREND\_TRANSITION = "DOWNTREND\_TRANSITION"
```

## 10.1 주요 전이

```text
DOWNTREND -> BOTTOMING
  - LL 갱신 둔화/실패
  - ADX가 하락추세 고점에서 하락
  - MDI 하락 시작

BOTTOMING -> REVERSAL
  - Dow REVERSAL\_CANDIDATE 이상
  - MACD > Signal
  - RSI > 25

REVERSAL -> UPTREND
  - HH + HL 확정
  - MACD 유지
  - ADX 바닥 후 상승이면 신뢰도 증가

UPTREND -> PULLBACK
  - HH 이후 조정
  - 구조상 기존 HL 미훼손

PULLBACK -> REACCELERATION
  - HL 확정/유지
  - MACD > 0
  - RSI > 50 또는 50 지지 후 재상승
  - ADX >= 30 또는 강한 영역 재상승

UPTREND/REACCELERATION -> LATE\_STAGE
  - 가격 HH인데 RSI LH 누적
  - ADX peak가 이전보다 낮음
  - 고점권 MA5 이격 급팽창 시 가중

LATE\_STAGE -> DOWNTREND\_TRANSITION
  - LH 후보 + 주요 HL 훼손

DOWNTREND\_TRANSITION -> DOWNTREND
  - LL 확정
```

### 10.1.1 v1.1 구체화 — 정성적 표현 → 확정 불리언 매핑

> **v1.0에서 변경**: "고점에서 하락", "바닥 후 상승", "peak가 이전보다 낮음" 같은 표현을 8.3/9.3에서 이미 정의한 불리언·파라미터로 고정한다. 새 개념을 도입하지 않고 기존 어휘를 재사용하는 것이 목적이다.

| 전이 조건 문구 | 확정 정의 |
|---|---|
| "ADX가 하락추세 고점에서 하락" | `adx_falling == True` (8.3 정의, 3일 slope 기준) **AND** 직전 `adx_lookback_peak_window`(기본 20영업일) 내 `adx`가 해당 구간 최댓값 대비 하락 중 |
| "ADX 바닥 후 상승" | `adx_turn_up == True` (8.3) **AND** 전환 시점의 `adx` 값이 직전 `adx_lookback_peak_window` 구간 최솟값 대비 110% 이내(바닥권 정의) |
| "ADX peak가 이전보다 낮음" | 최근 confirmed pivot high 구간의 `adx` 로컬 최댓값이, 그 이전 confirmed pivot high 구간의 `adx` 로컬 최댓값보다 작음 (15장 약세 다이버전스의 ADX divergence와 동일 정의 재사용) |
| "MDI 하락 시작" | `mdi_falling == True` (8.3, 3일 slope 기준) |
| "HH 이후 조정" | UPTREND 확정 이후 종가가 마지막 confirmed HH 대비 하락하는 국면(아직 새 pivot low가 확정되지 않아도 진입 가능한 관찰 상태) |
| "구조상 기존 HL 미훼손" | 조정 저가가 마지막 confirmed HL의 저가를 하회하지 않음 |
| "고점권 MA5 이격 급팽창 시 가중" | 15.2의 `ma5_distance_z20 >= threshold` 그대로 재사용 |

`adx_lookback_peak_window`는 `config/indicators.yml`에 신규 파라미터로 추가한다(기본값 20, 원 설계서 350일 backfill 권장치 내에서 충분히 계산 가능).

\---

# 11\. 점수 모델

## 11.1 핵심 원칙

**ADX는 Core Entry Score의 주역이 아니다.**

따라서 두 층으로 분리한다.

```text
1) Core Entry Score = Dow + MACD + RSI
2) ADX/MDI Gate      = PASS / CAUTION / BLOCK
```

최종 액션은 Core 점수와 ADX Gate를 결합한다.

\---

# 12\. Reversal Entry Score (초기 반전)

총점 100.

## 12.1 Dow Score: 45점

```text
+15  최근 구조가 기존 LL/LH 하락추세에서 벗어나기 시작
+15  마지막 확정 LH 고점 종가/고가 돌파
+10  최근 저점이 이전 LL보다 높아 HL 구조 형성/확정
+5   최근 3\~5일 저점 갱신 없음 + 종가 회복
```

구현 함수:

```python
def score\_dow\_reversal(ctx: ScoreContext) -> ScorePart:
    ...
```

## 12.2 MACD Score: 30점

```text
+20  MACD > Signal
+5   MACD 3일 slope > 0
+5   최근 5영업일 이내 MACD 상향 cross 또는 histogram 증가
```

`MACD > 0`은 초기 반전 점수에 필수 아님.

## 12.3 RSI Score: 25점

```text
+10  RSI > 25
+10  RSI 3일 slope > 0 / 직전 저점 대비 반전
+5   RSI가 최근 저점 이후 higher-low 또는 연속 상승 구조
```

`RSI < 25`이면 **Core Score 상한을 69로 제한**하여 ENTRY 금지.

## 12.4 ADX/MDI Gate

```python
class Gate(str, Enum):
    PASS = "PASS"
    CAUTION = "CAUTION"
    BLOCK = "BLOCK"
```

### PASS

아래 중 하나:

```text
A) MDI 3일 slope < 0 AND ADX 3일 slope < 0
B) MDI 3일 slope < 0 AND ADX flattening
C) MDI 3일 slope < 0 AND ADX turn\_up, while Dow/MACD/RSI already bullish
```

### CAUTION

```text
MDI slope가 혼조이거나 ADX가 아직 고점부에서 빠르게 하락 중이나 Core 조건은 좋음
```

### BLOCK

```text
MDI 상승 + ADX 상승 = 기존 하락 방향성이 다시 강화되는 상황
OR
RSI < 25
OR
DowState == DOWNTREND and no break of last LH
```

### v1.1 추가 — 미정의 분기에 대한 명시적 default

> **v1.0에서 변경**: PASS(A/B/C)는 모두 `MDI 3일 slope < 0`을 전제하고, BLOCK은 `MDI 상승 AND ADX 상승`을 전제한다. 그런데 **"MDI 3일 slope >= 0(상승 또는 보합)이면서 ADX 3일 slope < 0(하락)"인 조합**은 PASS 조건에도, BLOCK 조건("MDI 상승 + ADX 상승" 둘 다 필요)에도 해당하지 않아 v1.0 서술만으로는 미정의 상태였다.

```python
def evaluate_adx_gate(ctx) -> Gate:
    if _pass_condition(ctx):   # A/B/C
        return Gate.PASS
    if _block_condition(ctx):  # MDI 상승 + ADX 상승, RSI<25, DOWNTREND 미돌파
        return Gate.BLOCK
    # v1.1: 위 두 조건 모두 아니면 전부 CAUTION으로 귀결시킨다 (명시적 default).
    # "MDI 상승 + ADX 하락"은 하락추세가 약해지고 있으나 아직 -DI가 주도권을 쥔
    # 애매한 조정 구간으로 간주 — ENTRY를 막지는 않되(BLOCK 아님) READY로만 허용한다(12.5).
    return Gate.CAUTION
```

이 `evaluate_adx_gate`는 PASS/BLOCK 여부를 먼저 판정하고 **나머지 전부(기존 CAUTION 서술 포함, MDI 상승+ADX 하락 케이스 포함)를 CAUTION 하나로 귀결**시키는 구조로 구현한다 — 미정의 분기를 코드 레벨에서 원천적으로 없앤다.

## 12.5 Final Reversal Action

config 기본값:

```yaml
reversal:
  ready\_score: 70
  entry\_score: 80
  strong\_entry\_score: 90
```

### v1.1 신설 — cycle_state 게이팅

> 14.2에서 예고한 보강. Reversal 스코어러는 `cycle_state ∈ {BOTTOMING, REVERSAL}`일 때만 `action_resolver`가 참조한다. 이미 `UPTREND`/`PULLBACK`/`REACCELERATION`에 들어간 종목은 Pullback 스코어러(14.2)가 담당하고, `LATE_STAGE`/`DOWNTREND*`는 15장(익절)/16장(손절)이 담당한다 — Reversal의 "다우 구조가 하락추세 종료/반전을 보여야 한다"(2.2-A) 전제와도 일치한다.

결정:

```python
def resolve_reversal_action(core: float, gate: Gate, cycle_state: CycleState) -> Action:
    if cycle_state not in (CycleState.BOTTOMING, CycleState.REVERSAL):
        return Action.WAIT  # 이 스코어러가 관할하는 구간이 아님 — Pullback 쪽 결과를 따른다
    if core < 70:
        return Action.WAIT
    if core < 80:
        return Action.READY if gate != Gate.BLOCK else Action.WAIT
    if core >= 80 and gate == Gate.PASS:
        return Action.ENTRY
    if core >= 80 and gate == Gate.CAUTION:
        return Action.READY
    return Action.WAIT
```

\---

# 13\. ADX 상승전환과 비중확대(ADD)

초기 Entry 이후 다음 조건을 별도 추적한다.

```text
- 가격: HH/HL 진행 또는 진입 후 새 고점 형성
- MACD: > Signal 유지
- RSI: > 25 유지, 가급적 상승
- ADX: 저점 -> 상승전환
- MDI: 낮아지거나 최소한 재상승하지 않음
```

```python
def detect\_add\_confirmation(ctx) -> AddSignal:
    if not ctx.has\_active\_plan:
        return NONE
    if ctx.adx\_turn\_up and ctx.dow\_bullish and ctx.macd\_above\_signal:
        return ADD\_CONFIRM
```

비중 숫자는 시스템이 주문하지 않으며, UI에서 `ADD\_CONFIRM`만 표시한다.

\---

# 14\. Pullback Entry Score (상승추세 눌림)

총점 100.

```text
Dow/Price Structure          35
MACD Regime                  20
RSI Regime                   20
ADX Strength                 15
Pullback Reversal Quality    10
```

## 14.1 조건 예시

### Dow/Price 35

```text
+20  기존 HH-HL 상승추세
+10  눌림 저점이 기존 HL 미훼손
+5   눌림 이후 양봉/직전 단기고점 돌파
```

### MACD 20

```text
+15  MACD > 0
+5   MACD > Signal 또는 histogram 재상승
```

### RSI 20

```text
+15  RSI > 50
+5   RSI가 50 부근 지지 후 재상승
```

### ADX 15

```text
+10  ADX >= 30
+5   ADX가 하락 멈춤/재상승
```

### Pullback Quality 10

```text
+5   20일선/주요 지지선 부근
+5   조정 거래량 감소 후 반등 거래량 회복
```

## 14.2 Final Pullback Action (v1.1 신설)

> **v1.0에서 변경**: Reversal Entry(12.5)는 `core score + gate → action` 결정 로직이 명시돼 있었지만, Pullback Entry는 배점(14장)만 있고 액션 결정 로직이 없었다. 아래는 12.5와 **동일한 구조**로 정의하되, Pullback 점수 안에 ADX 15점이 이미 포함돼 있다는 차이를 반영한다.

### ADX/MDI Gate 적용 여부

**Pullback Entry는 12.4의 ADX/MDI Gate를 재사용하지 않는다.** 이유:

- Pullback 점수(14장)는 이미 `ADX >= 30`(+10점), `ADX 하락 멈춤/재상승`(+5점)으로 ADX 강도를 점수 안에 직접 반영하고 있다.
- 12.4 Gate는 "ADX가 아직 방향을 못 정한 초기 반전 국면"을 위한 안전장치인데, Pullback은 정의상 **이미 확정된 상승추세(HH-HL)** 안에서의 재진입이므로 같은 안전장치가 이중으로 걸릴 이유가 없다.
- 대신 Pullback 고유의 리스크 — "눌림이 아니라 추세 전환의 시작"인 경우 — 는 Dow/Price Structure 35점의 "눌림 저점이 기존 HL 미훼손"(+10) 조건과 cycle_state 게이팅(아래)으로 방어한다.

### cycle_state 게이팅

Pullback 스코어러는 `cycle_state ∈ {PULLBACK, REACCELERATION}`일 때만 평가한다(10장 Cycle State Machine 기준). `cycle_state`가 `REVERSAL`/`UPTREND`(눌림 이전) 또는 `LATE_STAGE`/`DOWNTREND*`(눌림이 아니라 추세 종료 국면)이면 Pullback 점수는 계산하되 `action_resolver`가 참조하지 않는다 — 이렇게 두 스코어러(Reversal/Pullback)가 서로 다른 cycle_state 구간에서만 최종 action을 결정하도록 역할을 분리한다. Reversal Entry도 동일 원칙으로 `cycle_state ∈ {BOTTOMING, REVERSAL}`일 때만 action_resolver가 참조한다(12.5 보강).

### config 기본값

```yaml
pullback:
  thresholds:
    ready: 65
    entry: 75
```

### 결정

```python
def resolve_pullback_action(pullback_score: float, cycle_state: CycleState) -> Action:
    if cycle_state not in (CycleState.PULLBACK, CycleState.REACCELERATION):
        return Action.WAIT  # 이 스코어러가 관할하는 구간이 아님 — Reversal 쪽 결과를 따른다
    if pullback_score < 65:
        return Action.WAIT
    if pullback_score < 75:
        return Action.READY
    return Action.ENTRY
```

`ready`/`entry` 임계값은 Reversal(70/80)보다 낮게 잡았다 — Pullback은 이미 확정된 상승추세 내부 재진입이라 초기 반전보다 판단 근거(HH-HL 구조)가 더 확실하기 때문이다. 초기값은 가설값이며 22장 백테스트로 조정한다.

\---

# 15\. Late Stage / 약세 다이버전스 점수

이 모듈의 목적은 **전량매도 시점 맞히기**가 아니라 분할익절 준비/실행이다.

## 15.1 Bearish Divergence

최근 confirmed pivot highs 2\~3개 비교.

```text
Price: HH
RSI:   LH
```

기본:

```python
def bearish\_divergence(price\_highs, rsi\_at\_highs) -> DivergenceResult:
    # pivot confirm\_date 기준으로만 사용
    ...
```

ADX divergence는 보조:

```text
Price HH + ADX peak LH = 상승의 일방성 약화
```

MACD HH는 오히려 기존 관성이 강함을 뜻할 수 있으므로 약세 divergence를 무효화하지 않는다.

## 15.2 MA5 급이격 / Terminal Acceleration

고점권에서:

```text
- ma5\_distance\_z20 >= threshold
- ma5\_distance\_delta\_1 급증
- price slope가 최근 10\~20일 평균보다 급격히 증가
```

목적:

```text
약세 다이버전스 진행 중 + 고점권 급가속
    -> TAKE\_PROFIT\_PARTIAL 후보
```

기본 late-stage score:

```text
+35  Price HH + RSI LH
+20  RSI LH가 2회 이상 누적
+15  Price HH + ADX peak LH
+20  MA5 이격 급팽창
+10  전고점/박스상단 근접
```

결정:

```text
>= 60: PREPARE\_TAKE\_PROFIT
>= 75: TAKE\_PROFIT\_PARTIAL
```

단, 실제 하락추세 전환(`LH -> LL`)은 별도의 `EXIT`이다.

\---

# 16\. Stop / RESET 설계

## 16.1 단순하고 일관된 기본 Stop

기본 전략:

```text
stop\_price = latest\_valid\_pivot\_low \* 0.99
```

즉 **최근 의미 있는 상승 변곡점(Pivot Low) 저가 -1%**.

설정:

```yaml
risk:
  stop\_buffer\_pct: 1.0
  stop\_reference: latest\_confirmed\_pivot\_low
```

## 16.2 Stop reference 선정

REVERSAL ENTRY:

```text
진입 직전 가장 최근 confirmed pivot low
```

PULLBACK ENTRY:

```text
해당 눌림의 confirmed HL pivot low
```

## 16.3 Gap 처리

EOD 백테스트에서는:

```text
당일 low <= stop\_price:
  기본 체결가 = min(open, stop\_price) 가 아니라
  gap down이면 open, 장중 터치면 stop\_price
```

구현:

```python
def simulated\_stop\_fill(open\_, low, stop):
    if open\_ <= stop:
        return open\_
    if low <= stop:
        return stop
    return None
```

## 16.4 RESET

```python
if stop\_triggered:
    close\_plan()
    emit(STOP)
    emit(RESET)
    reset\_anchor\_state(symbol)
```

RESET이 지우지 않는 것:

* 시장 데이터
* 지표
* 과거 pivot
* 과거 trade events

RESET이 지우는 것:

* 현재 active plan
* 진입가격 앵커
* 현재 포지션 기대

\---

# 17\. 일일 Decision Engine

`src/swingcycle/scoring/engine.py`

```python
@dataclass
class Decision:
    symbol: str
    trade\_date: date
    cycle\_state: CycleState
    reversal\_core\_score: float
    adx\_gate: Gate
    pullback\_score: float
    late\_stage\_score: float
    action: Action
    reasons: list\[str]
    stop\_price: float | None

class DecisionEngine:
    def evaluate(self, symbol: str, trade\_date: date) -> Decision:
        ctx = self.context\_builder.build(symbol, trade\_date)
        cycle = self.cycle\_classifier.classify(ctx)
        rev = self.reversal\_scorer.score(ctx)
        gate = self.adx\_gate.evaluate(ctx)
        pullback = self.pullback\_scorer.score(ctx)
        late = self.late\_stage\_scorer.score(ctx)
        action = self.action\_resolver.resolve(ctx, cycle, rev, gate, pullback, late)
        stop = self.stop\_engine.suggest(ctx, action)
        return Decision(...)
```

## 17.1 Action 우선순위

```text
1. STOP / EXIT
2. RESET
3. TAKE\_PROFIT\_PARTIAL
4. ADD
5. ENTRY
6. READY
7. WAIT
```

리스크 이벤트가 신규 진입보다 항상 우선한다.

### v1.1 신설 — action_resolver.resolve 내부 합성 순서

`action_resolver.resolve(ctx, cycle, rev, gate, pullback, late)`는 아래 순서로 후보를 모아 17.1 우선순위표로 최종 1개를 고른다(12.5/14.2에서 cycle_state 게이팅이 이미 적용된 값이 들어오므로, 여기서는 "관할 구간이 아닌" 스코어러는 이미 `WAIT`로 들어온다):

```python
candidates = [
    stop_engine.check_stop(ctx),                          # STOP (있으면 최우선)
    reset_engine.check_reset(ctx),                         # RESET
    late_stage_scorer.resolve_take_profit(late, ctx),      # TAKE_PROFIT_PARTIAL
    add_detector.detect(ctx),                              # ADD (13장)
    resolve_reversal_action(rev, gate, cycle),             # 12.5 — 관할 아니면 WAIT
    resolve_pullback_action(pullback, cycle),              # 14.2 — 관할 아니면 WAIT
]
action = max(candidates, key=lambda a: _ACTION_PRIORITY[a])  # 17.1 순서로 가장 급한 것 선택
```

이렇게 하면 "STOP과 ENTRY가 같은 날 동시에 계산돼도 STOP이 이긴다"는 17.1 원칙이 코드 레벨에서 하나의 함수로 닫힌다.

\---

# 18\. 절친 Universe 설정

> **v1.1에서 변경**: 아래 YAML은 **최초 시드 전용 파일**이다(실 파일: [`config/friend_universe.yml`](/home/mhhan/projects/wt/SwingCycle/config/friend_universe.yml), 이미 생성되어 있음). **운영 중 종목 추가/삭제/그룹 변경의 source of truth는 Supabase `swingcycle_symbols` 테이블**이며, 이 YAML을 다시 읽어 실행 시점에 유니버스를 구성하는 로직은 만들지 않는다 — `scripts/seed_friend_universe.py`가 최초 1회만 이 파일을 읽어 Supabase를 채운 뒤에는 8장(`SwingCycle_Radar_MoneyFlowHub_Integration_Design_v0.2.md`) CRUD 화면과 Supabase가 유일한 변경 경로다. 아키텍처는 3장 다이어그램 참고.

`config/friend\_universe.yml` (최초 시드용, 런타임 입력 아님)

```yaml
symbols:
  - {symbol: "475960", name: "토모큐브", group: "growth/inspection"}
  - {symbol: "005930", name: "삼성전자", group: "semiconductor"}
  - {symbol: "000660", name: "SK하이닉스", group: "semiconductor"}
  - {symbol: "080220", name: "제주반도체", group: "semiconductor"}
  - {symbol: "319660", name: "피에스케이", group: "semiconductor"}
  - {symbol: "240810", name: "원익IPS", group: "semiconductor"}
  - {symbol: "042700", name: "한미반도체", group: "semiconductor"}
  - {symbol: "007660", name: "이수페타시스", group: "ai\_pcb"}
  - {symbol: "067310", name: "하나마이크론", group: "semiconductor"}
  - {symbol: "000990", name: "DB하이텍", group: "semiconductor"}
  - {symbol: "353200", name: "대덕전자", group: "pcb"}
  - {symbol: "222800", name: "심텍", group: "pcb"}
  - {symbol: "084370", name: "유진테크", group: "semiconductor"}
  - {symbol: "058470", name: "리노공업", group: "semiconductor"}
  - {symbol: "095340", name: "ISC", group: "semiconductor"}
  - {symbol: "108490", name: "로보티즈", group: "robot"}
  - {symbol: "319400", name: "현대무벡스", group: "robot"}
  - {symbol: "454910", name: "두산로보틱스", group: "robot\_beta"}
  - {symbol: "058610", name: "에스피지", group: "robot"}
  - {symbol: "307950", name: "현대오토에버", group: "auto\_ai"}
  - {symbol: "012330", name: "현대모비스", group: "auto"}
  - {symbol: "011210", name: "현대위아", group: "auto"}
  - {symbol: "448900", name: "한국피아이엠", group: "auto\_robot"}
  - {symbol: "204320", name: "HL만도", group: "auto"}
  - {symbol: "119850", name: "지엔씨에너지", group: "power"}
  - {symbol: "009830", name: "한화솔루션", group: "solar"}
  - {symbol: "322000", name: "HD현대에너지솔루션", group: "solar"}
  - {symbol: "010060", name: "OCI홀딩스", group: "solar"}
  - {symbol: "332570", name: "PS일렉트로닉스", group: "rf\_power"}
  - {symbol: "010140", name: "삼성중공업", group: "shipbuilding"}
  - {symbol: "014620", name: "성광벤드", group: "plant"}
  - {symbol: "071970", name: "HD현대마린엔진", group: "shipbuilding"}
  - {symbol: "006400", name: "삼성SDI", group: "battery\_ess"}
  - {symbol: "066970", name: "엘앤에프", group: "battery\_ess"}
  - {symbol: "003670", name: "포스코퓨처엠", group: "battery\_ess"}
  - {symbol: "086520", name: "에코프로", group: "battery"}
  - {symbol: "083650", name: "비에이치아이", group: "nuclear\_power"}
  - {symbol: "034020", name: "두산에너빌리티", group: "nuclear\_power"}
  - {symbol: "052690", name: "한전기술", group: "nuclear\_power"}
  - {symbol: "006910", name: "보성파워텍", group: "nuclear\_candidate"}
  - {symbol: "000720", name: "현대건설", group: "construction"}
  - {symbol: "010120", name: "LS ELECTRIC", group: "ai\_power"}
  - {symbol: "267260", name: "HD현대일렉트릭", group: "ai\_power"}
  - {symbol: "298040", name: "효성중공업", group: "ai\_power"}
  - {symbol: "062040", name: "산일전기", group: "ai\_power"}
  - {symbol: "001440", name: "대한전선", group: "cable"}
  - {symbol: "000500", name: "가온전선", group: "cable"}
  - {symbol: "103590", name: "일진전기", group: "cable\_power"}
  - {symbol: "035420", name: "NAVER", group: "internet\_ai"}
  - {symbol: "017670", name: "SK텔레콤", group: "telecom\_ai"}
  - {symbol: "004020", name: "현대제철", group: "steel"}
  - {symbol: "460860", name: "동국제강", group: "steel"}
  - {symbol: "001430", name: "세아베스틸지주", group: "steel"}
```

\---

# 19\. 섹터 동시성 점수(보조, v1.1 후보)

개별 종목의 ENTRY 판단을 대체하지 않고 **동일 그룹에서 READY/ENTRY가 얼마나 동시에 발생하는지** 표시한다.

```python
sector\_ready\_ratio = ready\_or\_entry\_count / enabled\_group\_count
```

예:

```text
ai\_power 7개 중 5개 READY/ENTRY -> sector\_confirmation = HIGH
robot 9개 중 1개 READY          -> sector\_confirmation = LOW
```

v1에서는 report badge만 표시하고 Entry Core Score에는 미반영한다.

\---

# 20\. 일일 배치

## 20.1 권장 실행 순서

```text
16:30 이후 또는 KRX EOD 데이터 확정 후

1. collect
2. normalize/validate
3. indicators
4. pivots/dow
5. cycle
6. scores
7. trade-plan risk check
8. report
```

CLI:

```bash
swingcycle collect --date 2026-08-08
swingcycle analyze --date 2026-08-08
swingcycle report --date 2026-08-08
swingcycle run-daily --date 2026-08-08
```

## 20.2 Backfill

```bash
swingcycle backfill --start 2020-01-01 --end 2026-08-08
```

권장 최소 lookback: 300 trading days. SMA240 및 안정적인 ADX/RSI warm-up을 위해 350일 권장.

\---

# 21\. HTML 리포트 요구사항

매일 절친 종목을 아래 순서로 정렬:

```text
1. STOP/EXIT
2. ENTRY
3. ADD
4. TAKE\_PROFIT\_PARTIAL
5. READY
6. WAIT
```

각 카드:

```text
종목명 / 코드 / 그룹
Cycle State
Action
Reversal Core Score
ADX Gate
Pullback Score
Late Stage Score
Dow State
MACD / Signal / 0선 위치
RSI / 25 / 50
ADX / MDI / 각도
최근 pivot HH/HL/LH/LL
제안 Stop
Reason codes
```

Reason 예:

```text
DOW\_LAST\_LH\_BROKEN
MACD\_ABOVE\_SIGNAL
RSI\_ABOVE\_25\_TURNING\_UP
MDI\_FALLING
ADX\_FLATTENING
STOP\_AT\_PIVOT\_LOW\_MINUS\_1PCT
```

\---

# 22\. 백테스트 설계

## 22.1 핵심: 시그널 날짜와 체결 날짜 분리

EOD 신호는 당일 종가 확정 후 알 수 있으므로 기본 백테스트 체결은 **다음 영업일 시가**로 한다.

```text
signal\_date = T
entry\_fill\_date = T+1
entry\_fill\_price = open\[T+1]
```

당일 종가 체결 모드는 연구용으로만 제공하며 기본 OFF.

## 22.2 포지션 모델

v1 단순 모델:

```text
ENTRY  = 1 unit
ADD    = +1 unit (max 3 units configurable)
TAKE\_PROFIT\_PARTIAL = -1 unit
STOP/EXIT = all remaining units
```

실제 사용자는 종목당 20% 상한을 두지만, 백테스트에서는 unit 기반으로 룰 성과를 먼저 본다.

## 22.3 성과 지표

반드시 계산:

```text
trade\_count
win\_rate
avg\_return
median\_return
profit\_factor
expectancy
max\_drawdown
avg\_holding\_days
MFE (Maximum Favorable Excursion)
MAE (Maximum Adverse Excursion)
stop\_rate
reentry\_success\_rate
5d/10d/20d forward return after ENTRY
5d/10d/20d forward MAE
```

특히 아래 A/B/C 비교를 자동 생성:

```text
A. Dow + MACD>Signal + RSI>25 진입
B. A + ADX Gate PASS 진입
C. ADX 실제 상승전환까지 기다린 진입
```

목표: ADX를 최종 필터로 쓸 때 **초기 진입 손익비와 손절 빈도가 실제 개선되는지** 검증.

\---

# 23\. 테스트 전략

## 23.1 Unit Test

### Indicators

* EMA seed/warm-up 규칙 고정.
* Wilder RSI가 reference fixture와 오차 허용범위 내 일치.
* DMI/ADX가 reference fixture와 일치.
* zero division 처리.
* gap up/down TR 계산 검증.

### Pivot

* plateau high/low.
* equal high tolerance.
* right\_bars 이전에는 pivot 미확정.
* confirm\_date 이후에만 Dow label 사용.

### Scoring

* RSI <25이면 Entry 불가.
* MACD <= Signal이면 MACD 점수 0/감점 정책 확인.
* ADX/MDI BLOCK이 Entry를 차단.
* Pullback은 MACD>0, RSI>50, ADX strong 조건의 가중 반영.

### Stop

* intraday touch.
* gap down.
* exact stop touch.
* STOP 후 RESET 생성.

## 23.2 Integration Test

* KRX sample response -> normalized bar -> DB upsert.
* KRX 실패 -> pykrx fallback -> source 표시.
* 350일 backfill -> indicator -> pivot -> score 전체 파이프라인.
* daily 재실행 idempotency.

## 23.3 Regression Test

대표 10\~20개 종목/특정 구간을 fixture로 고정.

반드시 포함:

```text
1. 큰 하락 후 정상 반전 성공 사례
2. MACD/RSI 반전했지만 다시 LL로 실패한 사례
3. ADX/MDI가 여전히 강한 하락을 보여 BLOCK해야 하는 사례
4. STOP 후 재진입 성공 사례
5. 강한 상승추세 눌림 성공 사례
6. 약세 다이버전스 후 고점권 급가속/분할익절 사례
7. 박스권에서 false breakout 사례
```

\---

# 24\. 검증 체크리스트

## 24.1 데이터 수집

* \[ ] KRX 웹 로그인 자격증명(`KRX_WEB_ID`/`KRX_WEB_PASSWORD`)이 환경변수에서만 로드된다. (v1.1)
* \[ ] KRX 응답이 IP 차단/자동화 탐지 문구(`is_kdm_blocked_text` 패턴)를 검사받는다. (v1.1 신설)
* \[ ] `collect`/`analyze`/`report`를 별도 프로세스로 실행해도 로그인이 중복 발생하지 않는다(세션 싱글턴 검증). (v1.1 신설)
* \[ ] KOSPI/KOSDAQ 일별 데이터가 지정 날짜에 수집된다.
* \[ ] 절친종목 53개가 symbol mapping 오류 없이 매칭된다.
* \[ ] 휴장일은 오류가 아니라 `NO\_TRADING\_DAY`로 처리된다.
* \[ ] KRX_DIRECT 실패 시 pykrx fallback이 작동한다.
* \[ ] KRX_DIRECT/pykrx 중복 시 KRX_DIRECT가 우선한다.
* \[ ] OHLC 불변식(low<=open/close<=high)이 검증된다.
* \[ ] 동일 일자 재실행 시 중복 row가 생성되지 않는다.
* \[ ] raw hash/source lineage가 남는다.

## 24.2 지표

* \[ ] MACD(12,26,9)가 reference와 일치한다.
* \[ ] RSI14 계산이 Wilder smoothing 방식으로 일치한다.
* \[ ] RSI <25 구간에서 Entry가 발생하지 않는다.
* \[ ] ADX14/MDI14가 reference와 일치한다.
* \[ ] ADX 하락/평탄/상승전환 판정이 fixture와 일치한다.
* \[ ] MDI 감소 판정이 1일 noise보다 3일 slope를 우선한다.
* \[ ] MA5 이격과 z-score가 올바르다.
* \[ ] V.O는 점수에 영향이 없고 관찰만 한다.

## 24.3 다우/Pivot

* \[ ] Pivot High/Low는 wick(high/low) 기준이다.
* \[ ] right\_bars가 지나기 전 pivot을 사용하지 않는다.
* \[ ] HH/HL/LH/LL이 이전 동일 타입 pivot과 비교된다.
* \[ ] 실제 시그널 날짜는 pivot\_date가 아니라 confirm\_date를 따른다.
* \[ ] 동일고점/동일저점 tolerance가 적용된다.
* \[ ] 하락추세 중 일시 반등을 상승추세로 오판하지 않는 regression case가 있다.

## 24.4 초기 반전 Entry

* \[ ] Dow가 핵심 선행조건이다.
* \[ ] MACD > Signal이 확인된다.
* \[ ] RSI >25 및 상승방향이 확인된다.
* \[ ] ADX/MDI는 최종 Gate일 뿐 Core Score를 지배하지 않는다.
* \[ ] `MDI↑ + ADX↑` 강한 하락 강화 시 BLOCK된다.
* \[ ] ADX >30, MACD >0을 초기 Entry 필수로 요구하지 않는다.
* \[ ] READY와 ENTRY가 구분된다.

## 24.5 비중확대 ADD

* \[ ] Entry 이후에만 ADD가 발생한다.
* \[ ] ADX 바닥->상승전환이 확인 조건으로 쓰인다.
* \[ ] 가격구조가 동시에 우호적이지 않으면 ADX 상승만으로 ADD하지 않는다.
* \[ ] 최대 unit/비중 상한 설정이 있다.

## 24.6 눌림 Entry

* \[ ] HH-HL 상승추세가 전제다.
* \[ ] MACD >0.
* \[ ] RSI >50 또는 50 지지 후 반등.
* \[ ] ADX >=30 또는 강한 영역 재상승.
* \[ ] 눌림 저점/HL 손절선이 산출된다.

## 24.7 손절/RESET

* \[ ] 진입 전에 stop\_price가 반드시 생성된다.
* \[ ] 기본 stop은 최신 confirmed pivot low -1%다.
* \[ ] gap down 체결을 stop 가격으로 과대평가하지 않는다.
* \[ ] STOP 후 active plan이 종료된다.
* \[ ] STOP과 RESET 이벤트가 모두 남는다.
* \[ ] RESET 후 동일 종목 재진입이 가능하다.
* \[ ] 손절된 종목을 blacklist하지 않는다.

## 24.8 약세 다이버전스/익절

* \[ ] 약세 다이버전스만으로 EXIT하지 않는다.
* \[ ] `Price HH + RSI LH`는 분할매도 준비로 분류한다.
* \[ ] 고점권 MA5 이격 급팽창이 partial take-profit 점수에 반영된다.
* \[ ] MACD HH가 약세 divergence를 자동 무효화하지 않는다.
* \[ ] LH->LL 하락추세 전환은 별도 EXIT다.

## 24.9 백테스트 신뢰성

* \[ ] 모든 pivot은 confirm\_date 기준으로 사용한다.
* \[ ] EOD signal은 기본 다음날 시가 체결이다.
* \[ ] 거래정지/상한가/하한가/갭을 현실적으로 처리한다.
* \[ ] survivorship bias를 문서화한다(현재 절친 universe 기반 과거검증이라는 한계).
* \[ ] score threshold tuning과 최종 검증 구간을 분리한다.
* \[ ] 성공 사례뿐 아니라 실패 사례를 동일 비중으로 review한다.
* \[ ] A/B/C 진입 방식 비교 리포트가 나온다.

## 24.10 운영

* \[ ] `run-daily` 한 명령으로 수집부터 리포트까지 완료된다.
* \[ ] 단계별 재실행 가능하다.
* \[ ] 실패 단계에서 명확한 exit code와 log가 남는다.
* \[ ] DB backup/restore 절차가 README에 있다.
* \[ ] config 변경 이력이 score 결과와 함께 기록된다.

\---

# 25\. 반드시 피할 구현 오류

1. **미래 pivot 사용**: 차트 복기 시 가장 흔한 look-ahead 오류.
2. `ADX > 30 = 상승`으로 해석: ADX에는 방향이 없다.
3. `ADX - MDI`로 PDI를 추정: 수학적으로 성립하지 않는다.
4. RSI 25 한 숫자만 보고 진입: 다우/MACD가 먼저다.
5. MACD 골든크로스만으로 하락추세 중 매수.
6. 손절 후 이전 진입가격을 기준으로 재판단.
7. 현재 절친 종목만으로 과거 백테스트 후 전체시장 일반화.
8. 점수를 너무 세분화해 과최적화.
9. KRX/pykrx 값을 조용히 섞어 source lineage를 잃는 것.
10. corporate action/수정주가 정책을 명시하지 않는 것.

\---

# 26\. 수정주가/Corporate Action 정책

기술지표 계산에는 액면분할/병합 등 가격 불연속이 치명적이다.

v1 정책:

* KRX 원시가격(raw) 저장은 그대로 보존.
* 별도 `adjusted\_bars` 또는 adjustment factor를 도입할 수 있게 schema 확장 여지 확보.
* pykrx fallback의 수정주가 여부를 명시적으로 확인하고 KRX와 혼용하지 않는다.
* 실제 split/merge 발생 종목은 indicator continuity QA 대상에 자동 등록.

v1 구현에서 수정주가 데이터를 안정적으로 확보하지 못하면 해당 이벤트 전후 일정 기간을 백테스트 제외하는 보수적 정책을 허용한다.

\---

# 27\. 설정 파일 예시

`config/scoring.yml`

```yaml
reversal:
  weights:
    dow: 45
    macd: 30
    rsi: 25
  thresholds:
    ready: 70
    entry: 80
    strong\_entry: 90
  rsi:
    min\_entry: 25.0
  adx\_gate:
    flat\_slope\_abs\_max: 0.25
    mdi\_slope\_window: 3
    adx\_slope\_window: 3

pullback:
  thresholds:
    entry: 75
  macd\_min: 0.0
  rsi\_min: 50.0
  adx\_min: 30.0

late\_stage:
  prepare: 60
  partial\_take\_profit: 75
  ma5\_distance\_z\_min: 1.5

risk:
  stop\_buffer\_pct: 1.0
```

> 초기 숫자는 \*\*가설값\*\*이며 validation 결과에 따라 조정한다. 코드 상수로 고정 금지.

\---

# 28\. Domain Model 핵심 예시

```python
from dataclasses import dataclass
from datetime import date
from enum import StrEnum

class Action(StrEnum):
    WAIT = "WAIT"
    READY = "READY"
    ENTRY = "ENTRY"
    ADD = "ADD"
    TAKE\_PROFIT\_PARTIAL = "TAKE\_PROFIT\_PARTIAL"
    EXIT = "EXIT"
    STOP = "STOP"
    RESET = "RESET"

@dataclass(frozen=True)
class IndicatorSnapshot:
    macd: float
    macd\_signal: float
    rsi: float
    adx: float
    mdi: float
    pdi: float | None
    sma5: float
    sma20: float
    ma5\_distance\_pct: float

@dataclass(frozen=True)
class StructureSnapshot:
    dow\_state: str
    last\_high\_label: str | None
    last\_low\_label: str | None
    last\_pivot\_high: float | None
    last\_pivot\_low: float | None

@dataclass(frozen=True)
class ScoreContext:
    symbol: str
    trade\_date: date
    bar: object
    indicators: IndicatorSnapshot
    structure: StructureSnapshot
    history: object
```

\---

# 29\. Reason Code 체계

사람이 점수를 신뢰하려면 **왜 그 점수가 나왔는지**가 보여야 한다.

```text
DOW\_DOWNTREND
DOW\_REVERSAL\_CANDIDATE
DOW\_LAST\_LH\_BROKEN
DOW\_HL\_CONFIRMED
DOW\_HH\_CONFIRMED
MACD\_ABOVE\_SIGNAL
MACD\_CROSS\_UP\_RECENT
MACD\_ABOVE\_ZERO
RSI\_BELOW\_25\_BLOCK
RSI\_ABOVE\_25
RSI\_TURN\_UP
RSI\_ABOVE\_50
ADX\_FALLING\_FROM\_HIGH
ADX\_FLATTENING
ADX\_TURN\_UP
ADX\_ABOVE\_30
MDI\_FALLING
MDI\_RISING\_BLOCK
PULLBACK\_HL\_HOLD
LATE\_BEARISH\_DIVERGENCE
LATE\_MA5\_ACCELERATION
STOP\_PIVOT\_LOW\_MINUS\_BUFFER
RESET\_AFTER\_STOP
```

DB에는 reasons를 JSON 배열로 저장한다.

\---

# 30\. Codex 구현 순서(권장 Sprint)

## Sprint 1 - 기반

* 프로젝트 skeleton
* config/settings
* SQLite migration
* friend universe seed
* KRX client stub + sample fixture
* pykrx fallback

완료 기준:

```bash
swingcycle collect --date YYYY-MM-DD
```

이 정상 동작하고 daily\_bars에 데이터가 저장됨.

## Sprint 2 - Indicators

* SMA/EMA
* MACD
* RSI Wilder
* DMI/ADX/MDI
* MA5 distance
* VO observational

완료 기준: reference fixture와 수치 일치.

## Sprint 3 - Pivot/Dow

* causal pivot
* confirm\_date
* HH/HL/LH/LL
* DowState

완료 기준: 회귀 fixture 20개 구간 통과.

## Sprint 4 - Cycle/Scoring

* state machine
* reversal core score
* ADX gate
* pullback score
* late-stage score

완료 기준: reason code 포함 daily decision 생성.

## Sprint 5 - Risk/RESET

* stop suggestion
* trade plan/events
* stop simulation
* reset/re-entry

## Sprint 6 - Report

* daily HTML
* CSV/JSON export
* sortable score table
* action badges

## Sprint 7 - Backtest/Validation

* next-open execution
* MFE/MAE
* A/B/C comparison
* regression report

\---

# 31\. Definition of Done

v1은 아래를 모두 충족해야 완료로 본다.

```text
\[DATA]
KRX primary + pykrx fallback + lineage + idempotent

\[TECHNICAL]
MACD/RSI/ADX/MDI reference 검증

\[STRUCTURE]
look-ahead 없는 pivot + Dow 구조

\[SCORING]
초기반전과 눌림 분리
Core Entry = Dow/MACD/RSI
ADX/MDI = final Gate

\[RISK]
진입 전 stop 필수
STOP -> RESET -> 재진입 가능

\[EXIT]
약세 divergence = 준비
고점권 급가속 = partial take-profit
LH/LL 하락전환 = exit

\[VALIDATION]
성공/실패 regression fixture
A/B/C 비교
MFE/MAE/stop rate/reentry success 산출

\[OPERATIONS]
1-command daily run + HTML report
```

\---

# 32\. Codex에게 전달할 구현 지시문

아래 문장을 이 설계서와 함께 전달하면 된다.

> 이 문서의 v1 범위를 그대로 구현하라. 임의로 전략 조건을 추가하거나 삭제하지 말고, 모든 threshold/weight는 config로 분리하라. KRX OPEN API를 primary source로, pykrx를 fallback으로 구현한다. 가장 중요한 품질 조건은 (1) pivot look-ahead 금지, (2) Wilder 방식 RSI/DMI/ADX 수치 검증, (3) Core Entry Score와 ADX Gate 분리, (4) STOP 후 RESET/re-entry 가능, (5) 모든 decision reason code 저장이다. 각 Sprint마다 pytest를 먼저 추가하고 통과 후 다음 Sprint로 진행하라. 구현 중 KRX 실제 API ID/path가 명세와 다르면 config만 수정하고 domain/scoring 코드는 변경하지 마라.

\---

# 33\. 공식 KRX 참고자료

* KRX OPEN API 서비스 이용방법: 인증키 신청 -> API 탐색 -> 활용 신청 -> 승인 후 개발 적용.
* KRX OPEN API 서비스 목록: 주식/지수 등 통계 API 제공, 안내상 2010년 이후 데이터 제공 대상.
* 주식 `유가증권 일별매매정보` 서비스 페이지는 2026-01-16 수정 이력이 확인되며 JSON/XML 제공.

참고 URL:

```text
https://openapi.krx.co.kr/contents/OPP/INFO/OPPINFO003.jsp
https://openapi.krx.co.kr/contents/OPP/INFO/service/OPPINFO004.cmd
https://openapi.krx.co.kr/contents/OPP/USES/service/OPPUSES002\_S1.cmd
https://openapi.krx.co.kr/
```

\---

# 34\. 최종 운용 문장

```text
좋은 종목인가? -> 절친 등록 단계에서 끝낸다.
지금 좋은 진입인가? -> 다우/MACD/RSI가 판단한다.
추세환경이 이 판단과 모순되는가? -> ADX/MDI가 마지막 확인한다.
틀리면? -> 자동 손절하고 RESET한다.
다시 좋아지면? -> 처음부터 다시 매수권을 평가한다.
강한 상승 후 약세 다이버전스가 나오면? -> 분할매도를 준비한다.
고점권에서 갑자기 과속하면? -> 일부 이익을 실현한다.
하락추세로 바뀌면? -> 남은 물량을 청산한다.
아무도 매수권을 얻지 못하면? -> 현금이 1등 절친이다.
```

