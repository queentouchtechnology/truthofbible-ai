# Charging for AI, Translation and TTS after free usage

## Where this stands today

AI Q&A is already gate-able — `truth_of_bible/rewards/gate.py`'s `charge_ai`
decorator, applied to `api/bible.py`'s `qa`/`qa_followup`. Off by default,
currently configured via three `site_config.json` keys:

```
rewards_ai_charge_enabled: 1
rewards_ai_free_per_day:   3     # questions per day before the wallet is used
rewards_ai_cost:           1     # wallet-currency units per extra question
```

That's a server-file edit (SSH/bench access) for every change — this plan
moves all three features' settings onto a Single doctype instead (see
"Where the settings live" below), so an admin can change the free tier or
cost from the app itself, same as `TOB AI Settings`' existing
`translation_requires_approval`/`translation_feature_enabled` toggles
already work.

A member out of free questions with too little wallet balance gets a
`frappe.throw` instead of an answer; the wallet (`rewards/engine.py`'s
`wallet_spend`) is debited only after the answer actually succeeded.
`explain()` (verse explanations) stays free always — every result is cached
in `TOB Bible Explanation` and re-served from there, so there's no repeat AI
cost to recover.

**Translation** (`api/translation.py`) and **TTS** (`api/tts.py`) shipped
since then and have no charge gate at all yet — both are fully free
regardless of usage. This doc is the plan to extend the exact same
wallet-gate pattern to both, reusing `rewards/engine.py` as-is.

## Why this isn't a copy-paste of `charge_ai`

`charge_ai` charges unconditionally once a user is past their free quota,
which is correct for Q&A because every call is a fresh AI generation. Both
newer features cache their results server-side and must **never** charge a
cache hit:

- **Translation**: `_upsert_translation()` writes to `TOB Content
  Translation`, keyed by `(source_doctype, source_name, field, language)`.
  Once any one student (or an admin's bulk job) has translated a given
  field into a given language, every other student reading that same
  content calls `translate_now`/`get_translated_fields` and gets served the
  cached row — zero new AI cost. Only a genuine cache **miss** (new
  text, or a changed `source_hash`) spends an AI call.
- **TTS**: `synthesize()` already checks `TOB TTS Audio Cache` by a hash of
  `text|locale|voice|encoding` before ever calling Google. A cache hit
  returns instantly and logs `was_cache_hit=1, estimated_cost_usd=0` — real
  Google spend only happens on a miss.

So the gate has to sit **inside** each function, at the exact point a cache
miss is confirmed and a real provider call is about to happen — not as an
outer decorator around the whole endpoint like `charge_ai`. The wallet must
only ever be debited for the work that actually cost something.

## New `rewards/gate.py` functions

Add two plain functions (not decorators, for the reason above) next to
`charge_ai`, called inline at the cache-miss point in each feature:

```python
def charge_translation(user: str) -> None:
    """Call immediately before generating a translation (confirmed cache
    miss). Raises frappe.ValidationError if the user is out of free
    translations and can't afford one. Returns normally otherwise — the
    caller debits via record_translation_charge() only after the AI call
    actually succeeds, same ordering as charge_ai."""

def record_translation_charge(user: str, ref: str) -> None:
    """Debits the wallet for one translation, idempotent per ref (ref =
    the TOB Content Translation row name, so a retry never double-charges)."""

def charge_tts(user: str) -> None:
    """Same shape as charge_translation, for a confirmed TTS cache miss."""

def record_tts_charge(user: str, ref: str) -> None:
    """Debits the wallet for one TTS synth, idempotent per ref (the TOB
    TTS Audio Cache row name)."""
```

Each `charge_*` reads its own settings fresh from `TOB AI Settings` (a
Single doctype, so `frappe.get_cached_doc`/`get_single_value` — an admin
saving the settings screen takes effect on the very next request, no
worker restart, same immediacy `site_config.json` had), exempts
`Guest`/`Administrator`, and counts today's free usage from a usage-log
table (see below) rather than re-deriving it from the shared/deduplicated
content tables, which can't attribute repeat usage to the right user (see
"Why a new doctype" below).

