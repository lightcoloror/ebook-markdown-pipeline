# 耐久目标 07 - CP1 Health CLI 证据

日期：2026-07-10
项目：`D:\used-by-codex\ebook_markdown_pipeline`
Checkpoint：CP1 - health CLI 修复

## 结论

CP1 已完成。`--health-check` 不再要求 `input/output`，默认返回 `health-check-v2` JSON。核心能力和可选能力已分层；当前机器缺少若干可选后端时返回 `degraded_optional`，但 `minimal_ok=true` 且进程 exit 0。

## 基线证据

修复前：

```powershell
python batch_convert_books.py --health-check
```

结果：exit 1；argparse 报 `the following arguments are required: input, output`。

## 实施内容

- positional `input/output` 仅在普通转换模式下必填。
- 新增 `--health-check-format {json,text}`，默认 `json`。
- 新增 `build_health_status()`，稳定输出 `core_ok / degraded_optional / core_missing`。
- `optional_missing_is_ok=true`；仅缺失最小核心能力时 health 返回非零。
- Pandoc 可用但 Calibre 缺失时，`structured_ebooks` 为 degraded，不冒充完整覆盖，也不阻断 Pandoc 支持格式。
- 修正 batch health 中 dots.mocr 的上游路径为 `dots_mocr/parser.py`。

## 验证证据

```powershell
python -B scripts\test_health_cli.py
```

结果：`Health CLI contract test passed.`，覆盖 `core_ok`、`degraded_optional`、`core_missing`。

```powershell
python batch_convert_books.py --health-check
```

关键结果：

```json
{"exit_code":0,"schema_version":"health-check-v2","status":"degraded_optional","minimal_ok":true,"optional_missing_is_ok":true,"missing_minimal_capabilities":[],"ready_count":13,"degraded_count":4,"missing_count":10}
```

```powershell
python -B batch_convert_books.py
```

结果：普通模式仍拒绝缺少 positional，报 `input and output are required unless --health-check is used`。

```powershell
python -B scripts\test_external_wrapper_plans.py
```

结果：`External wrapper plan contract test passed.`

```powershell
python -m pytest -q -p no:cacheprovider -k health_cli
```

结果：`1 passed, 75 deselected in 0.45s`。

```powershell
python -B scripts\check_project_readiness.py
```

结果：`42 passed / 0 failed`。

```powershell
git diff --check
```

结果：通过，无 whitespace error。

## 边界记录

- 未安装或升级任何后端、模型或系统依赖。
- 未下载模型，未调用外部 OCR/VLM API。
- 未处理用户私有书籍。
- 未启动持久 HTTP/UI，未修改端口。
- 缺失与 planned-only 后端保持原状态。
