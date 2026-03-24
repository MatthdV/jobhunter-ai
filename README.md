# JobHunter AI

[![Python 3.11+](https://img.shields.io/badge/Python-3.11+-blue.svg)](https://python.org)
[![License](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)

Système semi-autonome de recherche d'emploi piloté par IA. Scraping → matching → génération de candidatures personnalisées → validation humaine → suivi des réponses.

Tu n'as qu'à **passer les entretiens**.

## Quick Start

```bash
# 1. Cloner et installer
git clone https://github.com/MatthdV/jobhunter-ai.git
cd jobhunter-ai
pip install -e ".[dev]"

# 2. Configurer l'environnement
cp .env.example .env
# Remplir .env avec vos clés API (voir section Supported LLM Providers)

# 3. Initialiser la base de données
python -m src.main init-db

# 4. Installer Playwright (scraping, première fois uniquement)
playwright install chromium

# 5. Scanner les offres
python -m src.main scan --source wttj --limit 20

# 6. Lancer le matching IA (score > 80%)
python -m src.main match --min-score 80

# 7. Générer les candidatures (dry-run par défaut)
python -m src.main apply --dry-run
```

## Supported LLM Providers

Choisir le provider via `LLM_PROVIDER` dans `.env` :

| Provider | `LLM_PROVIDER` | Modèle par défaut | Variable clé |
|---|---|---|---|
| Anthropic (Claude) | `anthropic` | `claude-opus-4-6` | `ANTHROPIC_API_KEY` |
| OpenAI | `openai` | `gpt-4o` | `OPENAI_API_KEY` |
| Mistral | `mistral` | `mistral-large-latest` | `MISTRAL_API_KEY` |
| DeepSeek | `deepseek` | `deepseek-chat` | `DEEPSEEK_API_KEY` |
| OpenRouter | `openrouter` | `openai/gpt-4o` | `OPENROUTER_API_KEY` |

### Exemples `.env`

**Anthropic (défaut)**
```env
LLM_PROVIDER=anthropic
ANTHROPIC_API_KEY=sk-ant-...
```

**OpenAI**
```env
LLM_PROVIDER=openai
OPENAI_API_KEY=sk-...
LLM_MODEL=gpt-4o-mini   # optionnel, override le modèle par défaut
```

**Mistral**
```env
LLM_PROVIDER=mistral
MISTRAL_API_KEY=...
```

**DeepSeek**
```env
LLM_PROVIDER=deepseek
DEEPSEEK_API_KEY=sk-...
```

**OpenRouter** (accès à 100+ modèles : Llama, Gemini, Qwen, Kimi…)
```env
LLM_PROVIDER=openrouter
OPENROUTER_API_KEY=sk-or-...
LLM_MODEL=meta-llama/llama-3.1-70b-instruct
```

## Architecture

```
Phase 1 — Préparation  : Analyse profil, génération CV adaptatif
Phase 2 — Recherche    : Scraping (LinkedIn, Indeed, WTTJ, AngelList), matching IA (score > 80%)
Phase 3 — Candidature  : CV + lettre personnalisés → validation humaine → soumission
Phase 4 — Réponse      : Réponses automatiques, détection scam, négociation salariale
Phase 5 — RDV          : Intégration Calendly, briefing entreprise, préparation entretien
```

```
src/
├── main.py               # CLI Typer — point d'entrée
├── config/
│   ├── settings.py       # Pydantic Settings (charge .env)
│   └── profile.yaml      # Profil candidat, rôles cibles, entreprises
├── storage/
│   ├── models.py         # SQLAlchemy ORM : Job, Application, Company, Recruiter
│   └── database.py       # Engine, session factory, init_db(), health_check()
├── scrapers/             # Phase 2 — BaseScraper + LinkedIn/Indeed/WTTJ
├── matching/             # Phase 2 — Scorer (LLM), EmbeddingMatcher
├── generators/           # Phase 3 — CVGenerator, CoverLetterGenerator
├── communications/       # Phase 4 — EmailHandler, TelegramBot, RecruiterResponder
├── scheduler/            # Phase 4 — JobScheduler orchestre toutes les phases
└── analysis/             # Analyse de profil
```

## Commandes CLI

```bash
python -m src.main --help
python -m src.main init-db                          # Initialiser la DB
python -m src.main scan --source linkedin --limit 20  # Scraper les offres
python -m src.main scan --source wttj --limit 50
python -m src.main match                            # Scorer toutes les offres NEW
python -m src.main match --min-score 80             # Seuil personnalisé
python -m src.main apply --dry-run                  # Générer les candidatures (sans envoi)
python -m src.main apply --live                     # Envoi réel (validation Telegram requise)
```

## Décisions de design

- **Human-in-the-loop** : `TelegramBot.request_approval()` bloque avant tout envoi — ne jamais bypasser cette gate
- **Dry-run par défaut** : `DRY_RUN=true` dans `.env` ; `--live` requis pour soumettre
- **Cap journalier** : `MAX_APPLICATIONS_PER_DAY` protège contre les bans
- **Seuil de matching** : seuls les jobs avec `match_score >= MIN_MATCH_SCORE` passent en candidature
- **Source de vérité profil** : `src/config/profile.yaml` pilote le scoring, la génération CV et les keywords — modifier ici, pas dans le code
- **Personnalisation** : chaque CV et lettre est adapté à l'offre via LLM — jamais de candidature générique

## Tests

```bash
pytest                                  # Tous les tests
pytest tests/test_scheduler.py -v      # Un seul fichier
pytest -k "test_score"                 # Un test spécifique
```

## Objectifs KPI

| KPI | Objectif |
|-----|----------|
| Offres analysées | 50/jour |
| Candidatures envoyées | 5-10/jour |
| Taux de réponse | > 15% |
| Entretiens obtenus | 2-3/semaine |

## Auteur

**Matthieu de Villele** — Automation & AI Engineer / RevOps Consultant
