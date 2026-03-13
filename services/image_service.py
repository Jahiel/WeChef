"""Service de génération/stockage d'image pour une recette.

Les images sont désormais sauvegardées sur le **système de fichiers**
(dossier static/images/) et non plus encodées en base64 dans la DB.
Cela réduit considérablement la taille de la base et améliore les perfs
de lecture (notamment pour le listing des recettes).
"""
from __future__ import annotations

import os
import uuid
from pathlib import Path
from typing import Optional

import httpx
from google import genai

UNSPLASH_KEY = os.environ.get("UNSPLASH_ACCESS_KEY")
_HTTP_HEADERS = {"User-Agent": "WeChef/1.0"}

# Répertoire de stockage des images — créé automatiquement au démarrage
IMAGES_DIR = Path(os.getenv("IMAGES_DIR", "static/images"))
IMAGES_DIR.mkdir(parents=True, exist_ok=True)


async def _translate_title(client_gemini: genai.Client, title: str) -> str:
    """Traduit un titre FR → EN via Gemini pour la recherche Unsplash."""
    try:
        resp = client_gemini.models.generate_content(
            model="gemini-2.5-flash-lite",
            contents=(
                f"Translate this French recipe title to English, "
                f"return ONLY the translation, nothing else: '{title}'"
            ),
        )
        return resp.text.strip().strip('"').strip("'")
    except Exception:
        return title


async def _save_image_from_bytes(content: bytes, content_type: str) -> str:
    """Sauvegarde des bytes image sur disque et retourne le chemin URL relatif."""
    ext = content_type.split("/")[-1].split("+")[0]  # "jpeg", "png", "webp"...
    if ext not in ("jpeg", "jpg", "png", "webp", "gif"):
        ext = "jpg"
    filename = f"{uuid.uuid4().hex}.{ext}"
    filepath = IMAGES_DIR / filename
    filepath.write_bytes(content)
    return f"/static/images/{filename}"  # URL servie par FastAPI StaticFiles


async def _fetch_unsplash(query: str) -> Optional[str]:
    """Cherche une image sur Unsplash et sauvegarde localement."""
    if not UNSPLASH_KEY:
        return None
    async with httpx.AsyncClient(timeout=20, follow_redirects=True, headers=_HTTP_HEADERS) as client:
        try:
            search_resp = await client.get(
                "https://api.unsplash.com/search/photos",
                params={"query": query, "per_page": 1, "orientation": "landscape",
                        "client_id": UNSPLASH_KEY},
            )
            if search_resp.status_code != 200:
                return None
            results = search_resp.json().get("results", [])
            if not results:
                return None
            img_url = results[0]["urls"]["regular"]
            img_resp = await client.get(img_url)
            if img_resp.status_code == 200 and len(img_resp.content) > 10_000:
                ctype = img_resp.headers.get("content-type", "image/jpeg").split(";")[0]
                return await _save_image_from_bytes(img_resp.content, ctype)
        except Exception:
            return None
    return None


async def _fetch_picsum(title: str) -> Optional[str]:
    """Fallback: image aléatoire via picsum.photos, sauvegardée localement."""
    seed = abs(hash(title)) % 1000
    async with httpx.AsyncClient(timeout=15, follow_redirects=True, headers=_HTTP_HEADERS) as client:
        try:
            resp = await client.get(f"https://picsum.photos/seed/{seed}/800/600")
            if resp.status_code == 200 and len(resp.content) > 10_000:
                return await _save_image_from_bytes(resp.content, "image/jpeg")
        except Exception:
            return None
    return None


async def generate_image_for_recipe(client_gemini: genai.Client, title: str) -> Optional[str]:
    """Point d'entrée : essaie Unsplash, puis Picsum en fallback.

    Retourne une URL relative (/static/images/xxx.jpg) ou None.
    """
    english_query = await _translate_title(client_gemini, title)
    image_path = await _fetch_unsplash(english_query)
    if image_path:
        return image_path
    return await _fetch_picsum(title)


def delete_image_file(image_url: Optional[str]) -> None:
    """Supprime le fichier image local lors de la suppression d'une recette."""
    if not image_url or not image_url.startswith("/static/images/"):
        return
    filepath = Path(image_url.lstrip("/"))
    if filepath.exists():
        filepath.unlink(missing_ok=True)
