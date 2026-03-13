"""Service de génération / recherche d'image pour une recette."""
from __future__ import annotations

import base64
import os
from typing import Optional

import httpx
from google import genai

UNSPLASH_KEY = os.environ.get("UNSPLASH_ACCESS_KEY")
_HTTP_HEADERS = {"User-Agent": "WeChef/1.0"}


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
        return title  # fallback : titre original


async def _fetch_unsplash(query: str) -> Optional[str]:
    """Cherche une image sur Unsplash et retourne un data-URI base64."""
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
                b64 = base64.b64encode(img_resp.content).decode()
                ctype = img_resp.headers.get("content-type", "image/jpeg")
                return f"data:{ctype};base64,{b64}"
        except Exception:
            return None
    return None


async def _fetch_picsum(title: str) -> Optional[str]:
    """Fallback: image aléatoire via picsum.photos."""
    seed = abs(hash(title)) % 1000
    async with httpx.AsyncClient(timeout=15, follow_redirects=True, headers=_HTTP_HEADERS) as client:
        try:
            resp = await client.get(f"https://picsum.photos/seed/{seed}/800/600")
            if resp.status_code == 200 and len(resp.content) > 10_000:
                b64 = base64.b64encode(resp.content).decode()
                return f"data:image/jpeg;base64,{b64}"
        except Exception:
            return None
    return None


async def generate_image_for_recipe(client_gemini: genai.Client, title: str) -> Optional[str]:
    """Point d'entrée : essaie Unsplash, puis Picsum en fallback."""
    english_query = await _translate_title(client_gemini, title)
    image = await _fetch_unsplash(english_query)
    if image:
        return image
    return await _fetch_picsum(title)
