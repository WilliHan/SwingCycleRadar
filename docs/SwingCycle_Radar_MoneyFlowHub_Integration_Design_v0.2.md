# SwingCycle Radar — MoneyFlow Hub 통합 설계 (초안 v0.2)

> 작성: 2026-08-08 (v0.1) / 개정: 2026-08-08 (v0.2)
> 상태: **DRAFT** — 코딩 착수 전 확정 필요 항목 존재 (11장 참고)
> 범위: SwingCycle Radar를 MoneyFlow Hub 서비스로 등록, 절친종목 유니버스를 Supabase로 관리
> 전제 문서: [`SwingCycle_Radar_Source_Level_Design_v1.1.md`](/home/mhhan/projects/wt/SwingCycle/docs/SwingCycle_Radar_Source_Level_Design_v1.1.md), [`mfhub_phase4_service_sso_rollout.md`](/home/mhhan/projects/wt/MoneyFlowHub/docs/mfhub_phase4_service_sso_rollout.md), [`mfhub_phase2_3_auth_design.md`](/home/mhhan/projects/wt/MoneyFlowHub/docs/mfhub_phase2_3_auth_design.md)

### v0.2 변경 이력 (v0.1 대비)

| # | 문제 | 조치 | 위치 |
|---|---|---|---|
| 1 | KRX 연동 방식이 원 설계서(Open API)와 이 문서(sugup-report 웹 로그인) 사이에서 충돌 | 원 설계서를 v1.1로 개정해 `krx_direct`(웹 세션)로 단일화 — 이 문서는 그 결정을 참조만 함 | 1.1항, 원 설계서 v1.1 6장 |
| 2 | Streamlit + Hub gate만으로는 쓰기 요청 신원 확인/위조 방지가 안 됨 | 4.4 "Hub 신원 확인 브리지" 신설 — 운영 nginx의 실제 헤더 주입 패턴 기반 | 4.4 |
| 3 | `/scr/` 배포용 baseUrlPath·health 경로·nginx 설정이 없음 | 4.1, 4.5 신설 — MFTS 운영 스크립트 실측값 반영 | 4.1, 4.5 |
| 4 | Supabase→SQLite 동기화 시 삭제/비활성/활성 플랜 보유 종목 처리 규칙 없음 | 7.3 신설 | 7.3 |
| 5 | group 매핑을 마크다운 설계 문서 파싱에 의존 | `config/friend_universe.yml` 실제 파일로 승격, 8.2 갱신 | 8.2 |

**v0.2 후속 수정 (같은 날, 교차 일관성 리뷰 반영):**

