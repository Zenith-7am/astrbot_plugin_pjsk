# PJSK Emu Bot — 项目宪章与开发指南（CLAUDE.md）

> 本文件是本仓库的**最高执行约束**。它规定「怎么工作、不许偏差」。
> **需求真相源**是设计规格与阶段计划；本文件与它们冲突时，以规格/计划为准，并**先向用户澄清，不得自行决定**。
>
> - 当前设计规格：`docs/superpowers/specs/2026-07-16-phase-5-standalone-onebot-gateway-design.md`
> - 生产必读：`docs/production/PRODUCTION-OPERATIONS.md`
>
> 开始任何工作前必须完整阅读上面两份文档，以及当前阶段已批准的实施计划。

---

## 0. 语言与协作约定

- 与用户对话用**中文**；代码、注释、commit message、标识符用**英文**。
- 谨慎优先于速度。范围不明、规格冲突、或涉及删除/生产/密钥时——**先问，不猜**。
- 外科手术式改动：只碰当前任务必须碰的文件，不顺手重构无关代码。

---

## 1. 项目定位

独立的 **PJSK 成绩识别与排行系统**。从旧 `emu-bot` 中**提取经过验证的 PJSK 业务规则与历史数据**，在干净的分层架构里重建。旧仓库 `D:\emu-bot` 只作**只读参考**，不整体复制其 `src/`。

**为什么重建**：旧库长期存在 git↔生产漂移（孤儿文件、缺模块地雷、全量 scp 覆盖手改版），故障面无法收窄。新库以「git 唯一真相源 + 原子发布 + 版本化迁移 + 依赖方向机械强制」根治。

**入口优先级**（三者共享同一业务核心/数据库/规则，**禁止复制三套实现**）：

1. **NoneBot 2 + OneBot v11 standalone gateway** — 当前首要生产入口。
2. **QQ 官方 Bot** — 首版只预留正式适配器接口 + OpenID 绑定流程，不做完整生产连接。
3. **AstrBot** — 历史实现，非当前生产入口。代码暂时保留，未经独立清理任务批准不得删除。不继续投入开发。

**部署布局**：香港 VPS 承载 standalone gateway / SQLite / 视觉编排 / 渲染服务；国内 VPS 只留 NapCat + 反向隧道。

---

## 2. 仓库与工作区

| 项 | 值 |
|----|----|
| 新仓库 | `D:\pjsk-astrbot` |
| 旧仓库（只读参考） | `D:\emu-bot` |
| 当前开发 worktree | `D:\pjsk-astrbot\.worktrees\foundation-scaffold` |
| 当前分支 | `codex/foundation-scaffold` |
| 技术栈 | Python **3.11+**、pytest、pytest-asyncio、dataclasses、typing.Protocol、SQLite（`mode=ro` 审计）、ruff、mypy strict |

---

## 3. 架构（六边形 / ports & adapters，向内构建）

依赖方向（**单向，机械强制**）：

```text
gateway / matchers
       ↓
   application
       ↓
 domain + ports
       ↑
  adapters 实现 ports
```

目录结构：

```text
gateway/                NoneBot 2 bot 入口、matchers、OneBot 事件转换与回复
  bot.py
  matchers/
  adapters/
  connection_monitor.py
  health.py

pjsk_runtime/           平台无关 Composition Root
  bootstrap.py

pjsk_core/
  domain/               同步、无 I/O 的纯业务规则
  application/          异步用例编排，只依赖 ports
  ports/                repository / vision / renderer / identity / cache 窄接口

adapters/
  database/             SQLite schema、repository、版本化迁移
  vision/               Gemini / 智谱 / StepFun / DashScope 适配器与竞速器
  rendering/            独立渲染服务 HTTP 适配器
  cache/                进程内候选存储与降级

render_service/         FastAPI + Playwright 独立渲染服务
chart_data/             Git 版本化民间精确定数 + manifest
tools/                  旧库迁移、定数导入、启动自检
tests/                  domain / application / adapter / gateway / failure 测试
ops/                    香港 VPS systemd 单元
docs/
  production/           生产必读文档
  superpowers/specs/    设计规格
  superpowers/plans/    实施计划
```

### 强制规则（违反即为缺陷，由测试机械检查）

