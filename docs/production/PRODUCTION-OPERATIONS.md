# PJSK Emu Bot Production Operations — Mandatory Read

> **Status: Under Review**
>
> 任何涉及 VPS、systemd、部署、回滚、数据库、NapCat、CDN、渲染服务的任务，执行者必须完整阅读本文。未阅读不得执行生产写操作。

---

## A. 生产拓扑

### 最终目标拓扑

```text
国内 VPS：
  NapCat (OneBot v11 client)
    → 反向 WebSocket → 香港 VPS NoneBot listener

香港 VPS：
  pjsk-onebot.service      (NoneBot 2 standalone gateway — 目标状态)
  pjsk-renderer.service    (FastAPI + Playwright 渲染)
  pjsk-cdn.service          (图片 CDN — 建议独立，待设计)
  SQLite                    (/opt/pjsk-astrbot/shared/data/pjsk.db)
  Redis                     (可选，fail-safe)
```

### 迁移期共存服务

以下服务在迁移期间仍存在，不属于最终拓扑。状态为 2026-07-16 审计快照：

| 服务 | 状态（审计时） | 角色 | 处置 |
|------|--------------|------|------|
| `pjsk-emu-bot.service` | active/running (pid 762758, since Jul 11; OneBot connection status: **unknown** — health endpoint returned `online:false` with last heartbeat ~50h ago, but this has not been independently verified against NapCat logs) | 旧 NoneBot | 冻结、归档、待切换后停用 |
| `astrbot.service` | active/running | AstrBot + 我们的插件 | 保留，退出生产消息链 |
| `render-service.service` | loaded, enabled, crash-looping（未 mask；`Restart=always, RestartSec=3`） | 旧渲染器（`/opt/render_service/`） | 待批准后 stop/disable/mask；当前端口 3000 由 `pjsk-renderer.service` 持有，旧服务启动即 EADDRINUSE 崩溃 |

**审计依据**：2026-07-16 `systemctl list-units --all`, `systemctl status`, `ss -tlnp`, `curl /health/napcat`, `journalctl -u pjsk-emu-bot` (last log Jul 14). NapCat 日志未查阅，OneBot 实际连接状态未经独立验证。

> **以上是审计快照，不是永久事实。任何生产操作前必须重新查询实际状态，不得照抄历史状态做决定。**

---

## B. 当前服务登记表

> 填写前必须现场查询 `systemctl is-active` 和 `ss -tlnp`。不得根据旧聊天记录猜测。

| 字段 | 说明 |
|------|------|
| service | systemd unit 名 |
| purpose | 服务用途 |
| expected state | 最终目标状态 |
| port | 监听端口 |
| code path | 源码路径 |
| data path | 数据路径 |
| owner | 责任人 |
| rollback role | 回滚时的处置 |
| may stop without approval | Yes/No |

（完整表格在生产切换前填写——当前 Phase 仅做文档框架。）

---

## C. 数据分类

### Immutable release（每次发布不可变）

- 源码
- 锁定依赖（`requirements.txt` 或 lock 文件）
- 模板（渲染 HTML/JS）
- migration 代码
- manifest

### Shared persistent（跨 release 持久）

- `bot.env`（密钥，权限 600）
- `pjsk.db`（SQLite 生产数据库）
- `backups/`（数据库备份）
- `cache/images/`（CDN 图片缓存）
- `logs/`（应用日志）

### Ephemeral（可随时丢弃）

- 临时文件
- 进程内存缓存
- Playwright Page/Context
- `/tmp` 下非持久文件

**Release 包不得包含**：`.env`、数据库、日志、缓存、`.pyc`。

---

## D. 标准发布布局

```text
/opt/pjsk-astrbot/
  releases/
    <release_id>/           # 完整不可变 release
      gateway/
      pjsk_core/
      pjsk_runtime/
      adapters/
      render_service/
      ops/
      chart_data/
      requirements.lock
      manifest.json
    <previous_release_id>/  # 保留为回滚候选
  current -> releases/<release_id>   # 原子软链接
  shared/
    bot.env                 # 600, owner pjsk
    data/
      pjsk.db
      backups/
    cache/
      images/
    logs/
```

**systemd 必须从 `current` 启动**，不得指向临时上传目录或 `releases/<id>` 直接。

---

## E. Release Manifest

每个 release 必须包含 `manifest.json`：

```json
{
  "release_id": "2026-07-16-<sha7>",
  "git_sha": "full 40-char SHA",
  "git_dirty": false,
  "build_time": "ISO-8601",
  "python_version": "3.11.x",
  "dependency_lock_hash": "sha256 of lock file",
  "source_manifest_sha256": "sha256 of all source files",
  "schema_version": 6,
  "chart_data_version": "2026-07-12",
  "renderer_template_version": "1.0",
  "required_env_names": ["<dynamic — see note>"],
  "migration_required": false,
  "previous_release_id": "<previous release id or null>"
}
```

**必须同时生成 release 内所有文件的 SHA-256 清单**（`manifest_files.sha256`）。

