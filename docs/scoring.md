# Scoring rules that credit or hide the wrong thing

[Book](../README.md) | [All tables](results.md) | [Pitfalls](pitfalls.md)

### Problem

Graders and aggregators encode rules that assume the response shape. When the shape differs between engines, the same truncated or empty response earns a different score. When the rules are not applied to every path, tools written to repair a number break them.

### What we built or changed

1. Truncation gets no credit, whatever the engine. If `finish_reason` is `length` and the grader would give a score above zero, the score is set to 0 and the original is kept in a `truncated_credit_revoked` field. Engines differ: one engine with a template that opens the thinking block inside the prompt returned unclosed thinking in `content` when generation was cut, and the grader found a code fence in the draft and gave full marks to an incomplete answer. The same truncation on vLLM leaves `content` empty and scores 0. Without a uniform rule scores are not comparable across engines.
2. A scan, `trunc_credit_scan.py`, that walks a runs directory and reports, per category: items scored, items with `finish=length`, how many of those were credited, the score without them, and the share of items whose usage shows separated reasoning tokens (non-zero reasoning tokens). The share matters: when reasoning is not separated, truncated answers can be graded from the thinking draft.
3. A re-grader that reuses the main grading path. A first re-grade script judged the answer field, which the runner had already cut to 2,000 characters, bypassed the truncation rule and silently fell back to the cut field when the raw body would not parse. It now takes the full text from the raw HTTP body, applies the same truncation rule, and reports a parse failure instead of falling back.
4. Equality comparisons that refuse empty input: `greedy_compare.py` stores reasoning and content for each greedy sample, and if either side is empty on both fields it reports "invalid test", never "identical".
5. Grader environment is recorded in the result file: tool-eval-bench version, pytest version, Python version. A missing `pytest` makes every hidden-test run exit with code 1 and score 0; nothing refused to run. The check "refuse to run when the grader is unavailable" was specified and not built.
6. The pack-category subprocess takes its concurrency from the flag (it had been hard-coded to 4, so a test labelled "parallel 2" ran at 4), a non-zero exit returns "no score" instead of a score, and the overall pack wall-clock limit scales with the output budget (`int(3600 * scale)`) and catches the timeout.
7. Both budgets in one run. Own categories used 8,000 output tokens; pack categories used the third-party tool's default (16,384 in the thinking configuration), so categories within one "uniform" run had different budgets. The budget is passed to the pack tool only when a recipe or flag sets it explicitly.

### Procedure as actually run

GB10 control scan, run during fact gathering over our stored raw per-item records (the shipped `trunc_credit_scan.py` logic, with a different directory selection): 30 result directories that hold raw per-item files, 28 dated 2026-09-17 to 2026-09-20 and two GB10 runs from 2026-09-23, all served by vLLM on the two-node pair, 264 per-category result files. Every result file in the selection names the two-node endpoint as its base URL (two directories have raw files but no result file).

| Quantity | Value |
|---|---|
| Per-item records with a score | 6,671 |
| Records that carry a `finish` field (all coding-loop records and some older records of other categories do not) | 6,151 |
| Records whose usage shows separated reasoning tokens | 1,744 |
| Records with `finish = length` | 7 |
| Of those, scored above zero | 0 |

Five distinct items account for the seven records: one each in an extraction, a vision and a Chinese-instruction category, and two code-fix items that appear in two files holding identical records (a thinking-mode run and its merged corrected copy). All seven scored 0. So on vLLM the truncation-credit defect did not occur in 6,151 recorded finishes; it was an engine-B behaviour that the engine-independent rule was written for.

### Results

Effect of the output setting on the same bank, GB10, category c4-code (12 hidden-test code-fix items), run 1 of each:

| Model and setting | Tokens per item mean / median / max | Reasoning tokens per item (mean) | Truncated at cap | Score |
|---|---|---|---|---|
| Qwen3.8-Flash-Next, thinking off | 132 / 91.5 / 453 | 0 | 0 | 95.8 |
| Qwen3.8-Flash-Next, effort requested as `high` through a port that forces a low tier | 398 / 324 / 1,033 | 310 | 0 | 95.8 |
| Qwen3.8-Flash-Next, thinking on, default tier, cap 16,384 | 2,708 / 986 / 12,917 | 2,599 | 0 | 95.8 |
| DeepSeek V4 Flash Vision-Exp, thinking off | 81 / 68.5 / 160 | 0 | 0 | 87.5 |
| DeepSeek V4 Flash Vision-Exp, thinking `high`, cap 16,384 | 3,366 / 648.5 / 16,384 | 3,302 | 2 | 79.2 |

