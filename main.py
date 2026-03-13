"""WeChef Backend — FastAPI entry point.

Responsabilités : routing, validation des requêtes/réponses, gestion des erreurs HTTP.
Toute logique métier est déléguée aux services/.
"""
from __future__ import annotations

import os
from typing import List, Optional

from dotenv import load_dotenv
from fastapi import Depends, FastAPI, HTTPException, Query, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, Response
from fastapi.staticfiles import StaticFiles
from pathlib import Path
from sqlalchemy.orm import Session
import base64

from google import genai

from database import get_db, init_db
from models import Recipe, Tag
from pdf_generator import generate_pdf
from schemas import (
    ExportPDFRequest,
    ExtractRequest,
    RecipeCreate,
    RecipeListItem,
    RecipeResponse,
    RecipeUpdate,
    TagAddRequest,
    TagResponse,
)
from services.extractor import extract_recipe_with_llm, fetch_video_metadata
from services.image_service import generate_image_for_recipe, delete_image_file, IMAGES_DIR
from urllib.parse import urlparse, urlunparse

load_dotenv()

# ── Clients externes ──────────────────────────────────────────────────────────
client_gemini = genai.Client(api_key=os.environ["GEMINI_API_KEY"])

# ── App ───────────────────────────────────────────────────────────────────────
app = FastAPI(title="WeChef API", version="1.0.0")

# Servir les images statiques
IMAGES_DIR.mkdir(parents=True, exist_ok=True)
app.mount("/static", StaticFiles(directory="static"), name="static")

# CORS : origines configurables via .env
_ALLOWED_ORIGINS = os.getenv("CORS_ORIGINS", "http://localhost,http://127.0.0.1").split(",")
app.add_middleware(
    CORSMiddleware,
    allow_origins=_ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

init_db()


# ── Helpers ───────────────────────────────────────────────────────────────────

def _normalize_url(url: str) -> str:
    parsed = urlparse(url)
    return urlunparse((parsed.scheme, parsed.netloc, parsed.path, "", "", ""))


def _recipe_to_response(r: Recipe) -> RecipeResponse:
    return RecipeResponse(
        id=r.id,
        title=r.title,
        ingredients=r.ingredients or [],
        steps=r.steps or [],
        servings=r.servings,
        prep_time=r.prep_time,
        tags=[t.name for t in r.tags],
        source_url=r.source_url,
        image_url=r.image_url,
        created_at=r.created_at.isoformat(),
        updated_at=r.updated_at.isoformat() if r.updated_at else None,
    )


# ── Endpoints ─────────────────────────────────────────────────────────────────

@app.get("/", response_class=HTMLResponse, include_in_schema=False)
def frontend() -> str:
    with open("frontend.html", encoding="utf-8") as f:
        return f.read()


# --- Recettes -----------------------------------------------------------------

@app.get("/recipes", response_model=List[RecipeListItem])
def list_recipes(
    db: Session = Depends(get_db),
    tag: Optional[str] = Query(default=None),
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=200),
) -> list:
    query = db.query(Recipe)
    if tag:
        query = query.join(Recipe.tags).filter(Tag.name == tag.strip().lower())
    recipes = query.offset(skip).limit(limit).all()
    return [
        RecipeListItem(
            id=r.id,
            title=r.title,
            servings=r.servings,
            prep_time=r.prep_time,
            tags=[t.name for t in r.tags],
            source_url=r.source_url,
            image_url=r.image_url,
            created_at=r.created_at.isoformat(),
        )
        for r in recipes
    ]


@app.get("/recipes/{recipe_id}", response_model=RecipeResponse)
def get_recipe(recipe_id: int, db: Session = Depends(get_db)) -> RecipeResponse:
    recipe = db.get(Recipe, recipe_id)
    if not recipe:
        raise HTTPException(status_code=404, detail="Recette non trouvée")
    return _recipe_to_response(recipe)


@app.post("/recipes", response_model=RecipeResponse, status_code=201)
def create_recipe(body: RecipeCreate, db: Session = Depends(get_db)) -> RecipeResponse:
    db_recipe = Recipe(
        title=body.title,
        ingredients=[i.model_dump() for i in body.ingredients],
        steps=body.steps,
        servings=body.servings,
        prep_time=body.prep_time,
        image_url=body.image_url,
    )
    db.add(db_recipe)
    db.commit()
    db.refresh(db_recipe)
    return _recipe_to_response(db_recipe)


@app.put("/recipes/{recipe_id}", response_model=RecipeResponse)
def update_recipe(recipe_id: int, body: RecipeUpdate, db: Session = Depends(get_db)) -> RecipeResponse:
    recipe = db.get(Recipe, recipe_id)
    if not recipe:
        raise HTTPException(status_code=404, detail="Recette non trouvée")
    update_data = body.model_dump(exclude_unset=True)
    if "ingredients" in update_data and body.ingredients is not None:
        update_data["ingredients"] = [i.model_dump() for i in body.ingredients]
    for field, value in update_data.items():
        setattr(recipe, field, value)
    db.commit()
    db.refresh(recipe)
    return _recipe_to_response(recipe)


