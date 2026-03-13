# main.py
import json
import subprocess
import io
import os
import asyncio
import base64
from urllib.parse import urlparse, urlunparse
from datetime import datetime
from typing import List, Optional
from fastapi import FastAPI, Depends, HTTPException, UploadFile, File
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, Response
from pdf_generator import generate_pdf
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session
from pydantic import BaseModel
from jinja2 import Template
from weasyprint import HTML
import httpx

from google import genai
from google.genai import types
from dotenv import load_dotenv

from models import Recipe, Tag
from database import init_db, get_db

load_dotenv()
client_gemini = genai.Client(api_key=os.environ["GEMINI_API_KEY"])
YT_DLP_PATH = os.getenv("YT_DLP_PATH", "/usr/bin/yt-dlp")
app = FastAPI(title="WeChef Backend")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

init_db()

# ─────────────────────────────────────────────
# Schémas Pydantic
# ─────────────────────────────────────────────

class Ingredient(BaseModel):
    name: str
    quantity: Optional[str] = None
    unit: Optional[str] = None

class TagResponse(BaseModel):
    id: int
    name: str

    class Config:
        from_attributes = True

# ─────────────────────────────────────────────
# Génération image (Pollinations — gratuit, sans clé)
# ─────────────────────────────────────────────
def normalize_url(url: str) -> str:
    """Supprime les paramètres de tracking de l'URL"""
    parsed = urlparse(url)
    return urlunparse((parsed.scheme, parsed.netloc, parsed.path, '', '', ''))

UNSPLASH_KEY = os.environ.get("UNSPLASH_ACCESS_KEY")

async def generate_image_for_recipe(title: str) -> Optional[str]:
    """Cherche une image via Unsplash avec titre traduit en anglais"""
    
    # Traduit le titre en anglais via Gemini pour la recherche image
    english_query = title
    try:
        translate_response = client_gemini.models.generate_content(
            model="gemini-2.5-flash-lite",
            contents=f"Translate this French recipe title to English, return ONLY the translation, nothing else: '{title}'"
        )
        english_query = translate_response.text.strip().strip('"').strip("'")
        print(f"DEBUG titre traduit : {english_query}")
    except Exception as e:
        print(f"Translation failed: {e}")

    try:
        async with httpx.AsyncClient(
            timeout=20,
            follow_redirects=True,
            headers={"User-Agent": "Mozilla/5.0"}
        ) as client:
            search_resp = await client.get(
                "https://api.unsplash.com/search/photos",
                params={
                    "query": english_query,
                    "per_page": 1,
                    "orientation": "landscape",
                    "client_id": UNSPLASH_KEY
                }
            )
            print(f"DEBUG Unsplash status: {search_resp.status_code}, total: {search_resp.json().get('total', 0)}")

            if search_resp.status_code == 200:
                results = search_resp.json().get("results", [])
                if results:
                    img_url = results[0]["urls"]["regular"]
                    img_resp = await client.get(img_url)
                    if img_resp.status_code == 200 and len(img_resp.content) > 10000:
                        img_b64 = base64.b64encode(img_resp.content).decode("utf-8")
                        content_type = img_resp.headers.get("content-type", "image/jpeg")
                        print(f"Image Unsplash OK : {len(img_resp.content)} octets")
                        return f"data:{content_type};base64,{img_b64}"

    except Exception as e:
        print(f"Unsplash exception: {e}")

    # Fallback Picsum
    try:
        seed = abs(hash(title)) % 1000
        async with httpx.AsyncClient(timeout=15, follow_redirects=True, headers={"User-Agent": "Mozilla/5.0"}) as client:
            resp = await client.get(f"https://picsum.photos/seed/{seed}/800/600")
            if resp.status_code == 200 and len(resp.content) > 10000:
                img_b64 = base64.b64encode(resp.content).decode("utf-8")
                print("Image Picsum fallback OK")
                return f"data:image/jpeg;base64,{img_b64}"
    except Exception as e:
        print(f"Picsum exception: {e}")

    return None


# ─────────────────────────────────────────────
# 1. Import recette depuis URL TikTok / Instagram
# ─────────────────────────────────────────────

