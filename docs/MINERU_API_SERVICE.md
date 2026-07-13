# Shared MinerU API Service

Last reviewed: 2026-07-13 Asia/Shanghai by Codex.

## Contract

MinerU uses one operator-managed FastAPI process. The ebook pipeline never lets the `mineru` client start its temporary `LocalAPIServer`, because that path creates `mineru-api-client-*` directories that can become inaccessible across Windows sandbox and child-process security contexts.

The single configuration source is `config/mineru-api.env`:

- bind host: `127.0.0.1` only;
- configured port: `8000`;
- command: `mineru-api`, resolved to the installed `tools/mineru-venv` entry when absent from `PATH`;
- state root: `D:\used-by-codex\.local\mineru-api`;
- fixed subdirectories: `data`, `temp`, `client-temp`, `logs`, and `run`.

On Windows, a configured `mineru-api.exe` console entry point is normalized to
the same virtual environment's `python.exe -m mineru.cli.fast_api`. This keeps
the recorded PID attached to a persistent venv Python process-tree root instead
of a short-lived console-script launcher. The listening Python child remains in
that tree, so `status` and `stop /T` stay reliable across agents.

Port `8000` passed the shared port record, live listener, Windows excluded-range, and real `127.0.0.1` bind checks on 2026-07-13. Future port changes must edit this config first and repeat all checks.

## Stable Commands

```powershell
.\mineru_api.cmd init
.\mineru_api.cmd status
.\mineru_api.cmd start
.\mineru_api.cmd health
.\mineru_api.cmd stop
```

`start` writes logs and a PID record below the state root. `stop` refuses to terminate a PID unless its command line is verified as MinerU API. No scheduled task or always-on service is installed.

## Conversion Behavior

The batch CLI exposes `--mineru-api-url`; its default comes from `EBOOK_CONVERTER_MINERU_API_URL` or `config/mineru-api.env`. Every MinerU command includes the upstream `--api-url` argument.

When `/health` is unavailable:

1. the pipeline raises `MinerUAPIUnavailableError` before launching `mineru`;
2. normal jobs use the existing local PyMuPDF4LLM/PyMuPDF fallback when enabled;
3. `--no-pdf-auto-fallback` produces a failed conversion report;
4. no temporary MinerU API is started and no success is fabricated.

## Windows Permissions

The state root is under the existing `D:\used-by-codex\.local` boundary, which already grants the current user and `CodexSandboxUsers` Modify access. This implementation does not change system TEMP, grant `Everyone`, or require an elevated Agent.

If permissions are rebuilt later, scope changes to the MinerU state root and grant Modify only to the current user and `CodexSandboxUsers`; retain normal Administrator/SYSTEM semantics.

## Cross-Agent Discovery

Agents must read `config/mineru-api.env` or call `.\mineru_api.cmd status`; they must not guess a port or invoke bare `mineru` without `--api-url`. The shared registry change remains proposal-only in `docs/MINERU_API_TOOL_REGISTRY_PROPOSAL.json` until the Local Tools owner applies it.

## Acceptance Evidence

Local acceptance on 2026-07-13 used the original 18-page failure PDF:

- fixed API command contained `--api-url http://127.0.0.1:8000`;
- MinerU 3.1.15 completed in 95.922 seconds and wrote 25,401 bytes of Markdown;
- API counters ended at one completed task and zero failed tasks;
- the stopped-API run reported `MinerUAPIUnavailableError`, then produced a
  25,321-byte local fallback result;
- the pre-existing inaccessible `mineru-api-client-*` count remained 12 before
  and after both runs, proving this path created no new temporary API directory;
- final `status` was `stopped`, with no listener left on port 8000.

Regression evidence: `check_project_readiness.py` passed 42/42,
`test_batch_control_flow.py` passed, `test_service_readiness.py` passed, and
the targeted pytest compatibility check passed.