## Where the settings live (`TOB AI Settings`, not `site_config.json`)

`TOB AI Settings` already holds exactly this kind of admin-editable global
default (`ai_enabled`, `translation_requires_approval`,
`translation_feature_enabled`, ...), already has a System Manager-only
permission row, and `translation.py` already exposes a get/set pair for
its fields to the admin panel. Add nine new fields to it, one new
"Usage Charging" section:

| Field | Type | Default | Meaning |
|---|---|---|---|
| `ai_charge_enabled` | Check | 0 | Master switch for AI Q&A charging |
| `ai_free_per_day` | Int | 3 | Free questions per day |
| `ai_cost` | Float | 1 | Wallet units per extra question |
| `translation_charge_enabled` | Check | 0 | Master switch for translation charging |
| `translation_free_per_day` | Int | 3 | Free new translations per day |
| `translation_cost` | Float | 1 | Wallet units per extra translation |
| `tts_charge_enabled` | Check | 0 | Master switch for TTS charging |
| `tts_free_per_day` | Int | 3 | Free new (cache-miss) listens per day |
| `tts_cost` | Float | 1 | Wallet units per extra listen |

Add one get/set pair to `rewards/gate.py`, mirroring
`translation.py`'s `get_translation_settings`/`set_translation_*` shape
exactly:

```python
@frappe.whitelist(methods=["GET"])
def get_charging_settings():
    require_admin()
    doc = frappe.get_single("TOB AI Settings")
    return {f: doc.get(f) for f in _CHARGING_FIELDS}

@frappe.whitelist(methods=["POST"])
def set_charging_settings(**kwargs):
    require_admin()
    doc = frappe.get_single("TOB AI Settings")
    for f in _CHARGING_FIELDS:
        if f in kwargs:
            doc.set(f, kwargs[f])
    doc.save(ignore_permissions=True)
    return {f: doc.get(f) for f in _CHARGING_FIELDS}
```

`charge_ai` also needs migrating off `frappe.get_site_config()` onto the
same doctype read, so all three features are configured the same way —
otherwise AI stays a server-file edit while translation/TTS become
app-editable, which is the inconsistency this redesign is meant to fix.

**Flutter admin UI**: one new section (or screen) under
`lib/src/users/admin/ai_settings/` — three Check + Int + Float field
groups, same shape as the existing Translation settings screen's toggles,
calling `get_charging_settings`/`set_charging_settings`. Not scoped in
detail here; flag when you want that screen built.

All three keep the same flat "N free per day, then a flat cost per call"
shape `rewards_ai_*` already used, deliberately not a per-character price —
one mental model across all three features, and it's what `ai_cost`
already trains admins to expect. TTS's real cost genuinely varies with
text length (a whole chapter vs. one verse), but the admin usage dashboard
(`get_tts_usage`) already tracks exact character counts and Google's list
price for monitoring the real bill separately; the wallet charge doesn't
need to track it penny-for-penny, just needs a free tier and a brake past
it. A per-character wallet cost is a documented future refinement, not a
blocker for v1.

## Why a new doctype (`TOB Translation Usage Log`)

