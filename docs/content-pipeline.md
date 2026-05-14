# Content pipeline — architecture

> How AP lesson content gets created, stored, and surfaced to Aria.
> Last updated: 2026-05-14.

## TL;DR

For each of the ~25 empty AP topics: pull the matching **OpenStax** chapter (CC BY 4.0), chunk it equation-aware, embed each chunk into `lesson_embeddings`, then have **Gemini Pro** emit an 8-step `[{tts, html, dur}]` lesson in Aria's voice via **structured output**, validated against required terms + equations + length, and written to `topics.content` with a provenance JSON.

The same chunk index powers **runtime RAG** — when a student asks Aria a question, we retrieve the chunks she just delivered and ground her Socratic nudge in that exact material instead of generic LLM knowledge.

One CLI drives both bulk and per-topic runs. Estimated total cost for a full bulk ingest: **under $3** of Gemini API spend. Effort: **~13 engineer-days**.

## Why this approach

- **OpenStax** is the only K-12-aligned source that's both (a) reviewed by domain experts and (b) CC BY 4.0 (commercial-use-OK with attribution).
- **AP course names + unit lists** are factual scaffolding (not copyrightable per *Feist v. Rural*), so our DB can mirror the College Board CED structure. **CED prose is © College Board** — never reproduce it in lessons.
- **Gemini Pro** (not Flash-Lite) handles generation because we need reasoning + voice fidelity; Flash-Lite handles embeddings. Cost difference is negligible at 25 topics.
- **Structured output** (response_schema) makes the output shape mechanically verifiable instead of relying on prompt-following.

## Sources

| AP Course | Primary source | License | URL |
|---|---|---|---|
| AP Physics 1 | OpenStax **College Physics 2e** | CC BY 4.0 | https://openstax.org/details/books/college-physics-2e |
| AP Calc BC | OpenStax **Calculus Vol 1–3** | CC BY 4.0 | https://openstax.org/details/books/calculus-volume-1 |
| AP Biology | OpenStax **Biology 2e** | CC BY 4.0 | https://openstax.org/details/books/biology-2e |
| Simulations | **PhET** | CC BY 4.0 | https://phet.colorado.edu/en/simulations/browse |
| Bio/medical visuals | NIH / NLM / Genome.gov | Public domain | https://www.genome.gov/genetics-glossary |
| Earth/space context | NASA / NOAA | Public domain | https://images.nasa.gov |

A YAML mapping table (`apps/api/app/content/mapping.yaml`) keys each AP CED topic to a list of OpenStax section IDs. Data, not code — curriculum updates don't require redeploys.

Representative mapping rows:

- `ap-physics-1.unit-7.oscillations-amplitude-period-frequency` → `cp2e/ch-16/16-1, 16-2, 16-3`
- `ap-calc-bc.unit-1.limits-continuity` → `calc-vol-1/ch-2`
- `ap-biology.unit-5.heredity` → `bio-2e/ch-12, ch-13, ch-14`

## Data flow

```
                    one-off / per-topic (offline)
 ┌──────────────────┐  HTML   ┌─────────────┐ chunks ┌─────────────┐
 │ OpenStax archive ├────────▶│ extractor   ├───────▶│ chunker     │
 │ (CNX api)        │         │ (HTML→AST,  │        │ (200–400 tok│
 └──────────────────┘         │ MathML→TeX) │        │ eqn-aware)  │
                              └─────────────┘        └──────┬──────┘
                                                            │
                                                            ▼
                                                     ┌─────────────┐
                                                     │ embedder    │
                                                     │ (gemini-    │
                                                     │ embedding-2)│
                                                     └──────┬──────┘
                                                            │ vec(768)
                                                            ▼
                                ┌────────────────────────────────────┐
                                │ Supabase lesson_embeddings         │
                                │ (chunk_id PK, topic_id, ordinal,   │
                                │  text, source_url, embedding)      │
                                └──────┬─────────────────────────────┘
                                       │ top-k retrieval
                                       ▼
        ┌─────────────┐  response_schema  ┌─────────────────┐
        │ generator   │◀─gemini-pro-latest┤ retrieve top-8  │
        │ (8-step,    │  Pydantic schema  │ chunks per topic│
        │ Aria voice) │                   └─────────────────┘
        └──────┬──────┘
               │ candidate steps
               ▼
        ┌─────────────┐
        │ validator   │── fail → retry w/ stricter prompt (≤3×)
        │ (terms,     │── pass ↓
        │ equations,  │
        │ TTS length, │
        │ HTML lint)  │
        └──────┬──────┘
               ▼
        ┌─────────────┐
        │ persister   │── upsert topics.content + content_provenance
        │             │── archive prior content to content_history
        └─────────────┘

                ─── runtime (during a lesson) ───
 student Q → TutorAgent → embed Q → cosine-search lesson_embeddings
  WHERE topic_id=? ORDER BY embedding<=>q LIMIT 3
 → inject chunks into RAG_QUESTION_PROMPT → SocraticAgent.stream_text
```

