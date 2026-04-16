from fastapi import FastAPI, Request, Response
from fastapi.responses import RedirectResponse
from starlette.middleware.cors import CORSMiddleware

from routers import auth, users, customers, business, products, orders, inventory
from settings import settings

app = FastAPI()

app.include_router(auth.router)
app.include_router(users.router)
app.include_router(customers.router)
app.include_router(business.router)
app.include_router(products.router)
app.include_router(orders.router)
app.include_router(inventory.router)


@app.get("/")
def greet():
    return {
        "message": "Welcome to Jalaram Khakhra Order Management System!",
    }


@app.get("/favicon.ico", include_in_schema=False)
async def favicon():
    return Response(status_code=204)


app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.middleware("http")
async def enforce_canonical_host(request: Request, call_next):
    canonical_host = settings.CANONICAL_HOST
    # Avoid redirecting CORS preflight or browser XHR/fetch requests.
    # Redirects on preflight are blocked by browsers.
    if canonical_host and request.method != "OPTIONS" and "origin" not in request.headers:
        req_host = request.url.hostname
        if req_host and req_host != canonical_host:
            port = settings.CANONICAL_PORT or request.url.port
            scheme = settings.CANONICAL_SCHEME or request.url.scheme
            netloc = f"{canonical_host}:{port}" if port else canonical_host
            target = request.url.replace(scheme=scheme, netloc=netloc)
            return RedirectResponse(url=str(target), status_code=307)
    return await call_next(request)