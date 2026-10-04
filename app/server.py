#!/usr/bin/env python3
"""Dependency-free local orchestrator for the school voice assistant."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import mimetypes
import re
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import threading
import unicodedata
import urllib.error
import urllib.request
import uuid
from difflib import SequenceMatcher
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent.parent
WEB_ROOT = ROOT / "web"
DB_PATH = ROOT / "data" / "school.db"
SCHEMA_PATH = ROOT / "data" / "schema.sql"
CONFIG_PATH = ROOT / "config.json"

SEED_LOCATIONS = [
    {
        "canonical_name": "Laboratorio di robotica",
        "aliases": "robotica|laboratorio robot|aula robotica|lab robotica",
        "building": "Edificio principale",
        "floor": "Primo piano",
        "room": "Aula 115",
        "directions": "Dall'ingresso principale prosegui fino alle scale centrali. Sali al primo piano, gira a destra: il laboratorio è la terza porta sulla sinistra.",
        "accessible_directions": "Dall'ingresso principale raggiungi l'ascensore accanto alla segreteria. Sali al primo piano, gira a destra: il laboratorio è la terza porta sulla sinistra.",
        "notes": "",
        "description": "Laboratorio dedicato a robotica, programmazione, elettronica e attività STEM.",
        "services": "lezioni di robotica|programmazione|progetti STEM|elettronica|montaggio robot",
        "keywords": "robot|computer|sensori|coding|tecnologia|automazione",
        "example_questions": "Dove fanno robotica?|Dove si costruiscono i robot?|Dov'è il laboratorio STEM?",
    },
    {
        "canonical_name": "Segreteria didattica",
        "aliases": "segreteria|ufficio studenti|ufficio alunni|didattica",
        "building": "Edificio principale",
        "floor": "Piano terra",
        "room": "Ufficio 04",
        "directions": "Dall'ingresso principale gira a sinistra. La segreteria didattica è il secondo ufficio sulla destra.",
        "accessible_directions": "Il percorso è senza scale. Dall'ingresso principale gira a sinistra: la segreteria è il secondo ufficio sulla destra.",
        "notes": "",
        "description": "Ufficio che gestisce le pratiche amministrative e didattiche degli studenti.",
        "services": "iscrizioni|certificati|moduli|trasferimenti|nulla osta|documenti degli studenti|informazioni scolastiche",
        "keywords": "iscriversi|documentazione|certificato|modulo|pratica|ufficio studenti|cambio scuola",
        "example_questions": "Dove faccio l'iscrizione?|A chi chiedo un certificato?|Dove consegno i documenti?",
    },
    {
        "canonical_name": "Aula magna",
        "aliases": "auditorium|sala conferenze|sala riunioni",
        "building": "Edificio principale",
        "floor": "Piano terra",
        "room": "Aula 01",
        "directions": "Dall'ingresso principale prosegui dritto per circa venti metri. L'aula magna è in fondo al corridoio.",
        "accessible_directions": "Il percorso è completamente accessibile. Prosegui dritto dall'ingresso principale fino al fondo del corridoio.",
        "notes": "",
        "description": "Sala grande per conferenze, assemblee, presentazioni, riunioni e spettacoli.",
        "services": "assemblee|conferenze|riunioni|presentazioni|eventi|spettacoli",
        "keywords": "auditorium|palco|incontro|evento|assemblea di istituto",
        "example_questions": "Dove si tiene l'assemblea?|Dov'è la sala per le conferenze?|Dove fanno le presentazioni?",
    },
    {
        "canonical_name": "Palestra",
        "aliases": "campo sportivo|ginnastica|educazione fisica",
        "building": "Edificio sportivo",
        "floor": "Piano terra",
        "room": "",
        "directions": "Esci dall'ingresso laterale destro e segui il percorso coperto. La palestra si trova nel secondo edificio.",
        "accessible_directions": "Usa l'uscita laterale destra e segui il percorso coperto senza gradini fino al secondo edificio.",
        "notes": "",
        "description": "Spazio sportivo per educazione fisica, allenamenti e attività motorie.",
        "services": "educazione fisica|ginnastica|allenamenti|attività sportive|tornei",
        "keywords": "sport|pallone|campo|spogliatoi|attività motoria",
        "example_questions": "Dove si fa educazione fisica?|Dove devo andare per ginnastica?|Dov'è il campo sportivo?",
    },
    {
        "canonical_name": "Biblioteca",
        "aliases": "mediateca|libri|sala lettura",
        "building": "Edificio principale",
        "floor": "Secondo piano",
        "room": "Aula 208",
        "directions": "Raggiungi le scale centrali e sali al secondo piano. Gira a sinistra: la biblioteca è di fronte all'aula 208.",
        "accessible_directions": "Prendi l'ascensore accanto alla segreteria fino al secondo piano. All'uscita gira a sinistra: la biblioteca è di fronte all'aula 208.",
        "notes": "",
        "description": "Spazio per consultare, leggere e prendere in prestito libri e materiale didattico.",
        "services": "prestito libri|consultazione|sala lettura|ricerche|materiale didattico",
        "keywords": "leggere|libro|studiare|prestito|restituzione libri|mediateca",
        "example_questions": "Dove posso prendere un libro?|Dov'è la sala lettura?|Dove restituisco un libro?",
    },
]


def load_config() -> dict[str, Any]:
    with CONFIG_PATH.open("r", encoding="utf-8") as handle:
        return json.load(handle)


CONFIG = load_config()
EMBEDDING_LOCK = threading.Lock()

LOCATION_TEXT_COLUMNS = {
    "description": "TEXT NOT NULL DEFAULT ''",
    "services": "TEXT NOT NULL DEFAULT ''",
    "keywords": "TEXT NOT NULL DEFAULT ''",
    "example_questions": "TEXT NOT NULL DEFAULT ''",
}


def db_connect() -> sqlite3.Connection:
    connection = sqlite3.connect(DB_PATH)
    connection.row_factory = sqlite3.Row
    return connection


def initialize_database() -> None:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with db_connect() as connection:
        connection.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))
        existing_columns = {
            row["name"] for row in connection.execute("PRAGMA table_info(locations)").fetchall()
        }
        for name, declaration in LOCATION_TEXT_COLUMNS.items():
            if name not in existing_columns:
                connection.execute(f"ALTER TABLE locations ADD COLUMN {name} {declaration}")
        count = connection.execute("SELECT COUNT(*) FROM locations").fetchone()[0]
        if count == 0:
            connection.executemany(
                """
                INSERT INTO locations (
                    canonical_name, aliases, building, floor, room,
                    directions, accessible_directions, notes, description,
                    services, keywords, example_questions
                ) VALUES (
                    :canonical_name, :aliases, :building, :floor, :room,
                    :directions, :accessible_directions, :notes, :description,
                    :services, :keywords, :example_questions
                )
                """,
                SEED_LOCATIONS,
            )
        else:
            # Enrich only untouched demo rows; never overwrite user content.
            for location in SEED_LOCATIONS:
                connection.execute(
                    """
                    UPDATE locations
                    SET description = CASE WHEN trim(description) = '' THEN :description ELSE description END,
                        services = CASE WHEN trim(services) = '' THEN :services ELSE services END,
                        keywords = CASE WHEN trim(keywords) = '' THEN :keywords ELSE keywords END,
                        example_questions = CASE WHEN trim(example_questions) = '' THEN :example_questions ELSE example_questions END
                    WHERE canonical_name = :canonical_name
                    """,
                    location,
                )
        refresh_fts_index(connection)
        connection.execute("PRAGMA optimize")


def normalize(value: str) -> str:
    decomposed = unicodedata.normalize("NFKD", value.lower())
    without_accents = "".join(char for char in decomposed if not unicodedata.combining(char))
    return " ".join(re.findall(r"[a-z0-9]+", without_accents))


STOPWORDS = {
    "a", "ad", "al", "alla", "alle", "allo", "come", "da", "dal", "dall",
    "dalla", "dalle", "dello", "dove", "e", "gli", "il", "in", "l", "la",
    "le", "lo", "mi", "nel", "nella", "per", "posso", "qual", "quale",
    "raggiungo", "si", "sono", "sta", "trova", "trovare", "un", "una", "vorrei",
    "andare", "chiedere", "chiedo", "deve", "devi", "devo", "fare", "faccio",
    "sapere", "vado", "vai",
}


def useful_tokens(value: str) -> set[str]:
    return {token for token in normalize(value).split() if token not in STOPWORDS and len(token) > 1}


ITALIAN_SMALL_NUMBERS = {
    0: "zero", 1: "uno", 2: "due", 3: "tre", 4: "quattro", 5: "cinque",
    6: "sei", 7: "sette", 8: "otto", 9: "nove", 10: "dieci", 11: "undici",
    12: "dodici", 13: "tredici", 14: "quattordici", 15: "quindici",
    16: "sedici", 17: "diciassette", 18: "diciotto", 19: "diciannove",
}
ITALIAN_TENS = {
    20: "venti", 30: "trenta", 40: "quaranta", 50: "cinquanta",
    60: "sessanta", 70: "settanta", 80: "ottanta", 90: "novanta",
}


def italian_number_words(number: int, spaced: bool = False) -> str:
    """Return a practical Italian reading for room numbers from 0 to 999."""
    if number < 20:
        return ITALIAN_SMALL_NUMBERS[number]
    if number < 100:
        tens = number // 10 * 10
        unit = number % 10
        if not unit:
            return ITALIAN_TENS[tens]
        separator = " " if spaced else ""
        return ITALIAN_TENS[tens] + separator + ITALIAN_SMALL_NUMBERS[unit]
    if number < 1000:
        hundreds = number // 100
        remainder = number % 100
        prefix = "cento" if hundreds == 1 else ITALIAN_SMALL_NUMBERS[hundreds] + "cento"
        if not remainder:
            return prefix
        separator = " " if spaced else ""
        return prefix + separator + italian_number_words(remainder, spaced)
    return str(number)


def room_labels(room: str) -> list[str]:
    """Expand `Aula 115` with forms commonly produced by speech recognition."""
    labels = [room] if room else []
    match = re.search(r"\d+", room)
    if not match:
        return labels
    number_text = match.group(0)
    number = int(number_text)
    prefix = room[:match.start()].strip() or "aula"
    labels.extend(
        [
            number_text,
            f"{prefix} {number_text}",
            f"{prefix} {italian_number_words(number)}",
            f"{prefix} {italian_number_words(number, spaced=True)}",
            f"{prefix} {' '.join(number_text)}",
            f"{prefix} {' '.join(ITALIAN_SMALL_NUMBERS[int(digit)] for digit in number_text)}",
        ]
    )
    # Transcribers sometimes split a room number around the decimal separator
    # ("1.15" -> "1 15") or insert an "e" after the hundreds.
    for split_at in range(1, len(number_text)):
        labels.append(f"{prefix} {number_text[:split_at]} {number_text[split_at:]}")
    if 100 <= number < 1000 and number % 100:
        hundreds = number // 100
        hundred_words = "cento" if hundreds == 1 else ITALIAN_SMALL_NUMBERS[hundreds] + "cento"
        labels.append(f"{prefix} {hundred_words} e {italian_number_words(number % 100, spaced=True)}")
    return list(dict.fromkeys(labels))


def fuzzy_token_coverage(question_tokens: set[str], label_tokens: set[str]) -> float:
    """Measure how much of a label survives small transcription errors."""
    if not label_tokens:
        return 0.0
    similarities: list[float] = []
    for label_token in label_tokens:
        if label_token.isdigit():
            similarities.append(1.0 if label_token in question_tokens else 0.0)
            continue
        best = max(
            (SequenceMatcher(None, label_token, question_token).ratio() for question_token in question_tokens),
            default=0.0,
        )
        similarities.append(best if best >= 0.68 else 0.0)
    return sum(similarities) / len(similarities)


def get_locations() -> list[dict[str, Any]]:
    with db_connect() as connection:
        rows = connection.execute(
            """
            SELECT id, canonical_name, aliases, building, floor, room,
                   directions, accessible_directions, notes, description,
                   services, keywords, example_questions
            FROM locations
            WHERE active = 1
            ORDER BY canonical_name
            """
        ).fetchall()
    return [dict(row) for row in rows]


def build_search_document(location: dict[str, Any]) -> str:
    """Build the factual text indexed by lexical and semantic retrieval."""
    aliases = ", ".join(part.strip() for part in location.get("aliases", "").split("|") if part.strip())
    services = ", ".join(part.strip() for part in location.get("services", "").split("|") if part.strip())
    examples = " ".join(part.strip() for part in location.get("example_questions", "").split("|") if part.strip())
    parts = [
        location.get("canonical_name", ""),
        aliases,
        location.get("room", ""),
        location.get("building", ""),
        location.get("floor", ""),
        location.get("description", ""),
        services,
        location.get("keywords", ""),
        examples,
    ]
    return ". ".join(part.strip(" .") for part in parts if str(part).strip()) + "."


def refresh_fts_index(connection: sqlite3.Connection) -> bool:
    """Refresh the optional SQLite full-text index without making it mandatory."""
    try:
        connection.execute(
            """
            CREATE VIRTUAL TABLE IF NOT EXISTS locations_fts USING fts5(
                location_id UNINDEXED,
                search_text,
                tokenize = 'unicode61 remove_diacritics 2'
            )
            """
        )
        connection.execute("DELETE FROM locations_fts")
        rows = connection.execute(
            """
            SELECT id, canonical_name, aliases, building, floor, room,
                   directions, accessible_directions, notes, description,
                   services, keywords, example_questions
            FROM locations WHERE active = 1
            """
        ).fetchall()
        connection.executemany(
            "INSERT INTO locations_fts(location_id, search_text) VALUES (?, ?)",
            [(row["id"], build_search_document(dict(row))) for row in rows],
        )
        return True
    except sqlite3.OperationalError:
        return False


def score_location(question: str, location: dict[str, Any]) -> float:
    question_normalized = normalize(question)
    question_tokens = useful_tokens(question)
    labels = [
        location["canonical_name"],
        *location["aliases"].split("|"),
        *room_labels(location.get("room", "")),
    ]
    best = 0.0
    for label in labels:
        label_normalized = normalize(label)
        label_tokens = useful_tokens(label)
        if label_normalized and label_normalized in question_normalized:
            # Prefer the most specific contained label. This avoids treating
            # "aula uno" (room 01) as equal to "aula uno uno cinque" (115).
            exact_score = 0.94 + min(0.06, len(label_normalized) / 200)
            best = max(best, exact_score)
            continue
        overlap = len(question_tokens & label_tokens) / max(1, len(label_tokens))
        fuzzy_coverage = fuzzy_token_coverage(question_tokens, label_tokens)
        similarity = SequenceMatcher(None, question_normalized, label_normalized).ratio()
        best = max(best, overlap * 0.55 + fuzzy_coverage * 0.30 + similarity * 0.15)
    return best


def local_matches(question: str) -> list[tuple[float, dict[str, Any]]]:
    matches = [(score_location(question, location), location) for location in get_locations()]
    return sorted(matches, key=lambda item: item[0], reverse=True)


def fts_scores(question: str) -> dict[int, float]:
    tokens = sorted(useful_tokens(question))
    if not tokens:
        return {}
    query = " OR ".join(f'"{token}"' for token in tokens)
    try:
        with db_connect() as connection:
            rows = connection.execute(
                """
                SELECT CAST(location_id AS INTEGER) AS location_id
                FROM locations_fts
                WHERE locations_fts MATCH ?
                ORDER BY bm25(locations_fts, 0.0, 1.0)
                LIMIT 8
                """,
                (query,),
            ).fetchall()
    except sqlite3.OperationalError:
        return {}
    return {int(row["location_id"]): 1.0 / (1.0 + index * 0.35) for index, row in enumerate(rows)}


def _normalized_vector(values: Any) -> list[float] | None:
    if not isinstance(values, list) or not values:
        return None
    try:
        vector = [float(value) for value in values]
    except (TypeError, ValueError):
        return None
    if not all(math.isfinite(value) for value in vector):
        return None
    norm = math.sqrt(sum(value * value for value in vector))
    if norm <= 0:
        return None
    return [value / norm for value in vector]


def request_embeddings(texts: list[str]) -> list[list[float]] | None:
    if not CONFIG.get("use_semantic_search", True) or not texts:
        return None
    url = str(CONFIG.get("embeddings_url", "")).strip()
    if not url:
        return None
    payload = {
        "model": CONFIG.get("embeddings_model", "local-embedding-model"),
        "input": texts,
    }
    headers = {"Content-Type": "application/json"}
    api_key = str(CONFIG.get("embeddings_api_key", "")).strip()
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers=headers,
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=CONFIG["request_timeout_seconds"]) as response:
            result = json.load(response)
        items = sorted(result["data"], key=lambda item: int(item.get("index", 0)))
        vectors = [_normalized_vector(item.get("embedding")) for item in items]
        if len(vectors) != len(texts) or any(vector is None for vector in vectors):
            return None
        return [vector for vector in vectors if vector is not None]
    except (urllib.error.URLError, TimeoutError, KeyError, TypeError, ValueError, json.JSONDecodeError):
        return None


def semantic_scores(question: str, locations: list[dict[str, Any]]) -> dict[int, float]:
    """Embed the question and cache only location documents that changed."""
    if not CONFIG.get("use_semantic_search", True) or not locations:
        return {}
    model_name = str(CONFIG.get("embeddings_model", "local-embedding-model"))
    documents = {location["id"]: build_search_document(location) for location in locations}
    hashes = {
        location_id: hashlib.sha256(f"{model_name}\0{text}".encode("utf-8")).hexdigest()
        for location_id, text in documents.items()
    }

    with EMBEDDING_LOCK:
        cached: dict[int, list[float]] = {}
        missing: list[int] = []
        with db_connect() as connection:
            for location in locations:
                row = connection.execute(
                    """
                    SELECT embedding FROM location_embeddings
                    WHERE location_id = ? AND model_name = ? AND content_hash = ?
                    """,
                    (location["id"], model_name, hashes[location["id"]]),
                ).fetchone()
                vector = None
                if row:
                    try:
                        vector = _normalized_vector(json.loads(row["embedding"]))
                    except (TypeError, json.JSONDecodeError):
                        vector = None
                if vector:
                    cached[location["id"]] = vector
                else:
                    missing.append(location["id"])

            query_text = (
                "Instruct: trova l'ambiente scolastico pertinente alla domanda. "
                f"Query: {question.strip()}"
            )
            texts = [query_text, *(documents[location_id] for location_id in missing)]
            generated = request_embeddings(texts)
            if not generated:
                return {}
            query_vector = generated[0]
            for location_id, vector in zip(missing, generated[1:]):
                cached[location_id] = vector
                connection.execute(
                    """
                    INSERT INTO location_embeddings(location_id, model_name, content_hash, embedding, updated_at)
                    VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)
                    ON CONFLICT(location_id) DO UPDATE SET
                        model_name = excluded.model_name,
                        content_hash = excluded.content_hash,
                        embedding = excluded.embedding,
                        updated_at = CURRENT_TIMESTAMP
                    """,
                    (location_id, model_name, hashes[location_id], json.dumps(vector, separators=(",", ":"))),
                )

        return {
            location_id: max(0.0, min(1.0, sum(a * b for a, b in zip(query_vector, vector))))
            for location_id, vector in cached.items()
            if len(vector) == len(query_vector)
        }


def hybrid_matches(question: str) -> list[dict[str, Any]]:
    locations = get_locations()
    lexical = {location["id"]: score_location(question, location) for location in locations}
    full_text = fts_scores(question)
    semantic = semantic_scores(question, locations)
    semantic_available = bool(semantic)
    matches: list[dict[str, Any]] = []
    for location in locations:
        lexical_score = lexical.get(location["id"], 0.0)
        semantic_score = semantic.get(location["id"], 0.0)
        full_text_score = full_text.get(location["id"], 0.0)
        if semantic_available:
            combined = lexical_score * 0.45 + semantic_score * 0.45 + full_text_score * 0.10
        else:
            combined = lexical_score * 0.88 + full_text_score * 0.12
        matches.append(
            {
                "location": location,
                "score": combined,
                "lexical_score": lexical_score,
                "semantic_score": semantic_score,
                "fts_score": full_text_score,
                "semantic_available": semantic_available,
            }
        )
    return sorted(matches, key=lambda item: item["score"], reverse=True)


def service_available(url: str, health_path: str | None = None) -> bool:
    if not url:
        return False
    target = url.rstrip("/") + (health_path or "")
    try:
        with urllib.request.urlopen(target, timeout=1.2) as response:
            return 200 <= response.status < 500
    except (urllib.error.URLError, TimeoutError, ValueError):
        return False


def llama_choose_location(question: str, locations: list[dict[str, Any]]) -> tuple[int | None, str]:
    if not CONFIG.get("use_llama_for_ambiguity"):
        return None, "unavailable"
    if not service_available(str(CONFIG.get("llama_url", "")), "/health"):
        return None, "unavailable"
    ids = [int(location["id"]) for location in locations]
    system = (
        "Sei un classificatore per un punto informazioni scolastico. Interpreta anche "
        "parafrasi ed errori plausibili di trascrizione, ma usa soltanto i candidati forniti. "
        "Non inventare ambienti, servizi o posizioni. Se i dati non bastano o più candidati "
        "sono plausibili, restituisci location_id null e confidence low. Usa confidence high "
        "quando la domanda cita direttamente un servizio del candidato, medium per una "
        "parafrasi ragionevole e low soltanto quando serve davvero un chiarimento. Se la "
        "stessa domanda contiene due bisogni riferiti a candidati diversi, non sceglierne uno: "
        "restituisci null e low."
    )
    candidates = [
        {
            "location_id": location["id"],
            "name": location["canonical_name"],
            "room": location["room"],
            "description": location.get("description", ""),
            "services": location.get("services", "").split("|") if location.get("services") else [],
            "keywords": location.get("keywords", ""),
        }
        for location in locations
    ]
    payload = {
        "model": CONFIG.get("llama_model", "local-model"),
        "temperature": 0,
        "max_tokens": 64,
        "reasoning_effort": "none",
        "chat_template_kwargs": {"enable_thinking": False},
        "messages": [
            {"role": "system", "content": system},
            {
                "role": "user",
                "content": json.dumps({"question": question, "candidates": candidates}, ensure_ascii=False),
            },
        ],
        "response_format": {
            # llama.cpp build 11046 applies the supplied schema with json_object.
            "type": "json_object",
            "schema": {
                "type": "object",
                "properties": {
                    "location_id": {"enum": [None, *ids]},
                    "confidence": {"enum": ["high", "medium", "low"]},
                },
                "required": ["location_id", "confidence"],
                "additionalProperties": False,
            },
        },
    }
    request = urllib.request.Request(
        CONFIG["llama_url"].rstrip("/") + "/v1/chat/completions",
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {CONFIG.get('llama_api_key', '')}",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=CONFIG["request_timeout_seconds"]) as response:
            result = json.load(response)
        content = result["choices"][0]["message"]["content"]
        selection = json.loads(content)
        chosen = selection.get("location_id")
        confidence = str(selection.get("confidence", "low"))
        chosen_id = int(chosen) if chosen is not None else None
        return (chosen_id if chosen_id in ids else None), confidence
    except (urllib.error.URLError, TimeoutError, KeyError, IndexError, TypeError, ValueError, json.JSONDecodeError):
        return None, "unavailable"


def location_summary(location: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": location["id"],
        "name": location["canonical_name"],
        "building": location["building"],
        "floor": location["floor"],
        "room": location["room"],
    }


def successful_answer(question: str, selected: dict[str, Any], accessible: bool, method: str) -> dict[str, Any]:
    directions = selected["accessible_directions"] if accessible and selected["accessible_directions"] else selected["directions"]
    room_part = f", {selected['room']}" if selected["room"] else ""
    answer = f"{selected['canonical_name']} si trova in {selected['building']}, {selected['floor']}{room_part}. {directions}"
    return {
        "status": "ok",
        "answer": answer,
        "transcript": question,
        "matched_location": location_summary(selected),
        "match_method": method,
        "accessible": accessible,
    }


def answer_question(question: str, accessible: bool) -> dict[str, Any]:
    question = question.strip()
    if not question:
        return {"status": "invalid", "answer": "Non ho ricevuto una domanda."}

    matches = hybrid_matches(question)
    if not matches:
        return {"status": "not_found", "answer": "L'archivio degli ambienti è vuoto.", "transcript": question}

    best = matches[0]
    second = matches[1] if len(matches) > 1 else {"score": 0.0, "lexical_score": 0.0, "semantic_score": 0.0}
    score_gap = best["score"] - second["score"]
    lexical_matches = sorted(matches, key=lambda item: item["lexical_score"], reverse=True)
    lexical_best = lexical_matches[0]
    lexical_second = lexical_matches[1] if len(lexical_matches) > 1 else {"lexical_score": 0.0}
    lexical_gap = lexical_best["lexical_score"] - lexical_second["lexical_score"]
    semantic_matches_ranked = sorted(matches, key=lambda item: item["semantic_score"], reverse=True)
    semantic_best = semantic_matches_ranked[0]
    semantic_second = semantic_matches_ranked[1] if len(semantic_matches_ranked) > 1 else {"semantic_score": 0.0}
    semantic_gap = semantic_best["semantic_score"] - semantic_second["semantic_score"]

    # Exact names, aliases and room identifiers remain deterministic.
    if lexical_best["lexical_score"] >= 0.94 and lexical_gap >= 0.01:
        return successful_answer(question, lexical_best["location"], accessible, "exact")

    # Strong fuzzy matches are also safe when clearly separated from the rest.
    if lexical_best["lexical_score"] >= 0.68 and lexical_gap >= 0.10:
        return successful_answer(question, lexical_best["location"], accessible, "fuzzy")

    # Agreement between lexical and semantic retrieval is stronger than either signal alone.
    if (
        best["semantic_available"]
        and best["lexical_score"] >= 0.42
        and best["semantic_score"] >= 0.55
        and score_gap >= 0.07
    ):
        return successful_answer(question, best["location"], accessible, "hybrid")

    # Two almost identical semantic matches represent two plausible intentions;
    # a generative model must not break this tie by guessing.
    if (
        semantic_best["semantic_available"]
        and semantic_best["semantic_score"] >= 0.50
        and semantic_second["semantic_score"] >= 0.50
        and semantic_gap < 0.035
    ):
        ambiguous = semantic_matches_ranked[:2]
        options = [location_summary(item["location"]) for item in ambiguous]
        return {
            "status": "clarification_required",
            "answer": f"La domanda può riferirsi a {options[0]['name']} oppure a {options[1]['name']}. Quale intendi?",
            "options": options,
            "suggestions": [option["name"] for option in options],
            "transcript": question,
            "match_method": "semantic_tie",
        }

    # With semantic retrieval use only the best candidates. Without it let Llama
    # inspect the small complete directory so a weak lexical score cannot hide the answer.
    llama_candidates = [item["location"] for item in matches[:3]] if best["semantic_available"] else get_locations()
    chosen_id, llama_confidence = llama_choose_location(question, llama_candidates)
    if chosen_id is not None and llama_confidence in {"high", "medium"}:
        selected = next((location for location in llama_candidates if location["id"] == chosen_id), None)
        if selected:
            return successful_answer(question, selected, accessible, "llama_rerank")

    # If Llama is offline, a very clear semantic lead can still answer locally.
    if (
        llama_confidence in {"unavailable", "low"}
        and semantic_best["semantic_available"]
        and semantic_best["semantic_score"] >= 0.50
        and semantic_gap >= 0.06
    ):
        return successful_answer(question, semantic_best["location"], accessible, "semantic")

    viable = [
        item for item in matches
        if item["lexical_score"] >= 0.24 or item["semantic_score"] >= 0.48 or item["fts_score"] >= 0.70
    ][:3]
    if len(viable) >= 2:
        options = [location_summary(item["location"]) for item in viable]
        names = ", ".join(option["name"] for option in options)
        return {
            "status": "clarification_required",
            "answer": f"Ho trovato più possibilità: {names}. Quale intendi?",
            "options": options,
            "suggestions": [option["name"] for option in options],
            "transcript": question,
            "match_method": "clarification",
        }

    return {
        "status": "not_found",
        "answer": "Non ho trovato con certezza questo ambiente. Puoi indicare il nome, il numero dell'aula o il servizio che cerchi?",
        "suggestions": [
            item["location"]["canonical_name"]
            for item in matches[:3]
            if item["lexical_score"] >= 0.20 or item["semantic_score"] >= 0.45
        ],
        "transcript": question,
        "match_method": "none",
    }


def whisper_vocabulary_prompt() -> str:
    entries = []
    for location in get_locations():
        label = location["canonical_name"]
        if location["room"]:
            label += f", {location['room']}"
        entries.append(label)
    prompt = "Punto informazioni scolastico. Ambienti: " + "; ".join(entries) + "."
    return prompt[:1200]


def build_multipart_audio(data: bytes, content_type: str) -> tuple[bytes, str]:
    boundary = f"----school-assistant-{uuid.uuid4().hex}"
    extension = "webm" if "webm" in content_type else "wav"
    chunks = [
        f"--{boundary}\r\n".encode(),
        f'Content-Disposition: form-data; name="file"; filename="recording.{extension}"\r\n'.encode(),
        f"Content-Type: {content_type}\r\n\r\n".encode(),
        data,
        b"\r\n",
        f"--{boundary}\r\n".encode(),
        b'Content-Disposition: form-data; name="language"\r\n\r\nit\r\n',
        f"--{boundary}\r\n".encode(),
        b'Content-Disposition: form-data; name="response_format"\r\n\r\njson\r\n',
        f"--{boundary}\r\n".encode(),
        b'Content-Disposition: form-data; name="prompt"\r\n\r\n',
        whisper_vocabulary_prompt().encode("utf-8"),
        b"\r\n",
        f"--{boundary}--\r\n".encode(),
    ]
    return b"".join(chunks), f"multipart/form-data; boundary={boundary}"


def transcribe_audio(audio: bytes, content_type: str) -> str:
    """Send one audio recording to the local Whisper service."""
    body, multipart_type = build_multipart_audio(audio, content_type)
    request = urllib.request.Request(
        CONFIG["whisper_url"],
        data=body,
        headers={"Content-Type": multipart_type},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=CONFIG["request_timeout_seconds"]) as response:
        result = json.load(response)
    text = result.get("text") or result.get("transcription") or result.get("result")
    if not text:
        raise ValueError("missing_transcript")
    return str(text).strip()


def synthesize_with_macos(text: str) -> bytes:
    """Create a 16 kHz mono PCM WAV using the Italian macOS voice."""
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise RuntimeError("ffmpeg_not_found")

    with tempfile.TemporaryDirectory(prefix="school-assistant-tts-") as temporary:
        aiff_path = Path(temporary) / "speech.aiff"
        wav_path = Path(temporary) / "speech.wav"
        subprocess.run(
            ["/usr/bin/say", "-v", "Alice", "-o", str(aiff_path), text],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            timeout=CONFIG["request_timeout_seconds"],
        )
        subprocess.run(
            [
                ffmpeg,
                "-hide_banner",
                "-loglevel", "error",
                "-y",
                "-i", str(aiff_path),
                "-ar", "16000",
                "-ac", "1",
                "-c:a", "pcm_s16le",
                str(wav_path),
            ],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            timeout=CONFIG["request_timeout_seconds"],
        )
        return wav_path.read_bytes()


def synthesize_speech(text: str) -> tuple[bytes, str]:
    """Prefer Piper when available, otherwise use the built-in macOS voice."""
    request = urllib.request.Request(
        CONFIG["piper_url"],
        data=json.dumps({"text": text}).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=CONFIG["request_timeout_seconds"]) as response:
            audio = response.read()
            response_type = response.headers.get_content_type()
        if not audio or not response_type.startswith("audio/"):
            raise ValueError("invalid_piper_response")
        return audio, response_type
    except (urllib.error.URLError, TimeoutError, ValueError):
        return synthesize_with_macos(text), "audio/wav"


class AssistantHandler(BaseHTTPRequestHandler):
    server_version = "SchoolAssistant/0.1"

    def log_message(self, format_string: str, *args: Any) -> None:
        # Intentionally avoid logging request bodies or transcripts.
        sys.stderr.write(f"{self.address_string()} - {format_string % args}\n")

    def send_json(self, payload: dict[str, Any] | list[Any], status: int = 200) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(body)

    def read_body(self, maximum: int | None = None) -> bytes:
        length = int(self.headers.get("Content-Length", "0"))
        if maximum is not None and length > maximum:
            raise ValueError("request_too_large")
        return self.rfile.read(length)

    def do_GET(self) -> None:
        if self.path == "/api/health":
            self.send_json(
                {
                    "status": "ok",
                    "school_name": CONFIG["school_name"],
                    "services": {
                        "database": True,
                        "llama": service_available(CONFIG["llama_url"], "/health"),
                        "embeddings": service_available(str(CONFIG.get("embeddings_url", "")).rsplit("/v1/", 1)[0], "/health"),
                        "whisper": service_available(CONFIG["whisper_url"].rsplit("/", 1)[0] + "/"),
                        "piper": service_available(CONFIG["piper_url"].rsplit("/", 1)[0], "/info"),
                    },
                    "browser_tts_fallback": bool(CONFIG.get("browser_tts_fallback", True)),
                }
            )
            return
        if self.path == "/api/locations":
            locations = [
                {
                    "name": item["canonical_name"],
                    "building": item["building"],
                    "floor": item["floor"],
                    "room": item["room"],
                }
                for item in get_locations()
            ]
            self.send_json(locations)
            return
        self.serve_static()

    def do_POST(self) -> None:
        try:
            if self.path == "/api/query":
                data = json.loads(self.read_body(64 * 1024))
                self.send_json(answer_question(str(data.get("text", "")), bool(data.get("accessible", False))))
                return
            if self.path == "/api/transcribe":
                self.handle_transcription()
                return
            if self.path == "/api/device/query":
                self.handle_device_query()
                return
            if self.path == "/api/device/respond":
                self.handle_device_response()
                return
            if self.path == "/api/speak":
                self.handle_speech()
                return
            self.send_json({"error": "Endpoint non trovato"}, HTTPStatus.NOT_FOUND)
        except ValueError as error:
            status = HTTPStatus.REQUEST_ENTITY_TOO_LARGE if str(error) == "request_too_large" else HTTPStatus.BAD_REQUEST
            self.send_json({"error": "Richiesta non valida"}, status)
        except json.JSONDecodeError:
            self.send_json({"error": "JSON non valido"}, HTTPStatus.BAD_REQUEST)

    def handle_transcription(self) -> None:
        maximum = int(CONFIG["max_audio_megabytes"]) * 1024 * 1024
        audio = self.read_body(maximum)
        if not audio:
            self.send_json({"error": "Registrazione vuota"}, HTTPStatus.BAD_REQUEST)
            return
        content_type = self.headers.get("Content-Type", "audio/webm").split(";", 1)[0]
        try:
            self.send_json({"text": transcribe_audio(audio, content_type)})
        except (urllib.error.URLError, TimeoutError, ValueError, json.JSONDecodeError):
            self.send_json(
                {"error": "Il servizio di trascrizione locale non è disponibile. Puoi usare la domanda scritta."},
                HTTPStatus.SERVICE_UNAVAILABLE,
            )

    def handle_device_query(self) -> None:
        maximum = int(CONFIG["max_audio_megabytes"]) * 1024 * 1024
        audio = self.read_body(maximum)
        if not audio:
            self.send_json({"error": "Registrazione vuota"}, HTTPStatus.BAD_REQUEST)
            return
        content_type = self.headers.get("Content-Type", "audio/wav").split(";", 1)[0]
        try:
            transcript = transcribe_audio(audio, content_type)
            self.send_json(answer_question(transcript, accessible=False))
        except (urllib.error.URLError, TimeoutError, ValueError, json.JSONDecodeError):
            self.send_json(
                {"error": "Il servizio di trascrizione locale non è disponibile."},
                HTTPStatus.SERVICE_UNAVAILABLE,
            )

    def handle_device_response(self) -> None:
        maximum = int(CONFIG["max_audio_megabytes"]) * 1024 * 1024
        recording = self.read_body(maximum)
        if not recording:
            self.send_json({"error": "Registrazione vuota"}, HTTPStatus.BAD_REQUEST)
            return

        content_type = self.headers.get("Content-Type", "audio/wav").split(";", 1)[0]
        try:
            transcript = transcribe_audio(recording, content_type)
            result = answer_question(transcript, accessible=False)
            answer = str(result["answer"])
            speech, speech_type = synthesize_speech(answer)

            print(f"Domanda ESP32: {transcript}", flush=True)
            print(f"Risposta ESP32: {answer}", flush=True)

            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", speech_type)
            self.send_header("Content-Length", str(len(speech)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Assistant-Status", str(result.get("status", "unknown")))
            self.end_headers()
            self.wfile.write(speech)
        except (urllib.error.URLError, TimeoutError, ValueError, json.JSONDecodeError):
            self.send_json(
                {"error": "Il servizio di trascrizione locale non è disponibile."},
                HTTPStatus.SERVICE_UNAVAILABLE,
            )
        except (KeyError, OSError, RuntimeError, subprocess.SubprocessError):
            self.send_json(
                {"error": "La risposta vocale non può essere generata."},
                HTTPStatus.SERVICE_UNAVAILABLE,
            )

    def handle_speech(self) -> None:
        data = json.loads(self.read_body(64 * 1024))
        text = str(data.get("text", "")).strip()
        if not text:
            self.send_json({"error": "Testo mancante"}, HTTPStatus.BAD_REQUEST)
            return
        try:
            audio, response_type = synthesize_speech(text)
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", response_type)
            self.send_header("Content-Length", str(len(audio)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(audio)
        except (OSError, RuntimeError, subprocess.SubprocessError):
            self.send_json({"error": "Sintesi vocale non disponibile", "browser_fallback": True}, HTTPStatus.SERVICE_UNAVAILABLE)

    def serve_static(self) -> None:
        route = self.path.split("?", 1)[0]
        relative = "index.html" if route == "/" else route.lstrip("/")
        candidate = (WEB_ROOT / relative).resolve()
        if WEB_ROOT.resolve() not in candidate.parents and candidate != WEB_ROOT.resolve():
            self.send_error(HTTPStatus.FORBIDDEN)
            return
        if not candidate.is_file():
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        body = candidate.read_bytes()
        content_type = mimetypes.guess_type(candidate.name)[0] or "application/octet-stream"
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", f"{content_type}; charset=utf-8" if content_type.startswith("text/") else content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-cache")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Content-Security-Policy", "default-src 'self'; media-src 'self' blob:; style-src 'self'; script-src 'self'; connect-src 'self'")
        self.end_headers()
        self.wfile.write(body)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Assistente scolastico locale")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", default=8000, type=int)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    initialize_database()
    server = ThreadingHTTPServer((args.host, args.port), AssistantHandler)
    print(f"Assistente scolastico disponibile su http://{args.host}:{args.port}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