`required_env_names` 由构建时启用的引擎配置**动态生成**：`ONEBOT_ACCESS_TOKEN` + `ADMIN_QQ` + `CDN_BASE_URL` 始终必填；各引擎的 `*_API_KEY` 仅在该引擎 `enabled=true` 时列入。不硬编码固定列表。

---

## F. 发布前门禁

所有项目必须通过，任一项失败禁止部署：

```text
[x] git status 干净（无未提交改动）
[x] commit 可解析为完整 40-char SHA
[x] 完整测试通过（pytest）且 0 failed
[x] Ruff 通过
[x] Mypy strict 通过
[x] 架构边界测试通过（domain 零 I/O、application 零平台 import）
[x] 全模块 import 通过（python -c "import <all_modules>"）
[x] 所有相对 import 目标存在
[x] 依赖锁定完整
[x] 配置变量全部展开，无 ${UNEXPANDED_VAR} 残留
[x] 敏感文件扫描通过（release 不含 .env / database / 日志 / 缓存 / .pyc）
[x] 数据库迁移 dry-run（如需）通过
[x] health check endpoint 可执行
[x] 回滚 release 已存在且经 health 验证
```

---

## G. 原子发布流程

```text
1.  从干净 Git commit 构建完整 release（生成所有文件 + manifest）
2.  上传到新的 /opt/pjsk-astrbot/releases/<release_id>/
3.  校验 manifest 文件 hash 与预期一致
4.  在未切换 current 时执行预检（见 §G.2 预检端口隔离）
5.  如需数据库迁移 → 单独审批，不在本流程内自动执行
6.  使用独立的 preflight 端口启动新 release health check
7.  原子切换 current：
    a.  flock /opt/pjsk-astrbot/.deploy.lock  # 防并发发布
    b.  ln -s releases/<release_id> /opt/pjsk-astrbot/current.new
    c.  校验 current.new 指向预期 release：
        [ "$(readlink -f /opt/pjsk-astrbot/current.new)" = "/opt/pjsk-astrbot/releases/<release_id>" ]
    d.  mv -T /opt/pjsk-astrbot/current.new /opt/pjsk-astrbot/current
        # mv -T 在同文件系统内是原子的 — 不经过"先删除旧链接"的窗口
    e.  校验 current 指向预期 release
    f.  释放锁
8.  systemctl restart pjsk-onebot.service
9.  检查 health：curl /health → status=ok
10. 执行受控 smoke test（至少 1 条私聊消息，写入隔离确认）
11. 观察窗口 ≥ 15 分钟，监控错误率和延迟
12. 记录 deployment record（见 §L）
```

**禁止**：向现有 release 目录覆盖文件。每个 release 是全新的不可变目录。
**禁止**：使用 `ln -snf` 切换 `current`——它可能先 unlink 旧链接再创建新链接，存在短暂空窗。

### G.2 预检端口隔离

新旧 release 不能同时绑定同一端口。预检使用以下策略：

**采用方案：独立 preflight 端口**

- 新 release 启动时使用 `PREFLIGHT_PORT=<临时端口>`（通过 environment 或命令行参数传入）。
- Preflight 端口不与生产端口冲突，仅用于 health check + import 验证。
- Preflight 进程完成后立即停止；不进入正式消息处理循环。
- Smoke test 仅在正式切换后执行——此时旧 release 已停止，端口已释放。

**禁止**：
- 在生产端口上同时运行新旧实例（端口冲突）。
- Smoke test 在预检阶段写入生产数据库——预检只做只读验证。Smoke test 的写入在切换后执行，且必须能区分并回滚。

---

## H. 回滚定义

**三类回滚是不同的操作，不得混淆。**

### H.1 Code Rollback（代码回滚）

```text
current → previous verified release

条件：
- previous release 已通过当时全部门禁
- manifest 完整
- 无数据库 schema 降级需求
```

### H.2 Service-Entry Rollback（服务入口回滚）

```text
停止新 gateway
启动经过冻结和验证的旧入口

前提（旧 Bot 为例）：
- 旧 Bot 已完成冻结基线（见 §I）
- 已确认旧 Bot 可独立启动并响应 health check
- 已确认不依赖已变更的共享状态

当前 /opt/pjsk-emu-bot 尚未完成冻结基线，
不是可靠回滚候选。
```

### H.3 Database Recovery（数据库恢复）

```text
必须单独设计、单独审批。
不得包含在普通服务回滚脚本中。
不得在回滚操作中自动执行 cp pjsk.db.bak-* pjsk.db。
```

### 回滚步骤（以 standalone gateway 回滚到旧 Bot 为例——旧 Bot 冻结后生效）

```text
1. systemctl stop pjsk-onebot.service
2. systemctl start pjsk-emu-bot.service
3. 验证旧 bot 恢复（health check）
4. 观察 5 分钟确认正常
5. 记录故障原因和时间线
```

**数据库不回滚。** 新 gateway 切换期间写入的成绩保留在新数据库中，标记 `source_gateway="onebot"`。增量数据在事后评估处理方式。

---

