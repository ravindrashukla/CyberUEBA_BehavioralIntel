"""FastAPI application for Cyber UEBA Behavioral Intelligence."""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware


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

    app.include_router(entity_router, prefix="/api/v1/entities", tags=["entities"])
    app.include_router(trajectory_router, prefix="/api/v1/trajectories", tags=["trajectories"])
    app.include_router(detection_router, prefix="/api/v1/detection", tags=["detection"])

    @app.get("/health")
    def health():
        return {"status": "ok", "service": "cyber-ueba"}

    return app


app = create_app()
