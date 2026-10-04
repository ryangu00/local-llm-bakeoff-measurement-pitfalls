# Transport, configuration and capacity failures scored as model ability

[Book](../README.md) | [All tables](results.md) | [Pitfalls](pitfalls.md)

### Problem

A request that fails for transport, authentication, configuration or capacity reasons is recorded as a zero. Averages, medians and rankings then treat that zero as ability. We hit at least ten distinct forms. Two have GB10 numbers: an engine death inside a scored run, with a median computed over error rows (this chapter), and a timeout counted as ability (chapter 4). The others are described as mechanisms.

### What we built or changed

Rules and code paths:

1. Every request path sends the key. The harness had two request paths that bypassed one another's fixes: the main chat path and the long-horizon coding loop. The coding loop sent only `Content-Type`. Against an endpoint that requires a key, every request returned 401 and the category scored near zero. The default endpoint of that script was a key-less one, so the defect had never been exercised. Later the pack subprocess lost its `--api-key` for a different reason: a comment was inserted in the middle of a one-line expression and the half of the line after the `#` stopped existing. A stub test now asserts that the pack command line carries the key, the output budget and the sampling.
2. A response is valid only if it contains `choices`. Engine B returns HTTP 200 first (to send a keepalive), and if the request is then aborted by its memory guard the body is an error object without `choices`. A preflight that checked only the status code passed it.
3. A wall-clock deadline, not a socket timeout. If the engine keeps writing heartbeat bytes while it works, `urllib`'s timeout never fires, because the timeout applies to each socket operation and any byte resets it. The deadline is a daemon thread joined with a timeout (default 900 s). Because the client walking away does not stop the server, the driver must also restart the engine after a deadline hit.
4. The preflight sends a real request. `/v1/models` listing a model does not prove it is servable: on engine B a model directory added after start was listed and then returned 404, because the model directory is scanned only at startup.
5. After editing a model's configuration, restart the engine and verify the effective value. Engine B read the context length from one field only; a model without that field fell back to a 32,768 default and rejected long prompts. An earlier fix edited the config but the engine had not been restarted, so the next run failed the same way.
6. Long-input categories run with concurrency 1, and inputs that exceed local capacity are listed as "deployment-capacity-limited", never as a score. On engine B a memory guard aborted one long request and every later request received 409 "busy; unload pending", so the rest of the category failed in a chain.
7. A category is incomplete if any item errored. The runner exits non-zero and does not write a valid median. Built only partially (see below).
8. Preflight pass criteria include a tool-call probe that must return at least one parsed `tool_calls` entry and, for vision, a check that the prompt token count rose when an image was attached. Specified, not built.
9. Config parsing uses `or`, not a default argument: `d.get("text_config", d)` returns the empty dict when the key exists with an empty value, and the fallback never triggers. The same expression existed in three files; only one was fixed at first.

What was and was not built in the private harness: the runner returned a non-zero exit code when a category produced no score at all (for example the pack subprocess failed or timed out) and wrote that run's rows as "run failed". It did not do so for categories graded in-process: a category whose every request failed with 401 or 409 still returned a numeric score of 0.0 and exit code 0. Items 7 (for in-process categories) and 8, and the refusal to write a median over a run that contains error rows, were specified in the post-incident action list and not implemented.

### Procedure as actually run

Triage followed chapter 1: per-item `error` field, then server log, then harness source. The wall-clock deadline and the `choices` check were added to the preflight after a preflight on a very long prompt crawled for a very long time because heartbeat bytes kept the socket timeout from firing, while the engine, working through the prompt in tiny chunks under memory pressure, starved a host shared with other services (the host is not described here).

### Results

First-hand GB10 incident: an engine death inside a scored run (two-node DeepSeek V4 Flash Vision-Exp, thinking on at effort high, 16,384 output cap, two runs, 2026-09-19).

| Category | Run 1 | Run 2 | What run 2 actually was | Median reported |
|---|---|---|---|---|
| c10-sre-ops (30 items) | 80.0 | 0.0 | 30 of 30 items: `Connection refused` (errno 61), no latency recorded | 40.0, spread 80.0 (flagged, not failed) |
| c9-long-coding (6 repos) | 83.3 | 66.7 | 2 of 6: `HTTP Error 500` after 673.1 s and 628.1 s | 75.0, spread 16.7 |
| c4-code (12 items) | 79.2 | 95.8 | 2 items truncated at the 16,384 cap in run 1 | 87.5, spread 16.7 |

The run's own report computed an own-mean of 80.2 including the 40.0. After the engine was restored, c9 and c10 were re-run (two runs each) and merged into a corrected record: c9 [81.25, 83.33] median 82.3, c10 [76.7, 83.3] median 80.0. The re-run of only those two categories carries a different bank hash than the original run, because the bank hash is computed over the categories run; a merge of partial reruns needs that remembered.

The same engine hung under a maximum-effort thinking arm on 2026-09-25 while it was also carrying production fallback traffic; that second death and its log are in the linked stack cookbook. That run also kept writing: after the engine died every remaining item was written as an error row and the run was saved as complete; the valid portion was c1, c2 and c3 run 1 and 10 of 12 c4 items.

### What did not work

- Exit code 0 on a dead engine. The runner wrote error rows and returned success.
- Reading `/health`. It stays 200 while the engine is dead (see the linked cookbook); liveness must be a real generation of a few tokens.
- Treating a median as a summary when one run is error rows. A median of `[80.0, 0.0]` is 40.0 and nothing in the number says why.
- A preflight that checked only HTTP status, then one that checked `choices` but not tool parsing or modality. The tool probe's result was printed but not part of pass; the vision probe's prompt token count was not checked. A text-only model passed a preflight that asked it about an image because the image was dropped and the prompt was tiny. Both gaps were left open (specified, not built).

### Pitfalls

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

### The rule

A run that contains transport, authentication or capacity errors is not a run. Every request path sends the key, every response needs `choices`, every wait has a wall-clock deadline, every category with errors is listed, not scored, and the runner exits non-zero.

Stub tests (implemented here in `scripts/stub_server.py`): a server that returns 401 unless the header is present (the client must read the body to see "API key required"); a server that returns 200 with a whitespace byte every second and then an error body (verified during fact gathering: the client sees HTTP 200 after 6.0 s with a 2 s socket timeout, and the body has no `choices`); a server that answers 200 and never finishes (the wall-clock deadline fires; the server is still working).

## Public implementation boundary

The public `preflight.py` adds the previously missing parsed-tool-call and image-token checks. The latter checks a token-count increase only, not visual correctness. A daemon-thread deadline abandons the client wait; this repository does not restart any engine. Restart and readiness handling remain the caller's responsibility. The full runner is not shipped.
