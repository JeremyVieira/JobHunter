# Contributing

Thanks for taking a look. JobHunter is a personal-project-turned-showcase, but fixes and ideas are welcome.

## Set up

```bash
git clone https://github.com/JeremyVieira/JobHunter.git
cd JobHunter
python -m venv .venv && source .venv/bin/activate      # Windows: .venv\Scripts\Activate.ps1
python -m pip install -r jobhunter/requirements.txt pytest pytest-cov ruff
python -m jobhunter demo          # explore with synthetic data
```

## Before opening a pull request

```bash
python -m ruff check .
python -m pytest tests --cov=jobhunter --cov-fail-under=80
```

CI runs the same checks on Python 3.10-3.12 (Linux and Windows) and also builds the wheel and the
Optional: `pip install pre-commit && pre-commit install`.

## Guidelines

- **Tests for behaviour changes.** Scrapers are tested offline with fixture payloads (see
  `tests/test_sources.py`); never make a test depend on the network.
- **Whole-word matching.** Use `textutils.contains_term`, not `in`, when checking words in text.
- **No fabrication.** Anything that generates application text must only use facts from the master
  resume, and `resume/verify.py` should stay clean.
- **No personal data in the repo.** Use the synthetic data in `jobhunter/demo_data/` for examples
  and tests.
- **Be a good citizen to job sites.** Respect their terms and rate limits; prefer official APIs and
  employers' own boards over scraping.

See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for how the pieces fit together and how to add a
source, a skill, or a scoring dimension.
