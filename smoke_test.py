import asyncio
from loguru import logger

async def run_smoke_test():
    logger.info("Smoke test requires the API server to be running.")
    logger.info("Run: uvicorn api.main:app")
    logger.info("Then: curl http://localhost:8000/")
    logger.info("Or: curl http://localhost:8000/signals?limit=5")

if __name__ == "__main__":
    asyncio.run(run_smoke_test())
