"""Tests unitaires des schémas Pydantic — WeChef.

Ces tests ne nécessitent aucune DB ni client HTTP.
Ils vérifient la logique de validation et de normalisation des données.
"""
from __future__ import annotations

import pytest
from pydantic import ValidationError
from urllib.parse import urlparse

from schemas import (
    Ingredient,
    RecipeCreate,
    RecipeUpdate,
    ExtractRequest,
    TagAddRequest,
    ExportPDFRequest,
    _parse_prep_time,
)


# ── _parse_prep_time ─────────────────────────────────────────────────────────

class TestParsePrepTime:
    """Tests exhaustifs du helper de parsing de durée."""

    @pytest.mark.parametrize("raw,expected", [
        (None, None),
        ("", None),
        (0, 0),
        (30, 30),
        (120, 120),
        ("30", 30),
        ("0", 0),
        ("30 min", 30),
        ("30min", 30),
        ("45 minutes", 45),
        ("1h", 60),
        ("2h", 120),
        ("1 heure", 60),
        ("2 heures", 120),
        ("1h30", 90),
        ("1h30min", 90),
        ("2h15", 135),
        ("2 heures 15", 135),
        ("invalid", None),
        ("abc min", None),
    ])
    def test_parse_prep_time_parametrize(self, raw, expected):
        assert _parse_prep_time(raw) == expected

    def test_negative_int_clamped_to_zero(self):
        assert _parse_prep_time(-5) == 0


# ── Ingredient ───────────────────────────────────────────────────────────────

class TestIngredient:
    def test_valid_ingredient(self):
        ing = Ingredient(name="Farine", quantity="200", unit="g")
        assert ing.name == "Farine"
        assert ing.quantity == "200"
        assert ing.unit == "g"

    def test_ingredient_optional_fields(self):
        ing = Ingredient(name="Sel")
        assert ing.quantity is None
        assert ing.unit is None

    def test_ingredient_empty_name_raises(self):
        with pytest.raises(ValidationError):
            Ingredient(name="")

    def test_ingredient_name_too_long_raises(self):
        with pytest.raises(ValidationError):
            Ingredient(name="x" * 201)


# ── RecipeCreate ─────────────────────────────────────────────────────────────

class TestRecipeCreate:
    def test_minimal_valid_recipe(self):
        r = RecipeCreate(title="Omelette")
        assert r.title == "Omelette"
        assert r.ingredients == []
        assert r.steps == []
        assert r.servings == 4
        assert r.prep_time is None

    def test_empty_title_raises(self):
        with pytest.raises(ValidationError):
            RecipeCreate(title="")

    def test_title_too_long_raises(self):
        with pytest.raises(ValidationError):
            RecipeCreate(title="A" * 201)

    def test_servings_bounds(self):
        with pytest.raises(ValidationError):
            RecipeCreate(title="Test", servings=0)
        with pytest.raises(ValidationError):
            RecipeCreate(title="Test", servings=101)
        assert RecipeCreate(title="Test", servings=1).servings == 1
        assert RecipeCreate(title="Test", servings=100).servings == 100

    def test_prep_time_string_normalized(self):
        r = RecipeCreate(title="Test", prep_time="1h30")  # type: ignore[arg-type]
        assert r.prep_time == 90

    def test_prep_time_none_ok(self):
        r = RecipeCreate(title="Test", prep_time=None)
        assert r.prep_time is None

    def test_prep_time_negative_raises(self):
        with pytest.raises(ValidationError):
            RecipeCreate(title="Test", prep_time=-10)

    def test_with_ingredients_and_steps(self):
        r = RecipeCreate(
            title="Quiche",
            ingredients=[{"name": "Oeufs", "quantity": "3", "unit": "pièces"}],
            steps=["Mélanger", "Cuire"],
            servings=4,
            prep_time=30,
        )
        assert len(r.ingredients) == 1
        assert r.ingredients[0].name == "Oeufs"
        assert len(r.steps) == 2


# ── RecipeUpdate ─────────────────────────────────────────────────────────────