1. `domain` 必须**同步、纯计算、无 I/O**。
2. `domain` **不得 import**：application / ports / adapters / gateway / NoneBot / SQLite / Redis / httpx / 任何视觉模型 SDK。
3. `application` 只能依赖 `domain` 和 `ports`。
4. `application` **不得认识** NoneBot / OneBot / AstrBot / QQ 官方 Bot 事件对象。
5. `ports` 只定义窄接口，不放业务实现；repository 方法返回**领域对象**，不返回 dict 或 SQLite 行。
6. `adapters` 实现数据库、Redis、视觉、渲染、平台接入。
7. `gateway` 只做事件转换与回复呈现，**不实现** Rating / B20 / OCR 共识 / 数据库规则。
8. 平台事件对象**不得进入**业务核心。
9. 核心领域接口**不得返回无类型的通用 `dict`**——优先 dataclass、enum、明确类型。
10. **不得把整个旧 `src/` 复制进新仓库。**

核心统一回复类型（不生成 CQ 码 / OneBot 消息段 / AstrBot 消息对象）：`TextReply` / `ImageReply` / `CandidateReply` / `ProgressReply` / `ErrorReply`。

---

## 4. 首版功能范围

**做**：用户注册；QQ 号↔PJSK 游戏 ID 绑定；成绩截图上传；多视觉模型并发识别；识别分歧时候选确认；成绩历史入库；个人最佳更新；B20；民间精确定数**全局难度排行**；**个人难度排行**（须显示该难度等级**全部谱面**：未游玩 / CLEAR / FC / AP）。

**不做**：独立批量上传会话；「开始/结束批量」状态机；聊天人格与 LLM 对话模型；传统 OCR / PP-OCR / ONNX；官方 QQ 完整生产连接；CQ 码业务逻辑。

私聊连发图：**每张图独立任务**，靠用户级 + 全局并发上限自然形成批量，不建会话。

---

## 5. 领域规则参考（PJSK 游戏机制）

> 以下规则从旧 `emu-bot` 提取，是 **`domain` 层实现依据**。已按 TDD 对齐旧仓库 fixtures（`D:\emu-bot\tests\test_accuracy.py`、`test_kn_power.py` 等），任何与旧结果的差异均已**记录并经批准**。当前执行边界见 §16。

### 5.1 判定系统

| 判定 | 权重 | 维持 Combo |
|------|------|-----------|
| PERFECT | 100% | ✅ |
| GREAT | 75% | ✅ |
| GOOD | 50% | ❌ |
| BAD | 0% | ❌ |
| MISS | 0% | ❌ |

### 5.2 达成率（Accuracy）

```text
accuracy = ((P×100 + G×75 + Good×50) / (total×100)) × 101.0000
         = (P + G×0.75 + Good×0.5) / N × 101
AP 时强制 = 101.0000%
```

评分等级：SSS+(≥101%) > SSS(≥100.75%) > SS+(≥100.5%) > SS(≥100%) > S+(≥99.5%) > S(≥99%) > …
（Great=75%、Good=50%，非 80% 拟合值。）

### 5.3 通关状态

```text
AP    : great=0 且 good=0 且 bad=0 且 miss=0 且 perfect>0
FC    : good=0 且 bad=0 且 miss=0（great≥0，GOOD 也断 Combo）
CLEAR : 其他
```

### 5.4 单曲 Rating（单曲 SP / Kn Power）

单次成绩独立计算，不参考历史 FC 状态。

```text
CLEAR: rating = Lv × (90 + s_clear)   # s_clear 封顶 6.5
  acc < 90%        : s = 0
  90% ≤ acc < 97%  : s = (acc-90)/7 × 3
  97% ≤ acc < 100% : s = 3 + (acc-97)/3 × 2
  100% ≤ acc <100.5: s = 5 + (acc-100)/0.5
  acc ≥ 100.5%     : s = 6.5

FC: rating = Lv × (98 + s)
  s = min(3, max(0, (达成率 - 100.5) × 6))

AP: rating = Lv × 101 + round(定数ボーナス × 20) + 70
  定数ボーナス = 小数部 + tag_bonus
    小数部: 32.5 → 0.5，32.5+ → 0.55（.5+ 小数部=0.55）
    tag_bonus: + → +0.05，- → -0.05，无 → 0
  仅 MASTER / APPEND / EXPERT 的 AP 生效（有精确定数的难度）
```

### 5.5 SEKAI POWER（SP）与 B20