At n = 12 one item is 8.3 points; the 79.2 versus 87.5 difference is exactly one item. The same model with the same score generates between 132 and 2,708 tokens per item depending on the setting; chapter 8 turns that into latency.

Timeout counted as ability (single-node EXL3 build, a category of six long coding repositories, harness-uniform arm with effort low, two runs): scores 81.25 and 96.53, median 88.9, spread 15.3 (flagged). The first run's low value was recorded in our notes as one repository reaching the 900 s item timeout while the model generated at about 25 tok/s; the raw bodies of that run were not retained locally, so this attribution is recorded, not re-verified. A supplementary single run with the timeout doubled to 1,800 s scored 98.6 and no repository exceeded 526 s:

| Repository slot | Wall seconds | Output tokens | Hidden tests passed |
|---|---|---|---|
| 1 | 23.8 | 875 | 10 / 10 |
| 2 | 74.2 | 2,657 | 8 / 8 |
| 3 | 25.4 | 969 | 10 / 10 |
| 4 | 26.3 | 962 | 11 / 11 |
| 5 | 392.4 | 12,873 | 11 / 12 |
| 6 | 525.4 | 17,481 | 12 / 12 |

At the 21.5 to 24.5 tok/s per-stream rate measured in the stress test, 900 s is about 19,000 to 22,000 tokens, within reach of the generation lengths above. The protocol score stayed 88.9; 98.6 was reported beside it as evidence that the low value was throughput, not capability.

### What did not work

- "Fix the grader score after the fact" without applying the rule. The re-grade tool initially skipped the truncation rule and cut the answer.
- The strict position-matching of the pack evaluator (a probing call before the expected call scores 0) systematically penalises thinking models. We promised a lenient re-score and never built it; the size of the bias was never measured. Treat pack differences between a thinking and a non-thinking model as unresolved.
- Declaring a ranking rule before the data and then changing it after seeing the data (which categories count toward a rank, how many runs per model). The remedy is a frozen rule file hashed at the first run, with a header that prints "rule changed after data N times" (specified, not built). A GB10 example of a gate rewritten after a failed result is in chapter 6.
- A reference row from a different harness version, concurrency and configuration placed in the same ranking table and labelled "background only". The label constrained nothing; a reference row that is not rerun under the same driver may not enter a ranking.
- Cutting the minimum number of runs. A single run per model was used to pick finalists; the per-category sizes (12 to 30 items; one item is 3.3 to 8.3 points) put the finalists inside the noise.

### Pitfalls

| Symptom | Root cause | Fix |
|---|---|---|
| A truncated answer scores full marks | Engine returns unclosed thinking in `content`; grader finds an answer-shaped block in the draft | Score 0 whenever `finish == length`; keep original in a field |
| "10 of 10 identical" for two decoding modes | Both sides were empty strings (the answer sat in the reasoning field, only `content` was stored) | Store both fields; empty on either side is "invalid" |
| Every code item scores 0, rc 1 | Grader dependency missing on a new host | Record grader versions; refuse to run when the grader cannot run |
| "Parallel 2" run behaves like 4 | The pack subprocess had a hard-coded `--parallel 4` | Pass the flag through; assert in a test with a fake subprocess |
| Categories in one run not comparable | Own categories 8,000 tokens, pack categories tool default | Make the budget explicit for all categories |
| Slow generation recorded as a failure | Item timeout reached while the model was still producing | Re-run once with a longer timeout, report both, keep the protocol score |
| Repair tool disagrees with the main grader | Repair tool re-implements a subset of the rules | Import the main grader; never fall back silently |

### The rule

A response earns a score only if it finished (`finish != length`), only if what is compared is non-empty, and only if the grader that ran is the grader that is recorded. A repair tool must use the same code path as the original grader.

Stub tests: a server that returns `finish_reason: "length"` with a code fence in `content`; a unit test that a fake subprocess receives `--parallel 2` when the flag says 2; a greedy comparison of two files with empty text must say "invalid".

## Public implementation boundary

The public scan keeps the original score arithmetic and explicitly reports credited truncations. `greedy_compare.py` keeps the empty-input rule and first-divergence position, and also rejects missing or unequal sample lists. The optional re-grader is omitted because the public grader import interface is not provided. See [the harness test pattern](implementation.md#harness-integration-test-pattern).
