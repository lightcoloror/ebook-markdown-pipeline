# 外部代码审查处置矩阵（2026-08-02）

<!-- Documentation update: 2026-08-02 09:37:26 | Codex (GPT-5) | Reviewed and remediated findings against baseline b79f8fb. -->

本文记录针对 commit `b79f8fb` 外部审查中 R1-R14 的复核、修复和保留决策。它不替代安全测试；可执行证据仍以仓库测试和 completion audit 为准。

## 结论

| 项 | 复核结论 | 处置 |
|---|---|---|
| R1 | 成立，阻断发布 | 已删除 Docker 默认 token；非本地绑定拒绝空、短或占位 token。 |
| R2 | 成立 | 已增加无 token、错误 Bearer、错误 X-Api-Token、占位 token 和正确 token 测试。 |
| R3 | 成立 | 共享 VKP catalog、health、execution 返回前执行递归凭据字段扫描并 fail-closed。 |
| R4 | 成立 | 已覆盖 access_token、client_secret、x-api-key、bearer、private_key、credentials 和后缀变体。 |
| R5 | 风险描述部分成立，建议方案不采用 | ebook 将整次费用上限分配到 source/stage；VKP consent/trusted connector 是唯一实际调用与费用强制点。本仓不复制一套无法核对供应商账单的 spend ledger。未来可消费 VKP 提供的可信实际费用证据。 |
| R6 | 误判 | `local_review_subdir` 以 workspace root 为基准；五个固定 commit 工作树存在且干净。manifest 和 audit 已显式记录路径基准。 |
| R7 | 边界混淆 | `online_only + vkp_shared` 只用 VKP 单一凭据源；`online_providers.py` 是独立、显式、非默认的二次增强接口。两者不能混称为同一路径。 |
| R8 | 误判 | `process_material` 返回前统一调用 `normalize_agent_next_actions`；完整 Agent contract 测试验证四个必需字段。 |
| R9 | 接受的残余风险 | ebook 在同一宿主进程加载 VKP 协调模块，但供应商 secret 仍由 VKP DPAPI/gateway 管理。多租户或不可信插件环境应把 gateway 部署为独立受限进程。 |
| R10 | 非发布阻断 | candidate、diagnostic、registry 是不同 artifact family；保留各自 schema version，后续可增加统一 envelope，而不是强行共用一个 schema。 |
| R11 | 技术债 | 在线管道复用大转换模块是 tool-first 粘合层取舍；后续只在依赖影响测试证明收益时拆轻量 adapter。 |
| R12 | 成立 | TOOL_CONTRACT 的 HTTP entrypoints 示例已加入 `start_online_conversion`。 |
| R13 | 部分成立 | 已使用恒定时间比较、非 root 容器和 dockerignore。health 只返回环境变量名而非值，当前保留用于诊断。 |
| R14 | 不采用 | `HttpConfig` 是可公开的 host/port 事实源；API token 是独立 secret 输入，不应写入同一个非敏感配置对象或文件。 |

## 安全边界

- HTTP loopback 可无 token 供本机按需调试；任何非本地绑定必须使用至少 24 字符的唯一随机 token。
- Docker/Compose 不提供默认 token，缺失 token 时 fail-closed；镜像以非 root 用户运行。
- `.dockerignore` 排除 `.env`、本地 smoke、缓存、模型目录和 benchmark 运行产物。
- shared VKP 结构化返回在交给调用方或写入 artifact 前扫描凭据字段；命中时中止，不记录字段值。
- `online_only` 真实执行仍要求 `execute=true`、`confirm_data_export=true` 和正数整次费用上限。

## 验证证据

- `python -B scripts/test_http_api.py`
- `python -B scripts/test_shared_vkp_gateway.py`
- `python -B scripts/test_docs_contract.py`
- `python -B scripts/test_agent_contract.py`
- `python -B scripts/test_online_only_agent_contract.py`
- `python -B scripts/test_mcp_stdio.py`
- `python -B scripts/check_public_release.py`
- `python -B scripts/run_quality_gate.py --profile minimal --sample-timeout 60 --no-update-latest`
- `python -B scripts/audit_online_mode_completion.py --json --supplier-smoke-report <local-report> --require-live-supplier-smoke`

最后一条审计只读取本地脱敏 smoke 证据，不重新调用供应商。真实 smoke 的本地路径、用户材料、API key 和模型缓存均不进入公开仓库。