## Package layout

```
apps/api/app/content/
  __init__.py
  mapping.yaml             # AP CED → OpenStax section map (data)
  sources.py               # URL templates + license metadata
  extractors.py            # OpenStax HTML → typed Section
  chunker.py               # 200–400 tok, equation/term aware
  embedder.py              # gemini-embedding-2 batch wrapper
  generator.py             # structured-output prompt + Pydantic schema
  validator.py             # CER + term coverage + TTS length + HTML allow-list
  persister.py             # idempotent upsert + content_history
  retriever.py             # runtime RAG (called by TutorAgent)
  prompts.py               # GENERATE_LESSON_PROMPT, RAG_QUESTION_PROMPT
  cli.py                   # python -m app.content.cli ingest|generate|verify
  fixtures/                # cached OpenStax HTML for offline tests
```

## Stage detail

### Extract (`extractors.py`)
OpenStax exposes per-section HTML via the CNX archive (`https://openstax.org/api/v0/contents/<book-uuid>:<section-uuid>.html`). The extractor strips chrome, normalises **MathML → LaTeX + Unicode**, and emits `Section{slug, title, paragraphs[], equations[], named_terms[], source_url}`. Equations and bolded named terms are surfaced separately because the validator treats them as **required tokens**.

### Chunk (`chunker.py`)
Split at heading + paragraph boundaries, pack to 200–400 tokens (cl100k-style estimate). Refuse to split inside a `<math>` block or between a defined term and its definition sentence — chunks must remain self-contained because the RAG retriever returns them verbatim.

### Embed (`embedder.py`)
`gemini-embedding-2` returns 768-d vectors (matches `vector(768)`). Batch 96 chunks per API call. **Schema change needed** (see Risks §1): `lesson_embeddings` becomes per-chunk, not per-topic.

### Generate (`generator.py`)
Calls `gemini-pro-latest` with Pydantic `response_schema`:

```python
class LessonStep(BaseModel):
    tts: str  # ≤120 chars
    html: str  # allow-listed tags only
    dur: str  # mm:ss

class LessonContent(BaseModel):
    items: list[LessonStep]  # length == 8
```

Prompt skeleton (system + user):

> **System:** ARIA_BASE_PERSONA (verbatim from `apps/api/app/agents/prompts.py`) + "You are writing 8-step lesson content for the in-app teleprompter, NOT a chat reply."
>
> **User:** Topic = "Oscillations: Amplitude, Period & Frequency". AP CED LO = 7.A.1. Required terms (must all appear): [amplitude, period, frequency, equilibrium, restoring force]. Required equations (must all appear literally): [T = 1/f, T = 2π√(m/k), x(t) = A cos(ωt)]. Source chunks: [top-8 retrieved chunks, full text]. 8-step rubric: step 0 = "Preparing your lesson"; steps 1–2 ground the everyday phenomenon; 3–5 name the concept and unfold the equation; 6–7 state the rule and the "why". Each step must include exactly one `<span class="hl-y|hl-b|hl-p|hl-g">` highlight; `tts` ≤120 chars; the canonical equation literally in the highlight in the last step.

### Validate (`validator.py`)
Three gates — all must pass before persist:

1. **Required-terms coverage** — every term/equation extracted in §Extract appears (case-insensitive, equation-normalised) somewhere across the 8 steps. ≥90% coverage required.
2. **CER triad** — at least one step states the **concept**, one the **equation**, one the **rule/consequence**. Per-topic regex pack generated from `mapping.yaml`.
3. **Schema sanity** — `tts ≤ 120 chars`, `dur` is mm:ss and monotonically increases, `html` parses and only uses allow-listed tags/classes (`<span class="hl-*">`, `<em>`, `<strong>`, `<code>`).

A failed gate triggers up to **3 retries** with a stricter prompt that injects the failure list (e.g. "you dropped `T = 2π√(m/k)` — include it literally in step 6 or 7"). After 3 fails, the topic goes to `content_review` with `status='needs_human'`.

### Persist (`persister.py`)
Inside a transaction:
```sql
UPDATE topics
SET content = $1, content_provenance = $2
WHERE id = $3;
```
`content_provenance` is a new `jsonb` column:
```json
{
  "source": "openstax-college-physics-2e",
  "source_url": "https://openstax.org/books/college-physics-2e/pages/16-1-...",
  "license": "CC BY 4.0",
  "attribution": "OpenStax, College Physics 2e",
  "chunk_ids": ["…"],
  "model_generate": "gemini-pro-latest",
  "model_embed": "gemini-embedding-2",
  "generated_at": "2026-05-14T...",
  "validator_version": "1.0.0",
  "human_reviewed": false
}
```

