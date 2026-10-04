# Triage before ranking: three signals and five pre-comparison checks

[Book](../README.md) | [All tables](results.md) | [Pitfalls](pitfalls.md)

### Problem

A first scorecard from a new run contained three numbers that were each wrong, two of them in opposite directions: a prefill rate that was twelve and a half times too high, a coding category that scored near zero with errors in its per-item records, and a long-context category that scored near zero because the engine silently applied a 32,768-token window. Had they gone out, hardware and routing decisions would have been made on all three. None was a model property.

### What we built or changed

A triage rule and a pre-comparison checklist. They are procedure, not code, but each line maps to a gate in later chapters.

The three signals. Treat the pipeline as guilty until the raw records clear it when any of these holds:

1. `errors > 0` in any category, even if the score "looks fine".
2. One category sits far below the same model's other categories.
3. A number is too good to be true (absolute throughput above anything the hardware can do; a category near 100 on a model that should struggle).

Where to look first, in order:

1. The per-item records of the run (`raw/<category>-run<k>.jsonl` in the harness). The runner's summary table did not print the `error` field; the per-item record did.
2. The server log for the same minute. The client error text is often useless: Python's `urllib.error.HTTPError` does not carry the response body unless the code calls `e.read()`, so "HTTP Error 400: Bad Request" tells you nothing, while the server log said the prompt exceeded a 32,768-token window.
3. Only then the model.

The five checks before comparing any two models, written as one line each in the planning file of the comparison:

1. Where does the engine put truncated thinking: in `reasoning_content` or in `content`?
2. Is every object you compare for equality non-empty?
3. What thinking tier does each model's chat template actually apply to the string you send?
4. Does any long input exceed the capacity of the local machine or the context window the engine really applies?
5. Is each model run with its own vendor recipe (sampling, thinking tier, output budget, multi-turn reasoning echo), or is the run explicitly labelled a uniform control arm?

### Procedure as actually run

During the bake-off the signal fired three times in the first hours (the three numbers above), and each was traced by reading the raw per-item error field, then the server log, then the harness source for the request path. The checklist was written afterwards from the incidents; it was not applied beforehand, which is the point of the book.

### Results

| Wrong number | What it really was | How it was found |
|---|---|---|
| Prefill 64K at 28,894 tok/s on two GB10 nodes | Cache read, not prefill. True value at the same nominal size 2,318 tok/s in the same harness, 12.5 times lower (28,894 / 2,318); about 2,725 tok/s once server token counts replace the nominal size | Absolute value far above the other tiers; fixed seed in the generator; see chapter 2 |
| A coding category near zero with errors in its per-item records | Every request in one code path was rejected: no `Authorization` header | Per-item `error` field and server log line `401: API key required` |
| A long-context category near zero | Engine read the context length from one config field, did not find it, fell back to 32,768 | Server log: prompt N tokens exceeds max context window of 32768 |

Ledger of measurement defects in that bake-off: 21 items were classed as measurement defects (scoring, timing, harness arithmetic). When the ledger was frozen, 11 of the 21 had a mechanical guard, 2 had only a written note, 8 had nothing.

### What did not work

- A single written rule ("errors above zero means check the pipeline") was in our notes before the second and third incident of the same family. Notes did not stop recurrence. The same missing-authentication defect came back in a second code path (chapter 3) and the same heartbeat defect came back three times in three places (chapters 2 and 3).
- Reading only the summary table. It showed scores, not errors.

### Pitfalls

| Symptom | Root cause | Fix |
|---|---|---|
| "HTTP Error 400: Bad Request" with no reason | `urllib` raises `HTTPError` without reading the body | In the harness call `e.read()` and keep the first 400 characters in the record |
| Category score looks plausible but one run is wrong | Median over runs includes a run of error rows scored as zero | See chapter 3: refuse a median over any run that contains errors |
| Cause is attributed to the model first | No rule says where to look first | The three-signal rule, with the raw record as first reading |

### The rule

Any category with errors above zero, any category far below its siblings, and any number that is too good to be true is read in the raw records and the server log before it is read as a result. Write the five comparison checks into the plan of every comparison.

## Public implementation boundary

The incident checklist is historical. The synthetic run in `fixtures/runs/` exercises the scanner and error summary; it does not reproduce the private questions or scores.
