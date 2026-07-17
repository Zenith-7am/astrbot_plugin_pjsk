# Command Trigger Redesign — 私聊静默直达 / 群聊 .emu 统一入口

> **Status:** Design approved. Implementation plan: TBD.

## Goal

简化用户交互：私聊零门槛（发图即识别，命令无需前缀），群聊统一
`.emu` 入口（发图后 30s 内 `.emu` 认领，命令全走前缀）。

## Scope

- 私聊 OCR 改为只返图片、不返文字
- 新增 B20 / 难度排行快捷命令（私聊无前缀，群聊 `.emu` 前缀）
- 群聊支持「先发图，再 `.emu`」独立触发
- 候选确认不变（纯数字 1-9，公私聊均无前缀）
- 旧 `/emu register` 私聊保留

## Non-Goals

- 不改变 OCR 引擎逻辑
- 不改变 候选确认、register 的业务逻辑
- 不改变渲染服务
- 不引入持久化（PendingImageStore 进程内，重启丢失可接受）

---

## 1. 私聊触发规则

| 输入 | 行为 |
|------|------|
| 图片（任意） | 自动 OCR → 只返渲染图 |
| `b20` / `查b20` | 返回 B20 渲染图 |
| `我的maXX` | 返回个人难度排行渲染图（XX=官方等级，如 `ma31`） |
| `难度排行maXX` | 返回全局难度排行渲染图 |
| `/emu register` | 注册（保留旧命令兼容） |
| `/emu help` | 帮助信息 |
| 纯数字 `1`-`9` | 候选确认 |

## 2. 群聊触发规则

| 输入 | 行为 |
|------|------|
| 图片 | **不立即识别**，存入 PendingImageStore，key=(group_id, qq) |
| `.emu`（无参数） | 查找 key=(group_id, qq) 最新图：≤30s → OCR 返图；超时 → "未找到30秒内的截图" |
| `.emu b20` | B20 渲染图 |
| `.emu 我的maXX` | 个人难度排行渲染图 |
| `.emu 难度排行maXX` | 全局难度排行渲染图 |
| `.emu register` | 注册 |
| `.emu help` | 帮助 |
| `。emu ...` | 同 `.emu`（中文句号 `。` 也认） |
| 纯数字 `1`-`9` | 候选确认 |

---

## 3. PendingImageStore

进程内字典，**不持久化**。

```
key: (group_id: str, qq: str)
value: {image_bytes: bytes, timestamp: float, hashed_reply: str | None}

TTL: 30 秒（按 timestamp 判定，下次查或 gc 时淘汰）。
覆盖策略: 同一 key 的新图覆盖旧图。
```

- 每群每用户只存最新一张
- 私有方法，`image_handler` 写、`command_handler` 读

## 4. CommandParser

统一命令解析，公私聊复用：

```
输入文本 → 输出 Command enum:
  B20
  MY_DIFFICULTY(level)      # "我的ma31" → level=31
  GLOBAL_DIFFICULTY(level)  # "难度排行ma31" → level=31
  REGISTER
  HELP
  OCR_TRIGGER               # 群聊 .emu 无参数 → OCR 最新图
```

解析规则：
- `b20` / `查b20` → `B20`
- `我的ma(\d+)` → `MY_DIFFICULTY(level)`
- `难度排行ma(\d+)` → `GLOBAL_DIFFICULTY(level)`
- `/emu register` / `.emu register` → `REGISTER`
- `/emu help` / `.emu help` → `HELP`
- `.emu` / `。emu`（无参数）→ `OCR_TRIGGER`（仅群聊有效）

## 5. 文件变更清单

| 文件 | 变更 |
|------|------|
| `gateway/matchers/image_handler.py` | 群聊不立即 OCR，改为存图；私聊只返图不返文字 |
| `gateway/matchers/command_handler.py` | 重写：群聊 `.emu` 前缀 + 私聊无前缀；集成 PendingImageStore 查图 |
| `gateway/matchers/commands.py` | 扩展 Command enum，新增解析函数 |
| `gateway/matchers/pending_image_store.py` | **新文件**: PendingImageStore |
| `tests/gateway/` | 新增测试 |

## 6. 不变项

- `candidate_handler.py` — 零改动
- OCR 编排 / 共识 / 候选生产逻辑
- 渲染服务
- 数据库
- `/health` endpoint
