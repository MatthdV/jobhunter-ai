# 🎯 JobHunter AI

[![Python](https://img.shields.io/badge/Python-3.11+-blue.svg)](https://python.org)
[![License](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)

Système de recherche d'emploi automatisé avec IA.

## Vision

Agent IA qui gère 100% du processus de recherche d'emploi : **Détection** → **Candidature** → **Négociation** → **Entretien**

Tu n'as qu'à **passer les entretiens**.

## 🏗️ Architecture

```
┌─────────────────────────────────────────────────────────────┐
│  PHASE 1: PRÉPARATION                                       │
│  ├── Analyse Portfolio → Extraction compétences             │
│  ├── Optimisation LinkedIn → Profil attractif               │
│  └── Génération CVs → Versions adaptatives                  │
├─────────────────────────────────────────────────────────────┤
│  PHASE 2: RECHERCHE                                         │
│  ├── Scraping LinkedIn, Indeed, WTTJ                        │
│  ├── Matching IA → Score adéquation > 80%                   │
│  └── Filtrage → Salaire, remote, stack technique            │
├─────────────────────────────────────────────────────────────┤
│  PHASE 3: CANDIDATURE (Semi-Auto)                           │
│  ├── Génération CV personnalisé → Par offre                 │
│  ├── Rédaction lettre motivation → Ton humain               │
│  ├── Soumission → Validation humaine requise                │
│  └── Suivi → Relances intelligentes                         │
├─────────────────────────────────────────────────────────────┤
│  PHASE 4: RÉPONSE & NÉGOCIATION                             │
│  ├── Analyse réponses recruteurs                            │
│  ├── Réponses automatiques → Questions courantes            │
│  ├── Négociation salariale → Scripts                        │
│  └── Détection scam → Filtre offres frauduleuses            │
├─────────────────────────────────────────────────────────────┤
│  PHASE 5: RDV & PRÉPARATION                                 │
│  ├── Intégration Calendly → Booking auto                    │
│  ├── Analyse entreprise → Rapport pré-entretien             │
│  ├── Préparation questions → Tech + comportemental          │
│  └── Briefing final → Récap Telegram + Email                │
└─────────────────────────────────────────────────────────────┘
```

## 📊 Configuration

### Profil Cible
- **Nom** : Matthieu de Villele
- **Rôle** : Automation & AI Engineer / RevOps Consultant
- **Secteurs** : FinTech, SaaS, Consulting
- **Localisation** : Full Remote (Europe)
- **Salaire visé** : 80k€+

### Sources d'Offres
- LinkedIn Jobs
- Indeed
- Welcome to the Jungle
- AngelList (startups)
- WeWorkRemotely

### Mode de Fonctionnement
**Semi-automatique** : Chaque candidature est validée par l'utilisateur avant envoi.

## 🎯 Objectifs

| KPI | Objectif |
|-----|----------|
| Offres analysées | 50/jour |
| Candidatures envoyées | 5-10/jour |
| Taux réponse | > 15% |
| Entretiens obtenus | 2-3/semaine |
| Temps économisé | 10h/semaine |

## 🛠️ Stack Technique

| Composant | Technologie |
|-----------|-------------|
| Scraping | Playwright + Python |
| Matching IA | Claude/GPT-4 + Embeddings |
| Génération CV | LaTeX + Jinja2 |
| Email | Gmail API |
| Calendly | Calendly API |
| Notifications | Telegram + Email |
| Storage | Notion / PostgreSQL |

## 🚀 Utilisation

```bash
# Installation
git clone https://github.com/MatthdV/jobhunter-ai.git
cd jobhunter-ai

# Configuration
export LINKEDIN_COOKIES="li_at=...; JSESSIONID=..."
export CALENDLY_API_KEY="..."
export GMAIL_CREDENTIALS="..."

# Lancer
python3 main.py --mode semi-auto
```

## ⚠️ Sécurité & Éthique

- Max 20 candidatures/jour (évite ban LinkedIn)
- Matching strict > 80% (pas de spam)
- Validation humaine obligatoire
- Stockage local chiffré

## 📅 Roadmap

- [x] Création architecture
- [ ] Analyse portfolio GitHub
- [ ] Optimisation LinkedIn
- [ ] Module scraping offres
- [ ] Système matching IA
- [ ] Génération CV/Lettres
- [ ] Intégration Calendly
- [ ] Déploiement

## 👨‍💻 Auteur

**Matthieu de Villele** - Automation & AI Engineer
- Portfolio: [matthieudevillele.com](https://matthieudevillele.com)
- LinkedIn: [linkedin.com/in/matthieu-devillele](https://linkedin.com/in/matthieu-devillele)

---

*Projet en cours de développement.*
