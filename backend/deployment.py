from mangum import Mangum

from backend.app.main import app, seed_cloud_demo

_initialized = False
_asgi_handler = Mangum(app, lifespan="off")


def handler(event, context):
    global _initialized
    if not _initialized:
        seed_cloud_demo()
        _initialized = True
    return _asgi_handler(event, context)
