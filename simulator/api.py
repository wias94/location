from __future__ import annotations

import asyncio
import os
import secrets
from contextlib import asynccontextmanager
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Annotated, Any

from fastapi import BackgroundTasks, Depends, FastAPI, Header, HTTPException, Query, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import HTMLResponse, JSONResponse, Response
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from pydantic import BaseModel, Field

from .service import SimulatorService

ROOT = Path(__file__).parents[1]
POPULATION_PATH = Path(os.getenv("POPULATION_PATH", ROOT / "data" / "gta_population_with_places.csv"))
PLACES_PATH = Path(os.getenv("PLACES_PATH", ROOT / "data" / "places.csv"))
RELATIONSHIPS_PATH = Path(os.getenv("RELATIONSHIPS_PATH", ROOT / "data" / "relationships.csv"))
EXTERNAL_CONTACTS_PATH = Path(os.getenv("EXTERNAL_CONTACTS_PATH", ROOT / "data" / "external_contacts.csv"))
ROAD_NETWORK_PATH = Path(os.getenv("ROAD_NETWORK_PATH", ROOT / "data" / "road_network.pkl"))
ROUTE_CACHE_PATH = Path(os.getenv("ROUTE_CACHE_PATH", ROOT / "work" / "routes.sqlite"))
ROUTING_MODE = os.getenv("ROUTING_MODE", "straight")
STATE_PATH = Path(os.getenv("STATE_PATH", "/data/simulator-state.json" if Path("/data").exists() else ROOT / "work" / "simulator-state.json"))
ADMIN_API_KEY = os.getenv("ADMIN_API_KEY", "")
PUBLIC_API_KEY = os.getenv("PUBLIC_API_KEY", "")
ADMIN_USER = os.getenv("ADMIN_USER", "admin")
security = HTTPBasic(auto_error=False)
service = SimulatorService(POPULATION_PATH, STATE_PATH, int(os.getenv("SCHEDULE_DAYS", "1")), PLACES_PATH,
                           RELATIONSHIPS_PATH, ROAD_NETWORK_PATH, ROUTE_CACHE_PATH, EXTERNAL_CONTACTS_PATH,
                           ROUTING_MODE)


@asynccontextmanager
async def lifespan(_: FastAPI):
    if os.getenv("APP_ENV") == "production" and len(ADMIN_API_KEY) < 16:
        raise RuntimeError("ADMIN_API_KEY must contain at least 16 characters in production")
    await asyncio.to_thread(service.start)
    maintenance = asyncio.create_task(maintain_schedule())
    route_warming = asyncio.create_task(warm_routes())
    try:
        yield
    finally:
        maintenance.cancel()
        route_warming.cancel()
        service.close()


async def maintain_schedule() -> None:
    while True:
        await asyncio.sleep(30)
        current = service.clock.now()
        if not service.schedule_start <= current.date() < service.schedule_start + timedelta(days=service.days):
            await asyncio.to_thread(service.regenerate, current.date())


async def warm_routes() -> None:
    while True:
        await asyncio.to_thread(service.prewarm_routes)
        await asyncio.sleep(60)


app = FastAPI(title="GTA Synthetic Mobility API", version="1.0.0", lifespan=lifespan)
app.add_middleware(GZipMiddleware, minimum_size=1_000)
origins = [item.strip() for item in os.getenv("CORS_ORIGINS", "").split(",") if item.strip()]
if origins:
    app.add_middleware(CORSMiddleware, allow_origins=origins, allow_methods=["GET"], allow_headers=["*"])


def require_public_key(x_api_key: Annotated[str | None, Header()] = None) -> None:
    if PUBLIC_API_KEY and not secrets.compare_digest(x_api_key or "", PUBLIC_API_KEY):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid API key")


def require_admin_key(x_admin_key: Annotated[str | None, Header()] = None) -> None:
    if not ADMIN_API_KEY or not secrets.compare_digest(x_admin_key or "", ADMIN_API_KEY):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid admin key")


def require_admin_basic(credentials: Annotated[HTTPBasicCredentials | None, Depends(security)]) -> None:
    valid = credentials is not None and bool(ADMIN_API_KEY) and secrets.compare_digest(credentials.username, ADMIN_USER) and secrets.compare_digest(credentials.password, ADMIN_API_KEY)
    if not valid:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Authentication required", headers={"WWW-Authenticate": "Basic"})


class ClockRequest(BaseModel):
    simulation_time: datetime | None = None
    speed: float | None = Field(default=None, ge=0, le=86_400)