@app.delete("/recipes/{recipe_id}", status_code=204)
def delete_recipe(recipe_id: int, db: Session = Depends(get_db)) -> None:
    recipe = db.get(Recipe, recipe_id)
    if not recipe:
        raise HTTPException(status_code=404, detail="Recette non trouvée")
    delete_image_file(recipe.image_url)  # nettoyage fichier image
    db.delete(recipe)
    db.commit()


# --- Tags --------------------------------------------------------------------

@app.get("/tags", response_model=List[TagResponse])
def list_tags(db: Session = Depends(get_db)) -> list:
    return db.query(Tag).all()


@app.post("/recipes/{recipe_id}/tags", status_code=201)
def add_tag(recipe_id: int, body: TagAddRequest, db: Session = Depends(get_db)) -> dict:
    recipe = db.get(Recipe, recipe_id)
    if not recipe:
        raise HTTPException(status_code=404, detail="Recette non trouvée")
    tag = db.query(Tag).filter(Tag.name == body.tag).first()
    if not tag:
        tag = Tag(name=body.tag)
        db.add(tag)
    if tag not in recipe.tags:
        recipe.tags.append(tag)
    db.commit()
    return {"message": "Tag ajouté", "tag": body.tag}


# --- Extraction --------------------------------------------------------------

@app.post("/extract", status_code=201)
async def extract_recipe(body: ExtractRequest, db: Session = Depends(get_db)) -> dict:
    url = _normalize_url(body.url)

    existing = db.query(Recipe).filter(Recipe.source_url == url).first()
    if existing:
        raise HTTPException(status_code=409, detail="Recette déjà importée")

    try:
        meta = await fetch_video_metadata(url)  # non-bloquant
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    description = (meta.get("description") or "")[:3000]
    video_title = meta.get("title", "Recette importée")

    try:
        recipe_data = extract_recipe_with_llm(client_gemini, description, video_title)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Erreur LLM : {exc}") from exc

    image_url = await generate_image_for_recipe(client_gemini, recipe_data.get("title", video_title))

    db_recipe = Recipe(
        title=recipe_data.get("title", video_title)[:200],
        ingredients=recipe_data.get("ingredients", []),
        steps=recipe_data.get("steps", []),
        servings=max(int(recipe_data.get("servings") or 4), 1),
        prep_time=recipe_data.get("prep_time"),
        source_url=url,
        image_url=image_url,
    )
    db.add(db_recipe)
    db.commit()
    db.refresh(db_recipe)

    return {
        "id": db_recipe.id,
        "title": db_recipe.title,
        "image_url": image_url,
        "message": "Recette importée avec succès",
    }


# --- Image -------------------------------------------------------------------

@app.post("/recipes/{recipe_id}/regenerate-image")
async def regenerate_image(recipe_id: int, db: Session = Depends(get_db)) -> dict:
    recipe = db.get(Recipe, recipe_id)
    if not recipe:
        raise HTTPException(status_code=404, detail="Recette non trouvée")
    delete_image_file(recipe.image_url)  # supprime l'ancienne image
    image_url = await generate_image_for_recipe(client_gemini, recipe.title)
    if image_url:
        recipe.image_url = image_url
        db.commit()
    return {"image_url": image_url}


@app.post("/recipes/{recipe_id}/image")
async def upload_image(recipe_id: int, file: UploadFile, db: Session = Depends(get_db)) -> dict:
    recipe = db.get(Recipe, recipe_id)
    if not recipe:
        raise HTTPException(status_code=404, detail="Recette non trouvée")
    content = await file.read()
    if len(content) > 10 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="Image trop lourde (max 10 Mo)")
    from services.image_service import _save_image_from_bytes
    delete_image_file(recipe.image_url)
    image_url = await _save_image_from_bytes(content, file.content_type or "image/jpeg")
    recipe.image_url = image_url
    db.commit()
    return {"message": "Image mise à jour", "image_url": image_url}


# --- PDF ---------------------------------------------------------------------

@app.post("/export-pdf")
def export_pdf(body: ExportPDFRequest, db: Session = Depends(get_db)) -> Response:
    recipes = db.query(Recipe).filter(Recipe.id.in_(body.recipe_ids)).all()
    if not recipes:
        raise HTTPException(status_code=404, detail="Aucune recette trouvée pour ces IDs")
    pdf_bytes = generate_pdf(recipes)
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": "attachment; filename=carnet_recettes.pdf"},
    )
