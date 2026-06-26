# GrindVacPro — Development helper commands

.PHONY: help install-dev infra-up infra-down scraper transformer analyzer telegram dashboard

help:
	@echo "GrindVacPro Development Commands"
	@echo "=============================="
	@echo "  make install-dev   - Create .venv and install all dependencies"
	@echo "  make infra-up      - Start Docker infrastructure (postgres + redis)"
	@echo "  make infra-down    - Stop Docker infrastructure"
	@echo "  make scraper       - Run scraper service (PowerShell required)"
	@echo "  make transformer   - Run transformer arq worker (PowerShell required)"
	@echo "  make analyzer      - Run analyzer arq worker (PowerShell required)"
	@echo "  make telegram      - Run telegram bot (PowerShell required)"
	@echo "  make dashboard     - Run Streamlit dashboard (PowerShell required)"

install-dev:
	python -m venv .venv
	.venv\Scripts\pip install -r shared\requirements.txt
	.venv\Scripts\pip install -e shared
	.venv\Scripts\pip install -r services\scraper\requirements.txt
	.venv\Scripts\pip install torch --index-url https://download.pytorch.org/whl/cpu
	.venv\Scripts\pip install -r services\transformer\requirements.txt
	.venv\Scripts\pip install -r services\analyzer\requirements.txt
	.venv\Scripts\pip install -r services\telegram_bot\requirements.txt
	.venv\Scripts\pip install -r services\dashboard\requirements.txt

infra-up:
	docker compose up -d postgres redis

infra-down:
	docker compose down postgres redis

scraper:
	set PYTHONPATH=. && .venv\Scripts\python services\scraper\src\main.py

transformer:
	set PYTHONPATH=. && .venv\Scripts\arq services.transformer.src.worker.WorkerSettings

analyzer:
	set PYTHONPATH=. && .venv\Scripts\arq services.analyzer.src.worker.WorkerSettings

telegram:
	set PYTHONPATH=. && .venv\Scripts\python services\telegram_bot\src\main.py

dashboard:
	set PYTHONPATH=. && .venv\Scripts\streamlit run services\dashboard\src\app.py --server.headless=true