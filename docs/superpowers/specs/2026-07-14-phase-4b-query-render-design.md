> **Status: Superseded** by Phase 5 standalone OneBot gateway direction.
> **Historical reference only.** Do not use as current implementation authority.
> Current spec: `docs/superpowers/specs/2026-07-16-phase-5-standalone-onebot-gateway-design.md`
> Current governance: `CLAUDE.md` §18.

# Phase 4b — B20, Difficulty Rankings & Render Service

> 设计规格。Phase 4a/4a.1 完成后编写。**不实现业务代码，不新建 migration，不操作 VPS。**

**目标：** 从 OCR 识别入库的成绩数据出发，提供 B20 查询、难度排行查询、APPEND 开关，以及独立的 FastAPI + Playwright 渲染服务。

**架构：** 4b-1（查询与偏好）→ 4b-2（渲染服务）→ 4b-3（AstrBot 接入）。每阶段可独立测试。domain 纯同步计算；application 异步编排只依赖 ports；渲染服务独立进程只接收预计算 payload。

---

## 1. 子阶段边界

### 4b-1：查询与偏好（可独立 pytest 测试）

- 新增 `Song` domain 类型 + `SongRepository` port
- 新增 `PlayerClass` domain 类型 + `calc_player_class()` 纯函数（从旧库 `a3070e7` git 恢复）
- `ScoreRepository` 扩展：B20 查询、难度排行查询
- `UserRepository` 扩展：`get_append_excluded()` / `set_append_excluded()`
- Migration 005：`users.append_excluded INTEGER NOT NULL DEFAULT 1`
- 新增 application 用例：`QueryB20`、`QueryDifficultyRanking`、`ToggleAppend`
- **零依赖渲染服务**——所有用例返回结构化 dataclass

### 4b-2：渲染服务（可独立 HTTP 测试）

- 独立 FastAPI + Playwright 进程，监听 `127.0.0.1`，systemd 管理
- 两个固定模板端点：B20 与难度排行（不接受任意 HTML 渲染）
- JS 渲染函数从旧 `b20.js` / `difficulty.js` 迁移，去掉 `calcKn`/`parseLevel`，改为从 Python 预计算值直接读取
- 曲封缓存 + 渲染缓存分层，原子写入
- `Renderer` port + HTTP adapter（业务核心不直接调渲染服务）

### 4b-3：AstrBot 接入（依赖 4b-1 + 4b-2）

- `/pjsk b20` — 个人 B20 查询
- `/pjsk ma31` / `/pjsk apd32` — 个人/全局难度排行（缩写复用旧项目兼容语义）
- `/pjsk append on|off|status` — APPEND 开关
- 渲染服务不可用时降级为文本摘要
- `PluginRuntime` 扩展：持有 `QueryB20` / `QueryDifficultyRanking` / `ToggleAppend` 用例 + `Renderer` adapter

---

## 2. Domain 层新增类型

### 2.1 Song

```python
# pjsk_core/domain/song.py

@dataclass(frozen=True)
class Song:
    """A PJSK song (independent of difficulty)."""
    id: int
    title_ja: str
    title_cn: str
    title_en: str
    aliases: str  # JSON array string
```

从旧项目 `src/data/models.py` 移植，字段一一对应。`aliases` 保持 JSON string 格式（与旧 DB 兼容），不引入额外的 alias 子表。

### 2.2 PlayerClass

```python
# pjsk_core/domain/player_class.py

@dataclass(frozen=True)
class PlayerClass:
    """Player rank (段位) derived from SEKAI POWER."""
    name: str            # e.g. "Diamond"
    icon: str            # emoji e.g. "💎"
    stars: int           # 0-10
    fallback_color: str  # CSS color name

def calc_player_class(sp: float) -> PlayerClass:
    """Pure function. Thresholds per CLAUDE.md §5.6."""
```

从旧项目 git commit `a3070e7` 恢复 `calc_player_class()` 源码，改为返回强类型 `PlayerClass` dataclass（非 dict），添加单元测试覆盖所有阈值边界。

### 2.3 查询结果类型

