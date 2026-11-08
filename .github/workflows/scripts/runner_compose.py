import os, json, time, hmac, hashlib, subprocess, urllib.parse, requests
import textwrap
from PIL import Image, ImageDraw, ImageFont

payload = json.loads(os.environ["JOB_PAYLOAD"])
secret = os.environ.get("WEBHOOK_SECRET") or "agnes_hmac_secret_2026_prajan_hub"

job_id = payload["job_id"]
scenes = payload.get("scenes", [])
duration = int(payload.get("duration", 20))
language = payload.get("language", "nepali")
voiceover = payload.get("voiceover", "off")
topic = payload.get("topic", "").lower()
callback_url = payload["callback_url"]

os.makedirs("work", exist_ok=True)
sig = hmac.new(secret.encode(), job_id.encode(), hashlib.sha256).hexdigest()

req_headers = {
    "X-Agnes-Signature": sig,
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/124.0.0.0 Safari/537.36"
}

try:
    if not scenes:
        scenes = [
            {"image_prompt": f"Vertical 9:16 cinematic scene of {topic}", "narration": payload.get("topic",""), "subtitle": payload.get("topic","")},
            {"image_prompt": f"Vertical 9:16 dramatic close up of {topic}", "narration": "", "subtitle": payload.get("topic","")}
        ]

    scene_clips = []
    num_scenes = max(len(scenes), 2)
    clip_dur = max(int(duration / num_scenes), 5)

    for idx, sc in enumerate(scenes):
        prompt = sc.get("image_prompt", topic)
        # भिडियोको लागि टेक्स्ट तान्ने (narration वा subtitle जुन उपलब्ध छ)
        overlay_text = sc.get("subtitle", "") or sc.get("narration", "")
        img_path = f"work/scene_{idx}.jpg"

        # १. AI Scene Image डाउनलोड
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

        # २. Center Overlay Text (TikTok / Reels Style)
        img = Image.open(img_path).convert("RGB").resize((768, 1152))
        
        # टेक्स्टलाई प्रष्ट देखाउन भिडियोमा हल्का कालो (Dark Tint) तह राख्ने
        tint = Image.new('RGBA', img.size, (0, 0, 0, 110))
        img = Image.alpha_composite(img.convert('RGBA'), tint).convert('RGB')
        draw = ImageDraw.Draw(img)

        try:
            # अङ्ग्रेजी, नेपाली, र हिन्दी तीनवटै सपोर्ट गर्ने फन्ट
            font = ImageFont.truetype("/usr/share/fonts/truetype/noto/NotoSansDevanagari-Bold.ttf", 55)
        except Exception:
            font = ImageFont.load_default()

        if overlay_text:
            lines = textwrap.wrap(overlay_text, width=22)
            line_height = 75
            # भिडियोको ठ्याक्कै बीचमा (Center) टेक्स्ट राख्ने
            y_text = (1152 - (len(lines) * line_height)) // 2

            for line in lines:
                bbox = font.getbbox(line)
                line_width = bbox[2] - bbox[0]
                x_text = (768 - line_width) // 2

                # टेक्स्टको पछाडि कालो छाया (Drop Shadow) ताकि जुनसुकै ब्याकग्राउन्डमा प्रष्ट देखियोस्
                for dx in [-3, 0, 3]:
                    for dy in [-3, 0, 3]:
                        draw.text((x_text+dx, y_text+dy), line, font=font, fill="black")
                
                # मुख्य सेतो टेक्स्ट
                draw.text((x_text, y_text), line, font=font, fill="#ffffff")
                y_text += line_height
                
        img.save(img_path)

        # ३. Cinematic Motion (Real Video Feel)
        clip_path = f"work/clip_{idx}.mp4"
        frames = clip_dur * 25
        # एड्भान्स जुम र प्यान इफेक्ट
        cmd = [
            "ffmpeg", "-y", "-loop", "1", "-i", img_path,
            "-vf", f"scale=1536:2304,zoompan=z='min(zoom+0.0015,1.3)':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)+10':d={frames}:s=768x1152:fps=25,format=yuv420p",
            "-t", str(clip_dur), "-c:v", "libx264", "-preset", "fast", clip_path
        ]
        subprocess.run(cmd, check=True)
        scene_clips.append(clip_path)

    # ४. सबै क्लिप जोड्ने
    with open("work/concat.txt", "w") as f:
        for cp in scene_clips:
            f.write(f"file '{os.path.abspath(cp)}'\n")

    merged_video = "work/merged.mp4"
    subprocess.run(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", "work/concat.txt", "-c", "copy", merged_video], check=True)

    # ५. Background Music (BGM) & Voiceover
    final_output = "work/final_output.mp4"
    bg_music_file = "work/bgm.mp3"
    
    # Topic अनुसार Background Music छान्ने
    if any(word in topic for word in ["sad", "cry", "heart", "hurt", "दुख", "रुवाउने"]):
        music_url = "https://cdn.pixabay.com/download/audio/2022/05/16/audio_03d9178bf7.mp3" # Sad Emotional
    elif any(word in topic for word in ["love", "romantic", "माया", "प्रेम"]):
        music_url = "https://cdn.pixabay.com/download/audio/2022/01/18/audio_d0a13f69d2.mp3" # Romantic
    elif any(word in topic for word in ["motivat", "success", "प्रेरणा", "सफलता"]):
        music_url = "https://cdn.pixabay.com/download/audio/2021/08/09/audio_82c5e533c6.mp3" # Motivational
    else:
        music_url = "https://cdn.pixabay.com/download/audio/2022/03/15/audio_c8b824eb87.mp3" # Ambient Cinematic
        
    try:
        r_music = requests.get(music_url, headers=req_headers, timeout=20)
        if r_music.status_code == 200:
            with open(bg_music_file, "wb") as f:
                f.write(r_music.content)
    except:
        pass

    full_narration = " ".join([s.get("narration", "") for s in scenes]).strip()

    if voiceover == "on" and full_narration:
        voice_map = {"english": "en-US-ChristopherNeural", "hindi": "hi-IN-MadhurNeural", "nepali": "ne-NP-SagarNeural"}
        v_name = voice_map.get(language, "en-US-ChristopherNeural")
        audio_file = "work/vo.mp3"
        subprocess.run(["edge-tts", "--voice", v_name, "--text", full_narration, "--write-media", audio_file], check=True)
        
        if os.path.exists(bg_music_file):
            # Voiceover र BGM दुवै मिक्स गर्ने (BGM को भोल्युम घटाएर)
            subprocess.run([
                "ffmpeg", "-y", "-i", merged_video, "-i", audio_file, "-i", bg_music_file,
                "-filter_complex", "[1:a]volume=1.0[v];[2:a]volume=0.15[b];[v][b]amix=inputs=2:duration=first:dropout_transition=2[a]",
                "-map", "0:v", "-map", "[a]", "-c:v", "copy", "-c:a", "aac", "-shortest", final_output
            ], check=True)
        else:
            subprocess.run(["ffmpeg", "-y", "-i", merged_video, "-i", audio_file, "-c:v", "copy", "-c:a", "aac", "-shortest", final_output], check=True)
    else:
        if os.path.exists(bg_music_file):
            subprocess.run(["ffmpeg", "-y", "-i", merged_video, "-i", bg_music_file, "-c:v", "copy", "-c:a", "aac", "-shortest", final_output], check=True)
        else:
            subprocess.run(["ffmpeg", "-y", "-i", merged_video, "-f", "lavfi", "-i", "anoisesrc=d=30:c=pink:r=44100:a=0.02", "-c:v", "copy", "-c:a", "aac", "-shortest", final_output], check=True)

    # ६. Webhook मार्फत सुरक्षित अपलोड
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
