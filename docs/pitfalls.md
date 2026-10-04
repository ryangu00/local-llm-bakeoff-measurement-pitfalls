# Pitfalls: symptom, cause, repair and boundary

Read the raw per-item record, then the server log, before interpreting a score. These mappings retain the difference between implemented guards and proposals. Public additions are called out per chapter.

## 1. Triage

| Symptom | Root cause | Fix |
|---|---|---|
| "HTTP Error 400: Bad Request" with no reason | `urllib` raises `HTTPError` without reading the body | In the harness call `e.read()` and keep the first 400 characters in the record |
| Category score looks plausible but one run is wrong | Median over runs includes a run of error rows scored as zero | See chapter 3: refuse a median over any run that contains errors |
| Cause is attributed to the model first | No rule says where to look first | The three-signal rule, with the raw record as first reading |

### Why the first repair was insufficient

- A single written rule ("errors above zero means check the pipeline") was in our notes before the second and third incident of the same family. Notes did not stop recurrence. The same missing-authentication defect came back in a second code path (chapter 3) and the same heartbeat defect came back three times in three places (chapters 2 and 3).
- Reading only the summary table. It showed scores, not errors.

### Check the boundary

The incident checklist is historical. The synthetic run in `fixtures/runs/` exercises the scanner and error summary; it does not reproduce the private questions or scores.

Full mechanism and evidence: [triage](triage.md).

## 2. Timing

| Symptom | Root cause | Fix |
|---|---|---|
| Prefill 12.5 times too high | Generator used a fixed seed; engine prefix cache hit on every pass after the first | Seed from `(n, i)` and a per-pass nonce at the start of the prompt; read cached tokens when the server reports them |
| Prefill 15 % low | Denominator is the nominal size (words / 1.3), not the tokenizer's count | Divide by `usage.prompt_tokens` |
| Absurdly high prefill rate from a streaming probe, or a division by zero at the smallest tier | First data line was a heartbeat, so the timer stopped at heartbeat arrival | Skip chunks with `model == "keepalive"` and chunks with empty content and empty reasoning; assert a plausibility bound; or use non-streaming requests with server usage |
| Decode rate a third of the truth | One SSE delta carried 2.6 to 3.0 tokens | Use `usage.completion_tokens` |
| Stall alarm on a healthy server | Idle counter included streams that had finished | Count only unfinished streams; confirm with the server's running-request count |
| Cached-token field is `null` | Server may need a reporting flag (likely here, unverified) | Check the flag; do not read `null` as "no cache hit" |

### Why the first repair was insufficient

- Dropping only the first pass and trusting repeats. A cache survives across passes, not just across the first one.
- The millisecond-agreement heuristic (above).
- Fixing the denominator in one script. The streaming probe kept dividing by the nominal size after the other script had moved to server token counts. Chapter 1's sibling sweep applies.
- A seed derived only from `(tier, pass)`: re-running a target replays the same prompts as the previous invocation, so a second invocation can hit a cache left by the first. This was recorded in the ledger as open and never fixed in our scripts. The nonce in `speed_bench.py` closes it for that script only.

### Check the boundary

The public `speed_bench.py` generates a fresh leading nonce per measurement request and uses usage counts. `prefill_ttft.py` deliberately retains the historical `(n, i)` seed and nominal denominator; its output is explicitly labelled nominal. Its prompts repeat across invocations. The SSE stub isolates heartbeat timing; it is not a GPU benchmark.

Full mechanism and evidence: [timing](timing.md).

## 3. Transport

| Symptom | Root cause | Fix |
|---|---|---|
| Coding category near zero, `errors` in every item | `Authorization` header missing on the coding-loop request path; then again on the pack subprocess | Send the key on every path; unit-test that each outgoing command and request carries it |
| Preflight passes but run fails | HTTP 200 with an error body, no `choices` | Require `choices` |
| Preflight hangs far beyond its timeout | Heartbeat bytes keep resetting the socket timeout | Wall-clock deadline in a daemon thread, restart the engine after it |
| Whole category 404 after downloading a model | Model directory scanned only at engine start; `/v1/models` listing does not prove servable | Restart, then a real request |
| Long-context category low | Engine fell back to its default window (32,768) because the config field it reads was absent or empty | Verify the effective window with a probe prompt, restart after config edits |
| Rest of a long-input category fails in a chain | Memory guard abort, then every request gets 409 until the unload completes | Concurrency 1 for long inputs; capacity-limited items are listed, not scored |
| Median 40.0 for a model that scores about 80 | Engine died during run 2; rows saved as zeros | Incomplete run is not a run: non-zero exit, no median |
| Text-only model "passes" a vision preflight | Image dropped, prompt tiny, pass criterion ignored it | Assert the prompt token count rises with an image |
| Tool category near zero with zero errors | Model's native tool-call markup arrived in `content`, `tool_calls` empty because the engine's tool parser was not attached on that path | A tool probe that must return parsed calls, in the pass criterion |

