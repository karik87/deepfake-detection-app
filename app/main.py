from fastapi import FastAPI, Request, Form
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel
from typing import Union
import json
import uuid
import random

from .data_mock import INTERVENTION_CARICATURE, INTERVENTION_TEXT
from .stimuli import get_session_stimuli
from .database import get_db

app = FastAPI(title="Deepfake Detection Study")

app.mount("/static", StaticFiles(directory="app/static"), name="static")
templates = Jinja2Templates(directory="app/templates")

IMAGES_PER_CLASS_PER_PHASE = 10  # 10 real + 10 ai = 20 zdjęć w Pre-teście i 20 w Post-teście


class AnswerSubmission(BaseModel):
    session_id: str
    phase: str
    image_id: Union[str, int]
    ground_truth: str
    user_choice: str
    confidence_score: int
    response_time_seconds: float


class InterventionCompletion(BaseModel):
    session_id: str
    duration_seconds: float


@app.get("/")
@app.get("/consent")
async def consent_page(request: Request):
    return templates.TemplateResponse(request=request, name="consent.html")


@app.get("/questionnaire")
async def questionnaire_page(request: Request):
    return templates.TemplateResponse(request=request, name="questionnaire.html")


@app.post("/start-session")
async def start_session(
    age: int = Form(...),
    gender: str = Form(...),
    it_experience: int = Form(...),
    social_media: str = Form(...),
    self_assessment: int = Form(...)
):
    session_id = f"ID_{uuid.uuid4().hex[:8].upper()}"

    conn = get_db()
    cursor = conn.cursor()

    # Zrównoważony przydział blokowy do grup (równa liczebność grupy eksperymentalnej i kontrolnej)
    cursor.execute("SELECT COUNT(*) FROM sessions WHERE group_type = 'caricature'")
    n_caricature = cursor.fetchone()[0]
    cursor.execute("SELECT COUNT(*) FROM sessions WHERE group_type = 'text'")
    n_text = cursor.fetchone()[0]

    if n_caricature < n_text:
        group_type = "caricature"
    elif n_text < n_caricature:
        group_type = "text"
    else:
        group_type = random.choice(["caricature", "text"])

    cursor.execute("""
        INSERT INTO sessions (session_id, age, gender, it_experience, social_media, self_assessment, group_type)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """, (session_id, age, gender, it_experience, social_media, self_assessment, group_type))
    conn.commit()
    conn.close()

    return RedirectResponse(url=f"/instructions?session_id={session_id}", status_code=303)


@app.get("/instructions")
async def instructions_page(request: Request, session_id: str = ""):
    if not session_id:
        return RedirectResponse(url="/consent")
    return templates.TemplateResponse(request=request, name="instructions.html", context={"session_id": session_id})


@app.get("/pretest")
async def pretest_page(request: Request, session_id: str = ""):
    if not session_id:
        return RedirectResponse(url="/consent")
    pretest_images, _ = get_session_stimuli(session_id, per_class_per_phase=IMAGES_PER_CLASS_PER_PHASE)
    return templates.TemplateResponse(
        request=request,
        name="pretest.html",
        context={"images_json": json.dumps(pretest_images), "session_id": session_id}
    )


@app.get("/intervention")
async def intervention_page(request: Request, session_id: str = ""):
    if not session_id:
        return RedirectResponse(url="/consent")
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT group_type FROM sessions WHERE session_id = ?", (session_id,))
    row = cursor.fetchone()
    conn.close()

    group_type = row["group_type"] if row else "text"
    cards = INTERVENTION_CARICATURE if group_type == "caricature" else INTERVENTION_TEXT

    return templates.TemplateResponse(
        request=request,
        name="intervention.html",
        context={
            "cards_json": json.dumps(cards),
            "session_id": session_id,
            "group_type": group_type
        }
    )


@app.post("/api/complete-intervention")
async def complete_intervention(data: InterventionCompletion):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("""
        UPDATE sessions
        SET intervention_duration_seconds = ?
        WHERE session_id = ?
    """, (data.duration_seconds, data.session_id))
    conn.commit()
    conn.close()
    print(f"[{data.session_id}] Ukończono moduł pośredni w czasie: {data.duration_seconds}s")
    return {"status": "success"}


@app.get("/posttest")
async def posttest_page(request: Request, session_id: str = ""):
    if not session_id:
        return RedirectResponse(url="/consent")
    _, posttest_images = get_session_stimuli(session_id, per_class_per_phase=IMAGES_PER_CLASS_PER_PHASE)
    return templates.TemplateResponse(
        request=request,
        name="posttest.html",
        context={"images_json": json.dumps(posttest_images), "session_id": session_id}
    )


@app.get("/debriefing")
async def debriefing_page(request: Request, session_id: str = ""):
    return templates.TemplateResponse(request=request, name="debriefing.html", context={"session_id": session_id})


@app.post("/api/submit-answer")
async def submit_answer(data: AnswerSubmission):
    gt = data.ground_truth.strip().lower()
    choice = data.user_choice.strip().lower()
    is_correct = 1 if gt == choice else 0

    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO responses (session_id, phase, image_id, ground_truth, user_choice, is_correct, confidence_score, response_time_seconds)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        data.session_id,
        data.phase,
        str(data.image_id),
        gt,
        choice,
        is_correct,
        data.confidence_score,
        data.response_time_seconds
    ))
    conn.commit()
    conn.close()
    print(f"[{data.session_id}] ({data.phase}) {data.image_id} | Prawda: {gt} | Wybór: {choice} | RT: {data.response_time_seconds}s")
    return {"status": "success"}