## I. 旧生产冻结基线

在将 `pjsk-emu-bot.service` 用作正式回滚候选前，必须执行以下只读流程：

```text
1.  不修改 /opt/pjsk-emu-bot 目录
2.  记录完整文件列表（find /opt/pjsk-emu-bot -type f）
3.  计算所有文件的 SHA-256
4.  记录 Python 版本（python3 --version）和已安装包（pip freeze）
5.  静态检查所有 import 是否可解析
6.  标记：
    - Git 有 / VPS 无
    - VPS 有 / Git 无（孤儿文件）
    - 活代码（被 import）/ 死代码（未被引用且非入口）
7.  制作归档（tarball，记录 sha256）
8.  在隔离环境 smoke test（启动、health check、至少一条消息往返）
9.  生成 legacy baseline ID（例：legacy-2026-07-16-<sha256前8位>）
```

**只有完成以上全部步骤后，旧 Bot 才能被称为"冻结回滚候选"。**

### 已确认的生产漂移（2026-07-16 审计）

```text
Git 有 / VPS 无：
  - src/core/throttle.py
  - 部分限流接线

VPS 有 / 当前 Git 无（孤儿文件）：
  - src/core/player_class.py
  - 其他可能的历史残留

生产仍依赖 VPS 孤儿文件：
  handler_b20.py → import core.player_class
```

---

## J. 数据库红线

- **不直接修改生产数据库。** 任何写入必须经过 application → repository adapter。
- 审计**只从只读快照**进行（`sqlite3 file.db "mode=ro"` 或 `cp --reflink` 后读副本）。
- 不在启动时隐式执行大规模 schema 变更。Migration 必须显式版本化。
- 备份**不等于**迁移授权。
- **回滚服务不自动回滚数据库**（见 §H.3）。
- 禁止输出用户级数据（QQ 号、游戏 ID、OCR 原文、图片地址）。
- 聚合审计不能包含任何可识别个人身份的信息。
- 新旧库切换必须有完整的对账报告（用户数、成绩数、抽样 B20、难度排行）。

---

## K. 紧急热修

**原则：禁止 VPS 直接热修。**

如果生产完全不可用且用户明确批准紧急热修：

```text
1. 先记录当前 release ID 和 Git SHA
2. 创建 Git hotfix 分支（从当前 release 对应的 commit）
3. 在 Git 中完成修复并跑完整测试
4. 构建完整的 hotfix release（含 manifest）
5. 按标准原子发布流程（§G）上线
```

仍**不得**直接编辑 `current` 目录中的文件。

如果确实发生了人工生产修改（任何原因）：

```text
1. 停止后续覆盖式部署（暂停所有 scp/rsync/手动编辑）
2. 导出 diff：diff -r current/ releases/<last_known_good>/
3. 回流 Git：diff → patch → git apply → commit
4. 代码审查
5. 跑完整测试
6. commit
7. 重新构建正式 release
8. 替换手改状态
```

---

## L. 操作记录

每次生产写操作必须记录：

```text
timestamp:        ISO-8601
operator:         执行者
user_approval:    用户批准引用（消息时间/内容摘要）
old_release:      切换前的 release ID
new_release:      切换后的 release ID
git_sha:          full 40-char SHA
schema_version:   迁移后的 schema version（如无迁移则 N/A）
commands:         执行的命令类别（deploy / rollback / hotfix / migrate）
health_result:    health check 结果
smoke_result:     smoke test 结果
rollback_result:  如执行了回滚，记录结果
incident_link:    关联的事故记录
```

**不得记录**：密钥、密码、QQ 号、游戏 ID、OCR 原文、图片地址。

---

## M. 旧 Bot 事故链（禁止覆盖式部署的依据）

### 事故 1：2026-07-11 全量 SCP 覆盖

```text
动作：scp -r src
结果：
  - Git 旧版覆盖 VPS 手改新版
  - calc_kn_power 参数数量不兼容
  - run_ocr_race 候选数据结构不兼容
  - render_ocr_card 字段结构不兼容
  - OCR 多条链路同时崩溃
恢复来源：/tmp/emu-bot-backup-src-20260709-191514
对应提交：1004c2c
```

### 事故 2：2026-07-11 单文件部署

```text
动作：只部署 src/__init__.py
结果：
  - 新 __init__.py import throttle
  - VPS 没有 throttle.py
  - Application startup failed
  - systemd 自动重启 → 每数秒崩溃一次
对应提交：f615d2a, 099d5dd, 54ce6f0
```

### 事故 3：2026-07-12 孤儿模块

```text
生产 handler_b20.py → import core.player_class
当前 Git 分支没有 player_class.py
生产仅因 VPS 遗留孤儿文件存在而没有立即崩溃
```

**教训**：
- "生产当前能启动"不能证明"Git 可完整部署"。
- "回滚到旧版本"不能证明"回滚一定有效"。
- 单文件覆盖和目录覆盖在生产中反复证明是灾难性的。

---

> **本文档待 Phase 5 批准后从 Under Review 改为 Approved。**
