# LLD 18c: Pass 2 Translation Quality Guardrails

## Summary
Implement structural and prompt-level guardrails in Pass 2 (Fidelity Pass) to prevent the Analyst model from performing unnecessary stylistic rewrites that degrade the quality of the specialized Translator's (Pass 1) output.

## Problem Statement
The Pass 2 Analyst (e.g., Qwen) currently has too much freedom to edit the English draft. While it is effective at finding factual errors, it often replaces Pass 1's sophisticated prose with flatter, generic wording, even when the fidelity was already correct.

## Technical Design

### 1. Persona and "Minimal Edit" Mandate
The Analyst persona in `translate_pass2.txt` will be restricted from "Editor" to "Fidelity Auditor".
- **Instruction:** "You are a translation auditor. Your sole objective is to ensure the English Draft is factually faithful to the Source. You are NOT an editor. Do not change the prose, flow, or vocabulary of the Draft unless it is required to fix a fidelity error (omission, mistranslation, or terminology violation)."
- **Prompt version:** Bumped from `1.0` to `2.0`.

### 2. "Critique-then-Correct" Workflow
The output format will be moved to a structured JSON response to force the model to justify every change it makes. This discourages "just because" edits.

**New Schema:**
```json
{
  "fidelity_errors_found": true,
  "analysis": "Briefly state if the draft is missing facts or using wrong terms.",
  "corrected_text": "The full text with MINIMAL corrections. Must be identical to the original draft if fidelity_errors_found is false."
}
```

### 3. Verification Logic
The `translation.pass2.translate_pass2` function will:
1. Parse the JSON response from the LLM.
2. Perform a "Stability Check": If `fidelity_errors_found` is `false`, return the original Pass 1 draft, ignoring any accidental edits in `corrected_text`.
3. If `fidelity_errors_found` is `true` and `corrected_text` is non-empty, return `corrected_text`.
4. If `fidelity_errors_found` is `true` but `corrected_text` is missing or empty, fall back to the original Pass 1 draft.
5. If JSON parsing fails entirely, log a warning and fall back to the original Pass 1 draft.

### 4. Pipeline Impact
`translate_pass2` return type remains `str`. The `translation/pipeline.py` caller does not need modification unless additional error handling or logging around pass2 failures is desired.

## Data Flow
1. `translate_chapter_pass2` calls `translate_pass2` with Pass 1 draft.
2. Analyst LLM receives source, draft, and context.
3. Analyst performs a fidelity comparison.
4. Analyst returns JSON with `fidelity_errors_found` and `analysis`.
5. Code validates the decision:
   - If `errors_found=false` -> return original draft.
   - If `errors_found=true` and `corrected_text` non-empty -> return `corrected_text`.
   - If `errors_found=true` and `corrected_text` empty -> return original draft (fallback).
   - If JSON parse fails -> return original draft (fallback).
6. Result is saved to `pass2.json` and checkpoints.

## Edge Cases

| Scenario | Behavior |
|----------|----------|
| JSON parse failure | Log warning, return original `draft_text` |
| `fidelity_errors_found: true`, empty `corrected_text` | Return original `draft_text` |
| `fidelity_errors_found: false`, `corrected_text` differs from draft | Ignore `corrected_text`, return original `draft_text` |
| `fidelity_errors_found: true`, valid `corrected_text` | Return `corrected_text` |

## Out of Scope
- Automatic BLEU/ROUGE comparison (handled implicitly by "Stability Check").
- Multi-model voting for Pass 2.
- Changes to Pass 1 or Pass 3 logic.
