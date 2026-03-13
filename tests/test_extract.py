"""Tests du service d'extraction — WeChef."""
from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, patch, MagicMock

from services.extractor import parse_prep_time, extract_recipe_with_llm


# ── Tests unitaires parse_prep_time ──────────────────────────────────────────

@pytest.mark.parametrize("raw,expected", [
    (None, None),
    (30, 30),
    (0, 0),
    ("30", 30),
    ("30 min", 30),
    ("30min", 30),
    ("1h", 60),
    ("1h30", 90),
    ("1h30min", 90),
    ("2 heures 15", 135),
    ("invalid", None),
])
def test_parse_prep_time(raw, expected):
    assert parse_prep_time(raw) == expected


# ── Tests intégration extract endpoint (mock yt-dlp + Gemini) ─────────────────

@pytest.mark.anyio
async def test_extract_duplicate(client):
    """Une URL déjà importée doit retourner 409."""
    from models import Recipe
    from sqlalchemy.orm import Session

    # Insère une recette existante avec cette URL
    with patch("main.fetch_video_metadata") as mock_meta, \
         patch("main.extract_recipe_with_llm") as mock_llm, \
         patch("main.generate_image_for_recipe", new_callable=AsyncMock) as mock_img:

        mock_meta.return_value = {"description": "desc", "title": "test"}
        mock_llm.return_value = {
            "title": "Test", "ingredients": [], "steps": [], "servings": 4, "prep_time": 10
        }
        mock_img.return_value = None

        resp1 = client.post("/extract", json={"url": "https://www.tiktok.com/@chef/video/123"})
        # Premier import réussit
        assert resp1.status_code in (200, 201)

        # Deuxième import → 409
        resp2 = client.post("/extract", json={"url": "https://www.tiktok.com/@chef/video/123"})
        assert resp2.status_code == 409


def test_extract_invalid_url(client):
    """URL non-TikTok/Instagram → 422 (validation Pydantic)."""
    resp = client.post("/extract", json={"url": "https://youtube.com/watch?v=abc"})
    assert resp.status_code == 422
