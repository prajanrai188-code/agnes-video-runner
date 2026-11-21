import hashlib
import hmac
import requests

USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/124.0.0.0 Safari/537.36"


def _make_headers(job_id: str, secret: str) -> dict:
    sig = hmac.new(secret.encode(), job_id.encode(), hashlib.sha256).hexdigest()
    return {"X-Agnes-Signature": sig, "User-Agent": USER_AGENT}


def upload_completed_video(callback_url: str, job_id: str, secret: str, video_path: str) -> None:
    headers = _make_headers(job_id, secret)
    with open(video_path, "rb") as vf:
        res = requests.post(
            callback_url,
            headers=headers,
            data={"job_id": job_id, "status": "completed"},
            files={"video": (f"{job_id}.mp4", vf, "video/mp4")},
            timeout=120,
        )
    print("Webhook Response:", res.status_code, res.text[:300])
    res.raise_for_status()


def report_job_failure(callback_url: str, job_id: str, secret: str, error_msg: str) -> None:
    headers = _make_headers(job_id, secret)
    try:
        requests.post(
            callback_url,
            headers=headers,
            data={"job_id": job_id, "status": "failed", "error_message": str(error_msg)[:240]},
            timeout=30,
        )
    except Exception as e:
        print("Failure callback error:", e)
