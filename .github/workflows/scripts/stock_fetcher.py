import os
import random
import subprocess
import time
import urllib.parse
import requests

USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/124.0.0.0 Safari/537.36"


def download_from_pexels(query: str, output_path: str, api_key: str, min_duration: int = 5) -> bool:
    if not api_key:
        return False
    url = (
        f"https://api.pexels.com/videos/search"
        f"?query={urllib.parse.quote(query)}&orientation=portrait&per_page=15"
    )
    try:
        res = requests.get(url, headers={"Authorization": api_key}, timeout=20)
        if res.status_code != 200:
            print(f"[Pexels] HTTP {res.status_code} for '{query}'")
            return False
        data = res.json()
        videos = data.get("videos", [])
        if not videos:
            return False

        candidates = [v for v in videos if v.get("duration", 0) >= min_duration] or videos
        chosen = random.choice(candidates)
        files = chosen.get("video_files", [])
        # Portrait HD (width <= 1080) प्राथमिकता
        hd_files = [
            f for f in files
            if f.get("file_type") == "video/mp4"
            and f.get("width", 0) <= 1080
            and f.get("height", 0) >= f.get("width", 0)
        ] or [f for f in files if f.get("file_type") == "video/mp4"]

        if not hd_files:
            return False

        best = sorted(hd_files, key=lambda x: x.get("width", 0), reverse=True)[0]
        dl = requests.get(best["link"], headers={"User-Agent": USER_AGENT}, timeout=60)
        if dl.status_code == 200 and len(dl.content) > 50_000:
            with open(output_path, "wb") as f:
                f.write(dl.content)
            return True
    except Exception as e:
        print(f"[Pexels] Error: {e}")
    return False


def download_from_pixabay(query: str, output_path: str, api_key: str) -> bool:
    if not api_key:
        return False
    url = (
        f"https://pixabay.com/api/videos/"
        f"?key={api_key}&q={urllib.parse.quote(query)}&video_type=film&per_page=15"
    )
    try:
        res = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=20)
        if res.status_code != 200:
            print(f"[Pixabay] HTTP {res.status_code} for '{query}'")
            return False
        hits = res.json().get("hits", [])
        if not hits:
            return False

        chosen = random.choice(hits)
        vids = chosen.get("videos", {})
        link = (
            vids.get("large", {}).get("url")
            or vids.get("medium", {}).get("url")
            or vids.get("small", {}).get("url")
        )
        if not link:
            return False

        dl = requests.get(link, headers={"User-Agent": USER_AGENT}, timeout=60)
        if dl.status_code == 200 and len(dl.content) > 50_000:
            with open(output_path, "wb") as f:
                f.write(dl.content)
            return True
    except Exception as e:
        print(f"[Pixabay] Error: {e}")
    return False


def create_fallback_clip(query: str, output_path: str, duration: int = 6) -> None:
    """Pexels र Pixabay दुवै असफल भएमा Pollinations AI इमेजबाट 1080x1920 zoom क्लिप बनाउँछ"""
    img_path = output_path.replace(".mp4", ".jpg")
    downloaded = False
    try:
        url = (
            f"https://image.pollinations.ai/prompt/{urllib.parse.quote(query + ', cinematic vertical 9:16')}"
            f"?width=1080&height=1920&nologo=true&model=flux&seed={int(time.time())}"
        )
        r = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=35)
        if r.status_code == 200 and len(r.content) > 5000:
            with open(img_path, "wb") as f:
                f.write(r.content)
            downloaded = True
    except Exception as e:
        print(f"[Fallback Image] Warning: {e}")

    frames = duration * 25
    if downloaded:
        cmd = [
            "ffmpeg", "-y", "-loop", "1", "-i", img_path,
            "-vf", (
                f"scale=1620:2880,"
                f"zoompan=z='min(zoom+0.0012,1.25)':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)'"
                f":d={frames}:s=1080x1920:fps=25,format=yuv420p"
            ),
            "-t", str(duration), "-c:v", "libx264", "-preset", "fast", output_path
        ]
    else:
        cmd = [
            "ffmpeg", "-y", "-f", "lavfi",
            "-i", f"color=c=#141c30:s=1080x1920:d={duration}",
            "-c:v", "libx264", "-pix_fmt", "yuv420p", output_path
        ]
    subprocess.run(cmd, check=True)


def fetch_stock_video(query: str, output_path: str, duration: int = 6) -> str:
    pexels_key = os.environ.get("PEXELS_API_KEY", "").strip()
    pixabay_key = os.environ.get("PIXABAY_API_KEY", "").strip()

    # १. Pexels प्रयास
    if download_from_pexels(query, output_path, pexels_key, min_duration=duration):
        return "pexels"
    # २. Pixabay प्रयास
    if download_from_pixabay(query, output_path, pixabay_key):
        return "pixabay"
    # ३. सामान्य keyword बाट पुन: प्रयास
    broad_query = query.split()[0] if query.split() else "nature"
    if download_from_pexels(broad_query, output_path, pexels_key, min_duration=duration):
        return "pexels_broad"
    if download_from_pixabay(broad_query, output_path, pixabay_key):
        return "pixabay_broad"

    # ४. अन्तिम सुरक्षित Fallback
    create_fallback_clip(query, output_path, duration)
    return "fallback"