Driver-script defects found in the same hunt (each verified with a stdlib or shell experiment during fact gathering):

| Defect | Verified behaviour |
|---|---|
| `echo "$(date +%H) rc=$?"` after a failing command | Prints `rc=0`: `$?` is expanded after the command substitution, so the failure code is always that of `date` |
| `trap 'cleanup' EXIT INT TERM` with no `exit` | After TERM the handler runs, then the script continues to the next model; exit code 0 (bash; exact version withheld) |
| `trap cleanup EXIT` plus `trap 'exit 143' INT TERM` | Cleanup runs once; exit code 143; the loop stops |
| `... | tee "$FILE"` without `-a` | Second invocation truncates the earlier result file |
| A time window cut with `awk '$0 >= "2026-09-23 22:00"'` | Continuation lines of a traceback start with letters that sort above `2`, so every continuation line passes at any time (verified: a five-line sample returned three untimestamped lines from before the cut). On our server log this produced an invented error count that was then used as the reason to stop a run |
| `pgrep -f name | kill` | Matches any process whose command line contains the string, including one that is not yours |

### Why the first repair was insufficient

- Exit code 0 on a dead engine. The runner wrote error rows and returned success.
- Reading `/health`. It stays 200 while the engine is dead (see the linked cookbook); liveness must be a real generation of a few tokens.
- Treating a median as a summary when one run is error rows. A median of `[80.0, 0.0]` is 40.0 and nothing in the number says why.
- A preflight that checked only HTTP status, then one that checked `choices` but not tool parsing or modality. The tool probe's result was printed but not part of pass; the vision probe's prompt token count was not checked. A text-only model passed a preflight that asked it about an image because the image was dropped and the prompt was tiny. Both gaps were left open (specified, not built).

### Check the boundary

The public `preflight.py` adds the previously missing parsed-tool-call and image-token checks. The latter checks a token-count increase only, not visual correctness. A daemon-thread deadline abandons the client wait; this repository does not restart any engine. Restart and readiness handling remain the caller's responsibility. The full runner is not shipped.

Full mechanism and evidence: [transport](transport.md).

## 4. Scoring

| Symptom | Root cause | Fix |
|---|---|---|
| A truncated answer scores full marks | Engine returns unclosed thinking in `content`; grader finds an answer-shaped block in the draft | Score 0 whenever `finish == length`; keep original in a field |
| "10 of 10 identical" for two decoding modes | Both sides were empty strings (the answer sat in the reasoning field, only `content` was stored) | Store both fields; empty on either side is "invalid" |
| Every code item scores 0, rc 1 | Grader dependency missing on a new host | Record grader versions; refuse to run when the grader cannot run |
| "Parallel 2" run behaves like 4 | The pack subprocess had a hard-coded `--parallel 4` | Pass the flag through; assert in a test with a fake subprocess |
| Categories in one run not comparable | Own categories 8,000 tokens, pack categories tool default | Make the budget explicit for all categories |
| Slow generation recorded as a failure | Item timeout reached while the model was still producing | Re-run once with a longer timeout, report both, keep the protocol score |
| Repair tool disagrees with the main grader | Repair tool re-implements a subset of the rules | Import the main grader; never fall back silently |

### Why the first repair was insufficient

- "Fix the grader score after the fact" without applying the rule. The re-grade tool initially skipped the truncation rule and cut the answer.
- The strict position-matching of the pack evaluator (a probing call before the expected call scores 0) systematically penalises thinking models. We promised a lenient re-score and never built it; the size of the bias was never measured. Treat pack differences between a thinking and a non-thinking model as unresolved.
- Declaring a ranking rule before the data and then changing it after seeing the data (which categories count toward a rank, how many runs per model). The remedy is a frozen rule file hashed at the first run, with a header that prints "rule changed after data N times" (specified, not built). A GB10 example of a gate rewritten after a failed result is in chapter 6.
- A reference row from a different harness version, concurrency and configuration placed in the same ranking table and labelled "background only". The label constrained nothing; a reference row that is not rerun under the same driver may not enter a ranking.
- Cutting the minimum number of runs. A single run per model was used to pick finalists; the per-category sizes (12 to 30 items; one item is 3.3 to 8.3 points) put the finalists inside the noise.

