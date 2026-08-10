#!/usr/bin/env bash
# 매일 배치(MFTS parquet 소스 버전): collect-parquet -> decide -> report.
#
# run_daily_batch.sh와 거의 동일하지만 1단계가 다르다 — KRX를 직접 두드리는 대신
# 같은 서버에 배포된 MFTS가 장마감 후 이미 갱신해둔 로컬 parquet 캐시를 읽는다
# (MFTS_PARQUET_DIR). SwingCycle과 MFTS가 같은 서버에 없으면 이 스크립트 대신
# run_daily_batch.sh(KRX 직접수집)를 써야 한다.
#
# Oracle 서버 크론 등록 예 — MFTS 수집 크론은 18:30 KST에 시작하지만 전종목(약 2,800개)
# 수집이라 실제로는 22:40~22:46 KST경 완료된다(2026-08-03~08-07 로그 실측). 03:30/04:00대에
# 돌리면 아직 오늘자 parquet이 안 채워져 있어 전량 stale 처리된다(2026-08-09 최초 배포 때
# 06:05 KST 실행 시 실제로 겪은 문제) — 반드시 MFTS 완료 이후로 여유를 두고 기동할 것:
#   30 23 * * 1-5 /home/ubuntu/projects/SwingCycle/run_daily_batch_parquet.sh \
#       >> /home/ubuntu/projects/SwingCycle/logs/cron_daily_batch_parquet.log 2>&1
#
# 사용: bash run_daily_batch_parquet.sh [YYYY-MM-DD] [MFTS_PARQUET_DIR]
#       (둘 다 생략 시 오늘 날짜 / ../MFTS/@RUN/cache/parquet)

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "${SCRIPT_DIR}"

SWINGCYCLE="${SCRIPT_DIR}/.venv/bin/swingcycle"
LOG_DIR="${SCRIPT_DIR}/logs"
mkdir -p "${LOG_DIR}"

TRADE_DATE="${1:-$(date +%Y-%m-%d)}"
PARQUET_DIR="${2:-${MFTS_PARQUET_DIR:-${SCRIPT_DIR}/../MFTS/@RUN/cache/parquet}}"
LOG_FILE="${LOG_DIR}/daily_batch_parquet_$(date +%Y%m).log"

_log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*" | tee -a "${LOG_FILE}"
}

if [[ ! -x "${SWINGCYCLE}" ]]; then
    _log "[ERROR] swingcycle 실행파일 없음: ${SWINGCYCLE} — .venv 설치 확인 필요"
    exit 1
fi
if [[ ! -d "${PARQUET_DIR}" ]]; then
    _log "[ERROR] parquet 캐시 디렉터리 없음: ${PARQUET_DIR}"
    exit 1
fi

_log "=== daily batch(parquet) 시작 (trade_date=${TRADE_DATE}, parquet_dir=${PARQUET_DIR}) ==="

_log "[1/3] collect-parquet"
if ! "${SWINGCYCLE}" collect-parquet --date "${TRADE_DATE}" --parquet-dir "${PARQUET_DIR}" 2>&1 | tee -a "${LOG_FILE}"; then
    _log "[ERROR] collect-parquet 실패 — decide/report 건너뜀"
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

_log "=== daily batch(parquet) 종료 (trade_date=${TRADE_DATE}) ==="
