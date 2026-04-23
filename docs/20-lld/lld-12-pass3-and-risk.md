# LLD 12: Pass 3 and Risk Handling (M9)

## Summary

Implement Pass 3 (readability polish) and a stronger paragraph risk classification system to ensure high-quality, stable translation output while minimizing regression risk in complex sections.

## Public Interfaces

Python modules:

- `translation.pass3.translate_pass3()`
- `translation.risk.classify_paragraph_risk()`
- `translation.validators.validate_pass3_integrity()`

Artifacts:

- pass3 polished output
- risk classification report

## Data Flow

1. After Pass 2 completes and is validated, classify the paragraph risk.
2. Risk factors: idiom density, title density, lore exposition, pronoun ambiguity, XHTML fragility.
3. If risk is "HIGH", skip Pass 3 and use Pass 2 output as final.
4. If risk is "LOW/MEDIUM", run Pass 3 to improve readability without changing facts or terms.
5. Validate Pass 3 output against Pass 2 to ensure no "meaning drift" or terminology corruption.
6. Commit the final polished output.

## Risk Score Formula

The risk score is a weighted sum of per-factor indicators, clamped to [0.0, 1.0]:

```
risk = min(1.0,
    idiom_density_score * 0.20
  + title_density_score * 0.15
  + relationship_reveal_score * 0.20
  + pronoun_ambiguity_score * 0.20
  + xhtml_fragility_score * 0.15
  + entity_density_score * 0.10
)
```

Where each sub-score is in [0.0, 1.0]:

- **idiom_density_score** = `min(1.0, idiom_count / 3.0)` — 3+ idioms in a paragraph is max risk.
- **title_density_score** = `min(1.0, title_count / 3.0)` — 3+ titles/honorifics is max risk.
- **relationship_reveal_score** = `1.0` if any masked-identity or reveal-gated relationship is present, else `0.0`.
- **pronoun_ambiguity_score** = `min(1.0, ambiguous_pronoun_count / 2.0)` — 2+ ambiguous pronouns is max risk.
- **xhtml_fragility_score** = `min(1.0, placeholder_count / 5.0)` — 5+ placeholders is max risk.
- **entity_density_score** = `min(1.0, distinct_entity_count / 4.0)` — 4+ distinct entities is max risk.

Classification thresholds (configurable via `translation.risk_threshold_high`):

- `risk >= 0.7` → HIGH (skip Pass 3)
- `0.3 <= risk < 0.7` → MEDIUM (run Pass 3 with standard constraints)
- `risk < 0.3` → LOW (run Pass 3)

All sub-score values are persisted in the risk classification report for auditability.

## Validation Ownership

- Pass 3 MUST preserve all named entities from Pass 2
- Pass 3 MUST NOT alter event order or add new facts
- integrity validator compares Pass 2 and Pass 3 block by block

## Resume And Rerun

- if Pass 3 fails, the system fallbacks to the validated Pass 2 output
- risk classification is persisted to allow auditing of skip decisions

## Tests

- Pass 3 readability improvement happy path
- high-risk paragraph skip behavior
- integrity validation failure (reversion to Pass 2)
- terminology preservation check in Pass 3
- risk score produces deterministic output for identical inputs
- risk score at exactly 0.7 triggers HIGH classification
- each sub-score saturates at its cap (e.g., 3 idioms = 1.0)
- risk classification report includes all sub-score values
