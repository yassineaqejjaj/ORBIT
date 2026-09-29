# Progress — backend-platform-seed-mcp (attempt 4)

## Done
- metrics/MCP code + tests exist (earlier attempts). Non-DB tests pass; DB tests need Postgres :5433
  (docker daemon NOT running during attempt 4 -> DB tests + live seed could not run).
- app/seed/data/** : 16 manifest documents (4 CR, synthèse + TR (header + append), spec v1/v2, inventaire, jira 12,
  crm 5 CSV, beta 8, traces 3, budget C3 role:owner, benchmark J-400 url, RH) + manifest.json
  (users/agents/sources/docs/phases/validations/memory/sessions/30 context requests + feedback + snapshots)
- app/seed/manifest.py : load / render {{J-n}} {{date:J-n}} / validate_manifest()
- app/seed/direct.py : DB/service ops (reset, org long_term memory, expire session, redistribute timestamps)
- app/seed/seed.py + __main__.py : httpx runner (phases 1-3 with worker wait + validations between phases)
- tests/test_seed_data.py (9 tests) + tests/test_seed_data_flow.py (fake API via httpx.MockTransport, 2 tests) PASS
- ruff check/format clean on app/seed

- README.md at repo root DONE (pitch, mermaid, quick start, accounts, MCP JSON, config, security, tests, layout, roadmap)
- CR tables: durations written in words to avoid noisy "fact" extraction of table rows (checked with real extractor)
- tests/test_seed_data.py also checks import files with the real importer (10 tests)

## Next steps
- when docker is up: run DB tests for metrics/MCP (20 tests error only because Postgres :5433 unreachable);
  run `make seed` end-to-end at integration (api image must be rebuilt to contain app/seed)

## Known issues / cross-owner
- backend/.seed-agents.json must be added to root .gitignore (not my file)
- DEMO.md §6 says "15 sources": the seed creates 11 sources (15 table rows / 16 documents, 39 docs incl. records)