Idempotency: hash `(source_url, model_generate, validator_version)`. If hash unchanged and `human_reviewed=true`, skip. Otherwise archive the prior `topics.content` into a `content_history` row before overwriting.

### Human review queue
New table `content_review(topic_id PK, status enum['pending','approved','edit_needed'], notes text, reviewer_id, decided_at)`. Author UI deferred — the table just unblocks a stub admin page later.

## Runtime RAG (Aria uses the content)

In `apps/api/app/agents/tutor.py`, before `SocraticAgent.respond_to_question`, call `retriever.fetch_context(topic_id, question, last_step_idx)`:

```python
embedding = await embedder.embed_query(question)
results = supabase.rpc("match_lesson_chunks", {
    "p_topic_id": topic_id,
    "p_query_embedding": embedding,
    "p_match_count": 3,
    "p_threshold": 0.6,
}).execute()
```

Plus the chunk(s) whose `ordinal == last_step_idx ± 1` (the passage Aria literally just delivered) — guarantees temporal grounding even if cosine misses.

A new prompt in `app/agents/prompts.py`:

```
SOURCE PASSAGES (these are what we just covered — anchor your reply here,
not generic physics knowledge):
[chunk 1 text]
[chunk 2 text]
[chunk 3 text]

SESSION CONTEXT: ... (existing block)
The student just asked: "..."

Respond Socratically. Reference the source passages above when forming
your hint — paraphrase, don't quote. Do not introduce concepts that
aren't in those passages. One small nudge, end with a question.
2–4 sentences.
```

If retrieval returns nothing (similarity < 0.6 for all top-k), Aria falls back to the existing `QUESTION_PROMPT` path. Graceful degradation for topics not yet ingested.

## Cost back-of-envelope

- 25 topics × 8 steps × ~500 output tokens = 100 000 output tokens
- ~5 000 input tokens per topic (chunks + persona + rubric) = 125 000 input
- gemini-pro-latest list: ~$1.25/M input, ~$5/M output
- Generation: 125k × $1.25/M + 100k × $5/M ≈ **$0.66**
- Re-embedding ~25 topics × 30 chunks × 300 tok = 225k embed tokens ≈ **<$0.05**
- With 3× retry headroom: **< $3** for the entire bulk ingest

## Run cadence

- **One-time bulk ingest**: `python -m app.content.cli ingest --course all --topic all`, run locally by the curriculum engineer. Logs to `agent_traces` with `agent='content_ingest'`.
- **Per-topic re-runs**: when a teacher flags a step or Aria's persona changes — `--topic-slug oscillations-... --force`.
- **CI smoke**: nightly GitHub Action runs `python -m app.content.cli verify --topic all` against staging Supabase to catch silent schema drift. No generation.
- **Not** a Supabase Edge Function (60s wall clock kills large topics). **Not** an in-process FastAPI route at first (long-running, blocks workers). A dedicated CLI keeps secrets local and lets us tee output to a log.

## Migrations needed

1. **Rework `lesson_embeddings`** (breaking) — from `topic_id PK` to per-chunk:
   ```sql
   chunk_id      uuid primary key
   topic_id      uuid references topics(id) on delete cascade
   ordinal       int  -- chunk position within topic
   text          text
   source_url    text
   embedding     vector(768)
   created_at    timestamptz
   -- index: USING hnsw (embedding vector_cosine_ops)
   ```
2. Add `content_provenance jsonb` to `topics`.
3. New `content_review` table.
4. New `content_history` table (archive prior `topics.content` rows).
5. RPC `match_lesson_chunks(p_topic_id, p_query_embedding, p_match_count, p_threshold)` — wraps the cosine search so the API doesn't push the embedding vector through the REST layer.

## Worked example — Unit 7 Oscillations

1. `mapping.yaml`: `ap-physics-1.unit-7.oscillations-amplitude-period-frequency → openstax/college-physics-2e/ch-16/16-1, 16-2, 16-3`.
2. Extractor pulls 3 sections → `Section` with `equations=['T=2π√(m/k)', 'f=1/T', 'x(t)=A cos(ωt)']`, `named_terms=['amplitude','period','frequency','equilibrium','restoring force']`.
3. Chunker emits ~22 chunks averaging 280 tokens.
4. Embedder writes 22 rows to the redesigned `lesson_embeddings`.
5. `retriever.fetch_for_generation(topic_id, k=8)` pulls the top-8 chunks by similarity to the topic title + summary.
6. Generator calls `gemini-pro-latest` with `response_schema=LessonContent`. Returns 8 steps. Step 0 is the boilerplate; the last step contains `<span class="hl-y">T = 1 / f</span>`.
7. Validator: terms `amplitude`, `period`, `frequency`, `equilibrium` all present ✓; equation `T = 1/f` present ✓; **`restoring force` was dropped** — retry with stricter prompt → second pass passes.
8. Persister writes content + provenance with `human_reviewed=false`.
9. The hand-authored seed lesson stays for now (compare side-by-side; curriculum engineer flips `human_reviewed=true` on whichever wins).
10. At runtime, student asks *"why does a stiffer spring oscillate faster?"* — retriever returns chunks containing the `T = 2π√(m/k)` discussion — `RAG_QUESTION_PROMPT` grounds Aria's Socratic nudge in that exact passage.

