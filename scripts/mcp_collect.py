#!/usr/bin/env python3
"""MCP Collector — Script exécuté par la scheduled task Cowork.

Ce script génère un JSON structuré prêt à être importé par le bot.
Il est conçu pour être lu par Claude dans Cowork qui appelle les MCP tools,
PAS pour être exécuté directement en Python.

=== MODE D'EMPLOI ===

Ce fichier sert de TEMPLATE pour la scheduled task Cowork.
La task Cowork fait ceci :

1. Lit profile.yaml pour connaître les keywords et pays cibles
2. Appelle MCP search_jobs pour chaque keyword × country
3. Appelle MCP get_company_data pour les companies intéressantes
4. Écrit le résultat en JSON dans data/mcp_inbox/

=== FORMAT JSON ATTENDU ===

{
    "schema_version": "1",
    "collected_at": "2026-04-06T14:30:00Z",
    "source": "mcp_indeed",
    "search_params": {
        "keywords": ["automation engineer AI"],
        "country_code": "FR",
        "location": "remote"
    },
    "jobs": [
        {
            "title": "Senior AI Engineer",
            "url": "https://to.indeed.com/xxxxx",
            "company_name": "Anthropic",
            "location": "Remote",
            "country_code": "FR",
            "posted_on": "2026-04-02",
            "job_type": "fulltime",
            "compensation": "90 000 - 120 000 EUR/an",
            "job_id": "indeed_job_id_here",
            "description": null
        }
    ],
    "company": {
        "name": "Anthropic",
        "size": "51 to 200",
        "sector": "Information Technology",
        "description": "AI safety company...",
        "ceo": "Dario Amodei",
        "glassdoor_rating": null,
        "salary_data": {
            "job_title": "AI Engineer",
            "average_salary": 299335,
            "currency": "USD",
            "country": "US"
        }
    }
}

=== INSTRUCTIONS POUR LA SCHEDULED TASK COWORK ===

Voici le prompt exact à utiliser pour la scheduled task :

---BEGIN PROMPT---
Tu es un collecteur de données job pour JobHunter AI.

1. Lis le fichier src/config/profile.yaml pour obtenir :
   - search_keywords (liste de mots-clés)
   - search.countries (liste de pays ISO)
   - search.location (typiquement "remote")
   - target_companies (listes d'entreprises cibles)

2. Pour chaque combinaison keyword × country, appelle l'outil MCP search_jobs :
   - search: <keyword>
   - location: <search.location>
   - country_code: <country>

3. Pour chaque entreprise trouvée dans les résultats (et pour les target_companies),
   appelle l'outil MCP get_company_data :
   - companyName: <company>
   - jobTitle: <le titre du job trouvé>
   - language: "en"
   - location: { country: <country>, usState: null, usStateCode: null, usCity: null }
   - knowledgeCategories: { metadata: true, ratings: true, salaries: true }

4. Construis un fichier JSON par exécution, au format décrit dans scripts/mcp_collect.py.

5. Écris le fichier dans data/mcp_inbox/ avec le nom :
   mcp_collect_YYYY-MM-DD_HHMMSS.json

6. NE PAS écraser les fichiers existants — toujours un nouveau fichier horodaté.

7. Limite : max 5 keywords × 3 pays par exécution pour éviter le rate limiting.
   Rote les pays et keywords entre exécutions.
---END PROMPT---
"""
