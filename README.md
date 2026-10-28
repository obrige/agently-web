# agently-web

**Gmail 风格的 Agently（QQ 邮箱 Agent）网页客户端** —— 基于对 `@tencent-qqmail/agently-cli` v1.0.18 的完整协议实现。

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue.svg)](pyproject.toml)
[![Docker](https://img.shields.io/badge/docker-GHCR-2496ED.svg)](docker-compose.yml)

## 这是什么

Agently 是腾讯 QQ 邮箱推出的「Agent 原生邮箱」：邮箱本身带 API 与授权能力，可以被 AI Agent 收发和管理邮件。官方只提供了 CLI（Go 二进制），没有 Web 界面。

`agently-web` 把这套协议用 **Python 标准库** 重新实现了一遍，并配上一套 **零构建、零框架** 的 Gmail 风格前端：

- **后端**：`http.server` + `ThreadingHTTPServer`，只依赖标准库，clone 完直接 `python server.py` 就能跑；
- **前端**：原生 HTML / CSS / JS，无打包、无 npm、无 CDN，`static/` 目录直接由后端托管；
- **部署**：多阶段 Dockerfile（构建阶段先跑测试）、docker-compose、以及 Caddy 自动签发 Let's Encrypt 证书的 HTTPS 叠加层。

## 特性

- **OAuth 2.0 Device Flow 登录** —— 与官方 CLI 完全一致的授权流程，授权码只需在浏览器里点一次。
- **多账号 / 多别名** —— 可同时登录多个 QQ 邮箱账号，并在同一账号的不同邮箱别名之间切换。
- **完整收发** —— 收件箱 / 未读 / 已发送 / 回收站 / 星标，支持搜索（全文 / 仅主题 / 仅正文）。
- **写邮件** —— 纯文本 / Markdown / HTML 三种正文格式，附件上传，签名自动附加，**草稿自动保存**。
- **两步确认发送** —— 服务端要求二次确认时，前端弹出确认框并回传 `confirmation_token`。
- **地址簿** —— 收件人失焦时自动记为联系人，写作时自动补全。
- **本地状态持久化** —— OAuth 凭证、草稿、签名、星标、联系人全部落在本地 JSON 文件里。
- **演示模式** —— `AGENTLY_WEB_DEMO=1` 用内置种子邮箱跑起来，不需要任何 QQ 账号，也不联网。
- **自动刷新** —— 通过 `/events/wait` 长轮询感知新邮件。
- **移动端适配** —— 窄屏自动切换为抽屉式侧边栏 + 全屏阅读视图。
## 快速开始

### 1. 本地运行

只需要 Python 3.10+，**不需要 pip install 任何东西**：

```bash
git clone https://github.com/obrige/agently-web.git
cd agently-web

# 演示模式：不需要 QQ 账号，内置 9 封种子邮件
AGENTLY_WEB_DEMO=1 python server.py

# 正式模式：启动后打开 http://127.0.0.1:8787 走 OAuth 授权
python server.py
```

启动后终端会打印本机与局域网地址：

```
   Local : http://127.0.0.1:8787
   LAN   : http://192.168.x.x:8787
   Auth  : https://agent.qq.com/page/oauth
   API   : https://api.agent.qq.com/v1
```

### 2. Docker Compose

```bash
# 正式模式（本地构建镜像）
docker compose up -d

# 演示模式（映射到 8788 端口）
docker compose --profile demo up -d
```

数据默认保存在名为 `agently-data` 的 volume 中。想改挂到宿主机目录：

```bash
AGENTLY_DATA_VOLUME=/srv/agently/data docker compose up -d
```

想直接拉 CI 推送的镜像而不在本地构建：

```bash
AGENTLY_WEB_IMAGE=ghcr.io/<你的用户名>/agently-web:latest docker compose up -d
```

### 3. 生产环境 + HTTPS

先参照 `.env.example` 在 `.env` 里设置域名：

```dotenv
DOMAIN=mail.example.com
ADMIN_EMAIL=you@example.com
```

再叠加 TLS 层启动，Caddy 会自动申请并续期 Let's Encrypt 证书：

```bash
docker compose -f docker-compose.yml -f docker-compose.tls.yml up -d
```

Caddy 监听 80/443 并反代到容器内的 8787，同时加上 HSTS、nosniff、X-Frame-Options、Referrer-Policy 等安全响应头。

## 配置

所有环境变量都是可选的。

### 服务端（server.py）

| 变量 | 默认值 | 说明 |
| --- | --- | --- |
| `PORT` | `8787` | 监听端口 |
| `HOST` | `0.0.0.0` | 监听地址 |
| `AGENTLY_WEB_DEMO` | – | 设为 `1` 启用演示模式（不联网、不需要账号） |
| `AGENTLY_WEB_DATA_DIR` | `<repo>/.data` | 数据目录，存放 5 个 JSON 文件 |
| `AGENTLY_WEB_DEBUG` | – | 设为 `1` 时服务端打印完整 traceback |
| `AGENTLY_WEB_AGENT` | 空 | 上报给腾讯的 agent 标识（User-Agent 里的 `; agent/<slug>`） |
| `AGENTLY_WEB_FAKE_UA` | 空 | 设为 `1` 时 User-Agent 追加 `; client/agently-web` 标记，便于服务端识别 |
| `AGENTLY_WEB_CLIENT_ID` | 空 | `/oauth/token` 需要的 client id（授权响应通常会直接下发，见「协议实现说明」） |
| `AGENTLY_WEB_CLIENT_SECRET` | 空 | `/oauth/token` 可选的 client secret |

### docker compose

| 变量 | 默认值 | 说明 |
| --- | --- | --- |
| `AGENTLY_WEB_IMAGE` | 空（本地构建） | 使用的镜像地址 |
| `AGENTLY_DATA_VOLUME` | `agently-data` | 挂载到 `/data` 的 volume 名或宿主机路径 |
| `DOMAIN` | – | **TLS 必填**，证书对应的域名 |
| `ADMIN_EMAIL` | – | Let's Encrypt 到期提醒邮箱 |
| `CADDY_CERTS_VOLUME` | `caddy-data` | Caddy 证书目录（volume 名或宿主机路径） |
| `CADDY_LOGS_DIR` | `./caddy-logs` | Caddy 访问 / 错误日志目录 |

## 使用

### 登录

点击「使用 OAuth 授权登录」，页面会显示一个授权码和腾讯授权链接：

1. 在同一台机器（或任何设备）打开授权链接；
2. 用要绑定的 QQ 邮箱扫码 / 确认授权；
3. 回到网页端，后台每 2 秒轮询一次授权状态，成功后自动进入主界面。

整个流程是 OAuth 2.0 Device Flow：服务端调用 `POST https://auth.agent.qq.com/oauth/device?func=1` 拿到 `poll_url` 与 `input_code`，用 `GET <poll_url>` 长轮询授权状态，用户确认后即可拿到 access / refresh token。**凭证只保存在你自己的机器上。**

### 界面

- **顶栏** —— 搜索框（可限定「主题」或「正文」）、刷新、账号菜单。
- **侧边栏** —— 写邮件、收件箱 / 未读 / 已发送 / 回收站 / 星标邮件、邮箱别名列表、连接状态指示。
- **邮件列表** —— 发件人 / 主题 / 摘要 / 附件与目录标签，未读加粗，行内可直接加星标。
- **阅读窗格** —— 完整正文（HTML / Markdown / 纯文本自适应渲染）、附件列表、可展开的「查看原始数据」JSON 视图。
- **写邮件** —— 收件人 / 抄送 / 密送 / 主题 / 正文格式 / 附件 / 签名；停止输入 1.2 秒后自动保存草稿。
- **快捷键** —— `C` 写邮件，`R` 刷新，`Esc` 关闭弹窗。

### 已知限制

- 上游 API **没有提供「移出回收站」** 接口，回收站中的邮件无法还原（前端会给出提示）。
- 星标、签名、地址簿、草稿属于 **本地状态**，只存在这台机器上，不会上传回服务端。
- 演示模式下附件下载返回的是一段占位文本，用于跑通链路，不是真实文件。

## 项目结构

```
agently-web/
├── server.py              # HTTP 服务、路由、会话、OAuth 编排（纯标准库）
├── agently/
│   ├── client.py          # 协议客户端：OAuth Device Flow + REST API 封装
│   ├── store.py           # 本地账号 / 草稿 / 签名 / 星标 / 联系人存储
│   ├── normalize.py       # 响应归一化（抹平不同接口返回结构的差异）
│   └── demo.py            # 演示模式：种子邮箱 + 内存 store
├── static/
│   ├── index.html         # 单页结构（登录页 + 主界面 + 各类弹窗）
│   ├── app.js             # 全部前端逻辑（原生 JS，无框架）
│   └── style.css          # Gmail 风格主题 + 响应式布局
├── tests/                 # pytest 测试（client / store / demo / normalize）
├── Dockerfile             # 多阶段构建：builder 跑测试，runtime 只留运行产物
├── docker-compose.yml     # 默认编排（live + demo profile）
├── docker-compose.tls.yml # HTTPS 叠加层（Caddy）
├── Caddyfile              # 反向代理 + 自动 HTTPS + 安全响应头
├── pyproject.toml         # pytest / ruff / black / mypy 配置
└── .github/workflows/     # CI：lint → test → 镜像构建 → compose 冒烟测试
```

## HTTP API

前端只跟本服务的 `/api/*` 通信，所有响应统一为 `{"ok": true, "data": ...}` 或 `{"ok": false, "error": {"code", "message"}}`。

除登录相关的几个接口外，其余接口都要求携带会话 Cookie（`agently_web_sid`，HttpOnly + SameSite=Lax，有效期 30 天）。

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/healthz` | 健康检查（容器 HEALTHCHECK 使用） |
| GET | `/api/auth/session` | 当前会话与账号列表 |
| POST | `/api/auth/login/start` | 发起 Device Flow，返回授权链接与授权码 |
| GET | `/api/auth/login/{loginId}` | 轮询授权状态 |
| POST | `/api/auth/login/{loginId}/cancel` | 取消授权 |
| POST | `/api/auth/switch` | 切换账号 |
| POST | `/api/auth/logout` | 撤销 refresh token 并清除本地凭证 |
| GET | `/api/me` | 当前账号资料与别名列表 |
| GET | `/api/aliases` | 邮箱别名 |
| GET | `/api/accounts` | 已登录账号列表 |
| GET / POST | `/api/drafts` | 草稿列表 / 保存草稿 |
| GET / DELETE | `/api/drafts/{draftId}` | 单个草稿 |
| GET / POST | `/api/signature` | 邮件签名 |
| GET | `/api/stars` | 星标列表 |
| POST / DELETE | `/api/stars/{messageId}` | 加星标 / 取消星标 |
| GET / POST | `/api/contacts` | 地址簿 |
| DELETE | `/api/contacts/{email}` | 删除联系人 |
| GET | `/api/aliases/{alias}/messages` | 邮件列表（`limit` / `before` / `is-read` / `folder`） |
| GET | `/api/aliases/{alias}/messages/search` | 搜索（`q` / `search-in`） |
| GET | `/api/aliases/{alias}/messages/{id}` | 邮件详情 |
| GET | `/api/aliases/{alias}/messages/{id}/attachments/{aid}` | 下载附件 |
| GET | `/api/aliases/{alias}/events/wait` | 长轮询等待新事件 |
| POST | `/api/aliases/{alias}/messages/send` | 发信（无 `confirmation_token` 时返回待确认） |
| POST | `/api/aliases/{alias}/messages/{id}/reply` | 回复 |
| POST | `/api/aliases/{alias}/messages/{id}/forward` | 转发 |
| DELETE | `/api/aliases/{alias}/messages/{id}` | 移入回收站 |
| POST | `/api/aliases/{alias}/messages/{id}/permanent` | 彻底删除 |
| POST | `/api/aliases/{alias}/trash/empty` | 清空回收站 |
| POST | `/api/aliases/{alias}/files/upload` | 上传附件（multipart） |

## 数据存储

所有状态都写在 `AGENTLY_WEB_DATA_DIR`（容器内为 `/data`）下的 5 个 JSON 文件里，写入采用「临时文件 + `os.replace`」的原子替换：

| 文件 | 内容 |
| --- | --- |
| `accounts.json` | 每个账号一条记录：access / refresh token、过期时间、资料 |
| `drafts.json` | `{账号: {草稿ID: 草稿}}` |
| `signatures.json` | `{账号: {plain, html}}` |
| `stars.json` | `{账号: [message_id, ...]}` |
| `contacts.json` | `{账号: {邮箱: {name, email, addedAt}}}` |

> ⚠️ `accounts.json` 里是明文 OAuth 凭证。请确保数据目录权限可控，并且 **不要提交到版本库**（`.gitignore` 已忽略 `.data/`）。

## 协议实现说明

以下报文格式全部来自**对官方 CLI（`@tencent-qqmail/agently-cli` v1.0.18）的实地抓包**，并逐条与真实服务端核对过。

- 端点：`https://api.agent.qq.com/v1`（业务）、`https://auth.agent.qq.com`（授权）、`https://agent.qq.com`（网页）。
- **User-Agent 必须以 `agently-cli/<version>` 开头**，否则授权接口会返回 `{"errmsg":"unsupported client"}`。本项目默认发送的字符串与官方 CLI 完全一致：`agently-cli/1.0.18 (windows/amd64)`；只有在检测到 agent 外壳时才追加 `; agent/<slug>`，设置 `AGENTLY_WEB_FAKE_UA=1` 才会追加 `; client/agently-web`。
- **第 1 步 — 申请设备码**：`POST /oauth/device?func=1`，`Content-Type: application/json`，请求体是描述调用方的三个字段：
  ```json
  {"cli_hostname": "<uuid>", "cli_ua": "agently-cli/1.0.18 (windows/amd64)", "cli_version": "1.0.18"}
  ```
  响应：`{"scan_url": "", "poll_url": "…/oauth/device?func=2&device_code=dc_…", "browser_url": "…/oauth?user_code=uc_…", "input_code": "ic_…", "expires_in": 600}`。
- **第 2 步 — 长轮询授权状态**：`GET <poll_url>`（**GET**，无请求体）。服务端会挂起连接约 20 秒后返回 `{"status": "pending"}`；用户确认后返回带凭证的报文。
- **第 3 步 — 换取 token**：`POST /oauth/token`，`Content-Type: application/x-www-form-urlencoded`，且**只接受** `grant_type` +（`code` | `refresh_token`）+ `client_id`（+ `client_secret`）这几个键。多一个键、或把 body 换成 JSON，服务端一律回：
  ```json
  {"err_code": -20011, "error": "invalid_request", "error_description": "missing or malformed request parameters"}
  ```
  参数形状正确但 client id 不对时，回的是 `{"err_code": -21651, "error": "invalid_client"}`——两者可以用来自检请求形状。
- 客户端 id 不在官方 CLI 的二进制常量里，因此只能由服务端在下发：授权响应里带 `app_id` / `app_secret`，对应 token 接口的 `client_id` / `client_secret`。登录成功后本项目会把它们随 token 一起存进 `accounts.json`，续期时复用；也可以用 `AGENTLY_WEB_CLIENT_ID` / `AGENTLY_WEB_CLIENT_SECRET` 直接指定。
- 业务接口统一返回 `{"ok": true, "data": ...}`，非 `ok` 一律抛 `ApiError`，并保留 `code` / `request_id` / `_hints`。
- 客户端显式绕开系统 HTTP 代理（`urllib.request.ProxyHandler({})`），并手动处理 gzip 响应。
- access token 剩余寿命不足 60 秒时，会自动用 refresh token 续期并落盘。

## 开发

```bash
# 安装开发工具
pip install pytest==9.1.1 ruff==0.7.4 black==24.10.0 mypy==1.13.0

# 跑测试
python -m pytest tests -v

# 代码检查（与 CI 完全一致）
ruff check agently server.py tests
ruff format --check agently server.py tests
black --check --diff agently server.py tests
mypy --strict --ignore-missing-imports agently
```

测试覆盖了协议编码与错误封装（`tests/test_client.py`）、本地存储的增删改查与重启持久化（`tests/test_store.py`）、演示邮箱行为（`tests/test_demo.py`）以及响应归一化（`tests/test_normalize.py`）。

### CI/CD

`.github/workflows/ci.yml` 在 push / PR 上依次执行：

1. **lint** —— ruff + black + mypy strict；
2. **test** —— Python 3.10 / 3.11 / 3.12 / 3.13 四版本矩阵跑 pytest；
3. **docker** —— Buildx 构建 `linux/amd64` 与 `linux/arm64`，推送到 `ghcr.io/<owner>/agently-web`，同时生成 SBOM 与 provenance；
4. **compose-smoke** —— 真正用 `docker compose` 起一个 demo 容器，curl 校验 `/healthz`、首页、静态资源，以及未登录接口返回 401；
5. **docker-pr** —— PR 上额外做一次不推送的镜像构建。

推送 `v*` tag 会触发 `release.yml` 自动创建 GitHub Release。

## 安全须知

- 本项目面向 **个人 / 家庭服务器** 的自建场景，没有做多用户隔离、审计日志与 CSRF token，请不要直接暴露到公网。
- 公网部署请务必使用 `docker-compose.tls.yml`（HTTPS），并在反向代理层再加一层访问控制。
- OAuth 凭证以明文形式保存在本地磁盘，请像对待密码文件一样对待 `accounts.json`。
- 退出登录会调用 `POST /oauth/logout_session` 撤销 refresh token，并删除本地记录。

## License

[MIT](LICENSE) © 2026 agently-web contributors

## 致谢

- `@tencent-qqmail/agently-cli` —— 协议参考来源，本项目的协议实现即逆向自该 CLI v1.0.18。
