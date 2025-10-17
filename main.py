import os
import json
import logging
from typing import List, Optional, Tuple, Dict, Any

import numpy as np
import requests
from google.cloud import storage

try:
    from sentence_transformers import SentenceTransformer
except Exception:
    SentenceTransformer = None  # без этой либы RAG отключится

# ========= ЛОГИ =========
LOG_LEVEL = os.environ.get("LOG_LEVEL", "INFO").upper()
logging.basicConfig(level=LOG_LEVEL, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

# ========= КОНФИГ (дефолты как в старом) =========
GCS_BUCKET = os.environ.get("GCS_BUCKET", "telegram-bot-schemas")
SCHEMAS_FILE = os.environ.get("SCHEMAS_FILE", "schemas.txt.txt")
MODEL_GCS_PREFIX = os.environ.get("MODEL_GCS_PREFIX", "model/")
MODEL_LOCAL_DIR = os.environ.get("MODEL_LOCAL_DIR", "/tmp/model")

TG_TOKEN = os.environ.get("TG_TOKEN")
OPENROUTER_API_KEY = os.environ.get("OPENROUTER_API_KEY")

# Модели: сначала те, что стабильно пишут content; GLM — в конце
OPENROUTER_MODELS = [
    m.strip()
    for m in os.environ.get(
        "OPENROUTER_MODELS",
        "mistralai/mistral-nemo:free,meta-llama/llama-3.1-8b-instruct:free,z-ai/glm-4.5-air:free",
    ).split(",")
    if m.strip()
]
OPENROUTER_TIMEOUT = int(os.environ.get("OPENROUTER_TIMEOUT", "30"))
OPENROUTER_X_TITLE = os.environ.get("OPENROUTER_X_TITLE", "Telegram Bot")
OPENROUTER_REFERER = os.environ.get("OPENROUTER_REFERER")  # опционально

# Поиск по схемам
TOP_K = int(os.environ.get("TOP_K", "5"))
TOP_K_LOG = int(os.environ.get("TOP_K_LOG", "3"))
TRIGGER_BONUS = float(os.environ.get("TRIGGER_BONUS", "0.20"))
SIM_THRESHOLD = float(os.environ.get("SIM_THRESHOLD", "0.0"))

# ========= HTTP =========
http = requests.Session()
http.headers.update({"Accept": "application/json"})

# ========= ГЛОБАЛЫ =========
_initialized = False
embedding_model: Optional[SentenceTransformer] = None
# каждая схема: dict{full,title,triggers,instruction,embed_text,embedding}
schemas: List[Dict[str, Any]] = []

# ========= ИНСТРУКЦИИ =========
BASE_INSTRUCTION = (
    "Ты живой человек и сидишь в чате с другими. Отвечай коротко максимум 1-2 предложения, "
    "естественно, со слэнгом и шутками. "
    "Могут быть редкие опечатки, 'е' вместо 'ё', 'ь' вместо 'ъ'. "
    "Можно немного небрежности в пунктуации. "
    "Предложения могут начинаться со строчной буквы. "
    "Используй короткое тире - вместо длинного —."
)
DEFAULT_STYLE_INSTRUCTION = "Отвечай коротко, легко и шутливо."

# ========= УТИЛИТЫ =========
def safe_truncate(text: str, n: int = 120) -> str:
    return text if len(text) <= n else text[:n] + "..."

def cosine_similarity(a: np.ndarray, b: np.ndarray, eps: float = 1e-8) -> float:
    na, nb = float(np.linalg.norm(a)), float(np.linalg.norm(b))
    if na < eps or nb < eps:
        return 0.0
    return float(np.dot(a, b) / (na * nb))

def _decode_bytes(b: bytes) -> str:
    for enc in ("utf-8", "utf-8-sig", "cp1251", "latin-1"):
        try:
            return b.decode(enc)
        except UnicodeDecodeError:
            continue
    return b.decode("utf-8", errors="replace")

def _parse_schema_line(line: str) -> Optional[Dict[str, Any]]:
    parts = [p.strip() for p in line.split("|")]
    if len(parts) >= 5:
        mode, subtype, triggers, behavior, instruction = parts[0], parts[1], parts[2], parts[3], parts[4]
        title = f"{mode} | {subtype}"
    elif len(parts) == 3:
        mode, triggers, instruction = parts[0], parts[1], parts[2]
        subtype = ""
        behavior = ""
        title = mode
    elif len(parts) == 2:
        mode, instruction = parts[0], parts[1]
        triggers = ""
        subtype = ""
        behavior = ""
        title = mode
    else:
        return None

    triggers_list = [t.strip().lower() for t in triggers.split(",")] if triggers else []
    embed_text = " ".join(x for x in [mode, subtype, triggers] if x)
    return {
        "full": line,
        "title": title,
        "triggers": triggers_list,
        "instruction": instruction,
        "embed_text": embed_text,
    }

# ========= ЗАГРУЗКА =========
def _download_model_from_gcs(bucket: storage.Bucket, prefix: str) -> None:
    blobs = list(bucket.list_blobs(prefix=prefix))
    if not blobs:
        raise FileNotFoundError(f"Модель не найдена в GCS по префиксу '{prefix}'")
    for blob in blobs:
        if blob.name.endswith("/"):
            continue
        dest_path = os.path.join("/tmp", blob.name)  # /tmp/model/...
        os.makedirs(os.path.dirname(dest_path), exist_ok=True)
        blob.download_to_filename(dest_path)
    logger.info("Модель скачана из GCS.")

def _load_embedding_model(local_dir: str) -> Optional[SentenceTransformer]:
    if SentenceTransformer is None:
        logger.warning("sentence-transformers не установлен. RAG будет отключен.")
        return None
    model = SentenceTransformer(local_dir)
    logger.info("Модель эмбеддингов загружена.")
    return model

def _load_schemas_from_gcs(bucket: storage.Bucket, filename: str) -> Optional[str]:
    blob = bucket.blob(filename)
    if not blob.exists():
        logger.warning("Схема не найдена по имени: %s. Пробую поиск по суффиксу.", filename)
        for b in bucket.list_blobs(prefix=""):
            if b.name.endswith(filename):
                data = b.download_as_bytes()
                text = _decode_bytes(data)
                logger.info("Файл схем загружен (по суффиксу): %s (байт: %d)", b.name, len(data))
                print(f"SCHEMAS LOADED (suffix): name={b.name}, bytes={len(data)}", flush=True)
                return text
        logger.error("Схема '%s' не найдена ни по имени, ни по суффиксу.", filename)
        return None

    data = blob.download_as_bytes()
    text = _decode_bytes(data)
    logger.info("Файл схем загружен из GCS: %s (байт: %d)", blob.name, len(data))
    print(f"SCHEMAS LOADED: name={blob.name}, bytes={len(data)}", flush=True)
    return text

def initialize():
    global _initialized, embedding_model, schemas
    if _initialized:
        return

    # Важно: строка — одной строкой, без переноса
    print(f"CONFIG: bucket={GCS_BUCKET}, schemas_file={SCHEMAS_FILE}, model_prefix={MODEL_GCS_PREFIX}", flush=True)
    logger.info("Инициализация...")

    try:
        storage_client = storage.Client()
        bucket = storage_client.bucket(GCS_BUCKET)

        # Модель
        os.makedirs(MODEL_LOCAL_DIR, exist_ok=True)
        try:
            _download_model_from_gcs(bucket, MODEL_GCS_PREFIX)
            embedding_model = _load_embedding_model(MODEL_LOCAL_DIR)
        except Exception as e:
            logger.error("Ошибка загрузки модели эмбеддингов: %s", e)
            embedding_model = None

        # Схемы
        schemas = []
        try:
            text_data = _load_schemas_from_gcs(bucket, SCHEMAS_FILE)
            if text_data:
                lines = [line.strip() for line in text_data.split("\n") if line.strip()]
                parsed = [_parse_schema_line(line) for line in lines]
                parsed = [p for p in parsed if p is not None]
                if embedding_model:
                    for p in parsed:
                        emb = embedding_model.encode(p["embed_text"], convert_to_tensor=False)
                        p["embedding"] = np.asarray(emb, dtype=np.float32)
                    schemas = parsed
                    logger.info("Готово: схем с эмбеддингами: %d", len(schemas))
                    print(f"SCHEMAS COUNT: {len(schemas)}", flush=True)
                else:
                    logger.warning("Схемы прочитаны, но модель не загружена — RAG отключён.")
            else:
                logger.warning("Схемы не загружены — будет дефолтная инструкция.")
        except Exception as e:
            logger.error("Ошибка чтения/обработки схем: %s", e)

        _initialized = True
        print("INIT OK", flush=True)
        logger.info("Инициализация завершена.")
    except Exception as e:
        _initialized = True
        logger.error("Критическая ошибка инициализации: %s", e)

# ========= RAG =========
def search_schema(query: str, top_k: int = TOP_K) -> List[Dict[str, Any]]:
    if not schemas or embedding_model is None:
        logger.info("RAG отключён: schemas=%d, model_loaded=%s", len(schemas), bool(embedding_model))
        print(f"RAG OFF: schemas={len(schemas)}, model={bool(embedding_model)}", flush=True)
        return []

    try:
        q = embedding_model.encode(query, convert_to_tensor=False)
        q = np.asarray(q, dtype=np.float32)
    except Exception as e:
        logger.error("Ошибка encode запроса для RAG: %s", e)
        return []

    low = query.lower()
    scored: List[Tuple[int, float]] = []
    for idx, p in enumerate(schemas):
        sim = cosine_similarity(q, p["embedding"])
        hits = sum(1 for t in p["triggers"] if t and t in low)  # бонус за совпадение триггеров
        sim += TRIGGER_BONUS * hits
        scored.append((idx, sim))

    scored.sort(key=lambda x: x[1], reverse=True)

    for i, (idx, s) in enumerate(scored[:min(TOP_K_LOG, len(scored))], 1):
        title = schemas[idx]["title"]
        logger.info("Кандидат #%d: %s | score=%.3f", i, title, s)
        print(f"Кандидат #{i}: {title} | score={s:.3f}", flush=True)

    top = [schemas[idx] for idx, s in scored[:top_k] if s >= SIM_THRESHOLD] or \
          [schemas[idx] for idx, s in scored[:max(1, top_k)]]
    return top

# ========= ПРОМПТ =========
def get_system_prompt(user_message: str) -> str:
    low = (user_message or "").lower()

    # Шуточные триггеры (анти-рецепт)
    if any(w in low for w in ["рецепт", "кружка", "кроссовки", "свиные крылышки"]):
        instr = "Над тобой шутят, не отвечай серьёзно, пошути в ответ, максимум 1-2 предложения. Не давай никаких рецептов."
        return f"{BASE_INSTRUCTION} {instr}".strip()

    instruction = DEFAULT_STYLE_INSTRUCTION
    results = search_schema(user_message, top_k=TOP_K)

    chosen = None
    for p in results:
        if p["triggers"] and any(t in low for t in p["triggers"] if t):
            chosen = p
            break
    if chosen is None and results:
        chosen = results[0]

    if chosen:
        logger.info("Выбрана схема: %s", chosen["title"])
        print(f"Выбрана схема: {chosen['title']}", flush=True)
        if chosen.get("instruction"):
            instruction = chosen["instruction"]

    return f"{BASE_INSTRUCTION} {instruction}".strip()

# ========= OpenRouter =========
def _try_openrouter(messages: List[dict], model: str) -> Optional[str]:
    if not OPENROUTER_API_KEY:
        return None

    url = "https://openrouter.ai/api/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {OPENROUTER_API_KEY}",
        "Content-Type": "application/json",
        "X-Title": OPENROUTER_X_TITLE or "Telegram Bot",
    }
    if OPENROUTER_REFERER:
        headers["HTTP-Referer"] = OPENROUTER_REFERER
        headers["Referer"] = OPENROUTER_REFERER

    payload = {
        "model": model,
        "messages": messages,
        "max_tokens": 150,
        "temperature": 0.7,
        "instructions": "Дай сразу короткий ответ (1-2 предложения), без рассуждений.",
    }

    try:
        r = http.post(url, json=payload, headers=headers, timeout=OPENROUTER_TIMEOUT)
        r.raise_for_status()
        j = r.json()

        choices = j.get("choices") or []
        if not choices:
            logger.error("OpenRouter пустой choices: %s", j)
            return None

        msg = choices[0].get("message") or {}
        content = (msg.get("content") or "").strip()
        if not content:
            logger.info("OpenRouter: пустой content у модели %s, пробую следующую.", model)
            return None
        return content
    except requests.exceptions.RequestException as e:
        logger.error("Ошибка OpenRouter (%s): %s", model, e)
        return None

