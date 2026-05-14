# JobHunter AI — Guide d'installation

JobHunter AI scanne automatiquement les sites d'emploi, analyse chaque offre par rapport à ton profil et te donne un score de compatibilité dans un dashboard web.

---

## Ce dont tu as besoin avant de commencer

- Le fichier **`profile.yaml`** fourni par Matthieu (avec ton profil candidat)
- Une clé API gratuite sur https://openrouter.ai/keys (compte Google OK)

---

## Étape 1 — Installer Docker Desktop

Docker fait tourner l'application. Pas besoin d'installer Python ou quoi que ce soit d'autre.

1. Va sur https://www.docker.com/products/docker-desktop/
2. Télécharge et installe la version pour ton système :
   - **Mac** → "Mac with Apple Silicon" (Mac 2020+) ou "Mac with Intel Chip" (avant 2020)
   - **Windows** → "Docker Desktop for Windows"
3. Lance Docker Desktop. Attends que l'icône de baleine soit stable (pas d'animation)

**Vérification** — ouvre un terminal et tape :
```
docker --version
```
Tu dois voir : `Docker version 27.x.x`

> **Windows uniquement — si Docker ne démarre pas :**
> Ouvre PowerShell en administrateur et tape :
> ```
> wsl --install
> ```
> Redémarre l'ordinateur, puis relance Docker Desktop.

---

## Étape 2 — Installer Git et télécharger le projet

**Mac**

Ouvre **Terminal** (Cmd+Espace → "Terminal") et tape :
```bash
git --version
```
Si Git n'est pas installé, macOS propose de l'installer — accepte.

Puis télécharge le projet :
```bash
cd ~/Desktop
git clone https://github.com/MatthdV/jobhunter-ai.git
cd jobhunter-ai
```

---

**Windows**

1. Va sur https://git-scm.com/download/win → télécharge et installe Git (options par défaut = OK)
2. Ouvre **Git Bash** depuis le menu Démarrer

> ⚠️ **Utilise Git Bash pour toutes les commandes de ce guide.**
> PowerShell ne fonctionne pas pour ce projet.

Dans Git Bash :
```bash
cd ~/Desktop
git clone https://github.com/MatthdV/jobhunter-ai.git
cd jobhunter-ai
```

---

## Étape 3 — Configurer ton profil (2 questions)

Lance le script de setup :
```bash
bash scripts/init-profile.sh
```

Il te pose 2 questions :
1. **Ton prénom-nom** (ex : `jean-dupont`) → crée le dossier `profiles/jean-dupont/`
2. **Ta clé API OpenRouter** → écrit automatiquement le fichier de config

Ensuite, **glisse ton fichier `profile.yaml`** dans le dossier `profiles/jean-dupont/`  
(Sur Mac, le dossier s'ouvre automatiquement après le script)

C'est tout — pas d'autre fichier à modifier.

---

## Étape 4 — Lancer le dashboard

```bash
PROFILE_DIR=./profiles/TON-PROFIL docker compose up -d jobhunter-web
```

Remplace `TON-PROFIL` par le nom que tu as entré à l'étape 3 (ex: `jean-dupont`).

Ouvre ton navigateur sur **http://localhost:8000**

---

## Scanner des offres

```bash
# Scanner Welcome to the Jungle
PROFILE_DIR=./profiles/TON-PROFIL docker compose run --rm jobhunter python -m src.main scan --source wttj --limit 50

# Analyser et scorer les offres
PROFILE_DIR=./profiles/TON-PROFIL docker compose run --rm jobhunter python -m src.main match
```

Retourne sur http://localhost:8000 pour voir les résultats.

---

## Éviter de retaper PROFILE_DIR à chaque commande

```bash
echo 'export PROFILE_DIR=~/Desktop/jobhunter-ai/profiles/TON-PROFIL' >> ~/.bashrc
source ~/.bashrc
```

Après ça, les commandes sont plus courtes :
```bash
docker compose up -d jobhunter-web
docker compose run --rm jobhunter python -m src.main scan --source wttj --limit 50
```

---

## Commandes utiles

| Action | Commande |
|--------|----------|
| Lancer le dashboard | `PROFILE_DIR=./profiles/TON-PROFIL docker compose up -d jobhunter-web` |
| Arrêter | `docker compose down` |
| Scanner des offres | `PROFILE_DIR=./profiles/TON-PROFIL docker compose run --rm jobhunter python -m src.main scan --source wttj --limit 50` |
| Scorer les offres | `PROFILE_DIR=./profiles/TON-PROFIL docker compose run --rm jobhunter python -m src.main match` |
| Voir les logs | `docker compose logs -f jobhunter-web` |
| Mettre à jour | `git pull && PROFILE_DIR=./profiles/TON-PROFIL docker compose up -d --build jobhunter-web` |

---

## Problèmes courants

**"Cannot connect to the Docker daemon"**
→ Docker Desktop n'est pas lancé. Ouvre-le depuis le menu Démarrer (Windows) ou Applications (Mac).

**Windows : `PROFILE_DIR : command not found`**
→ Tu utilises PowerShell. Ferme-le, ouvre **Git Bash** et réessaie.

**"port 8000 already in use"**
→ Change de port :
```bash
WEB_PORT=8001 PROFILE_DIR=./profiles/TON-PROFIL docker compose up -d jobhunter-web
```
Puis ouvre http://localhost:8001

**"API key invalid" / erreur 401**
→ Ta clé OpenRouter est incorrecte. Relance `bash scripts/init-profile.sh` pour la corriger.

**Le dashboard est vide**
→ Lance `scan` puis `match` (voir section ci-dessus). Vérifie les logs : `docker compose logs -f jobhunter-web`

---

Besoin d'aide → contacte Matthieu.
