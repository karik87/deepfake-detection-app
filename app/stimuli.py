import os
import random
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
REAL_DIR = BASE_DIR / "static" / "images" / "real"
AI_DIR = BASE_DIR / "static" / "images" / "ai"

VALID_EXTENSIONS = (".jpg", ".jpeg", ".png", ".webp")


def _get_image_files(directory: Path) -> list[str]:
    if not directory.exists():
        return []
    # Ignoruje ukryte pliki (np. .DS_Store na macOS) i pobiera tylko obrazy
    files = [
        f for f in os.listdir(directory)
        if not f.startswith(".") and f.lower().endswith(VALID_EXTENSIONS)
    ]
    return sorted(files)


def get_session_stimuli(session_id: str, per_class_per_phase: int = 10) -> tuple[list[dict], list[dict]]:
    """
    Generuje unikalny, przetasowany zestaw bodźców dla danego uczestnika:
    - per_class_per_phase = 10 -> 10 AI + 10 Real (20 zdjęć) w Pre-teście i 20 innych w Post-teście.
    - per_class_per_phase = 5  -> 5 AI + 5 Real (10 zdjęć) w Pre-teście i 10 innych w Post-teście.
    """
    real_files = _get_image_files(REAL_DIR)
    ai_files = _get_image_files(AI_DIR)

    # Generator losowy powiązany z konkretnym session_id (brak powtórzeń między fazami)
    rng = random.Random(session_id)

    total_needed = per_class_per_phase * 2
    n_real = min(len(real_files), total_needed)
    n_ai = min(len(ai_files), total_needed)

    sampled_real = rng.sample(real_files, n_real)
    sampled_ai = rng.sample(ai_files, n_ai)

    half_real = n_real // 2
    half_ai = n_ai // 2

    # Podział na rozłączne pule dla Pre-testu i Post-testu
    pre_real, post_real = sampled_real[:half_real], sampled_real[half_real:]
    pre_ai, post_ai = sampled_ai[:half_ai], sampled_ai[half_ai:]

    pretest_stimuli = [
        {"id": f"real/{fname}", "url": f"/static/images/real/{fname}", "is_ai": False}
        for fname in pre_real
    ] + [
        {"id": f"ai/{fname}", "url": f"/static/images/ai/{fname}", "is_ai": True}
        for fname in pre_ai
    ]

    posttest_stimuli = [
        {"id": f"real/{fname}", "url": f"/static/images/real/{fname}", "is_ai": False}
        for fname in post_real
    ] + [
        {"id": f"ai/{fname}", "url": f"/static/images/ai/{fname}", "is_ai": True}
        for fname in post_ai
    ]

    # Pełne przetasowanie kolejności (losowe przeplatanie AI i Real)
    rng.shuffle(pretest_stimuli)
    rng.shuffle(posttest_stimuli)

    return pretest_stimuli, posttest_stimuli