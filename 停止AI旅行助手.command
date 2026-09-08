#!/bin/zsh

set -eu

PROJECT_DIR="${0:A:h}"
RUN_DIR="$PROJECT_DIR/.run"

print "== 停止 AI 旅行助手 =="

for service_name in frontend backend railway search cloudflared; do
  pid_file="$RUN_DIR/${service_name}.pid"
  if [[ ! -f "$pid_file" ]]; then
    continue
  fi
  pid_value="$(tr -dc '0-9' < "$pid_file")"
  if [[ -n "$pid_value" ]] && kill -0 "$pid_value" 2>/dev/null; then
    kill "$pid_value" 2>/dev/null || true
    print "已停止：${service_name}"
  fi
  rm -f "$pid_file"
done

rm -f "$RUN_DIR/cloudflared.url"

print "所有由启动脚本创建的服务已停止。"
print "请按回车键关闭窗口。"
read -r
