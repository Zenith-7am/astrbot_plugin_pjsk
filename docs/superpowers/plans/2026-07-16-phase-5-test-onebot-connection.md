# Phase 5 — Test OneBot Connection Plan

> 目标：验证 NapCat → NoneBot Gateway → `/emu status` → QQ 收到回复。
> 不接 OCR、不写数据库、不切换生产。执行前需用户批准。

## 1. 连接拓扑

```
NapCat (国内 VPS)
    │
    ├── ws_reverse[0] → AstrBot aiocqhttp (现有，不变)
    │
    └── ws_reverse[1] → 新 Gateway (香港 VPS :8080，新增)
                             │
                             └── 只响应 TEST_QQ 的 /emu 命令
```

## 2. 双回复防护

- 旧 `pjsk-emu-bot.service`：已断开 NapCat（WebSocket closed Jul 14），无风险。
- AstrBot：仍在接收消息，但**新 Gateway 不抢 AstrBot 的聊天流量**——只有 `@filter.event_message_type(ALL)` 装饰的 `on_message` 才处理通用消息。新 Gateway 只注册了 `on_command("emu")`，普通文本不匹配。
- 额外保险：Gateway 启动时检查 `TEST_QQ_ALLOWLIST` 环境变量。如果设置了该变量，**只有来自该 QQ 号的 `/emu` 命令才会回复**。生产环境不设此变量（正常服务所有用户），测试期间必须设置。

## 3. 执行步骤

### Step 1: 在 Gateway 加入测试白名单（本地 commit）

在 `gateway/commands.py` 增加：

```python
import os

def _qq_allowed(external_user_id: str) -> bool:
    allowed = os.environ.get("TEST_QQ_ALLOWLIST", "")
    if not allowed:
        return True  # no allowlist → serve everyone
    return external_user_id in allowed.split(",")
```

在 `gateway/matchers/command_handler.py` 的 `_emu()` 开头增加检查：

```python
if not _qq_allowed(msg.external_user_id):
    return
```

### Step 2: 部署到香港 VPS

```bash
# 只读检查当前状态
ssh root@154.37.219.8 "systemctl is-active astrbot pjsk-emu-bot pjsk-renderer"

# 将代码推到 VPS（git pull on codex/foundation-scaffold）
# 不安装 systemd unit，直接用 nohup 启动一次性测试进程
```

### Step 3: 启动测试 Gateway

```bash
ssh root@154.37.219.8 "
  export ONEBOT_ACCESS_TOKEN=<from-shared-bot-env>
  export TEST_QQ_ALLOWLIST=<用户指定的测试 QQ 号>
  cd /root/data/plugins/astrbot_plugin_pjsk
  nohup /root/.local/share/uv/tools/astrbot/bin/python gateway/bot.py > /tmp/pjsk-gateway-test.log 2>&1 &
  echo PID=\$!
"
```

**端口**：NoneBot 默认监听 `127.0.0.1:8080`。通过 `.env` 或环境变量 `HOST=127.0.0.1 PORT=8080` 设置。

### Step 4: 配置 NapCat 反向 WebSocket（国内 VPS）

在 NapCat 的 `ws_reverse` 配置中**新增**一条：

```json
{
  "ws_reverse": [
    {"url": "ws://<existing-astrbot-tunnel>:<port>/onebot/v11/ws", "access_token": "..."},
    {"url": "ws://<tunnel-to-gateway>:8080/onebot/v11/ws/", "access_token": "..."}
  ]
}
```

NapCat 会同时向两个地址推送事件。

### Step 5: 从测试 QQ 发送验证消息

```text
/emu help
/emu status
/emu b20          ← 预期: "未知命令，请使用 /emu help"
你好              ← 预期: 无回复
```

验证：
- `/emu help` → QQ 收到帮助文本
- `/emu status` → QQ 收到 "OneBot: connected"
- `/emu b20` → QQ 收到未知命令提示
- 普通文本 → 无回复

### Step 6: 检查日志

```bash
ssh root@154.37.219.8 "cat /tmp/pjsk-gateway-test.log"
```

确认：
- `[PJSK] gateway starting — access_token=<present>`
- `emu command=help conversation_type=private`
- `emu command=status conversation_type=private`
- `emu command=unknown conversation_type=private`
- 无异常、无崩溃
- 无 QQ 号、无消息正文泄露

### Step 7: 停止测试 Gateway

```bash
ssh root@154.37.219.8 "kill <PID>"
```

移除 NapCat 配置中的第二条 `ws_reverse`（恢复原状）。

## 4. 不做的

- 不安装 systemd unit
- 不修改 AstrBot 服务
- 不修改旧 bot
- 不写入数据库
- 不触发 OCR
- 不让非测试 QQ 收到回复
- 不长期运行

## 5. 验收

- [ ] `/emu help` → QQ 收到回复
- [ ] `/emu status` → QQ 收到 "OneBot: connected"
- [ ] 普通文字 → 无回复
- [ ] 日志无用户标识泄露
- [ ] 测试后恢复原状（NapCat 配置还原，进程已终止）

## 6. 授权门

**本计划中的所有 VPS 操作均需用户批准后执行。** 包括：
- 代码推送
- 启动测试进程
- 修改 NapCat 配置
- kill 测试进程

当前状态：**等待批准。**
