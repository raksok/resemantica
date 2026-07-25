RSEM(1)                   Resemantica User Manual                  RSEM(1)

NAME
    rsem — local-first EPUB translation pipeline for Chinese web novels

SYNOPSIS
    uv run rsem [options] <command> [<args>...]

    uv run rsem extract   -i <epub> -r <release> [options]
    uv run rsem translate -r <release> -R <run> (-C <N> | -s <N> [-e <N>]) [options]
    uv run rsem preprocess <subcommand> -r <release> [options]
    uv run rsem packets   build -r <release> -R <run> [options]
    uv run rsem rebuild   -r <release> -R <run> [options]
    uv run rsem run       <subcommand> -r <release> -R <run> [options]
    uv run rsem tui       [options]
    uv run rsem set-chapter-flag -r <release> -C <N> (--story | --non-story) [options]

DESCRIPTION
    Resemantica is a local-first, multi-stage pipeline that converts
    Chinese web novel EPUBs into readable English EPUBs. All inference
    runs locally via llama.cpp router mode (OpenAI-compatible API).

    Pipeline stages (execution order):
    extract → preprocess → packets → translate → rebuild

    Three LLM roles are required:
    - translator  (default: HY-MT1.5-7B)  — Pass 1 translation
    - analyst     (default: Qwen3.5-9B-GLM5.1) — Pass 2/3, analysis
    - embedding   (default: BAAI/bge-m3) — fuzzy alias/epithet matching
      Auto-fetched from HuggingFace on first use. Cached at
      embedding/BAAI/bge-m3/. Do not change unless you understand
      the embedding pipeline.

    HanLP (~500MB) downloads on first glossary-discover call for
    Chinese tokenization/POS/NER. Falls back to simple segmentation
    if unavailable.

GLOBAL OPTIONS
    -c, --config PATH     Path to resemantica.toml (default: ./resemantica.toml).
    -v, --verbose         Increase verbosity (-vvv for DEBUG).
    -r, --release ID      Release identifier. Required for most commands.
    -R, --run ID          Run identifier for checkpoint scoping.
    -f, --force           Rebuild instead of resuming from checkpoints.
    -w, --allow-rewind    Allow re-running even if later stages started.
    -C, --chapter N       Single chapter (mutually exclusive with --start).
    -s, --start N         First chapter in range (inclusive).
    -e, --end N           Last chapter in range (inclusive).
    -b, --batched         Run all chapters pass1-first, then pass2/3.

COMMANDS

    extract (ext)
        Unpack and validate EPUB. -i, --input PATH required.

    translate (tra)
        Two-pass chapter translation. Requires --release, --run, chapter scope.

    preprocess (pre)
        Preprocessing sub-stages:

        glossary-discover (gls-discover)
            Discover glossary candidates. Options: --pruning-threshold,
            --eval-batch-size, --skip-llm-eval, --dedup-threshold.

        glossary-translate (gls-translate)
            Translate candidates via translator LLM.
            Resume skips existing per-model votes for the same release,
            run, and config. Re-run without --force after a local
            model-server crash to continue from missing votes. With a
            complete seed model vote set, resume avoids a full
            candidate-table scan and fetches rows later by candidate_id
            primary key.

        glossary-review (gls-review)
            Generate review.json + review.csv for human editing. See
            "HUMAN REVIEW" section.

        glossary-promote (gls-promote)
            Validate and promote to locked glossary. -F for review file.

        summaries (sum)
            Generate chapter summaries (story_so_far, chapter, arc).

        idioms
            Detect and promote idiom policies.

        idiom-review (idi-review)
            Generate idiom review files.

        idiom-promote (idi-promote)
            Validate and promote idiom policies. -F for review file.

        graph
            Build entity-relationship graph (LadybugDB).

        continuity
            Refresh graph-grounded continuity.

    packets build (pac build)
        Build immutable chapter packets with glossary, summaries, idioms,
        and graph context.

    rebuild (reb)
        Reconstruct final EPUB from translated pass artifacts.

    run
        Orchestration:

        production (prod)   Full pipeline in canonical order.
        resume              Resume from last checkpoint.
        retry-failed        Retry failed pipeline units.
        cleanup-plan (cln-plan)   Preview deletable artifacts.
        cleanup-apply (cln-apply) Execute cleanup.

    tui
        Launch Textual TUI.

    set-chapter-flag (scf)
        Override story/non-story classification.

STAGE GATES & LOCKS

    Stages execute in strict order (STAGE_ORDER from
    orchestration/models.py):

        preprocess-summaries → preprocess-glossary → preprocess-idioms →
        preprocess-graph → preprocess-continuity → packets-build →
        translate-range → epub-rebuild

    Legal transitions:
    - No prior state → any stage allowed.
    - Same stage re-run always allowed.
    - Forward move allowed; backward move DENIED unless --allow-rewind.

    Per-stage gate checks (orchestration/gates.py):

        stage                checks
        ──────────────────  ──────────────────────────────
        preprocess-summaries extracted inputs
        preprocess-glossary  extracted inputs
        preprocess-idioms    extracted + unresolved votes + summaries
        preprocess-graph     extracted + unresolved votes + summaries
        preprocess-continuity extracted + unresolved + summaries + graph
        packets-build        extracted + unresolved + summaries + graph
        translate-range      extracted + unresolved + summaries + graph
                             + packets
        epub-rebuild         extracted + unresolved + summaries + graph
                             + packets + rebuild

    Gate failures save a checkpoint, generate review artifacts, and
    return exit code 1. The --force flag bypasses checkpoint resume
    but does NOT bypass gate checks.

    Chunk-level checkpoints (chunk_checkpoints table) enable granular
    progress within stages. The last-good-chunk cleanup scope rewinds
    to the last completed chunk.

