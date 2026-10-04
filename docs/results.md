# Results and evidence tables

These are transcribed historical results and diagnostic tables. They are not outputs of the synthetic tests. Dates or sample sizes absent from the source are identified as not supplied. Exact test-environment version strings are withheld; the reproduction baseline is bash 3.2 or newer, Python 3.10 or newer.

## Chapter 1: triage

Context and qualifications: [triage](triage.md).

Conditions: First-hours triage during the roughly day-long 2026-09-23 to 2026-09-24 bake-off; the prefill comparison is the two-node GB10 measurement, other failures are mechanisms without published scores.

| Wrong number | What it really was | How it was found |
|---|---|---|
| Prefill 64K at 28,894 tok/s on two GB10 nodes | Cache read, not prefill. True value at the same nominal size 2,318 tok/s in the same harness, 12.5 times lower (28,894 / 2,318); about 2,725 tok/s once server token counts replace the nominal size | Absolute value far above the other tiers; fixed seed in the generator; see chapter 2 |
| A coding category near zero with errors in its per-item records | Every request in one code path was rejected: no `Authorization` header | Per-item `error` field and server log line `401: API key required` |
| A long-context category near zero | Engine read the context length from one config field, did not find it, fell back to 32,768 | Server log: prompt N tokens exceeds max context window of 32768 |

Conditions: Diagnostic mapping for this chapter; fixes describe the intended rule, not universal deployment or historical completion.

| Symptom | Root cause | Fix |
|---|---|---|
| "HTTP Error 400: Bad Request" with no reason | `urllib` raises `HTTPError` without reading the body | In the harness call `e.read()` and keep the first 400 characters in the record |
| Category score looks plausible but one run is wrong | Median over runs includes a run of error rows scored as zero | See chapter 3: refuse a median over any run that contains errors |
| Cause is attributed to the model first | No rule says where to look first | The three-signal rule, with the raw record as first reading |

## Chapter 2: timing

Context and qualifications: [timing](timing.md).

Conditions: 2026-09-23, Qwen3.8-Flash-Next NVFP4, two GB10 nodes, tensor parallelism 2; four passes per tier, first dropped, median of three; nominal denominator.

| Nominal tier (words / 1.3) | TTFT median (s) | Three passes (s) | Prefill (tok/s, nominal denominator) |
|---|---|---|---|
| 1,000 | 0.397 | 0.402, 0.397, 0.396 | 2,519 |
| 4,000 | 1.467 | 1.467, 1.467, 1.458 | 2,727 |
| 16,000 | 6.092 | 6.092, 6.085, 6.109 | 2,626 |
| 64,000 | 27.608 | 27.486, 27.756, 27.608 | 2,318 |

Conditions: 2026-09-25 at 01:08 local, same two-node pair and model; three distinct prompts; server usage denominator; cached_tokens null, cause not verified.

| Pass | Prompt tokens (usage) | TTFT (s) | Prefill (tok/s) |
|---|---|---|---|
| 1 | 63,936 | 23.537 | 2,716.4 |
| 2 | 63,750 | 23.313 | 2,734.5 |
| 3 | 63,836 | 23.437 | 2,723.7 |

Conditions: 2026-09-26, single-node EXL3 stress log, 102 minutes; nine completed streams across the listed rounds; five streams at concurrency 6 hit the 1,700 s client timeout.

| Round (concurrency) | Streams completed | Completion tokens (usage) | Deltas | Tokens per delta |
|---|---|---|---|---|
| 2 | 2 | 32,768 and 32,768 | 11,726 and 11,673 | 2.79 and 2.81 |
| 4 | 4 | 32,768 x3 and 13,145 | 11,574, 11,390, 11,680 and 5,074 | 2.83, 2.88, 2.81, 2.59 |
| 6 | 1 completed (five hit the 1,700 s client timeout) | 21,795 | 8,110 | 2.69 |
| 2, second port | 2 | 32,768 and 28,384 | 10,998 and 10,424 | 2.98 and 2.72 |

Conditions: Diagnostic mapping for this chapter; fixes describe the intended rule, not universal deployment or historical completion.

