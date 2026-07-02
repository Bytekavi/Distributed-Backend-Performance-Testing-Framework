.PHONY: up down logs test build submit clean

up:
	docker compose up -d --build --scale worker=2

down:
	docker compose down

logs:
	docker compose logs -f api worker

test:
	python -m unittest discover -s api/tests -v

build:
	docker compose build

submit:
	bash scripts/submit-test.sh

clean:
	docker compose down -v --remove-orphans

