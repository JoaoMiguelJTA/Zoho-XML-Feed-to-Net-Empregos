import requests
import xml.etree.ElementTree as ET
import os
import json
import time
import logging
import re
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlencode
from dotenv import load_dotenv

# --- configurar logging ---
LOG_DIR = Path(os.getenv("LOG_DIR", "logs"))
LOG_DIR.mkdir(parents=True, exist_ok=True)

github_run_id = os.getenv("GITHUB_RUN_ID")
github_run_attempt = os.getenv("GITHUB_RUN_ATTEMPT")
RUN_ID = (
    f"{github_run_id}_attempt_{github_run_attempt}"
    if github_run_id and github_run_attempt
    else datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
)
TEXT_LOG_PATH = LOG_DIR / f"jobs_sync_{RUN_ID}.log"
ACTION_LOG_PATH = LOG_DIR / f"actions_{RUN_ID}.jsonl"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler("jobs_sync.log", encoding="utf-8"),
        logging.FileHandler(TEXT_LOG_PATH, encoding="utf-8"),
        logging.StreamHandler()
    ]
)

run_started_at = time.monotonic()


def log_action(action: str, status: str, **details) -> None:
    """Write one structured audit entry for each significant action."""
    entry = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "run_id": RUN_ID,
        "action": action,
        "status": status,
        "details": details,
    }
    try:
        with ACTION_LOG_PATH.open("a", encoding="utf-8") as log_file:
            log_file.write(json.dumps(entry, ensure_ascii=False, default=str) + "\n")
    except Exception as exc:
        logging.warning("Could not write action log entry: %s", exc)

load_dotenv()

API_URL = "http://partner.net-empregos.com/hrsmart_insert.asp"
REMOVE_API_URL = "http://partner.net-empregos.com/hrsmart_remove.asp"
FEED_URL = "https://recruit.zoho.eu/recruit/downloadjobfeed?clientid=e5477b038ce4b5202ddbf36b873fbc6ff21e47b47056dd0829cb212655a55ff9b86cb70b634ff01e524066e539f85846"
API_KEY = os.getenv("API_ACCESS_KEY")
FORM_HEADERS = {"Content-Type": "application/x-www-form-urlencoded; charset=iso-8859-1"}
if not API_KEY:
    message = "API_ACCESS_KEY is not set in the environment or .env file."
    logging.error(message)
    log_action("validate_environment", "error", message=message)
    log_action(
        "sync_run",
        "failed",
        duration_seconds=round(time.monotonic() - run_started_at, 2),
        reason=message,
    )
    raise SystemExit(1)

logging.info("Sync run started. Run ID: %s", RUN_ID)
logging.info("Text log: %s", TEXT_LOG_PATH)
logging.info("Action log: %s", ACTION_LOG_PATH)
log_action(
    "sync_run",
    "started",
    text_log=str(TEXT_LOG_PATH),
    action_log=str(ACTION_LOG_PATH),
    github_run_id=github_run_id,
    github_run_attempt=github_run_attempt,
    github_workflow=os.getenv("GITHUB_WORKFLOW"),
    github_sha=os.getenv("GITHUB_SHA"),
)

# --- carregar mappings ---
try:
    with open("mapping.json", "r", encoding="iso-8859-1") as f:
        mappings = json.load(f)
except Exception as e:
    logging.error(f"Erro ao carregar mapping.json → {e}")
    log_action("load_mappings", "error", file="mapping.json", error=str(e))
    log_action(
        "sync_run",
        "failed",
        duration_seconds=round(time.monotonic() - run_started_at, 2),
        failed_action="load_mappings",
        error=str(e),
    )
    raise

zona_mapping = mappings["zona_mapping"]
categoria_mapping = mappings["categoria_mapping"]
tipo_mapping = mappings["tipo_mapping"]
log_action(
    "load_mappings",
    "success",
    file="mapping.json",
    zona_count=len(zona_mapping),
    categoria_count=len(categoria_mapping),
    tipo_count=len(tipo_mapping),
)

# --- fetch feed ---
try:
    response = requests.get(FEED_URL, timeout=30)
    response.raise_for_status()
    root = ET.fromstring(response.content)
    jobs = root.findall("job")
    logging.info("Feed carregado com sucesso.")
    log_action(
        "fetch_feed",
        "success",
        http_status=response.status_code,
        job_count=len(jobs),
    )
except Exception as e:
    logging.error(f"Erro ao carregar XML feed → {e}")
    log_action("fetch_feed", "error", error=str(e))
    log_action(
        "sync_run",
        "failed",
        duration_seconds=round(time.monotonic() - run_started_at, 2),
        failed_action="fetch_feed",
        error=str(e),
    )
    raise

# garantir que tudo fica em ISO-8859-1 antes do envio
def _looks_like_mojibake(candidate: str) -> bool:
    """Detect common mojibake sequences that show up when UTF-8 is misread as Latin-1."""
    if not candidate:
        return False
    markers = ("\u00c3", "\u00a1", "\u00a3", "\u00a7", "\u00aa", "\u00ba", "\u00bd", "\u00be")
    return any(marker in candidate for marker in markers)


def fix_mojibake(text: str) -> str:
    """Attempt to repair UTF-8 strings that were decoded as ISO-8859-1."""
    if not text:
        return ""
    try:
        repaired = text.encode("iso-8859-1").decode("utf-8")
    except UnicodeDecodeError:
        return text
    if _looks_like_mojibake(repaired):
        return text
    if _looks_like_mojibake(text):
        return repaired
    return repaired