`TOB Content Translation` has no per-request user field — it's a shared,
deduplicated cache, and `owner` only reflects whoever triggered the *first*
generation of that exact row, not every later re-generation (e.g. after a
source edit changes `source_hash`, a *different* student's `translate_now`
call may be the one that re-generates it — the spend is genuinely theirs,
but `.save()` doesn't update `owner`). There's no reliable way to count
"how many new translations has *this* user caused today" from that table
alone.

`TOB TTS Usage Log` already solves this correctly for TTS (`user`,
`was_cache_hit`, `character_count`, `creation`, written on every call,
hit or miss) — it's also what powers the existing `get_tts_usage` admin
billing screen. Translation has no equivalent, so admins currently have
**zero visibility** into translation AI cost — same gap this charging
work needs to close anyway.

Add `TOB Translation Usage Log`, mirroring `TOB TTS Usage Log`'s shape:

| Field | Type | Notes |
|---|---|---|
| `user` | Link (User) | Who triggered the call |
| `source_doctype` | Data | |
| `field` | Data | |
| `language` | Link (Language) | |
| `was_cache_hit` | Check | |
| `status` | Select (success / error) | |
| `error_message` | Small Text | |

Written once per `translate_now`/`translate_local_text`/`translate_field`
call (including admin-triggered ones, for complete visibility — admins are
simply exempt from the charge itself, same as `charge_ai` already exempts
`Administrator`). Free-per-day counting becomes:

```python
frappe.db.count("TOB Translation Usage Log",
    {"user": user, "was_cache_hit": 0, "creation": [">=", nowdate()]})
```

## Call-site changes

**`api/translation.py`** — `translate_now` and `translate_local_text` are
the only two student-triggered, on-demand generators (`translate_field`/
`bulk_translate` are admin-only already, gated by `require_admin()`, and
should stay uncharged — populating content isn't a student's AI spend).
In both functions, right where a cache miss is confirmed (just before
calling `_upsert_translation`):

```python
cache_miss = not already_servable and not (existing and existing.source_hash == source_hash and gated)
if cache_miss:
    gate.charge_translation(frappe.session.user)
doc = _upsert_translation(...)
if cache_miss:
    gate.record_translation_charge(frappe.session.user, doc.name)
```

Also write one `TOB Translation Usage Log` row per call (hit or miss) right
there, for the admin usage screen — same spot, regardless of whether the
charge gate is even enabled, so usage visibility doesn't depend on billing
being turned on.

**`api/tts.py`** — `synthesize()` already has a clean cache-hit early
return (line ~121) and a cache-miss path that calls
`tts_service.synthesize_speech()`. Insert the charge check right before
that call, and the debit right after it succeeds (before `record_tts_usage`
so a `frappe.throw` from the gate itself still gets logged as `status:
"error"` by the existing `record_tts_usage` call in the `except` block —
no change needed there, since `record_tts_usage` already runs on failure).
`preview_tts_voice` (admin-only, `require_admin()`) stays uncharged, same
reasoning as `translate_field`.

## Rollout order

1. Add the nine `TOB AI Settings` fields + migration; migrate `charge_ai`
   off `site_config.json` onto the doctype (behavior-preserving — same
   defaults, same semantics, just a different config source). Ships alone,
   independently testable: AI charging keeps working exactly as before.
2. `TOB Translation Usage Log` doctype + migration.
3. Wire usage logging (hit/miss, no charge yet) into `translate_now`/
   `translate_local_text` — ship this alone first and watch real volume for
   a few days before turning any charge on, same caution the original
   `rewards_ai_*` rollout used.
4. Add `charge_translation`/`record_translation_charge`/`charge_tts`/
   `record_tts_charge` to `rewards/gate.py`, plus `get_charging_settings`/
   `set_charging_settings`; wire the charge calls into both call sites,
   both still controlled by their own `*_charge_enabled` field (off).
5. Mirror `get_tts_usage` as `get_translation_usage` in
   `api/translation.py` for admin billing visibility (grouped by
   language/source_doctype/day, same shape).
6. Build the Flutter admin settings UI (the nine fields, get/set wired up).
7. Turn on `translation_charge_enabled` / `tts_charge_enabled` from that
   screen once free-tier numbers look right from step 3's real data — no
   app release or server access needed, same immediacy `site_config.json`
   had, now from the admin panel instead of SSH.

## Flutter app — no new error-handling code expected

Every AI/translation/TTS screen already catches and surfaces whatever
message the backend's `frappe.throw` sends (confirmed across
`lib/src/users/bible/ai/view/*` and their providers) — the same generic
path that already shows the AI Q&A "You've used today's free questions…"
message today. `charge_translation`/`charge_tts` raising
`frappe.ValidationError` with a clear message needs no new client code,
same as the original `charge_ai` rollout didn't. Worth a manual pass once
live to confirm the message reads sensibly in the Translate-button and
Premium-voice contexts specifically (wording, not plumbing).

