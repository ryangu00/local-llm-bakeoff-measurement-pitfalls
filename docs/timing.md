# Timing and throughput numbers that were never measured

[Book](../README.md) | [All tables](results.md) | [Pitfalls](pitfalls.md)

### Problem

Speed numbers are the easiest to fake by accident. Five different mechanisms produced wrong speed numbers in our runs: a prefix cache, a word-count denominator, a heartbeat treated as the first token, a stream delta counted as a token, and an idle counter that included finished streams. Four were found on GB10 and are shown with GB10 numbers; the heartbeat case was found on engine B and is shown without numbers.

### What we built or changed

1. `speed_bench.py`: a stdlib-only script with these properties. All requests are non-streaming. Token counts always come from the server's `usage.prompt_tokens` and `usage.completion_tokens`, never from a word count. Every measurement pass puts a unique nonce at the very start of the prompt (`[run <nonce>] ...`) so no pass can reuse another pass's cache. The first run of each tier is dropped as cold and the median of the rest is reported. Decode uses a short prompt (about 60 tokens) with a long essay-style output so prefill is under 1 % of the time; prefill uses `max_tokens=1`. Defaults: 4 runs, decode 512 tokens, concurrency 4 and 8, prefill tiers 1,000 / 4,000 / 16,000 / 64,000 tokens, decode sampling temperature 0.6 and top_p 0.95 fixed across arms. The script can also store greedy outputs (temperature 0, top_p 1) with reasoning and content text kept separately.
2. `prefill_ttft.py`: the streaming version. Prompts are built from a 20-word list, `n / 1.3` words for a nominal `n` tokens, from a random generator seeded with `n * 1000 + i` so that lengths and runs never share a prefix. `max_tokens=1`, `temperature=0`, `stream=true`. Four passes per tier, the first dropped, median of three. TTFT is taken at the first data line whose parsed delta has non-empty `content` or `reasoning_content`; chunks whose `model` field is `keepalive`, and the opening chunk that carries only a role, are skipped. Prefill throughput is `n / TTFT`. The public rewrite accepts an endpoint and an optional credential environment-variable name; it performs no host or credential discovery.
3. A rule that the denominator comes from the server: `usage.prompt_tokens`, not the nominal size.

### Procedure as actually run

The first prefill probe on the two-node pair used a fixed generator seed (42). Different lengths therefore shared a prefix, and repeated passes at one length were identical. The engine's prefix caching (on by default in the build we ran, according to our notes; not independently re-checked during fact gathering) made every pass after the first a cache read. After the fix every pass used fresh content.

The corrected measurement, GB10 two nodes, Qwen3.8-Flash-Next NVFP4, tensor parallelism 2, through the proxy port that fixes the thinking tier (irrelevant at `max_tokens=1`), 2026-09-23:

| Nominal tier (words / 1.3) | TTFT median (s) | Three passes (s) | Prefill (tok/s, nominal denominator) |
|---|---|---|---|
| 1,000 | 0.397 | 0.402, 0.397, 0.396 | 2,519 |
| 4,000 | 1.467 | 1.467, 1.467, 1.458 | 2,727 |
| 16,000 | 6.092 | 6.092, 6.085, 6.109 | 2,626 |
| 64,000 | 27.608 | 27.486, 27.756, 27.608 | 2,318 |

The earlier fixed-seed run reported 28,894 tok/s at the 64K tier. The raw output of that run was not kept; the number is recorded in our notes and quoted in two later documents. Ratio 28,894 / 2,318 = 12.5.

A later three-pass measurement on the same pair (2026-09-25, 01:08 local time) used distinct prompts and the server's token counts:

| Pass | Prompt tokens (usage) | TTFT (s) | Prefill (tok/s) |
|---|---|---|---|
| 1 | 63,936 | 23.537 | 2,716.4 |
| 2 | 63,750 | 23.313 | 2,734.5 |
| 3 | 63,836 | 23.437 | 2,723.7 |

The result file records `cached_tokens: null` and a field `suspicious_identical: false`. Our notes list adding the vLLM launch flag `--enable-prompt-tokens-details` as an open to-do on 2026-09-25, so the likely reason for the null is that this server did not report prompt-token details (not verified); the single-node build's stress log does report `prompt_tokens_details.cached_tokens` (0). The script that wrote this file was not found in our repositories; treat the file as a record only.

### Results

Cross-check of the word-count denominator, both on GB10 with the same model: the usage-based run sustained about 2,725 tok/s. At that rate the earlier nominal "64,000" run, which took 27.608 s, held about 75,000 tokens (27.608 s times 2,725 tok/s). The nominal denominator therefore understated throughput by about 15 % (2,318 / 2,725 = 0.85). This is an implied value from two different days and prompts; it is not a direct count of the earlier prompt.

