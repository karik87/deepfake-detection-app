from fastapi import FastAPI, Request, Form, HTTPException
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field
from typing import Union, Literal
import json
import uuid
import random

from .data_mock import INTERVENTION_CARICATURE, INTERVENTION_TEXT
from .stimuli import get_session_stimuli
from .database import get_db

app = FastAPI(title="Deepfake Detection Study", docs_url=None, redoc_url=None)

app.mount("/static", StaticFiles(directory="app/static"), name="static")
templates = Jinja2Templates(directory="app/templates")

IMAGES_PER_CLASS_PER_PHASE = 10  # 10 real + 10 ai = 20 zdjęć na fazę
TOTAL_TRIALS_PER_PHASE = IMAGES_PER_CLASS_PER_PHASE * 2


class AnswerSubmission(BaseModel):
    session_id: str = Field(..., max_length=32)
    phase: Literal["pretest", "posttest"]
    image_id: Union[str, int]
    ground_truth: Literal["real", "ai"]
    user_choice: Literal["real", "ai"]
    confidence_score: int = Field(..., ge=1, le=5)
    response_time_seconds: float = Field(..., ge=0.0, le=3600.0)


class InterventionCompletion(BaseModel):
    session_id: str = Field(..., max_length=32)
    duration_seconds: float = Field(..., ge=0.0, le=3600.0)


def get_session_progress(session_id: str):
    """Sprawdza stan sesji oraz liczbę udzielonych odpowiedzi w każdym etapie."""
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM sessions WHERE session_id = ?", (session_id,))
    session = cursor.fetchone()
    if not session:
        conn.close()
        return None

    cursor.execute("SELECT image_id FROM responses WHERE session_id = ? AND phase = 'pretest'", (session_id,))
    pre_done = {row["image_id"] for row in cursor.fetchall()}

    cursor.execute("SELECT image_id FROM responses WHERE session_id = ? AND phase = 'posttest'", (session_id,))
    post_done = {row["image_id"] for row in cursor.fetchall()}

    conn.close()
    return {
        "session": dict(session),
        "pre_done": pre_done,
        "post_done": post_done,
    }


@app.get("/")
@app.get("/consent")
async def consent_page(request: Request):
    return templates.TemplateResponse(request=request, name="consent.html")


@app.get("/questionnaire")
async def questionnaire_page(request: Request):
    return templates.TemplateResponse(request=request, name="questionnaire.html")


