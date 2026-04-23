# Glossary Of Terms

## Core Terms

- `authority state`: validated data that downstream stages may trust directly.
- `working state`: provisional or intermediate data that may guide review but is not canon.
- `chapter packet`: immutable runtime-ready chapter memory artifact built from validated upstream state.
- `paragraph bundle`: narrow context object derived from a chapter packet for one source block.
- `locked glossary`: canonical naming store for approved source-to-English terminology.
- `candidate registry`: provisional glossary discovery and translation store.
- `validated Chinese summary`: authoritative continuity memory.
- `derived English summary`: inspection-oriented rendering derived from validated Chinese summary plus locked glossary.
- `idiom policy`: structured record describing preferred rendering for an idiom or set phrase.
- `graph state`: promoted entity, alias, appearance, and relationship data stored in LadybugDB.
- `checkpoint`: operational state that allows a run to resume without rerunning validated earlier work.
- `validation report`: inspectable artifact that explains pass/fail results for a stage.
- `release`: a coherent set of source input plus versioned upstream artifacts used to build packets and translation outputs.
- `run`: a single execution instance within a release.

## Operational Terms

- `rebuild`: regenerate a derived artifact from unchanged authority state.
- `invalidate`: mark a derived artifact stale because one of its upstream hashes changed.
- `resume`: continue from the latest successful checkpoint for the same run or release scope.
- `repair rerun`: rerun a failed stage or chapter without discarding unrelated successful outputs.
- `chapter-safe`: filtered so it contains no future knowledge beyond the target chapter.

## Implementation Terms

- `repository`: module responsible for data access to one store or dataset.
- `service`: deterministic orchestration within one subsystem.
- `workflow`: multi-stage executable path spanning several services or stores.
- `artifact path`: stable on-disk location derived from release, run, stage, and chapter identity.
