import json
import os
import sys

# scripts फोल्डरबाट आयात गर्न मिल्ने बनाउने
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from stock_fetcher import fetch_stock_video
from voice_generator import generate_voice_and_subtitles
from video_renderer import normalize_clip, pick_local_bgm, render_final_video
from hosting_uploader import upload_completed_video, report_job_failure


def write_fallback_srt(scenes: list[dict], clip_dur: float, srt_path: str) -> None:
    """यदि voiceover 'off' छ भने scenes को subtitle बाटै timed .srt बनाउँछ"""
    def fmt(sec: float) -> str:
        h = int(sec // 3600)
        m = int((sec % 3600) // 60)
        s = int(sec % 60)
        ms = int((sec - int(sec)) * 1000)
        return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"

    blocks = []
    cur = 0.0
    for i, sc in enumerate(scenes, start=1):
        txt = (sc.get("subtitle") or sc.get("narration") or "").strip()
        if txt:
            blocks.append(f"{i}\n{fmt(cur)} --> {fmt(cur + clip_dur - 0.1)}\n{txt}")
        cur += clip_dur

    if blocks:
        with open(srt_path, "w", encoding="utf-8") as f:
            f.write("\n\n".join(blocks) + "\n")


def main():
    payload = json.loads(os.environ["JOB_PAYLOAD"])
    secret = os.environ.get("WEBHOOK_SECRET") or "agnes_hmac_secret_2026_prajan_hub"

    job_id = payload["job_id"]
    topic = payload.get("keyword") or payload.get("topic") or "inspirational story"
    language = payload.get("language", "ne")
    voice_gender = payload.get("voice_gender", "male")
    target_duration = int(payload.get("duration", 20))
    callback_url = payload["callback_url"]

    # पुरानो (voiceover='on'/'off', music='auto'/'none') र नयाँ दुवै payload सपोर्ट
    vo_flag = payload.get("voiceover", "on")
    use_voice = vo_flag is True or str(vo_flag).lower() == "on"

    sub_flag = payload.get("subtitles", True)
    use_subtitles = sub_flag is True or str(sub_flag).lower() in ("true", "on", "1")

    bgm_flag = payload.get("background_music", payload.get("music", "auto"))
    use_bgm = bgm_flag is True or str(bgm_flag).lower() not in ("false", "none", "off", "0")

    scenes = payload.get("scenes") or [
        {"search_keyword": "cinematic nature landscape", "narration": topic, "subtitle": topic[:45]},
        {"search_keyword": "inspiring sunrise mountain", "narration": "", "subtitle": topic[:45]},
    ]

    os.makedirs("work", exist_ok=True)

    try:
        # १. Voiceover र Auto-SRT बनाउने
        voice_path = "work/voice.mp3"
        srt_path = "work/subtitles.srt"
        full_narration = " ".join(
            [(s.get("narration") or s.get("subtitle") or "").strip() for s in scenes]
        ).strip()

        actual_voice_path = None
        final_duration = float(target_duration)

        if use_voice and full_narration:
            ok, audio_dur = generate_voice_and_subtitles(
                full_narration, language, voice_gender, voice_path, srt_path
            )
            if ok:
                actual_voice_path = voice_path
                # भिडियोको अवधि अडियोभन्दा छोटो नहोस् (अधिकतम ३० सेकेन्ड)
                if audio_dur > 3:
                    final_duration = min(max(audio_dur + 0.5, 10.0), 35.0)

        # २. हरेक scene का लागि Stock Footage डाउनलोड र 1080x1920 Normalize गर्ने
        num_scenes = max(len(scenes), 2)
        clip_dur = final_duration / num_scenes
        normalized_clips = []

        for idx, sc in enumerate(scenes):
            kw = sc.get("search_keyword") or sc.get("image_prompt") or "cinematic nature"
            raw_vid = f"work/raw_{idx}.mp4"
            norm_vid = f"work/clip_{idx}.mp4"
            source = fetch_stock_video(kw, raw_vid, duration=max(int(clip_dur) + 1, 5))
            print(f"Scene {idx + 1} ('{kw}') fetched from: {source}")
            normalize_clip(raw_vid, norm_vid, duration=clip_dur, width=1080, height=1920)
            normalized_clips.append(norm_vid)

        # यदि voiceover बन्द थियो भने scenes बाट SRT बनाउने
        if use_subtitles and not os.path.exists(srt_path):
            write_fallback_srt(scenes, clip_dur, srt_path)

        # ३. Local Background Music छान्ने
        bgm_path = pick_local_bgm(topic) if use_bgm else None

        # ४. अन्तिम 1080x1920 MP4 रेन्डर गर्ने
        final_output = "work/final_output.mp4"
        render_final_video(
            clip_paths=normalized_clips,
            output_path=final_output,
            voice_path=actual_voice_path,
            srt_path=srt_path if use_subtitles else None,
            bgm_path=bgm_path,
            total_duration=final_duration,
        )

        # ५. Hosting मा सुरक्षित अपलोड गर्ने
        upload_completed_video(callback_url, job_id, secret, final_output)
        print(f"Job {job_id} completed successfully!")

    except Exception as e:
        print("Runner Error:", str(e))
        report_job_failure(callback_url, job_id, secret, str(e))
        raise


if __name__ == "__main__":
    main()