| Symptom | Root cause | Fix |
|---|---|---|
| Prefill 12.5 times too high | Generator used a fixed seed; engine prefix cache hit on every pass after the first | Seed from `(n, i)` and a per-pass nonce at the start of the prompt; read cached tokens when the server reports them |
| Prefill 15 % low | Denominator is the nominal size (words / 1.3), not the tokenizer's count | Divide by `usage.prompt_tokens` |
| Absurdly high prefill rate from a streaming probe, or a division by zero at the smallest tier | First data line was a heartbeat, so the timer stopped at heartbeat arrival | Skip chunks with `model == "keepalive"` and chunks with empty content and empty reasoning; assert a plausibility bound; or use non-streaming requests with server usage |
| Decode rate a third of the truth | One SSE delta carried 2.6 to 3.0 tokens | Use `usage.completion_tokens` |
| Stall alarm on a healthy server | Idle counter included streams that had finished | Count only unfinished streams; confirm with the server's running-request count |
| Cached-token field is `null` | Server may need a reporting flag (likely here, unverified) | Check the flag; do not read `null` as "no cache hit" |

## Chapter 3: transport

Context and qualifications: [transport](transport.md).

Conditions: 2026-09-19, two-node DeepSeek V4 Flash Vision-Exp, thinking high, output cap 16,384, two runs; n = 30 / 6 / 12 as labelled; error-contaminated medians are invalid.

| Category | Run 1 | Run 2 | What run 2 actually was | Median reported |
|---|---|---|---|---|
| c10-sre-ops (30 items) | 80.0 | 0.0 | 30 of 30 items: `Connection refused` (errno 61), no latency recorded | 40.0, spread 80.0 (flagged, not failed) |
| c9-long-coding (6 repos) | 83.3 | 66.7 | 2 of 6: `HTTP Error 500` after 673.1 s and 628.1 s | 75.0, spread 16.7 |
| c4-code (12 items) | 79.2 | 95.8 | 2 items truncated at the 16,384 cap in run 1 | 87.5, spread 16.7 |

Conditions: Diagnostic mapping for this chapter; fixes describe the intended rule, not universal deployment or historical completion.

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

Conditions: Driver behaviour verified by small shell or stdlib experiments during fact gathering; bash 3.2 or newer, Python 3.10 or newer; these are failure demonstrations, not model results.

| Defect | Verified behaviour |
|---|---|
| `echo "$(date +%H) rc=$?"` after a failing command | Prints `rc=0`: `$?` is expanded after the command substitution, so the failure code is always that of `date` |
| `trap 'cleanup' EXIT INT TERM` with no `exit` | After TERM the handler runs, then the script continues to the next model; exit code 0 (bash; exact version withheld) |
| `trap cleanup EXIT` plus `trap 'exit 143' INT TERM` | Cleanup runs once; exit code 143; the loop stops |
| `... | tee "$FILE"` without `-a` | Second invocation truncates the earlier result file |
| A time window cut with `awk '$0 >= "2026-09-23 22:00"'` | Continuation lines of a traceback start with letters that sort above `2`, so every continuation line passes at any time (verified: a five-line sample returned three untimestamped lines from before the cut). On our server log this produced an invented error count that was then used as the reason to stop a run |
| `pgrep -f name | kill` | Matches any process whose command line contains the string, including one that is not yours |

## Chapter 4: scoring

Context and qualifications: [scoring](scoring.md).

Conditions: Control scan: 30 raw-record directories, 264 per-category files; 28 directories dated 2026-09-17 to 2026-09-20 and two dated 2026-09-23; two-node vLLM; two directories lacked results.json.

| Quantity | Value |
|---|---|
| Per-item records with a score | 6,671 |
| Records that carry a `finish` field (all coding-loop records and some older records of other categories do not) | 6,151 |
| Records whose usage shows separated reasoning tokens | 1,744 |
| Records with `finish = length` | 7 |
| Of those, scored above zero | 0 |

Conditions: GB10 c4-code, 12 hidden-test items, run 1 per setting; exact per-row dates not supplied, within the recorded 2026-09-17 to 2026-09-27 window; no cross-setting latency claim.

| Model and setting | Tokens per item mean / median / max | Reasoning tokens per item (mean) | Truncated at cap | Score |
|---|---|---|---|---|
| Qwen3.8-Flash-Next, thinking off | 132 / 91.5 / 453 | 0 | 0 | 95.8 |
| Qwen3.8-Flash-Next, effort requested as `high` through a port that forces a low tier | 398 / 324 / 1,033 | 310 | 0 | 95.8 |
| Qwen3.8-Flash-Next, thinking on, default tier, cap 16,384 | 2,708 / 986 / 12,917 | 2,599 | 0 | 95.8 |
| DeepSeek V4 Flash Vision-Exp, thinking off | 81 / 68.5 / 160 | 0 | 0 | 87.5 |
| DeepSeek V4 Flash Vision-Exp, thinking `high`, cap 16,384 | 3,366 / 648.5 / 16,384 | 3,302 | 2 | 79.2 |

