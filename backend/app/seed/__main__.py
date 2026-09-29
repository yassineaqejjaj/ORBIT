"""Entry point: ``python -m app.seed [--reset] [--api http://localhost:8000]``."""

from app.seed.seed import main

if __name__ == "__main__":
    raise SystemExit(main())
