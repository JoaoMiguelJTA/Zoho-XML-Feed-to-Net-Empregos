import requests
import xml.etree.ElementTree as ET
import os
import json
import time
import logging
import re
from urllib.parse import urlencode
from dotenv import load_dotenv

# --- configurar logging ---
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler("jobs_sync.log", encoding="iso-8859-1"),
        logging.StreamHandler()
    ]
)

load_dotenv()

API_URL = "http://partner.net-empregos.com/hrsmart_insert.asp"
REMOVE_API_URL = "http://partner.net-empregos.com/hrsmart_remove.asp"
FEED_URL = "https://recruit.zoho.eu/recruit/downloadjobfeed?clientid=da279e513762f8ff929094f0761b8d7028c9ede87d9cc749c7fc7c9ec526d541db96e9a00da67f84101be0a8e52f82b6"
API_KEY = os.getenv("API_ACCESS_KEY")
FORM_HEADERS = {"Content-Type": "application/x-www-form-urlencoded; charset=iso-8859-1"}
if not API_KEY:
    print("Error: API_ACCESS_KEY is not set in the environment or .env file.")
    exit(1)

# --- carregar mappings ---
try:
    with open("mapping.json", "r", encoding="iso-8859-1") as f:
        mappings = json.load(f)
except Exception as e:
    logging.error(f"Erro ao carregar mapping.json → {e}")
    raise

zona_mapping = mappings["zona_mapping"]
categoria_mapping = mappings["categoria_mapping"]
tipo_mapping = mappings["tipo_mapping"]

# --- fetch feed ---
try:
    response = requests.get(FEED_URL, timeout=30)
    response.raise_for_status()
    root = ET.fromstring(response.content)
    logging.info("Feed carregado com sucesso.")
except Exception as e:
    logging.error(f"Erro ao carregar XML feed → {e}")
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

for job in root.findall("job"):
    try:
        title = job.findtext("title", "").strip()
        ref = job.findtext("referencenumber", "").strip()
        url = job.findtext("url", "").strip()
        description = job.findtext("description", "").strip()
        categoria_raw = job.findtext("category", "").strip()
        zona_raw = job.findtext("city", "").strip()
        tipo_raw = job.findtext("type", "").strip() if job.find("type") is not None else "Tempo Inteiro"

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
        requests.get(REMOVE_API_URL, params=remove_payload, timeout=10)
        logging.info(f"[{ref}] Anúncio antigo removido.")

        # --- inserir novo ---
        encoded_payload = urlencode(payload, encoding="iso-8859-1").encode("iso-8859-1")
        r = requests.post(API_URL, data=encoded_payload, headers=FORM_HEADERS, timeout=10)
        if r.status_code == 200:
            logging.info(f"[{ref}] '{title}' publicado com sucesso.")
        else:
            logging.warning(f"[{ref}] Erro ao publicar '{title}' → {r.status_code} - {r.text}")

        time.sleep(3)

    except Exception as e:
        logging.error(f"Erro no processamento do job → {e}")
