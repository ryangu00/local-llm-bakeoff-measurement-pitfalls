# Public scripts and reproduction boundaries

The scripts in this book are diagnostic extracts and adaptations. They do not include the evaluation runner or the private question bank. All fixtures are synthetic, including their model names, identity strings, timings, counts and answer text. None of their output is a measured model result.

Use bash 3.2 or newer, Python 3.10 or newer. The core scripts and tests use only the standard library. A real offline template render additionally needs an already installed Transformers package and local tokenizer files. The banner template requires Pillow if it is rendered later; it was not executed for this book.

## Source-to-file map

| Supplied component | Public file | Adaptation |
|---|---|---|
| Truncation-credit scan | `scripts/trunc_credit_scan.py` | Runs root and directory glob are arguments; English JSON output; original score arithmetic retained; all numbered raw-run files considered |
| Greedy comparison | `scripts/greedy_compare.py` | Both reasoning and content retained; empty or unequal sample lists invalid; first-divergence index retained |
| Non-streaming speed benchmark | `scripts/speed_bench.py` | Private statistics removed; output defaults to current directory; fresh leading nonce for every measurement request, including repeated invocations; greedy input stays identical |
| Streaming shell probe | `scripts/prefill_ttft.py` | Python rewrite; explicit endpoint/model/key environment-variable name; historical seed, nominal denominator, heartbeat skipping and drop-first median retained |
| Preflight extract | `scripts/preflight.py` | Deadline, HTTPError body, choices requirement and usability retained; finite-positive threshold, tool-call and image-token checks added |
| Production gate | `scripts/prod_gate.py` | Numeric host canonicalization and route-table logic retained; no service-manager or credential-file access; key only from an explicitly named environment variable |
| Recipe probe | `scripts/recipe_probe.py` | String checks and two-tool-turn history retained; optional local Transformers rendering; separately supplied serving-layer rendering required |
| Runner source-gate extract | `scripts/recipe_source_gate.py` | Research root is an argument; exact model heading; hash-bound verification; positive per-field allow-list; arm naming only, no runner |
| Run-summary script | `scripts/check_run.py` | Explicit run directory; English error/truncation/revoked-credit summaries; reads, never repairs scores |
| Same-arm sketch | `scripts/check_same_arm.py` | New implementation of the field list; named intentional differences printed; missing identity cannot silently match |
| Reference server sketches | `scripts/stub_server.py` | New loopback-only server with authentication, dribble, hang, truncation and SSE cases |
| Original gate tests | `tests/test_offline.py` | Rewritten against public modules and synthetic fixtures; no original environment or incident routes |
| Socket-free test adapter | `tests/memory_transport.py` | Runs the same stub handler through queues; does not validate socket framing or operating-system timeout behaviour |
| Example recipe | `configs/Qwen3.8-Flash-Next-1M.json` | Short supplied model-card quotes and URLs only; inferred fields labelled; verification reference is a placeholder |

The optional raw-body re-grader is omitted. Its correct implementation must import the actual harness grader, read the complete raw HTTP body, apply the shared truncation rule and report parsing failure without falling back to a shortened answer. The public grader import interface was not supplied; duplicating the private grader here would defeat the shared-code-path requirement.

## Run the offline suite

