# EU Cyber Resilience Act — evidence worksheet

[Project overview](../../README.md) · [Visual walkthrough](../../WALKTHROUGH.md) · [Documentation map](../README.md#assurance-mappings)

The Cyber Resilience Act is **Regulation (EU) 2024/2847**. Use the [official EUR-Lex text](https://eur-lex.europa.eu/eli/reg/2024/2847/oj) for the legal requirements and the version applicable to the product. This page supplies a BootLab engineering worksheet; it does not decide product applicability or conformity.

## 01 / Connect a product requirement to a test

```text
product requirement -> security question -> actual experiment -> reviewed evidence
       clause             scenario intent        observation        scoped conclusion
```

## 02 / Candidate engineering topics

| Product topic to assess | Useful BootLab material | Boundary to carry into the review |
|---|---|---|
| Integrity of update bytes | S01, S03, A05, A06 | Host verifier outcomes; no transport or device trace |
| Authenticity of candidate images | S02, S06, A07, A08 | Separate offline key checks from simulator runtime assertions |
| Malformed-input handling | S04, S05, fuzz reproducers | A verifier crash is different from clean rejection |
| Update and trial behavior | P02, P03, P04; mode-specific checks | Shared upstream proxies; overwrite baseline helpers may skip |
| Product version policy | V01, V02 | Enabled-policy upstream check exists; disabled helper does not exercise acceptance |
| Recovery after interruption | F02, F03, F04, F02O | Confirm a cut was reached; no physical-power evidence |
| Reviewable records | Records, logs, manifests, optional signatures | Record signatures do not cover referenced log contents |

BootLab does not evaluate update distribution, support commitments, disclosure/reporting processes, or the complete technical documentation for a product. Keep those work items separate from a successful bootloader experiment.

## 03 / Build a reviewable evidence row

Use a product-owned requirement ID and the exact clause reference selected for the assessment. The subject headings above are engineering topics, not official requirement identifiers.

| Field | Fill in for the product |
|---|---|
| Product requirement | `<requirement ID and testable statement>` |
| Source reference | `<edition/version and exact applicable clause>` |
| Threat / rationale | `<threat ID and reason this check is relevant>` |
| Effective configuration | `<MCUboot revision, local patch, Cargo features or board setup>` |
| Executed case | `<scenario ID, backend, actual test/input>` |
| Retained evidence | `<run archive>/evidence/<id>/record.json`, stdout, stderr, input hashes |
| Observation and limit | `<what happened; what the experiment did not observe>` |
| Review | `<owner, date, conclusion, unresolved work>` |

From `BootLab/`, after preparing the environment and corpus:

```bash
bootlab run-matrix
bootlab sanitize-report
```

Use the resulting records and logs, not the scenario name alone. Read [the test matrix](../TEST_MATRIX.md) and [evidence limitations](../LIMITATIONS.md) before filling in the conclusion. A sanitized summary is a sharing aid; retain the raw experiment in the internal run archive.

## 04 / Interpretation

This worksheet organizes engineering evidence. Passing BootLab scenarios does not establish product compliance, certification, or a complete assessment. The product's scope, applicable requirements, implementation, and other lifecycle evidence need their own review.
