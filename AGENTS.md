# Agent and contributor notes

- **Docs stay in the same commit.** Every change to this repo must update `README.md` in that same commit. Update `DEVELOPERS.md` too when the change is operator- or developer-facing (deploy, IAM, local run, tests, secrets). Do not leave README describing yesterday’s product.
- Do not commit secrets, real OAuth client IDs, real customer data, or real email addresses. Screenshots and fixtures use generic example names only (`Acme`, `editor@example.com`).
- Do not touch `KramRevilo/sonar`. This repo is Brandometer2.
- Regenerating README screenshots: `python3 tools/capture_screenshots.py` (see `tools/requirements-screenshots.txt`).
