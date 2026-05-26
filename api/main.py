"""FastAPI application for Cyber UEBA Behavioral Intelligence."""
from pathlib import Path
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles


def create_app() -> FastAPI:
    app = FastAPI(
        title="Cyber UEBA - Behavioral Intelligence",
        description="Temporal Trajectory Intelligence for Cybersecurity",
        version="0.1.0",
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Register routers
    from api.entity_routes import router as entity_router
    from api.trajectory_routes import router as trajectory_router
    from api.detection_routes import router as detection_router
    from api.tier3_routes import router as tier3_router

    app.include_router(entity_router, prefix="/api/v1/entities", tags=["entities"])
    app.include_router(trajectory_router, prefix="/api/v1/trajectories", tags=["trajectories"])
    app.include_router(detection_router, prefix="/api/v1/detection", tags=["detection"])
    app.include_router(tier3_router, prefix="/api/v1/tier3", tags=["tier3"])

    @app.get("/health")
    def health():
        return {"status": "ok", "service": "cyber-ueba"}

    # Serve demo UI static files
    ui_path = Path(__file__).parent.parent / "demo" / "ui"
    if ui_path.exists():
        app.mount("/ui", StaticFiles(directory=str(ui_path), html=True), name="demo-ui")

    return app


app = create_app()
