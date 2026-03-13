"""Tests CRUD recettes — WeChef."""
from __future__ import annotations


def test_list_recipes_empty(client):
    resp = client.get("/recipes")
    assert resp.status_code == 200
    assert resp.json() == []


def test_create_recipe(client):
    payload = {
        "title": "Tarte tatin",
        "ingredients": [{"name": "Pommes", "quantity": "6", "unit": "pièces"}],
        "steps": ["Éplucher les pommes", "Cuire au four"],
        "servings": 6,
        "prep_time": 45,
    }
    resp = client.post("/recipes", json=payload)
    assert resp.status_code == 201
    data = resp.json()
    assert data["title"] == "Tarte tatin"
    assert data["servings"] == 6
    assert data["prep_time"] == 45
    assert len(data["ingredients"]) == 1
    return data["id"]


def test_get_recipe(client):
    # Création puis récupération
    create_resp = client.post("/recipes", json={"title": "Crêpes", "ingredients": [], "steps": []})
    recipe_id = create_resp.json()["id"]

    resp = client.get(f"/recipes/{recipe_id}")
    assert resp.status_code == 200
    assert resp.json()["title"] == "Crêpes"


def test_get_recipe_not_found(client):
    resp = client.get("/recipes/99999")
    assert resp.status_code == 404


def test_update_recipe(client):
    create_resp = client.post("/recipes", json={"title": "Soupe", "ingredients": [], "steps": []})
    recipe_id = create_resp.json()["id"]

    resp = client.put(f"/recipes/{recipe_id}", json={"title": "Soupe de légumes", "prep_time": 30})
    assert resp.status_code == 200
    assert resp.json()["title"] == "Soupe de légumes"
    assert resp.json()["prep_time"] == 30


def test_delete_recipe(client):
    create_resp = client.post("/recipes", json={"title": "À supprimer", "ingredients": [], "steps": []})
    recipe_id = create_resp.json()["id"]

    resp = client.delete(f"/recipes/{recipe_id}")
    assert resp.status_code == 204

    # Vérification de la suppression
    assert client.get(f"/recipes/{recipe_id}").status_code == 404


def test_add_tag(client):
    create_resp = client.post("/recipes", json={"title": "Risotto", "ingredients": [], "steps": []})
    recipe_id = create_resp.json()["id"]

    resp = client.post(f"/recipes/{recipe_id}/tags", json={"tag": "Italien"})
    assert resp.status_code == 201
    assert resp.json()["tag"] == "italien"  # normalisé en lowercase


def test_list_recipes_pagination(client):
    # Crée 3 recettes
    for i in range(3):
        client.post("/recipes", json={"title": f"Recette {i}", "ingredients": [], "steps": []})

    resp = client.get("/recipes?skip=0&limit=2")
    assert resp.status_code == 200
    assert len(resp.json()) == 2

    resp2 = client.get("/recipes?skip=2&limit=2")
    assert resp2.status_code == 200
    assert len(resp2.json()) == 1


def test_export_pdf_empty_ids(client):
    resp = client.post("/export-pdf", json={"recipe_ids": [99999]})
    assert resp.status_code == 404


def test_create_recipe_invalid_title(client):
    """Titre vide → 422 Unprocessable Entity."""
    resp = client.post("/recipes", json={"title": "", "ingredients": [], "steps": []})
    assert resp.status_code == 422
