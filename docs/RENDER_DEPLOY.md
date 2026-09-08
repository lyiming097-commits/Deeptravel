# GitHub + Render 部署

本项目是 Python FastAPI 应用，不使用 Maven、Java 或 `target/*.jar`。

## 创建 Render 服务

1. 登录 Render，选择 **New + → Blueprint**。
2. 连接 GitHub 仓库 `lyiming097-commits/AI-`。
3. Render 会读取仓库根目录的 `render.yaml`，创建 Web Service 和 PostgreSQL。
4. 在首次创建页面填写标记为 `sync: false` 的环境变量：
   - `DEEPSEEK_API_KEY`
   - `AMAP_MCP_API_KEY`
   - `ADMIN_INITIAL_PASSWORD`
   - `WECHAT_APP_ID`
   - `WECHAT_APP_SECRET`
5. 点击 **Apply**，等待 `/health` 显示 `status: ok`。

密钥只填写在 Render Dashboard，禁止把本机 `.env` 上传 GitHub。

## 微信小程序

Render 部署完成后会获得类似下面的固定 HTTPS 地址：

```text
https://deeptravel-agent-api.onrender.com
```

使用实际地址重新构建：

```bash
zsh ./构建微信小程序.command \
  --api-url https://实际服务名.onrender.com \
  --no-pause
```

然后在微信开发者工具重新导入 `miniapp/dist/build/mp-weixin`、上传代码并生成体验版。

> 注意：微信公众平台可能拒绝未备案的 `onrender.com` 二级域名作为
> `request 合法域名`。Render 可以完成固定公网部署，但是否能直接用于中国大陆
> 微信体验版取决于微信后台校验。若无法添加，需绑定已备案自有域名，或迁移到微信云托管。

## 免费实例限制

- 免费 Web Service 空闲后可能休眠，首次请求会明显变慢。
- 免费数据库的可用周期、容量和套餐规则以 Render 当前页面为准。
- Render 免费实例不运行 Ollama，本配置使用 `local_hash` 完成向量流程，语义检索质量低于本机 Qwen Embedding。
- 上传文件位于临时文件系统；向量化后的内容保存在 PostgreSQL，但原始上传文件可能在实例重启后丢失。
