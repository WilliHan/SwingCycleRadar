#!/usr/bin/env bash
# 매일 배치: collect -> decide -> report (20장 1~3단계 순차 실행).
#
# Windows Task Scheduler + WSL 연결은 sugup-report와 동일 패턴을 따른다
# (docs/operations 참고할 것 — sugup-report/docs/operations/WINDOWS_TASK_SCHEDULER_WSL_AUTORUN.md):
#   wsl.exe -d <배포판명> -- bash /home/mhhan/projects/wt/SwingCycle/run_daily_batch.sh
#
# 사용: bash run_daily_batch.sh [YYYY-MM-DD]   (생략 시 오늘 날짜)
#
# 각 단계(collect/decide/report)는 독립적으로 idempotent하므로, 이 스크립트가
# 중간에 실패해도 재실행하면 이미 끝난 단계는 자동으로 스킵/재확인만 하고 넘어간다
# (decide는 scores_daily 존재 여부로, report는 저장 파일을 그냥 덮어쓰는 방식으로).
#
# 휴장일 판정은 각 파이썬 단계 내부(data/trading_calendar.py)가 한다 — 현재는
# 주말만 판정하는 최소 구현이라(공휴일 캘린더 연동은 별도 후속 작업), 평일인
# 공휴일에는 이 스크립트가 실행은 되지만 collect가 빈 데이터를 받게 될 수 있다.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "${SCRIPT_DIR}"

SWINGCYCLE="${SCRIPT_DIR}/.venv/bin/swingcycle"
LOG_DIR="${SCRIPT_DIR}/logs"
mkdir -p "${LOG_DIR}"

TRADE_DATE="${1:-$(date +%Y-%m-%d)}"
LOG_FILE="${LOG_DIR}/daily_batch_$(date +%Y%m).log"

_log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*" | tee -a "${LOG_FILE}"
}

if [[ ! -x "${SWINGCYCLE}" ]]; then
    _log "[ERROR] swingcycle 실행파일 없음: ${SWINGCYCLE} — .venv 설치 확인 필요"
    exit 1
fi

_log "=== daily batch 시작 (trade_date=${TRADE_DATE}) ==="

_log "[1/3] collect"
if ! "${SWINGCYCLE}" collect --date "${TRADE_DATE}" 2>&1 | tee -a "${LOG_FILE}"; then
    _log "[ERROR] collect 실패 — decide/report 건너뜀"
    exit 1
fi

_log "[2/3] decide"
if ! "${SWINGCYCLE}" decide --date "${TRADE_DATE}" 2>&1 | tee -a "${LOG_FILE}"; then
    _log "[ERROR] decide 실패 — report 건너뜀"
    exit 1
fi

_log "[3/3] report"
if ! "${SWINGCYCLE}" report --date "${TRADE_DATE}" 2>&1 | tee -a "${LOG_FILE}"; then
    _log "[ERROR] report 실패"
    exit 1
fi

_log "=== daily batch 종료 (trade_date=${TRADE_DATE}) ==="
