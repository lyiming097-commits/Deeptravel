# 发给 AI 代理的部署提示词

请在当前目录部署「AI 旅行助手」项目。这是 macOS 项目，请使用 zsh 终端执行，不要只读取代码后停止。

## 执行要求

1. 先检查 Python 3.12+、Node.js 18+、PostgreSQL/pgvector、Ollama 和 npm 是否已安装。缺少时不要只给出说明就停止；请向用户申请必要的联网/安装权限，然后在 macOS 上优先使用 `brew install python@3.12 node postgresql@17 pgvector ollama`、`brew services start postgresql@17`、`brew services start ollama` 和 `ollama pull qwen3-embedding:0.6b` 完成安装。不要删除或覆盖已有数据库。
2. 先阅读 `部署运行说明.md`、`.env` 和 `README.md`。`.env` 包含敏感配置，请不要在输出、日志或回复中显示密钥原文。
3. 执行：

   ```bash
   zsh ./一键快速部署.command --no-pause
   ```

   该脚本会创建 Python 虚拟环境、安装后端和小程序依赖、安装 12306 MCP、执行 Alembic 迁移、构建前端和微信小程序，并启动后端、Search MCP 和管理端。
4. 如果命令失败，先查看 `logs/backend.log`、`logs/search.log`、`logs/frontend.log`，根据实际错误修改 `.env` 或补充系统依赖，然后重试；禁止编造“已成功”。
5. 部署后执行：

   ```bash
   zsh ./部署自检.command --no-pause
   ```

   依次验证 `http://127.0.0.1:8000/health`、`http://127.0.0.1:8100/health`、`http://127.0.0.1:5173/`。请返回每个地址的状态，不要返回敏感配置值。
6. 如果用户要进行微信真机调试，执行：

   ```bash
   zsh ./构建微信小程序.command --no-pause
   ```

   然后告知用户在微信开发者工具导入 `miniapp/dist/build/mp-weixin`。

7. 如果用户明确要求手机与后端电脑不在同一网络，使用临时 Cloudflare Tunnel：

   ```bash
   zsh ./启动Cloudflare体验.command --no-pause
   ```

   该脚本会检查/安装 `cloudflared`、启动本地服务（如尚未启动）、创建临时 HTTPS 地址，并用公网地址重新构建小程序。将 `miniapp/dist/build/mp-weixin` 导入微信开发者工具后，使用“真机调试”扫码；调试设置中勾选“不校验合法域名、TLS 版本及 HTTPS 证书”。隧道地址随机且只在本机进程运行期间有效，不要把它当作长期体验版公网域名。

## 完成条件

- `部署自检.command --no-pause` 全部通过。
- 管理端可以在 `http://127.0.0.1:5173/` 打开。
- 后端 `/health` 返回 `status=ok` 或者对缺失的外部服务给出具体配置提示。
- 不返回、不记录 `.env` 中的密钥。
