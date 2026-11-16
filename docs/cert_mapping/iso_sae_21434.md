# ISO/SAE 21434 — evidence worksheet

[Project overview](../../README.md) · [Visual walkthrough](../../WALKTHROUGH.md) · [Documentation map](../README.md#assurance-mappings)

[ISO/SAE 21434:2021](https://www.iso.org/standard/70918.html) addresses cybersecurity engineering for road vehicles. Use the applicable edition and your project's cybersecurity requirements for exact work-product and clause references. This page connects selected BootLab observations to product questions without inventing ISO requirement IDs.

## 01 / Preserve the engineering chain

```text
threat / risk rationale -> product requirement -> test configuration -> observation
          TARA                  traceability          experiment         evidence
```

TARA means threat analysis and risk assessment. A BootLab case can contribute a test observation to that chain; it does not create the product's TARA or validate a vehicle function by itself.

## 02 / Candidate product questions

| Product question | Useful BootLab material | Evidence still needed beyond the current case |
|---|---|---|
| Are modified firmware bytes detected? | S01, S03, A05, A06 | Behavior on the deployed image-verification path |
| Is the expected signer required? | S02, S06, A07, A08 | Product trust-anchor provisioning and configuration |
| Does the intended update workflow operate? | D01, D06; P01–P04 | Direct image selection and modeled recovery; proxy rows remain upstream-fixture evidence |
| Is the version policy enforced? | V01/V02 | Same authenticated v2/v1.5 bytes with refusal/acceptance observed under paired features |
| Does recovery preserve an allowed state? | D06, F02/F03/F04/F02O | Modeled reached interruption; actual board layout and product recovery policy still need evidence |
| Can a signing key change safely? | K01–K03 | Device trust-store transition, reset persistence, and revocation handling |
| Can the experiment be reviewed later? | Record, logs, corpus manifest | Complete run provenance and product requirement traceability |

Treat simulator checks as component-level experiment inputs to the product review. They are not vehicle-level validation or proof of lifecycle process completion.

## 03 / Build a reviewable evidence row

Use a product-owned requirement ID and the exact clause reference selected for the assessment. The subject headings above are engineering topics, not official requirement identifiers.

| Field | Fill in for the product |
|---|---|
| Product requirement | `<requirement ID and testable statement>` |
| Source reference | `<edition/version and exact applicable clause>` |
| Threat / rationale | `<threat ID and reason this check is relevant>` |
| Effective configuration | `<MCUboot revision, local patch, Cargo features or board setup>` |
| Executed case | `<scenario ID, backend, actual test/input>` |
| Retained evidence | `evidence/runs/<run-id>/<id>/record.json`, stdout, stderr, immutable input hashes |
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