```python
# pjsk_core/domain/b20.py

@dataclass(frozen=True)
class B20Entry:
    """One entry in a B20 result."""
    rank: int
    song_id: int
    song_title: str          # resolved via SongRepository
    difficulty: Difficulty
    official_level: int
    community_constant: str  # e.g. "32.5+"
    status: ScoreStatus
    accuracy: float
    rating: float
    judgements: Judgements

@dataclass(frozen=True)
class B20Result:
    """Complete B20 query result."""
    entries: tuple[B20Entry, ...]  # 0-20 items
    sp: float
    player_class: PlayerClass
    b20_avg: float
    fc_bonus: float          # reserved, always 0.0 for now
    ap_bonus: float          # reserved, always 0.0 for now
    append_excluded: bool
    chart_data_version: str
```

```python
# pjsk_core/domain/difficulty_ranking.py

@dataclass(frozen=True)
class DifficultyRankEntry:
    """One entry in a difficulty ranking."""
    song_id: int
    song_title: str
    community_constant: str
    const_tag: str            # "+" / "-" / ""
    note_count: int
    personal_best: ScoreAttempt | None  # None = 未游玩
    is_played: bool

@dataclass(frozen=True)
class DifficultyRanking:
    """Complete difficulty ranking for one (difficulty, level) pair."""
    difficulty: Difficulty
    official_level: int
    mode: str                 # "global" or "personal"
    user_id: UserId | None    # None for global mode
    entries: tuple[DifficultyRankEntry, ...]
    chart_data_version: str
```

---

## 3. Ports 层新增

### 3.1 SongRepository

```python
# pjsk_core/ports/repositories.py (追加)

class SongRepository(Protocol):
    async def get_by_id(self, song_id: int) -> Song | None: ...
    async def get_all(self) -> list[Song]: ...
```

### 3.2 ScoreRepository 扩展

```python
# pjsk_core/ports/repositories.py (追加方法)

class ScoreRepository(Protocol):
    # … existing methods …

    async def get_b20(
        self, user_id: UserId, *, include_append: bool,
    ) -> list[ScoreAttempt]:
        """Return FC/AP personal bests, sorted by rating DESC, chart_id ASC.

        Filtering (append excluded, top-20) is done by the application layer.
        Repository returns ALL qualifying rows; application slices.
        """
        ...

    async def list_personal_bests_for_difficulty(
        self, user_id: UserId, chart_ids: list[int],
    ) -> dict[int, ScoreAttempt]:
        """Return personal bests keyed by chart_id for the given chart IDs."""
        ...
```

### 3.3 UserRepository 扩展

```python
# pjsk_core/ports/repositories.py (追加方法)

class UserRepository(Protocol):
    # … existing methods …
    async def get_append_excluded(self, user_id: UserId) -> bool: ...
    async def set_append_excluded(self, user_id: UserId, excluded: bool) -> None: ...
```

### 3.4 Renderer port

```python
# pjsk_core/ports/renderer.py (新文件)

@dataclass(frozen=True)
class RenderPayload:
    """Versioned, pre-computed payload for the render service."""
    template_name: str       # "b20" | "difficulty"
    renderer_version: str    # semantic version of the JS renderer
    chart_data_version: str
    payload_json: str        # JSON string — template-specific shape

class Renderer(Protocol):
    async def render(self, payload: RenderPayload) -> bytes | None:
        """Render to PNG bytes. Returns None on failure (never raises)."""
        ...
```

渲染失败不抛异常——返回 None，调用方降级为文本摘要。

---

## 4. Application 层新增用例

### 4.1 QueryB20

```python
# pjsk_core/application/query_b20.py

class QueryB20:
    def __init__(
        self,
        scores: ScoreRepository,
        songs: SongRepository,
        charts: ChartRepository,
        users: UserRepository,
    ) -> None: ...

    async def query(self, user_id: UserId) -> B20Result:
        """Fetch user's B20: filter FC/AP bests, exclude APPEND per preference,
        sort by rating DESC, take top 20, resolve song titles."""
        ...
```

流程：
1. `users.get_append_excluded(user_id)` → bool
2. `scores.get_b20(user_id, include_append=...)` → list[ScoreAttempt]
3. Application 层 slice top 20（Rating 降序，chart_id 升序 deterministic）
4. `charts.get_by_id()` 批量解析 chart → const info
5. `songs.get_by_id()` 批量解析 song → title
6. `calc_player_class(sp)` → PlayerClass
7. 组装 `B20Result`