Conditions: Single-node EXL3, six long-coding repositories, one supplementary run with a 1,800 s timeout; exact run date not supplied; protocol median remains 88.9.

| Repository slot | Wall seconds | Output tokens | Hidden tests passed |
|---|---|---|---|
| 1 | 23.8 | 875 | 10 / 10 |
| 2 | 74.2 | 2,657 | 8 / 8 |
| 3 | 25.4 | 969 | 10 / 10 |
| 4 | 26.3 | 962 | 11 / 11 |
| 5 | 392.4 | 12,873 | 11 / 12 |
| 6 | 525.4 | 17,481 | 12 / 12 |

Conditions: Diagnostic mapping for this chapter; fixes describe the intended rule, not universal deployment or historical completion.

| Symptom | Root cause | Fix |
|---|---|---|
| A truncated answer scores full marks | Engine returns unclosed thinking in `content`; grader finds an answer-shaped block in the draft | Score 0 whenever `finish == length`; keep original in a field |
| "10 of 10 identical" for two decoding modes | Both sides were empty strings (the answer sat in the reasoning field, only `content` was stored) | Store both fields; empty on either side is "invalid" |
| Every code item scores 0, rc 1 | Grader dependency missing on a new host | Record grader versions; refuse to run when the grader cannot run |
| "Parallel 2" run behaves like 4 | The pack subprocess had a hard-coded `--parallel 4` | Pass the flag through; assert in a test with a fake subprocess |
| Categories in one run not comparable | Own categories 8,000 tokens, pack categories tool default | Make the budget explicit for all categories |
| Slow generation recorded as a failure | Item timeout reached while the model was still producing | Re-run once with a longer timeout, report both, keep the protocol score |
| Repair tool disagrees with the main grader | Repair tool re-implements a subset of the rules | Import the main grader; never fall back silently |

## Chapter 5: recipes

Context and qualifications: [recipes](recipes.md).

Conditions: Recipe verification: six models, 74 key fields; dates per verification not supplied; 39 official, 24 inferred, 11 refuted, 0 unverifiable.

| Verdict | Count |
|---|---|
| Confirmed official | 39 |
| Confirmed, but the value rests on an inference (source equivalence, neutral value not stated, etc.) | 24 |
| Refuted | 11 |
| Unverifiable | 0 |

Conditions: Six request-changing defects among the 11 refuted fields; the other five changed prose; these are verification findings, not model benchmarks.

| Kind | What it was |
|---|---|
| No-op key | A chat-template flag that the template reads but that does nothing behind the serving layer, because the layer strips the field the flag depends on |
| Echo shape | A "preserve reasoning" flag that, through the serving layer, produced two thinking blocks in a turn (`<think></think><think>` plus the reasoning) |
| Budget | An output budget whose stated source did not say that; the value was a quarter of the vendor's recommendation (the researcher had labelled it inferred; the label was lost when the fact was copied into the recipe) |
| Wrong scenario | A top_p taken from the agentic scenario applied to all categories (the vendor gives 0.95 for agentic use and 1.0 otherwise) |
| Key never read | A `thinking` key the template never reads; sending only it silently produced non-thinking behaviour |
| Missing field | An omitted scenario-dependent field and a 384K output cap |

Conditions: Template-source reading, not a test on vLLM; effective behaviour can depend on the serving layer.

| Template behaviour for an unsupported or unknown value | Effect |
|---|---|
| Accepts only three named tiers (extra-high, medium, low); a value such as `high` or `max` makes the template raise | A serving layer with an alias fallback maps it silently to the top tier; a template-faithful server errors |
| Accepts high / low / no-think; an invalid value is silently changed to no-think with an empty thinking prefill | Thinking silently off |
| Accepts named values that map to numbers (`max` is 0.99, clamped to [0, 0.99]); `xhigh`, the name the vendor documentation uses, is not a name this template knows | A name copied from the wrong vendor's documentation maps to nothing useful; check the template's own table |
| Treats low / high as named and any other value as max | The string "high" is high; omitting it is max |
| Never reads a `thinking` key | The flag is a no-op; sending it alone can switch thinking off |

Conditions: One pruned 3.0 bits-per-weight text-only EXL3 build of a 284B MoE on one GB10 node; vendor-informed A/B are separate single repetitions dated 2026-09-25 / 2026-09-26; control is a two-run median dated 2026-09-26; composite intervention, same bank and grader, no vision.

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

