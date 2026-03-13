"""Schémas Pydantic v2 centralisés pour WeChef."""
from __future__ import annotations
from typing import Optional, List
from pydantic import BaseModel, Field, field_validator


# ── Ingrédients ──────────────────────────────────────────────────────────────

class Ingredient(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    quantity: Optional[str] = None
    unit: Optional[str] = None


# ── Tags ─────────────────────────────────────────────────────────────────────

class TagResponse(BaseModel):
    id: int
    name: str

    model_config = {"from_attributes": True}


# ── Recette ───────────────────────────────────────────────────────────────────

class RecipeCreate(BaseModel):
    title: str = Field(..., min_length=1, max_length=200)
    ingredients: List[Ingredient] = Field(default_factory=list)
    steps: List[str] = Field(default_factory=list)
    servings: int = Field(default=4, ge=1, le=100)
    prep_time: Optional[int] = Field(default=None, ge=0, description="Durée en minutes")
    image_url: Optional[str] = None


class RecipeUpdate(BaseModel):
    title: Optional[str] = Field(default=None, min_length=1, max_length=200)
    ingredients: Optional[List[Ingredient]] = None
    steps: Optional[List[str]] = None
    servings: Optional[int] = Field(default=None, ge=1, le=100)
    prep_time: Optional[int] = Field(default=None, ge=0)
    image_url: Optional[str] = None


class RecipeResponse(BaseModel):
    id: int
    title: str
    ingredients: List[Ingredient]
    steps: List[str]
    servings: int
    prep_time: Optional[int]
    tags: List[str]
    source_url: Optional[str]
    image_url: Optional[str]
    created_at: str
    updated_at: Optional[str] = None

    model_config = {"from_attributes": True}


class RecipeListItem(BaseModel):
    """Version allégée pour la liste (sans ingrédients/steps)."""
    id: int
    title: str
    servings: int
    prep_time: Optional[int]
    tags: List[str]
    source_url: Optional[str]
    image_url: Optional[str]
    created_at: str


# ── Requêtes ─────────────────────────────────────────────────────────────────

class ExtractRequest(BaseModel):
    url: str = Field(..., min_length=10, description="URL TikTok ou Instagram")

    @field_validator("url")
    @classmethod
    def must_be_supported_platform(cls, v: str) -> str:
    	v = v.strip()
    	if not any(domain in v for domain in ("tiktok.com", "instagram.com", "vm.tiktok.com")):
    		raise ValueError("URL doit provenir de TikTok ou Instagram")
    	return v


class TagAddRequest(BaseModel):
    tag: str = Field(..., min_length=1, max_length=50)

    @field_validator("tag")
    @classmethod
    def lowercase_strip(cls, v: str) -> str:
    	return v.strip().lower()


class ExportPDFRequest(BaseModel):
    recipe_ids: List[int] = Field(..., min_length=1)
