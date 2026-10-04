# Do not benchmark on the endpoint that serves traffic

[Book](../README.md) | [All tables](results.md) | [Pitfalls](pitfalls.md)

### Problem

A benchmark that shares an endpoint, an engine process or a host with production traffic contaminates both: the production endpoint is slowed or evicted, and the benchmark is interrupted or throttled by production requests. On engine B, which keeps one model resident, loading the model under test evicted the production model every time; per-swap cost and the length of the disturbance are not given here. On GB10, the second contamination mode is shown: an evaluation arm that is heavy enough to kill the engine while the engine is also the production fallback.

### What we built or changed

`prod_gate.py` (stdlib):

1. Canonicalise the benchmark's host before comparing: strip a trailing dot, treat `localhost`, `*.localhost`, `127.0.0.0/8`, `::1`, `the wildcard bind address`, the integer form `2130706433`, the short form `127.1` and the mapped form `::ffff:127.0.0.1` as one loopback identity, without DNS.
2. Ask the gateway for its route table (`/model/info` on LiteLLM) and compare the benchmark's host and port with the API base of every deployment. A match exits with code 3. Allowed only with an explicit reason, written into the result file; a reason made of whitespace does not count.
3. If the benchmark goes through the gateway itself, resolve the alias to its deployments first; refuse if that cannot be done.
4. If the route table cannot be read, or it answers 200 with an empty `data` list or an error object, the check does not claim "zero hits": it records `verified: false` and prints a warning, and does not block. (Fail-open with a record; a design choice that audit flagged.)
5. The gate runs at the top of the runner, before any request and before the result directory is created, and in every driver's preamble.

Built, but dropped from the shipped version because it depends on one host's service manager and a credentials file: a second check that exits 3 when the production service is loaded in the host's service manager and the benchmark targets its port. Specified and not built: a host-health watchdog (free memory and database readiness) that pauses a run when the shared host is starved.

### Procedure as actually run

The gate was written from the original incident and then reviewed twice by an independent adversarial pass (mutation plus new cases built from the original incident). Tests use fake route tables and a fake service-manager command, no sockets.

### Results

GB10, 2026-09-25 (local time 03:39:50 to 03:44:44; the engine log is in UTC, 08:39:50 to 08:44:44): a maximum-effort thinking evaluation arm (maximum effort, 32,768 output tokens, two parallel requests) was running on the two-node engine that was also the production fallback tier. Throughput went to 0 at 03:39:50, a once-per-minute shared-memory warning followed, and at 03:44:44 an RPC timeout killed the engine core. The container stayed "Up" with 96 % GPU use. The same arm with thinking off had run about 2.3 hours without an error. An earlier death on 2026-09-19 occurred during a thinking-mode evaluation on the same engine (chapter 3 table). The decision record closed the evaluation without re-running the max arm on the production fallback engine, reported the non-thinking arm (two runs: own 87.0, pack 77.8) plus the valid portion of the max arm (c1 93.3, c2 90.0, c3 60.0, c4 10 of 12 items), and wrote "the vendor max recipe kills the engine on this stack" as the main result. Full log and workload details are in the linked stack cookbook; do not repeat them.

| Case | What prod-gate does |
|---|---|
| Benchmark base URL equals a gateway deployment's base | Exit 3 |
| `localhost.`, `127.0.0.1.`, `127.1`, `2130706433`, `[::ffff:127.0.0.1]`, `[::1]`, `the wildcard bind address` | All recognised as loopback |
| Reason string empty or whitespace | Not accepted as an override |
| Route table unreadable | Warning; `verified: false`; not blocked |
| Route table `200` with `{"data": []}` | Treated as "could not verify", not as zero hits |

Known bypasses left open at the final audit: the machine's own LAN address, its hostname, tunnel addresses and cross-host addresses to the production port are not recognised as the same endpoint.

### What did not work

- A rule written in notes that experiments do not run on production. It existed; the benchmark ran on the production endpoint anyway because the endpoint became production after the plan was written.
- Matching on the gateway address. Through a gateway the deployments behind the alias are what must be compared.
- Treating a container's "Up" status or `/health` as an engine liveness signal.

### Pitfalls

| Symptom | Root cause | Fix |
|---|---|---|
| Production slowed or its model evicted during a test | Test and production share an engine process or a resident-model slot | Gate on the route table; move production off first |
| Test data disturbed by production requests | Same cause | Dedicated window or a dedicated engine |
| Gate passes for an obvious production address | Address spelling (trailing dot, short IPv4, mapped IPv6, integer) | Canonicalise numerically without DNS |
| Gate passes when asked through the gateway | Compared the gateway's address, not the deployments | Resolve the alias |
| Heavy thinking arm kills a production-fallback engine | Evaluation workload as heavy as the failure trigger | No maximum-effort arms on an engine that carries fallback traffic |

### The rule

A benchmark never runs on an endpoint, or an engine process, that a gateway route points at, unless a written reason says so and is recorded in the result. A workload known to kill the engine does not run where a production fallback shares that engine.

Stub tests: a fake route table with the benchmark's host as one deployment (exit 3); the same host spelled seven ways; a table that answers 200 with an empty list (must record `verified: false`).

## Public implementation boundary

The public gate retains the documented fail-open record for unreadable or empty route tables when checking a direct endpoint. An unresolved gateway alias is refused. Host-service-manager checks and credential-file discovery are removed. No LAN-interface discovery is added; the historical address-alias gap remains. Fixtures use loopback endpoints only.
