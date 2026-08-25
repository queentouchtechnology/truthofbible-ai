# Truth Of Bible — AI Backend

Independent multilingual Bible intelligence AI backend for
`learn.truthofbible.org`. **Not a QTT SaaS product** — this app has zero
dependency on `qtt_platform`. Real Bible verse text and cross-references
already exist on-device in the `truthofbible-app` Flutter client (offline
SQLite Bible modules); this app never stores or serves scripture text
itself — only AI-generated content (explanations, Q&A, quiz questions)
keyed to a plain reference string the client already resolves locally.

## Architecture

- **`truth_of_bible/ai/core/`** — the AI gateway (routing, retry,
  fallback). Ported from `qtt_platform.ai.core` (read directly, not
  guessed) — same proven design, zero import coupling. `AiGateway.generate()`
  has no knowledge of tenants, credits, or what a "quiz" is.
- **`truth_of_bible/ai/providers/`** — `mock`, `deepseek`, `openai`
  (OpenAI-compatible chat completions). `openrouter`/`gemini`/`anthropic`
  follow the identical `OpenAiCompatibleProvider` pattern and can be added
  the same way once actually needed.
- **`truth_of_bible/ai/service.py`** — the one function every API endpoint
  calls: builds the gateway, generates, logs usage. No credit reservation
  (this site has no billing system) — pure observability via
  `TOB AI Usage Log`.
- **Language** — extends Frappe's own core `Language` doctype (via
  `fixtures/custom_field.json`: `native_name`, `direction`, `script`,
  `is_default`) rather than a parallel doctype. `based_on` (already on
  core `Language`) is reused as the fallback-language link.
- **`truth_of_bible/api/`** — `ai.py` (generic dispatcher), `bible.py`
  (verse/chapter explanation with caching, conversational Q&A),
  `topics.py` (curated topic search), `lms_ai.py` (multilingual quiz
  generation, creates real `LMS Question`/`LMS Quiz` docs).

## Setup

1. Configure at least one `TOB AI Provider` (System Manager, Desk UI) —
   `provider_key` must match a registered provider class (`mock`,
   `deepseek`, `openai`), `enabled` checked, real `api_key`.
2. Configure a `TOB AI Model` per task you'll use — `provider` (link),
   real `model_id` (e.g. `deepseek-chat`), `default_for_task` (e.g.
   `verse_explanation`, `bible_qa`, `quiz_generation`).
3. Default prompts for those three tasks are seeded automatically on
   install/migrate (`install.py::seed_default_prompts`) — edit them via
   `TOB AI Prompt` in the Desk once real content review has happened.
4. Populate `native_name`/`direction`/`script`/`is_default` on the
   `Language` rows you care about (at minimum en/ta/hi/ar/he, per this
   product's own multilingual testing requirement).

## Deployment

Git-first, same discipline as every other backend app in this stack —
**never edit or create files directly on the server.**

```bash
# on the server, inside the frappe container
bench get-app https://github.com/queentouchtechnology/truthofbible-ai
bench --site learn.truthofbible.org install-app truth_of_bible
bench --site learn.truthofbible.org migrate
```

To deploy a later change: edit locally → commit → push → on the server,
`cd apps/truth_of_bible && git pull` → `bench migrate` if a doctype
changed.

## Known Phase 1 scope limits (deliberate, not oversights)

- `lms_ai.generate_quiz` only creates `Choices`-type questions. Native
  LMS `Open Ended` support in `qmp_lms_bridge` depends on a
  `sample_answer` Custom Field *that app's own fixture* adds to
  `LMS Question` — that field does not exist on `learn.truthofbible.org`
  (`qmp_lms_bridge` isn't installed there), so relying on it here would
  silently write to a field that doesn't exist. Add it behind this app's
  own fixture if/when Open Ended support is actually needed.
- No Bible verse/cross-reference database — deliberate, see the
  architecture note above.
- `openrouter`/`gemini`/`anthropic` provider classes aren't wired into
  `ai/bootstrap.py` yet — trivial to add (same pattern as `deepseek.py`)
  once there's a real account to configure.
