# What was under test, part one: vendor recipes, effective settings, and the recipe gate

[Book](../README.md) | [All tables](results.md) | [Pitfalls](pitfalls.md)

### Problem

The first comparison of the bake-off ran every model under one harness recipe (temperature 0.5, top_p 0.95, no top_k, 8,000 output tokens including thinking, no system prompt, no echo of earlier reasoning in multi-turn loops). That is a control arm. The vendors' own recipes differ in sampling, thinking tier, output budget and multi-turn handling. The comparison had already been used for decisions when it was asked whether each model was run with its own recipe. It was not. The question had been answerable at the start: each model directory carried a `generation_config.json` and the runner already had a `--sampling` option whose comment said "vendor-recommended params".

### What we built or changed

1. A recipe file per model: `recipes/<model>.json`, with `sampling` (must include `temperature` and `top_p`), `chat_kwargs` (sent as `chat_template_kwargs`), `max_tokens` (including reasoning), `system`, `preserve_reasoning`, a `limitations` list that must be present even when empty, a `sources` list (fact, source quote, kind), a `conflicts` list, and `field_sources`, a flat map from each key field to `official` or `inferred`. The shipped example is for Qwen3.8-Flash-Next and is built from the public model card; the public example is sanitized as described in [implementation notes](implementation.md).
2. A gate in the runner, before a run directory is created: no recipe file means exit, unless the run says `--recipe-arm harness-uniform --reason "<why>"`, in which case the result is labelled a control. A reason is mandatory. A recipe without `temperature` and `top_p` is refused so the harness defaults cannot leak into a vendor arm.
3. Arm names that mean something: `vendor` (every key field labelled official and the evidence verified), `vendor-informed` (at least one key field not official), `vendor-overridden` (any command-line override on a vendor arm), `harness-uniform` (control). The name is written into the result file and the report header.
4. A source gate. A label `official` counts only if `verified_by` names a verification report by path and a `sha256:` prefix of at least 12 hex characters that equals the report's actual hash; the report must live under the research directory and be named `VERIFY*.md`; it must contain a section titled with the model's name; and fields that section lists as refuted may not be labelled official. When the check fails, every key field is treated as non-official and the reason is written to the result.
5. A recipe probe run before a vendor arm: (a) the server accepts the recipe's parameters (HTTP 200 with `choices`); (b) a token-count proxy for "reasoning is echoed back into the prompt": a tool-calling history of the shape the coding loop uses, once without and once with a long marker in `reasoning_content`, passes if the prompt grows by at least 60 tokens; (c) the offline render check below.
6. An offline render check. The history is two assistant turns, each a reasoning block plus a tool call, both after the single user message. It is rendered with the model's own tokenizer and chat template through the serving layer's message normalisation, and again through the "official path" (the reasoning field handed to the template verbatim). Per assistant turn the check requires exactly one thinking block, no empty thinking block, the reasoning marker present, and the two renderings byte-identical.
7. Offline-verifiable proof of what the template reads. The researcher and the verifier read each template's source for the keys it consults.

### Procedure as actually run

Recipe research produced a recipe and evidence file per model. An independent verification pass tried to refute each field against first-hand sources (model cards, generation configs, template source). Reconciliation against the tool source overturned two verification claims, described below. Only then were vendor-arm runs allowed to claim `official`.

Where time allowed, both arms were run: the vendor arm under the recipe, the control arm labelled `harness-uniform` with a reason. The report header states that a vendor arm is a composite intervention (sampling, thinking tier, budget, echo and per-item wall-clock scale change together); there was no single-factor ablation. The per-item wall-clock limit scales with the output budget, `max(1, max_tokens / 8000)`, because the item timeouts had been set for the 8,000-token control; a 32,768-token recipe therefore multiplies each limit by 4.096.

### Results

Verification of drafted recipes, six models, 74 key fields:

| Verdict | Count |
|---|---|
| Confirmed official | 39 |
| Confirmed, but the value rests on an inference (source equivalence, neutral value not stated, etc.) | 24 |
| Refuted | 11 |
| Unverifiable | 0 |

Of the 11 refuted, six changed the actual request, five were wrong prose (a reason, a note, a misattributed example, an outdated deviation, a wrong conclusion in a research file). The six that changed requests:

