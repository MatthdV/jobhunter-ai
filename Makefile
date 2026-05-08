.PHONY: build run stop logs scan match apply shell clean web

# Profile directory — override with: make scan PROFILE_DIR=./profiles/xavier-layalle
PROFILE_DIR ?= .
export PROFILE_DIR

build:
	docker compose build

web:
	docker compose up -d jobhunter-web

run:
	docker compose up -d jobhunter-cron

stop:
	docker compose down

logs:
	docker compose logs -f

scan:
	docker compose run --rm jobhunter python -m src.main scan --source wttj --limit 50

match:
	docker compose run --rm jobhunter python -m src.main match

apply:
	docker compose run --rm jobhunter python -m src.main apply --dry-run

apply-live:
	docker compose run --rm jobhunter python -m src.main apply --live

shell:
	docker compose run --rm jobhunter bash

init-db:
	docker compose run --rm jobhunter python -m src.main init-db

clean:
	docker compose down -v --remove-orphans
