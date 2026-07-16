> **Status: Superseded** by Phase 5 standalone OneBot gateway direction.
> **Historical reference only.** Do not use as current implementation authority.
> Current spec: `docs/superpowers/specs/2026-07-16-phase-5-standalone-onebot-gateway-design.md`
> Current governance: `CLAUDE.md` §18.

# PJSK AstrBot 重构设计

日期：2026-07-12

## 目标

从旧 `emu-bot` 中提取经过验证的 PJSK 业务知识和历史数据，在独立仓库重建 AstrBot 插件。AstrBot 是首要入口，QQ 官方 Bot 预留适配器，NapCat/OneBot 仅作为兜底。所有新服务以香港 VPS 为主，国内 VPS 只保留 NapCat 和反向隧道。

首版提供注册、成绩截图上传、多视觉模型识别、候选确认、成绩入库、B20、民间精确定数全局排行和包含未游玩谱面的个人难度排行。不迁移独立批量会话、Astrobot 人格或传统 OCR。

## 架构

业务核心与 AstrBot 插件同进程运行，但通过 ports 解耦；FastAPI + Playwright 渲染继续作为独立服务。

```text
AstrBot Plugin ─┐
Official QQ ────┼→ Application → Domain → Ports
OneBot Fallback ┘                    ↓
                         SQLite / Redis / Vision / Renderer
```

```text
plugin/                 AstrBot 生命周期、事件转换和回复呈现
pjsk_core/domain/       同步、无 I/O 的业务规则
pjsk_core/application/  异步用例编排
pjsk_core/ports/        repository、vision、renderer、identity、cache 接口
adapters/database/      SQLite schema、repository 和版本化迁移
adapters/vision/        Gemini、智谱、StepFun 等视觉模型适配器与竞速器
adapters/rendering/     独立渲染服务 HTTP 适配器
adapters/cache/         Redis 与进程内降级实现
adapters/gateways/      AstrBot、官方 QQ、OneBot 适配器
chart_data/             Git 管理的民间精确定数与版本 manifest
render_service/         FastAPI + Playwright
tools/                  旧库迁移、定数导入、启动自检
tests/                  domain、application、adapter、迁移和故障测试
ops/                    香港 VPS 原子发布和 systemd
```

`domain` 不依赖数据库、网络、AstrBot 或具体厂商；`application` 只依赖 ports；gateway 不包含业务规则。以后可将 application 包装成 HTTP 服务，无需重写领域逻辑。

## 用户身份

QQ 号是主要身份，数据库关系使用内部 `users.id`。AstrBot/NapCat 可直接提供 QQ 号；官方 Bot 的 OpenID 保存在 `external_identities`，通过一次性绑定码映射到既有 QQ 用户。官方入口不得自行推断 QQ 号。

```text
users(id, qq_number UNIQUE, game_id, created_at, updated_at)
external_identities(id, user_id, platform, external_id, created_at)
```

## 成绩模型

每次成功确认均保存独立历史记录，即使图片和成绩完全相同也不去重；同一事务内更新个人最佳。

```text
score_attempts(
  id, user_id, chart_id,
  perfect, great, good, bad, miss,
  accuracy, rating, status,
  image_sha256, source_gateway, ocr_run_id, created_at
)

personal_bests(
  user_id, chart_id, best_attempt_id,
  accuracy, rating, status, updated_at
)
```

B20 只选择 FC/AP 的个人最佳，再按 Rating 降序取前 20。CLEAR 不进入 B20，但参与个人难度完成信息。

“我的 MA31”等个人难度视图从该难度等级的全部谱面出发，左连接个人最佳，展示未游玩、CLEAR、FC、AP、达成率、Rating 和判定。全局难度排行仅按民间精确定数降序并以 0.1 分档，不使用社区通过率统计。

## 曲目与定数数据

`songs` 保存曲目信息，`charts` 保存难度、官方等级、Note 数、民间精确定数和数据版本。民间精确定数的唯一真相源是 Git 中人工审核的版本化数据文件；SQLite 是运行时查询副本。

香港 VPS 定时检测仓库更新。新数据必须通过 schema、曲目覆盖率、重复项、定数范围和异常变更校验，随后事务性导入并刷新排行缓存。失败保留上一版并发送一次告警。每个排行结果记录 `chart_data_version`。

## 视觉模型竞速

不迁移 PP-OCR/ONNX。视觉识别通过统一接口支持 Gemini、智谱、StepFun 及未来引擎：

```python
class VisionEngine(Protocol):
    name: str

    async def recognize(
        self,
        image: bytes,
        *,
        timeout: float,
    ) -> OcrObservation: ...
```

每个引擎独立配置启用状态、优先级、模型、超时、最大并发和熔断。默认并行调用 2–3 个免费模型，以稳定、快速和准确为优先目标。

厂商响应统一为歌曲名、难度、显示等级和五项判定。结果再经过本地曲名匹配、谱面难度与 Note 总数校验。两个独立模型一致时形成强共识并完整取消、回收其余任务；单模型仅在强校验通过且其他模型超时或不可用时降级采用。