class TestRecipeUpdate:
    def test_all_optional(self):
        u = RecipeUpdate()
        assert u.title is None
        assert u.ingredients is None
        assert u.steps is None

    def test_partial_update(self):
        u = RecipeUpdate(title="Nouveau titre", servings=2)
        assert u.title == "Nouveau titre"
        assert u.servings == 2
        assert u.steps is None

    def test_prep_time_normalized_in_update(self):
        u = RecipeUpdate(prep_time="2h")  # type: ignore[arg-type]
        assert u.prep_time == 120


# ── ExtractRequest ───────────────────────────────────────────────────────────

# NOTE CodeQL — on ne fait AUCUNE comparaison de substring de domaine dans les
# assertions. On vérifie uniquement que la validation Pydantic réussit (pas de
# ValidationError) et que le scheme est correct. La logique de filtrage par
# domaine est testée via les cas de rejet ci-dessous, pas via des assertions
# positives sur le contenu de l'URL.

class TestExtractRequest:

    # ─ Cas acceptes ──────────────────────────────────────────────────────────

    def test_valid_tiktok_url_accepted(self):
        """Une URL TikTok valide ne doit pas lever de ValidationError."""
        # On vérifie juste que la construction réussit et que le scheme est https
        r = ExtractRequest(url="https://www.tiktok.com/@chef/video/123456")
        assert urlparse(r.url).scheme == "https"

    def test_valid_instagram_url_accepted(self):
        """Une URL Instagram valide ne doit pas lever de ValidationError."""
        r = ExtractRequest(url="https://www.instagram.com/reel/ABC123/")
        assert urlparse(r.url).scheme == "https"

    def test_valid_vm_tiktok_url_accepted(self):
        """Une URL vm.tiktok.com valide ne doit pas lever de ValidationError."""
        r = ExtractRequest(url="https://vm.tiktok.com/ZMabcdef/")
        assert urlparse(r.url).scheme == "https"

    def test_accepted_url_is_a_string(self):
        """L'URL retournée après validation doit être une string non vide."""
        r = ExtractRequest(url="https://www.tiktok.com/@chef/video/999")
        assert isinstance(r.url, str) and len(r.url) > 0

    def test_url_stripped_of_whitespace(self):
        """Les espaces autour de l'URL doivent être supprimés par le validator."""
        r = ExtractRequest(url="  https://www.tiktok.com/@chef/video/123  ")
        assert r.url == r.url.strip()

    # ─ Cas rejetes ──────────────────────────────────────────────────────────

    def test_youtube_url_rejected(self):
        with pytest.raises(ValidationError) as exc_info:
            ExtractRequest(url="https://youtube.com/watch?v=abc123")
        assert "TikTok ou Instagram" in str(exc_info.value)

    def test_random_domain_rejected(self):
        with pytest.raises(ValidationError):
            ExtractRequest(url="https://example.com/recipe/123")

    def test_too_short_url_rejected(self):
        with pytest.raises(ValidationError):
            ExtractRequest(url="https://")

    def test_evil_tiktok_in_query_rejected(self):
        """Domain spoof via query param doit être rejeté."""
        with pytest.raises(ValidationError):
            ExtractRequest(url="https://evil.com/redirect?to=tiktok.com")

    def test_evil_tiktok_subdomain_spoof_rejected(self):
        """evil-tiktok.com n'est pas un sous-domaine valide de tiktok.com."""
        with pytest.raises(ValidationError):
            ExtractRequest(url="https://evil-tiktok.com/video/123")


# ── TagAddRequest ─────────────────────────────────────────────────────────────

class TestTagAddRequest:
    def test_tag_lowercased(self):
        t = TagAddRequest(tag="VEGÉTARIEN")
        assert t.tag == "vegétarien"

    def test_tag_stripped(self):
        t = TagAddRequest(tag="  rapide  ")
        assert t.tag == "rapide"

    def test_empty_tag_raises(self):
        with pytest.raises(ValidationError):
            TagAddRequest(tag="")

    def test_tag_too_long_raises(self):
        with pytest.raises(ValidationError):
            TagAddRequest(tag="x" * 51)


# ── ExportPDFRequest ──────────────────────────────────────────────────────────

class TestExportPDFRequest:
    def test_valid_ids(self):
        r = ExportPDFRequest(recipe_ids=[1, 2, 3])
        assert r.recipe_ids == [1, 2, 3]

    def test_empty_list_raises(self):
        with pytest.raises(ValidationError):
            ExportPDFRequest(recipe_ids=[])