```text
SP = B20平均 + 全FCボーナス + 全APボーナス
B20平均 = Top20 FC/AP 单曲 Rating 平均（CLEAR 不参与 B20 排名）
全FC/全AP bonus：当前阶段置 0，预留接口
```

B20 选取：只取 FC/AP 的**个人最佳** → 按 Rating 降序 → 取前 20；同 Rating 以 chart_id 决定性排序；不足 20 条也合法。

### 5.6 玩家段位（Player Class）

| 段位 | SP 范围 | 星级（步长） |
|------|---------|-------------|
| Beginner | 0–2,499 | ★0–4（每 625） |
| Bronze | 2,500–2,799 | ★0–4（每 75） |
| Silver | 2,800–2,949 | ★0–4（每 30） |
| Gold | 2,950–3,049 | ★0–4（每 25） |
| Platinum | 3,050–3,149 | ★0–4（每 25） |
| Diamond | 3,150–3,249 | ★0–4（每 25） |
| Master | 3,250–3,399 | ★0–4（每 30） |
| Grand Master | 3,400–3,938 | ★1–9（每 50） |
| SEKAI MASTER | 3,939+ | ★10 |

### 5.7 谱面定数与难度

- 引用 PENTATONIC 系（民间精确定数，`.1`~`.5`、`+/-` 后缀）；EXPERT 定数另有独立源。
- 难度范围：EASY(1–8) NORMAL(6–14) HARD(11–20) EXPERT(21–32) MASTER(24–37) APPEND(24–38)。
  - 基于实际 chart_data 更新：EXPERT 21–32（原 22–30）、APPEND 24–38（原 22–37）。
  - **已知数据异常**：song_id=241 在游戏中不存在，疑为 PJSK 官方编号疏漏（跳号）。chart_data 中该条目暂作占位保留，待深度查证后决定删除或修正。

| 难度 | 缩写 |
|------|------|
| EASY | EZ |
| NORMAL | NM |
| HARD | HD |
| EXPERT | EXP |
| MASTER | MAS |
| APPEND | APD |

### 5.8 Note 数验证

```text
|total_judges - expected_note| ≤ 1 → 通过（OCR ±1 容差）
```

### 5.9 歌名匹配

```text
Step 1 精确匹配（不区分大小写，位置+长度打分）
Step 2 标题区域提取（难度关键词截断 + UI 关键词过滤）
Step 3 模糊匹配（Dice 60% + Levenshtein 40%，阈值 0.50，位置 bonus）
Step 4 前缀匹配（≥5 字符，last resort）
OCR 纠错：口→ク  一→ー  才→オ  全角→半角
```

---

## 6. 用户身份

QQ 号是主要身份；数据库关联用内部 `users.id`。

```text
users(id, qq_number UNIQUE, game_id, created_at, updated_at)
external_identities(id, user_id, platform, external_id, created_at)
```

- Standalone gateway 和 NapCat 可直接提供 QQ 号。
- 官方 Bot 的 OpenID 存 `external_identities`，经**一次性绑定码**映射到既有 QQ 用户。
- **OpenID 不能替代 QQ 号成为内部主身份；官方入口不得自行推断 QQ 号。**

---

## 7. 成绩规则

双线存储，一次确认在**同一事务**内完成：

```text
score_attempts(id, user_id, chart_id, perfect, great, good, bad, miss,
               accuracy, rating, status, image_sha256, source_gateway,
               ocr_run_id, created_at)          # 每次确认都存，重复图/分也不去重
personal_bests(user_id, chart_id, best_attempt_id,
               accuracy, rating, status, updated_at)   # 同事务更新
```

- **B20**：只取 FC/AP 个人最佳，Rating 降序 Top20，CLEAR 不进 B20。
- **个人难度排行**（如「我的MA31」）：从该难度+官方等级的**全部谱面**出发，LEFT JOIN 个人最佳；无成绩显示「未游玩」；展示 CLEAR/FC/AP、准确率、Rating、判定。
- **全局难度排行**：只按民间精确定数降序、0.1 分档，高定数在前；**不使用通过率/FC率/AP率**。

---

## 8. OCR 与视觉模型

不使用传统 OCR。统一多引擎接口，禁止把业务绑定到某一家：

```python
class VisionEngine(Protocol):
    name: str
    async def recognize(self, image: bytes, *, timeout: float) -> OcrObservation: ...
```