### 4.2 QueryDifficultyRanking

```python
# pjsk_core/application/query_difficulty_ranking.py

class QueryDifficultyRanking:
    def __init__(
        self,
        charts: ChartRepository,
        scores: ScoreRepository,
        songs: SongRepository,
    ) -> None: ...

    async def query_global(
        self, difficulty: Difficulty, official_level: int,
    ) -> DifficultyRanking: ...

    async def query_personal(
        self, user_id: UserId, difficulty: Difficulty, official_level: int,
    ) -> DifficultyRanking: ...
```

流程：
1. `charts.list_by_difficulty_level(difficulty, official_level)` → 完整谱面目录
2. 按 community_constant 排序：定数降序 → 同数值 `+ > 无 > -` → `song_id` ASC
3. Personal 模式：`scores.list_personal_bests_for_difficulty()` → LEFT JOIN
4. 未游玩 → `personal_best=None, is_played=False`
5. `songs.get_by_id()` 批量解析歌名

### 4.3 ToggleAppend

```python
# pjsk_core/application/toggle_append.py

class ToggleAppend:
    def __init__(self, users: UserRepository) -> None: ...

    async def set(self, user_id: UserId, excluded: bool) -> bool: ...
    async def get(self, user_id: UserId) -> bool: ...
```

---

## 5. Migration 005

文件：`adapters/database/migrations/005_append_preference.sql`

```sql
-- 005: Add append_excluded preference to users
ALTER TABLE users ADD COLUMN append_excluded INTEGER NOT NULL DEFAULT 1;

-- Backfill: users with FC/AP APPEND scores are opted IN
UPDATE users SET append_excluded = 0
WHERE append_excluded = 1 AND id IN (
    SELECT DISTINCT pb.user_id FROM personal_bests pb
    JOIN charts c ON c.id = pb.chart_id
    WHERE c.difficulty = 'append'
    AND pb.status IN ('ap', 'fc')
);
```

`User` domain 类型同步新增 `append_excluded: bool` 字段（default=True）。

---

## 6. 独立渲染服务

### 6.1 部署架构

```text
/opt/pjsk-astrbot/
  releases/<id>/
    render_service/
      main.py          FastAPI app
      functions/
        _loader.js     registerRenderFunction() 注册器
        b20.js         B20 Canvas 渲染（无 calcKn）
        difficulty.js  难度排行 Canvas 渲染（无 parseLevel）

systemd: pjsk-renderer.service
  监听: 127.0.0.1:3000
  仅 localhost 可达
```

### 6.2 API

| 端点 | 方法 | Body | 返回 |
|------|------|------|------|
| `/health` | GET | — | `{"status":"ok","version":"1.0"}` |
| `/render/b20` | POST | `B20RenderPayload` JSON | `image/png` |
| `/render/difficulty` | POST | `DifficultyRenderPayload` JSON | `image/png` |

### 6.3 Render payload schema

**B20 渲染 payload：**

```json
{
  "renderer_version": "1.0",
  "chart_data_version": "2026-07-14",
  "player_name": "emu在看你",
  "sp": 34567.89,
  "player_class": {"name": "Diamond", "icon": "💎", "stars": 3, "fallback_color": "blue"},
  "b20_avg": 34000.0,
  "fc_bonus": 0.0,
  "ap_bonus": 0.0,
  "append_excluded": true,
  "entries": [
    {
      "rank": 1,
      "song_title": "幾望の月",
      "difficulty": "MASTER",
      "display_level": "32.5+",
      "status": "FC",
      "accuracy": 99.83,
      "rating": 33.12,
      "jacket_url": "data:image/webp;base64,..."
    }
  ]
}
```

**难度排行渲染 payload（全局 / 个人共用结构）：**

```json
{
  "renderer_version": "1.0",
  "chart_data_version": "2026-07-14",
  "mode": "personal",
  "difficulty": "MASTER",
  "official_level": 31,
  "player_name": "emu在看你",
  "total_played": 5,
  "total_charts": 12,
  "tiers": [
    {
      "label": "32.5",
      "songs": [
        {
          "song_id": 100,
          "song_title": "幾望の月",
          "community_constant": "32.5+",
          "note_count": 1123,
          "jacket_url": "data:image/webp;base64,...",
          "is_played": true,
          "status": "FC",
          "accuracy": 99.83,
          "rating": 33.12
        }
      ]
    }
  ]
}
```

