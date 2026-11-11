# Security and privacy

## Reporting a vulnerability

Please use GitHub's private vulnerability reporting (Security tab > "Report a vulnerability")
instead of a public issue.

## Design

- **Local-first.** Your data (database, resumes, generated documents, logs) stays on your machine.
  There is no account, telemetry or third-party AI service; Streamlit's usage statistics are disabled.
- **The dashboard has no login.** It binds to `127.0.0.1` by default. Do not expose it to a network
  without adding your own authentication in front of it.
- **Secrets stay out of Git.** `.env`, master resumes, databases, logs and outputs are git-ignored and
  excluded from the built wheel (CI checks the wheel).
- **Dependencies are audited.** A weekly workflow runs `pip-audit` on the pinned requirements and
  Dependabot proposes updates. `pyarrow` and `numpy` are held back deliberately because
  `python-jobspy` pins NumPy 1.26 (see `jobhunter/requirements.txt`).

## Your responsibilities

- Review generated documents before sending them; the verifier flags unsupported claims but does
  not replace your judgement.
- Only use proxies and scraping options you are authorised to use, and follow each job site's terms.