| # | 문제 | 조치 | 위치 |
|---|---|---|---|
| 6 | Supabase `swingcycle_symbols.market` nullable 시드가 원 설계서 v1.1의 `symbols.market NOT NULL`과 충돌 | 원 설계서 v1.1 7.1에서 `market` NOT NULL 제거 + 6.6 역보정 규칙 추가로 해결(이 문서에서는 변경 없음, 원 설계서 쪽 수정) | 원 설계서 v1.1 7.1, 6.6 |
| 7 | KRX 로그인 조율(10장 #5)이 열린 질문 수준에 머묾 | 원 설계서 v1.1 6.1.1에 구체 규격(공유 파일 경로/락/최소 간격) 확정 — 10장 #5 갱신 | 10장 #5, 원 설계서 v1.1 6.1.1 |

---

## 1. 문서 목적

기존 리뷰(2026-08-08)에서 확인된 3개 선결정 — **런타임 형태 / Hub 서비스 ID / 유니버스 저장 모델** — 을 이 문서에서 확정하고, 실제 구현 착수 시 수정할 파일 목록까지 구체화한다. 이 문서는 초안이므로 9장 "확정 결정"과 10장 "열린 위험"을 구분해 표시한다.

### 1.1 코드 재사용 원칙 (sugup-report)

- `sugup-report`의 KRX 연동(`krx_direct.py`, `pykrx_session.py`)과 Supabase 접근(`webapp/common/supabase_helper.py`)은 **참조하되, 필요한 부분을 SwingCycle Radar 저장소 안으로 복사해서 자체 보유**한다.
- `sugup-report` 소스를 **공용 패키지로 만들거나, import/sys.path 조작으로 두 저장소가 같은 코드를 직접 공유하지 않는다.**
- 이유:
  - 두 서비스는 독립적으로 배포·버전관리되어야 하며, 한쪽의 리팩터링이 다른 쪽을 깨뜨리면 안 된다.
  - `sugup-report`는 이미 운영 중인 서비스라 코드 변경에 보수적이어야 하는데, SwingCycle Radar 개발 중 잦은 수정이 필요한 코드를 같은 파일에서 공유하면 두 서비스 모두 회귀 위험이 커진다.
- **단, 코드를 분리해도 운영 리스크는 분리되지 않는 지점이 있다**: `sugup-report`와 SwingCycle Radar가 같은 서버(같은 아웃바운드 IP)에서 각자 KRX 웹 로그인을 수행하면, 두 서비스의 로그인 빈도가 합산되어 2026-08-04 IP 차단 사고(`sugup-report/docs/history/2026-08-04_krx_ip_block_double_login_fix.md`)와 같은 자동화 탐지 기준에 더 쉽게 걸릴 수 있다. 코드는 복사해서 분리하되, **KRX 로그인 시각/빈도를 두 서비스가 서로 인지할 수 있는 별도의 운영 조율(예: 로그인 최소 간격을 두 서비스가 공유하는 파일/락으로 관리)이 필요한지는 10장 열린 질문에 추가한다.**

**KRX 연동 방식 확정 (v0.2)**: v0.1 시점에는 원 설계서(v1.0)가 "KRX Open API Marketplace(AUTH_KEY)"를 primary로 못박고 있는데 이 문서는 sugup-report의 웹 로그인형 `krx_direct`를 전제로 해 두 문서가 서로 다른 인증 방식을 가리키는 충돌이 있었다. **원 설계서를 v1.1로 개정해 `krx_direct`(웹 세션 기반)를 primary로 확정**했으므로(`SwingCycle_Radar_Source_Level_Design_v1.1.md` 6장), 이 문서의 전제와 원 설계서가 이제 일치한다. 인증 방식/장애 모드/환경변수/세션 관리의 구체적 내용은 원 설계서 v1.1 6장을 단일 기준으로 따른다 — 이 문서에서 중복 서술하지 않는다.

---

## 2. 저장소 / 디렉토리

- **Git 저장소**: `https://github.com/WilliHan/SwingCycleRadar.git`
- **프로젝트 작업 홈 디렉토리**: **`/home/mhhan/projects/wt/SwingCycle/`** (기존 디렉토리 그대로 사용 — 신규 최상위 폴더를 따로 만들지 않는다).
  - 이미 존재하는 `SwingCycle/docs/`(설계서 + `절친종목.csv` + 이 문서)를 그대로 두고, 그 옆에 원 설계서 5장 구조를 이 홈 디렉토리 기준으로 생성한다:
    ```text
    SwingCycle/
    ├─ docs/                     # 기존 설계서 + 절친종목.csv + 통합 설계서(이 문서) (유지)
    ├─ config/
    ├─ data/
    ├─ src/swingcycle/
    ├─ migrations/
    ├─ tests/
    └─ scripts/
    ```
  - 원 설계서 5장의 최상위 폴더명(`swingcycle-radar/`, kebab-case)은 **패키지 내부 구조 설명용 예시**로만 참고하고, 실제 최상위 디렉토리는 이미 정해진 `SwingCycle/`을 그대로 쓴다. `wt`의 다른 프로젝트들(`MFTS`, `MFGR`, `sugup-report` 등)과 동일하게, 이 디렉토리 자체가 독립 git 저장소가 된다.
  - 앞으로 이 프로젝트에서 산출되는 모든 자료(코드, 설계 문서, 시드 스크립트, 캐시/로그 등)는 이 `SwingCycle/` 디렉토리 체계 하위에 위치시킨다 — 다른 프로젝트 디렉토리(`MoneyFlowHub/`, `sugup-report/` 등)에는 SwingCycle 소유 산출물을 두지 않는다.
- `git init` + `git remote add origin https://github.com/WilliHan/SwingCycleRadar.git`은 실제 코드 스캐폴딩을 시작하는 시점에 `SwingCycle/` 안에서 수행한다. 이 문서(설계 초안) 작성 단계에서는 아직 실행하지 않았다.

---

## 3. 런타임 형태 결정

### 3.1 후보 비교

| 후보 | 장점 | 단점 |
|---|---|---|
| FastAPI + 정적 HTML 리포트 | 원 설계서 21장(Jinja2 HTML 리포트)과 1:1 대응 | 종목 추가/삭제 같은 CRUD UI를 별도로 구현해야 함 (폼+엔드포인트 다수) |
| **Streamlit (권장)** | `st.data_editor`로 종목 CRUD, 점수 테이블 정렬/뱃지를 적은 코드로 구현. Hub의 기존 서비스 4개 중 3개(MLT/MFTS/MSS)가 이미 Streamlit — 배포/health 관례가 검증되어 있음 | 원 설계서의 "정적 HTML 리포트" 산출물과 별개로 화면을 새로 구성해야 함 (다만 Jinja2 리포트는 백테스트 결과 파일로 별도 보관하면 됨) |
| 배치 결과 전용 읽기 UI | 구현 최소 | 요청 2번(종목 추가/삭제/변경 메뉴)을 충족 못함 — 배제 |

### 3.2 결정: **Streamlit**

이유:
1. 요청 2번("종목 추가/삭제/변경 메뉴")은 상호작용 CRUD가 필요 — 정적 HTML 리포트만으로는 불가능.
2. `mfhub_phase4_service_sso_rollout.md` 4장(Track A, MFTS)이 **가장 낮은 통합 비용의 실제 선례**다: 앱 내부 로그인 레이어 없이 Hub 게이트만으로 인증을 끝낸 사례. SwingCycle Radar도 원 설계서 1.2 비목표에 "증권사 주문 연동 없음", 자체 사용자 관리 요구가 없으므로 **MFTS와 동일한 패턴**을 그대로 재사용할 수 있다.
3. Streamlit 계열 health check는 기존 Hub 운영에서 이미 쓰이고 있다 — 단, 정확한 경로는 4.1에서 실측값으로 정정한다(`mfhub_phase1_portal_design.md` 47행의 `/healthz` 표기와 `MoneyFlowHub/run_hub.sh`의 실제 점검 경로가 다름을 확인함).

원 설계서의 Jinja2 HTML 리포트(21장)는 폐기하지 않는다 — Streamlit 앱이 매일 배치 결과를 화면에서 직접 렌더링하고, 정적 HTML은 **이메일 발송/아카이브용 부산물**로 그대로 생성한다(sugup-report의 `daily_leaders_report.py` 패턴과 동일 역할 분리).

---

## 4. Hub 서비스 등록

### 4.1 service_id / 포트 / 경로 / baseUrlPath / health (v0.2에서 실측값으로 정정)

> **v0.1에서 변경**: v0.1은 health 엔드포인트를 `mfhub_phase1_portal_design.md`의 "Streamlit → `/healthz`" 서술만 보고 `GET /scr/healthz`라고 적었다. 그런데 실제 운영 스크립트(`MoneyFlowHub/run_hub.sh:146`)는 MFTS 상태를 `_http_status 8504 /_stcore/health`로 점검하고 있어 **문서와 실제 운영 스크립트가 불일치**했다. 또한 MFTS는 하위 경로 배포를 위해 `run_mfts_local.sh`에서 `WEBAPP_BASE_PATH` 환경변수로 `--server.baseUrlPath`를 주입하는데(41-51행, 107-108행), v0.1에는 이 항목 자체가 없었다. 아래 표는 이 실측값을 반영한다.

| 항목 | 값 |
|---|---|
| service_id | `scr` (SwingCycle Radar) |
| 로컬 개발 포트 | `8505` (기존 mlt=8501, mss=8502, mfgr=8503, mfts=8504 다음 번호) |
| 경로 prefix | `/scr/` |
| 운영 도메인 경로 | `https://mlt-service.n-e.kr/scr` (기존 mss/mfgr/mfts와 동일 방식) |
| **Health 엔드포인트** | **`GET /_stcore/health`** (Streamlit 내장, `run_hub.sh`가 실제로 점검하는 경로) — `mfhub_phase1_portal_design.md`의 `/healthz` 표기는 실제 운영 스크립트와 다르므로 SCR은 실측값(`/_stcore/health`)을 따른다. (Hub 쪽 문서 정정 여부는 이 문서 범위 밖이나, 10장 열린 질문에 기록) |
| **baseUrlPath (운영)** | `WEBAPP_BASE_PATH=scr` → Streamlit 실행 인자 `--server.baseUrlPath scr` (MFTS `run_mfts_local.sh` `_resolve_base_path` 패턴 그대로 포팅) |
| **baseUrlPath (로컬 dev)** | 미설정(root) — `dev_server.py`의 `_SERVICE_LAUNCHERS["/scr/"]["path"]`를 `"/"`로 두고 로컬 Streamlit은 base path 없이 루트에서 실행 (MFTS와 동일 이원화: 로컬은 root, 운영은 nginx가 `/scr/`로 매핑) |

### 4.2 수정이 필요한 파일 (하드코딩 4곳 + 1)

Hub는 서비스 목록을 단일 config가 아니라 아래 4곳에 개별 하드코딩하고 있음이 코드 확인으로 검증됨. `scr` 추가 시 전부 동시에 수정해야 한다.

1. **`MoneyFlowHub/dev_server.py:62`** — `_SERVICE_LAUNCHERS` 딕셔너리에 항목 추가:
   ```python
   "/scr/": {"service_id": "scr", "redirect_url": os.getenv("SCR_LOCAL_URL", ""), "port": 8505, "path": "/"},
   ```
2. **`MoneyFlowHub/portal/index.html:44-83`** — 서비스 테이블에 5번째 행 추가 (아래 9장 UI 참고).
3. **`MoneyFlowHub/portal/admin.html:47`** — `ALL_SERVICES` 배열에 `'scr'` 추가.
4. **`MoneyFlowHub/docs/mfhub_phase2_3_auth_design.md`** (설계 문서 자체 갱신):
   - 142행: `hub_user_services.service_id` 주석에 `'scr'` 추가
   - 187행: `_PATH_TO_SERVICE` 매핑에 `"/scr/": "scr"` 추가
5. (신규) **MFGR 백엔드**의 `_PATH_TO_SERVICE`, `hub_user_services` 등록 로직 — 설계 문서(4번)와 동일 내용을 실제 MFGR 코드에도 반영해야 함(문서만 고치고 코드 반영을 누락하는 실수를 피하기 위해 체크리스트 12장에 명시). 이 항목은 `MoneyFlowHub` 저장소 쪽 변경이므로, SwingCycle Radar 저장소와는 별도 PR로 진행한다.

### 4.3 인증 모델

MFTS Track A(`mfhub_phase4_service_sso_rollout.md` 4장)와 동일하게 처리한다.

- SwingCycle Radar 앱 내부에 로그인 폼을 만들지 않는다.
- `/scr/` 접근은 Hub 게이트(`/hub/auth/verify`)만 통과하면 즉시 진입.
- 로그아웃/미인증 시 Hub 로그인 화면으로 리다이렉트되는 기존 흐름을 그대로 사용.
- 종목 CRUD 등 "쓰기" 동작에 대한 추가 권한 분리(예: admin만 삭제 가능)는 1차 구현 범위에서는 두지 않는다 — Hub에서 `scr` 서비스 권한을 가진 사용자는 전원 CRUD 가능. 필요해지면 Hub의 `role=admin` 클레임을 재사용해 앱 내부에서 분기한다(2차 구현, 지금은 과설계 방지를 위해 보류).

### 4.4 Hub 신원 확인 브리지 (v0.2 신설)

> **v0.1에서 변경**: MFTS Track A 패턴("허브 게이트만 통과하면 됨")은 **읽기 전용**이라 앱이 사용자가 누구인지 알 필요가 없었다. 그러나 SCR은 종목 CRUD의 `updated_by`를 기록해야 하므로 **누가 요청했는지 실제로 식별**해야 한다 — 이건 UI 선택이 아니라 별도의 인증 브리지가 필요한 문제다. v0.1은 "X-Hub-User-Email 헤더를 읽는다"고만 적고 그 헤더가 언제·어떻게 주입되는지, 로컬 개발에서는 무엇으로 대체하는지, 위조를 어떻게 막는지가 없었다.

**근거 조사 결과**: 운영 nginx는 이미 4개 기존 서비스에 대해 이 문제를 풀어놓았다(`mfhub_phase2_3_auth_design.md` 8-2절).

```nginx
# 8-2절 기존 패턴 (mss/mfgr/mfts/mlt 공통) — /scr/ 에도 동일 적용
location /scr/ {
    auth_request      /_hub_verify;
    auth_request_set  $hub_deny_reason  $upstream_http_x_hub_deny_reason;
    auth_request_set  $hub_user_id      $upstream_http_x_hub_user_id;
    auth_request_set  $hub_user_email   $upstream_http_x_hub_user_email;
    error_page 401 = @hub_deny;

    proxy_set_header X-Hub-User-Id    "";   # 클라이언트가 보낸 값 무효화 (스푸핑 방지)
    proxy_set_header X-Hub-User-Id    $hub_user_id;
    proxy_set_header X-Hub-User-Email "";
    proxy_set_header X-Hub-User-Email $hub_user_email;
    proxy_pass http://127.0.0.1:8505/scr/;
}
```

nginx가 `X-Hub-User-*` 헤더를 **먼저 빈 값으로 지운 뒤** verify 결과로 덮어쓰므로, 이 경로로 들어오는 헤더는 클라이언트가 조작할 수 없다 — **단, 이는 Streamlit 프로세스(8505 포트)가 nginx를 거치지 않고 직접 인터넷에 노출되지 않는다는 전제에서만 유효하다.** 운영 배포 시 8505 포트를 외부에 직접 열지 않는 것을 필수 조건으로 못박는다.

**문제는 로컬 개발 환경이다**: `dev_server.py`의 `_launch_service`는 프록시가 아니라 **브라우저 302 리다이렉트**이므로(`dev_server.py:189` `self._redirect(...)`), 로컬에서는 Streamlit 프로세스가 nginx 없이 직접 열리고 `X-Hub-User-Email` 헤더가 전혀 주입되지 않는다. `mfhub_phase4_service_sso_rollout.md` 5.4절이 이미 이 문제를 겪었고 해법도 나와 있다: "로컬 개발에서는 `hub_token` 쿠키 폴백 허용".

`webapp/common/hub_bridge.py` (신규, `mfhub_phase4`의 `hub_bridge.py` 네이밍 재사용 — 코드는 SCR 저장소에서 새로 작성, sugup-report/MLT의 실제 모듈을 import하지 않음):

```python
def resolve_hub_identity(request) -> HubIdentity | None:
    # 1) 운영 경로: nginx가 주입한 헤더를 신뢰 (nginx가 X-Hub-User-* 를 지우고 재주입하므로 안전)
    email = request.headers.get("X-Hub-User-Email")
    if email:
        return HubIdentity(email=email, source="nginx_header")

    # 2) 로컬 개발 경로: hub_token 쿠키를 MFGR에 그대로 전달해 신원을 서버 사이드로 확인
    #    (dev_server.py가 헤더를 주입하지 않으므로, 브라우저가 보낸 쿠키를 직접 사용)
    hub_token = request.cookies.get("hub_token")
    if hub_token:
        resp = httpx.get(f"{MFGR_URL}/hub/auth/me", cookies={"hub_token": hub_token}, timeout=3)
        if resp.status_code == 200:
            return HubIdentity(email=resp.json()["email"], source="dev_cookie_bridge")

    return None  # 신원 확인 실패 — 쓰기 버튼 비활성화, "허브 인증 정보를 확인할 수 없습니다" 표시
```

Streamlit에서 들어오는 요청의 헤더/쿠키는 `st.context.headers` / `st.context.cookies`(Streamlit ≥1.29)로 읽는다. 이 API가 없는 구버전이면 대체 수단을 먼저 검증한다(구현 시 Streamlit 버전 고정 필요 — `pyproject.toml`에 `streamlit>=1.29` 명시).

**쓰기 위조 방지 규칙**:
- `resolve_hub_identity()`가 `None`을 반환하면 종목 관리 탭의 저장 버튼을 비활성화한다 — 신원 불명 상태의 쓰기를 원천 차단.
- `source="dev_cookie_bridge"`로 확인된 신원은 로컬 개발 전용이며, `ENV=production`일 때는 이 경로를 비활성화하고 `nginx_header`만 신뢰한다(운영에서 쿠키 위조로 우회하는 경로 차단).

### 4.5 nginx 반영 필요 사항

Hub 4곳 하드코딩(4.2) 외에, **운영 nginx 설정에도 `/scr/` location 블록 추가가 필요**하다 — 이 항목은 코드 저장소 검색으로는 발견되지 않는다(nginx 설정 파일이 이 워크스페이스에 없고 서버에서 직접 관리됨, `MoneyFlowHub/deploy/mfhub_deploy_checklist.md` 참고). 4.4의 nginx 스니펫을 실제 서버 설정에 반영하는 작업을 Hub 배포 체크리스트에 추가 항목으로 등록해야 한다(담당자는 4.2-5와 동일).

---

## 5. 데이터 저장소 — 2-DB 구조 (명문화)

이전 리뷰에서 지적된 "Supabase vs SQLite 모순"(원 설계서 17-18행 vs 4/7/18장)을 아래와 같이 해소한다.

```text
[Hub 권한/인증 DB]          MFGR PostgreSQL      — hub_users, hub_user_services (기존 그대로, 변경 없음)
[SwingCycle 시세/지표/점수]  SQLite (로컬)         — daily_bars, indicators_daily, pivots,
                                                    cycle_daily, scores_daily, trade_plans/events
                                                    (원 설계서 7장 그대로 유지)
[SwingCycle 절친종목 유니버스] Supabase (Postgres)  — symbols 테이블 (신규, 이 문서 6장)
```

원 설계서 최상단 요구("절친 종목 등 관리가 필요한 항목은 Supabase DB에 관리")는 **"관리(운영 중 추가/삭제/변경)가 필요한 유니버스 테이블만" Supabase로 한정**하고, 나머지 시세/지표/점수/트레이드 데이터는 원 설계서의 SQLite 설계를 그대로 유지한다. 두 DB를 쓰는 이유:

- 유니버스는 사람이 수시로 편집(추가/삭제)하는 **저빈도·저용량 마스터 데이터** → 원격 DB로 관리해야 여러 실행 환경(로컬 배치, Streamlit 앱)이 항상 같은 최신 유니버스를 본다.
- 시세/지표/점수는 **매일 대량 upsert되는 배치 산출물** → 로컬 SQLite가 지연/트래픽 면에서 유리하고, 원 설계서의 look-ahead 방지·재계산 요구사항과도 맞음.

---

## 6. Supabase 스키마

### 6.1 `swingcycle_symbols` 테이블

파일명 규칙(원 설계서 17행, sugup-report `CLAUDE.md` 21.1항 — "소속 서비스+기능이 드러나야 함")에 맞춰 테이블명도 `symbols`가 아니라 `swingcycle_symbols`로 명명한다(Supabase 프로젝트가 다른 서비스와 공유될 가능성 고려).

```sql
CREATE TABLE swingcycle_symbols (
    symbol        TEXT PRIMARY KEY,       -- 6자리 종목코드, zero-padded
    name          TEXT NOT NULL,
    market        TEXT,                   -- KOSPI/KOSDAQ, 시드 시점엔 nullable 허용
    friend_group  TEXT,                   -- 원 설계서 18장 YAML의 group과 동일 의미
    enabled       BOOLEAN NOT NULL DEFAULT TRUE,
    note          TEXT,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_by    TEXT                    -- Hub 이메일 (X-Hub-User-Email 헤더에서 획득)
);
```

- 원 설계서 7.1 `symbols` 테이블과 컬럼을 맞춰, SwingCycle 배치가 Supabase에서 이 테이블을 읽어와 로컬 SQLite `symbols` 테이블로 매 실행 시 동기화(read-through cache)하는 구조로 간다. 즉 **Supabase가 원본(source of truth), 로컬 SQLite `symbols`는 매 배치 실행 시 갱신되는 캐시**다.
- RLS(Row Level Security): Hub 인증을 통과한 요청만 Supabase에 닿으므로, 앱 서버 측에서 `SUPABASE_SERVICE_KEY`(sugup-report의 `webapp/common/supabase_helper.py` 패턴과 동일)를 사용해 RLS를 우회하는 서버 사이드 접근으로 시작한다. 사용자별 세분화된 RLS는 1차 구현 범위 밖.

### 6.2 환경변수 (sugup-report 기존 관례 재사용, 코드는 별도 복사)

```dotenv
SUPABASE_URL=
SUPABASE_SERVICE_KEY=
```

환경변수 **이름**은 `sugup-report/webapp/common/supabase_helper.py`와 동일하게 맞춘다 — 같은 wt 워크스페이스 관례를 따라 혼동을 피하기 위함이다. 다만 1.1항 원칙에 따라 **이 헬퍼 코드 자체는 SwingCycle Radar 저장소 안에 복사해 독립적으로 보유**하며, `sugup-report`의 모듈을 직접 import하지 않는다. Supabase 프로젝트 자체를 sugup-report와 공유할지 별도로 팔지는 10장 열린 질문 참고.

---

## 7. 절친종목 초기 시드 절차 및 동기화 정책

### 7.1 문제

`SwingCycle/docs/절친종목.csv`는 실측 결과:
- UTF-8 **BOM 포함** (`EF BB BF`), 헤더 `종목명,종목코드`
- **53개 종목**, `group` 컬럼 없음
- 원 설계서 18장 `config/friend_universe.yml` 예시는 **동일 53개 종목 + group**을 이미 갖고 있음 (심텍→pcb, 로보티즈→robot 등)

### 7.2 시드 방법 (v0.2에서 변경 — 문서 파싱 → 실제 config 파일)

> **v0.1에서 변경**: v0.1은 group 매핑을 "원 설계서 18장의 마크다운 YAML 블록을 파싱"하는 방식으로 제안했다. 설계 문서는 런타임 데이터 소스가 아니고 마크다운 포맷이 조금만 바뀌어도(코드블록 위치, 들여쓰기 등) 파서가 깨지므로 재현성/테스트성이 약하다. **`config/friend_universe.yml`을 실제 파일로 승격**해 이미 생성해뒀다: [`SwingCycle/config/friend_universe.yml`](/home/mhhan/projects/wt/SwingCycle/config/friend_universe.yml) — 원 설계서 18장 YAML 블록의 53개 항목을 그대로 옮긴 것으로, 이제부터 이 파일이 초기 시드의 유일한 group 출처다(설계 문서 재파싱 불필요).

```python
import pandas as pd
import yaml

# 1) CSV: BOM 안전 처리 (실제 절친종목.csv 헤더/종목코드 원본)
df = pd.read_csv("docs/절친종목.csv", encoding="utf-8-sig", dtype={"종목코드": str})
df["종목코드"] = df["종목코드"].str.zfill(6)

# 2) group 매핑: config/friend_universe.yml (실 파일, 마크다운 파싱 아님)
with open("config/friend_universe.yml", encoding="utf-8") as f:
    universe_seed = yaml.safe_load(f)["symbols"]
group_map = {row["symbol"]: row["group"] for row in universe_seed}

# 3) 두 소스 정합성 검증 — 종목코드 집합이 다르면 즉시 실패 (조용히 넘어가지 않음)
csv_symbols = set(df["종목코드"])
yaml_symbols = set(group_map)
if csv_symbols != yaml_symbols:
    raise ValueError(f"CSV/YAML 종목코드 불일치: CSV-only={csv_symbols - yaml_symbols}, "
                      f"YAML-only={yaml_symbols - csv_symbols}")

# 4) Supabase 시드
rows = [
    {
        "symbol": row["종목코드"],
        "name": row["종목명"],
        "friend_group": group_map[row["종목코드"]],
        "enabled": True,
    }
    for _, row in df.iterrows()
]
supabase.table("swingcycle_symbols").upsert(rows).execute()
```

- `scripts/seed_friend_universe.py`(원 설계서 5장 디렉토리 구조에 이미 이름이 지정돼 있음)가 이 로직을 담당하며, **최초 1회 시드 전용**이다 — 시드 이후 종목 추가/삭제/그룹 변경은 8장 CRUD 화면을 통해 Supabase에서 직접 이뤄진다(`config/friend_universe.yml`은 재실행하지 않음, 재실행 시 CRUD로 이미 바뀐 내용을 덮어쓰지 않도록 스크립트에 `--force` 플래그 없이는 기존 Supabase row가 있으면 skip하는 가드를 둔다).
- market(KOSPI/KOSDAQ) 필드는 초기 시드에는 비워두고, 최초 배치 수집(KRX 응답)에서 역으로 채워 넣거나 수동 보정한다 — CSV/YAML 어디에도 시장 구분이 없기 때문.

### 7.3 Supabase → SQLite 동기화 정책 (v0.2 신설)

> **v0.1에서 변경**: v0.1은 "Supabase가 원본, 로컬 SQLite `symbols`는 매 배치 실행 시 갱신되는 캐시"라고만 적고, 삭제/비활성/이름 변경/그룹 변경/활성 트레이드 보유 종목 처리 규칙이 없었다. 아래로 확정한다.

매일 배치(`swingcycle collect` 시작 시점)마다 Supabase `swingcycle_symbols` 전체를 읽어와 로컬 SQLite `symbols`에 다음 규칙으로 반영한다:

| Supabase 쪽 변경 | 로컬 SQLite `symbols` 반영 | 시세/지표/점수/trade_plans 처리 |
|---|---|---|
| 신규 종목 추가 (`enabled=true`) | upsert (신규 insert) | 다음 backfill 대상에 포함 |
| 이름/그룹 변경 | upsert (덮어쓰기) | 영향 없음 — 과거 `daily_bars` 등은 `symbol`(코드)로만 join하므로 이름/그룹 변경이 과거 데이터를 깨지 않음 |
| `enabled=false` (soft-disable) | 로컬도 `enabled=0`으로 동기화 | 신규 수집/스코어링 대상에서 제외. **단, 해당 종목에 `trade_plans.status='ACTIVE'` 레코드가 있으면 collect/analyze는 계속 수행**해 기존 포지션의 STOP/EXIT 판정을 이어간다 — 비활성화는 "신규 진입 금지"를 의미하지, "기존 포지션 방치"를 의미하지 않는다(원 설계서 2.3 "손절 = 종목 포기 X" 철학과 동일). |
| Supabase에서 **완전 삭제**(하드 delete) | 로컬은 **하드 삭제하지 않는다** — `enabled=0` + `deleted_upstream=1`(SQLite `symbols`에 컬럼 추가)로 반영 | 위 `enabled=false` 처리와 동일하게 ACTIVE 플랜은 계속 추적. 과거 `daily_bars`/`scores_daily`/`trade_plans` 등 이력 테이블은 원 설계서 16.4 "RESET이 지우지 않는 것"과 동일 원칙으로 **절대 삭제하지 않는다**. |
| Supabase 쪽 활성 플랜 보유 종목을 실수로 삭제/비활성화 | 8장 CRUD 화면에서 **삭제/비활성 시도 시 로컬 SQLite에 ACTIVE 플랜이 있는지 먼저 조회해 경고 표시**(차단은 아님 — 사용자가 의도적으로 비활성화할 수도 있으므로 확인 다이얼로그만 추가) | 위와 동일 |

이 정책으로 "Supabase에서 지웠는데 로컬 SQLite/score/trade_plan이 어떻게 되는지"가 명확해진다: **유니버스 마스터(이름/그룹/활성여부)는 Supabase를 그대로 따라가지만, 한번 쌓인 시세/지표/점수/트레이드 이력은 유니버스 상태와 무관하게 절대 삭제되지 않는다.**

`symbols` 테이블의 `deleted_upstream` 컬럼은 원 설계서 v1.1 7.1장에 이미 반영했다(교차 반영 완료).

---

## 8. 종목 관리 메뉴 (Streamlit)

- 신규 탭: **"종목 관리"** (Hub 게이트 통과 후 접근 가능한 SwingCycle Radar 앱 내부 탭 중 하나)
- 구현: `st.data_editor(df, num_rows="dynamic")`로 Supabase `swingcycle_symbols` 테이블을 그대로 편집 — 추가(빈 행 입력)/삭제(행 삭제)/변경(셀 수정) 후 "저장" 버튼 클릭 시 diff만 계산해 Supabase에 upsert/delete 반영.
- 저장 시 `updated_by`에 4.4의 `resolve_hub_identity()`가 반환한 이메일을 기록한다. 신원 확인에 실패하면(운영에서 nginx 헤더 없음, 로컬에서 `hub_token` 쿠키도 없음) 저장 버튼 자체를 비활성화한다 — `updated_by`가 비어있는 채로 저장되는 경로를 만들지 않는다.
- 종목 삭제는 하드 delete 대신 `enabled=false` soft-disable을 기본값으로 제공하고, 화면에 "완전 삭제" 별도 확인 버튼을 둔다 — 원 설계서 24.7 체크리스트의 "손절된 종목을 blacklist하지 않는다"는 원칙과 마찬가지로, 유니버스에서도 실수로 인한 영구 삭제를 방지하기 위함.

---

## 9. UI 구성 — Hub 표에 추가

`portal/index.html`은 카드형이 아니라 **표(table) 기반 런처**임을 확인했으므로(44-83행), 기존 4개 행과 동일한 형식으로 5번째 행만 추가한다. Phase 1 문서(`mfhub_phase1_portal_design.md` 199행)의 카드 UI는 채택되지 않은 별도 안이므로 참고하지 않는다.

```html
<tr>
  <td>5</td>
  <td class="tool-id">SCR</td>
  <td>절친종목 사이클·진입점수 레이더</td>
  <td><a href="https://mlt-service.n-e.kr/scr" target="_blank" rel="noopener" onclick="trackService('scr', '/scr/')">열기</a></td>
  <td class="dev-col"><a href="/scr/" data-dev-port="8505" data-dev-path="/" target="_blank" rel="noopener" onclick="trackService('scr', '/scr/')">열기</a></td>
</tr>
```

앱 내부 화면 구성은 MFTS/MSS 스타일(사이드바 탭 전환)을 참고한다:

1. **대시보드** — 원 설계서 21장 카드 정렬(STOP/EXIT → ENTRY → ADD → TAKE_PROFIT → READY → WAIT), score/reason code 표시
2. **종목 관리** — 8장의 CRUD 화면
3. **백테스트/검증** — 원 설계서 22장 A/B/C 비교 결과 열람 (읽기 전용)

---

## 10. 열린 질문 / 확정 필요 (구현 착수 전)

| # | 질문 | 권장 default | 결정 필요 시점 |
|---|---|---|---|
| 1 | Supabase 프로젝트를 sugup-report와 공유할지, SwingCycle 전용으로 새로 팔지 | 전용 신규 프로젝트 (서비스 간 데이터 경계 분리, 장애 격리) | 6.2 구현 전 |
| ~~2~~ | ~~`market`(KOSPI/KOSDAQ) 컬럼을 초기 시드 때 채울지~~ — **해결됨**: 비워두고 최초 배치에서 역보정(원 설계서 v1.1 6.6 "symbols.market 역보정 규칙"). 로컬 SQLite `symbols.market`도 NOT NULL을 제거해 Supabase 시드 시점의 NULL과 스키마 충돌이 없도록 함(v1.1 7.1) | — | 해결됨 |
| 3 | 종목 CRUD 쓰기 권한을 전체 `scr` 사용자에게 줄지, admin으로 제한할지 | 1차: 전체 허용, 2차: admin 제한 검토 | 8장 구현 시 |
| 4 | MFGR 백엔드의 `_PATH_TO_SERVICE`/`hub_user_services` 실제 코드 반영 담당자, `/scr/` nginx location(4.5) 추가 담당자 | Hub 통합 작업자가 SwingCycle 작업과 별도 PR/서버 작업으로 진행 | 4.2-5, 4.5 작업 시 |
| 5 | `sugup-report`와 SwingCycle Radar 간 KRX 로그인 빈도 조율 — **구체 규격은 확정됨**(원 설계서 v1.1 6.1.1: `~/.krx_shared/login_state.json` + `fcntl.flock` + `KRX_LOGIN_MIN_INTERVAL_SEC`), 단 `sugup-report` 저장소 쪽에 동일 프로토콜을 반영하는 작업은 SwingCycle Radar 구현 범위 밖 | `sugup-report` 쪽에 6.1.1 규격을 반영하는 별도 작업 티켓 필요 | KRX 연동 모듈 포팅 시 |
| 6 | `mfhub_phase1_portal_design.md` 47행의 "Streamlit → `/healthz`" 표기가 실제 운영 스크립트(`run_hub.sh`가 쓰는 `/_stcore/health`)와 다름 — Hub 쪽 문서 정정 필요 | SCR 구현과는 무관하게 Hub 문서 정정을 별도 이슈로 등록 | Hub 문서 관리자 확인 시 |
| 7 | Streamlit 버전이 `st.context.headers`/`st.context.cookies`(4.4 브리지가 의존)를 지원하는 ≥1.29인지 확정 | `pyproject.toml`에 `streamlit>=1.29` 고정 | 4.4 구현 시 |

---

## 11. 실행 순서 제안

1. `SwingCycle/` 안에서 git 초기화 + GitHub 원격(`SwingCycleRadar.git`) 연결, 2장 디렉토리 구조로 스캐폴딩
2. 원 설계서 v1.1 Sprint 1~3 (수집/지표/Pivot) 로컬 SQLite 기준으로 우선 구현 — `krx_direct` 포팅 포함, Hub 통합과 무관하게 먼저 진행 가능
3. Supabase `swingcycle_symbols` 테이블 생성 + `config/friend_universe.yml` + `scripts/seed_friend_universe.py`로 53종목 시드, 7.3 동기화 배치 로직 구현
4. Streamlit 앱 골격 + `webapp/common/hub_bridge.py`(4.4) 구현 + baseUrlPath 이원화(4.1) 적용
5. Hub 4곳 동시 수정(4.2) + nginx `/scr/` location 추가(4.5) + `SCR_LOCAL_URL` 등 dev 환경변수 등록
6. 종목 관리 탭(8장) 구현 및 CRUD + 신원 확인 브리지 검증 (운영 헤더 경로/로컬 쿠키 경로 둘 다)
7. 대시보드 탭 연결 (원 설계서 Sprint 4~6 완료 후)

---

## 12. Definition of Done (이 문서 범위)

```text
[저장소]      SwingCycle/ 이 SwingCycleRadar.git 원격을 가진 독립 git 저장소로 존재
[런타임]      Streamlit 앱이 GET /_stcore/health 200 응답, 운영은 --server.baseUrlPath scr로 기동
[Hub 등록]    dev_server.py / portal/index.html / admin.html / auth 설계문서·MFGR 코드 4+1곳 모두 scr 반영
[nginx]       /scr/ location에 auth_request + X-Hub-User-* 헤더 주입/무효화 패턴 반영 (4.4/4.5)
[인증]        운영: nginx 헤더 신뢰 / 로컬: hub_token 쿠키→MFGR 조회 브리지, 신원 미확인 시 쓰기 차단
[유니버스]    config/friend_universe.yml 기준으로 Supabase swingcycle_symbols에 53종목 시드 완료(group 포함),
              앱에서 추가/삭제/변경 가능, 7.3 동기화 정책(삭제/비활성/활성플랜 보호)이 배치에 반영됨
[코드 재사용] sugup-report 모듈은 복사본으로만 존재, 공용 import 없음
[문서]        2-DB 구조 및 KRX 연동 방식(krx_direct)이 원 설계서 v1.1과 이 문서에 일관되게 반영됨
```