@app.post("/start-session")
async def start_session(
    age: int = Form(..., ge=18, le=99),
    gender: str = Form(..., max_length=50),
    it_experience: int = Form(..., ge=0, le=5),
    social_media: str = Form(..., max_length=100),
    self_assessment: int = Form(..., ge=0, le=5)
):
    session_id = f"ID_{uuid.uuid4().hex[:8].upper()}"

    conn = get_db()
    cursor = conn.cursor()

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
    """, (session_id, age, gender.strip(), it_experience, social_media.strip(), self_assessment, group_type))
    conn.commit()
    conn.close()

    return RedirectResponse(url=f"/instructions?session_id={session_id}", status_code=303)


@app.get("/instructions")
async def instructions_page(request: Request, session_id: str = ""):
    prog = get_session_progress(session_id)
    if not prog:
        return RedirectResponse(url="/consent")
    if prog["session"]["completed"] == 1:
        return RedirectResponse(url=f"/debriefing?session_id={session_id}")
    if len(prog["pre_done"]) > 0:
        return RedirectResponse(url=f"/pretest?session_id={session_id}")
    return templates.TemplateResponse(request=request, name="instructions.html", context={"session_id": session_id})


@app.get("/pretest")
async def pretest_page(request: Request, session_id: str = ""):
    prog = get_session_progress(session_id)
    if not prog:
        return RedirectResponse(url="/consent")
    if prog["session"]["completed"] == 1:
        return RedirectResponse(url=f"/debriefing?session_id={session_id}")
    if len(prog["pre_done"]) >= TOTAL_TRIALS_PER_PHASE:
        return RedirectResponse(url=f"/intervention?session_id={session_id}")

    pretest_images, _ = get_session_stimuli(session_id, per_class_per_phase=IMAGES_PER_CLASS_PER_PHASE)
    remaining = [
        img for img in pretest_images
        if str(img.get("id") or img.get("image_id") or img.get("filename") or img.get("url", "").split("/")[-1]) not in prog["pre_done"]
    ]

    return templates.TemplateResponse(
        request=request,
        name="pretest.html",
        context={
            "images_json": json.dumps(remaining),
            "session_id": session_id,
            "completed_count": len(prog["pre_done"]),
            "total_count": TOTAL_TRIALS_PER_PHASE
        }
    )


@app.get("/intervention")
async def intervention_page(request: Request, session_id: str = ""):
    prog = get_session_progress(session_id)
    if not prog:
        return RedirectResponse(url="/consent")
    if prog["session"]["completed"] == 1:
        return RedirectResponse(url=f"/debriefing?session_id={session_id}")
    if len(prog["pre_done"]) < TOTAL_TRIALS_PER_PHASE:
        return RedirectResponse(url=f"/pretest?session_id={session_id}")
    if prog["session"]["intervention_duration_seconds"] > 0 or len(prog["post_done"]) > 0:
        return RedirectResponse(url=f"/posttest?session_id={session_id}")

    group_type = prog["session"]["group_type"]
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
        WHERE session_id = ? AND intervention_duration_seconds = 0
    """, (data.duration_seconds, data.session_id))
    conn.commit()
    conn.close()
    return {"status": "success"}


@app.get("/posttest")
async def posttest_page(request: Request, session_id: str = ""):
    prog = get_session_progress(session_id)
    if not prog:
        return RedirectResponse(url="/consent")
    if prog["session"]["completed"] == 1 or len(prog["post_done"]) >= TOTAL_TRIALS_PER_PHASE:
        return RedirectResponse(url=f"/debriefing?session_id={session_id}")
    if len(prog["pre_done"]) < TOTAL_TRIALS_PER_PHASE:
        return RedirectResponse(url=f"/pretest?session_id={session_id}")

    _, posttest_images = get_session_stimuli(session_id, per_class_per_phase=IMAGES_PER_CLASS_PER_PHASE)
    remaining = [
        img for img in posttest_images
        if str(img.get("id") or img.get("image_id") or img.get("filename") or img.get("url", "").split("/")[-1]) not in prog["post_done"]
    ]

    return templates.TemplateResponse(
        request=request,
        name="posttest.html",
        context={
            "images_json": json.dumps(remaining),
            "session_id": session_id,
            "completed_count": len(prog["post_done"]),
            "total_count": TOTAL_TRIALS_PER_PHASE
        }
    )


@app.get("/debriefing")
async def debriefing_page(request: Request, session_id: str = ""):
    prog = get_session_progress(session_id)
    if not prog:
        return RedirectResponse(url="/consent")
    if len(prog["post_done"]) < TOTAL_TRIALS_PER_PHASE:
        return RedirectResponse(url=f"/posttest?session_id={session_id}")

    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("UPDATE sessions SET completed = 1 WHERE session_id = ?", (session_id,))
    conn.commit()
    conn.close()

    return templates.TemplateResponse(request=request, name="debriefing.html", context={"session_id": session_id})


@app.post("/api/submit-answer")
async def submit_answer(data: AnswerSubmission):
    prog = get_session_progress(data.session_id)
    if not prog or prog["session"]["completed"] == 1:
        raise HTTPException(status_code=403, detail="Sesja nieaktywna lub zakończona")

    gt = data.ground_truth.strip().lower()
    choice = data.user_choice.strip().lower()
    is_correct = 1 if gt == choice else 0

    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("""
        INSERT OR IGNORE INTO responses (session_id, phase, image_id, ground_truth, user_choice, is_correct, confidence_score, response_time_seconds)
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
    return {"status": "success"}