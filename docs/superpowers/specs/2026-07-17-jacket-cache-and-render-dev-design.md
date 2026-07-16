# Jacket Cache + Local Render Dev — Design Spec

> **Scope:** 曲封磁盘缓存加固 + 本机可视化渲染开发环境。不改 B20 查询规则、评分、DB schema、OneBot 消息路由。

## 1. JacketCache 加固

### 1.1 环境变量 `PJSK_JACKET_CACHE_DIR`

- 统一使用一个显式环境变量。生产值：`/opt/pjsk-astrbot/shared/cache/jackets`
- Bootstrap (`pjsk_emubot/bootstrap.py`) 优先读取该环境变量；若为空则回退到 config dict 的 `jacket_cache_dir` key
- 若两者均为空 → `jacket_cache = None`，渲染时传 `jacket: null`
- 目录创建失败 (`OSError` / `PermissionError`) → 记录 warning，`jacket_cache = None`，不崩

### 1.2 内容校验：WebP 签名

在 `_fetch_from_cdn()` 写入缓存前，验证下载内容：
- 前 12 字节必须匹配 WebP RIFF 签名：`RIFF????WEBP`（4 bytes 'RIFF' + 4 bytes size LE + 4 bytes 'WEBP'）
- 最小长度 ≥ 100 bytes（已有，但加上签名校验后更加安全）
- 校验失败 → 不写入缓存，返回 None，记录 debug log "not a valid WebP"

### 1.3 目录可写性检查

`JacketCache.__init__()` 中 `os.makedirs()` 可能失败。改为在构造函数中不创建目录，延迟到第一次写入时尝试。增加 `_writable: bool | None` 状态：
- `None` = 未检查
- `True` = 已验证可写
- `False` = 不可写，跳过后续写入

首次 `_fetch_from_cdn()` 时尝试 `os.makedirs(cache_dir, exist_ok=True)` + 测试写入临时文件 → 设置 `_writable`

或者更简单：在 `__init__` 中 try/except 捕获 `OSError`，设置 `_cache_disabled = True`，后续所有写入跳过。

采用更简单方案：构造时尝试创建目录，失败则标记 `_cache_disabled`。

### 1.4 Bootstrap 变更

`pjsk_emubot/bootstrap.py`：
```python
jacket_cache_dir = os.environ.get("PJSK_JACKET_CACHE_DIR", "").strip()
if not jacket_cache_dir:
    jacket_cache_dir = cfg.get("jacket_cache_dir", "").strip()
if jacket_cache_dir:
    try:
        jacket_cache = JacketCache(cache_dir=jacket_cache_dir, client=http_client)
        if jacket_cache.cache_disabled:
            _logger.warning("JacketCache dir unwritable: %s", jacket_cache_dir)
            jacket_cache = None
    except Exception:
        _logger.exception("Failed to create JacketCache")
        jacket_cache = None
```

### 1.5 现有行为保留

- 5 并发下载 (`_FETCH_SEM`)
- 原子写入 (`tempfile.mkstemp` + `os.replace`)
- 共享 `httpx.AsyncClient`
- 缓存命中跳过 CDN
- `prefetch_jackets()` 返回 `dict[int, str]`，失败曲目不出现
- 日志脱敏（不输出完整 URL）

## 2. 本地渲染开发环境

### 2.1 Dev 渲染服务 (`ops/run-render-dev.ps1`)

```powershell
.\.venv\Scripts\python.exe -m uvicorn render_service.main:app --host 127.0.0.1 --port 3001 --reload
```

- 端口 3001，绝不碰 3000 或 VPS
- `--reload` 处理 Python 改动；JS 修改后重新 POST 即可

### 2.2 样例 Payload (`tests/fixtures/render/b20_preview.json`)

- 2 首虚构歌曲的 B20 数据
- jacket 使用 data URL 小占位图（灰色 1×1 WebP），无外部依赖
- 不依赖真实 QQ 用户、生产数据库或外网

### 2.3 预览脚本 (`tools/render_preview.py`)

```
python tools/render_preview.py --template b20 --payload tests/fixtures/render/b20_preview.json
python tools/render_preview.py --template b20 --output artifacts/render-preview/my-test.png
```

参数：
- `--template` (required): b20 | difficulty
- `--payload` (optional): JSON 文件路径，默认使用内置 fixture
- `--url` (optional): 默认 `http://127.0.0.1:3001`
- `--output` (optional): 输出 PNG 路径，默认 `artifacts/render-preview/{template}_{timestamp}.png`

行为：
- POST `{url}/render/{template}`
- 校验响应 Content-Type 是 `image/png`
- 校验 PNG 签名（前 8 字节）
- 失败时打印简洁错误到 stderr，exit 1
- 成功时打印文件路径和尺寸到 stdout

### 2.4 文档 (`docs/development/render-preview.md`)

覆盖：安装 `.[dev,render]` → 安装 Playwright Chromium → 启动 dev 服务 → 生成 PNG → 浏览图片 → 关闭服务。不引用旧 `/root/data/plugins/...` 路径。

### 2.5 旧部署文件清理

- `ops/pjsk-renderer.service`：更新 WorkingDirectory 和 ExecStart 指向 `/opt/pjsk-astrbot/current`，添加注释指向新布局
- `ops/deploy-render-service.sh`：添加废弃注释，指向 `docs/production/PRODUCTION-OPERATIONS.md`

### 2.6 `.gitignore`

添加 `artifacts/render-preview/`

## 3. 测试策略

### Commit 1 测试
- `test_webp_signature_valid` — 有效 RIFF/WEBP 签名 → 缓存
- `test_non_webp_rejected` — HTML/JSON 响应 → 不缓存，返回 None
- `test_cache_dir_unwritable` — 不可写目录 → `cache_disabled = True`，不崩
- `test_env_var_takes_priority` — `PJSK_JACKET_CACHE_DIR` 环境变量优先

### Commit 2 测试
- `test_render_preview_valid_png` — 有效渲染返回 200 + PNG
- `test_render_preview_bad_template` — 未知模板 → 非零退出
- `test_health_returns_functions` — GET /health 返回函数列表
- render service import + app object 测试（已有）
- visual 测试标记为 `@pytest.mark.visual`，不在普通 CI 运行

## 4. 提交计划

1. `feat: wire persistent jacket disk cache` — JacketCache 加固 + bootstrap 环境变量
2. `feat: add local render preview workflow` — dev 脚本 + fixture + preview 工具 + docs + ops 清理
