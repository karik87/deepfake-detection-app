import csv
import math
import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).resolve().parent / "study_data.db"


def norm_ppf(p: float) -> float:
    """Odwrotna dystrybuanta rozkładu normalnego (aproksymacja Acklama)."""
    a = [-3.969683028665376e+01, 2.209460984245205e+02, -2.759285104469687e+02,
         1.383577518672690e+02, -3.066479806614716e+01, 2.506628277459239e+00]
    b = [-5.447609879822406e+01, 1.615858368580409e+02, -1.556989798598866e+02,
         6.680131188771972e+01, -1.328068155288572e+01]
    c = [-7.784894002430293e-03, -3.223964580411365e-01, -2.400758277161838e+00,
         -2.549732539343734e+00, 4.374664141464968e+00, 2.938163982698783e+00]
    d = [7.784695709041462e-03, 3.224671290700398e-01, 2.445134137142996e+00,
         3.754408661907416e+00]

    p_low = 0.02425
    p_high = 1.0 - p_low

    if p < p_low:
        q = math.sqrt(-2.0 * math.log(p))
        return (((((c[0] * q + c[1]) * q + c[2]) * q + c[3]) * q + c[4]) * q + c[5]) / \
               ((((d[0] * q + d[1]) * q + d[2]) * q + d[3]) * q + 1.0)
    elif p <= p_high:
        q = p - 0.5
        r = q * q
        return (((((a[0] * r + a[1]) * r + a[2]) * r + a[3]) * r + a[4]) * r + a[5]) * q / \
               (((((b[0] * r + b[1]) * r + b[2]) * r + b[3]) * r + b[4]) * r + 1.0)
    else:
        q = math.sqrt(-2.0 * math.log(1.0 - p))
        return -(((((c[0] * q + c[1]) * q + c[2]) * q + c[3]) * q + c[4]) * q + c[5]) / \
                ((((d[0] * q + d[1]) * q + d[2]) * q + d[3]) * q + 1.0)


def compute_sdt_metrics(trials: list[dict]) -> dict:
    """Oblicza wskaźniki SDT (d-prime, kryterium c) z korektą log-liniową Hautusa."""
    if not trials:
        return {
            "n_trials": 0, "acc_pct": "", "hit_rate": "", "fa_rate": "",
            "d_prime": "", "criterion_c": "", "mean_rt_sec": "", "mean_conf": ""
        }

    ai_trials = [t for t in trials if t["ground_truth"] == "ai"]
    real_trials = [t for t in trials if t["ground_truth"] == "real"]

    hits = sum(1 for t in ai_trials if t["user_choice"] == "ai")
    fas = sum(1 for t in real_trials if t["user_choice"] == "ai")

    # Korekta log-liniowa Hautusa (1995) zapobiegająca wartościom nieskończonym przy 0% lub 100%
    hit_rate = (hits + 0.5) / (len(ai_trials) + 1.0)
    fa_rate = (fas + 0.5) / (len(real_trials) + 1.0)

    z_hit = norm_ppf(hit_rate)
    z_fa = norm_ppf(fa_rate)

    d_prime = z_hit - z_fa
    criterion_c = -0.5 * (z_hit + z_fa)

    acc_pct = (sum(t["is_correct"] for t in trials) / len(trials)) * 100.0
    mean_rt = sum(t["response_time_seconds"] for t in trials) / len(trials)
    mean_conf = sum(t["confidence_score"] for t in trials) / len(trials)

    return {
        "n_trials": len(trials),
        "acc_pct": round(acc_pct, 2),
        "hit_rate": round(hit_rate, 3),
        "fa_rate": round(fa_rate, 3),
        "d_prime": round(d_prime, 3),
        "criterion_c": round(criterion_c, 3),
        "mean_rt_sec": round(mean_rt, 3),
        "mean_conf": round(mean_conf, 2),
    }


def export_all():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    # 1. Eksport wszystkich pojedynczych prób (wyniki_proby.csv)
    cursor.execute("""
        SELECT
            s.session_id, s.group_type, s.age, s.gender, s.it_experience,
            s.social_media, s.self_assessment, s.intervention_duration_seconds,
            r.phase, r.image_id, r.ground_truth, r.user_choice,
            r.is_correct, r.confidence_score, r.response_time_seconds, r.created_at
        FROM responses r
        JOIN sessions s ON r.session_id = s.session_id
        ORDER BY s.created_at, r.id
    """)
    trial_rows = [dict(row) for row in cursor.fetchall()]

    with open("wyniki_proby.csv", "w", newline="", encoding="utf-8-sig") as f:
        if trial_rows:
            writer = csv.DictWriter(f, fieldnames=list(trial_rows[0].keys()), delimiter=";")
            writer.writeheader()
            writer.writerows(trial_rows)

    # 2. Eksport zagregowany na uczestnika ze wskaźnikami SDT (wyniki_uczestnicy_sdt.csv)
    cursor.execute("SELECT * FROM sessions ORDER BY created_at")
    sessions = [dict(row) for row in cursor.fetchall()]

    summary_rows = []
    for s in sessions:
        sid = s["session_id"]
        pre_trials = [t for t in trial_rows if t["session_id"] == sid and t["phase"] == "pretest"]
        post_trials = [t for t in trial_rows if t["session_id"] == sid and t["phase"] == "posttest"]

        pre = compute_sdt_metrics(pre_trials)
        post = compute_sdt_metrics(post_trials)

        d_delta = round(post["d_prime"] - pre["d_prime"], 3) if (pre["d_prime"] != "" and post["d_prime"] != "") else ""

        summary_rows.append({
            "session_id": sid,
            "group_type": s["group_type"],
            "age": s["age"],
            "gender": s["gender"],
            "it_experience": s["it_experience"],
            "social_media": s["social_media"],
            "self_assessment": s["self_assessment"],
            "intervention_duration_sec": s["intervention_duration_seconds"],
            "pre_n": pre["n_trials"],
            "pre_acc_pct": pre["acc_pct"],
            "pre_d_prime": pre["d_prime"],
            "pre_criterion_c": pre["criterion_c"],
            "pre_mean_rt_sec": pre["mean_rt_sec"],
            "pre_mean_conf": pre["mean_conf"],
            "post_n": post["n_trials"],
            "post_acc_pct": post["acc_pct"],
            "post_d_prime": post["d_prime"],
            "post_criterion_c": post["criterion_c"],
            "post_mean_rt_sec": post["mean_rt_sec"],
            "post_mean_conf": post["mean_conf"],
            "d_prime_change": d_delta,
        })

    with open("wyniki_uczestnicy_sdt.csv", "w", newline="", encoding="utf-8-sig") as f:
        if summary_rows:
            writer = csv.DictWriter(f, fieldnames=list(summary_rows[0].keys()), delimiter=";")
            writer.writeheader()
            writer.writerows(summary_rows)

    conn.close()
    print(f"Wyeksportowano {len(trial_rows)} prób do 'wyniki_proby.csv'")
    print(f"Wyeksportowano {len(summary_rows)} uczestników (w tym d' i c) do 'wyniki_uczestnicy_sdt.csv'")


if __name__ == "__main__":
    export_all()