# Quality rank is not enough: the usability (latency) gate

[Book](../README.md) | [All tables](results.md) | [Pitfalls](pitfalls.md)

### Problem

Choosing finalists by quality average alone promotes a model nobody can wait for. In our bake-off a quality-only ranking put a model into the finals whose measured wait was far longer than the incumbent's, and it consumed a long exclusive evaluation run before anyone asked whether it was usable; the model, hardware and numbers are not shown here. The signal had been present earlier, as a low tokens-per-second figure and a long per-item output, and had not been converted into the wait a user would feel. The question that surfaced it was "is it unusable?", asked by a person.

### What we built or changed

A usability preflight that runs before the full evaluation and decides whether a model is allowed into the full run and into the ranking.

1. Five representative single-turn questions, one from each of c1-kbqa, c4-code, c5-extract, c7-zhif, c10-sre-ops (the first item of each; no image, no long context), sent one at a time (single stream), using the model's recipe when it has one (the wait a user feels is the wait at the recipe's tier).
2. Per question: end-to-end wall seconds and output tokens. A wall-clock timeout counts as the timeout in seconds (a lower bound on the latency); other failures count as errors.
3. Statistic: median and p90 of the five wall times (inclusive quantile method; with five samples the inclusive p90 weights the slowest 60 % and the next slowest 40 %, so it is nearly the maximum).
4. Status: `INTERACTIVE` if p90 is at or below the threshold (default 30 s), `NOT_INTERACTIVE` above it, `ERROR` if any non-timeout failure, `UNMEASURED` if the preflight did not ask for it. Request timeout during the preflight is `max(120, 4 x p90 limit)` seconds.
5. Gate: only `INTERACTIVE` goes to the full run and to the ranking. `NOT_INTERACTIVE`, `ERROR` and `UNMEASURED` do not, unless the plan explicitly declares an offline use and gives a reason (written to the output). Loosening the threshold above 30 s requires a written reason, or an `INTERACTIVE` result is still not allowed through.
6. Wiring: the driver skips the full run; the summary script ranks only models that pass.

The 30 s default is a judgment of an interactive-chat ceiling, not a calibrated value.

### Procedure as actually run

Built after the incident, unit tested with a fake `post` and a fake bank (fixtures taken from the original incident, replaced here with synthetic numbers), wired into the three drivers and the summary script, and replayed over existing runs: all five models in the replay were marked "unmeasured, not ranked" because the preflight had not run for them. It was never used in anger on a new bake-off.

### Results

GB10 evidence, derived from the stored per-item records of complete runs of the same 132 items (c1, c4, c5, c7-zhif, c10; 30 + 12 + 30 + 30 + 30), by tokens and not by wall time (wall times in those runs were taken under concurrency and are not single-stream latencies):

| Model and setting | Output tokens per item: median | p90 (inclusive) | max | Truncated at cap |
|---|---|---|---|---|
| Qwen3.8-Flash-Next, thinking off | 69.5 | 129 | 453 | 0 |
| Qwen3.8-Flash-Next, thinking on, default tier, cap 16,384 | 284.5 | 1,191 | 12,917 | 0 |
| DeepSeek V4 Flash Vision-Exp, thinking off | 45 | 111 | 182 | 0 |
| DeepSeek V4 Flash Vision-Exp, thinking `high`, cap 16,384 | 125.5 | 589 | 16,384 | 2 |

Illustrative arithmetic only (prefill, queueing and the difference between the runs' engine settings ignored): single-stream decode rates published in the evaluation cookbook for the same pair are 52.9 tok/s (Qwen3.8-Flash-Next, two nodes) and 31.8 tok/s (DeepSeek V4 Flash Vision-Exp, two nodes). Dividing:

| Model and setting | p90 tokens / published rate | Estimated seconds | Against a 30 s gate |
|---|---|---|---|
| Qwen3.8-Flash-Next, thinking off | 129 / 52.9 | 2.4 | passes |
| Qwen3.8-Flash-Next, thinking on | 1,191 / 52.9 | 22.5 | passes narrowly |
| Qwen3.8-Flash-Next, thinking on, worst item | 12,917 / 52.9 | 244 | far over |
| DeepSeek V4 Flash Vision-Exp, thinking off | 111 / 31.8 | 3.5 | passes |
| DeepSeek V4 Flash Vision-Exp, thinking `high` | 589 / 31.8 | 18.5 | passes |
| DeepSeek V4 Flash Vision-Exp, thinking `high`, cap-hit item | 16,384 / 31.8 | 515 | far over |

A 30 s budget at those rates is about 1,590 tokens (52.9 tok/s) or about 950 tokens (31.8 tok/s) of output. On the single-node EXL3 build, measured per-stream rates were 21.4 to 24.6 tok/s, so a 30 s budget is roughly 640 to 740 output tokens; a maximum-effort or high-effort 32,768-token generation took about 1,230 to 1,530 s per stream (stress log).

The long coding category on that single node (chapter 4 table) shows what the gate cannot see: the five-question preflight uses short categories, while the long coding category's slowest repository took 525 s with 17,481 output tokens.

### What did not work

- Quality-only ranking with a note "usability not measured".
- Relying on tokens per second alone: the user waits for the length of the answer divided by the rate.
- The default threshold gate with a bypass: setting the maximum to `nan` made `p90 > nan` false for every model, so a model whose p90 was far above the 30 s limit was marked interactive. A check requiring a finite positive value was specified and left open in the audit.
- Five samples for p90. It is almost the maximum; a single slow item decides.

### Pitfalls

| Symptom | Root cause | Fix |
|---|---|---|
| A model near the top of quality ranks takes minutes per answer | Rank ignored latency | Preflight usability gate before the full run |
| Gate loosened silently | Threshold set high without a reason | Loosening requires a reason; unreasoned loosening is refused |
| `nan` threshold passes everything | Comparison with nan is false | Validate the threshold is finite and positive |
| Latency estimates differ between runs | Concurrency, recipe tier and cache state differ | Single-stream, recipe tier, fresh prompts |

### The rule

Before a model is ranked, a five-question single-stream preflight measures the wait at the tier you would deploy, and a model whose p90 exceeds the stated threshold does not enter the full run or the ranking unless an offline use is declared in writing.

Stub test: a fake `post` that returns scripted seconds; five scripted values whose inclusive p90 is above 30 s (for example 8, 15, 40, 95, 95, giving 95) must give `NOT_INTERACTIVE`, five values near 3 s (p90 3.8 for 2.8, 3.1, 3.2, 3.5, 4.0) must give `INTERACTIVE`, a threshold of 120 without a reason must refuse, and a threshold of `nan` must be rejected (not currently in the code).

## Public implementation boundary

The public gate adds the requested finite-positive threshold validation. All scripted timing values are synthetic. Non-timeout errors take precedence over the latency classification. This change is a local implementation, not evidence that the historical gate was deployed or used on a live bake-off.
