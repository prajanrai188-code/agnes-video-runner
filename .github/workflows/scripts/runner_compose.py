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

# 1. Download a reliable Devanagari font directly if it's missing (To fix Box-Box issue)
font_path = "work/NotoSansDevanagari.ttf"
if not os.path.exists(font_path):
    font_url = "https://github.com/googlefonts/noto-fonts/raw/main/hinted/ttf/NotoSansDevanagari/NotoSansDevanagari-Bold.ttf"
    try:
        font_res = requests.get(font_url, timeout=10)
        with open(font_path, "wb") as f:
            f.write(font_res.content)
    except:
        pass

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
        overlay_text = sc.get("subtitle", "") or sc.get("narration", "")
        img_path = f"work/scene_{idx}.jpg"
        txt_overlay_path = f"work/text_overlay_{idx}.png"

        # १. AI Image डाउनलोड गर्ने
        img_downloaded = False
        try:
            url = f"https://image.pollinations.ai/prompt/{urllib.parse.quote(prompt)}?width=768&height=1152&nologo=true&model=flux&seed={int(time.time())+idx}"
            r = requests.get(url, headers={"User-Agent": req_headers["User-Agent"]}, timeout=45)
            if r.status_code == 200 and len(r.content) > 1000:
                with open(img_path, "wb") as f:
                    f.write(r.content)
                img_downloaded = True
        except Exception as e:
            pass

        if not img_downloaded:
            fallback_img = Image.new("RGB", (768, 1152), color=(20, 28, 48))
            fallback_img.save(img_path)

        # २. पारदर्शी (Transparent PNG) लेयरमा टेक्स्ट लेख्ने
        txt_img = Image.new('RGBA', (768, 1152), (0, 0, 0, 0))
        draw = ImageDraw.Draw(txt_img)

        try:
            # Use the downloaded Devanagari font
            font = ImageFont.truetype(font_path, 52)
        except Exception:
            font = ImageFont.load_default()

        if overlay_text:
            lines = textwrap.wrap(overlay_text, width=22)
            line_height = 75
            y_text = (1152 - (len(lines) * line_height)) // 2

            draw.rectangle([(20, y_text - 30), (748, y_text + (len(lines) * line_height) + 30)], fill=(0, 0, 0, 150))

            for line in lines:
                bbox = font.getbbox(line)
                line_width = bbox[2] - bbox[0]
                x_text = (768 - line_width) // 2

                for dx in [-2, 0, 2]:
                    for dy in [-2, 0, 2]:
                        draw.text((x_text+dx, y_text+dy), line, font=font, fill="black")
                draw.text((x_text, y_text), line, font=font, fill="#ffffff")
                y_text += line_height
                
        txt_img.save(txt_overlay_path)

        # ३. FFMPEG मार्फत Image लाई जुम गर्ने र त्यसमाथि Transparent Text टाँस्ने
        clip_path = f"work/clip_{idx}.mp4"
        frames = clip_dur * 25
        cmd = [
            "ffmpeg", "-y", "-loop", "1", "-i", img_path,
            "-i", txt_overlay_path,
            "-filter_complex", 
            f"[0:v]scale=1536:2304,zoompan=z='min(zoom+0.0015,1.3)':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d={frames}:s=768x1152:fps=25[bg];[bg][1:v]overlay=0:0[vout]",
            "-map", "[vout]", "-t", str(clip_dur), "-c:v", "libx264", "-preset", "fast", clip_path
        ]
        subprocess.run(cmd, check=True)
        scene_clips.append(clip_path)

    # ४. सबै क्लिप जोड्ने
    with open("work/concat.txt", "w") as f:
        for cp in scene_clips:
            f.write(f"file '{os.path.abspath(cp)}'\n")

    merged_video = "work/merged.mp4"
    subprocess.run(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", "work/concat.txt", "-c", "copy", merged_video], check=True)

    # ५. Background Music (BGM) छान्ने लजिकलाई लचिलो (Flexible) बनाइएको छ
    final_output = "work/final_output.mp4"
    bg_music_file = "work/bgm.mp3"
    
    # Check for keywords more broadly
    if any(word in topic for word in ["sad", "cry", "heart", "hurt", "दुख", "रुवाउने", "pain", "lonely"]):
        music_url = "https://cdn.pixabay.com/download/audio/2022/05/16/audio_03d9178bf7.mp3"
    elif any(word in topic for word in ["love", "romantic", "माया", "प्रेम", "couple", "kiss", "romance"]):
        music_url = "https://cdn.pixabay.com/download/audio/2022/01/18/audio_d0a13f69d2.mp3"
    elif any(word in topic for word in ["motivat", "success", "प्रेरणा", "सफलता", "inspire", "goal", "dream"]):
        music_url = "https://cdn.pixabay.com/download/audio/2021/08/09/audio_82c5e533c6.mp3"
    else:
        # Default fallback music (Ambient Cinematic) instead of silent
        music_url = "https://cdn.pixabay.com/download/audio/2022/03/15/audio_c8b824eb87.mp3"
        
    bgm_downloaded = False
    try:
        r_music = requests.get(music_url, headers=req_headers, timeout=20)
        if r_music.status_code == 200:
            with open(bg_music_file, "wb") as f:
                f.write(r_music.content)
            bgm_downloaded = True
    except:
        pass

    full_narration = " ".join([s.get("narration", "") for s in scenes]).strip()

    if voiceover == "on" and full_narration:
        voice_map = {"english": "en-US-ChristopherNeural", "hindi": "hi-IN-MadhurNeural", "nepali": "ne-NP-SagarNeural"}
        v_name = voice_map.get(language, "en-US-ChristopherNeural")
        audio_file = "work/vo.mp3"
        subprocess.run(["edge-tts", "--voice", v_name, "--text", full_narration, "--write-media", audio_file], check=True)
        
        if bgm_downloaded:
            subprocess.run([
                "ffmpeg", "-y", "-i", merged_video, "-i", audio_file, "-i", bg_music_file,
                "-filter_complex", "[1:a]volume=1.0[v];[2:a]volume=0.15[b];[v][b]amix=inputs=2:duration=first:dropout_transition=2[a]",
                "-map", "0:v", "-map", "[a]", "-c:v", "copy", "-c:a", "aac", "-shortest", final_output
            ], check=True)
        else:
            subprocess.run(["ffmpeg", "-y", "-i", merged_video, "-i", audio_file, "-c:v", "copy", "-c:a", "aac", "-shortest", final_output], check=True)
    else:
        if bgm_downloaded:
            subprocess.run(["ffmpeg", "-y", "-i", merged_video, "-i", bg_music_file, "-c:v", "copy", "-c:a", "aac", "-shortest", final_output], check=True)
        else:
            subprocess.run(["ffmpeg", "-y", "-i", merged_video, "-f", "lavfi", "-i", "anullsrc=r=44100:cl=stereo", "-c:v", "copy", "-c:a", "aac", "-shortest", final_output], check=True)

    # ६. Webhook अपलोड
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