| Kind | What it was |
|---|---|
| No-op key | A chat-template flag that the template reads but that does nothing behind the serving layer, because the layer strips the field the flag depends on |
| Echo shape | A "preserve reasoning" flag that, through the serving layer, produced two thinking blocks in a turn (`<think></think><think>` plus the reasoning) |
| Budget | An output budget whose stated source did not say that; the value was a quarter of the vendor's recommendation (the researcher had labelled it inferred; the label was lost when the fact was copied into the recipe) |
| Wrong scenario | A top_p taken from the agentic scenario applied to all categories (the vendor gives 0.95 for agentic use and 1.0 otherwise) |
| Key never read | A `thinking` key the template never reads; sending only it silently produced non-thinking behaviour |
| Missing field | An omitted scenario-dependent field and a 384K output cap |

Two verifier claims were overturned by reading the evaluation tool's source: the pack tool's `--timeout 360` was reported as capping a turn's output at about 14K to 29.5K tokens, but each turn is streamed and the timeout is the gap between tokens, not the turn length (and zero read timeouts appeared in six result files). A residual real risk was found instead: the outer 3,600 s wall-clock around a whole pack category did not scale with the output budget and had no handler for the timeout (fixed in code).

How `reasoning_effort` strings are interpreted differs per template (read from template source, not run by us):

| Template behaviour for an unsupported or unknown value | Effect |
|---|---|
| Accepts only three named tiers (extra-high, medium, low); a value such as `high` or `max` makes the template raise | A serving layer with an alias fallback maps it silently to the top tier; a template-faithful server errors |
| Accepts high / low / no-think; an invalid value is silently changed to no-think with an empty thinking prefill | Thinking silently off |
| Accepts named values that map to numbers (`max` is 0.99, clamped to [0, 0.99]); `xhigh`, the name the vendor documentation uses, is not a name this template knows | A name copied from the wrong vendor's documentation maps to nothing useful; check the template's own table |
| Treats low / high as named and any other value as max | The string "high" is high; omitting it is max |
| Never reads a `thinking` key | The flag is a no-op; sending it alone can switch thinking off |

The consequence in our runs: one uniform request, `reasoning_effort: "high"`, gave different effective tiers per model. On GB10 the effect was visible without any template reading: the same Qwen3.8-Flash-Next model asked for `high` through a port that forces a low tier generated a mean 398 output tokens per c4 item (median 324), against 2,708 (median 986) at the default tier, and 132 with thinking off (table in chapter 4). The result file for the low-tier run records the request as `high`.

Two-arm sample on a single GB10 node (pruned 3.0 bits-per-weight text-only EXL3 build of a 284B MoE; same private bank hash, same grader hash, same tool-eval-bench; the model has no vision, so c6 scores 0.0 in both arms). Vendor-informed arm: temperature 1.0, top_p 1.0, thinking on, `reasoning_effort` max, `max_tokens` 32,768, reasoning echo on; two separate runs of one repetition each, 2026-09-25 and 2026-09-26. Control arm: harness-uniform, `reasoning_effort` low, harness sampling (0.5 / 0.95), `max_tokens` 8,000, two repetitions, median, 2026-09-26. All six key fields of the vendor arm were non-official because no independent verification report existed for this recipe, so it ran as `vendor-informed`. Per-scenario top_p was not implemented in the harness; 1.0 applied throughout.

| Category | Vendor-informed run A | Run B | Control median (two runs) | Control runs | A minus control | B minus control |
|---|---|---|---|---|---|---|
| c1-kbqa | 83.3 | 90.0 | 81.7 | 83.3, 80.0 | +1.6 | +8.3 |
| c2-longctx | 93.3 | 93.3 | 91.7 | 96.7, 86.7 | +1.6 | +1.6 |
| c3-tool (pack) | 60.0 | 53.3 | 60.0 | 60.0, 60.0 | 0.0 | -6.7 |
| c4-code | 95.8 | 95.8 | 87.5 | 87.5, 87.5 | +8.3 | +8.3 |
| c5-extract | 85.5 | 88.1 | 90.1 | 88.8, 91.4 | -4.6 | -2.0 |
| c6-vision (text-only model) | 0.0 | 0.0 | 0.0 | 0.0, 0.0 | 0.0 | 0.0 |
| c7-zhif | 90.0 | 86.7 | 68.3 | 63.3, 73.3 | +21.7 | +18.4 |
| c7-agentic-if (pack) | 86.7 | 86.7 | 84.2 | 81.7, 86.7 | +2.5 | +2.5 |
| c8-judgment (pack) | 83.3 | 83.3 | 80.0 | 80.0, 80.0 | +3.3 | +3.3 |
| c9-long-coding | 100.0 | 100.0 | 97.8 | 98.6, 96.9 | +2.2 | +2.2 |
| c10-sre-ops | 80.0 | 80.0 | 75.0 | 76.7, 73.3 | +5.0 | +5.0 |
| Own mean as recorded (includes c6 = 0) | 78.5 | 79.2 | 74.0 | | | |
| Own mean excluding c6 (derived) | 89.7 | 90.6 | 84.6 | | | |

