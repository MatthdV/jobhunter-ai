# Jobhunter AI — Context

> ARTEFACT GÉNÉRÉ — ne pas éditer manuellement.
> Source : Matthieu_local/projets/jobhunter/historique.md | Régénéré le 2026-05-07 via /archive

## Infos critiques
- Repo : ~/Documents/Claude/Projects/jobhunter-ai/
- Stack : Python 3.14, FastAPI, SQLAlchemy, Playwright, Typer CLI, Anthropic/OpenRouter/Mistral APIs
- DB : SQLite local (`jobhunter.db`) — peut se corrompre si kill mid-write → `sqlite3 db.db "PRAGMA integrity_check"`
- APIs : Anthropic, OpenRouter, Gmail OAuth2, JSearch RapidAPI (expirée → 403), Telegram Bot
- Web UI : `uvicorn src.api.app:app --reload` (port 8000) — livré en session 2026-05-07
- Deploy : local (CLI + dashboard web)

## État actuel
- Dernière tâche : Dashboard web FastAPI/HTMX/Tailwind livré. 81 tests passants. Commit `4f58d68` sur `claude/musing-nobel-245332`
- Prochaine étape : Merger `claude/musing-nobel-245332` → `main` puis vérifier dashboard live avec `uvicorn src.api.app:app --reload`

## Décisions clés (3 plus récentes)
- Dashboard : FastAPI + Jinja2 + HTMX no-build — rejeté : React SPA (transpilation inutile)
- Background tasks : `background_tasks.add_task(_run_scan)` direct — rejeté : `asyncio.ensure_future` (crash sans event loop)
- `TemplateResponse(request, name, ctx)` Starlette v0.27+ — rejeté : ancienne signature → `unhashable dict` en cache Jinja2

## Watch out
- `tracker.start(name)` doit être appelé dans le route handler *avant* `add_task` — sinon race window 409
- `_run_match` : charger IDs en session 1 (fermée), rouvrir session 2 pour scoring async — évite session sync tenue sur await
- `_run_apply` : extraire snapshot job en dict avant fermeture session — évite `DetachedInstanceError`
- JSearch subscription expirée (`69cebe676d…`) → pipeline fonctionne en stub (titre/company, pas JD)
- Activer venv : `source .venv/bin/activate` (Python 3.14)

## Session carry-forward
- Aniket Sen (ex-manager Groupon) a demandé à voir le repo — opportunité réseau, réponse LinkedIn à rédiger
- 10+ jobs cluster 74-79 — avec JSearch actif beaucoup passeront ≥80
- Branche `claude/musing-nobel-245332` pas encore mergée sur main
