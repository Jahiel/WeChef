"""Service d'extraction de recette depuis une URL vidéo (TikTok/Instagram).

yt-dlp est exécuté de façon **non-bloquante** via asyncio.create_subprocess_exec
pour ne pas bloquer la boucle d'événements FastAPI pendant la récupération.

Chaîne LLM :
  1. Gemini 2.5 Flash Lite  (primaire, 3 tentatives avec backoff)
  2. Groq Llama 3.3 70B      (fallback si quota Gemini épuisé, clé GROQ_API_KEY)
  3. QuotaExceededError       (si les deux sont KO → HTTP 503)
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import time
from typing import Any

from google import genai
from google.genai import errors as genai_errors
from google.genai import types

logger = logging.getLogger(__name__)

YT_DLP_PATH = os.getenv("YT_DLP_PATH", "/usr/bin/yt-dlp")
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")

# Délais de retry exponentiel pour les erreurs 429 Gemini (en secondes)
_RETRY_DELAYS = [2, 5, 15]

# Prompt partagé entre Gemini et Groq
_RECIPE_PROMPT_TEMPLATE = """Tu es un assistant culinaire. Extrait la recette depuis ce texte de vidéo.
Si certaines informations manquent, déduis-les intelligemment.
Réponds UNIQUEMENT en JSON valide, en français, avec ce format exact :
{{
  "title": "...",
  "ingredients": [{{"name": "...", "quantity": "...", "unit": "..."}}],
  "steps": ["étape 1", "étape 2"],
  "servings": 4,
  "prep_time": 20
}}
Note: prep_time doit être un entier représentant le nombre de MINUTES.

Texte : \"\"\"{description}\"\"\"
Titre : {video_title}
"""


async def fetch_video_metadata(url: str) -> dict[str, Any]:
    """Lance yt-dlp de manière asynchrone et retourne les métadonnées JSON."""
    proc = await asyncio.create_subprocess_exec(
        YT_DLP_PATH, "--skip-download", "-j", url,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=45)
    except asyncio.TimeoutError as exc:
        proc.kill()
        raise RuntimeError("yt-dlp timeout (>45s)") from exc

    if proc.returncode != 0:
        raise RuntimeError(f"yt-dlp error: {stderr.decode()[:500]}")

    try:
        return json.loads(stdout.decode())
    except json.JSONDecodeError as exc:
        raise RuntimeError("Métadonnées vidéo invalides (JSON malformé)") from exc


def parse_prep_time(raw: Any) -> int | None:
    """Convertit prep_time renvoyé par le LLM (str ou int) en entier de minutes."""
    if raw is None:
        return None
    if isinstance(raw, int):
        return max(raw, 0)
    s = str(raw).strip().lower()
    hm = re.match(r"(\d+)\s*h(?:eure)?s?\s*(\d*)\s*m?", s)
    if hm:
        hours = int(hm.group(1))
        mins = int(hm.group(2)) if hm.group(2) else 0
        return hours * 60 + mins
    m = re.match(r"(\d+)", s)
    if m:
        return int(m.group(1))
    return None


def _normalize_recipe(recipe_data: dict) -> dict:
    """Normalise la sortie JSON du LLM (ingredients strings → objets, prep_time)."""
    ingredients = recipe_data.get("ingredients", [])
    if ingredients and isinstance(ingredients[0], str):
        ingredients = [{"name": i, "quantity": None, "unit": None} for i in ingredients]
        recipe_data["ingredients"] = ingredients
    recipe_data["prep_time"] = parse_prep_time(recipe_data.get("prep_time"))
    return recipe_data


def _is_quota_error(exc: Exception) -> bool:
    """Détecte une erreur de quota/rate-limit Gemini (429 / RESOURCE_EXHAUSTED)."""
    msg = str(exc).lower()
    return (
        isinstance(exc, (genai_errors.APIError, genai_errors.ClientError))
        and ("429" in msg or "resource_exhausted" in msg or "quota" in msg)
    ) or ("429" in msg or "resource_exhausted" in msg or "quota" in msg)


def _call_groq_llm(description: str, video_title: str) -> dict[str, Any]:
    """Appelle Groq (Llama 3.3 70B) comme fallback quand Gemini est KO.

    Utilise l'API OpenAI-compatible de Groq via le SDK `groq`.
    Raise RuntimeError si GROQ_API_KEY absent ou si l'appel échoue.
    """
    if not GROQ_API_KEY:
        raise RuntimeError("GROQ_API_KEY non configurée — impossible d'utiliser le fallback Groq")

    try:
        from groq import Groq  # import lazy pour ne pas créer de dépendance obligatoire
    except ImportError as exc:
        raise RuntimeError("Package 'groq' non installé. Lance : pip install groq") from exc

    prompt = _RECIPE_PROMPT_TEMPLATE.format(
        description=description[:3000],
        video_title=video_title,
    )

    client = Groq(api_key=GROQ_API_KEY)
    logger.info("Fallback Groq (llama-3.3-70b-versatile) activé")

    response = client.chat.completions.create(
        model="llama-3.3-70b-versatile",
        messages=[
            {"role": "system", "content": "Tu es un assistant culinaire expert. Réponds uniquement en JSON valide."},
            {"role": "user", "content": prompt},
        ],
        response_format={"type": "json_object"},
        temperature=0.3,
        max_tokens=2048,
    )

    raw_json = response.choices[0].message.content
    recipe_data: dict = json.loads(raw_json)
    return _normalize_recipe(recipe_data)


def extract_recipe_with_llm(
    client_gemini: genai.Client,
    description: str,
    video_title: str,
) -> dict[str, Any]:
    """Extrait la recette via Gemini, avec fallback automatique sur Groq.

    Chaîne :
      1. Gemini 2.5 Flash Lite (3 tentatives backoff 2s/5s/15s)
      2. Groq Llama 3.3 70B    (si GROQ_API_KEY présente)
      3. QuotaExceededError    (si tout échoue → HTTP 503 dans main.py)
    """
    prompt = _RECIPE_PROMPT_TEMPLATE.format(
        description=description[:3000],
        video_title=video_title,
    )

    last_exc: Exception | None = None
    for attempt, delay in enumerate(_RETRY_DELAYS, start=1):
        try:
            response = client_gemini.models.generate_content(
                model="gemini-2.5-flash-lite",
                contents=prompt,
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                ),
            )
            recipe_data: dict = json.loads(response.text)
            return _normalize_recipe(recipe_data)

        except Exception as exc:
            if _is_quota_error(exc):
                last_exc = exc
                logger.warning(
                    "Quota Gemini atteint (tentative %d/%d) — attente %ds",
                    attempt, len(_RETRY_DELAYS), delay,
                )
                if attempt < len(_RETRY_DELAYS):
                    time.sleep(delay)
                continue
            raise  # erreur non-quota : on remonte immédiatement

    # ── Gemini KO sur quota — tentative Groq ──
    logger.warning("Quota Gemini confirmé épuisé, basculement sur Groq")
    try:
        return _call_groq_llm(description, video_title)
    except Exception as groq_exc:
        logger.error("Groq fallback échoué aussi : %s", groq_exc)
        raise QuotaExceededError(
            f"Quota Gemini épuisé et fallback Groq indisponible : {groq_exc}"
        ) from last_exc


class QuotaExceededError(Exception):
    """Levée quand Gemini ET Groq sont tous les deux indisponibles."""
