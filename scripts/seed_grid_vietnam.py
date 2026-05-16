"""
Seed catalog.grid_points với lưới ~700 điểm 0.2° phủ toàn Việt Nam.

Mục đích: Hệ thống chỉ có ~7-40 trạm thật, không đủ phủ toàn quốc cho heatmap.
Script này sinh grid 0.2° (~22 km) trong bounding box VN, loại bỏ điểm ngoài
đất liền (trên biển/lân cận), gắn province_name dựa trên polygon-in-polygon test.

Sau khi seed, cron job (xem app/grid_ingest/openmeteo_grid.py) sẽ fetch AQI
từ Open-Meteo cho mỗi grid_point và lưu vào analytics.grid_aqi_observations.

Cách chạy:
    cd air-quality-be
    python scripts/seed_grid_vietnam.py

Idempotent: ON CONFLICT (lat, lng) DO NOTHING — chạy lại không sinh duplicate.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path
from typing import Iterable

# Khi chạy script trực tiếp, thêm root project vào sys.path để import app.db
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from shapely.geometry import Point, shape  # type: ignore[import-not-found]
from shapely.prepared import prep  # type: ignore[import-not-found]

import asyncpg  # noqa: E402


# Standalone env loader — không import app.db để tránh kéo theo SQLAlchemy.
def load_local_env() -> None:
    env_path = ROOT / ".env"
    if not env_path.exists():
        return
    for raw_line in env_path.read_text().splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def get_database_url() -> str | None:
    """Get DATABASE_URL, normalize cho asyncpg."""
    url = os.getenv("DATABASE_URL")
    if not url:
        return None
    return url.replace("postgresql+asyncpg://", "postgresql://")


# ─── Tham số grid ─────────────────────────────────────────────────────────
LAT_MIN, LAT_MAX = 8.4, 23.6     # Cà Mau → Hà Giang
LNG_MIN, LNG_MAX = 102.0, 110.0  # Lai Châu → Trường Sa Lớn (ngoài khơi đông)
GRID_STEP = 0.2                   # ~22 km giữa các điểm
GEOJSON_PATH = ROOT / "data" / "vn-provinces.geojson"


def load_provinces() -> list[tuple[str, object]]:
    """Đọc GeoJSON, trả list các (province_name, prepared_geometry)."""
    if not GEOJSON_PATH.exists():
        raise FileNotFoundError(
            f"Không tìm thấy {GEOJSON_PATH}. "
            f"Copy từ air-quality-fe/public/vn-provinces.geojson vào data/."
        )
    with GEOJSON_PATH.open(encoding="utf-8") as f:
        gj = json.load(f)

    out: list[tuple[str, object]] = []
    for feat in gj.get("features", []):
        name = (feat.get("properties") or {}).get("shapeName") or "Unknown"
        geom = shape(feat["geometry"])
        # prepared geometry chạy contains() nhanh hơn ~10× cho query lặp
        out.append((name, prep(geom)))
    return out


def generate_grid() -> Iterable[tuple[float, float]]:
    """Sinh các tuple (lat, lng) với step 0.2° trong bounding box VN."""
    lat = LAT_MIN
    while lat <= LAT_MAX + 1e-9:
        lng = LNG_MIN
        while lng <= LNG_MAX + 1e-9:
            yield round(lat, 5), round(lng, 5)
            lng += GRID_STEP
        lat += GRID_STEP


def filter_land_points(
    candidates: Iterable[tuple[float, float]],
    provinces: list[tuple[str, object]],
) -> list[dict]:
    """Giữ lại điểm nằm trong polygon của 1 tỉnh nào đó."""
    kept: list[dict] = []
    for lat, lng in candidates:
        pt = Point(lng, lat)  # Shapely Point là (x, y) = (lng, lat)
        for name, prep_geom in provinces:
            if prep_geom.contains(pt):
                kept.append({
                    "lat": lat,
                    "lng": lng,
                    "province_name": name,
                    "province_code": _slugify_province(name),
                })
                break
    return kept


def _slugify_province(name: str) -> str:
    """'KhánhHòa' -> 'khanhhoa' (ASCII, không dấu). Phục vụ làm code URL-safe."""
    import unicodedata
    # NFD decomposition: 'á' -> 'a' + combining_acute
    decomposed = unicodedata.normalize("NFD", name)
    # Lọc combining diacritics + chuyển 'đ' -> 'd' thủ công (NFD không tách 'đ')
    ascii_only = "".join(c for c in decomposed if unicodedata.category(c) != "Mn")
    ascii_only = ascii_only.replace("đ", "d").replace("Đ", "D")
    return "".join(c for c in ascii_only.lower() if c.isalnum())


async def insert_grid_points(points: list[dict]) -> int:
    """Bulk upsert grid points. Trả về số rows đã insert (không tính conflicts)."""
    db_url = get_database_url()
    if not db_url:
        raise RuntimeError("DATABASE_URL chưa được set trong .env")

    conn = await asyncpg.connect(db_url)
    try:
        before = await conn.fetchval("SELECT COUNT(*) FROM catalog.grid_points")
        await conn.executemany(
            """
            INSERT INTO catalog.grid_points (lat, lng, province_code, province_name, is_land)
            VALUES ($1, $2, $3, $4, TRUE)
            ON CONFLICT (lat, lng) DO UPDATE
                SET province_code = EXCLUDED.province_code,
                    province_name = EXCLUDED.province_name,
                    is_land = TRUE,
                    updated_at = now()
            """,
            [(p["lat"], p["lng"], p["province_code"], p["province_name"]) for p in points],
        )
        after = await conn.fetchval("SELECT COUNT(*) FROM catalog.grid_points")
        return after - before
    finally:
        await conn.close()


async def main() -> None:
    load_local_env()

    print(f"Loading provinces from {GEOJSON_PATH}...")
    provinces = load_provinces()
    print(f"  → {len(provinces)} tỉnh/thành")

    print(f"Sinh grid {GRID_STEP}° trong bbox [{LAT_MIN}, {LNG_MIN}] – [{LAT_MAX}, {LNG_MAX}]...")
    candidates = list(generate_grid())
    print(f"  → {len(candidates)} điểm candidate (trước khi lọc biển)")

    print("Lọc điểm nằm trong đất liền VN (polygon-in-polygon)...")
    land = filter_land_points(candidates, provinces)
    print(f"  → {len(land)} điểm trên đất liền (~{len(land) * 100 // len(candidates)}%)")

    # Thống kê theo tỉnh
    from collections import Counter
    by_prov = Counter(p["province_name"] for p in land)
    print(f"\nTop 10 tỉnh có nhiều grid points nhất:")
    for name, n in by_prov.most_common(10):
        print(f"  {n:3d}  {name}")

    print(f"\nUpserting {len(land)} điểm vào catalog.grid_points...")
    inserted = await insert_grid_points(land)
    print(f"  → {inserted} điểm mới (còn lại là update do conflict)")

    print(f"\n✓ Done. catalog.grid_points hiện có {len(land)} điểm phủ VN.")


if __name__ == "__main__":
    asyncio.run(main())
