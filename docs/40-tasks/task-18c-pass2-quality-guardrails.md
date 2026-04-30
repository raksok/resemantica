# Task 18c: Pass 2 Translation Quality Guardrails

## Goal
Implement a "Minimal Edit" guardrail in Pass 2 to prevent the Analyst model from degrading the prose quality of the Pass 1 draft.

## Scope
In:
- Update `translate_pass2.txt` prompt to use JSON schema and "Fidelity Auditor" persona (bump version `1.0` → `2.0`).
- Update `src/resemantica/translation/pass2.py` to parse JSON and implement the "Stability Check" (returning the original draft if no errors are flagged).
- Update `src/resemantica/translation/pipeline.py` if needed to handle the updated `translate_pass2` interface.

Out:
- Modifying Pass 1 or Pass 3 logic.

## Owned Files Or Modules
- `src/resemantica/llm/prompts/translate_pass2.txt`
- `src/resemantica/translation/pass2.py`
- `src/resemantica/translation/pipeline.py`

## Interfaces To Satisfy
- Pass 2 JSON schema:

```json
{
  "fidelity_errors_found": true,
  "analysis": "Brief explanation of errors found, or 'No fidelity errors detected.'",
  "corrected_text": "Full corrected text. Must be identical to draft if fidelity_errors_found is false."
}
```

- `translate_pass2` return signature remains `str` (derived from JSON logic internally).

## Edge Cases
- **JSON parse failure:** Log warning, fall back to original `draft_text`.
- **`fidelity_errors_found: true` but `corrected_text` missing or empty:** Fall back to original `draft_text`.
- **`fidelity_errors_found: false` with non-identical `corrected_text`:** Ignore `corrected_text`, return original `draft_text` (stability check).

## Prompt Version
The prompt file header changes from `# version: 1.0` to `# version: 2.0`. This causes stale-check invalidation for any existing pass2 checkpoints that used version 1.0.

## Pipeline Impact
`translation/pipeline.py` calls `translate_pass2()` which still returns `str`. If the return contract is unchanged, no pipeline modifications are needed. Only update pipeline code if error handling or logging around pass2 needs to change.

## Tests Or Smoke Checks
- **Unit Test:** Provide a perfect Pass 1 draft and source to `translate_pass2`. Mock LLM returns `{"fidelity_errors_found": false, "analysis": "No errors.", "corrected_text": "<original draft>"}`. Verify `translate_pass2` returns the original draft exactly.
- **Unit Test:** Provide a Pass 1 draft with a missing sentence. Mock LLM returns `{"fidelity_errors_found": true, "analysis": "Missing sentence.", "corrected_text": "<fixed text>"}`. Verify it returns the corrected text.
- **Unit Test:** Mock LLM returns malformed JSON. Verify `translate_pass2` falls back to the original draft.
- **Unit Test:** Mock LLM returns `{"fidelity_errors_found": true, "corrected_text": ""}`. Verify fallback to original draft.

## Done Criteria
- Pass 2 Analyst uses the "Fidelity Auditor" persona.
- Pass 2 prompt version is `2.0`.
- Pass 2 does not change the draft when no fidelity errors are detected.
- The system gracefully handles JSON parsing errors from the analyst by falling back to the Pass 1 draft.
- The system handles empty/missing `corrected_text` when `fidelity_errors_found` is true by falling back to the Pass 1 draft.
- Unit tests verify "No change", "Required correction", "JSON parse failure", and "Empty corrected_text" scenarios.