### Check the boundary

The public scan keeps the original score arithmetic and explicitly reports credited truncations. `greedy_compare.py` keeps the empty-input rule and first-divergence position, and also rejects missing or unequal sample lists. The optional re-grader is omitted because the public grader import interface is not provided. See [the harness test pattern](implementation.md#harness-integration-test-pattern).

Full mechanism and evidence: [scoring](scoring.md).

## 5. Recipes

| Symptom | Root cause | Fix |
|---|---|---|
| Vendor arm is better on one category only, total flat | Recipe changed several things; only budget-limited or tier-sensitive categories react | Report the arms side by side, with the header "composite intervention" |
| `official` label on a value that was inferred | Evidence label lost when copying research to the recipe | Source gate: `official` needs a hash-bound verification report that names the field |
| Same string, different tier | Templates interpret kwargs differently, a layer between client and template may rewrite or drop them | Send only keys the template source reads; render once offline and read the output |
| Multi-turn loop scores differ by engine | The loop did not echo reasoning back; the serving layer may rewrite what is echoed | Echo `reasoning_content`; verify by offline render, not by prompt tokens |
| Output looks truncated at 8,000 tokens | The harness cap, not the model | Budget = peak reasoning plus answer; record `finish_reason` |
| Verifier and researcher disagree | Either can be wrong | Reconcile against the tool's source and against result files |

### Why the first repair was insufficient

- Using the token-count increase as proof that reasoning reached the template. A model whose serving layer inlined the echoed reasoning and let the template add an empty block grew the prompt by far more than 60 tokens and passed; the offline render showed two thinking blocks. A token count is a proxy; the property is the rendering.
- The first probe used a plain chat history. Two of the templates keep earlier reasoning only for tool-call turns that come after the last user message, so a no-tool history can never reveal the problem.
- Writing drafted recipe values into a gate without verification: the drafted values launched a vendor arm on one model, and that run had to be discarded after the render check failed.
- Writing vendor sampling into a shared engine configuration file in one batch, without a runtime check that the engine reads those fields. The batch wrote a value the verification had already refuted (a top_p for all categories), left a misleading speculative-decoding field in place, and changed a default that the control arm depended on (an omitted `top_k` would now come from the file); at the time the ledger was frozen only a backup and a README existed, and the change had not been reverted. Engines differ on whether they read the model's `generation_config.json`: on engine B the precedence was request, then per-model settings, then global settings, and the model's own file was never read, so a client that omitted `top_k` did not get the vendor's value. Check how your engine resolves defaults; we did not check how vLLM does.

### Check the boundary

The public source gate closes the historical allow-list gap: every field labelled official must be explicitly confirmed official in the model section. The example has a placeholder verification reference and resolves to vendor-informed. The render probe uses an optional local Transformers tokenizer and requires a separately supplied serving-layer rendering for comparison; no engine-specific normalizer is assumed. String tests do not validate a real tokenizer.

Full mechanism and evidence: [recipes](recipes.md).

## 6. Identity

| Symptom | Root cause | Fix |
|---|---|---|
| Baseline column is a different model | Shared served alias across a swap; no weights identity recorded | Record the served model entry, revision or path, and mode at run start |
| Gate "own mean above baseline" passes against the wrong baseline | Gate keyed on bank only | Same-arm metadata check |
| Two runs not comparable though bank hash equal | Grader version hash, budget, thinking key and Python differ | Compare all listed fields; list intentional differences |
| Partial re-run merges into an older record | Bank hash is computed over the categories run | Keep category lists with the hash |
| "Landed on engine X" claim from a response field | Field present only in a state | Gateway headers; a disjoint-field test only as a cross-check |
| Request says `high`, served low | A port or proxy rewrites the tier | Record the effective tier; check output-length distribution against another tier |

### Why the first repair was insufficient

- Trusting the model field. After zero-client-change swaps through a shared alias, the model field in old result files does not identify the weights.
- Trusting `label` or file name. The label and model field named different models; either could be wrong in a different case.
- Relying on a gate that checks "same bank" but not "same arm". The route-change gate we reviewed compared bank hash and category list, not thinking mode, sampling, budget, system prompt, arm or grader version.
- Presenting a table whose columns came from different days, different grader code and different budgets as same-arm.

### Check the boundary

`check_same_arm.py` is new code implementing the specified field list. It refuses absent required metadata and prints each explicitly allowed difference. Empty system prompts and empty chat-kwargs dictionaries are valid recorded values; absent served identity is not. It cannot authenticate a claimed identity or infer the weights behind an alias.

Full mechanism and evidence: [identity](identity.md).

## 7. Isolation

| Symptom | Root cause | Fix |
|---|---|---|
| Production slowed or its model evicted during a test | Test and production share an engine process or a resident-model slot | Gate on the route table; move production off first |
| Test data disturbed by production requests | Same cause | Dedicated window or a dedicated engine |
| Gate passes for an obvious production address | Address spelling (trailing dot, short IPv4, mapped IPv6, integer) | Canonicalise numerically without DNS |
| Gate passes when asked through the gateway | Compared the gateway's address, not the deployments | Resolve the alias |
| Heavy thinking arm kills a production-fallback engine | Evaluation workload as heavy as the failure trigger | No maximum-effort arms on an engine that carries fallback traffic |

### Why the first repair was insufficient

- A rule written in notes that experiments do not run on production. It existed; the benchmark ran on the production endpoint anyway because the endpoint became production after the plan was written.
- Matching on the gateway address. Through a gateway the deployments behind the alias are what must be compared.
- Treating a container's "Up" status or `/health` as an engine liveness signal.

### Check the boundary

The public gate retains the documented fail-open record for unreadable or empty route tables when checking a direct endpoint. An unresolved gateway alias is refused. Host-service-manager checks and credential-file discovery are removed. No LAN-interface discovery is added; the historical address-alias gap remains. Fixtures use loopback endpoints only.

Full mechanism and evidence: [isolation](isolation.md).

## 8. Usability

| Symptom | Root cause | Fix |
|---|---|---|
| A model near the top of quality ranks takes minutes per answer | Rank ignored latency | Preflight usability gate before the full run |
| Gate loosened silently | Threshold set high without a reason | Loosening requires a reason; unreasoned loosening is refused |
| `nan` threshold passes everything | Comparison with nan is false | Validate the threshold is finite and positive |
| Latency estimates differ between runs | Concurrency, recipe tier and cache state differ | Single-stream, recipe tier, fresh prompts |

### Why the first repair was insufficient

- Quality-only ranking with a note "usability not measured".
- Relying on tokens per second alone: the user waits for the length of the answer divided by the rate.
- The default threshold gate with a bypass: setting the maximum to `nan` made `p90 > nan` false for every model, so a model whose p90 was far above the 30 s limit was marked interactive. A check requiring a finite positive value was specified and left open in the audit.
- Five samples for p90. It is almost the maximum; a single slow item decides.

### Check the boundary

The public gate adds the requested finite-positive threshold validation. All scripted timing values are synthetic. Non-timeout errors take precedence over the latency classification. This change is a local implementation, not evidence that the historical gate was deployed or used on a live bake-off.

Full mechanism and evidence: [usability](usability.md).

## 9. Audit

| Symptom | Root cause | Fix |
|---|---|---|
| Tests all green, audit fails | Tests encode the incident, not the class | Mutation plus incident-shaped new cases written by someone else |
| Gate bypass by relabelling | Gate trusts a label | Allow-list: positive evidence per field |
| Gate bypass by address spelling | String match on addresses | Canonicalise numerically, compare against local interfaces |
| Gate not on the host that runs the bake-off | Deployment step skipped | Deployment as a tested script with a backup step |

### Why the first repair was insufficient

- "The tests are green" as acceptance.
- Fixing only the spelling in the incident. Reviewer-built new cases (a different bank of relabelled fields, a different spelling of the local host) found what the original-incident tests could not.
- Self-written mutants only: the author's mutants are biased to what the author thought of.

### Check the boundary

The historical final verdict remains FAIL: 2 medium and 5 low findings were open. Local tests of this public adaptation do not replace that independent audit. The source allow-list and finite-threshold repairs are new; the production address-alias gap remains. No live bake-off was run with these gates.

Full mechanism and evidence: [audit](audit.md).
