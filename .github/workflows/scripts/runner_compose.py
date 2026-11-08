import os, json, time, hmac, hashlib, subprocess, urllib.parse, requests
import textwrap
import random
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

# Pexels & Pixabay API Keys
PEXELS_API_KEY = os.environ.get("PEXELS_API_KEY", "b40j3qN3N6N47bE0R9oX3uL3g4D3O9Y1T6A5pC5H8j2T1H9d1H2A6x4C") 
PIXABAY_API_KEY = os.environ.get("PIXABAY_API_KEY", "41503923-b1d7d0a2f4c9c2e5b3c8d1e2f")

os.makedirs("work", exist_ok=True)
sig = hmac.new(secret.encode(), job_id.encode(), hashlib.sha256).hexdigest()

req_headers = {
    "X-Agnes-Signature": sig,
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/124.0.0.0 Safari/537.36"
}

# 1. Download Devanagari font (For Text Overlay)
font_path = "work/NotoSansDevanagari.ttf"
if not os.path.exists(font_path):
    font_url = "https://github.com/googlefonts/noto-fonts/raw/main/hinted/ttf/NotoSansDevanagari/NotoSansDevanagari-Bold.ttf"
    try:
        font_res = requests.get(font_url, timeout=10)
        with open(font_path, "wb") as f:
            f.write(font_res.content)
    except:
        pass

def search_and_download_pexels_video(query, output_path, min_duration=5):
    """Pexels API बाट 9:16 (Portrait) भिडियो खोज्ने र डाउनलोड गर्ने"""
    headers = {"Authorization": PEXELS_API_KEY}
    url = f"https://api.pexels.com/videos/search?query={urllib.parse.quote(query)}&orientation=portrait&per_page=15"
    try:
        res = requests.get(url, headers=headers, timeout=20).json()
        if 'videos' in res and len(res['videos']) > 0:
            videos = [v for v in res['videos'] if v['duration'] >= min_duration]
            if not videos: videos = res['videos']
            selected_video = random.choice(videos)
            video_files = selected_video['video_files']
            hd_files = [f for f in video_files if f['quality'] == 'hd' and f['width'] <= 1080]
            if not hd_files: hd_files = video_files
            best_link = sorted(hd_files, key=lambda x: x['width'], reverse=True)[0]['link']
            video_data = requests.get(best_link, timeout=60)
            if video_data.status_code == 200:
                with open(output_path, "wb") as f:
                    f.write(video_data.content)
                return True
    except Exception as e:
        print(f"Pexels Error: {e}")
    return False

def search_and_download_pixabay_video(query, output_path):
    """Pexels ले काम नगरेमा Pixabay बाट भिडियो तान्ने (Fallback)"""
    url = f"https://pixabay.com/api/videos/?key={PIXABAY_API_KEY}&q={urllib.parse.quote(query)}&video_type=film&per_page=10"
    try:
        res = requests.get(url, timeout=20).json()
        if int(res.get('totalHits', 0)) > 0:
            selected_video = random.choice(res['hits'])
            best_link = selected_video['videos']['large']['url'] if selected_video['videos']['large']['size'] > 0 else selected_video['videos']['medium']['url']
            video_data = requests.get(best_link, timeout=60)
            if video_data.status_code == 200:
                with open(output_path, "wb") as f:
                    f.write(video_data.content)
                return True
    except Exception as e:
        print(f"Pixabay Error: {e}")
    return False

try:
    if not scenes:
        scenes = [
            {"search_keyword": "nature landscape", "narration": payload.get("topic",""), "subtitle": payload.get("topic","")},
            {"search_keyword": "cinematic beautiful", "narration": "", "subtitle": payload.get("topic","")}
        ]

    scene_clips = []
    num_scenes = max(len(scenes), 2)
    clip_dur = max(int(duration / num_scenes), 5)

    for idx, sc in enumerate(scenes):
        search_query = sc.get("search_keyword") or sc.get("image_prompt", "cinematic nature")
        overlay_text = sc.get("subtitle", "") or sc.get("narration", "")
        
        raw_vid_path = f"work/raw_scene_{idx}.mp4"
        txt_overlay_path = f"work/text_overlay_{idx}.png"
        clip_path = f"work/clip_{idx}.mp4"
        
        # १. Pexels वा Pixabay बाट भिडियो तान्ने प्रयास गर्ने
        vid_downloaded = search_and_download_pexels_video(search_query, raw_vid_path, clip_dur)
        if not vid_downloaded:
            vid_downloaded = search_and_download_pixabay_video(search_query, raw_vid_path)

        # २. पारदर्शी (Transparent PNG) लेयरमा टेक्स्ट लेख्ने
        txt_img = Image.new('RGBA', (768, 1152), (0, 0, 0, 0))
        draw = ImageDraw.Draw(txt_img)
        try: font = ImageFont.truetype(font_path, 52)
        except Exception: font = ImageFont.load_default()

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

        frames = clip_dur * 25

        # ३. भिडियो वा इमेजलाई प्रोसेस गर्ने
        if vid_downloaded:
            # रियल भिडियो डाउनलोड भयो भने त्यसलाई क्रप गरेर टेक्स्ट ओभरले गर्ने
            cmd = [
                "ffmpeg", "-y", "-i", raw_vid_path, "-i", txt_overlay_path,
                "-filter_complex", 
                f"[0:v]scale=768:1152:force_original_aspect_ratio=increase,crop=768:1152,setsar=1[bg];[bg][1:v]overlay=0:0[vout]",
                "-map", "[vout]", "-t", str(clip_dur), "-c:v", "libx264", "-preset", "fast", clip_path
            ]
        else:
            # Pexels/Pixabay फेल भयो भने कालो स्क्रिनको सट्टा Pollinations AI बाट इमेज तानेर जुम गर्ने (FAIL-SAFE)
            fallback_img_path = f"work/fallback_{idx}.jpg"
            try:
                img_url = f"https://image.pollinations.ai/prompt/{urllib.parse.quote(search_query)}?width=768&height=1152&nologo=true&model=flux&seed={int(time.time())+idx}"
                r_img = requests.get(img_url, headers=req_headers, timeout=20)
                if r_img.status_code == 200:
                    with open(fallback_img_path, "wb") as f:
                        f.write(r_img.content)
                else:
                    raise Exception("Image download failed")
            except:
                # अति अन्तिम अवस्थामा मात्रै ब्लु कलरको ब्याकग्राउन्ड बनाउने
                fallback_img = Image.new("RGB", (768, 1152), color=(20, 40, 80))
                fallback_img.save(fallback_img_path)
            
            # इमेजलाई जुम गरेर टेक्स्ट राख्ने
            cmd = [
                "ffmpeg", "-y", "-loop", "1", "-i", fallback_img_path,
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

    # ५. Background Music (BGM)
    final_output = "work/final_output.mp4"
    bg_music_file = "work/bgm.mp3"
    
    if any(word in topic for word in ["sad", "cry", "heart", "hurt", "दुख", "रुवाउने", "pain", "lonely"]):
        music_url = "https://cdn.pixabay.com/download/audio/2022/05/16/audio_03d9178bf7.mp3"
    elif any(word in topic for word in ["love", "romantic", "माया", "प्रेम", "couple", "kiss", "romance"]):
        music_url = "https://cdn.pixabay.com/download/audio/2022/01/18/audio_d0a13f69d2.mp3"
    elif any(word in topic for word in ["motivat", "success", "प्रेरणा", "सफलता", "inspire", "goal", "dream"]):
        music_url = "https://cdn.pixabay.com/download/audio/2021/08/09/audio_82c5e533c6.mp3"
    else:
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
