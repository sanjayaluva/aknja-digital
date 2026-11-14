from fastapi import FastAPI

app = FastAPI(title="Aknja Digital", version="0.1.0")

@app.get("/health/live", tags=["health"])
def live() -> dict[str, str]:
    return {"status": "alive"}

@app.get("/health/ready", tags=["health"])
def ready() -> dict[str, str]:
    # Replace with real dependency checks before staging.
    return {"status": "ready", "database": "not-yet-wired"}
