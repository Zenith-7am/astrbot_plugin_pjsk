> **Status: Approved** (core layer — still valid under Phase 5 standalone direction).
> The domain, application, ports, and adapter designs in this document remain authoritative for `pjsk_core` and `adapters/`.
> Current governance: `CLAUDE.md`. Phase-5 gateway design: `docs/superpowers/specs/2026-07-16-phase-5-standalone-onebot-gateway-design.md`.

# Phase 2: Chart Data and Persistence Layer Design

日期：2026-07-12

## 目标

建立新项目的 Git 版本化定数数据、SQLite schema、版本化迁移系统和三个 Repository adapter 的 SQLite 实现。Phase 2 结束后，插件可以真正读写数据库，为 Phase 3 视觉识别 → 入库链路做好准备。

## 范围

### 做

1. `chart_data/` — MASTER/APPEND/EXPERT 定数 JSON + manifest
2. `tools/import_chart_data.py` — JSON 校验 + 事务性导入
3. `adapters/database/schema.py` — SQL DDL
4. `adapters/database/migrations/` — 版本化迁移脚本
5. `adapters/database/migrator.py` — 按版本顺序执行迁移
6. `adapters/database/connection.py` — SQLite 连接工厂
7. `adapters/database/repository.py` — UserRepository + ChartRepository + ScoreRepository 的 SQLite 实现
8. 测试：schema 测试、迁移测试、Repository contract 测试

### 不做

- 旧数据迁移（Phase 4）
- OCR 表 (`ocr_runs`, `ocr_observations` — Phase 3)
- Redis adapter（Phase 3）
- Cache adapter（Phase 3）

## 定数数据格式

一个难度一个 JSON 文件，Git 版本化。

### 文件结构

```
chart_data/
  manifest.json               # 版本号 + 文件列表 + SHA-256
  pentatonic_master.json      # MASTER 定数
  pentatonic_append.json      # APPEND 定数
  pentatonic_expert.json      # EXPERT 定数
```

### JSON 格式

```json
{
  "version": "2026-07-12",
  "source": "PENTATONIC",
  "charts": [
    {
      "song_id": 1,
      "title_ja": "Tell Your World",
      "title_cn": "告诉你的世界",
      "difficulty": "master",
      "official_level": 30,
      "community_constant": "30.5",
      "note_count": 1200
    }
  ]
}
```

### manifest.json

```json
{
  "version": "2026-07-12",
  "files": {
    "pentatonic_master.json": "sha256:abc123",
    "pentatonic_append.json": "sha256:def456",
    "pentatonic_expert.json": "sha256:ghi789"
  }
}
```

### 导入校验规则

| 校验项 | 失败处理 |
|--------|---------|
| JSON schema 完整性 | 拒绝导入 |
| `community_constant` 格式 (`\d+\.\d[+-]?`) | 拒绝该条 |
| `official_level` 在合理范围 (1-40) | 警告，仍导入 |
| `difficulty` 是 6 个合法值之一 | 拒绝该条 |
| `note_count > 0` | 拒绝该条 |
| `song_id` 去重 | 拒绝重复 |
| SHA-256 与 manifest 一致 | 拒绝导入 |
| 定数变更 > 0.5（相比上一版） | 告警一次，仍导入 |

通过后事务性写入 `songs` + `charts` 表，记录 `chart_data_version`。

## SQLite Schema

对齐 CLAUDE.md §6-7。Phase 2 建 6 张表，OCR 相关留给 Phase 3。

### users

```sql
CREATE TABLE users (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    qq_number  TEXT NOT NULL UNIQUE,
    game_id    TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
```

### external_identities

```sql
CREATE TABLE external_identities (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id     INTEGER NOT NULL REFERENCES users(id),
    platform    TEXT NOT NULL,
    external_id TEXT NOT NULL,
    created_at  TEXT NOT NULL,
    UNIQUE(platform, external_id)
);
```

### songs

```sql
CREATE TABLE songs (
    id       INTEGER PRIMARY KEY,
    title_ja TEXT NOT NULL,
    title_cn TEXT NOT NULL DEFAULT '',
    title_en TEXT NOT NULL DEFAULT ''
);
```

### charts