# normalização de texto
def normalize_text(text: str) -> str:
    # substitui apóstrofos e aspas tipográficas por simples
    replacements = {
        "’": "'", "‘": "'",
        "“": '"', "”": '"',
        "–": "-", "—": "-",  # travessões
        "…": "..."           # reticências
    }
    for k, v in replacements.items():
        text = text.replace(k, v)
    return text

stats = {
    "found": len(jobs),
    "processed": 0,
    "removed": 0,
    "published": 0,
    "warnings": 0,
    "failed": 0,
}

for job in jobs:
    try:
        title = job.findtext("title", "").strip()
        ref = job.findtext("referencenumber", "").strip()
        url = job.findtext("url", "").strip()
        description = job.findtext("description", "").strip()
        categoria_raw = job.findtext("category", "").strip()
        zona_raw = job.findtext("city", "").strip()
        tipo_raw = job.findtext("type", "").strip() if job.find("type") is not None else "Tempo Inteiro"
        stats["processed"] += 1
        job_had_warning = False
        log_action("process_job", "started", ref=ref, title=title)

        # map values
        categoria = categoria_mapping.get(categoria_raw, "57")  # default: Call Center / Help Desk
        zona = zona_mapping.get(zona_raw, "29")  # default: Foreign - Others
        tipo = tipo_mapping.get(tipo_raw, "1")   # default: Tempo Inteiro

        # --- regra extra ---
        country = job.findtext("country", "").strip().lower()
        if country == "angola":
            zona = "20"
        elif country == "moçambique":
            zona = "21"
        elif country == "guiné bissau":
            zona = "22"
        elif country == "brasil":
            zona = "18"
        elif country == "são tomé e príncipe":
            zona = "23"
        elif country == "cabo verde":
            zona = "24"
        elif country == "açores":
            zona = "25"
        elif country == "madeira":
            zona = "26"
        elif country == "timor":
            zona = "27"
        elif country == "portugal":
            zona = zona_mapping.get(zona_raw, "0")  # default: Todas as Zonas
        elif country:
            zona = "29"  # Foreign - Others

        # regra teletrabalho
        if "teletrabalho" in title.lower() or "remote" in title.lower():
            tipo = "4"   # Teletrabalho
            zona = "0"   # Todas as Zonas

        log_action(
            "map_job",
            "success",
            ref=ref,
            title=title,
            categoria_raw=categoria_raw,
            categoria=categoria,
            zona_raw=zona_raw,
            zona=zona,
            tipo_raw=tipo_raw,
            tipo=tipo,
            country=country,
        )

        texto = normalize_text(
            f"{description}"
            f"<a href='{url}'>Clique aqui para se candidatar!</a><br>"
        )
        payload = {
            "ACCESS": API_KEY,
            "REF": ref,
            "TITULO": fix_mojibake(title),
            "TEXTO": fix_mojibake(texto),
            "ZONA": zona,
            "CATEGORIA": categoria,
            "TIPO": tipo,
        }

        # --- remove antigo ---
        remove_payload = {"ACCESS": API_KEY, "REF": ref}
        remove_response = requests.get(REMOVE_API_URL, params=remove_payload, timeout=10)
        if remove_response.status_code < 400:
            stats["removed"] += 1
            logging.info(f"[{ref}] Anúncio antigo removido.")
            log_action(
                "remove_old_job",
                "success",
                ref=ref,
                http_status=remove_response.status_code,
            )
        else:
            stats["warnings"] += 1
            job_had_warning = True
            logging.warning(
                "[%s] Erro ao remover anúncio antigo → %s - %s",
                ref,
                remove_response.status_code,
                remove_response.text,
            )
            log_action(
                "remove_old_job",
                "warning",
                ref=ref,
                http_status=remove_response.status_code,
                response_preview=remove_response.text[:500],
            )

        # --- inserir novo ---
        encoded_payload = urlencode(payload, encoding="iso-8859-1").encode("iso-8859-1")
        r = requests.post(API_URL, data=encoded_payload, headers=FORM_HEADERS, timeout=10)
        if r.status_code == 200:
            stats["published"] += 1
            logging.info(f"[{ref}] '{title}' publicado com sucesso.")
            log_action(
                "publish_job",
                "success",
                ref=ref,
                title=title,
                http_status=r.status_code,
            )
        else:
            stats["warnings"] += 1
            job_had_warning = True
            logging.warning(f"[{ref}] Erro ao publicar '{title}' → {r.status_code} - {r.text}")
            log_action(
                "publish_job",
                "warning",
                ref=ref,
                title=title,
                http_status=r.status_code,
                response_preview=r.text[:500],
            )

        job_status = "finished_with_warnings" if job_had_warning else "success"
        log_action("process_job", job_status, ref=ref, title=title)

        time.sleep(3)

    except Exception as e:
        stats["failed"] += 1
        logging.exception("Erro no processamento do job → %s", e)
        log_action(
            "process_job",
            "error",
            ref=locals().get("ref", ""),
            title=locals().get("title", ""),
            error=str(e),
        )

duration_seconds = round(time.monotonic() - run_started_at, 2)
final_status = (
    "finished_with_errors"
    if stats["failed"]
    else "finished_with_warnings"
    if stats["warnings"]
    else "finished"
)
logging.info(
    "Sync run finished. found=%s processed=%s removed=%s published=%s warnings=%s failed=%s duration=%ss",
    stats["found"],
    stats["processed"],
    stats["removed"],
    stats["published"],
    stats["warnings"],
    stats["failed"],
    duration_seconds,
)
log_action("sync_run", final_status, duration_seconds=duration_seconds, **stats)
