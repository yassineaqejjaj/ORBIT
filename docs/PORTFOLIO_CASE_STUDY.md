# ORBIT | Engineering case study

> **Project status:** public beta / technical demonstration. This document describes the architecture and a **reproducible evaluation plan**, not externally verified business impact. Metrics below are proposed measurements, **not achieved results**.

## The problem

AI agents often use stale or conflicting documents, exceed context budgets, or retrieve information outside a person's access rights.

## The solution

A governed retrieval/memory layer with versioned decisions, provenance, classification and ACLs, freshness handling, hybrid retrieval and selectable token budgets.

## System flow

```text
Documents and change events → ingestion → memory and hybrid search → permissions/freshness checks → ranked context → cited output and trace.
```

## What is available to inspect

[Synthetic Atlas dataset and guided demo](DEMO.md) · [Architecture](ARCHITECTURE.md) · [Features](FEATURES.md) · [CI](https://github.com/yassineaqejjaj/ORBIT/actions/workflows/ci.yml).

## A concrete, reproducible demo

Use the fictional Nordalis/Atlas project from docs/DEMO.md: a native app decision is replaced by a PWA decision, a specification has multiple versions, 650 and 720 workspace counts conflict, and a C3 budget must be excluded for less-cleared users. Compare context results between a permitted Product Owner and a lower-cleared user.

## Evidence protocol

Declare relevance judgments and ACL expectations before running. Measure precision@k or recall@k on a labeled synthetic query set, stale/superseded inclusion rate, unauthorized-source exposure (target zero), number of prompt tokens and p95 latency. Compare with a transparent baseline without claims of measured savings until executed.

To make a claim credible, record the repository commit, environment, dataset version, exact prompts/inputs, configuration, baseline, number of runs, test results, raw observations, and reviewer decision. Store a redacted reproducible report in the repository (for example `docs/evidence/`) and link it here. If the measurements have not been performed, write **Not measured**.

| Measure | Baseline | Candidate | Method | Verified result |
|---|---|---|---|---|
| Quality / task success | To define | To define | Fixed evaluation set and human-reviewed criteria | Not measured |
| Safety / critical failures | To define | To define | Severity-weighted fixed scenarios | Not measured |
| Resource use | To define | To define | Token and runtime logs, same workload | Not measured |
| End-to-end latency | To define | To define | Repeated runs, median and p95 | Not measured |

## Limitations and honest disclosure

The Atlas corpus, user identities and confidential labels are synthetic. Token savings, answer quality and isolation must be tested with the same budget and ground truth before being presented as results.

## Five-minute recorded walkthrough

1. **0:00–0:30 — Context.** Explain the user problem and intended scope.
2. **0:30–1:15 — Architecture.** Walk through the principal services and what each owns.
3. **1:15–3:15 — Workflow.** Run the concrete synthetic demo above, showing actual UI and results.
4. **3:15–4:15 — Evidence.** Show relevant trace, test, or comparison; distinguish mock and real providers.
5. **4:15–5:00 — Limits.** Name known constraints and the next experiment.

**Recording checklist:** no live secrets, tokens, proprietary client data, personal health data or real student data; visually label synthetic content; keep a link to the exact code commit and test run used.

---

[Back to repository](../README.md)
