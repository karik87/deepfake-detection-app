from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

app = FastAPI(title="Deepfake Detection Study")

# Podpięcie plików statycznych (CSS, JS, Obrazy)
app.mount("/static", StaticFiles(directory="app/static"), name="static")

# Podpięcie szablonów HTML
templates = Jinja2Templates(directory="app/templates")

@app.get("/")
async def home_page(request: Request):
    return templates.TemplateResponse(request=request, name="index.html")

@app.get("/api/health")
async def health_check():
    return {"status": "ok", "message": "Server is running"}