Reading: in both vendor-arm files the recipe moved the Chinese-instruction category by about 18 to 22 points and the code-fix category by 8.3 points; one file also moved c1-kbqa by 8.3 points and c3-tool by -6.7; every other category moved by 5 points or less. The control's own two-run spread was 10 points on c2 and on c7-zhif (flagged by the harness), so the c7-zhif gain is much larger than the control's noise and the c1 gain is not. This is a composite effect of one recipe on one pruned model, one repetition per vendor-arm file; it is not a general statement about vendor recipes and it does not say which of sampling, tier, budget or echo did the work.

### What did not work

- Using the token-count increase as proof that reasoning reached the template. A model whose serving layer inlined the echoed reasoning and let the template add an empty block grew the prompt by far more than 60 tokens and passed; the offline render showed two thinking blocks. A token count is a proxy; the property is the rendering.
- The first probe used a plain chat history. Two of the templates keep earlier reasoning only for tool-call turns that come after the last user message, so a no-tool history can never reveal the problem.
- Writing drafted recipe values into a gate without verification: the drafted values launched a vendor arm on one model, and that run had to be discarded after the render check failed.
- Writing vendor sampling into a shared engine configuration file in one batch, without a runtime check that the engine reads those fields. The batch wrote a value the verification had already refuted (a top_p for all categories), left a misleading speculative-decoding field in place, and changed a default that the control arm depended on (an omitted `top_k` would now come from the file); at the time the ledger was frozen only a backup and a README existed, and the change had not been reverted. Engines differ on whether they read the model's `generation_config.json`: on engine B the precedence was request, then per-model settings, then global settings, and the model's own file was never read, so a client that omitted `top_k` did not get the vendor's value. Check how your engine resolves defaults; we did not check how vLLM does.

### Pitfalls

| Symptom | Root cause | Fix |
|---|---|---|
| Vendor arm is better on one category only, total flat | Recipe changed several things; only budget-limited or tier-sensitive categories react | Report the arms side by side, with the header "composite intervention" |
| `official` label on a value that was inferred | Evidence label lost when copying research to the recipe | Source gate: `official` needs a hash-bound verification report that names the field |
| Same string, different tier | Templates interpret kwargs differently, a layer between client and template may rewrite or drop them | Send only keys the template source reads; render once offline and read the output |
| Multi-turn loop scores differ by engine | The loop did not echo reasoning back; the serving layer may rewrite what is echoed | Echo `reasoning_content`; verify by offline render, not by prompt tokens |
| Output looks truncated at 8,000 tokens | The harness cap, not the model | Budget = peak reasoning plus answer; record `finish_reason` |
| Verifier and researcher disagree | Either can be wrong | Reconcile against the tool's source and against result files |

### The rule

Do not call a comparison fair until each model has been run with its own recipe, each recipe field carries a first-hand source and a verification verdict, and the recipe has been rendered once and read. Until then the run is a labelled control arm.

Stub tests: a unit test that a run with no recipe and no `--reason` exits before creating a run directory; a recipe whose `verified_by` hash does not match the report is treated as informed; a rendering fixture with `<think></think><think>R</think>` fails the check while `<think>R</think>` passes.

## Public implementation boundary

The public source gate closes the historical allow-list gap: every field labelled official must be explicitly confirmed official in the model section. The example has a placeholder verification reference and resolves to vendor-informed. The render probe uses an optional local Transformers tokenizer and requires a separately supplied serving-layer rendering for comparison; no engine-specific normalizer is assumed. String tests do not validate a real tokenizer.