@app.post("/extract")
async def extract_recipe(body: dict, db: Session = Depends(get_db)):
    url = normalize_url(body.get("url", "").strip())
    if not url:
        raise HTTPException(status_code=400, detail="URL vide")

    # Déjà importée ?
    existing = db.query(Recipe).filter(Recipe.source_url == url).first()
    if existing:
        raise HTTPException(status_code=409, detail="Recette déjà importée")

    # Métadonnées via yt-dlp (sans télécharger la vidéo)
    result = subprocess.run(
        [YT_DLP_PATH, "--skip-download", "-j", url],
        capture_output=True,
        text=True,
        timeout=30
    )
    if result.returncode != 0:
        raise HTTPException(status_code=400, detail=f"yt-dlp error: {result.stderr}")

    try:
        meta = json.loads(result.stdout)
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="Métadonnées vidéo invalides")

    description = (meta.get("description") or "")[:3000]
    video_title = meta.get("title", "Recette importée")

    # Extraction structurée via Gemini
    try:
        prompt = f"""
Tu es un assistant culinaire. Extrait la recette depuis ce texte de vidéo.
Si certaines informations manquent, déduis-les intelligemment.
Réponds UNIQUEMENT en JSON valide, en français, avec ce format exact :
{{
  "title": "...",
  "ingredients": [{{"name": "...", "quantity": "...", "unit": "..."}}],
  "steps": ["étape 1", "étape 2"],
  "servings": 4,
  "prep_time": "20 min"
}}

Texte : \"\"\"{description}\"\"\"
Titre : {video_title}
"""

        response = client_gemini.models.generate_content(
            model="gemini-2.5-flash-lite",
            contents=prompt,
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
            )
        )

        recipe_data = json.loads(response.text)

        ingredients = recipe_data.get("ingredients", [])
        if ingredients and isinstance(ingredients[0], str):
            ingredients = [{"name": i, "quantity": None, "unit": None} for i in ingredients]

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Erreur Gemini : {str(e)}")

    # Générer une image
    image_url = await generate_image_for_recipe(recipe_data.get("title", video_title))

    # Sauvegarder en DB
    try:
        raw_servings = recipe_data.get("servings") or 4
        servings = max(int(str(raw_servings).strip()), 1)
    except (ValueError, TypeError):
        servings = 4
    try:
        raw_prep = recipe_data.get("prep_time") or 0
        prep_time = int(str(raw_prep).strip()) if raw_prep else None
    except (ValueError, TypeError):
        prep_time = None

    db_recipe = Recipe(
        title=recipe_data.get("title", video_title)[:100],
        ingredients=json.dumps(ingredients, ensure_ascii=False),
        steps=json.dumps(recipe_data.get("steps", []), ensure_ascii=False),
        servings = servings,
        prep_time = prep_time,
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
        "message": "Recette importée avec succès"
    }

# ─────────────────────────────────────────────
# 2. Lister les recettes
# ─────────────────────────────────────────────

@app.get("/recipes")
def list_recipes(db: Session = Depends(get_db), tag: Optional[str] = None):
    query = db.query(Recipe)
    if tag:
        query = query.join(Recipe.tags).filter(Tag.name == tag)
    recipes = query.all()
    return [
        {
            "id": r.id,
            "title": r.title,
            "servings": r.servings,
            "prep_time": r.prep_time,
            "tags": [t.name for t in r.tags],
            "source_url": r.source_url,
            "image_url": r.image_url,
            "created_at": r.created_at.isoformat(),
        }
        for r in recipes
    ]

# ─────────────────────────────────────────────
# 3. Tags
# ─────────────────────────────────────────────

@app.get("/tags", response_model=List[TagResponse])
def list_tags(db: Session = Depends(get_db)):
    return db.query(Tag).all()

@app.post("/recipes/{recipe_id}/tags")
def add_tag(recipe_id: int, body: dict, db: Session = Depends(get_db)):
    recipe = db.query(Recipe).get(recipe_id)
    if not recipe:
        raise HTTPException(status_code=404, detail="Recette non trouvée")

    tag_name = body.get("tag", "").strip().lower()
    if not tag_name:
        raise HTTPException(status_code=400, detail="Tag vide")

    tag = db.query(Tag).filter(Tag.name == tag_name).first()
    if not tag:
        tag = Tag(name=tag_name)
        db.add(tag)

    if tag not in recipe.tags:
        recipe.tags.append(tag)

    db.commit()
    return {"message": "Tag ajouté"}

# ─────────────────────────────────────────────
# 4. Suppression
# ─────────────────────────────────────────────

@app.delete("/recipes/{recipe_id}")
def delete_recipe(recipe_id: int, db: Session = Depends(get_db)):
    recipe = db.query(Recipe).get(recipe_id)
    if not recipe:
        raise HTTPException(status_code=404, detail="Recette non trouvée")
    db.delete(recipe)
    db.commit()
    return {"message": "Recette supprimée"}