### 6.4 渲染缓存策略

| 层 | 位置 | Key | 生命周期 |
|----|------|-----|---------|
| Jacket | 独立缓存目录（如 `/var/cache/pjsk/jackets/`） | `song_id` | 永久，手动清理 |
| Render | 独立缓存目录（如 `/var/cache/pjsk/renders/`） | `sha256(payload_json)` | 原子写入，持久化 |

- **Jacket 缓存**：本地文件 → CDN（`https://api.pjsk-rate-api.com/music/jacket/thumbnail_{sid}/thumbnail_{sid}.webp?v=2`）→ 下载失败用占位封面，整图正常生成
- **Render 缓存**：payload hash 不变则直接命中。chart_data 更新 → payload 变 → hash 变 → 自然失效
- 个人查询缓存按 hash 去重（相同 payload 不重复渲染）
- 不接受 payload 中的任意 URL（jacket 只从受信任 CDN 下载）

### 6.5 渲染器 HTTP adapter

```python
# adapters/rendering/renderer_adapter.py

class HttpRenderer:
    """HTTP adapter implementing Renderer port."""
    def __init__(self, base_url: str = "http://127.0.0.1:3000",
                 client: httpx.AsyncClient, ...) -> None: ...

    async def render(self, payload: RenderPayload) -> bytes | None:
        """POST to render service. Returns PNG bytes or None."""
        ...
```

### 6.6 旧资产迁移清单

| 源文件 | 迁移方式 |
|--------|---------|
| `render_service/main.py` | 复用架构，简化至仅两个端点 |
| `render_service/functions/_loader.js` | 直接复制 |
| `render_service/functions/b20.js` | 迁移 → **删除 `calcKn`/`parseLevel`** → 改为读取 Python 预计算值 |
| `render_service/functions/difficulty.js` | 迁移 → **删除 `parseLevel`** → 改为读取 Python 预计算值 |
| `src/data/jacket_cache.py` | 端口化 → `adapters/rendering/jacket_cache.py`，通过 `Renderer` port 注入 |
| `src/core/render_client.py` | `${CDN_BASE}/music/jacket/thumbnail_{sid}/thumbnail_{sid}.webp?v=2`，`sid = song_id` 零填充至 ≥3 位 |

---

## 7. AstrBot 接入（4b-3）

### 7.1 命令接口

| 命令 | 功能 | 用例 |
|------|------|------|
| `/pjsk b20` | 个人 B20 查询 | QueryB20 → Renderer.render → image |
| `/pjsk ma31` | MASTER 31 个人排行 | QueryDifficultyRanking.query_personal |
| `/pjsk apd32` | APPEND 32 全局排行 | QueryDifficultyRanking.query_global |
| `/pjsk diff ma31` | 同上，显式语法 | `diff <diff_abbr><level>` 解析 |
| `/pjsk ma31 global` | MA31 全局排行 | 显式 `global` 关键字 |
| `/pjsk append on` | 包含 APPEND 到 B20 | ToggleAppend.set(excluded=False) |
| `/pjsk append off` | 排除 APPEND | ToggleAppend.set(excluded=True) |
| `/pjsk append status` | 查看当前设置 | ToggleAppend.get |

难度缩写：`ez/nm/hd/exp/mas/apd`（不区分大小写）。解析逻辑放在 plugin 层。

### 7.2 PluginRuntime 扩展

```python
@dataclass
class PluginRuntime:
    # … existing fields …
    query_b20: QueryB20 | None
    query_difficulty: QueryDifficultyRanking | None
    toggle_append: ToggleAppend | None
    renderer: Renderer | None      # HttpRenderer adapter
    song_repo: SongRepository | None
```

### 7.3 渲染降级策略

```text
Renderer.render() → None (失败)
        ↓
QueryB20 仍然返回 B20Result
        ↓
Plugin 层检测无图 → 格式化为文本摘要
        ↓
TextReply: "B20 (SP 34567.89 · Diamond ★3):
           1. 幾望の月 MASTER 32.5+ · FC · 99.83% · Rating 33.12
           2. …"
```