HUMAN REVIEW

    Glossary and idiom candidates can be reviewed before promotion.

    Glossary review cycle:
        glossary-discover → glossary-translate → glossary-review
        → (edit review.csv) → glossary-promote -F review.csv

    Review JSON structure:
        review_schema_version, release_id, entries[]. Each entry:
        candidate_id, source_term, category, translation,
        evidence_snippet, alternatives[], action.

    Review CSV (tab-separated):
        action | source_term | category | translation |
        candidate_id | evidence_snippet | alternatives

    Editable actions:
        keep    Include in promotion (edit translation to override).
        delete  Exclude from promotion.
        add     Insert new entry (omit candidate_id).

    Promotion applies edits via _apply_review_overrides():
    - Changed translation: updates candidate_translation_en,
      resets validation_status to pending.
    - New entries: synthetic ID gcan_review_<sha256>, marked as
      human-reviewed (translator_model_name="human").
    - Conflicts detected via validate_candidates_for_promotion()
      against locked_glossary.

    Idiom review follows the same cycle with differences:
    - Fields: source_text, meaning_zh, meaning_en, rendering.
    - Alternatives have vote_kind ("rendering" or "meaning").
    - New entries: ican_review_<sha256>.

CLEANUP PIPELINE

    Two-phase design: cleanup-plan (preview) → cleanup-apply (execute).

    Scopes:

        scope             disk deleted                          SQLite
        ────────────────  ────────────────────────────────────  ──────────────
        run               runs/{run_id}                         16 tables
        translation       runs/{run_id}/translation/            2 tables
        preprocess        extracted,summaries,glossary,         14 tables
                          idioms,graph,packets
        cache             .cache/                               none
        keep-extracted    all except extracted/                 14 tables + 2 trk
        last-good-chunk   per-chapter after last checkpoint     chapter rows +
                                                                 checkpoint rewind
        all               everything (except 5 protected)       16 tables + 2 trk
        factory           releases/*, resemantica.db,           none
                          graph.ladybug

    Five protected artifacts (all scope only):
        tracking.db, resemantica.db, graph.ladybug,
        cleanup_plan.json, cleanup_report.json.

    Plan validation checks: schema version, scope match, release/run
    IDs, root path containment, artifact containment, SQLite target
    whitelist. --force bypasses scope mismatch for non-factory.

EXIT CODES
    0     Success.
    1     Stage or command failure.
    2     Invalid arguments.
    130   Interrupted (Ctrl+C).

    On the first Ctrl+C, Resemantica stops admitting new LLM tasks,
    cancels queued tasks, drains and persists active tasks, prints the
    durable resume boundary, and exits 130. A second Ctrl+C force exits
    immediately and may leave partial artifacts.

FILES
    resemantica.toml            Main configuration (TOML).
    artifacts/releases/<id>/    Release root directory.
      work/unpacked/            Extracted EPUB contents.
      extracted/chapters/       Per-chapter JSON extraction artifacts.
      extracted/placeholders/   Placeholder maps.
      extracted/reports/        Validation reports.
      glossary/                 Candidates, conflicts, review files.
      idioms/                   Candidates, policies, conflicts, review.
      summaries/                Summary JSON artifacts.
      graph/                    Snapshots, warnings.
      packets/                  Chapter packets.
      rebuild/reconstructed.epub Final EPUB.
      graph.ladybug             LadybugDB graph database.
      resemantica.db            Main SQLite database (25 tables).
      resemantica.tracking.db   Tracking database (run_state, events).
      logs/                     Loguru JSONL log files.

EXAMPLES
    # Extract a new release
    uv run rsem extract -i novel.epub -r v1.0

    # Generate summaries (must run before glossary)
    uv run rsem preprocess summaries -r v1.0

    # Discover glossary terms
    uv run rsem preprocess glossary-discover -r v1.0

    # Translate, review, promote
    uv run rsem preprocess glossary-review -r v1.0
    # (edit artifacts/v1.0/glossary/review.csv)
    uv run rsem preprocess glossary-promote -r v1.0 -F artifacts/v1.0/glossary/review.csv

    # Translate chapters 1-10
    uv run rsem translate -r v1.0 -R run1 -s 1 -e 10

    # Full production pipeline
    uv run rsem run production -r v1.0 -R run1
    uv run rsem run production -r v1.0 -R run1 -n   # dry-run

    # Resume from checkpoint
    uv run rsem run resume -r v1.0 -R run1

    # Cleanup
    uv run rsem run cleanup-plan -r v1.0 -R run1 -S preprocess
    uv run rsem run cleanup-apply -r v1.0 -R run1 -S preprocess

    # With custom config
    uv run rsem translate -c ./my-config.toml -r v1.0 -R run1 -C 1

    # Launch TUI
    uv run rsem tui -r v1.0

SEE ALSO
    Full documentation: docs/ directory in the project root.
    Architecture:     docs/10-architecture/
    Low-level design: docs/20-lld/
    Task briefs:      docs/40-tasks/
    SPEC.md           Full product specification
    ARCHITECT.md      Engineering blueprint
    DATA_CONTRACT.md  Data contracts
    DECISIONS.md      Architecture decisions