def get_ai_response(user_message: str) -> str:
    user_message = (user_message or "").strip()
    if not user_message:
        return "ээ, накинь пару слов, а то отвечать нечему :)"

    system_prompt = get_system_prompt(user_message)
    if not system_prompt.strip():
        system_prompt = f"{BASE_INSTRUCTION} {DEFAULT_STYLE_INSTRUCTION}"

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_message},
    ]

    for m in OPENROUTER_MODELS:
        resp = _try_openrouter(messages, m)
        if resp:
            return resp

    return "сервачок шалит, но я скоро вернусь — кинь ещё раз через минутку"

# ========= Telegram =========
def send_telegram_message(chat_id: int, text: str):
    if not TG_TOKEN:
        logger.warning("TG_TOKEN не задан — не могу отправить сообщение в Telegram.")
        return
    url = f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage"
    payload = {"chat_id": chat_id, "text": text, "disable_web_page_preview": True}
    try:
        r = http.post(url, json=payload, timeout=10)
        if r.status_code != 200:
            logger.error("Ошибка отправки в Telegram: %s %s", r.status_code, safe_truncate(r.text, 300))
    except requests.exceptions.RequestException as e:
        logger.error("Сетевая ошибка при отправке в Telegram: %s", e)

# ========= ENTRYPOINT =========
def telegram_webhook(request):
    # Диагностика: GET ?diag=1
    if request.method == "GET" and getattr(request, "args", None) and request.args.get("diag") == "1":
        if not _initialized:
            try:
                initialize()
            except Exception as e:
                logger.error("Init err in diag: %s", e, exc_info=True)
        body = {
            "initialized": _initialized,
            "bucket": GCS_BUCKET,
            "schemas_file": SCHEMAS_FILE,
            "schemas_count": len(schemas),
            "embedding_model_loaded": bool(embedding_model),
        }
        print(f"DIAG: {body}", flush=True)
        return json.dumps(body, ensure_ascii=False), 200, {"Content-Type": "application/json; charset=utf-8"}

    if not _initialized:
        initialize()

    try:
        data = request.get_json(silent=True)
        if not data:
            return "OK", 200

        # Telegram webhook
        if "message" in data:
            msg = data["message"]
            chat_id = (msg.get("chat") or {}).get("id")
            text = msg.get("text") or ""
            is_bot = bool((msg.get("from") or {}).get("is_bot"))

            if not chat_id or not text:
                return "OK", 200
            if is_bot:
                return "OK", 200

            logger.info("TG message chat=%s: %s", chat_id, safe_truncate(text))
            print(f"TG MSG: chat={chat_id}, text={safe_truncate(text)}", flush=True)

            ai_response = get_ai_response(text)
            send_telegram_message(chat_id, ai_response)
            return "OK", 200

        # Простой Web API
        if isinstance(data.get("message"), str):
            user_message = data["message"].strip()
            if not user_message:
                return {"error": "Пустое сообщение"}, 400
            logger.info("WEB API: %s", safe_truncate(user_message))
            print(f"WEB API: {safe_truncate(user_message)}", flush=True)
            ai_response = get_ai_response(user_message)
            return {"response": ai_response}, 200

        logger.warning("Bad request: keys=%s", list(data.keys()))
        return "Bad Request", 400

    except Exception as e:
        logger.error("Ошибка обработки запроса: %s", e, exc_info=True)
        return "Internal Server Error", 500