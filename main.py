# main.py
from fastapi import FastAPI, Depends, HTTPException
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session
from pydantic import BaseModel
from models import Recipe, Tag
from database import init_db, get_db
import json, subprocess, io
from datetime import datetime
from jinja2 import Template
from weasyprint import HTML
import httpx

app = FastAPI(title="WeChef Backend")

# CORS pour le frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Init DB au démarrage
init_db()

# --------- Schémas Pydantic ---------

class Ingredient(BaseModel):
    name: str
    quantity: str | None = None
    unit: str | None = None

class RecipeCreate(BaseModel):
    title: str
    ingredients: list[Ingredient]
    steps: list[str]
    servings: int = 4
    prep_time: str | None = None
    tags: list[str] = []
    source_url: str | None = None

class TagResponse(BaseModel):
    id: int
    name: str

    class Config:
        from_attributes = True

# --------- Génération image simple (Pollinations) ---------

async def generate_image_for_recipe(title: str) -> str | None:
    """Image food gratuite via Pollinations (simple URL) [web:65]"""
    try:
        prompt = f"Professional food photography of {title}, high quality, appetizing, cookbook style"
        prompt_encoded = prompt.replace(" ", "%20")
        img_url = f"https://image.pollinations.ai/prompt/{prompt_encoded}"
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.head(img_url)
            if resp.status_code == 200:
                return img_url
    except Exception as e:
        print(f"Image generation failed: {e}")
    return None

# --------- 1. Import recette depuis une URL ---------

