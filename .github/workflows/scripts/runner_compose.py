import os, json, time, hmac, hashlib, subprocess, urllib.parse, requests
from PIL import Image, ImageDraw, ImageFont

payload = json.loads(os.environ["JOB_PAYLOAD"])
secret = os.environ.get("WEBHOOK_SECRET") or "agnes_hmac_secret_2026_prajan_hub"

job_id = payload["job_id"]
scenes = payload.get("scenes", [])
duration = int(payload.get("duration", 20))
language = payload.get("language", "nepali")
voiceover = payload.get("voiceover", "off")
visual_style = payload.get("visual_style", "cinematic").lower()
music_pref = payload.get("music", "auto")
callback_url = payload["callback_url"]

os.makedirs("work", exist_ok=True)
sig = hmac.new(secret.encode(), job_id.encode(), hashlib.sha256).hexdigest()

req_headers = {
    "X-Agnes-Signature": sig,
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/124.0.0.0 Safari/537.36"
}

# Style Enhancer (For Realistic, Cinematic, or Anime looks)
style_prompts = {
    "cinematic": "cinematic lighting, movie scene, 8k resolution, highly detailed, dramatic shadows, photorealistic",
    "anime": "studio ghibli style, makoto shinkai, anime art, vibrant colors, beautiful anime scenery, 2d masterpiece",
    "realistic": "ultra realistic, 8k uhd, dslr photography, sharp focus, natural lighting"
}
style_suffix = style_prompts.get(visual_style, style_prompts["cinematic"])

try:
    scene_clips = []
    num_scenes = max(len(scenes), 2)
    clip_dur = max(int(duration / num_scenes), 5)

    for idx, sc in enumerate(scenes):
        raw_prompt = sc.get("image_prompt", payload.get("topic", "beautiful nature"))
        # प्रम्प्टमा स्टाइल जोडेर उत्कृष्ट नतिजा निकाल्ने
        enhanced_prompt = f"{raw_prompt}, {style_suffix}"
        subtitle = sc.get("subtitle", "")
        img_path = f"work/scene_{idx}.jpg"

        # १. AI Scene Image डाउनलोड (Pollinations Flux Model)
        img_downloaded = False
        try:
            url = f"https://image.pollinations.ai/prompt/{urllib.parse.quote(enhanced_prompt)}?width=768&height=1152&nologo=true&model=flux&seed={int(time.time())+idx}"
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

        # २. Subtitle राख्ने (राम्रो डिजाइनमा)
        img = Image.open(img_path).convert("RGB").resize((768, 1152))
        draw = ImageDraw.Draw(img)
        try:
            font = ImageFont.truetype("/usr/share/fonts/truetype/noto/NotoSansDevanagari-Bold.ttf", 36)
        except Exception:
            font = ImageFont.load_default()

        if subtitle:
            # अलिकति पारदर्शी कालो ब्याकग्राउन्ड
            draw.rectangle([(30, 880), (738, 1030)], fill=(0, 0, 0, 180))
            draw.text((60, 920), subtitle[:45], font=font, fill="white")
        img.save(img_path)

        # ३. Cinematic Zoompan Effect
        clip_path = f"work/clip_{idx}.mp4"
        frames = clip_dur * 25
        # बिस्तारै जुम हुने इफेक्ट
        cmd = [
            "ffmpeg", "-y", "-loop", "1", "-i", img_path,
            "-vf", f"scale=1536:2304,zoompan=z='min(zoom+0.0015,1.4)':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d={frames}:s=768x1152:fps=25,format=yuv420p",
            "-t", str(clip_dur), "-c:v", "libx264", "-preset", "fast", clip_path
        ]
        subprocess.run(cmd, check=True)
        scene_clips.append(clip_path)

    # ४. क्लिपहरू जोड्ने
    with open("work/concat.txt", "w") as f:
        for cp in scene_clips:
            f.write(f"file '{os.path.abspath(cp)}'\n")

    merged_video = "work/merged.mp4"
    subprocess.run(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", "work/concat.txt", "-c", "copy", merged_video], check=True)

    # ५. Voiceover र Mood-based Background Music
    final_output = "work/final_output.mp4"
    full_narration = " ".join([s.get("narration", "") for s in scenes]).strip()
    
    bg_music_file = "work/bgm.mp3"
    
    # थिम अनुसारको रोयल्टी-फ्री म्युजिक तान्ने (Fallback URL)
    music_url = "https://cdn.pixabay.com/download/audio/2022/01/18/audio_d0a13f69d2.mp3" # Cinematic Ambient
    if "sad" in payload.get("topic", "").lower():
        music_url = "https://cdn.pixabay.com/download/audio/2022/05/16/audio_03d9178bf7.mp3" # Sad Piano
    elif "happy" in payload.get("topic", "").lower():
        music_url = "https://cdn.pixabay.com/download/audio/2021/08/04/audio_12b0c7443c.mp3" # Happy LoFi
        
    if music_pref != "none":
        try:
            r_music = requests.get(music_url, headers=req_headers, timeout=20)
            if r_music.status_code == 200:
                with open(bg_music_file, "wb") as f:
                    f.write(r_music.content)
        except: pass

    if voiceover == "on" and full_narration:
        voice_map = {"english": "en-US-ChristopherNeural", "hindi": "hi-IN-MadhurNeural", "nepali": "ne-NP-SagarNeural"}
        v_name = voice_map.get(language, "en-US-ChristopherNeural")
        audio_file = "work/vo.mp3"
        subprocess.run(["edge-tts", "--voice", v_name, "--text", full_narration, "--write-media", audio_file], check=True)
        
        if os.path.exists(bg_music_file):
            # भोइसओभर र BGM दुवै मिक्स गर्ने (BGM को भोल्युम घटाएर)
            subprocess.run(["ffmpeg", "-y", "-i", merged_video, "-i", audio_file, "-i", bg_music_file, 
                            "-filter_complex", "[1:a]volume=1.0[v];[2:a]volume=0.2[b];[v][b]amix=inputs=2:duration=first:dropout_transition=2[a]", 
                            "-map", "0:v", "-map", "[a]", "-c:v", "copy", "-c:a", "aac", "-shortest", final_output], check=True)
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
        res.raise_for_status()

except Exception as e:
    requests.post(
        callback_url,
        headers=req_headers,
        data={"job_id": job_id, "status": "failed", "error_message": str(e)},
        timeout=30
    )
    raise e
