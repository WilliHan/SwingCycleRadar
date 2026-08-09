#!/usr/bin/env bash
# SCR (SwingCycle Radar) 웹앱 로컬 실행 스크립트
# 지원: start | stop | restart | status
# 포트: 8505

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LOG_DIR="${SCRIPT_DIR}/logs"
mkdir -p "${LOG_DIR}"

APP_LOG="${LOG_DIR}/webapp.log"
APP_PID_FILE="${LOG_DIR}/webapp.pid"
APP_PATTERN="${SCRIPT_DIR}/webapp/app.py"
ACTION="${1:-start}"
PORT=8505

PYTHON="${SCRIPT_DIR}/.venv/bin/python"
STREAMLIT="${SCRIPT_DIR}/.venv/bin/streamlit"

if [[ ! -x "${STREAMLIT}" ]]; then
    echo "[ERROR] venv 없음 — 먼저 setup 실행 (uv sync 또는 pip install -e .)"
    exit 1
fi

_cleanup_pid_file_if_stale() {
    local pid_file="$1"
    if [[ -f "${pid_file}" ]]; then
        local pid
        pid=$(cat "${pid_file}")
        if ! kill -0 "${pid}" 2>/dev/null; then
            rm -f "${pid_file}"
        fi
    fi
}

_is_running() {
    _cleanup_pid_file_if_stale "${APP_PID_FILE}"
    if [[ -f "${APP_PID_FILE}" ]]; then
        local pid
        pid=$(cat "${APP_PID_FILE}")
        if kill -0 "${pid}" 2>/dev/null; then
            return 0
        fi
    fi
    return 1
}

_find_pid() {
    pgrep -u "$(id -u)" -f "${APP_PATTERN}" | head -n 1 || true
}

_start() {
    local streamlit_args

    if _is_running; then
        echo "[SCR] 이미 실행 중 (PID $(cat "${APP_PID_FILE}"))"
        return
    fi
    local existing_pid
    existing_pid=$(_find_pid)
    if [[ -n "${existing_pid}" ]]; then
        echo "[SCR] 이미 실행 중 (pattern match PID ${existing_pid})"
        return
    fi

    cd "${SCRIPT_DIR}"
    export PYTHONPATH="${SCRIPT_DIR}:${SCRIPT_DIR}/src:${PYTHONPATH:-}"
    streamlit_args=(
        run "webapp/app.py"
        --server.port "${PORT}"
        --server.headless true
    )
    if [[ -n "${WEBAPP_BASE_PATH:-}" ]]; then
        streamlit_args+=(--server.baseUrlPath "${WEBAPP_BASE_PATH#/}")
    fi

    nohup "${STREAMLIT}" "${streamlit_args[@]}" >> "${APP_LOG}" 2>&1 &
    echo $! > "${APP_PID_FILE}"

    sleep 2
    if _is_running; then
        echo "[SCR] 시작됨 (PID $(cat "${APP_PID_FILE}"), 포트 ${PORT}) — 로그: ${APP_LOG}"
        echo "      접속: http://localhost:${PORT}"
    else
        echo "[SCR] 시작 실패 — 로그 확인: ${APP_LOG}"
        tail -n 15 "${APP_LOG}" 2>/dev/null || true
        rm -f "${APP_PID_FILE}"
    fi
}

_stop() {
    local stopped=0
    if [[ -f "${APP_PID_FILE}" ]]; then
        local pid
        pid=$(cat "${APP_PID_FILE}")
        if kill -0 "${pid}" 2>/dev/null; then
            kill "${pid}" 2>/dev/null || true
            echo "[SCR] 종료됨 (PID ${pid})"
            stopped=1
        fi
        rm -f "${APP_PID_FILE}"
    fi

    local pattern_pid
    pattern_pid=$(_find_pid)
    if [[ -n "${pattern_pid}" ]]; then
        kill "${pattern_pid}" 2>/dev/null || true
        echo "[SCR] 종료됨 (pattern PID ${pattern_pid})"
        stopped=1
    fi

    if [[ ${stopped} -eq 0 ]]; then
        echo "[SCR] 실행 중인 프로세스가 없습니다."
    fi
}

_status() {
    if _is_running; then
        echo "[SCR] 실행 중 (PID $(cat "${APP_PID_FILE}"), 포트 ${PORT})"
    else
        local pid
        pid=$(_find_pid)
        if [[ -n "${pid}" ]]; then
            echo "[SCR] 실행 중 (pattern PID ${pid}, 포트 ${PORT})"
        else
            echo "[SCR] 미실행"
        fi
    fi
}

case "${ACTION}" in
    start)
        _start
        ;;
    stop)
        _stop
        ;;
    restart)
        _stop
        sleep 1
        _start
        ;;
    status)
        _status
        ;;
    *)
        echo "사용법: bash run_scr_local.sh [start|stop|restart|status]"
        exit 1
        ;;
esac