渲染失败不阻断查询——用户总能看到文本结果。

---

## 8. 测试策略

### 4b-1（pytest）

| 层 | 测试内容 |
|----|---------|
| domain | `calc_player_class()` 阈值边界（0, 2499, 2500, 2799, 2800, …, 3939）；B20 排序规则（相同 Rating→chart_id ASC） |
| application | `QueryB20`：Mock repos → 20 条 / 不足 20 条 / 0 条 / append 排除 / append 包含；`QueryDifficultyRanking`：全局排序 / 个人 LEFT JOIN / 未游玩显示 / 空谱面目录 |
| adapter | Migration 005 应用 / 回滚 / SHA-256 验证；`SqliteSongRepository` CRUD；`HttpRenderer` 成功 / 超时 / 4xx / 5xx |
| failure | Renderer 不可用时降级为文本；Song 缺失时显示 song_id；空 B20 返回结构化错误 |

### 4b-2（HTTP + pytest）

- `curl -X POST http://127.0.0.1:3000/render/b20 -H 'Content-Type: application/json' -d @fixture.json` → PNG bytes
- 无效 payload → 4xx
- 并发渲染 ≤ pool 上限 → 超限排队
- 浏览器断开 → 自动重建（仅一次）

### 4b-3（pytest + FakeRenderer）

- `/pjsk b20` → 文本 / 图片回复（取决于 renderer mock）
- `/pjsk ma31` → 个人排行文本
- `/pjsk append on|off|status` → 状态变更 + 确认回复
- 无效缩写 → 格式错误提示
- 未注册用户 → 提示"暂无成绩数据"

---

## 9. 部署与回滚策略

### 部署 checklist

- [ ] Migration 005 在预检阶段验证（SHA-256 校验）
- [ ] `render_service/` 独立 systemd 单元，先启动并 health check 通过
- [ ] AstrBot 插件发布后 health check 验证 `/pjsk b20` 可达
- [ ] 默认关闭 AstrBot LLM 聊天人格（图片描述、主动回复、空艾特等待）——此项是部署前配置项，不是本轮 VPS 操作

### 回滚

```text
current → 上一 release
    ↓
migration 005 保持（列不删除，仅通过 append_excluded=1 回到默认行为）
    ↓
render_service 独立回滚（无 DB 依赖）
    ↓
AstrBot 插件回滚 → 前版本 main.py
```

---

## 10. 已知风险

| 风险 | 缓解 |
|------|------|
| `player_class.py` 源码仅在 git 历史中（旧工作树无 .py） | Phase 4b 实施第一步：从旧 `a3070e7` checkout 源码，commit 到旧库后再移植 |
| 旧 `b20.js` 嵌入 `calcKn` → 迁移时需手术剥离 | JS 端改为直接读取 `entry.rating`（Python 预计算值），不引用 `calcKn` |
| CDN 曲封 URL 的 `thumbnail_{sid}` 格式——新项目 song_id 可能超过 999 | 使用不带零填充的 URL：`thumbnail_{song_id}`（不用 `:03d`） |
| 难度排行渲染 payload 可能超大（EXPERT 全曲 >100 条） | 合理分页渲染（全局封面网格模式本身适合大量铺开）；每页 limit 检测 |
| Renderer port 引入后 `PluginRuntime` 膨胀 | `PluginRuntime` 保持 dataclass 扁平结构；超过 15 字段再考虑分组 |

---

## 11. 待人工决定的事项

1. **旧 `b20.js` 迁移策略**：直接修改 JS 去掉 `calcKn`，还是完全重写 JS（只复用布局常量）？直接修改风险更低——布局参数、字体、颜色均可复用
2. **难度排行命令格式**：`/pjsk ma31` vs `/pjsk diff ma31` vs `/pjsk ranking ma31`？建议：先支持缩写形式（`ma31`/`apd32`/`exp29`），后续按用户反馈迭代
3. **`song_aliases.json` 是否需要**：新项目 OCR 歌名匹配由 `chart_data/song_aliases.json` 覆盖。B20/难度排行使用 Song 表的 `title_cn`/`title_ja` 字段，不需要 alias 搜索。结论：4b 阶段不需要 alias JSON
4. **`/pjsk bind` 删除**：仍等待单独授权；不在本轮删除
