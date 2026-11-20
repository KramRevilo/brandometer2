# Agent and contributor notes

- **Docs stay in the same commit.** Every change to this repo must update `README.md` in that same commit. Update `DEVELOPERS.md` too when the change is operator- or developer-facing (deploy, IAM, local run, tests, secrets). Do not leave README describing yesterday’s product.
- Do not commit secrets, real OAuth client IDs, real customer data, or real email addresses. Screenshots and fixtures use generic example names only (`Acme`, `editor@example.com`).
- Use only the Brandometer2 name; do not reference the previous fork's name in docs or UI. Historical CSS comment sentinels and `--sonar-*` variables in stored `custom_css` stay as-is so live surveys still parse.
- Regenerating README screenshots: `python3 tools/capture_screenshots.py` (see `tools/requirements-screenshots.txt`).
