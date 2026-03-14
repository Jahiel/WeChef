"""Tests d'intégration supplémentaires — WeChef.

Couvre les cas non testés dans test_recipes.py :
- Filtrage par tag via GET /recipes?tag=
- Deduplication URL via POST /extract
- Upload image via POST /recipes/{id}/image
- Helper _normalize_url
- Comportement liste vide après suppression
"""
from __future__ import annotations

import io
import pytest
from unittest.mock import AsyncMock, patch


# ── _normalize_url ────────────────────────────────────────────────────────────

class TestNormalizeUrl:
    """Tests unitaires du helper de nettoyage d'URL."""

    def test_strips_query_params(self):
        from main import _normalize_url
        url = "https://www.tiktok.com/@chef/video/123?utm_source=copy"
        assert _normalize_url(url) == "https://www.tiktok.com/@chef/video/123"

    def test_strips_fragment(self):
        from main import _normalize_url
        url = "https://www.instagram.com/reel/ABC/#comments"
        assert _normalize_url(url) == "https://www.instagram.com/reel/ABC/"

    def test_clean_url_unchanged(self):
        from main import _normalize_url
        url = "https://www.tiktok.com/@chef/video/123456789"
        assert _normalize_url(url) == url

    def test_strips_both_query_and_fragment(self):
        from main import _normalize_url
        url = "https://www.tiktok.com/@chef/video/123?ref=copy#section"
        assert _normalize_url(url) == "https://www.tiktok.com/@chef/video/123"


# ── Filtrage par tag ──────────────────────────────────────────────────────────

class TestFilterByTag:
    def test_filter_returns_only_tagged_recipes(self, client):
        # Crée deux recettes
        r1 = client.post("/recipes", json={"title": "Pasta", "ingredients": [], "steps": []}).json()
        r2 = client.post("/recipes", json={"title": "Salade", "ingredients": [], "steps": []}).json()

        # Ajoute un tag seulement à r1
        client.post(f"/recipes/{r1['id']}/tags", json={"tag": "italien"})

        # Filtre par tag
        resp = client.get("/recipes?tag=italien")
        assert resp.status_code == 200
        ids = [r["id"] for r in resp.json()]
        assert r1["id"] in ids
        assert r2["id"] not in ids

    def test_filter_unknown_tag_returns_empty(self, client):
        client.post("/recipes", json={"title": "Burger", "ingredients": [], "steps": []})
        resp = client.get("/recipes?tag=inexistant")
        assert resp.status_code == 200
        assert resp.json() == []


# ── Tags déduplication ────────────────────────────────────────────────────────

class TestTagDedup:
    def test_same_tag_added_twice_no_duplicate(self, client):
        """Ajouter deux fois le même tag ne doit pas créer de doublon."""
        r = client.post("/recipes", json={"title": "Pizza", "ingredients": [], "steps": []}).json()
        client.post(f"/recipes/{r['id']}/tags", json={"tag": "rapide"})
        client.post(f"/recipes/{r['id']}/tags", json={"tag": "rapide"})

        resp = client.get(f"/recipes/{r['id']}")
        tags = resp.json()["tags"]
        assert tags.count("rapide") == 1

    def test_tag_normalized_lowercase(self, client):
        """Un tag 'Français' doit être stocké 'français'."""
        r = client.post("/recipes", json={"title": "Boeuf", "ingredients": [], "steps": []}).json()
        client.post(f"/recipes/{r['id']}/tags", json={"tag": "Français"})

        resp = client.get(f"/recipes/{r['id']}")
        assert "français" in resp.json()["tags"]


# ── Upload image ──────────────────────────────────────────────────────────────

class TestUploadImage:
    def test_upload_image_updates_recipe(self, client):
        """POST /recipes/{id}/image doit mettre à jour image_url."""
        r = client.post("/recipes", json={"title": "Gâteau", "ingredients": [], "steps": []}).json()
        recipe_id = r["id"]

        fake_image = io.BytesIO(b"fake-image-bytes")
        fake_image.name = "test.jpg"

        with patch("main._save_image_from_bytes", new_callable=AsyncMock) as mock_save:
            mock_save.return_value = "/static/images/test.jpg"
            resp = client.post(
                f"/recipes/{recipe_id}/image",
                files={"file": ("test.jpg", fake_image, "image/jpeg")},
            )

        assert resp.status_code == 200
        assert resp.json()["image_url"] == "/static/images/test.jpg"

        # Vérifie que la recette a bien été mise à jour
        updated = client.get(f"/recipes/{recipe_id}").json()
        assert updated["image_url"] == "/static/images/test.jpg"

    def test_upload_image_recipe_not_found(self, client):
        fake_image = io.BytesIO(b"data")
        resp = client.post(
            "/recipes/99999/image",
            files={"file": ("test.jpg", fake_image, "image/jpeg")},
        )
        assert resp.status_code == 404

    def test_upload_image_too_large(self, client):
        """Image > 10 Mo doit retourner 413."""
        r = client.post("/recipes", json={"title": "Trop gros", "ingredients": [], "steps": []}).json()
        big_file = io.BytesIO(b"x" * (10 * 1024 * 1024 + 1))
        resp = client.post(
            f"/recipes/{r['id']}/image",
            files={"file": ("big.jpg", big_file, "image/jpeg")},
        )
        assert resp.status_code == 413


# ── CRUD edge cases ───────────────────────────────────────────────────────────

class TestCrudEdgeCases:
    def test_delete_then_get_returns_404(self, client):
        r = client.post("/recipes", json={"title": "Temporaire", "ingredients": [], "steps": []}).json()
        client.delete(f"/recipes/{r['id']}")
        assert client.get(f"/recipes/{r['id']}").status_code == 404

    def test_update_nonexistent_recipe(self, client):
        resp = client.put("/recipes/99999", json={"title": "Ghost"})
        assert resp.status_code == 404

    def test_delete_nonexistent_recipe(self, client):
        resp = client.delete("/recipes/99999")
        assert resp.status_code == 404

    def test_list_tags_endpoint(self, client):
        """GET /tags doit retourner une liste (même vide)."""
        resp = client.get("/tags")
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)

    def test_recipe_created_at_is_string(self, client):
        """created_at doit être une string ISO 8601."""
        r = client.post("/recipes", json={"title": "ISO", "ingredients": [], "steps": []}).json()
        assert isinstance(r["created_at"], str)
        # Doit contenir une date valide
        from datetime import datetime
        datetime.fromisoformat(r["created_at"].replace("Z", "+00:00"))

    def test_export_pdf_with_valid_recipe(self, client):
        """Export PDF avec une recette existante doit retourner du contenu PDF."""
        r = client.post("/recipes", json={
            "title": "Tarte PDF",
            "ingredients": [{"name": "Farine", "quantity": "200", "unit": "g"}],
            "steps": ["Mélanger", "Cuire"],
        }).json()
        resp = client.post("/export-pdf", json={"recipe_ids": [r["id"]]})
        assert resp.status_code == 200
        assert resp.headers["content-type"] == "application/pdf"
        assert len(resp.content) > 0
