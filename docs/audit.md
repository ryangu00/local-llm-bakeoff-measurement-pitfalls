# Do the gates work? Mutation results and what still slips through

[Book](../README.md) | [All tables](results.md) | [Pitfalls](pitfalls.md)

### Problem

Gates are software. Unit tests that pass do not show a gate refuses what it should. We reviewed our evaluation gates with an independent adversarial pass: mutate the code, and rebuild each original incident in a new form.

### What we built or changed

A review protocol. For each gate group: implement, then two rounds of "fix, then independent adversarial review", where an independent reviewer writes mutants of the gate and new test cases shaped like the original incident but written differently, and returns a verdict with severity per finding.

### Procedure as actually run

Evaluation-gate group: five gates (production isolation, recipe source, render shape, patch pinning on engine B, usability), each with a script-style test file that prints OK, plus one extra fix. Two fix-and-review rounds after the initial review.

### Results

| Measure | Value |
|---|---|
| Mutants written by the final reviewer for the evaluation gates | 44 |
| Mutants killed by the tests | 41 (1 surviving real gap, 2 equivalent mutants) |
| Final verdict | Fail: 0 high, 0 medium-high, 2 medium, 5 low |
| Overall test run of all gate groups together | `180 passed` under pytest plus script-style tests all returning 0, and every group still failed its final audit |

What still slipped through at the end (evaluation gates only):

| Severity | Finding |
|---|---|
| Medium | The recipe source gate can be defeated by relabelling an inferred field as official: the gate reads only the verification report's "refuted" list, not its "confirmed but inferred" list, so any of the 24 inferred fields could be relabelled and the run recorded as a full vendor arm; the nine tests stayed green. Fix designed: allow-list; `official` only if the report names the field as confirmed official |
| Medium | The production isolation gate does not recognise the host's own LAN address, hostname or tunnel address |
| Low | Deployment script overwrote a host-only file without a backup |
| Low | The pinned-patch set missed a second file of one patch |
| Low | `nan` threshold bypasses the usability gate |
| Low | A driver stopped production before verifying that its patches were still in place |
| Low | One mutant survived because a whitespace-reason case was tested only on one path |

Status at the end of the programme: none of the gates were on the evaluation host. They were exercised by unit tests, by a replay over past runs, and in the case of the recipe gate and the truncation rule, by later runs. The usability gate was never used in anger.

Open measurement defects recorded in the ledger as not fixed: a prefill seed that repeats across invocations; a rule recorded in notes that identical timings mean a cache (refuted above, never retracted in the note); preflight not checking modality or tool parsing; no lenient re-score of pack categories; the coding loop swallowing a response with no `choices` and grading as usual. Plus several siblings of fixed defects (the empty-dict config fallback in two other files, an older driver with the old `trap`).

### What did not work

- "The tests are green" as acceptance.
- Fixing only the spelling in the incident. Reviewer-built new cases (a different bank of relabelled fields, a different spelling of the local host) found what the original-incident tests could not.
- Self-written mutants only: the author's mutants are biased to what the author thought of.

### Pitfalls

| Symptom | Root cause | Fix |
|---|---|---|
| Tests all green, audit fails | Tests encode the incident, not the class | Mutation plus incident-shaped new cases written by someone else |
| Gate bypass by relabelling | Gate trusts a label | Allow-list: positive evidence per field |
| Gate bypass by address spelling | String match on addresses | Canonicalise numerically, compare against local interfaces |
| Gate not on the host that runs the bake-off | Deployment step skipped | Deployment as a tested script with a backup step |

### The rule

A gate is accepted when an adversary has tried to get a bad run through it and failed, not when its own tests pass. Record what still slips through next to the gate.

## Public implementation boundary

The historical final verdict remains FAIL: 2 medium and 5 low findings were open. Local tests of this public adaptation do not replace that independent audit. The source allow-list and finite-threshold repairs are new; the production address-alias gap remains. No live bake-off was run with these gates.
