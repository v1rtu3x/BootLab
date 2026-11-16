# Findings policy

[Project overview](../README.md) · [Visual walkthrough](../WALKTHROUGH.md) · [Documentation map](README.md)

**A security finding needs observed behavior that violates a stated invariant under a recorded configuration.** A red test is a starting point for investigation; a green test has the scope of its backend and oracle.

## 01 / Classify the observation

| Observation | Classification | Evidence needed |
|---|---|---|
| Unauthorized image accepted by a verifier | Potential verification failure | Exact bytes, selected key, return code, stdout/stderr |
| Unauthorized image executes in the simulator | Potential modeled boot-policy violation | Runtime test, features, resulting image/state, logs |
| Malformed input raises a verifier traceback | Host parser robustness failure | Reproducer, exception, tool revision; no implied device bypass |
| Intended downgrade allowed with policy disabled | Expected control behavior | Disabled feature configuration and case expectation |
| Backend missing, timed out, or failed to start | Harness/infrastructure problem | Tool availability, build output, adapter error |
| Recovery or trailer checks fail | Potential modeled recovery failure | Fault index, reachable operation count, final-state checks |

The adapter marks selected execution failures as `infrastructure_error`. Compilation failures and every other environmental problem are not necessarily classified automatically; inspect the raw logs before labeling a failed case a vulnerability.

## 02 / Follow the evidence

```mermaid
flowchart LR
    O["Unexpected result"] --> R["Reproduce same inputs"]
    R --> C["Classify backend + failure"]
    C --> I["Compare with invariant"]
    I --> P["Report scoped impact"]
    classDef step fill:#12354e,color:#f4f1e8,stroke:#e7b26b;
    class O,R,C,I,P step;
```

1. Preserve the scenario YAML, explicit backend arguments, corpus manifest, and failing bytes before rerunning.
2. Keep `record.json`, `stdout.txt`, and `stderr.txt` from the same run, plus toolchain details and local vendor changes.
3. Repeat the exact command and state whether the result is deterministic.
4. Describe what was observed, what was expected, and which layer was affected.
5. Separate demonstrated impact from hypotheses requiring another test or a physical device.

## 03 / Interpret a pass carefully

The oracle accepts only recognized validation-error output as a clean `imgtool verify` rejection. Tracebacks, invocation errors, timeouts, missing tools, and ambiguous nonzero exits are errors. `fuzz-image` uses the same rejection patterns and records accepted, rejected, crash, timeout, and execution-error outcomes.

Proxy cases remain limited to upstream fixture assertions; K01–K03 do not modify a device trust store. Direct D06 and the fault sweep require explicit reached markers before a positive-index result can pass. These are [coverage limits](LIMITATIONS.md), not findings established by the documentation.

## 04 / Share a reviewable report

Generate `bootlab sanitize-report` after completing the run, then review its contents and any attachments. The sanitizer renders a reduced report; it does not sanitize arbitrary logs, reproducer files, or the entire evidence directory. Avoid publishing private signing material.

Record any upstream issue or PR URL only after it exists. Local report preparation and upstream submission are separate states.
