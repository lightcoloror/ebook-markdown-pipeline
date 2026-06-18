# Release Checklist

Use this checklist before publishing a public tag or GitHub release. The project is local-first: optional heavy OCR/VLM backends may be missing and should not block a minimal release unless the release notes claim they are required.

## Required Commands

Run from the repository root:

```powershell
python scripts\run_quality_gate.py --profile release
python scripts\check_public_release.py
python scripts\show_latest_quality_gate.py
```

The release profile writes `release-summary.json/md` and updates `benchmarks/runs/latest/release-index.json/md`. If this is only an experiment, pass `--no-update-latest`.

## Public Safety Checks

- `scripts/check_public_release.py` must pass.
- No private paths, real copyrighted sample names, tokens, API keys, or model-cache files should be tracked.
- `README.md`, `docs/QUICKSTART.md`, `docs/INSTALLATION.md`, `docs/BACKENDS.md`, `docs/ARCHITECTURE.md`, `docs/REFERENCES_AND_REUSE.md`, and `THIRD_PARTY_NOTICES.md` should describe the same backend boundary.
- Optional backend failures or missing dependencies must be described as optional, not as failed installation.
- `media_helper` and `python_dependency_consistency` degraded statuses should be explained as soft risks unless release notes claim optional media/provider/model-download workflows are required.

## Quality Evidence

- Minimal benchmark should pass on generated public fixtures.
- Backend comparison should include default routing versus MarkItDown.
- OCR provider comparison should write `ocr-provider-comparison.json/md`.
- Optional backend scorecard should write `backend-scorecard.json/md`.
- Release summary should list regression tags such as `structure_regression`, `ocr_regression`, `table_regression`, or `duration_regression` when present.

## Agent Contract

- `process_material` must keep `schema_version=process-material-v2`.
- `next_actions` and `recommended_followup` must remain machine executable with `tool`, `arguments`, `safe_default`, and `destructive=false`.
- `enhance_job_artifact` should remain non-overwriting by default and should not require agents to guess Markdown output paths.
- `/health`, `/capabilities`, and `get_agent_contract` must expose backend/provider capability status.
- Remote online model calls must require explicit `allow_remote=true`.

## Release Notes

Before publishing, copy the relevant items from `CHANGELOG.md` into the GitHub release body and include:

- Minimal install command.
- Known optional backend limitations.
- Latest release quality-gate status and output path.
- Third-party/backend license reminder.