@app.post("/extract")
async def extract_recipe(body: dict, db: Session = Depends(get_db)):
    url = body.get("url", "").strip()
    if not url:
        raise HTTPException(status_code=400, detail="URL vide")
    
    # Recette déjà importée ?
    existing = db.query(Recipe).filter(Recipe.source_url == url).first()
    if existing:
        raise HTTPException(status_code=409, detail="Recette déjà importée")
    
    # Métadonnées via yt-dlp (sans télécharger la vidéo) [web:42]
    result = subprocess.run(
        ["yt-dlp", "--skip-download", "-j", url],
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
    
    description = (meta.get("description") or meta.get("title") or "")[:2000]
    video_title = meta.get("title", "Recette importée")

    # TODO: remplacer ce mock par un vrai appel Gemini/LLM
    recipe_data = {
        "title": video_title[:100],
        "ingredients": [
            {"name": "Ingrédient à déterminer", "quantity": "1", "unit": "pièce"}
        ],
        "steps": ["Étape 1: À déterminer depuis la vidéo"],
        "servings": 4,
        "prep_time": "À déterminer",
    }

    image_url = await generate_image_for_recipe(recipe_data["title"])

    db_recipe = Recipe(
        title=recipe_data["title"],
        ingredients=json.dumps(recipe_data["ingredients"]),
        steps=json.dumps(recipe_data["steps"]),
        servings=recipe_data["servings"],
        prep_time=recipe_data.get("prep_time"),
        source_url=url,
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

# --------- 2. Liste / tags / suppression ---------

@app.get("/recipes")
def list_recipes(db: Session = Depends(get_db)):
    recipes = db.query(Recipe).all()
    result = []
    for r in recipes:
        result.append({
            "id": r.id,
            "title": r.title,
            "servings": r.servings,
            "prep_time": r.prep_time,
            "tags": [t.name for t in r.tags],
            "source_url": r.source_url,
            "created_at": r.created_at.isoformat(),
        })
    return result

@app.get("/tags", response_model=list[TagResponse])
def list_tags(db: Session = Depends(get_db)):
    tags = db.query(Tag).all()
    return tags

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

@app.delete("/recipes/{recipe_id}")
def delete_recipe(recipe_id: int, db: Session = Depends(get_db)):
    recipe = db.query(Recipe).get(recipe_id)
    if not recipe:
        raise HTTPException(status_code=404, detail="Recette non trouvée")
    db.delete(recipe)
    db.commit()
    return {"message": "Recette supprimée"}

# --------- 3. Export PDF 2 pages (image + contenu) ---------

HTML_TEMPLATE = """
<!DOCTYPE html>
<html>
<head>
<meta charset="UTF-8">
<style>
* { margin:0; padding:0; box-sizing:border-box; }
body { font-family:'Georgia', serif; color:#333; line-height:1.6; }

.page-break { page-break-after: always; }

.cover {
  height:100vh;
  display:flex; flex-direction:column;
  justify-content:center; align-items:center;
  background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
  color:white; text-align:center; padding:40px;
}
.cover h1 { font-size:4em; margin-bottom:20px; }
.cover p { font-size:1.3em; opacity:0.9; }

.toc { padding:60px 40px; }
.toc h2 { font-size:2em; margin-bottom:40px; border-bottom:3px solid #667eea; padding-bottom:10px; }
.toc ul { list-style:none; padding-left:0; }
.toc li { margin:15px 0; line-height:1.8; }
.toc a { color:#667eea; text-decoration:none; }

.recipe-section { display:flex; page-break-after:always; min-height:100vh; }

.recipe-image-page {
  flex:1;
  background:linear-gradient(135deg, #f5f7fa 0%, #c3cfe2 100%);
  display:flex; flex-direction:column;
  justify-content:center; align-items:center;
  padding:40px; text-align:center;
}
.recipe-image-page img {
  max-width:90%;
  max-height:400px;
  object-fit:cover;
  border-radius:12px;
  box-shadow:0 10px 30px rgba(0,0,0,0.2);
  margin-bottom:30px;
}
.recipe-image-page h2 {
  font-size:2em; color:#667eea; margin-top:20px;
}
.recipe-image-page .meta {
  color:#666; font-style:italic; margin-top:10px;
}

.recipe-content-page {
  flex:1;
  padding:60px 50px; display:flex; flex-direction:column;
  justify-content:center;
}
.recipe-content-page h3 {
  font-size:2.5em; color:#667eea;
  margin-bottom:30px; border-bottom:2px solid #667eea; padding-bottom:15px;
}

.ingredients {
  margin-bottom:40px;
}
.ingredients h4 {
  font-size:1.3em; color:#667eea; margin-bottom:15px;
}
.ingredients ul { list-style:none; padding-left:0; }
.ingredients li {
  margin:10px 0; padding-left:25px; position:relative;
}
.ingredients li::before {
  content:"✓"; color:#667eea; font-weight:bold;
  position:absolute; left:0;
}

.steps {
  margin-top:30px;
}
.steps h4 {
  font-size:1.3em; color:#667eea; margin-bottom:15px;
}
.steps ol { margin-left:20px; }
.steps li { margin:12px 0; line-height:1.7; }

@media print {
  .page-break { page-break-after: always; }
}
</style>
</head>
<body>

<div class="cover page-break">
  <h1>📖 Mon Carnet de Recettes</h1>
  <p>{{ recipe_count }} recettes sélectionnées</p>
  <p style="margin-top:60px; font-size:1em; opacity:0.8;">Généré le {{ date }}</p>
</div>

<div class="toc page-break">
  <h2>📑 Table des matières</h2>
  <ul>
  {% for r in recipes %}
    <li><a href="#recipe{{ r.id }}">{{ r.title }}</a> {% if r.prep_time %}<span style="color:#999;"> — {{ r.prep_time }}</span>{% endif %}</li>
  {% endfor %}
  </ul>
</div>

{% for r in recipes %}
<div class="recipe-section page-break" id="recipe{{ r.id }}">
  <div class="recipe-image-page">
    {% if r.image_url %}
      <img src="{{ r.image_url }}" alt="{{ r.title }}">
    {% else %}
      <div style="width:300px; height:300px; background:#ddd; border-radius:12px; display:flex; align-items:center; justify-content:center; color:#999;">
        Pas d'image
      </div>
    {% endif %}
    <h2>{{ r.title }}</h2>
    <div class="meta">
      👥 {{ r.servings }} portions
      {% if r.prep_time %} · ⏱️ {{ r.prep_time }}{% endif %}
    </div>
  </div>
  
  <div class="recipe-content-page">
    <h3>Préparation</h3>
    
    <div class="ingredients">
      <h4>Ingrédients</h4>
      <ul>
      {% for ing in r.ingredients %}
        <li>{% if ing.quantity %}{{ ing.quantity }} {% endif %}{% if ing.unit %}{{ ing.unit }}{% endif %} {{ ing.name }}</li>
      {% endfor %}
      </ul>
    </div>
    
    <div class="steps">
      <h4>Étapes</h4>
      <ol>
      {% for step in r.steps %}
        <li>{{ step }}</li>
      {% endfor %}
      </ol>
    </div>
  </div>
</div>
{% endfor %}

</body>
</html>
"""

@app.post("/export-pdf")
def export_pdf(body: dict, db: Session = Depends(get_db)):
    recipe_ids = body.get("recipe_ids", [])
    if not recipe_ids:
        raise HTTPException(status_code=400, detail="Aucune recette sélectionnée")
    
    recipes = db.query(Recipe).filter(Recipe.id.in_(recipe_ids)).all()
    if not recipes:
        raise HTTPException(status_code=404, detail="Aucune recette trouvée")
    
    recipes_data = []
    for r in recipes:
        recipes_data.append({
            "id": r.id,
            "title": r.title,
            "ingredients": json.loads(r.ingredients),
            "steps": json.loads(r.steps),
            "servings": r.servings,
            "prep_time": r.prep_time,
            "image_url": None,  # tu pourras stocker ça en DB plus tard
        })
    
    template = Template(HTML_TEMPLATE)
    html_content = template.render(
        recipes=recipes_data,
        recipe_count=len(recipes),
        date=datetime.now().strftime("%d/%m/%Y"),
    )
    
    pdf_bytes = HTML(string=html_content).write_pdf()  # HTML → PDF [web:60][web:70]
    
    return FileResponse(
        io.BytesIO(pdf_bytes),
        media_type="application/pdf",
        filename=f"Carnet_Recettes_{datetime.now().strftime('%Y%m%d')}.pdf",
    )

# --------- 4. Frontend HTML ---------

@app.get("/", response_class=HTMLResponse)
def frontend():
    return open("frontend.html").read()