Conditions: Diagnostic mapping for this chapter; fixes describe the intended rule, not universal deployment or historical completion.

| Symptom | Root cause | Fix |
|---|---|---|
| Vendor arm is better on one category only, total flat | Recipe changed several things; only budget-limited or tier-sensitive categories react | Report the arms side by side, with the header "composite intervention" |
| `official` label on a value that was inferred | Evidence label lost when copying research to the recipe | Source gate: `official` needs a hash-bound verification report that names the field |
| Same string, different tier | Templates interpret kwargs differently, a layer between client and template may rewrite or drop them | Send only keys the template source reads; render once offline and read the output |
| Multi-turn loop scores differ by engine | The loop did not echo reasoning back; the serving layer may rewrite what is echoed | Echo `reasoning_content`; verify by offline render, not by prompt tokens |
| Output looks truncated at 8,000 tokens | The harness cap, not the model | Budget = peak reasoning plus answer; record `finish_reason` |
| Verifier and researcher disagree | Either can be wrong | Reconcile against the tool's source and against result files |

## Chapter 6: identity

Context and qualifications: [identity](identity.md).

Conditions: Metadata and switch-log reconstruction: baseline 2026-09-24 at 22:48 local, switch 2026-09-25 at 01:10:48, ready 01:14; no response-level fingerprint retained.

