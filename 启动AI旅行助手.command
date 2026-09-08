#!/bin/zsh

set -eu

PROJECT_DIR="${0:A:h}"
RUN_DIR="$PROJECT_DIR/.run"
LOG_DIR="$PROJECT_DIR/logs"
cd "$PROJECT_DIR"

PAUSE_ON_FINISH=true
if [[ "${1:-}" == "--no-pause" ]]; then
  PAUSE_ON_FINISH=false
fi

pause_and_exit() {
  print ""
  print "$1"
  if [[ "$PAUSE_ON_FINISH" == true ]]; then
    print "请按回车键关闭窗口。"
    read -r
  fi
  exit 1
}

[[ -x .venv/bin/python && -f .env ]] || pause_and_exit "尚未安装，请先双击“首次安装.command”。"
[[ -d frontend/node_modules ]] || pause_and_exit "管理端依赖不完整，请先运行首次安装。"

mkdir -p "$RUN_DIR" "$LOG_DIR"

is_running() {
  local pid_file="$1"
  [[ -f "$pid_file" ]] || return 1
  local pid_value
  pid_value="$(tr -dc '0-9' < "$pid_file")"
  [[ -n "$pid_value" ]] && kill -0 "$pid_value" 2>/dev/null
}

start_service() {
  local service_name="$1"
  local pid_file="$RUN_DIR/$2.pid"
  local log_file="$LOG_DIR/$2.log"
  shift 2
  if is_running "$pid_file"; then
    print "${service_name}：已在运行"
    return
  fi
  nohup "$@" >"$log_file" 2>&1 &
  print $! > "$pid_file"
  print "${service_name}：已启动"
}

CONFIGURED_HOST="$(sed -n 's/^APP_HOST=//p' .env | head -n 1)"
if [[ -z "$CONFIGURED_HOST" || "$CONFIGURED_HOST" == "0.0.0.0" ]]; then
  CONFIGURED_HOST="127.0.0.1"
fi

backend_is_ready() {
  curl -fsS --max-time 3 http://127.0.0.1:8000/health >/dev/null 2>&1 \
    || curl -fsS --max-time 3 "http://${CONFIGURED_HOST}:8000/health" >/dev/null 2>&1
}

print "== 启动 AI 旅行助手 =="

if curl -fsS --max-time 3 http://127.0.0.1:8100/health >/dev/null 2>&1; then
  print "搜索 MCP：已在运行"
else
  start_service "搜索 MCP" search env PYTHONPATH="$PROJECT_DIR" \
    .venv/bin/python -m uvicorn backend.mcp_servers.search_server.server:app \
    --host 127.0.0.1 --port 8100
fi

if command -v nc >/dev/null 2>&1 && nc -z 127.0.0.1 8200 >/dev/null 2>&1; then
  print "12306 MCP：已在运行"
elif [[ -x .venv-12306/bin/mcp-12306 ]]; then
  start_service "12306 MCP" railway env DEBUG=false SERVER_HOST=127.0.0.1 SERVER_PORT=8200 \
    .venv-12306/bin/mcp-12306
else
  print "12306 MCP：未安装，跨城火车查询暂不可用"
fi

if backend_is_ready; then
  print "FastAPI 后端：已在运行"
else
  start_service "FastAPI 后端" backend env PYTHONPATH="$PROJECT_DIR" \
    .venv/bin/python -m uvicorn backend.app.main:app \
    --host 0.0.0.0 --port 8000
fi

BACKEND_PROXY_URL="http://127.0.0.1:8000"
if ! curl -fsS --max-time 3 http://127.0.0.1:8000/health >/dev/null 2>&1; then
  if curl -fsS --max-time 3 "http://${CONFIGURED_HOST}:8000/health" >/dev/null 2>&1; then
    BACKEND_PROXY_URL="http://${CONFIGURED_HOST}:8000"
  fi
fi

if curl -fsS --max-time 3 http://127.0.0.1:5173/ >/dev/null 2>&1; then
  print "管理端：已在运行"
else
  start_service "管理端" frontend env DEEPTRAVEL_BACKEND_URL="$BACKEND_PROXY_URL" \
    npm --prefix frontend run dev -- --host 0.0.0.0
fi

print ""
print "正在等待后端就绪…"
backend_ready=false
for attempt in {1..30}; do
  if backend_is_ready; then
    backend_ready=true
    break
  fi
  sleep 1
done

if [[ "$backend_ready" == true ]]; then
  BACKEND_DISPLAY_HOST="127.0.0.1"
  if ! curl -fsS --max-time 3 http://127.0.0.1:8000/health >/dev/null 2>&1; then
    BACKEND_DISPLAY_HOST="$CONFIGURED_HOST"
  fi
  print "启动完成："
  print "  管理端  http://127.0.0.1:5173/"
  print "  后端状态  http://${BACKEND_DISPLAY_HOST}:8000/health"
  open http://127.0.0.1:5173/ >/dev/null 2>&1 || true
else
  pause_and_exit "后端未在 30 秒内就绪，请查看 logs/backend.log。"
fi

print ""
print "服务已在后台运行。停止时双击“停止AI旅行助手.command”。"
if [[ "$PAUSE_ON_FINISH" == true ]]; then
  print "请按回车键关闭本窗口。"
  read -r
fi
