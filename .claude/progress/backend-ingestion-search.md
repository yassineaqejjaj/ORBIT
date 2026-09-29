# backend-ingestion-search progress (attempt 4) — code complete, integration tests pending infra
## Done
- search/{embeddings,opensearch,hybrid}.py, ingestion/{normalize,importers,pii,classifier,chunker}.py, extractors/*, pipeline.py (complete; lint fixed this run)
- NEW app/ingestion/service.py (DocumentViewer visibility, ingest_content create/version/dedupe, default sources, serialize_summaries, sync_index_metadata)
- routers api/{sources,documents,jobs,search}.py implemented; ruff check+format clean on all owned files; create_app()+openapi OK; SQL compiles (postgres dialect)
- tests/test_ingestion_units.py: 22 passed (no infra)
- tests/test_api_documents.py: 7 integration tests written — NOT RUN (docker daemon down: 5433/9201/6380/8000 unreachable)
## Next
- when infra is up: cd backend && ORBIT_TEST_DATABASE=orbit_test_ingest ORBIT_TEST_INDEX_PREFIX=orbit-test-ingest ORBIT_TEST_VALKEY_URL=redis://localhost:6380/11 uv run pytest -x -q tests/test_api_documents.py
## Known issues
- integration tests unverified against real infra; fix any assertion drift there first