## Showing this to users

None of the above makes charging *visible* — right now `qa`, `translate_now`,
and `synthesize` return only the answer/translation/audio, nothing about
free-tier usage or whether this call was charged. Without that, the
Flutter client has nothing to show and a charge would feel silent/sneaky
the first time a user notices their wallet moved. Add one small `usage`
block to each gated endpoint's response, only when that feature's charging
is enabled (keeps the payload unchanged — and existing client code
unaffected — while a feature's charging stays off):

```python
"usage": {
    "charged": bool,             # was this specific call paid for
    "cost": float,                # 0 if free
    "free_remaining_today": int,  # after this call
    "wallet_balance": float,      # current balance, after any debit
}
```

`rewards/gate.py`'s `charge_*` functions already compute `used`/`free`/
`paid` internally to decide whether to throw — return that instead of
`None`, and have each endpoint attach it to its response only when
`charge_enabled` for that feature.

Three places this needs to show, each already has a natural home:

- **Before the user acts** (AI chat input, Translate button, Premium voice
  toggle): a small persistent pill reading "3 free today" / "1 free left"
  / "Costs 1 pt" once free uses run out — driven by the *previous* call's
  `usage.free_remaining_today` (or a lightweight `get_charging_status`
  GET call on screen open, for the very first action in a session before
  any `usage` block has arrived yet).
- **Right after a charged call succeeds**: a toast via
  `SnackbarService.show(...)` — the exact mechanism `earn_point.dart`
  already uses for the symmetric *earning* case ("₹X added to your
  wallet"). Spend-side equivalent: `"1 point used for this question — 2
  free left tomorrow"` when `usage.charged` is true. A free call (most of
  them) shows nothing — only the moment money actually moves is worth
  interrupting the user for.
- **When blocked** (out of free uses, balance too low): already covered —
  the existing `frappe.throw` message surfaces through each screen's
  normal error handling, no new plumbing.

This needs real Flutter work (reading `usage` off each response, the
pill, wiring the snackbar) — not scoped in detail here since it depends on
whichever screen each feature's gate ends up live on first. Flag it
separately once the backend side (gate functions + `usage` block) is
built, so the UI work has real response shapes to build against instead of
a guessed one.

## Testing checklist

- [ ] AI charging behaves identically after migrating `charge_ai` from
      `site_config.json` to `TOB AI Settings` — same defaults, same
      free-tier counting, same throw message, verified before anything
      else in this plan proceeds.
- [ ] Both flags left off (default): translation and TTS behave exactly as
      today — no behavior change, confirms this ships safely dormant.
- [ ] Free-per-day limit: Nth+1 new translation/TTS call in a day throws;
      same-day cache hits never count against the limit.
- [ ] A cache hit (same text+field+language, or same text+locale+voice)
      never debits the wallet, charge gate on or off.
- [ ] Insufficient wallet balance past the free tier throws before any AI/
      Google call is made (no wasted spend on a call the user can't pay for).
- [ ] Wallet debit only happens after the generation actually succeeds; a
      provider failure never charges.
- [ ] Retrying the same failed request never double-charges (idempotent
      `ref`, same pattern as `wallet_spend`'s existing dedupe key).
- [ ] `Administrator` and content-population (bulk/admin) calls are never
      charged, only logged.
- [ ] Admin usage screens (translation's new one, TTS's existing one)
      show accurate hit/miss counts and per-user daily counts match what
      actually triggered a charge.
- [ ] `usage.free_remaining_today`/`usage.charged`/`usage.wallet_balance`
      match the actual ledger state after the call, and the block is
      absent entirely (not zeroed-out) when that feature's charging is off.
