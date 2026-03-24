.PHONY: build run stop logs scan match apply shell clean

build:
	docker compose build

run:
	docker compose up -d jobhunter-cron

stop:
	docker compose down

logs:
	docker compose logs -f jobhunter-cron

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