## Effort estimate

| Stage | Days |
|---|---|
| `mapping.yaml` + AP CED → source research | 1.5 |
| `extractors.py` (OpenStax HTML, MathML normalisation) | 2.0 |
| `chunker.py` + tests | 1.0 |
| `embedder.py` + migration (per-chunk + HNSW index) | 1.0 |
| `generator.py` + schema + prompt iteration | 2.0 |
| `validator.py` (terms, CER, TTS length, HTML allow-list) | 1.5 |
| `persister.py` + provenance migration + `content_review` table | 0.5 |
| `retriever.py` + wiring into `TutorAgent` + `RAG_QUESTION_PROMPT` | 1.5 |
| `cli.py` + idempotency + logging | 0.5 |
| Bulk run of 25 topics + manual spot-check + tweaks | 1.5 |
| **Total** | **~13 eng-days** |

## Failure modes

| Failure | Detection | Mitigation |
|---|---|---|
| Gemini drops an equation | `validator.required_terms` | Retry with explicit injection of the missing equation (cap 3) |
| OpenStax section too short | extractor returns <4 chunks | Pull adjacent sections per `mapping.yaml`; if still thin, escalate to a `gemini-pro-latest` planning step that synthesises across chapters with explicit citation |
| TTS step >120 chars | `validator.tts_length` | Auto-split into two sub-steps, recompute `dur` linearly, mark provenance `auto_split: true` |
| Hallucinated equation | regex finds an equation not in source `equations[]` | Hard fail, retry; if still present after retry → `content_review` |
| HTML injects disallowed tag | bleach allow-list check | Strip and retry once |
| RAG returns nothing at runtime | sim < 0.6 for all top-k | Fall back to original `QUESTION_PROMPT`; log to `agent_traces` for backlog triage |
| Re-running clobbers human edits | persister.idempotency | Refuse overwrite when `human_reviewed=true` unless `--force-human-override` |

## Risks / open questions

1. **`lesson_embeddings` schema must change.** Current PK is `topic_id` (one row per topic). RAG needs one row per chunk. Breaking migration.
2. **OpenStax MathML → readable LaTeX/Unicode** is fiddly; budget time for the normalisation layer.
3. **Attribution surface in the UI.** CC BY 4.0 requires visible attribution. Need an "About this lesson" affordance — design ticket separate from this pipeline.
4. **AP CED is © College Board.** We can reference learning objectives **by code** ("LO 7.A.1") but must NOT paste CED prose into prompts. Legal check before shipping.
5. **PhET embed URLs** drift; cache canonical sim slugs per topic in `mapping.yaml`.
6. **Voice/TTS sync.** `dur` mm:ss is currently authored; the generator estimates from `tts` length (~3.5 chars/sec). A future pass should let Gemini Live's actual TTS timing back-fill `dur`.
7. **Hallucinated cross-references.** Aria may invent "as we saw earlier" callbacks. Add a validator rule banning "earlier", "before", "we saw" in step 1.
8. **Human-in-the-loop scale.** 25 topics × 8 steps = 200 steps to spot-check. Plan ~4h of curriculum-engineer time for first pass; build a minimal review UI early.

## Primary sources

- OpenStax licensing: https://openstax.org/license · https://openstax.org/legal/terms-of-use
- OpenStax books: https://openstax.org/details/books/college-physics-2e · `.../calculus-volume-1` `.../calculus-volume-2` `.../calculus-volume-3` `.../biology-2e`
- OpenStax CNX archive: https://openstax.org/api/v0/contents/
- PhET (CC BY 4.0): https://phet.colorado.edu/en/about/licensing
- Gemini structured output: https://ai.google.dev/gemini-api/docs/structured-output
- Gemini embeddings (gemini-embedding-2 + 768-d): https://ai.google.dev/gemini-api/docs/embeddings
- pgvector cosine ops + HNSW: https://github.com/pgvector/pgvector
- AP CED (reference only — do NOT redistribute): https://apcentral.collegeboard.org/courses/ap-physics-1/course
- Prior art:
  - Khanmigo architecture overview: https://blog.khanacademy.org/khanmigo-education-ai-guide/
  - Stanford "Tutor CoPilot" paper: https://arxiv.org/abs/2410.03017
  - Anthropic "Building effective agents": https://www.anthropic.com/research/building-effective-agents
