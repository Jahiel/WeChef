# 📚 WeChef — Carnet de Recettes

Application web personnelle pour importer, gérer et exporter des recettes depuis TikTok et Instagram.

---

## 🧰 Stack technique

| Composant | Outil |
|---|---|
| Backend | FastAPI + Uvicorn |
| Base de données | SQLite + SQLAlchemy |
| Extraction vidéo | yt-dlp |
| LLM | Gemini 2.5 Flash Lite (Google AI Studio) |
| Images | Unsplash API (avec fallback Picsum) |
| Export PDF | WeasyPrint + Jinja2 |
| Frontend | HTML / CSS / JavaScript (vanilla) |

---

## 📁 Structure du projet

```
wechef-backend/
├── main.py           # API FastAPI + logique métier
├── models.py         # Modèles SQLAlchemy (Recipe, Tag)
├── database.py       # Connexion SQLite + init DB
├── frontend.html     # Interface web (SPA vanilla JS)
├── .env              # Variables d'environnement (non commité)
├── .gitignore
├── recipes.db        # Base SQLite (générée automatiquement, non commitée)
└── .venv/            # Environnement virtuel Python (non commité)
```

---

## ⚙️ Installation

### 1. Prérequis système (Ubuntu 22.04 / 24.04)

```bash
sudo apt update && sudo apt upgrade -y
sudo apt install -y python3 python3-venv python3-pip git
sudo apt install -y libpango-1.0-0 libharfbuzz0b libpangoft2-1.0-0
sudo apt install -y fonts-noto-color-emoji
```

### 2. Cloner et configurer

```bash
git clone <url-du-repo> wechef-backend
cd wechef-backend

python3 -m venv .venv
source .venv/bin/activate

pip install "fastapi[standard]" uvicorn weasyprint httpx jinja2 \
            python-multipart yt-dlp sqlalchemy pydantic \
            google-genai python-dotenv
```

### 3. Vérifier yt-dlp

```bash
which yt-dlp  # Copie le chemin dans YT_DLP_PATH du .env
```

### 4. Variables d'environnement

Crée le fichier `.env` à la racine :

```env
GEMINI_API_KEY=ta_clé_google_ai_studio
UNSPLASH_ACCESS_KEY=ta_clé_unsplash
YT_DLP_PATH=Chemin absolu vers l'exécutable yt-dlp
```

- **Gemini** : [aistudio.google.com/app/apikey](https://aistudio.google.com/app/apikey) — gratuit, 1000 req/jour
- **Unsplash** : [unsplash.com/developers](https://unsplash.com/developers) — gratuit, 50 req/heure

### 4. Lancer

```bash
source .venv/bin/activate
uvicorn main:app --host 0.0.0.0 --port 8000
```

Accès : [**http://IP_DE_LA_VM:8000**](http://IP_DE_LA_VM:8000)

---

## 🚀 Fonctionnalités

### Importer une recette
1. Copie l'URL d'une vidéo TikTok ou Instagram
2. Colle-la dans le champ en haut de l'interface
3. Clique **Importer** — extraction automatique via Gemini

### Gérer les recettes
- **Voir / Éditer** : clique sur 👁 pour ouvrir la modale
  - Modifier titre, portions, temps de préparation
  - Ajouter / supprimer ingrédients et étapes
  - Changer l'image (upload ou regénération Unsplash)
- **Taguer** : tape un tag + Entrée
- **Filtrer** par tag via le menu déroulant
- **Supprimer** une recette

### Exporter en PDF
1. Sélectionne les recettes (cases à cocher ou **Tout sélectionner**)
2. Filtre par tag si besoin
3. Clique **Télécharger le PDF**

Le PDF contient : couverture + table des matières + une page image et une page contenu par recette.

---

## 🔧 Service systemd

```bash
sudo nano /etc/systemd/system/wechef.service
```

```ini
[Unit]
Description=WeChef FastAPI Backend
After=network.target

[Service]
User=root
WorkingDirectory=/home/projets/wechef/wechef-backend
Environment="PATH=/home/projets/wechef/wechef-backend/.venv/bin"
ExecStart=/home/projets/wechef/wechef-backend/.venv/bin/uvicorn main:app --host 0.0.0.0 --port 8000
Restart=always

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable wechef
sudo systemctl start wechef
```

---

## 🗄️ Base de données

SQLite — `recipes.db` généré automatiquement au premier démarrage.

**Sauvegarde :**
```bash
cp recipes.db recipes_backup_$(date +%Y%m%d).db
```

---

## 🔑 API Endpoints

| Méthode | Endpoint | Description |
|---|---|---|
| POST | `/extract` | Importer depuis une URL |
| GET | `/recipes` | Lister (filtre `?tag=`) |
| GET | `/recipes/{id}` | Détail |
| PUT | `/recipes/{id}` | Modifier |
| DELETE | `/recipes/{id}` | Supprimer |
| POST | `/recipes/{id}/tags` | Ajouter un tag |
| POST | `/recipes/{id}/image` | Upload image |
| POST | `/recipes/{id}/regenerate-image` | Regénérer image |
| GET | `/tags` | Lister les tags |
| POST | `/export-pdf` | Générer le PDF |
| GET | `/docs` | Swagger UI |

---

## 🔜 Prochaines étapes

- [ ] Stable Diffusion local pour des images IA liées à la recette
- [ ] Recherche par titre
- [ ] Tri des recettes
- [ ] Thèmes PDF personnalisables
- [ ] Import depuis Marmiton / sites web

