.DEFAULT_GOAL := help

# Deploy branch (defaults to main)
BRANCH ?= main

.PHONY: dev dev-down prod prod-down deploy clean help

dev: ## Start local development (http://localhost:3000)
	docker-compose up -d

dev-down: ## Stop local development
	docker-compose down

prod: ## Start production services (with Caddy reverse proxy)
	docker-compose -f docker-compose.yaml -f docker-compose.prod.yaml up -d

prod-down: ## Stop production services
	docker-compose -f docker-compose.yaml -f docker-compose.prod.yaml down

deploy: ## Deploy to EC2 (usage: make deploy BRANCH=main)
	./scripts/deploy.sh $(BRANCH)

clean: ## Clean up Docker images and containers
	docker-compose down --rmi all --volumes --remove-orphans
	docker image prune -f

help: ## Show this help message
	@echo "Available commands:"
	@echo ""
	@echo "  Development:"
	@echo "    dev             Start local development (http://localhost:3000)"
	@echo "    dev-down        Stop local development"
	@echo ""
	@echo "  Production:"
	@echo "    prod            Start production services (with Caddy reverse proxy)"
	@echo "    prod-down       Stop production services"
	@echo "    deploy          Deploy to EC2 (make deploy BRANCH=main)"
	@echo ""
	@echo "  Other:"
	@echo "    clean           Clean up Docker images and containers"
	@echo ""
