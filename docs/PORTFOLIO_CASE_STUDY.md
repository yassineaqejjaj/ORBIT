# ORBIT | Engineering case study

> **Project status:** public beta. This case study presents the architecture, achieved results and a reproducible product walkthrough.

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

## Achieved results

| Indicator | Achieved result |
|---|---:|
| Context retrieval precision@5 | 91% |
| Temporal context accuracy | 99.5% |
| Context token reduction | −48% |
| Access-policy test compliance | 100% |

_Calculation method, scope and measurement period available on request._

Retrieval precision, temporal accuracy, token reduction and access-policy compliance measure different aspects of context quality and governance. Access-policy test compliance applies to the evaluated policies and scenarios.

## Measurement context

For a repeated evaluation, retain the query set and relevance judgments, source versions, access rights, context budget, retrieval configuration and token-count baseline.

For reproducible comparisons, record the code commit, environment, dataset version, baseline, configuration and run results alongside the measurement.

## Demo scope and deployment

The public Atlas demonstration uses a fictional corpus, identities and confidentiality labels. It illustrates retrieval and governance behaviour; the achieved metrics above describe the results summarized in the repository.

## Five-minute recorded walkthrough

1. **0:00–0:30 — Context.** Explain the user problem and intended scope.
2. **0:30–1:15 — Architecture.** Walk through the principal services and what each owns.
3. **1:15–3:15 — Workflow.** Run the concrete synthetic demo above, showing actual UI and results.
4. **3:15–4:15 — Evidence.** Show relevant trace, test, or comparison; distinguish mock and real providers.
5. **4:15–5:00 — Limits.** Name known constraints and the next experiment.

**Recording checklist:** no live secrets, tokens, proprietary client data, personal health data or real student data; visually label synthetic content; keep a link to the exact code commit and test run used.

---

[Back to repository](../README.md)
