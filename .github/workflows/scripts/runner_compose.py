import os, json, time, hmac, hashlib, subprocess, urllib.parse, requests
from PIL import Image, ImageDraw, ImageFont

payload = json.loads(os.environ["JOB_PAYLOAD"])
secret = os.environ.get("WEBHOOK_SECRET") or "agnes_hmac_secret_2026_prajan_hub"

job_id = payload["job_id"]
scenes = payload.get("scenes", [])
duration = int(payload.get("duration", 20))
language = payload.get("language", "nepali")
voiceover = payload.get("voiceover", "off")
callback_url = payload["callback_url"]

os.makedirs("work", exist_ok=True)
sig = hmac.new(secret.encode(), job_id.encode(), hashlib.sha256).hexdigest()

# cPanel Firewall (ModSecurity) ले ब्लक नगरोस् भनेर Browser Headers राख्ने
req_headers = {
    "X-Agnes-Signature": sig,
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/124.0.0.0 Safari/537.36"
}

try:
    if not scenes:
        scenes = [
            {"image_prompt": f"Vertical 9:16 cinematic scene of {payload.get('topic','story')}", "narration": payload.get("topic",""), "subtitle": payload.get("topic","")[:40]},
            {"image_prompt": f"Vertical 9:16 dramatic close up of {payload.get('topic','story')}", "narration": "", "subtitle": payload.get("topic","")[:40]}
        ]

    scene_clips = []
    num_scenes = max(len(scenes), 2)
    clip_dur = max(int(duration / num_scenes), 5)

    for idx, sc in enumerate(scenes):
        prompt = sc.get("image_prompt", payload.get("topic", "cinematic nature"))
        subtitle = sc.get("subtitle", "")
        img_path = f"work/scene_{idx}.jpg"

        # १. AI Scene Image डाउनलोड (यदि ढिलो भए अटोमेटिक Fallback इमेज बनाउने)
        img_downloaded = False
        try:
            url = f"https://image.pollinations.ai/prompt/{urllib.parse.quote(prompt)}?width=768&height=1152&nologo=true&seed={int(time.time())+idx}"
            r = requests.get(url, headers={"User-Agent": req_headers["User-Agent"]}, timeout=45)
            if r.status_code == 200 and len(r.content) > 1000:
                with open(img_path, "wb") as f:
                    f.write(r.content)
                img_downloaded = True
        except Exception as e:
            print(f"Pollinations warning: {e}")

        if not img_downloaded:
            fallback_img = Image.new("RGB", (768, 1152), color=(20, 28, 48))
            fallback_img.save(img_path)

        # २. Subtitle राख्ने
        img = Image.open(img_path).convert("RGB").resize((768, 1152))
        draw = ImageDraw.Draw(img)
        try:
            font = ImageFont.truetype("/usr/share/fonts/truetype/noto/NotoSansDevanagari-Bold.ttf", 34)
        except Exception:
            font = ImageFont.load_default()

        if subtitle:
            draw.rectangle([(40, 880), (728, 1020)], fill=(0, 0, 0))
            draw.text((70, 925), subtitle[:42], font=font, fill="white")
        img.save(img_path)

        # ३. Keyframe Motion (Zoompan) क्लिप बनाउने
        clip_path = f"work/clip_{idx}.mp4"
        frames = clip_dur * 25
        cmd = [
            "ffmpeg", "-y", "-loop", "1", "-i", img_path,
            "-vf", f"scale=1536:2304,zoompan=z='min(zoom+0.0012,1.35)':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d={frames}:s=768x1152:fps=25,format=yuv420p",
            "-t", str(clip_dur), "-c:v", "libx264", "-preset", "ultrafast", clip_path
        ]
        subprocess.run(cmd, check=True)
        scene_clips.append(clip_path)

    # ४. सबै क्लिप जोड्ने
    with open("work/concat.txt", "w") as f:
        for cp in scene_clips:
            f.write(f"file '{os.path.abspath(cp)}'\n")

    merged_video = "work/merged.mp4"
    subprocess.run(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", "work/concat.txt", "-c", "copy", merged_video], check=True)

    # ५. Voiceover र अडियो जोड्ने
    final_output = "work/final_output.mp4"
    full_narration = " ".join([s.get("narration", "") for s in scenes]).strip()

    if voiceover == "on" and full_narration:
        voice_map = {"english": "en-US-ChristopherNeural", "hindi": "hi-IN-MadhurNeural", "nepali": "ne-NP-SagarNeural"}
        v_name = voice_map.get(language, "en-US-ChristopherNeural")
        audio_file = "work/vo.mp3"
        subprocess.run(["edge-tts", "--voice", v_name, "--text", full_narration, "--write-media", audio_file], check=True)
        subprocess.run(["ffmpeg", "-y", "-i", merged_video, "-i", audio_file, "-c:v", "copy", "-c:a", "aac", "-shortest", final_output], check=True)
    else:
        subprocess.run(["ffmpeg", "-y", "-i", merged_video, "-f", "lavfi", "-i", "anoisesrc=d=30:c=pink:r=44100:a=0.02", "-c:v", "copy", "-c:a", "aac", "-shortest", final_output], check=True)

    # ६. होस्टिङको Webhook मा अपलोड गर्ने
    with open(final_output, "rb") as vf:
        res = requests.post(
            callback_url,
            headers=req_headers,
            data={"job_id": job_id, "status": "completed"},
            files={"video": (f"{job_id}.mp4", vf, "video/mp4")},
            timeout=120
        )
        print("Webhook Upload Response:", res.status_code, res.text)
        res.raise_for_status()

except Exception as e:
    print("Runner Error:", str(e))
    requests.post(
        callback_url,
        headers=req_headers,
        data={"job_id": job_id, "status": "failed", "error_message": str(e)},
        timeout=30
    )
    raise e