# ─────────────────────────────────────────────
# 5. Export PDF
# ─────────────────────────────────────────────
HTML_TEMPLATE = """
<!DOCTYPE html>
<html>
<head>
<meta charset="UTF-8">
<style>

@font-face {
    font-family: 'NotoEmoji';
    src: local('Noto Color Emoji');
}

* { margin:0; padding:0; box-sizing:border-box; }
body { font-family:'Georgia', serif; color:#333; line-height:1.6; }

/* ── Couverture ── */
.cover {
  page-break-after: always;
  height:297mm;
  display:block;
  background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
  color:white; text-align:center;
  padding-top: 100mm;
}
.cover h1 { font-size:3em; margin-bottom:20px; }
.cover p { font-size:1.2em; opacity:0.9; }

/* ── Table des matières ── */
.toc { page-break-after: always; padding:40px; }
.toc h2 { font-size:2em; margin-bottom:30px; border-bottom:3px solid #667eea; padding-bottom:10px; }
.toc ul { list-style:none; padding-left:0; }
.toc li { margin:12px 0; font-size:1.1em; }
.toc a { color:#667eea; text-decoration:none; }

/* ── Page image (page impaire) ── */
.recipe-image-page {
  page-break-after: always;
  height:297mm;
  background: linear-gradient(135deg, #f5f7fa 0%, #c3cfe2 100%);
  text-align:center;
  padding-top: 60mm;
}
.recipe-image-page img {
  width:160mm;
  height:120mm;
  object-fit:cover;
  border-radius:12px;
  box-shadow:0 10px 30px rgba(0,0,0,0.2);
}
.recipe-image-page .no-image {
  width:160mm; height:120mm;
  background:#ddd; border-radius:12px;
  margin:0 auto;
  line-height:120mm;
  color:#999; font-size:1.2em;
}
.recipe-image-page h2 {
  font-size:2.2em; color:#667eea; margin-top:20px;
}
.recipe-image-page .meta {
  color:#666; font-style:italic; margin-top:10px; font-size:1.1em;
}

/* ── Page recette (page paire) ── */
.recipe-content-page {
  page-break-after: always;
  padding: 30mm 25mm;
}
.recipe-content-page h3 {
  font-size:2em; color:#667eea;
  margin-bottom:20px;
  border-bottom:3px solid #667eea; padding-bottom:10px;
}
body {
    font-family: 'Georgia', 'NotoEmoji', serif;
}

.cover h1, .toc h2, .ingredients h4, .steps h4, .recipe-meta {
    font-family: 'Georgia', 'NotoEmoji', serif;
}
.ingredients { margin-bottom:30px; }
.ingredients h4 { font-size:1.2em; color:#667eea; margin-bottom:12px; }
.ingredients ul { list-style:none; padding-left:0; }
.ingredients li { margin:8px 0; padding-left:20px; position:relative; font-size:1em; }
.ingredients li::before { content:"✓ "; color:#667eea; font-weight:bold; position:absolute; left:0; }

.steps h4 { font-size:1.2em; color:#667eea; margin-bottom:12px; }
.steps ol { margin-left:20px; }
.steps li { margin:10px 0; line-height:1.7; font-size:1em; }
</style>
</head>
<body>

<!-- COUVERTURE -->
<div class="cover">
  <h1>📖 Mon Carnet<br>de Recettes</h1>
  <p>{{ recipe_count }} recette(s) sélectionnée(s)</p>
  <p style="margin-top:50mm; font-size:0.9em; opacity:0.7;">Généré le {{ date }}</p>
</div>

<!-- TABLE DES MATIÈRES -->
<div class="toc">
  <h2>📑 Table des matières</h2>
  <ul>
  {% for r in recipes %}
    <li>
      <a href="#recipe{{ r.id }}">{{ r.title }}</a>
      {% if r.prep_time %}<span style="color:#999;"> — {{ r.prep_time }}</span>{% endif %}
    </li>
  {% endfor %}
  </ul>
</div>

<!-- RECETTES : 1 page image + 1 page contenu -->
{% for r in recipes %}

<div class="recipe-image-page" id="recipe{{ r.id }}">
  {% if r.image_url %}
    <img src="{{ r.image_url }}" alt="{{ r.title }}">
  {% else %}
    <div class="no-image">Pas d'image</div>
  {% endif %}
  <h2>{{ r.title }}</h2>
  <p class="meta">
    👥 {{ r.servings }} portion(s)
    {% if r.prep_time %} · ⏱️ {{ r.prep_time }}{% endif %}
  </p>
</div>

<div class="recipe-content-page">

<div class="ingredients">
  <h4>🧂 Ingrédients</h4>
  <table style="width:100%; border-collapse:collapse;">
  {% for ing in r.ingredients %}
    <tr>
      <td style="width:16px; vertical-align:top; padding:6px 8px 6px 0; color:#667eea; font-weight:bold;">✓</td>
      <td style="width:80px; vertical-align:top; padding:6px 8px 6px 0; color:#666;">{% if ing.quantity %}{{ ing.quantity }}{% endif %} {% if ing.unit %}{{ ing.unit }}{% endif %}</td>
      <td style="vertical-align:top; padding:6px 0;">{{ ing.name }}</td>
    </tr>
  {% endfor %}
  </table>
</div>

<div class="steps">
  <h4>👨‍🍳 Préparation</h4>
  <table style="width:100%; border-collapse:collapse;">
  {% for step in r.steps %}
    <tr style="border-bottom:1px solid #f0f0f0;">
     <td style="width:30px; vertical-align:top; padding:8px 10px 8px 0; color:#667eea; font-weight:bold;">{{ loop.index }}.</td> 
      <td style="vertical-align:top; padding:8px 0; line-height:1.7;">{{ step }}</td>
    </tr>
  {% endfor %}
  </table>
</div>

{% endfor %}

</body>
</html>
"""



