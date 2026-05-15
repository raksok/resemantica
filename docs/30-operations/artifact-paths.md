# Artifact Paths

## Path Root

All generated artifacts should live under a single repo-local root:

```text
artifacts/
```

## Release-Scoped Paths

```text
artifacts/releases/{release_id}/
  resemantica.db
  graph.ladybug
  tracking.db
  cleanup_plan.json
  extracted/
    chapters/chapter-{chapter_number}.json
    reports/xhtml-validation.json
    placeholders/chapter-{chapter_number}.json
  glossary/
    candidates.json
    conflicts.json
  summaries/
    chapter-{chapter_number}-zh.json
    chapter-{chapter_number}-en.json
  graph/
    snapshot-{snapshot_id}.json
  packets/
    chapter-{chapter_number}-{packet_id}.json
    chapter-{chapter_number}-{packet_id}-bundles.json
```

## Run-Scoped Paths

```text
artifacts/releases/{release_id}/runs/{run_id}/
  translation/
    chapter-{chapter_number}/
      pass1.json
      pass2.json
      pass3.json
  validation/
    chapter-{chapter_number}/
      structure.json
      fidelity.json
      chapter.json
  reconstruction/
    translated.epub
    report.json
```

## Rules

- chapter-specific artifacts include `chapter_number` in the path
- authority stores are release-scoped; new runs do not read legacy `artifacts/resemantica.db` or `artifacts/graph.ladybug`
- immutable artifacts get a new file or versioned parent path instead of in-place edits where reproducibility matters
- SQLite stores metadata and indexes for these artifacts, but the artifact payload lives on disk
- if a path rule changes, update this file and the relevant LLD in the same change
