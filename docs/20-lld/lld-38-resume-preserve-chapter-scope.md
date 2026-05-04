# LLD 38: Resume Preserves Chapter Scope

## Summary

Three surgical changes to preserve the chapter range from a failed production run through the resume workflow, and to give the resume command the same rich progress bar as the production command.

## Data Flow

```
run_production(chapter_start=1, chapter_end=20)
  │
  └─▶ run_stage("packets-build", chapter_start=1, chapter_end=20)
        │
        ├─▶ _execute_stage(...)  →  build_packets(chapter_start=1, chapter_end=20)
        │
        └─▶ _update_run_state("packets-build", "failed",
        │       checkpoint={"chapter_start": 1, "chapter_end": 20})    ← NEW
        │
        ▼
     tracking.db  ──  run_state.checkpoint_json = '{"chapter_start":1,"chapter_end":20}'
                              ▲
resume_run()                  │
  │                           │
  ├─▶ load_run_state()  ──────┘
  │     reads checkpoint
  │
  └─▶ run_stage("packets-build",
        chapter_start=1, chapter_end=20,     ← NEW: extracted from checkpoint
        stop_token=...,                       ← NEW: forwarded from caller
      )
```

## Change 1: `runner.py` — Save chapter range in checkpoint

**Location:** `OrchestrationRunner.run_stage()` at the status-persistence point (~line 226).

Replace a bare `result.checkpoint or {}` with a dict that also carries the chapter range when present:

```python
# Before:
self._update_run_state(stage_name, status, result.checkpoint or {})

# After:
saved_checkpoint = dict(result.checkpoint or {})
if chapter_start is not None:
    saved_checkpoint["chapter_start"] = chapter_start
if chapter_end is not None:
    saved_checkpoint["chapter_end"] = chapter_end
self._update_run_state(stage_name, status, saved_checkpoint)
```

**Why this location:** `run_stage()` is the single persistence point for all stage state. By overlaying `chapter_start`/`chapter_end` here, every stage (preprocess-*, packets-build, translate-range) naturally records its scope. No call-site changes needed.

## Change 2: `resume.py` — Forward chapter range and stop_token

**Location:** `resume_run()` function.

Two additions to the signature and the `run_stage()` call:

```python
def resume_run(
    release_id: str,
    run_id: str,
    *,
    from_stage: Optional[str] = None,
    stop_token: StopToken | None = None,            # NEW
) -> StageResult:
```

Inside the resume loop, extract the chapter range from the loaded checkpoint and forward both it and the stop token:

```python
chapter_start = state.checkpoint.get("chapter_start")
chapter_end = state.checkpoint.get("chapter_end")

result = run_stage(
    release_id, run_id, current,
    checkpoint=state.checkpoint if current == start_stage else None,
    chapter_start=chapter_start,    # NEW
    chapter_end=chapter_end,        # NEW
    stop_token=stop_token,          # NEW
)
```

**Why:** `load_run_state()` returns the checkpoint that was saved by Change 1. If the checkpoint has no chapter range (e.g. legacy failed runs), `get()` returns `None` and the stage defaults to all chapters — safe degradation.

## Change 3: `cli.py` — Rich progress bar for resume

**Location:** `if args.run_command == "resume":` handler (~line 952).

Wrap the `resume_run()` call in `_with_cli_progress()` identical to the production handler:

```python
if args.run_command == "resume":
    stop_token = StopToken()
    resume_result = _with_cli_progress(
        lambda: resume_run(
            args.release, args.run,
            from_stage=args.from_stage,
            stop_token=stop_token,
        ),
        stop_token=stop_token,
        verbosity=int(getattr(args, "verbose", 0) or 0),
    )
    if resume_result is _INTERRUPTED_STOP:
        return 130
    if not resume_result.success:
        print(f"Resume failed: {resume_result.message}")
        return 1
    print("Resume completed successfully")
    return 0
```

**Why:** The production handler already uses this pattern for signal handling (`_install_interrupt_handlers` + `StopToken`), rich logging (`CliProgressSubscriber`), and clean exit codes. Resume should behave identically.

## Degradation

If a checkpoint has no `chapter_start`/`chapter_end` (e.g., from a run before this fix was deployed), `resume_run()` will pass `None` for both. The stage runners (`build_packets`, `_translate_range`, etc.) default to all chapters when the range is unspecified — same behavior as today. No crash, just a wider scope than intended. Users are expected to clean (`rsem run cleanup-apply --scope run`) and re-run with the correct flags.
