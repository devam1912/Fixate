# Production Deployment Architecture & Cloud Sandboxing Guide

This document details the production deployment architecture for **Fixate: Self-Healing CI/Codebase Agent**, specifically addressing containerized cloud execution, persistent vector stores, and isolated Docker-in-Docker sandbox runners.

---

## 1. Cloud Architecture Overview

```
 ┌───────────────────────────────────┐
 │   Vercel / Netlify Frontend       │
 │   React + TS Dashboard Static SPA │
 └─────────────────┬─────────────────┘
                   │ HTTPS / SSE / WebSockets
                   ▼
 ┌───────────────────────────────────┐
 │   Render / Railway Web API        │
 │   FastAPI + Uvicorn Async Server  │
 └─────────────────┬─────────────────┘
                   │ Redis / Celery Job Queue
                   ▼
 ┌───────────────────────────────────┐
 │   Dedicated Sandbox Worker VM     │
 │   (AWS EC2 / DigitalOcean Droplet)│
 │   Native Docker Socket Access     │
 │   Isolated Verification Sandbox   │
 └───────────────────────────────────┘
```

---

## 2. Docker Sandbox Cloud Execution Strategy

### The Cloud Challenge
Standard PaaS hosting providers (such as Render, Railway, or Vercel serverless functions) run application containers inside lightweight unprivileged VMs or firewalled runtime environments. They **do not support nested Docker execution (Docker-in-Docker)** or mounting the host Docker socket (`/var/run/docker.sock`).

### Production Solution: Decoupled Worker Architecture
To guarantee security and true isolated container execution without compromising web server scalability:

1. **Web API Tier (Render / Railway)**:
   - Hosts the FastAPI REST and SSE live streaming server.
   - Handles AST codebase graph queries, RAG context retrieval, and structured patch generation via LLM API calls.
   - Pushes sandbox verification jobs to a Redis job queue (Celery / RQ).

2. **Sandbox Worker VM Tier (AWS EC2 / DigitalOcean Droplet / GCP Compute)**:
   - A dedicated VM running Linux (Ubuntu 22.04 LTS) with native Docker daemon access.
   - Listens to the Redis job queue for verification execution tasks.
   - Spins up ephemeral `python:3.11-slim` containers per attempt, mounts temporary repositories, executes targeted pytest suites with `--network=none` isolation, and reports structured stdout/stderr results back to the API.

---

## 3. Environment Variables & Setup

Create a `.env` file in the project root with the following variables:

```bash
# LLM Provider Configuration (Priority: Free Tier)
FIXATE_LLM_PROVIDER=gemini       # Options: gemini | openai | ollama
GEMINI_API_KEY=your_gemini_key   # Google Gemini 2.5 Flash Free Tier
OPENAI_API_KEY=your_openai_key   # Optional secondary provider

# Local / Hosted Vector Database
CHROMA_SERVER_HOST=localhost
CHROMA_SERVER_HTTP_PORT=8000

# Backend API Configuration
PORT=8000
HOST=0.0.0.0
ALLOWED_ORIGINS=http://localhost:5173,https://fixate-dashboard.vercel.app
```

---

## 4. Frontend & Backend Production Builds

### Backend API (Docker Container)
```bash
docker build -t fixate-api:latest -f Dockerfile .
docker run -d -p 8000:8000 --env-file .env fixate-api:latest
```

### Frontend React Dashboard (Vite Static Build)
```bash
cd dashboard
npm install
npm run build
# Deploy dist/ directory to Vercel, Netlify, or AWS CloudFront
```
