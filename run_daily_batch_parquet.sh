#!/usr/bin/env bash
# 매일 배치(MFTS parquet 소스 버전): collect-parquet -> decide -> report.
#
# run_daily_batch.sh와 거의 동일하지만 1단계가 다르다 — KRX를 직접 두드리는 대신
# 같은 서버에 배포된 MFTS가 장마감 후 이미 갱신해둔 로컬 parquet 캐시를 읽는다
# (MFTS_PARQUET_DIR). SwingCycle과 MFTS가 같은 서버에 없으면 이 스크립트 대신
# run_daily_batch.sh(KRX 직접수집)를 써야 한다.
#
# **2026-08-13 스케줄 변경**: MFTS의 전종목 수집 크론이(원래 18:30 KST 시작 →
# 22:40경 완료였던 것에서) KST 01:00 시작(직전 거래일 데이터, 약 4시간 소요 →
# 04:50~05:00경 완료)으로 바뀌었다. 이 스크립트는 여전히 23:30 KST(같은 날 밤)에
# "오늘" 날짜로 돌고 있었는데, MFTS가 "오늘" 데이터를 실제로 채우는 시점은 그
# 다음날 새벽이라 매번 전 종목이 stale 처리되는 장애가 발생했다(2026-08-11,
# 08-12 실측 — universe 62종목 전부 skipped_no_data). 그래서:
#   1) 기본 대상일을 "오늘"이 아니라 `swingcycle latest-trading-day`(MFTS의
#      직전 거래일 계산 정책과 동일)로 바꿨다 — 아래 참고.
#   2) Oracle 크론 시각도 MFTS 완료(~05:00) 이후로 옮겨야 한다(아래 최신
#      등록 예 참고, 요일 범위는 2026-08-16 변경분 반영됨).
# (기존 `30 23 * * 1-5` 등록은 아래 크론으로 교체해야 한다 — crontab -e로 직접 반영 필요)
#
# **2026-08-16 스케줄 변경**: MFTS/SwingCycle 크론 요일 범위를 `1-5`(평일)에서
# `1-6`(월~토)로 넓혔다. 기존 `1-5`에서는 금요일 장 마감분을 처리하는 회차가
# 토요일(주말이라 크론 미실행)에야 도는 구조라, 다음 크론이 도는 월요일까지
# 최대 사흘간 대시보드에 금요일 데이터가 안 보이는 지연이 있었다(데이터
# 유실은 아님 — `latest_completed_trading_day()`의 주말 스킵 로직이 월요일
# 실행 시 금요일을 정상적으로 다시 찾아내 매주 자동으로 캐치업은 됐다.
# 2026-08-14 발생분은 토요일인 2026-08-16에 수동 보정 배치로 즉시 메웠다).
# `1-6`으로 넓히면 토요일 새벽에 곧바로 전날(금요일) 데이터를 처리해 지연이
# 최대 하루로 줄어든다.
#
#   30 5 * * 1-6 /home/ubuntu/projects/SwingCycle/run_daily_batch_parquet.sh \
#       >> /home/ubuntu/projects/SwingCycle/logs/cron_daily_batch_parquet.log 2>&1
#
# 사용: bash run_daily_batch_parquet.sh [YYYY-MM-DD] [MFTS_PARQUET_DIR]
#       (날짜 생략 시 `swingcycle latest-trading-day`가 계산한 직전 거래일 사용)

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "${SCRIPT_DIR}"

SWINGCYCLE="${SCRIPT_DIR}/.venv/bin/swingcycle"
LOG_DIR="${SCRIPT_DIR}/logs"
mkdir -p "${LOG_DIR}"
LOG_FILE="${LOG_DIR}/daily_batch_parquet_$(date +%Y%m).log"

_log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*" | tee -a "${LOG_FILE}"
}

if [[ ! -x "${SWINGCYCLE}" ]]; then
    _log "[ERROR] swingcycle 실행파일 없음: ${SWINGCYCLE} — .venv 설치 확인 필요"
    exit 1
fi

# 날짜 미지정 시 "오늘"이 아니라 MFTS의 직전 거래일 계산 정책과 동일한
# `swingcycle latest-trading-day`를 기본값으로 쓴다(위 2026-08-13 주석 참고).
TRADE_DATE="${1:-$("${SWINGCYCLE}" latest-trading-day)}"
PARQUET_DIR="${2:-${MFTS_PARQUET_DIR:-${SCRIPT_DIR}/../MFTS/@RUN/cache/parquet}}"
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
