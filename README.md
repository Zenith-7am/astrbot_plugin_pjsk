# astrbot_plugin_pjsk

PJSK（Project SEKAI / 世界计划）成绩截图 OCR 识别插件。上传成绩截图，多视觉模型并发识别，自动入库并追踪个人最佳。

**状态：Alpha（内测）**——核心链路可用，功能在持续完善。

## 功能

- 📸 **截图 OCR 识别**——上传 PJSK 结算截图，自动识别曲目、难度、判定
- 🤖 **多视觉模型竞速**——Gemini / 智谱 GLM-4V / StepFun 三引擎并发，取共识结果
- 🔢 **候选确认**——多模型分歧时向你列出候选，回复数字即可确认
- 📊 **个人最佳追踪**——每张谱面保留最高分，自动更新
- 🏷️ **游戏 ID 绑定**——`/pjsk bind <游戏ID>` 绑定你的 PJSK 账号
- 💬 **群聊支持**——@Bot + 图片触发识别，15 秒窗口内支持先发图后 @Bot

## 安装

### 从 AstrBot 插件市场安装（推荐）

AstrBot WebUI → 插件管理 → 搜索 `astrbot_plugin_pjsk` → 安装

### 从 GitHub 安装

```bash
cd AstrBot/data/plugins
git clone https://github.com/Zenith-7am/astrbot_plugin_pjsk.git
```

AstrBot 会在加载插件时自动安装依赖（`aiosqlite`、`httpx`）。

### 更新

插件市场安装的版本可从 WebUI 一键更新。GitHub 手动安装的版本：

```bash
cd AstrBot/data/plugins/astrbot_plugin_pjsk
git pull
```

> ⚠️ 数据库存储在 `data/plugin_data/astrbot_plugin_pjsk/pjsk.db`，更新或重装插件**不会**丢失数据。

## 配置

在 AstrBot WebUI → 插件管理 → astrbot_plugin_pjsk → 配置：

| 配置项 | 说明 | 默认值 |
|--------|------|--------|
| `gemini_api_key` | Google Gemini API Key | （空=禁用） |
| `zhipu_api_key` | 智谱 GLM-4V API Key | （空=禁用） |
| `stepfun_api_key` | StepFun API Key | （空=禁用） |
| `gemini_model` | Gemini 模型名 | `2.5-flash` |
| `zhipu_model` | 智谱模型名 | `glm-4.6v-flash`（免费） |
| `stepfun_model` | StepFun 模型名 | `step-1v-32k` |
| `ocr_timeout_seconds` | 单引擎超时（秒） | `15` |
| `ocr_concurrency` | 每引擎最大并发 | `3` |
| `image_window_seconds` | 群聊图片等待窗口（秒） | `15` |
| `candidate_ttl_seconds` | 候选确认超时（秒） | `300` |
| `user_cooldown_seconds` | 用户识别冷却（秒） | `5` |

**至少配置一个 API Key 插件才能工作。** 推荐同时启用 2–3 个引擎以获得最佳准确率。

### 获取 API Key

- **Gemini**：[Google AI Studio](https://aistudio.google.com/) → Get API Key → 免费额度
- **智谱**：[智谱开放平台](https://open.bigmodel.cn/) → API Keys → 新用户有赠送
- **StepFun**：[StepFun 平台](https://platform.stepfun.com/) → API Keys

## 命令

| 命令 | 说明 |
|------|------|
| `/pjsk bind <游戏ID>` | 绑定 PJSK 游戏 ID（6–16 位数字） |
| `/pjsk help` | 查看可用命令 |

后续版本会增加 `/pjsk b20`、`/pjsk rank`、`/pjsk my` 等查询命令。

## 使用方式

### 私聊

直接发送 PJSK 结算截图。一次一张。

### 群聊

群聊中需要 **@Bot + 图片** 才会触发识别（保护免费 API 额度）：

- **同一条消息 @Bot + 发图** → 立即识别
- **先发图，15 秒内 @Bot** → 识别
- **先 @Bot，15 秒内发图** → 识别
- **@Bot 说"你好"之类** → 不放 OCR 窗口，正常聊天

### 候选确认

当多个模型识别结果不一致时，Bot 会列出候选项：

```
识别结果存在分歧，请选择：

1. Tell Your World / MASTER 26
2. テルユアワールド / MASTER 26
3. Tell Your World / EXPERT 22

请在 5 分钟内回复 1、2 或 3。
候选编号：3b7f
```

直接回复数字即可确认。5 分钟内有效。

## 首次启动

插件首次加载时会自动：
1. 创建数据库并执行 schema 迁移
2. 导入 1,533 条民间精确定数
3. 输出启动日志（不含 API Key）

```text
[PJSK] v0.1.0-alpha.1 starting  schema_version=5  chart_data=2026-07-12  charts=1533
[PJSK] engines: gemini-2.5-flash, zhipu-glm-4.6v-flash
```

## 平台支持

| 平台 | 状态 |
|------|------|
| OneBot / NapCat | ✅ 可用 |
| QQ 官方 Bot | 🚧 审核中，暂不可用 |

## 隐私

- 成绩截图仅用于 OCR 识别，不存储原始图片
- API 调用仅将图片发送给你配置的视觉模型厂商
- 数据库只保存判定数据（Perfect/Great/Good/Bad/Miss）、曲目 ID、达成率、Rating
- 不在日志中记录 QQ 号、游戏 ID、OCR 原文

## License

MIT