```sql
CREATE TABLE charts (
    id                 INTEGER PRIMARY KEY AUTOINCREMENT,
    song_id            INTEGER NOT NULL REFERENCES songs(id),
    difficulty         TEXT NOT NULL,
    official_level     INTEGER NOT NULL,
    community_constant TEXT NOT NULL,
    note_count         INTEGER NOT NULL,
    chart_data_version TEXT NOT NULL,
    UNIQUE(song_id, difficulty)
);
```

### score_attempts

```sql
CREATE TABLE score_attempts (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id        INTEGER NOT NULL REFERENCES users(id),
    chart_id       INTEGER NOT NULL REFERENCES charts(id),
    perfect        INTEGER NOT NULL,
    great          INTEGER NOT NULL,
    good           INTEGER NOT NULL,
    bad            INTEGER NOT NULL,
    miss           INTEGER NOT NULL,
    accuracy       REAL NOT NULL,
    rating         REAL NOT NULL,
    status         TEXT NOT NULL,
    image_sha256   TEXT NOT NULL,
    source_gateway TEXT NOT NULL,
    ocr_run_id     INTEGER,
    created_at     TEXT NOT NULL
);
```

### personal_bests

```sql
CREATE TABLE personal_bests (
    user_id         INTEGER NOT NULL REFERENCES users(id),
    chart_id        INTEGER NOT NULL REFERENCES charts(id),
    best_attempt_id INTEGER NOT NULL REFERENCES score_attempts(id),
    accuracy        REAL NOT NULL,
    rating          REAL NOT NULL,
    status          TEXT NOT NULL,
    updated_at      TEXT NOT NULL,
    PRIMARY KEY(user_id, chart_id)
);
```

### 设计决策

- 时间戳用 ISO 8601 字符串 — SQLite 可读可排序，domain 层用 `datetime`，Repository 负责转换
- `status` 存 `'ap'/'fc'/'clear'` — 与 `ScoreStatus` enum value 一致
- `personal_bests` 复合主键 `(user_id, chart_id)` — 每用户每谱面一条最佳
- 不设 CASCADE — 保留全部历史数据

## 版本化迁移系统

```python
# migrator.py
def run_migrations(db_path: str, target_version: int | None = None) -> int:
    """Execute migrations in version order. Creates schema_version table.
    Returns the new version number.
    """
```

- 迁移脚本：`adapters/database/migrations/NNN_description.sql`
- `schema_version` 表记录当前版本号和最后迁移时间
- 启动时自动检测并执行缺失的迁移
- **不**在插件启动时隐式大规模改表 — 只执行显式迁移脚本

## Repository Adapter

实现 Phase 1 定义的三个 Protocol：

### UserRepository

- `get_by_id(user_id: UserId) -> User | None`
- `get_by_qq(qq: QqNumber) -> User | None`
- `create(qq, game_id) -> User`

### ChartRepository

- `get_by_id(chart_id: int) -> Chart | None`
- `find_by_song_and_difficulty(title, difficulty) -> Chart | None`
- `list_by_difficulty_level(difficulty, level) -> list[Chart]`

### ScoreRepository

- `record_attempt(attempt: ScoreAttempt) -> ScoreAttempt` — 插入 attempt + 同事务更新 personal_best
- `get_personal_best(user_id, chart_id) -> ScoreAttempt | None`
- `list_personal_bests(user_id, status_filter) -> list[ScoreAttempt]`

Repository 只依赖 `sqlite3`（标准库）和 domain 类型。所有 SQL 在 Repository 内部，不泄露到 application 层。

## 测试

- **Schema 测试** — 在临时 SQLite 上跑 migration 脚本，验证表结构
- **Migration 测试** — 验证版本递增、幂等性、缺失迁移检测
- **Repository 测试** — 复用 Phase 1 contract tests，用真实 SQLite 替换 fake
- **Import 测试** — 合成 JSON 数据 + 校验规则验证

## 执行顺序

1. chart_data 数据文件 + manifest
2. 迁移系统骨架（schema_version 表 + migrator）
3. 迁移 001：建表
4. Repository 实现（逐 port 实现，每完成一个跑 contract 测试）
5. 导入工具 + 校验
6. 全量测试 + 提交