From the repository root:

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests -q
```

The default suite uses file route tables, fake request functions and an in-memory transport around the real stub handler. Temporary files are created and removed inside this repository. It does not contact any external endpoint, read credentials or download models.

The memory transport models a timeout for each wait for bytes. A dribble response remains active longer than that timeout, whereas a daemon-thread wall deadline abandons its wait. This is a test of the client and handler logic. It is not proof of real socket behaviour. The historical socket experiment is separately described in [transport](transport.md).

Where local socket binding is permitted, select the same transport tests against an actual loopback server:

```bash
RUN_LOOPBACK_TESTS=1 PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests -q
```

This path was not completed in the writing environment: loopback binding was denied with `PermissionError: Operation not permitted`. The default mock suite is the executed validation path. An optional socket run must not be reported as passed on that basis.

## Inspect the synthetic failures

```bash
python3 scripts/trunc_credit_scan.py fixtures/runs
python3 scripts/check_run.py fixtures/runs/synthetic
python3 scripts/greedy_compare.py fixtures/greedy-equal-a.json fixtures/greedy-equal-b.json
python3 scripts/greedy_compare.py fixtures/greedy-empty.json fixtures/greedy-empty.json
python3 scripts/check_same_arm.py fixtures/arm-a.json fixtures/arm-b.json
python3 scripts/check_same_arm.py fixtures/arm-a.json fixtures/arm-b.json --intentional grader_version
```

The scan flags credited truncation. The run summary lists the category with a synthetic error. Greedy equality exits successfully; empty equality exits with code 2. The unequal grader hashes cause the same-arm check to exit nonzero; naming that field intentionally prints a note and permits the comparison. These are expected refusals, not failing tests.

The same-arm contract compares `bank_hash`, `grader_version`, `grader_env`, `recipe_arm`, `sampling`, `chat_template_kwargs`, `max_tokens`, `system`, `thinking` and `served_identity`. It cannot discover the actual weights. Capture the server's model entry, reported revision or model path, engine mode and timestamp at run start. Keep category lists alongside bank hashes when merging partial reruns.

## Route tables without sockets

The files under `fixtures/route-table/model/info` and `fixtures/empty-route-table/model/info` are synthetic LiteLLM-shaped responses. Use a local file URI:

```bash
python3 scripts/prod_gate.py --base-url http://127.0.0.1:8000/v1 \
  --litellm-url "file://$PWD/fixtures/route-table"
python3 scripts/prod_gate.py --base-url http://127.0.0.1:8000/v1 \
  --litellm-url "file://$PWD/fixtures/route-table" \
  --allow-shared-prod "dedicated evaluation window"
python3 scripts/prod_gate.py --base-url http://127.0.0.1:8000/v1 \
  --litellm-url "file://$PWD/fixtures/empty-route-table"
```

The first command exits 3. The second records a shared endpoint and the reason. The third warns and records `verified: false`; the historical direct-endpoint policy is fail-open. An unresolved gateway alias is refused instead. Use `--via-gateway` when gateway identity cannot be inferred from the configured URLs. There is no DNS lookup or local-interface inventory, so hostname, LAN and tunnel equivalence remains unproved. No command stops a production service.

## Source evidence and recipe arms

```bash
python3 scripts/recipe_source_gate.py --model Qwen3.8-Flash-Next-1M \
  --recipe configs/Qwen3.8-Flash-Next-1M.json
python3 scripts/recipe_source_gate.py --model synthetic-model \
  --recipe-arm harness-uniform --reason "uniform control arm"
```

The example resolves to `vendor-informed`. It is not a deployable proof of official settings. The model-card quotations were present in the supplied source record; no web verification was performed for this book. The model's name does not establish its served weights or context window.

For a verified recipe, set `--research-root` to a directory you control and use `verified_by: "VERIFY-example.md sha256:<report-hash-prefix>"`. The prefix must contain at least 12 hexadecimal characters and match the actual report. The resolved path must stay under that root, including through symlinks. Use this report format with an exact model heading:

```markdown
## synthetic-model

**Confirmed official**
1. `sampling.temperature`
2. `sampling.top_p`

**Confirmed but inferred**
1. `max_tokens`

