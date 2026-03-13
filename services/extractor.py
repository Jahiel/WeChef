"""Service d'extraction de recette depuis une URL vidéo (TikTok/Instagram).

Isole toute la logique yt-dlp + Gemini pour garder main.py propre.
"""
from __future__ import annotations

import json
import subprocess
import os
from typing import Any

from google import genai
from google.genai import types

YT_DLP_PATH = os.getenv("YT_DLP_PATH", "/usr/bin/yt-dlp")


def fetch_video_metadata(url: str) -> dict[str, Any]:
    """Lance yt-dlp et retourne les métadonnées JSON de la vidéo."""
    result = subprocess.run(
        [YT_DLP_PATH, "--skip-download", "-j", url],
        capture_output=True,
        text=True,
        timeout=30,
    )
    if result.returncode != 0:
        raise RuntimeError(f"yt-dlp error: {result.stderr[:500]}")
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError("Métadonnées vidéo invalides (JSON malformé)") from exc


def parse_prep_time(raw: Any) -> int | None:
    """Convertit prep_time renvoyé par le LLM (str ou int) en entier de minutes."""
    if raw is None:
        return None
    # Si c'est déjà un int
    if isinstance(raw, int):
        return max(raw, 0)
    # Si c'est une chaîne comme "20 min" ou "1h30"
    s = str(raw).strip().lower()
    import re
    # Cas "1h30" ou "1h"
    hm = re.match(r"(\d+)\s*h(?:eure)?s?\s*(\d*)\s*m?", s)
    if hm:
        hours = int(hm.group(1))
        mins = int(hm.group(2)) if hm.group(2) else 0
        return hours * 60 + mins
    # Cas "30 min" ou "30"
    m = re.match(r"(\d+)", s)
    if m:
        return int(m.group(1))
    return None


def extract_recipe_with_llm(client_gemini: genai.Client, description: str, video_title: str) -> dict[str, Any]:
    """Envoie la description au LLM Gemini et retourne la recette structurée."""
    prompt = f"""Tu es un assistant culinaire. Extrait la recette depuis ce texte de vidéo.
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
    response = client_gemini.models.generate_content(
        model="gemini-2.5-flash-lite",
        contents=prompt,
        config=types.GenerateContentConfig(
            response_mime_type="application/json",
        ),
    )
    recipe_data: dict = json.loads(response.text)

    # Normalise ingredients si le LLM renvoie des strings brutes
    ingredients = recipe_data.get("ingredients", [])
    if ingredients and isinstance(ingredients[0], str):
        ingredients = [{"name": i, "quantity": None, "unit": None} for i in ingredients]
        recipe_data["ingredients"] = ingredients

    # Normalise prep_time
    recipe_data["prep_time"] = parse_prep_time(recipe_data.get("prep_time"))

    return recipe_data