@app.post("/export-pdf")
def export_pdf(body: dict, db: Session = Depends(get_db)):
    recipe_ids = body.get("recipe_ids", [])
    recipes = db.query(Recipe).filter(Recipe.id.in_(recipe_ids)).all()
    pdf_bytes = generate_pdf(recipes)
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": "attachment; filename=carnet_recettes.pdf"}
    )
# ─────────────────────────────────────────────
# Détail + modification d'une recette
# ─────────────────────────────────────────────

@app.get("/recipes/{recipe_id}")
def get_recipe(recipe_id: int, db: Session = Depends(get_db)):
    recipe = db.query(Recipe).get(recipe_id)
    if not recipe:
        raise HTTPException(status_code=404, detail="Recette non trouvée")
    return {
        "id": recipe.id,
        "title": recipe.title,
        "ingredients": json.loads(recipe.ingredients),
        "steps": json.loads(recipe.steps),
        "servings": recipe.servings,
        "prep_time": recipe.prep_time,
        "tags": [t.name for t in recipe.tags],
        "source_url": recipe.source_url,
        "image_url": recipe.image_url,
        "created_at": recipe.created_at.isoformat(),
    }

@app.post("/recipes/{recipe_id}/regenerate-image")
async def regenerate_image(recipe_id: int, db: Session = Depends(get_db)):
    recipe = db.query(Recipe).get(recipe_id)
    if not recipe:
        raise HTTPException(status_code=404, detail="Recette non trouvée")

    image_url = await generate_image_for_recipe(recipe.title)
    if image_url:
        recipe.image_url = image_url
        db.commit()

    return {"image_url": image_url}

@app.post("/recipes")
def create_recipe(body: dict, db: Session = Depends(get_db)):
    db_recipe = Recipe(
        title=body.get("title", "Nouvelle recette")[:100],
        ingredients=json.dumps(body.get("ingredients", []), ensure_ascii=False),
        steps=json.dumps(body.get("steps", []), ensure_ascii=False),
        servings=body.get("servings", 4),
        prep_time=body.get("prep_time", None),
        source_url=None,
        image_url=None,
    )
    db.add(db_recipe)
    db.commit()
    db.refresh(db_recipe)
    return {"id": db_recipe.id, "message": "Recette créée"}


@app.put("/recipes/{recipe_id}")
def update_recipe(recipe_id: int, body: dict, db: Session = Depends(get_db)):
    recipe = db.query(Recipe).get(recipe_id)
    if not recipe:
        raise HTTPException(status_code=404, detail="Recette non trouvée")

    if "title" in body:
        recipe.title = body["title"]
    if "ingredients" in body:
        recipe.ingredients = json.dumps(body["ingredients"], ensure_ascii=False)
    if "steps" in body:
        recipe.steps = json.dumps(body["steps"], ensure_ascii=False)
    if "servings" in body:
        recipe.servings = body["servings"]
    if "prep_time" in body:
        recipe.prep_time = body["prep_time"]
    if "image_url" in body:
        recipe.image_url = body["image_url"]

    db.commit()
    db.refresh(recipe)
    return {"message": "Recette mise à jour"}

@app.post("/recipes/{recipe_id}/image")
async def upload_image(recipe_id: int, file: UploadFile, db: Session = Depends(get_db)):
    """Upload d'une image personnalisée"""
    recipe = db.query(Recipe).get(recipe_id)
    if not recipe:
        raise HTTPException(status_code=404, detail="Recette non trouvée")

    content = await file.read()
    if len(content) > 10 * 1024 * 1024:  # 10 Mo max
        raise HTTPException(status_code=400, detail="Image trop lourde (max 10 Mo)")

    img_b64 = base64.b64encode(content).decode("utf-8")
    content_type = file.content_type or "image/jpeg"
    recipe.image_url = f"data:{content_type};base64,{img_b64}"

    db.commit()
    return {"message": "Image mise à jour"}


# ─────────────────────────────────────────────
# 6. Frontend
# ─────────────────────────────────────────────

@app.get("/", response_class=HTMLResponse)
def frontend():
    return open("frontend.html").read()
