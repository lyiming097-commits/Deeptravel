#!/bin/zsh

set -eu

PROJECT_DIR="${0:A:h}"
cd "$PROJECT_DIR"

PAUSE_ON_FINISH=true
if [[ "${1:-}" == "--no-pause" ]]; then
  PAUSE_ON_FINISH=false
fi

# Homebrew 的 PostgreSQL 经常是 keg-only，Finder 双击脚本时 PATH 里
# 不一定有 psql/createdb。只添加已存在的标准目录。
for postgres_bin in \
  /opt/homebrew/opt/postgresql@17/bin \
  /opt/homebrew/opt/postgresql@16/bin \
  /usr/local/opt/postgresql@17/bin \
  /usr/local/opt/postgresql@16/bin; do
  if [[ -d "$postgres_bin" ]]; then
    export PATH="$postgres_bin:$PATH"
    break
  fi
done

print_title() {
  print ""
  print "== $1 =="
}

fail() {
  print ""
  print "安装未完成：$1"
  if [[ "$PAUSE_ON_FINISH" == true ]]; then
    print "请按回车键关闭窗口。"
    read -r
  fi
  exit 1
}

print_title "AI 旅行助手·环境检查"

PYTHON_EXECUTABLE=""
for candidate in python3.12 python3; do
  if command -v "$candidate" >/dev/null 2>&1; then
    if "$candidate" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 12) else 1)' 2>/dev/null; then
      PYTHON_EXECUTABLE="$candidate"
      break
    fi
  fi
done

[[ -n "$PYTHON_EXECUTABLE" ]] || fail "未找到 Python 3.12 或更高版本。"
command -v npm >/dev/null 2>&1 || fail "未找到 Node.js/npm，请先安装 Node.js 18+。"
command -v psql >/dev/null 2>&1 || fail "未找到 PostgreSQL，请先安装 PostgreSQL 15+ 和 pgvector。"
command -v createdb >/dev/null 2>&1 || fail "未找到 createdb 命令，请确认 PostgreSQL bin 目录已加入 PATH。"

if [[ ! -f .env ]]; then
  cp .env.example .env
  print "已由 .env.example 生成 .env，请在安装后填写真实服务密钥。"
fi

# 发布包保留原机密钥，但 PostgreSQL 的本地用户名需要适配新电脑。
LOCAL_ACCOUNT="$(id -un)"
if grep -q 'postgresql+asyncpg://liu123@127.0.0.1:5432/deeptravel' .env; then
  sed -i.bak "s#postgresql+asyncpg://liu123@127.0.0.1:5432/deeptravel#postgresql+asyncpg://${LOCAL_ACCOUNT}@127.0.0.1:5432/deeptravel#" .env
  rm -f .env.bak
  print "已将 DATABASE_URL 的本地用户名调整为 ${LOCAL_ACCOUNT}。"
fi

print_title "安装 Python 依赖"
"$PYTHON_EXECUTABLE" -m venv .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -e './backend[dev]'
.venv/bin/python -m playwright install chromium

if grep -Eq '^EMBEDDING_PROVIDER=ollama[[:space:]]*$' .env; then
  print_title "准备 Ollama Embedding"
  command -v ollama >/dev/null 2>&1 || fail ".env 启用了 Ollama，但本机未安装 Ollama。"
  if ! curl -fsS http://127.0.0.1:11434/api/tags >/dev/null 2>&1; then
    if command -v brew >/dev/null 2>&1; then
      brew services start ollama >/dev/null 2>&1 || true
    else
      nohup ollama serve > /tmp/ai-travel-ollama.log 2>&1 &
    fi
    for attempt in {1..20}; do
      curl -fsS http://127.0.0.1:11434/api/tags >/dev/null 2>&1 && break
      sleep 1
    done
  fi
  curl -fsS http://127.0.0.1:11434/api/tags >/dev/null 2>&1 || fail "Ollama 服务未启动。"
  EMBEDDING_MODEL_NAME="$(sed -n 's/^EMBEDDING_MODEL=//p' .env | head -n 1)"
  [[ -n "$EMBEDDING_MODEL_NAME" ]] || EMBEDDING_MODEL_NAME="qwen3-embedding:0.6b"
  ollama pull "$EMBEDDING_MODEL_NAME"
fi

print_title "安装 12306 MCP"
"$PYTHON_EXECUTABLE" -m venv .venv-12306
.venv-12306/bin/python -m pip install --upgrade pip
.venv-12306/bin/python -m pip install mcp-server-12306

print_title "安装并构建管理端"
(cd frontend && npm ci && npm run build)

print_title "安装并构建微信小程序"
(cd miniapp && npm ci)
"$PROJECT_DIR/构建微信小程序.command" --no-pause

print_title "初始化数据库"
createdb deeptravel 2>/dev/null || true
PYTHONPATH="$PROJECT_DIR" .venv/bin/python -m alembic upgrade head || fail "数据库迁移失败，请根据部署说明检查 .env 中的 DATABASE_URL 与 pgvector。"

print_title "安装完成"
print "可以双击“启动AI旅行助手.command”启动后端、搜索服务和管理端。"
print "微信小程序项目：miniapp/dist/build/mp-weixin"
if [[ "$PAUSE_ON_FINISH" == true ]]; then
  print ""
  print "请按回车键关闭窗口。"
  read -r
fi