class InteractionRequest(BaseModel):
    person_id: str
    lat: float = Field(ge=-90, le=90)
    lng: float = Field(ge=-180, le=180)
    status: str = Field(min_length=1, max_length=40)
    duration_minutes: int = Field(ge=1, le=10_080)
    start_time: datetime | None = None


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "routing_mode": service.routing_mode}


@app.get("/api/v1/simulation", dependencies=[Depends(require_public_key)])
def simulation_status() -> dict[str, object]:
    return service.status()


@app.get("/api/v1/people/{person_id}/location", dependencies=[Depends(require_public_key)])
def person_location(person_id: str, time: datetime | None = None) -> dict[str, object]:
    try:
        return service.location(person_id, time)
    except KeyError:
        raise HTTPException(404, "Unknown person") from None
    except LookupError as error:
        raise HTTPException(422, str(error)) from None


@app.get("/api/v1/world", dependencies=[Depends(require_public_key)])
def world(request: Request, time: datetime | None = None,
          bbox: Annotated[str | None, Query(description="min_lng,min_lat,max_lng,max_lat")] = None,
          compact: bool = True) -> Response:
    try:
        result = service.snapshot(time)
    except LookupError as error:
        raise HTTPException(422, str(error)) from None
    points = result["people"]
    if bbox:
        try:
            min_lng, min_lat, max_lng, max_lat = map(float, bbox.split(","))
        except ValueError:
            raise HTTPException(422, "bbox must be min_lng,min_lat,max_lng,max_lat") from None
        points = [p for p in points if min_lng <= p["lng"] <= max_lng and min_lat <= p["lat"] <= max_lat]
    etag = f'"world-{result["time"][:16]}-v{result["version"]}"'
    if request.headers.get("if-none-match") == etag:
        return Response(status_code=304, headers={"ETag": etag})
    content: dict[str, Any]
    if compact:
        content = {"t": result["time"], "v": result["version"], "p": [[p["id"], p["lat"], p["lng"], p["status"]] for p in points]}
    else:
        content = {**result, "people": points}
    return JSONResponse(content, headers={"ETag": etag, "Cache-Control": "public, max-age=1"})


@app.get("/admin", response_class=HTMLResponse, dependencies=[Depends(require_admin_basic)])
def admin_page() -> str:
    return (Path(__file__).with_name("admin.html")).read_text(encoding="utf-8")


@app.get("/api/v1/admin/config", dependencies=[Depends(require_admin_key)])
def admin_config() -> dict[str, object]:
    return {"simulation": service.status(), "behavior": service.behavior.to_dict(),
            "interactions": [item.to_dict() for item in service.interactions[-100:]]}


@app.post("/api/v1/admin/clock/{action}", dependencies=[Depends(require_admin_key)])
async def control_clock(action: str, body: ClockRequest) -> dict[str, object]:
    try:
        if action == "pause": service.clock.pause()
        elif action == "resume": service.clock.resume()
        elif action == "seek" and body.simulation_time: service.clock.seek(body.simulation_time)
        elif action == "speed" and body.speed is not None: service.clock.set_speed(body.speed)
        else: raise HTTPException(422, "Invalid action or missing value")
        if action == "seek":
            await asyncio.to_thread(service.ensure_coverage, service.clock.now())
        service.version += 1
        service._cache.clear()
        service.save()
        return service.status()
    except ValueError as error:
        raise HTTPException(422, str(error)) from None


@app.put("/api/v1/admin/behavior", dependencies=[Depends(require_admin_key)])
async def update_behavior(body: dict[str, Any]) -> dict[str, object]:
    try:
        service.update_behavior(body)
        result = await asyncio.to_thread(service.regenerate, service.clock.now().date())
        return {"behavior": service.behavior.to_dict(), "regeneration": result}
    except ValueError as error:
        raise HTTPException(422, str(error)) from None


@app.post("/api/v1/admin/regenerate", dependencies=[Depends(require_admin_key)])
async def regenerate(start_date: date | None = None) -> dict[str, object]:
    return await asyncio.to_thread(service.regenerate, start_date)


@app.post("/api/v1/admin/interactions", dependencies=[Depends(require_admin_key)])
def create_interaction(body: InteractionRequest) -> dict[str, Any]:
    try:
        return service.add_interaction(**body.model_dump()).to_dict()
    except KeyError:
        raise HTTPException(404, "Unknown person") from None
    except ValueError as error:
        raise HTTPException(422, str(error)) from None
