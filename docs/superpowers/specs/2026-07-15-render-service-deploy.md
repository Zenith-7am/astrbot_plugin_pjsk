> **Status: Approved** (core layer — still valid under Phase 5 standalone direction).
> The domain, application, ports, and adapter designs in this document remain authoritative for `pjsk_core` and `adapters/`.
> Current governance: `CLAUDE.md`. Phase-5 gateway design: `docs/superpowers/specs/2026-07-16-phase-5-standalone-onebot-gateway-design.md`.

# Render Service 部署文档

> 状态：Phase 4b 渲染服务已可部署。本文件只写事实，不假设 AstrBot WebUI 配置字段。

## 1. 前置依赖

### 1.1 Python 包

在插件运行环境中（香港 VPS 的 AstrBot venv）：

```bash
# 方式一：从插件源码目录安装 render 可选依赖
pip install ".[render]"

# 方式二：直接安装 requirements 文件
pip install -r render_service/requirements.txt
```

`requirements.txt` 内容（随插件源码发布）：

```
fastapi>=0.115
uvicorn>=0.30
playwright>=1.45
```

### 1.2 Chromium 浏览器

```bash
playwright install chromium
```

Chromium 安装到 Playwright 的缓存目录（`~/.cache/ms-playwright/`），**非全局系统包**。

## 2. 渲染服务启动

### 2.1 从命令行启动（调测用）

```bash
cd /opt/pjsk-astrbot/current
RENDER_HOST=127.0.0.1 RENDER_PORT=3000 RENDER_MAX_CONCURRENT=4 \
  python -m uvicorn render_service.main:app --host 127.0.0.1 --port 3000
```

或直接运行：

```bash
cd /opt/pjsk-astrbot/current
python render_service/main.py
```

### 2.2 健康检查

```bash
curl http://127.0.0.1:3000/health
```

正常响应：

```json
{"status":"ok","uptime":123,"functions":["b20","difficulty"],"browser":"connected"}
```

`browser` 为 `"disconnected"` 且重启失败时返回 503。

## 3. systemd 服务

文件：`/etc/systemd/system/pjsk-renderer.service`

```ini
[Unit]
Description=PJSK Render Service (FastAPI + Playwright)
After=network.target

[Service]
Type=simple
User=www-data
WorkingDirectory=/opt/pjsk-astrbot/current
Environment=RENDER_HOST=127.0.0.1
Environment=RENDER_PORT=3000
Environment=RENDER_MAX_CONCURRENT=4
ExecStart=/opt/pjsk-astrbot/current/.venv/bin/python render_service/main.py
Restart=on-failure
RestartSec=5

# Security
PrivateTmp=yes
NoNewPrivileges=yes

[Install]
WantedBy=multi-user.target
```

操作：

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now pjsk-renderer
sudo systemctl status pjsk-renderer    # 确认 running
curl http://127.0.0.1:3000/health       # 确认 browser: connected
```

## 4. 插件侧配置

插件读取其自身配置来源（AstrBot 的 `config` dict，即 `data/plugin_data/astrbot_plugin_pjsk/config.yml` 或等效路径）。以下配置键供参考：

| 键 | 类型 | 默认 | 说明 |
|----|------|------|------|
| `render_service_url` | `str` | `""` (空) | 渲染服务地址，如 `http://127.0.0.1:3000` |
| `jacket_cache_dir` | `str` | `""` (空) | 曲封本地缓存目录，如 `/var/cache/pjsk/jackets` |
| `render_timeout_seconds` | `float` | `30` | 渲染超时秒数 |

- `render_service_url` 为空或未设置时，`/pjsk b20` 与难度排行**仅返回文本**，不影响 OCR 功能。
- `jacket_cache_dir` 为空时或目录不可写时，render payload 中封面字段为 `null`，JS 显示灰色占位图，不影响渲染。

## 5. 回滚

```bash
# 方式一：清空 render_service_url 并重启插件 → 回到纯文本模式
#   (编辑 config，将 render_service_url 改为 ""，重启 AstrBot)

# 方式二：停掉渲染服务
sudo systemctl stop pjsk-renderer
sudo systemctl disable pjsk-renderer
# 渲染调用超时后自动回退文本，不影响 OCR

# 回滚到不含渲染服务的插件版本：
#   旧版本未定义 render_service_url，等于文本模式
```

## 6. 目录结构（部署后）

```text
/opt/pjsk-astrbot/
  current/                          # 原子发布 symlink
    render_service/
      main.py                       # FastAPI 入口
      requirements.txt              # render 依赖
      functions/
        _loader.js                  # render 函数注册器
        b20.js                      # B20 Canvas 渲染（纯画图，无 calcKn）
        difficulty.js               # 难度排行 Canvas 渲染
  shared/
    data/pjsk.db
  releases/<id>/
    ...
```

## 7. 调试命令

```bash
# 渲染服务是否存活
curl -s http://127.0.0.1:3000/health | python -m json.tool

# 手动调用 B20 渲染（需有效 payload）
curl -s -X POST http://127.0.0.1:3000/render/b20 \
  -H 'Content-Type: application/json' \
  -d '{"b20":[],"sp":0,"playerClass":{"name":"Beginner","icon":"🌟","stars":0,"fallbackColor":"gray"},"b20Avg":0,"fcBonus":0,"masterBonus":0,"isAppendExcluded":true}' \
  -o /tmp/test_b20.png

# 查看最近日志
sudo journalctl -u pjsk-renderer --since "5 min ago"
```

## 8. 已知限制

- 渲染服务仅监听 `127.0.0.1`，不暴露外网。
- 每请求独立 Page/Context，最大 4 并发（`RENDER_MAX_CONCURRENT` 环境变量）。
- 浏览器 crash 自动重启一次；再次失败返回 503，调用方降级到文本。
- Chromium 内存占用约 200–400 MB，请确保 VPS 有足够空闲内存。
- JS 渲染布局不做修改——所有值由 Python 预计算。