| Evidence | Value |
|---|---|
| Baseline run time | 2026-09-24 22:48 local |
| Model field in the result file | `deepseek-v4-flash-vision-exp` (the shared served alias) |
| Chat kwargs recorded | `enable_thinking: true` (the Qwen family's key; the other model uses `thinking` and `reasoning_effort`) |
| When the pair actually switched to the other model | 2026-09-25 01:10:48 (switch log), ready 01:14, so 2.4 hours after this run |
| Alias note in the decision record | Qwen3.8-Flash-Next under the one-million-token configuration was also served under that alias, so clients saw no change |
| A companion prefill file taken at 01:08 the same night | The file's own label names Qwen3.8-Flash-Next (NVFP4); its model field is the same alias |
| The cutover document that used this run | Treats it as the Qwen3.8-Flash-Next baseline for a quality-parity gate against the same model on another engine, not as a run of the other model |

Conditions: The same mislabeled-baseline comparison; bank hash matches, but grader, budget, thinking control and Python environment differ; opaque placeholders replace hashes and exact environment versions.

| Field | Baseline column run | Single-node arm run |
|---|---|---|
| Bank hash | hash A | hash A (same) |
| Grader version hash | hash G1 | hash G2 (different code) |
| Output budget | 16,384 | 8,000 |
| Thinking control recorded | `enable_thinking: true` (override) | `reasoning_effort: low` (override) |
| Python recorded | environment A | environment B (different Python versions; exact strings withheld) |

Conditions: Diagnostic mapping for this chapter; fixes describe the intended rule, not universal deployment or historical completion.

| Symptom | Root cause | Fix |
|---|---|---|
| Baseline column is a different model | Shared served alias across a swap; no weights identity recorded | Record the served model entry, revision or path, and mode at run start |
| Gate "own mean above baseline" passes against the wrong baseline | Gate keyed on bank only | Same-arm metadata check |
| Two runs not comparable though bank hash equal | Grader version hash, budget, thinking key and Python differ | Compare all listed fields; list intentional differences |
| Partial re-run merges into an older record | Bank hash is computed over the categories run | Keep category lists with the hash |
| "Landed on engine X" claim from a response field | Field present only in a state | Gateway headers; a disjoint-field test only as a cross-check |
| Request says `high`, served low | A port or proxy rewrites the tier | Record the effective tier; check output-length distribution against another tier |

## Chapter 7: isolation

Context and qualifications: [isolation](isolation.md).

Conditions: Production-isolation unit-test cases, not live deployment evidence; unreadable route information is recorded as unverified.

| Case | What prod-gate does |
|---|---|
| Benchmark base URL equals a gateway deployment's base | Exit 3 |
| `localhost.`, `127.0.0.1.`, `127.1`, `2130706433`, `[::ffff:127.0.0.1]`, `[::1]`, `the wildcard bind address` | All recognised as loopback |
| Reason string empty or whitespace | Not accepted as an override |
| Route table unreadable | Warning; `verified: false`; not blocked |
| Route table `200` with `{"data": []}` | Treated as "could not verify", not as zero hits |

Conditions: Diagnostic mapping for this chapter; fixes describe the intended rule, not universal deployment or historical completion.

| Symptom | Root cause | Fix |
|---|---|---|
| Production slowed or its model evicted during a test | Test and production share an engine process or a resident-model slot | Gate on the route table; move production off first |
| Test data disturbed by production requests | Same cause | Dedicated window or a dedicated engine |
| Gate passes for an obvious production address | Address spelling (trailing dot, short IPv4, mapped IPv6, integer) | Canonicalise numerically without DNS |
| Gate passes when asked through the gateway | Compared the gateway's address, not the deployments | Resolve the alias |
| Heavy thinking arm kills a production-fallback engine | Evaluation workload as heavy as the failure trigger | No maximum-effort arms on an engine that carries fallback traffic |

## Chapter 8: usability

Context and qualifications: [usability](usability.md).

Conditions: Stored complete runs on GB10, same 132 items (30 + 12 + 30 + 30 + 30); token counts, not single-stream wall times; per-run dates not supplied within the recorded 2026-09-17 to 2026-09-27 window.

| Model and setting | Output tokens per item: median | p90 (inclusive) | max | Truncated at cap |
|---|---|---|---|---|
| Qwen3.8-Flash-Next, thinking off | 69.5 | 129 | 453 | 0 |
| Qwen3.8-Flash-Next, thinking on, default tier, cap 16,384 | 284.5 | 1,191 | 12,917 | 0 |
| DeepSeek V4 Flash Vision-Exp, thinking off | 45 | 111 | 182 | 0 |
| DeepSeek V4 Flash Vision-Exp, thinking `high`, cap 16,384 | 125.5 | 589 | 16,384 | 2 |

Conditions: Illustrative arithmetic only: token counts divided by published 52.9 / 31.8 tok/s rates from different runs; prefill, queueing and engine-setting differences ignored; not measured latency.

| Model and setting | p90 tokens / published rate | Estimated seconds | Against a 30 s gate |
|---|---|---|---|
| Qwen3.8-Flash-Next, thinking off | 129 / 52.9 | 2.4 | passes |
| Qwen3.8-Flash-Next, thinking on | 1,191 / 52.9 | 22.5 | passes narrowly |
| Qwen3.8-Flash-Next, thinking on, worst item | 12,917 / 52.9 | 244 | far over |
| DeepSeek V4 Flash Vision-Exp, thinking off | 111 / 31.8 | 3.5 | passes |
| DeepSeek V4 Flash Vision-Exp, thinking `high` | 589 / 31.8 | 18.5 | passes |
| DeepSeek V4 Flash Vision-Exp, thinking `high`, cap-hit item | 16,384 / 31.8 | 515 | far over |

Conditions: Diagnostic mapping for this chapter; fixes describe the intended rule, not universal deployment or historical completion.

| Symptom | Root cause | Fix |
|---|---|---|
| A model near the top of quality ranks takes minutes per answer | Rank ignored latency | Preflight usability gate before the full run |
| Gate loosened silently | Threshold set high without a reason | Loosening requires a reason; unreasoned loosening is refused |
| `nan` threshold passes everything | Comparison with nan is false | Validate the threshold is finite and positive |
| Latency estimates differ between runs | Concurrency, recipe tier and cache state differ | Single-stream, recipe tier, fresh prompts |

## Chapter 9: audit

Context and qualifications: [audit](audit.md).

Conditions: Historical final independent adversarial audit after two fix-and-review rounds; 180 passed covers all gate groups, not this repository's tests; exact audit date not supplied.

| Measure | Value |
|---|---|
| Mutants written by the final reviewer for the evaluation gates | 44 |
| Mutants killed by the tests | 41 (1 surviving real gap, 2 equivalent mutants) |
| Final verdict | Fail: 0 high, 0 medium-high, 2 medium, 5 low |
| Overall test run of all gate groups together | `180 passed` under pytest plus script-style tests all returning 0, and every group still failed its final audit |

Conditions: Historical evaluation-gate findings left open at the final audit: 2 medium, 5 low; local repairs do not revise the historical verdict.

| Severity | Finding |
|---|---|
| Medium | The recipe source gate can be defeated by relabelling an inferred field as official: the gate reads only the verification report's "refuted" list, not its "confirmed but inferred" list, so any of the 24 inferred fields could be relabelled and the run recorded as a full vendor arm; the nine tests stayed green. Fix designed: allow-list; `official` only if the report names the field as confirmed official |
| Medium | The production isolation gate does not recognise the host's own LAN address, hostname or tunnel address |
| Low | Deployment script overwrote a host-only file without a backup |
| Low | The pinned-patch set missed a second file of one patch |
| Low | `nan` threshold bypasses the usability gate |
| Low | A driver stopped production before verifying that its patches were still in place |
| Low | One mutant survived because a whitespace-reason case was tested only on one path |

Conditions: Diagnostic mapping for this chapter; fixes describe the intended rule, not universal deployment or historical completion.

| Symptom | Root cause | Fix |
|---|---|---|
| Tests all green, audit fails | Tests encode the incident, not the class | Mutation plus incident-shaped new cases written by someone else |
| Gate bypass by relabelling | Gate trusts a label | Allow-list: positive evidence per field |
| Gate bypass by address spelling | String match on addresses | Canonicalise numerically, compare against local interfaces |
| Gate not on the host that runs the bake-off | Deployment step skipped | Deployment as a tested script with a backup step |

## Historical defect-to-gate map

Status words: **built** = exists in our private harness or scripts; **tested** = has a unit test that passed; **open** = known gap at the time the notes were frozen; **specified** = written down, not implemented.

| Defect | Gate | Chapter | Status |
|---|---|---|---|
| Fake prefill from prefix cache | Seed from `(n, i)`, per-pass nonce, server token counts, drop first pass | 2 | Built in the benchmark script; the streaming probe still seeds only from `(n, i)` (open); no unit test |
| Nominal-size denominator | Divide by `usage.prompt_tokens` | 2 | Built in the benchmark script; the streaming probe still divides by the nominal size (open) |
| Heartbeat taken as first token | Skip keepalive and empty-delta chunks | 2 | Built in the streaming probe; no unit test; stub sketch tested during fact gathering |
| Deltas counted as tokens | Use `usage.completion_tokens` | 2 | Built in the stress script (single-node cookbook material); stub-free |
| Missing key on a request path | Key on every path, fake-subprocess test | 3 | Built; tested for the pack command only, not for the coding loop |
| HTTP 200 without `choices` | `choices` required | 3 | Built in the preflight; open in the long-horizon coding loop |
| Socket timeout defeated by heartbeat bytes | Wall-clock deadline in a daemon thread, restart the engine after it | 3 | Built in the preflight and drivers; restart path test coverage not verified |
| Listed model not servable | Real request in the preflight, engine restart per model | 3 | Built in the drivers |
| Engine fell back to a default context window | Verify effective window; restart after config edits | 3 | Built only in a retired driver; open in the current ones |
| Capacity abort then 409 chain | Concurrency 1 for long categories; capacity-limited list | 3 | Built as a driver default; no capacity-estimate gate (specified) |
| Dead engine, saved run | Non-zero exit when a category has no score; no median over error rows | 3 | Partial (no-score categories only); the rest specified |
| Tool markup in `content`, text-only model asked about an image | Tool-call and image-token pass criteria | 3 | Specified, not built |
| Truncated answer credited | Score 0 on `finish=length`; scan; regrade from raw | 4 | Built; the public harness port carries a test, the private harness had none for this rule |
| Empty-versus-empty equality | `greedy_compare.py` marks invalid | 4 | Built |
| Missing grader dependency scores 0 | Record grader versions; refuse to run | 4 | Recorded; refusal specified |
| Pack concurrency, return code, timeout, budget | Fixes in the pack runner | 4 | Built; partly tested (key, budget and sampling in the private harness; the public port tests more) |
| Strict position matching biases against thinking models | None | 4 | Open (unmeasured) |
| Ranking rule changed after the data | Frozen rule file hashed at first run | 4, 6 | Specified |
| Timeout counted as ability | Re-run once with a longer limit, report both | 4 | Procedure |
| Uniform recipe taken as fair | Recipe gate, arm names | 5 | Built; tested |
| Inferred field labelled official | Hash-bound verification report, per-field allow-list | 5 | Built; tested; bypass open (relabelling) |
| Reasoning echo not reaching the template | Offline render check | 5 | Built; tested with strings; never run with a real tokenizer on the evaluation host |
| Alias is not the weights; unlike arms compared | Same-arm check; identity recorded at run start | 6 | Specified; sketch tested |
| Route evidence from an absent field | Gateway response headers | 6 | Procedure |
| Benchmark on a production endpoint | Route-table gate with canonical hosts | 7 | Built; tested; LAN-address bypass open |
| Unusable model ranked | Five-question usability preflight | 8 | Built; tested; `nan` bypass open; never used on a live bake-off |
