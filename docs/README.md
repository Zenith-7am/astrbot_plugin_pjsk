# PJSK Emu Bot — 文档索引

## 当前必读

| 文档 | 用途 |
|------|------|
| [`CLAUDE.md`](../CLAUDE.md) | 项目执行宪章 — 架构、红线、当前阶段、开发流程 |
| [`production/PRODUCTION-OPERATIONS.md`](production/PRODUCTION-OPERATIONS.md) | 生产必读 — 拓扑、服务、部署、回滚、事故记录 |
| [`superpowers/specs/2026-07-16-phase-5-standalone-onebot-gateway-design.md`](superpowers/specs/2026-07-16-phase-5-standalone-onebot-gateway-design.md) | Phase 5 standalone OneBot gateway 设计规格 |
| Phase 5 实施计划 | 尚未创建 — 待设计规格批准后编写 |

## 当前阶段

**Phase 5 — Governance and Production Baseline**

- 方向：NoneBot 2 + OneBot v11 standalone gateway
- AstrBot 已退出生产路径，代码保留但不继续投入
- 业务核心（`pjsk_core` / `adapters` / `render_service`）保持不变

### Phase 5 实施计划

| 文档 | 状态 |
|------|------|
| `superpowers/plans/2026-07-16-phase-5-task-3a-legacy-production-baseline.md` | Task 3A — 旧生产冻结与功能基线 |

### Legacy Audit (Phase 5 Task 3A)

| 文档 | 用途 |
|------|------|
| [`production/LEGACY-PRODUCTION-BASELINE.md`](production/LEGACY-PRODUCTION-BASELINE.md) | Old bot frozen baseline — files, drift, rollback eligibility |
| [`production/LEGACY-FEATURE-MATRIX.md`](production/LEGACY-FEATURE-MATRIX.md) | Old bot command and trigger inventory |

## 历史资料

以下文档为 AstrBot 时期的设计与计划，**已废止**。保留作为历史参考，不作为当前实施依据。

### AstrBot 设计规格（Superseded）

| 文档 | 状态 |
|------|------|
| `superpowers/specs/2026-07-12-pjsk-astrbot-rebuild-design.md` | Superseded by Phase 5 |
| `superpowers/specs/2026-07-13-phase-4a-astrbot-first-vertical-design.md` | Superseded by Phase 5 |
| `superpowers/specs/2026-07-14-phase-4b-query-render-design.md` | Superseded by Phase 5 |

### AstrBot 实施计划（Superseded）

| 文档 | 状态 |
|------|------|
| `superpowers/plans/2026-07-12-foundation-and-legacy-audit.md` | Superseded by Phase 5 |
| `superpowers/plans/2026-07-13-phase-4a-astrbot-first-vertical.md` | Superseded by Phase 5 |
| `superpowers/plans/2026-07-14-phase-4b-query-render.md` | Superseded by Phase 5 |

### 迁移资料

数据库审计和迁移文档将在未来 Phase 中创建。

## 文档状态标记

所有规格和计划使用以下状态标记：

- `Status: Draft | Under Review | Approved | Superseded | Archived`
- `Supersedes: <旧文档路径>`
- `Implementation allowed: Yes | No`