**Refuted**
1. `chat_kwargs.unsupported_flag`
```

Every field labelled official must be explicitly present in the confirmed-official list and absent from the inferred/refuted lists. A matching file hash proves the report has not changed; it does not prove the report is true or independently authored. Report trust is still an input to the gate. The check validates verdict labels, not arbitrary natural-language evidence or a new value substituted for an already listed field.

The resolver performs no writes. Integrators must call it before creating a run directory. Missing recipes fail unless an explicitly reasoned `harness-uniform` arm is selected. Vendor overrides are labelled `vendor-overridden`; non-official fields and verification problems remain visible in the returned record. The system prompt is included in the extracted gate's required source fields so an unverified system change cannot silently become official.

## Render shape without tokenizer files

```bash
python3 scripts/recipe_probe.py --rendered fixtures/render-good.txt --official fixtures/render-good.txt
python3 scripts/recipe_probe.py --rendered fixtures/render-double.txt --official fixtures/render-good.txt
```

The first passes; the second fails. Both assistant tool-call turns follow the sole user message. Each segment must have exactly one nonempty thinking block, its reasoning marker, and byte equality with the reference segment. A larger prompt token count alone does not prove that shape.

For a real tokenizer, use `--model-dir` with local files and `--rendered` with the serving layer's rendering of `history()`. The optional path calls `AutoTokenizer.from_pretrained(..., local_files_only=True, trust_remote_code=False)` and `apply_chat_template`; it does not discover an engine installation or download anything. How to obtain an equivalent rendered prompt from vLLM is unverified. Missing tokenizer or serving-layer evidence produces `SKIPPED`, which does not pass the public probe. The original probe relied on a driver to block skipped rendering; this standalone adaptation makes that boundary explicit.

## Optional loopback demonstration

Start the synthetic server in a separate terminal, only where binding is permitted:

```bash
python3 scripts/stub_server.py --port 8000
```

Then run:

```bash
python3 scripts/speed_bench.py --base-url http://127.0.0.1:8000/v1 \
  --model synthetic-model --label synthetic --out results-synthetic
python3 scripts/prefill_ttft.py --base-url http://127.0.0.1:8000/v1 --model synthetic-model
python3 scripts/preflight.py --base-url http://127.0.0.1:8000/v1 --usability \
  --tool-payload fixtures/tool-payload.json --image-payload fixtures/image-payload.json
python3 scripts/recipe_probe.py --base-url http://127.0.0.1:8000/v1 \
  --recipe configs/Qwen3.8-Flash-Next-1M.json \
  --rendered fixtures/render-good.txt --official fixtures/render-good.txt
```

These produce synthetic rates and response shapes, never hardware measurements. Stop the stub with Ctrl-C. The image fixture is a local data URI; the stub only models a rise in token counts and cannot establish visual understanding. The tool check requires parsed function calls, not tool-shaped text. Credentials, if needed for a real endpoint, are taken only from an environment variable explicitly named by `--api-key-env`; no file discovery is performed.

The streaming probe retains the historical nominal denominator and repeated `(tier, pass)` prompts. Use its output to inspect the timing mechanism, not as an automatically corrected usage-based throughput number. Non-streaming speed output includes server counts and elapsed time, so rates can be checked directly. Its wall duration includes more than prefill; it is an approximation to TTFT at `max_tokens=1`.

## Harness integration test pattern

The evaluation harness belongs in `ryanai-evalbank`. Its 2026-10 update receives authentication, truncation and recipe-gate fixes, including the related pack concurrency and recipe handling described by this book. The live repository state was not checked. No runner code is duplicated here.

Adapt the supplied fake-subprocess pattern in that repository's own `test_run_gate.py`, against its actual API:

1. Replace the harness's `subprocess.run` with a recorder returning a nonzero `CompletedProcess`; never start the pack tool.
2. Call the pack path with an explicitly supplied fixture credential, parallel 2, output budget 32,768 and the recipe's sampling.
3. Inspect the captured argument vector: `--api-key` carries the fixture value; `--parallel` carries 2; decoded `--backend-kwargs` includes the explicit budget and sampling.
4. Repeat without an explicit recipe/flag budget and check the documented default behaviour separately.
5. Simulate nonzero return and category timeout; neither may become a numeric model score.
6. Invoke configuration resolution with no recipe and with a whitespace-only control reason; both must fail before output-directory creation.
7. Re-test the coding-loop request path separately: a passing pack subprocess test cannot prove its Authorization header exists.

The harness source and public import interface were not supplied. This repository therefore tests the extracted configuration resolver and documents the integration contract; it does not claim to have modified or tested that other repository. A frozen ranking-rule file, incomplete-run median refusal, missing-grader refusal, lenient pack re-score, host watchdog and automatic engine restart remain separate work.