无法形成共识时生成编号候选。候选与用户绑定、有短 TTL、只允许消费一次；Redis 不可用时降级到进程内存。候选排序综合曲名相似度、难度、Note 数差异和模型支持数。

```text
ocr_runs(id, user_id, image_sha256, final_state, selected_engine, created_at)
ocr_observations(id, ocr_run_id, engine, elapsed_ms, parsed_result,
                 matched_chart_id, validation_state, error_type)
```

私聊连续发图时每张图都是独立任务，自然形成批量处理；通过用户级和全局并发上限保护模型，不建立“开始/结束批量”会话。

## 多入口

gateway 将平台事件转换成只含业务所需信息的标准事件：入口类型、外部用户标识、已知 QQ 号、会话类型和 ID、消息 ID、文本、图片与回复 token。

核心返回 `TextReply`、`ImageReply`、`CandidateReply`、`ProgressReply` 或 `ErrorReply`，不生成 CQ 码或 AstrBot 消息对象。

AstrBot 是首版生产入口；聊天人格完全交给 AstrBot。官方 QQ 首版只保留接口和 OpenID 绑定流程。迁移完成后，NapCat/OneBot 必须通过轻量 adapter 调用同一核心，不保留第二套业务实现。NapCat 离线只影响该 gateway，不停止 AstrBot、数据库、OCR 或渲染服务。

## 渲染

独立渲染服务复用 Browser，单次任务使用独立 Page/Context 并在 finally 关闭；限制并发，设置超时，浏览器断开后最多自动重建一次。

业务核心只依赖 `Renderer` port。B20、全局排行和个人排行使用版本化请求结构，响应包含 renderer/template 版本。缓存 key 包含用户、查询参数、数据更新时间、定数版本和模板版本。渲染失败返回文本摘要，不使查询整体失败。

## 数据库迁移

沿用现有 SQLite 数据，迁入新 schema，不建立两套长期正式数据库：

1. 从生产库制作只读快照并审计数量、重复身份、空值和孤儿成绩。
2. 导入用户、曲目、谱面和别名。
3. 旧成绩逐条转换为 `score_attempts`。
4. 按新规则重新计算 `personal_bests`。
5. 对账用户数、attempt 数、抽样 B20、全局排行和个人排行。
6. 新插件先对快照影子查询，不写生产库。
7. 切换时短暂停止旧 Bot 写入，执行最终增量迁移。
8. 新插件成为唯一写入者；旧 NapCat 改用新核心。

旧数据库和迁移前备份长期保留。schema 变化使用显式版本化迁移，不在插件启动时隐式重写大表。

## 香港 VPS 部署

```text
/opt/pjsk-astrbot/
├─ releases/<release_id>/
├─ current -> releases/<release_id>
└─ shared/
   ├─ bot.env
   ├─ data/pjsk.db
   ├─ cache/
   └─ backups/
```

AstrBot、SQLite、Redis、视觉模型编排与渲染服务都位于香港 VPS。国内 VPS 只运行 NapCat 和反向隧道。

发布包记录 Git commit、文件哈希、依赖锁、schema、定数和渲染模板版本。发布前通过测试、迁移对账、全模块导入、配置检查和敏感文件扫描；上传到新 release 目录并完成健康检查后原子切换 `current`，失败自动回滚。Redis 是可选能力，不能由 systemd `Requires=` 变成硬依赖。

## 测试与切换

- Domain：Rating、FC/AP、B20、个人最佳和候选排序。
- Application：内存 repository 下的注册、识别、确认与事务。
- Adapter：SQLite、Redis、视觉响应解析和渲染 HTTP 契约。
- Migration：生产库脱敏副本的数量和业务结果对账。
- Gateway：AstrBot 模拟事件和回复映射。
- Failure：Redis、单模型、渲染服务和 NapCat 分别故障。
- Import：干净环境导入全部正式模块。

切换顺序为：仓库骨架 → 曲目数据 → 旧库迁移器 → OCR → 成绩事务 → B20/排行 → AstrBot 测试入口 → 影子比对 → 最终增量迁移 → AstrBot 主写 → NapCat 新适配器。观察完整周期后才提出旧代码删除清单。

## 代码提取策略

旧仓库中的每个候选模块分为四类：直接提取、重写接口后提取、仅保留行为测试、删除候选。不会整体复制旧 `src/`。

优先提取并重新测试：准确率、Rating、成绩状态、曲名匹配、Note 校验、B20 规则、精确定数排行规则、曲目数据、历史用户成绩和 HTML/JS 视觉资产。

首版明确不迁移：传统 OCR、批量会话状态机、Astrobot 人格、旧 `features/db.py`、NoneBot matcher、CQ 码、裸后台任务和生产运行垃圾。任何旧文件删除都必须另列证据、影响和回滚路径，并获得明确批准。
