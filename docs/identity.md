# What was under test, part two: identity, provenance and same-arm comparison

[Book](../README.md) | [All tables](results.md) | [Pitfalls](pitfalls.md)

### Problem

A name in a result file is not the weights that answered. Four things were mistaken for each other in our runs: the alias a request used versus the weights behind it, the effort level a request asked for versus the one served, the arm a table column was labelled with versus the arm that produced it, and the alias a gateway was asked for versus the deployment that answered.

### What we built or changed

1. A same-arm metadata check, specified in this chapter from the fields the result file already stores (no source file exists for it; implemented here from the specification). Two runs may share a comparison table only if these fields match, or the difference is listed in an explicit "intentional differences" line: bank hash, grader version hash, grader environment, arm name, sampling, `chat_template_kwargs`, output budget, system prompt, thinking flag, served model identity.
2. Identity of the served weights recorded at run start, not inferred from a name: the server's model list entry, the model path or revision it reports, the engine mode in force at that time, a timestamp.
3. Routing proof from response headers, not from a field that may be absent. LiteLLM adds headers naming the deployment's API base and the number of attempted fallbacks. A route change is accepted when three real calls show the expected base and zero fallbacks; a removed alias is verified by a request that must return "Invalid model name".
4. Evaluations that go through a gateway bind to the deployment that answered. A gate that treats "I asked for alias X" as "X's first hop answered" accepts a run in which the first hop failed and the fallback answered.
5. Gates are set before the data and rewrites are recorded with the reason.

### Procedure as actually run

The case below was found after the fact, by cross-checking result metadata with the dated switch log. It was never caught by a gate.

### Results

A comparison table for a single-node build was labelled "two-node baseline". Its baseline column came from a result directory whose model field read `deepseek-v4-flash-vision-exp`. The run metadata and the switch log show that the weights behind that name at the time were Qwen3.8-Flash-Next:

| Evidence | Value |
|---|---|
| Baseline run time | 2026-09-24 22:48 local |
| Model field in the result file | `deepseek-v4-flash-vision-exp` (the shared served alias) |
| Chat kwargs recorded | `enable_thinking: true` (the Qwen family's key; the other model uses `thinking` and `reasoning_effort`) |
| When the pair actually switched to the other model | 2026-09-25 01:10:48 (switch log), ready 01:14, so 2.4 hours after this run |
| Alias note in the decision record | Qwen3.8-Flash-Next under the one-million-token configuration was also served under that alias, so clients saw no change |
| A companion prefill file taken at 01:08 the same night | The file's own label names Qwen3.8-Flash-Next (NVFP4); its model field is the same alias |
| The cutover document that used this run | Treats it as the Qwen3.8-Flash-Next baseline for a quality-parity gate against the same model on another engine, not as a run of the other model |

Confidence: high from the timeline, the chat-kwargs key and the labels; we have no response-level proof (the raw bodies were not kept locally), so this conclusion is established by metadata and dates.

The baseline column also differed from the single-node arm it was compared against in four more ways, all visible in the result files:

| Field | Baseline column run | Single-node arm run |
|---|---|---|
| Bank hash | hash A | hash A (same) |
| Grader version hash | hash G1 | hash G2 (different code) |
| Output budget | 16,384 | 8,000 |
| Thinking control recorded | `enable_thinking: true` (override) | `reasoning_effort: low` (override) |
| Python recorded | environment A | environment B (different Python versions; exact strings withheld) |

The decision that followed (adopting the single-node build) had a preset gate (own mean no more than 3 below the baseline, vision no more than 3 below). The measured gaps against that column were own -4.4, pack -6.4, vision -7.5, so the gate failed; the owner rewrote the gate (own within 5, pack at least 80, vision at least 70, no new safety failures) and accepted the cost in writing. The original gate was kept as a reference. Whatever one thinks of the rewrite, the table compared the single-node build against a different model, and the same-arm check above would have refused the table.

Recorded request versus served tier: the GB10 low-tier run mentioned in chapter 5 recorded `reasoning_effort: high` in its result file while the port it called forced a low tier. Only the output-length distribution (398 versus 2,708 mean tokens per item) revealed it.

Recorded flag versus effective flag, second instance: a test labelled "parallel 2" ran its pack categories at 4 (chapter 4). A false causal story was built on it: an observation "this category ran at concurrency 4 with zero errors" was used as a control to argue that concurrency was the variable behind a capacity failure, while the 4 itself came from a hard-coded value that no flag controlled.

Gateway alias versus answering deployment: a gate bound an evaluation to the alias that was requested. A test fixture with a fallback alias showed that when the first hop failed and the fallback answered, the result file still recorded the requested alias. The cure is to bind to the deployment id and the effective endpoint of each answered request, and to disable fallback when measuring a first hop.

`model_load_duration` as a routing signal: a verification note used the presence of that response field to decide where a request landed. It had been checked only in the cold state; when warm the field is absent, so a set of concurrent warm requests was judged to have landed on the other backend. The cure was a disjoint set of response fields for the two engines (fields only one of them returns), then the gateway headers above.

### What did not work

- Trusting the model field. After zero-client-change swaps through a shared alias, the model field in old result files does not identify the weights.
- Trusting `label` or file name. The label and model field named different models; either could be wrong in a different case.
- Relying on a gate that checks "same bank" but not "same arm". The route-change gate we reviewed compared bank hash and category list, not thinking mode, sampling, budget, system prompt, arm or grader version.
- Presenting a table whose columns came from different days, different grader code and different budgets as same-arm.

### Pitfalls

| Symptom | Root cause | Fix |
|---|---|---|
| Baseline column is a different model | Shared served alias across a swap; no weights identity recorded | Record the served model entry, revision or path, and mode at run start |
| Gate "own mean above baseline" passes against the wrong baseline | Gate keyed on bank only | Same-arm metadata check |
| Two runs not comparable though bank hash equal | Grader version hash, budget, thinking key and Python differ | Compare all listed fields; list intentional differences |
| Partial re-run merges into an older record | Bank hash is computed over the categories run | Keep category lists with the hash |
| "Landed on engine X" claim from a response field | Field present only in a state | Gateway headers; a disjoint-field test only as a cross-check |
| Request says `high`, served low | A port or proxy rewrites the tier | Record the effective tier; check output-length distribution against another tier |

### The rule

A result is only comparable to another result if the weights, the settings actually served and the grader that scored them are the same, and every one of those facts is recorded in the result file at run start, not recovered later from dates.

Stub test: two result files that differ only in grader hash must be refused by the same-arm check; one that differs only in an "intentional differences" field must pass with a printed note.

## Public implementation boundary

`check_same_arm.py` is new code implementing the specified field list. It refuses absent required metadata and prints each explicitly allowed difference. Empty system prompts and empty chat-kwargs dictionaries are valid recorded values; absent served identity is not. It cannot authenticate a claimed identity or infer the weights behind an alias.
