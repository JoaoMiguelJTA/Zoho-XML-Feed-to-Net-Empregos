# Zoho XML Feed to Net-Empregos

Syncs Recruityard's open job postings from the Zoho Recruit XML job feed to the [Net-Empregos](https://www.net-empregos.com) partner API. It runs on a schedule in GitHub Actions.

## How it works

`main.py` runs once per invocation:

1. Loads category, zone and job-type mappings from `mapping.json`.
2. Downloads the Zoho Recruit XML feed and reads every `<job>` element.
3. For each job:
   - Maps `category`, `city` and `type` to Net-Empregos IDs (see [Mapping rules](#mapping-rules)).
   - Builds the ad: title (cut to 100 characters, the API limit) and description, with an "apply here" link to the Zoho job URL appended.
   - Fixes mojibake (UTF-8 text that was decoded as Windows-1252) and replaces characters that Windows-1252 can't encode.
   - **Removes** any existing ad with the same reference number (`hrsmart_remove.asp`), then **publishes** it again (`hrsmart_insert.asp`) as a form POST encoded in Windows-1252.
   - Waits 3 seconds before the next job.
4. Logs a summary: jobs found, processed, removed, published, warnings and failures.

Each run republishes every job in the feed, so Net-Empregos always matches the latest Zoho content.

## Mapping rules

`mapping.json` holds three lookup tables that map feed values to Net-Empregos IDs:

| Table | Feed field | Default if not found |
| --- | --- | --- |
| `categoria_mapping` | `category` | `57` (Customer Service) |
| `zona_mapping` | `city` | `29` (Foreign - Others) |
| `tipo_mapping` | `type` | `1` (Tempo Inteiro) |

The script applies extra rules in this order after the lookups:

- **Country overrides zone:** Angola, Moçambique, Guiné Bissau, Brasil, São Tomé e Príncipe, Cabo Verde, Açores, Madeira and Timor each get their fixed zone ID. For `portugal`, the zone comes from the city, falling back to `0` (Todas as Zonas). Any other non-empty country gets `29`.
- **Remote jobs:** if the title contains "teletrabalho" or "remote", type becomes `4` (Teletrabalho) and zone becomes `0` (Todas as Zonas).

The ID values come from the Net-Empregos interface spec (`Net-Empregos Interface.doc.pdf`). `mapping.json` must be saved as UTF-8.

## Setup

Requires Python 3.12, the version CI uses.

```bash
python -m venv .venv
.venv\Scripts\activate        # Windows
source .venv/bin/activate     # macOS/Linux
pip install -r requirements.txt
```

Create a `.env` file in the repo root. It's gitignored.

```env
API_ACCESS_KEY=your-net-empregos-partner-key
```

| Variable | Required | Description |
| --- | --- | --- |
| `API_ACCESS_KEY` | Yes | Net-Empregos partner access key. The script exits with an error if it isn't set. |
| `LOG_DIR` | No | Folder for the per-run logs. Defaults to `logs`. |

## Running

```bash
python main.py
```

> **Warning:** a local run publishes to the live Net-Empregos account. Every job in the feed gets removed and published again.

## Scheduled runs (GitHub Actions)

[`.github/workflows/actions.yml`](.github/workflows/actions.yml) runs the sync:

- Daily at **10:30 and 17:30 UTC**.
- On demand from the Actions tab (**Run workflow**).

The workflow reads `API_ACCESS_KEY` from the repository secret of the same name. After every run, including failed ones, it uploads the logs as an artifact named `sync-logs-<run_id>-<attempt>` and keeps it for 30 days.

Dependabot keeps the pip dependencies up to date ([`.github/dependabot.yml`](.github/dependabot.yml)).

## Logs

Each run writes:

| File | Content |
| --- | --- |
| `jobs_sync.log` | Human-readable log, added to on every run |
| `logs/jobs_sync_<run_id>.log` | Human-readable log for this run only |
| `logs/actions_<run_id>.jsonl` | Structured audit trail, one JSON object per action (`sync_run`, `load_mappings`, `fetch_feed`, `process_job`, `map_job`, `remove_old_job`, `publish_job`), with status and details |

`<run_id>` is `<GITHUB_RUN_ID>_attempt_<GITHUB_RUN_ATTEMPT>` in CI and a UTC timestamp (`YYYYMMDD_HHMMSS`) locally. The API key is removed from all log output.

The final `sync_run` entry ends with one of three statuses:

- `finished`: everything succeeded.
- `finished_with_warnings`: the Net-Empregos API returned an error for at least one remove or publish call.
- `finished_with_errors`: at least one job raised an exception.

## Security

See [`.github/SECURITY.md`](.github/SECURITY.md) for how to report a vulnerability.

## License

MIT, see [LICENSE](LICENSE).

`Net-Empregos Interface.doc.pdf` is third-party documentation from Net-Empregos and is not covered by this license.
