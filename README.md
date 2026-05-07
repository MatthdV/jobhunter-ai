# JobHunter AI

[![Python 3.11+](https://img.shields.io/badge/Python-3.11+-blue.svg)](https://python.org)
[![License](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)
[![Pipeline](https://img.shields.io/badge/Gmail→Scorer-operational-brightgreen.svg)](#current-status)

Système semi-autonome de recherche d'emploi piloté par IA.

**Gmail alerts → scoring LLM multi-critères → matching ≥ 80% → CV + lettre personnalisés → validation humaine → envoi.**

Tu n'as qu'à **passer les entretiens**.

## Current Status

| Phase | Composant | Statut |
|-------|-----------|--------|
| 2 — Recherche | Gmail alerts scraper | ✅ Opérationnel |
| 2 — Recherche | Scorer LLM (5 blocs, score A–F) | ✅ Opérationnel |
| 2 — Recherche | JSearch / Indeed API | 🚧 Subscription requise |
| 2 — Recherche | WTTJ / LinkedIn scraper | 📋 Planifié |
| 3 — Candidature | CV + lettre personnalisés | 📋 Planifié |
| 4 — Réponse | Réponses automatiques | 📋 Planifié |
| 5 — RDV | Briefing entreprise + prep entretien | 📋 Planifié |

**Résultats semaine 1** : 49 offres collectées → 42 scorées → 2 matchs qualifiés (≥ 80%)

## Quick Start

```bash
# 1. Cloner et installer
git clone https://github.com/MatthdV/jobhunter-ai.git
cd jobhunter-ai
pip install -e ".[dev]"

# 2. Configurer l'environnement
cp .env.example .env
# Remplir .env (voir section LLM Providers ci-dessous)

# 3. Initialiser la base de données
python -m src.main init-db

# 4. Scanner via Gmail alerts (pipeline opérationnel)
python -m src.main scan --source gmail_alerts --limit 50

# 5. Lancer le matching IA
python -m src.main match --min-score 80

# 6. Générer les candidatures (dry-run par défaut)
python -m src.main apply --dry-run
```

### Exemple de sortie

```
$ python -m src.main scan --source gmail_alerts --limit 50
[INFO] GmailJobAlertScraper: fetching alerts...
[INFO] 49 jobs found, 42 new
[INFO] Scoring 42 jobs with LLM...

$ python -m src.main match --min-score 80
[INFO] 2 jobs matched (score ≥ 80%)
  → "Automation & AI Manager" @ Contentsquare   [score: 87/100]
  → "RevOps Lead" @ Aircall                     [score: 82/100]
```

## Supported LLM Providers

Choisir le provider via `LLM_PROVIDER` dans `.env` :

| Provider | `LLM_PROVIDER` | Modèle par défaut | Variable clé |
|---|---|---|---|
| Anthropic (Claude) | `anthropic` | `claude-sonnet-4-6` | `ANTHROPIC_API_KEY` |
| OpenAI | `openai` | `gpt-4o` | `OPENAI_API_KEY` |
| Mistral | `mistral` | `mistral-large-latest` | `MISTRAL_API_KEY` |
| DeepSeek | `deepseek` | `deepseek-chat` | `DEEPSEEK_API_KEY` |
| OpenRouter | `openrouter` | `openai/gpt-4o` | `OPENROUTER_API_KEY` |

```env
# Anthropic (défaut)
LLM_PROVIDER=anthropic
ANTHROPIC_API_KEY=sk-ant-...

# OpenRouter — accès 100+ modèles (Llama, Gemini, Qwen…)
LLM_PROVIDER=openrouter
OPENROUTER_API_KEY=sk-or-...
LLM_MODEL=meta-llama/llama-3.1-70b-instruct
```

## Architecture

```
Phase 1 — Préparation  : Analyse profil, génération CV adaptatif
Phase 2 — Recherche    : Gmail alerts + JSearch/Indeed/WTTJ → scoring LLM → matching ≥ 80%  ← ici
Phase 3 — Candidature  : CV + lettre personnalisés → validation humaine → soumission
Phase 4 — Réponse      : Réponses automatiques, détection scam, négociation salariale
Phase 5 — RDV          : Intégration Calendly, briefing entreprise, préparation entretien
```

```
src/
├── main.py                    # CLI Typer — point d'entrée
├── config/
│   ├── settings.py            # Pydantic Settings (charge .env)
│   └── profile.yaml           # Profil candidat, rôles cibles, entreprises ← source de vérité
├── storage/
│   ├── models.py              # SQLAlchemy ORM : Job, Application, Company, Recruiter
│   └── database.py            # Engine, session factory, init_db()
├── scrapers/
│   ├── gmail_scraper.py       # ✅ Gmail alerts → jobs DB
│   ├── indeed_scraper.py      # 🚧 JSearch API (subscription requise)
│   └── base.py                # BaseScraper
├── matching/
│   └── scorer.py              # ✅ Scoring LLM 5 blocs (skills/exp/sector/salary/remote)
├── generators/                # 📋 CVGenerator, CoverLetterGenerator
├── communications/            # 📋 EmailHandler, TelegramBot, RecruiterResponder
└── scheduler/                 # 📋 JobScheduler orchestre toutes les phases
```

## Scoring multi-blocs

Le scorer évalue chaque offre sur 5 dimensions via LLM, sans embeddings :

| Bloc | Poids | Ce qui est évalué |
|------|-------|-------------------|
| Skills match | 35% | Compétences techniques vs JD |
| Expérience | 25% | Séniorité, secteurs, taille équipe |
| Secteur / entreprise | 20% | Culture, stage, notoriété |
| Salaire | 10% | Fourchette vs attentes |
| Remote / localisation | 10% | Modalités de travail |

Score final → grade A–F. Seuil candidature : ≥ 80 (grade A/B).

## Commandes CLI

```bash
python -m src.main --help
python -m src.main init-db

# Scraping
python -m src.main scan --source gmail_alerts --limit 50   # ✅ opérationnel
python -m src.main scan --source indeed --limit 20         # 🚧 JSearch requis
python -m src.main scan --source wttj --limit 50           # 📋 planifié

# Matching
python -m src.main match --min-score 80

# Candidature
python -m src.main apply --dry-run    # génère sans envoyer
python -m src.main apply --live       # envoi réel (validation Telegram requise)
```

## Décisions de design

- **Human-in-the-loop** : `TelegramBot.request_approval()` bloque avant tout envoi — gate non bypassable
- **Dry-run par défaut** : `DRY_RUN=true` dans `.env` ; `--live` requis pour soumettre
- **Cap journalier** : `MAX_APPLICATIONS_PER_DAY` protège contre les bans plateformes
- **Profile YAML** : `src/config/profile.yaml` pilote scoring + CV + keywords — une seule source de vérité
- **Personnalisation sur volume** : chaque candidature est tailored via LLM — zéro candidature générique
- **Provider-agnostic** : swap LLM en 1 ligne d'env var — pas de lock-in Anthropic

## Tests

```bash
pytest                              # tous les tests
pytest tests/test_scrapers.py -v    # scrapers uniquement
pytest -k "test_score"              # un test spécifique
```

## Roadmap

- [ ] JSearch / RapidAPI → jobs avec JD complet (blocker actuel : subscription)
- [ ] WTTJ + LinkedIn scrapers
- [ ] CV génératif (Jinja2 → WeasyPrint → PDF)
- [ ] Cover letter personnalisée par offre
- [ ] Telegram bot validation gate
- [ ] Gmail auto-réponses recruters
- [ ] Dashboard web (FastAPI + SQLite)

## Auteur

**Matthieu de Villele** — Automation & AI Engineer / RevOps Consultant

[LinkedIn](https://www.linkedin.com/in/matthieudevillele/) · [GitHub](https://github.com/MatthdV)