The "three passes agree to the millisecond" heuristic. Our notes recorded a rule that identical timings across passes mean a cache. The corrected, legitimate GB10 passes above agree within 1.5 % at 1,000 tokens (0.402 / 0.397 / 0.396 s) and within 0.6 % at 4,000 tokens (1.467 / 1.467 / 1.458 s). A rule based on millisecond agreement would have flagged valid data. What discriminates is an absolute value no hardware can reach, and the server-reported cached token count.

Delta counting. The single-node EXL3 build was stress-tested for 102 minutes with long generations (log dated 2026-09-26). Counting SSE deltas as tokens under-counts: for nine completed streams the ratio of server-reported completion tokens to deltas was between 2.59 and 2.98. Example: a stream that completed 32,768 tokens delivered 11,726 deltas (2.79 tokens per delta). Per-stream rates computed from usage were 24.5 and 24.6 tok/s for two concurrent streams, 21.4 to 21.8 for three of four (18.6 for the fourth, which stopped early at 13,145 tokens), and 16.3 for the one stream that completed when six ran at once. Computing from deltas would have reported about a third of that.

| Round (concurrency) | Streams completed | Completion tokens (usage) | Deltas | Tokens per delta |
|---|---|---|---|---|
| 2 | 2 | 32,768 and 32,768 | 11,726 and 11,673 | 2.79 and 2.81 |
| 4 | 4 | 32,768 x3 and 13,145 | 11,574, 11,390, 11,680 and 5,074 | 2.83, 2.88, 2.81, 2.59 |
| 6 | 1 completed (five hit the 1,700 s client timeout) | 21,795 | 8,110 | 2.69 |
| 2, second port | 2 | 32,768 and 28,384 | 10,998 and 10,424 | 2.98 and 2.72 |

Heartbeat idle counters. In the same stress log a heartbeat printed an `idle_s` per stream. A stream that had finished normally (`finish=stop`) kept counting idle seconds (16 s, then 136 s, up to 736 s) while the server was healthy and the other streams still produced tokens. An idle counter that does not exclude finished streams reads as a stall. Stall detection should use the server's running-request count, not client idle time.

### What did not work

- Dropping only the first pass and trusting repeats. A cache survives across passes, not just across the first one.
- The millisecond-agreement heuristic (above).
- Fixing the denominator in one script. The streaming probe kept dividing by the nominal size after the other script had moved to server token counts. Chapter 1's sibling sweep applies.
- A seed derived only from `(tier, pass)`: re-running a target replays the same prompts as the previous invocation, so a second invocation can hit a cache left by the first. This was recorded in the ledger as open and never fixed in our scripts. The nonce in `speed_bench.py` closes it for that script only.

### Pitfalls

| Symptom | Root cause | Fix |
|---|---|---|
| Prefill 12.5 times too high | Generator used a fixed seed; engine prefix cache hit on every pass after the first | Seed from `(n, i)` and a per-pass nonce at the start of the prompt; read cached tokens when the server reports them |
| Prefill 15 % low | Denominator is the nominal size (words / 1.3), not the tokenizer's count | Divide by `usage.prompt_tokens` |
| Absurdly high prefill rate from a streaming probe, or a division by zero at the smallest tier | First data line was a heartbeat, so the timer stopped at heartbeat arrival | Skip chunks with `model == "keepalive"` and chunks with empty content and empty reasoning; assert a plausibility bound; or use non-streaming requests with server usage |
| Decode rate a third of the truth | One SSE delta carried 2.6 to 3.0 tokens | Use `usage.completion_tokens` |
| Stall alarm on a healthy server | Idle counter included streams that had finished | Count only unfinished streams; confirm with the server's running-request count |
| Cached-token field is `null` | Server may need a reporting flag (likely here, unverified) | Check the flag; do not read `null` as "no cache hit" |

### The rule

A speed number has three parts that must come from the server or from a nonce: the numerator and the denominator in server token counts, and fresh content in every pass. If any of the three is a client estimate, the number is a guess.

Stub test (no GPU): serve a fake `/v1/chat/completions` that (a) emits an empty chunk with `"model": "keepalive"` before the real first chunk and (b) returns `usage` with a known `prompt_tokens`. The TTFT parser must report the real first-token time, and a probe that divides by nominal size must be seen to differ from the usage-based value.

## Public implementation boundary

The public `speed_bench.py` generates a fresh leading nonce per measurement request and uses usage counts. `prefill_ttft.py` deliberately retains the historical `(n, i)` seed and nominal denominator; its output is explicitly labelled nominal. Its prompts repeat across invocations. The SSE stub isolates heartbeat timing; it is not a GPU benchmark.
