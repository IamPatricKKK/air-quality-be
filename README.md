# air-quality-be

FastAPI service cho:

- external providers / connectors
- ingestion pipeline
- normalize / analytics / forecasting
- ops observability cho admin

Repo này đọc trực tiếp từ PostgreSQL schema `sky_pulse` và cung cấp các endpoint vận hành cho `air-quality-admin`.

## Tech stack

- FastAPI
- asyncpg
- PostgreSQL 16
- Docker Compose

## Prerequisites

- Python 3.11+
- `pip`
- Docker Desktop hoặc Colima

## Files quan trọng

- `docker-compose.yml`: chạy service + PostgreSQL local
- `db/schema.sql`: schema local bootstrap
- `db/seed.bootstrap.sql`: bootstrap users, stations và binding để ingest dữ liệu thật
- `openapi/ops.yaml`: đặc tả API hiện tại

## Quick start

### 1. Cài dependencies

```bash
pip install -r requirements.txt
```

### 2. Tạo file môi trường

```bash
cp .env.example .env
```

### 3. Khởi động PostgreSQL local

```bash
docker compose up -d postgres
```

Kiểm tra DB:

```bash
docker compose exec postgres psql -U postgres -d sky_pulse -c "SELECT COUNT(*) FROM catalog.stations;"
```

### 4. Chạy service local

```bash
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

Endpoints kiểm tra nhanh:

- `http://localhost:8000/api/v1/health`
- `http://localhost:8000/api/v1/ops/providers`
- `http://localhost:8000/api/v1/ops/pipeline-runs`
- `http://localhost:8000/api/v1/ops/predictions`

Tất cả endpoint `/api/v1/ops/*` yêu cầu Bearer token hợp lệ do `air-quality-api` phát hành. Repo này verify token qua `JWKS_URL`.

## Chạy full stack bằng Docker

```bash
cp .env.example .env
docker compose up --build
```

Compose này sẽ:

- start PostgreSQL 16 trên host port `5433`
- init schema + bootstrap seed cho `sky_pulse`
- build và chạy service `air-quality-be`

Mặc định container app dùng:

- `DATABASE_URL=postgresql+asyncpg://postgres:postgres@postgres:5432/sky_pulse`
- `JWKS_URL=http://host.docker.internal:3002/api/v1/.well-known/jwks.json`

`JWKS_URL_DOCKER` chỉ hữu ích khi `air-quality-api` đang chạy trên máy host ở cổng `3002`.

Ví dụ gọi endpoint ops bằng token admin:

```bash
TOKEN=$(curl -s -X POST http://localhost:3002/api/v1/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email":"admin@skypulse.local","password":"Admin@123"}' \
  | python3 -c 'import json,sys; print(json.load(sys.stdin)["session"]["access_token"])')

curl http://localhost:8000/api/v1/ops/providers \
  -H "Authorization: Bearer $TOKEN"
```

## Live ingest

Repo này chạy scheduler ingest định kỳ từ Open-Meteo:

- `INGEST_ENABLED=true`: bật scheduler nền
- `INGEST_INTERVAL_MINUTES=30`: chu kỳ đồng bộ
- `OPENMETEO_PAST_HOURS=24`: số giờ lịch sử lấy về mỗi lần sync

Có thể trigger thủ công:

```bash
TOKEN=$(curl -s -X POST http://localhost:3002/api/v1/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email":"admin@skypulse.local","password":"Admin@123"}' \
  | python3 -c 'import json,sys; print(json.load(sys.stdin)["session"]["access_token"])')

curl -X POST http://localhost:8000/api/v1/ops/live-sync \
  -H "Authorization: Bearer $TOKEN"
```

## Scripts hữu ích

```bash
# Xem config compose
docker compose config

# Chỉ bật DB
docker compose up -d postgres

# Bật toàn bộ stack
docker compose up --build

# Reset schema + bootstrap seed
docker compose down -v
docker compose up -d postgres
```

## PostgreSQL notes

- DB mặc định: `sky_pulse`
- Host port mặc định của repo này: `5433`
- Nếu máy đang dùng `5433`, đổi `POSTGRES_PORT` trong `.env` sang cổng khác trước khi chạy `docker compose up`
- Port `5433` được chọn để tránh đụng `5432` nếu bạn cũng đang chạy `air-quality-api`
- Nếu muốn cả `air-quality-api` và `air-quality-be` dùng chung một DB local, chỉ cần sửa `DATABASE_URL` của một repo để trỏ sang cổng DB của repo còn lại

## Cấu trúc local DB

Schema và seed được copy từ nguồn chuẩn của workspace `sky-pulse-monitor` để repo có thể bootstrap độc lập mà không phụ thuộc mount chéo thư mục.
