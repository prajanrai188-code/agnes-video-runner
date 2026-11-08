import os, json, time, hmac, hashlib, subprocess, urllib.parse, requests
from PIL import Image, ImageDraw, ImageFont

payload = json.loads(os.environ["JOB_PAYLOAD"])
secret = os.environ.get("WEBHOOK_SECRET", "agnes_hmac_secret_2026_prajan_hub")

job_id = payload["job_id"]
scenes = payload.get("scenes", [])
duration = int(payload.get("duration", 20))
language = payload.get("language", "nepali")
voiceover = payload.get("voiceover", "off")
callback_url = payload["callback_url"]

os.makedirs("work", exist_ok=True)
sig = hmac.new(secret.encode(), job_id.encode(), hashlib.sha256).hexdigest()

try:
    scene_clips = []
    num_scenes = max(len(scenes), 2)
    clip_dur = max(int(duration / num_scenes), 5)

    for idx, sc in enumerate(scenes):
        prompt = sc.get("image_prompt", payload["topic"])
        subtitle = sc.get("subtitle", "")
        narration = sc.get("narration", subtitle)

        # १. 768x1152 (9:16 Portrait Preset) AI Scene डाउनलोड गर्ने
        img_path = f"work/scene_{idx}.jpg"
        url = f"https://image.pollinations.ai/prompt/{urllib.parse.quote(prompt)}?width=768&height=1152&nologo=true&seed={int(time.time())+idx}"
        r = requests.get(url, timeout=90)
        with open(img_path, "wb") as f:
            f.write(r.content)

        # २. Devanagari / English Animated Caption बक्स कोर्ने
        img = Image.open(img_path).convert("RGB").resize((768, 1152))
        draw = ImageDraw.Draw(img)
        try:
            font = ImageFont.truetype("/usr/share/fonts/truetype/noto/NotoSansDevanagari-Bold.ttf", 36)
        except Exception:
            font = ImageFont.load_default()

        if subtitle:
            draw.rectangle([(40, 880), (728, 1020)], fill=(0, 0, 0, 180))
            draw.text((80, 920), subtitle[:42], font=font, fill="white")
        img.save(img_path)

        # ३. Keyframe Motion (Zoompan) सहित MP4 क्लिप बनाउने
        clip_path = f"work/clip_{idx}.mp4"
        frames = clip_dur * 25
        cmd = [
            "ffmpeg", "-y", "-loop", "1", "-i", img_path,
            "-vf", f"scale=1536:2304,zoompan=z='min(zoom+0.0012,1.35)':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d={frames}:s=768x1152:fps=25,format=yuv420p",
            "-t", str(clip_dur), "-c:v", "libx264", "-preset", "fast", clip_path
        ]
        subprocess.run(cmd, check=True)
        scene_clips.append(clip_path)

    # ४. Multi-scene Composition (सबै क्लिप जोड्ने)
    with open("work/concat.txt", "w") as f:
        for cp in scene_clips:
            f.write(f"file '{os.path.abspath(cp)}'\n")

    merged_video = "work/merged.mp4"
    subprocess.run(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", "work/concat.txt", "-c", "copy", merged_video], check=True)

    # ५. Voiceover (Hindi / English / Nepali TTS) वा Background Sine Ambient Audio जोड्ने
    final_output = "work/final_output.mp4"
    full_narration = " ".join([s.get("narration", "") for s in scenes]).strip()

    if voiceover == "on" and full_narration:
        voice_map = {"english": "en-US-ChristopherNeural", "hindi": "hi-IN-MadhurNeural", "nepali": "ne-NP-SagarNeural"}
        v_name = voice_map.get(language, "en-US-ChristopherNeural")
        audio_file = "work/vo.mp3"
        subprocess.run(["edge-tts", "--voice", v_name, "--text", full_narration, "--write-media", audio_file], check=True)
        subprocess.run([
            "ffmpeg", "-y", "-i", merged_video, "-i", audio_file,
            "-c:v", "copy", "-c:a", "aac", "-shortest", final_output
        ], check=True)
    else:
        subprocess.run([
            "ffmpeg", "-y", "-i", merged_video,
            "-f", "lavfi", "-i", "anoisesrc=d=30:c=pink:r=44100:a=0.02",
            "-c:v", "copy", "-c:a", "aac", "-shortest", final_output
        ], check=True)

    # ६. तपाईंको होस्टिङमा सुरक्षित Callback पठाउने
    with open(final_output, "rb") as vf:
        requests.post(
            callback_url,
            headers={"X-Agnes-Signature": sig},
            data={"job_id": job_id, "status": "completed"},
            files={"video": (f"{job_id}.mp4", vf, "video/mp4")},
            timeout=120
        )

except Exception as e:
    requests.post(
        callback_url,
        headers={"X-Agnes-Signature": sig},
        data={"job_id": job_id, "status": "failed", "error_message": str(e)},
        timeout=30
    )
    raise e