统一响应 `OcrObservation`：`song_title, difficulty, displayed_level, perfect, great, good, bad, miss, engine, elapsed_ms`。

策略：

- 默认并发 2–3 个已启用免费模型；**稳、快、准优先于省调用**。
- 两个独立模型一致 → **强共识**；达成共识后**必须 `cancel()` 并 `await` 回收剩余任务**，不得 cancel 后直接返回。
- 单模型仅在**强校验通过**且其他模型超时/不可用时降级采用。
- 单模型故障不影响其他引擎；引擎连续错误进入**短期熔断**；每引擎独立配置超时/并发/优先级/启用状态。
- 模型结果继续经本地规则校验：曲名匹配、难度匹配、Note 总数校验、谱面存在性。
- 无共识 → **给编号候选，不直接判失败**。候选：绑发起用户、短 TTL、消费一次、进程内降级；排序综合模型支持数、Note 校验、曲名相似度、Note 差异。

```text
ocr_runs(id, user_id, image_sha256, final_state, selected_engine, created_at)
ocr_observations(id, ocr_run_id, engine, elapsed_ms, parsed_result,
                 matched_chart_id, validation_state, error_type)
```

---

## 9. 数据库与旧数据迁移

- 现有生产 SQLite 数据保留；新库用清晰新 schema。**单一 SQLite 血脉，不长期并行两套正式库。**
- 迁移只从生产库制**只读快照**，**不直接改生产库**。
- 先开发**只读审计器**（SQLite `mode=ro`），输出**只含聚合信息**；**禁止输出** QQ 号 / 游戏 ID / OCR 文本 / 图片地址等用户级数据。
- 流程：审计 → 导入用户/曲目/谱面/别名 → 旧成绩逐条转 `score_attempts` → 按新规则重算 `personal_bests` → 对账（用户数/成绩数/抽样 B20/难度排行）→ 影子查询 → 切换前备份 → 最终增量迁移 → 新库唯一写入。
- **数据库访问必须经 repository adapter，application 不得直接执行 SQL。**
- schema 变更用**显式版本化迁移**，**不得在启动时隐式大规模改表。**

---

## 10. 民间精确定数

真相源是 **Git 中人工审核的版本化数据文件**，不是 SQLite（SQLite 只是运行时查询副本）。

- 人工提交数据文件 → 香港 VPS 定时检测更新 → 导入前校验（schema / 曲目覆盖率 / 重复项 / 定数范围 / 异常变更）→ 通过则**事务性**更新 SQLite → 失败保留上一版并**告警一次** → 成功则刷新相关渲染缓存。
- 每条排行结果记录 `chart_data_version`。

---

## 11. 渲染

独立 FastAPI + Playwright 服务；**不得默认把 Chromium 塞进 gateway 进程**。业务核心只依赖 `Renderer` port。

- 复用 Browser；每次任务独立 Page/Context 且 **finally 关闭**；限并发 + 超时；浏览器断开**最多自动重建一次**。
- 请求/响应带 renderer/template 版本；缓存 key 含用户、查询参数、数据更新时间、定数版本、模板版本。
- **渲染失败返回文本摘要，不使查询整体失败。**

---

## 12. Redis 与可选能力（fail-safe）

- Redis 缺失/断开**不得崩主流程**；启动记录 degraded 状态。
- **不得由 systemd `Requires=redis-server.service` 变成硬依赖。**
- 候选状态、熔断状态可降级到进程内存。
- 不允许吞错误且无 warning；warning 必须**防刷**。

---

## 13. 部署（香港 VPS，原子发布）

```text
/opt/pjsk-astrbot/
  releases/<release_id>/
  current -> releases/<release_id>
  shared/{bot.env, data/pjsk.db, cache/, backups/}
```

- 从**干净 Git commit** 构建；依赖版本锁定；生成文件 SHA-256 manifest；记录 Git SHA / schema 版本 / 定数版本 / 渲染模板版本。
- 发布到新 release 目录 → 预检（测试 / 迁移对账 / 全模块导入 / 配置检查 / 敏感文件扫描）→ 健康检查 → **原子切换 `current`**，失败**自动回滚**。
- **不直接覆盖 live 源码；不通过 scp 单个源码文件拼装生产；发布包不含 `.env` / 数据库 / 日志 / 缓存 / `.pyc`。**

