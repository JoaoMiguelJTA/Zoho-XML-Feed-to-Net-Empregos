# Security Policy

## Supported Versions

This project has no versioned releases. Only the latest code on the `main` branch is supported and receives security fixes.

## Reporting a Vulnerability

**Please do not open a public issue for security problems.**

Report vulnerabilities privately through GitHub:

1. Go to the **Security** tab of this repository.
2. Click **Report a vulnerability**.
3. Include:
   - A clear description of the vulnerability.
   - Steps to reproduce it.
   - The potential impact (for example, exposed credentials or unauthorised job postings).

We will confirm receipt within 2 working days. If the report is verified, we aim to release a fix within 7–14 days, depending on severity.

## Secrets and Credentials

- The Net-Empregos API key is stored only as the `API_ACCESS_KEY` GitHub Actions secret, or in a local `.env` file that is never committed.
- Never commit API keys, tokens or passwords to this repository. If a secret is committed by mistake, treat it as compromised: revoke it and issue a new one straight away, because removing it from the code does not remove it from the git history.

## Our Commitment

- We will keep you updated throughout the resolution process.
- Credit will be given to the reporter unless otherwise requested.
