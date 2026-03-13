import json
import requests
from base64 import b64encode
from datetime import date
from weasyprint import HTML


def image_to_base64(url):
    try:
        headers = {"User-Agent": "Mozilla/5.0"}
        r = requests.get(url, timeout=10, headers=headers)
        print(f"[PDF] Image {url[:60]} -> status {r.status_code}, size {len(r.content)} bytes")
        if r.status_code == 200 and len(r.content) > 0:
            mime = r.headers.get("Content-Type", "image/jpeg").split(";")[0]
            return "data:" + mime + ";base64," + b64encode(r.content).decode()
        else:
            print(f"[PDF] Image echouee : {r.status_code}")
            return None
    except Exception as e:
        print(f"[PDF] Erreur image : {e}")
        return None


def generate_pdf(recipes):
    today = date.today().strftime("%d/%m/%Y")
    recipes_html = ""

    for recipe in recipes:
        if isinstance(recipe.ingredients, str):
            ingredients = json.loads(recipe.ingredients)
        else:
            ingredients = recipe.ingredients

        if isinstance(recipe.steps, str):
            steps = json.loads(recipe.steps)
        else:
            steps = recipe.steps

        if recipe.image_url:
            b64 = image_to_base64(recipe.image_url)
            if b64:
                img_html = '<img class="recipe-img" src="' + b64 + '">'
            else:
                img_html = '<img class="recipe-img" src="' + recipe.image_url + '">'
        else:
            img_html = '<div class="recipe-img-placeholder">&#127869;</div>'

        ing_items = ""
        for i in ingredients:
            if isinstance(i, dict):
                qty = i.get("quantity", "")
                unit = i.get("unit", "") or ""
                name = i.get("name", "")
                ing_items += '<li><span class="qty">' + str(qty) + " " + str(unit) + "</span>" + str(name) + "</li>"
            else:
                ing_items += "<li>" + str(i) + "</li>"

        steps_items = ""
        for s in steps:
            clean = str(s).replace("\n", " ").strip()
            if clean:
                steps_items += "<li>" + clean + "</li>"

        meta_parts = []
        if recipe.prep_time:
            meta_parts.append("&#9201; " + str(recipe.prep_time) + " min")
        if recipe.servings:
            meta_parts.append("&#128101; " + str(recipe.servings) + " portion(s)")
        meta_html = " &nbsp;&middot;&nbsp; ".join(meta_parts)

        recipes_html += """
        <div class="recipe-page">
        """ + img_html + """
            <div class="recipe-content">
                <h1 class="recipe-title">""" + recipe.title + """</h1>
                <p class="recipe-meta">""" + meta_html + """</p>
                <div class="two-col">
                    <div class="section">
                        <h2>Ingredients</h2>
                        <ul class="ingredients">""" + ing_items + """</ul>
                    </div>
                    <div class="section">
                        <h2>Preparation</h2>
                        <ol class="steps">""" + steps_items + """</ol>
                    </div>
                </div>
            </div>
        </div>
        """

    toc_items = ""
    for r in recipes:
        time_str = "&#9201; " + str(r.prep_time) + " min" if r.prep_time else ""
        toc_items += '<div class="toc-item"><span>' + r.title + '</span><span class="toc-time">' + time_str + "</span></div>"

    html = """<!DOCTYPE html>
<html lang="fr">
<head>
<meta charset="UTF-8">
<style>
* { margin:0; padding:0; box-sizing:border-box; }
body { font-family: Georgia, serif; color: #1a1a2e; background: white; }

.cover {
    width:100%; height:100vh;
    background: linear-gradient(160deg, #1a1a2e 0%, #0f3460 100%);
    display:flex; flex-direction:column;
    align-items:center; justify-content:center; text-align:center;
    page-break-after: always;
}
.cover-icon { font-size:72px; margin-bottom:24px; }
.cover h1 { font-size:52px; color:white; line-height:1.2; margin-bottom:16px; }
.cover .count {
    background:rgba(255,255,255,0.12); border:1px solid rgba(255,255,255,0.25);
    border-radius:20px; padding:8px 24px; color:white; font-size:15px; margin-top:16px;
}
.cover .date { color:rgba(255,255,255,0.4); font-size:13px; margin-top:20px; }

.toc { padding:60px 80px; page-break-after:always; }
.toc h2 { font-size:30px; margin-bottom:28px; padding-bottom:12px; border-bottom:3px solid #f5576c; }
.toc-item {
    display:flex; justify-content:space-between;
    padding:12px 0; border-bottom:1px dashed #ddd; font-size:14px;
}
.toc-time { color:#999; font-size:13px; font-family:sans-serif; }

.recipe-page { page-break-before:always; }
.recipe-img { width:100%; height:280px; object-fit:cover; display:block; }
.recipe-img-placeholder {
    width:100%; height:180px;
    background:linear-gradient(135deg,#f5f7fa,#e8ecf0);
    display:flex; align-items:center; justify-content:center; font-size:56px;
}
.recipe-content { padding:36px 60px 48px; }
.recipe-title { font-size:32px; margin-bottom:8px; line-height:1.2; }
.recipe-meta { color:#999; font-size:13px; font-family:sans-serif; margin-bottom:28px; }

.two-col { display:flex; gap:48px; }
.two-col .section:first-child { flex:1; }
.two-col .section:last-child { flex:2; }

.section h2 {
    font-size:11px; font-family:sans-serif; font-weight:700;
    text-transform:uppercase; letter-spacing:1.5px; color:#f5576c;
    margin-bottom:14px; padding-bottom:6px; border-bottom:2px solid #f5f7fa;
}
.ingredients { list-style:none; }
.ingredients li {
    display:flex; gap:8px; padding:7px 0;
    border-bottom:1px solid #f5f7fa; font-size:13px; font-family:sans-serif;
}
.qty { font-weight:700; color:#f5576c; min-width:50px; font-size:12px; }

.steps { padding-left:18px; }
.steps li {
    font-size:13px; font-family:sans-serif;
    line-height:1.75; margin-bottom:10px;
}

@page {
    margin: 0;
    @bottom-center {
        content: "WeChef  " counter(page);
        font-family: sans-serif; font-size:11px; color:#ccc; padding-bottom:8px;
    }
}
</style>
</head>
<body>

<div class="cover">
    <div class="cover-icon">&#128214;</div>
    <h1>Mon Carnet<br>de Recettes</h1>
    <div class="count">""" + str(len(recipes)) + """ recette(s)</div>
    <div class="date">Genere le """ + today + """</div>
</div>

<div class="toc">
    <h2>Sommaire</h2>
    """ + toc_items + """
</div>

""" + recipes_html + """
</body>
</html>"""

    return HTML(string=html, base_url=".").write_pdf(presentational_hints=True)

