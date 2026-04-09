# Docker Setup for Retail API

This guide explains how to build and run the Retail Business Operations API using Docker and Docker Compose.

## Prerequisites

- [Docker](https://www.docker.com/products/docker-desktop) installed
- [Docker Compose](https://docs.docker.com/compose/install/) installed

## Quick Start

### 1. Build and Run with Docker Compose (Recommended)

```bash
# Navigate to the project directory
cd /home/murugesan/retail_api

# Start all services (API + PostgreSQL)
docker-compose up --build
```

The API will be available at: **http://localhost:8000**
- Swagger UI Docs: **http://localhost:8000/docs**
- ReDoc: **http://localhost:8000/redoc**
- Health Check: **http://localhost:8000/health**

### 2. Stop the Services

```bash
# Stop and remove containers
docker-compose down

# Stop and remove containers + volumes (clears database)
docker-compose down -v
```

---

## Building and Running Manually

### Build the Docker Image

```bash
docker build -t retail-api:latest .
```

### Run the PostgreSQL Database Container

```bash
docker run -d \
  --name retail_db \
  -e POSTGRES_USER=postgres \
  -e POSTGRES_PASSWORD=Muru\$234SP \
  -e POSTGRES_DB=sales-db-v2 \
  -p 5432:5432 \
  -v postgres_data:/var/lib/postgresql/data \
  postgres:16-alpine
```

### Wait for Database to be Ready

```bash
# Check if database is ready
docker exec retail_db pg_isready -U postgres
```

### Run the API Container

```bash
docker run -d \
  --name retail_api \
  -e DATABASE_URL=postgresql+asyncpg://postgres:Muru\$234SP@retail_db:5432/sales-db-v2 \
  -p 8000:8000 \
  --link retail_db:db \
  retail-api:latest
```

### View Container Logs

```bash
# API logs
docker logs -f retail_api

# Database logs
docker logs -f retail_db
```

---

## Development Mode with Live Reload

### Using Docker Compose (with volume mounts)

```bash
docker-compose up
```

The `--reload` flag in the Compose file enables hot-reloading when you modify source files.

---

## Cleaning Up

### Remove Containers and Images

```bash
# Remove all containers
docker container prune

# Remove unused images
docker image prune

# Specific removal
docker stop retail_api retail_db
docker rm retail_api retail_db
docker rmi retail-api:latest
docker volume rm retail_api_postgres_data
```

---

## Useful Commands

### Shell Access

```bash
# Access API container shell
docker exec -it retail_api bash

# Access database container shell
docker exec -it retail_db bash
```

### Database Commands

```bash
# Connect to PostgreSQL inside container
docker exec -it retail_db psql -U postgres -d sales-db-v2

# Common psql commands inside container:
# \dt              — list tables
# \d table_name    — describe table
# \l               — list databases
# \q               — quit
```

### Run Custom Commands

```bash
# Execute a command in API container
docker exec retail_api uvicorn main:app --help

# Run Python scripts
docker exec retail_api python -c "import sqlalchemy; print(sqlalchemy.__version__)"
```

---

## Troubleshooting

### Port Already in Use

```bash
# Find what's using port 8000
lsof -i :8000

# Find what's using port 5432
lsof -i :5432

# Kill the process (replace <PID> with actual PID)
kill -9 <PID>
```

### Database Connection Issues

```bash
# Check if database is running
docker ps

# Test database connectivity
docker exec retail_api python -c "
import asyncpg
import asyncio
async def test():
    conn = await asyncpg.connect('postgresql://postgres:Muru\$234SP@db:5432/sales-db-v2')
    await conn.close()
asyncio.run(test())
"
```

### View Resource Usage

```bash
# Monitor container stats
docker stats

# View disk usage
docker system df
```

---

## Environment Configuration

To customize database credentials or other settings:

1. Create a `.env` file (copy from `.env.example`)
2. Modify values as needed
3. Update `docker-compose.yml` to reference `.env` file:

```yaml
env_file:
  - .env
```

---

## Production Deployment Notes

For production use:

1. **Security**: Change default database password in `docker-compose.yml`
2. **Environment**: Set `ENVIRONMENT=production` in `.env`
3. **Persistence**: Use named volumes for database data
4. **Restart Policy**: Add restart policy to services:
   ```yaml
   restart_policy:
     condition: on-failure
     delay: 5s
     max_attempts: 5
   ```
5. **Resource Limits**: Set memory and CPU limits:
   ```yaml
   deploy:
     resources:
       limits:
         cpus: '1'
         memory: 1G
   ```
6. **Logging**: Configure log drivers for centralized logging
7. **Health Checks**: Endpoint `/health` is already configured

---

## File Structure

```
retail_api/
├── Dockerfile              # Container image definition
├── docker-compose.yml      # Multi-container orchestration
├── .dockerignore          # Files to exclude from image
├── .env.example           # Environment variables template
├── main.py                # FastAPI entrypoint
├── requirements.txt       # Python dependencies
├── db/
│   └── database.py        # Database configuration
├── routers/               # API endpoints
│   ├── sales_manager.py
│   ├── supplier_manager.py
│   └── analyst.py
└── schemas/
    └── schemas.py         # Pydantic models
```

---

## Next Steps

- Mount database initialization scripts in `docker-compose.yml`
- Set up CI/CD pipeline to build and push images to registry
- Consider using Kubernetes for orchestration at scale
