#!/bin/zsh

set -eu

PROJECT_DIR="${0:A:h}"
cd "$PROJECT_DIR"

pause_on_finish=true
api_url_override="${VITE_API_BASE_URL:-}"

# 支持临时公网隧道或固定域名构建：
#   zsh ./构建微信小程序.command --api-url https://example.trycloudflare.com --no-pause
# 仍保留无参数时自动使用当前局域网 IP 的行为，方便开发者工具本机/同网调试。
while [[ $# -gt 0 ]]; do
  case "$1" in
    --no-pause)
      pause_on_finish=false
      shift
      ;;
    --api-url)
      [[ $# -ge 2 ]] || { print "--api-url 需要提供一个 http(s) 地址。"; exit 2; }
      api_url_override="$2"
      shift 2
      ;;
    --api-url=*)
      api_url_override="${1#*=}"
      shift
      ;;
    *)
      print "未知参数：$1"
      print "用法：$0 [--api-url http(s)://...] [--no-pause]"
      exit 2
      ;;
  esac
done

pause_and_exit() {
  print ""
  print "$1"
  if [[ "$pause_on_finish" == true ]]; then
    print "请按回车键关闭窗口。"
    read -r
  fi
  exit 1
}

if [[ ! -d miniapp/node_modules ]]; then
  print "正在安装小程序依赖…"
  (cd miniapp && npm ci)
fi

if [[ -n "$api_url_override" ]]; then
  API_URL="${api_url_override%/}"
  if [[ ! "$API_URL" == http://* && ! "$API_URL" == https://* ]]; then
    pause_and_exit "后端地址必须以 http:// 或 https:// 开头：${API_URL}"
  fi
  print "使用指定的小程序后端地址：${API_URL}"
else
  LAN_IP="$(ipconfig getifaddr en0 2>/dev/null || true)"
  if [[ -z "$LAN_IP" ]]; then
    LAN_IP="$(ipconfig getifaddr en1 2>/dev/null || true)"
  fi

  if [[ -n "$LAN_IP" ]]; then
    API_URL="http://${LAN_IP}:8000"
  else
    CONFIGURED_HOST="$(sed -n 's/^APP_HOST=//p' .env 2>/dev/null | head -n 1)"
    if [[ -n "$CONFIGURED_HOST" && "$CONFIGURED_HOST" != "0.0.0.0" ]]; then
      API_URL="http://${CONFIGURED_HOST}:8000"
      print "未检测到网卡地址，使用 .env 中的 APP_HOST：${CONFIGURED_HOST}"
    else
      API_URL="http://127.0.0.1:8000"
      print "未检测到局域网 IP，当前构建仅适用于开发者工具本机调试。"
    fi
  fi
fi

print "小程序后端地址：${API_URL}"
(cd miniapp && VITE_API_BASE_URL="$API_URL" npm run build:mp-weixin)

print ""
print "构建完成：miniapp/dist/build/mp-weixin"
print "请在微信开发者工具中导入该目录。"

if [[ "$pause_on_finish" == true ]]; then
  print "请按回车键关闭窗口。"
  read -r
fi
