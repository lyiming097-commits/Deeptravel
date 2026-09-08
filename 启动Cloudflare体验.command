#!/bin/zsh

set -eu

PROJECT_DIR="${0:A:h}"
RUN_DIR="$PROJECT_DIR/.run"
LOG_DIR="$PROJECT_DIR/logs"
TUNNEL_LOG="$LOG_DIR/cloudflared.log"
PID_FILE="$RUN_DIR/cloudflared.pid"
URL_FILE="$RUN_DIR/cloudflared.url"
cd "$PROJECT_DIR"

# Finder 双击脚本时 PATH 通常不包含 Homebrew；补充 Apple Silicon 和 Intel 的
# 常见安装目录，让 brew/cloudflared 在图形化启动和终端启动下行为一致。
for brew_bin in /opt/homebrew/bin /usr/local/bin; do
  if [[ -x "$brew_bin/brew" ]]; then
    export PATH="$brew_bin:$PATH"
    break
  fi
done

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

mkdir -p "$RUN_DIR" "$LOG_DIR"

is_running() {
  local pid_file="$1"
  [[ -f "$pid_file" ]] || return 1
  local pid_value
  pid_value="$(tr -dc '0-9' < "$pid_file")"
  [[ -n "$pid_value" ]] && kill -0 "$pid_value" 2>/dev/null
}

extract_url() {
  [[ -f "$TUNNEL_LOG" ]] || return 0
  # quick tunnel 的 URL 会写在 stdout/stderr 中；只接受 Cloudflare 临时域名，
  # 避免把日志里的文档链接误当成 API 地址。
  grep -Eo 'https://[[:alnum:]-]+\.trycloudflare\.com' "$TUNNEL_LOG" 2>/dev/null | tail -n 1 || true
}

backend_is_ready() {
  curl -fsS --max-time 5 http://127.0.0.1:8000/health >/dev/null 2>&1 \
    || curl -fsS --max-time 5 "http://${CONFIGURED_HOST}:8000/health" >/dev/null 2>&1
}

backend_origin() {
  if curl -fsS --max-time 5 http://127.0.0.1:8000/health >/dev/null 2>&1; then
    print -r -- "http://127.0.0.1:8000"
  elif curl -fsS --max-time 5 "http://${CONFIGURED_HOST}:8000/health" >/dev/null 2>&1; then
    print -r -- "http://${CONFIGURED_HOST}:8000"
  fi
}

print "== AI 旅行助手·Cloudflare 临时真机调试 =="

[[ -f .env && -x .venv/bin/python ]] || pause_and_exit "尚未完成首次安装，请先双击“首次安装.command”。"

CONFIGURED_HOST="$(sed -n 's/^APP_HOST=//p' .env | head -n 1)"
if [[ -z "$CONFIGURED_HOST" || "$CONFIGURED_HOST" == "0.0.0.0" ]]; then
  CONFIGURED_HOST="127.0.0.1"
fi

if ! backend_is_ready; then
  print "本地后端尚未启动，正在启动项目服务…"
  "$PROJECT_DIR/启动AI旅行助手.command" --no-pause || pause_and_exit "项目服务启动失败，请查看 logs/backend.log。"
  backend_is_ready || pause_and_exit "后端仍未就绪，请查看 logs/backend.log。"
fi

BACKEND_ORIGIN="$(backend_origin)"
[[ -n "$BACKEND_ORIGIN" ]] || pause_and_exit "无法确定后端监听地址，请检查 8000 端口和 logs/backend.log。"

if ! command -v cloudflared >/dev/null 2>&1; then
  if command -v brew >/dev/null 2>&1; then
    print "未检测到 cloudflared，正在通过 Homebrew 安装…"
    brew install cloudflared || pause_and_exit "cloudflared 安装失败。可手动执行：brew install cloudflared"
  else
    pause_and_exit "未找到 cloudflared。请先安装 Homebrew，然后执行：brew install cloudflared"
  fi
fi

# 已有隧道时复用，避免每次点击都生成新地址；如果日志中没有地址则清理并重启。
PUBLIC_URL=""
if is_running "$PID_FILE"; then
  PUBLIC_URL="$(extract_url)"
  if [[ -n "$PUBLIC_URL" ]]; then
    print "Cloudflare Tunnel：已在运行"
  else
    old_pid="$(tr -dc '0-9' < "$PID_FILE")"
    [[ -n "$old_pid" ]] && kill "$old_pid" 2>/dev/null || true
    rm -f "$PID_FILE"
  fi
fi

if [[ -z "$PUBLIC_URL" ]]; then
  : > "$TUNNEL_LOG"
  # HTTP/2 只依赖普通 HTTPS 出站连接；相比默认 QUIC，在校园网、公司网和
  # 部分家庭路由器上更容易连接成功。
  nohup cloudflared tunnel --no-autoupdate --protocol http2 --url "$BACKEND_ORIGIN" \
    >"$TUNNEL_LOG" 2>&1 &
  print $! > "$PID_FILE"
  print "正在建立临时公网隧道…"
  tunnel_registered=false
  for attempt in {1..40}; do
    PUBLIC_URL="$(extract_url)"
    if [[ -n "$PUBLIC_URL" ]] && grep -q 'Registered tunnel connection' "$TUNNEL_LOG" 2>/dev/null; then
      tunnel_registered=true
      break
    fi
    if ! is_running "$PID_FILE"; then
      break
    fi
    sleep 1
  done
  [[ "$tunnel_registered" == true ]] || pause_and_exit "Cloudflare 连接器未成功注册，请查看 logs/cloudflared.log。"
fi

[[ -n "$PUBLIC_URL" ]] || pause_and_exit "未获取到 Cloudflare 公网地址，请查看 logs/cloudflared.log。"
print "$PUBLIC_URL" > "$URL_FILE"

PUBLIC_READY=false
print "正在等待公网地址生效…"
for attempt in {1..30}; do
  if curl -fsS --max-time 8 "$PUBLIC_URL/health" >/dev/null 2>&1; then
    PUBLIC_READY=true
    break
  fi
  if ! is_running "$PID_FILE"; then
    break
  fi
  sleep 1
done

if [[ "$PUBLIC_READY" != true ]]; then
  print "提示：本机暂时无法验证公网健康地址（可能是 DNS 传播或当前网络限制）。"
  print "隧道连接器已注册，手机端可直接测试：${PUBLIC_URL}/health"
fi

print "正在使用公网地址构建微信小程序…"
VITE_API_BASE_URL="$PUBLIC_URL" "$PROJECT_DIR/构建微信小程序.command" --api-url "$PUBLIC_URL" --no-pause \
  || pause_and_exit "小程序构建失败，请查看终端输出。"

print ""
print "临时真机调试已就绪："
print "  公网后端：${PUBLIC_URL}"
print "  健康检查：${PUBLIC_URL}/health"
print "  小程序目录：miniapp/dist/build/mp-weixin"
print ""
print "请在微信开发者工具导入上述目录，打开“真机调试”扫码。体验者无需与本机连接同一网络。"
print "开发者工具请勾选“不校验合法域名、TLS 版本及 HTTPS 证书”（临时 trycloudflare.com 地址无法加入固定合法域名）。"
print "本机后端、Ollama、Search MCP 和此隧道进程必须保持运行；关闭电脑或停止脚本后，扫码将无法访问。"
print "随机公网地址变化后，请重新运行本脚本并重新导入/编译小程序。"

if [[ "$PAUSE_ON_FINISH" == true ]]; then
  print ""
  print "请按回车键关闭窗口（服务仍在后台运行）。"
  read -r
fi
