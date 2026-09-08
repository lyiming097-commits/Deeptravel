#!/bin/zsh

set -eu

PROJECT_DIR="${0:A:h}"
cd "$PROJECT_DIR"

PAUSE_ON_FINISH=true
if [[ "${1:-}" == "--no-pause" ]]; then
  PAUSE_ON_FINISH=false
fi

print "== AI 旅行助手·一键快速部署 =="
print "将自动安装项目依赖、执行数据库迁移并启动所有服务。"
print ""

if [[ ! -x .venv/bin/python || ! -d frontend/node_modules || ! -d miniapp/node_modules ]]; then
  "$PROJECT_DIR/首次安装.command" --no-pause
else
  print "已检测到现有依赖，跳过重复安装。"
  PYTHONPATH="$PROJECT_DIR" .venv/bin/python -m alembic upgrade head
  (cd frontend && npm run build)
  "$PROJECT_DIR/构建微信小程序.command" --no-pause
fi

"$PROJECT_DIR/启动AI旅行助手.command" --no-pause
"$PROJECT_DIR/部署自检.command" --no-pause

print ""
print "快速部署完成，管理端已在浏览器打开。"
if [[ "$PAUSE_ON_FINISH" == true ]]; then
  print "请按回车键关闭窗口。"
  read -r
fi
