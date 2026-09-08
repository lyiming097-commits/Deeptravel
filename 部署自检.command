#!/bin/zsh

set -eu

PROJECT_DIR="${0:A:h}"
cd "$PROJECT_DIR"

PAUSE_ON_FINISH=true
if [[ "${1:-}" == "--no-pause" ]]; then
  PAUSE_ON_FINISH=false
fi

failed=false

check_url() {
  local service_name="$1"
  local service_url="$2"
  if curl -fsS --max-time 8 "$service_url" >/dev/null 2>&1; then
    print "✓ ${service_name}"
  else
    print "✗ ${service_name}（${service_url}）"
    failed=true
  fi
}

CONFIGURED_HOST="$(sed -n 's/^APP_HOST=//p' .env 2>/dev/null | head -n 1)"
if [[ -z "$CONFIGURED_HOST" || "$CONFIGURED_HOST" == "0.0.0.0" ]]; then
  CONFIGURED_HOST="127.0.0.1"
fi

extract_tunnel_url() {
  local tunnel_log="${PROJECT_DIR}/logs/cloudflared.log"
  [[ -f "$tunnel_log" ]] || return 0
  grep -Eo 'https://[[:alnum:]-]+\.trycloudflare\.com' "$tunnel_log" 2>/dev/null | tail -n 1 || true
}

check_backend() {
  if curl -fsS --max-time 8 http://127.0.0.1:8000/health >/dev/null 2>&1 \
    || curl -fsS --max-time 8 "http://${CONFIGURED_HOST}:8000/health" >/dev/null 2>&1; then
    print "✓ FastAPI 后端"
  else
    print "✗ FastAPI 后端（端口 8000）"
    failed=true
  fi
}

print "== AI 旅行助手·部署自检 =="

[[ -f .env ]] && print "✓ 后端配置 .env" || { print "✗ 缺少 .env"; failed=true; }
[[ -x .venv/bin/python ]] && print "✓ Python 虚拟环境" || { print "✗ Python 虚拟环境"; failed=true; }
[[ -d frontend/node_modules ]] && print "✓ 管理端依赖" || { print "✗ 管理端依赖"; failed=true; }
[[ -f miniapp/dist/build/mp-weixin/app.js ]] && print "✓ 微信小程序构建产物" || { print "✗ 微信小程序构建产物"; failed=true; }

check_backend
check_url "Search MCP" "http://127.0.0.1:8100/health"
check_url "管理端" "http://127.0.0.1:5173/"

# Cloudflare 隧道是可选的；如果启动过，则顺便验证公网入口，便于定位真机调试问题。
if [[ -f "$PROJECT_DIR/.run/cloudflared.pid" ]]; then
  tunnel_pid="$(tr -dc '0-9' < "$PROJECT_DIR/.run/cloudflared.pid")"
  tunnel_url="$(extract_tunnel_url)"
  if [[ -n "$tunnel_pid" ]] && kill -0 "$tunnel_pid" 2>/dev/null && [[ -n "$tunnel_url" ]]; then
    check_url "Cloudflare Tunnel" "${tunnel_url}/health"
  else
    print "✗ Cloudflare Tunnel（进程或公网地址不可用）"
    failed=true
  fi
fi

if [[ "$failed" == true ]]; then
  print ""
  print "自检未通过，请查看 logs/ 目录或重新运行“一键快速部署.command”。"
  if [[ "$PAUSE_ON_FINISH" == true ]]; then
    print "请按回车键关闭窗口。"
    read -r
  fi
  exit 1
fi

print ""
print "自检通过，主要服务均可访问。"
if [[ "$PAUSE_ON_FINISH" == true ]]; then
  print "请按回车键关闭窗口。"
  read -r
fi