---

## 14. Git 唯一真相源（铁律）

**禁止**以下任何操作：

- `scp` / `rsync` 单个源码文件到 live 目录。
- `scp -r src` 覆盖 live 目录。
- 在 `/opt/.../current` 中直接编辑文件。
- 从 dirty worktree 构建。
- 从未提交代码构建。
- 在 VPS 上直接热修后不回流 Git。
- 部署缺少 manifest 的 release。
- 把生产孤儿文件复制进新项目而不审计来源。

**只允许**：

```text
clean commit
→ 构建完整 release
→ 生成 manifest
→ 在独立 release 目录预检
→ 原子切换 current
```

---

## 15. 安全红线

1. 不读取/输出 VPS 密钥；不打印 `.env` 内容。
2. **不修改、覆盖或删除生产数据库。**
3. 不重启生产服务，除非用户明确授权。
4. **不删除任何旧文件**，除非先列出：精确路径、无引用证据、删除原因、影响、回滚方式，并获**用户明确批准**。
5. 不把 QQ 号 / 游戏 ID / OCR 原文写入普通日志。
6. 不在 systemd 单元写明文 API key。
7. 不以 root/system Python 作为最终生产运行方案。
8. 不用 `git reset --hard` 或破坏用户现有修改。
9. 旧仓库只作参考，除非用户明确要求否则不得修改。
10. 生产回滚**不自动包含数据库恢复**——数据库恢复必须单独设计、单独审批。

---

## 16. 生产授权规则

**无需额外授权的只读操作**：

- 查询服务状态、端口、systemd 元数据。
- 计算源码 SHA-256。
- 静态 import 检查。
- 聚合错误数量。
- 读取脱敏健康状态。

**必须获得用户明确授权**：

- `systemctl stop/start/restart/mask/disable`。
- `kill` 进程。
- 修改 systemd unit。
- 修改生产文件。
- 创建、删除或切换 release。
- 修改 `current` 软链接。
- 数据库备份、迁移、恢复或写入。
- 修改 NapCat 配置。
- 部署代码。
- 清理缓存或旧目录。

即使用户说「处理一下」「看一下」，也不能解释为生产写授权。

---

## 17. 开发流程（TDD，铁律）

1. 先写**最小失败测试**（RED）。
2. 运行确认测试因目标功能缺失而失败。
3. 写**最小实现**（GREEN）。
4. 运行确认通过。
5. 重构后重新运行。
6. 每任务跑 **focused tests + 完整测试**。
7. 每任务**独立 commit**。

每完成一个任务必须报告：修改文件、新增接口、RED 证据、GREEN 证据、完整测试结果、Ruff 结果、Mypy 结果、commit hash、已知风险。

**禁止**：先写实现再补测试；一次实现多个计划任务；顺手重构无关文件；测试未通过就提交；只凭"应该没问题"宣布完成；未经审查进入下一阶段；创建 placeholder 函数或假实现。

---

## 18. 当前执行边界（最重要）

> **当前阶段：Phase 5 — Governance and Production Baseline**

Phase 1–4b（含 AstrBot 插件、OCR、B20、查询、渲染）已完成并标记为历史。
AstrBot 集成已停止继续开发，不属于当前生产路径。

**允许**：
- 文档修订（CLAUDE.md、生产 runbook、设计规格）
- 生产只读审计
- 旧生产归档设计
- release manifest 设计
- shadow composition root 设计
- 部署与回滚流程设计
- 测试计划设计

**禁止**：
- 实现 Gateway 业务代码
- 新增 matcher
- 修改生产源码
- 修改生产数据库
- 停止、启动或重启生产服务
- 终止生产进程
- 部署任何代码
- 删除 AstrBot 或旧 Bot 文件
- 创建 placeholder 函数或假实现

---

## 19. 开始工作时的固定步骤

1. 确认当前目录与分支。
2. `git status --short --branch`。
3. 完整阅读设计规格与当前阶段计划。
4. 检查工作树是否干净。
5. 运行基线：pytest / Ruff / Mypy。
6. 明确本次**只执行哪个任务**。
7. 若用户未授权业务实现，**立即停在文档/审计范围**。
8. 遇规格冲突或范围不明**先询问**，不自行决定。
9. 生产写操作前，确认已获得用户明确授权。
