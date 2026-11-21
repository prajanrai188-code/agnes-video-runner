import glob
import os
import random
import subprocess


def pick_local_bgm(topic: str) -> str | None:
    """assets/music/ फोल्डरबाट मुड अनुसारको रोयल्टी-फ्री MP3 छान्छ"""
    music_dir = "assets/music"
    if not os.path.isdir(music_dir):
        return None
    all_tracks = glob.glob(os.path.join(music_dir, "*.mp3"))
    if not all_tracks:
        return None

    t = (topic or "").lower()
    mood_map = {
        "sad": ["sad", "cry", "heart", "hurt", "pain", "lonely", "दुख", "पीडा"],
        "love": ["love", "romantic", "couple", "माया", "प्रेम"],
        "motivation": ["motivat", "success", "goal", "exercise", "प्रेरणा", "सफलता"],
    }
    for mood, words in mood_map.items():
        if any(w in t for w in words):
            matched = [p for p in all_tracks if mood in os.path.basename(p).lower()]
            if matched:
                return random.choice(matched)

    return random.choice(all_tracks)


def normalize_clip(raw_path: str, out_path: str, duration: float, width: int = 1080, height: int = 1920) -> None:
    """हरेक स्टक भिडियोलाई ठ्याक्कै 1080x1920 (9:16), 30fps, हल्का डार्क टिन्टसहित तयार पार्छ"""
    vf = (
        f"scale={width}:{height}:force_original_aspect_ratio=increase,"
        f"crop={width}:{height},setsar=1,fps=30,format=yuv420p,"
        f"eq=brightness=-0.05:contrast=1.05"
    )
    cmd = [
        "ffmpeg", "-y", "-stream_loop", "-1", "-i", raw_path,
        "-t", f"{duration:.2f}",
        "-vf", vf,
        "-an", "-c:v", "libx264", "-preset", "fast", "-crf", "23",
        out_path,
    ]
    subprocess.run(cmd, check=True)


def render_final_video(
    clip_paths: list[str],
    output_path: str,
    voice_path: str | None = None,
    srt_path: str | None = None,
    bgm_path: str | None = None,
    total_duration: float = 20.0,
) -> None:
    # १. सबै क्लिप जोड्ने
    concat_file = "work/concat.txt"
    with open(concat_file, "w", encoding="utf-8") as f:
        for cp in clip_paths:
            f.write(f"file '{os.path.abspath(cp)}'\n")

    merged_video = "work/merged.mp4"
    subprocess.run(
        ["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", concat_file, "-c", "copy", merged_video],
        check=True,
    )

    # २. यदि SRT सबटाइटल छ भने Noto Sans Devanagari मा बर्न गर्ने
    video_input = merged_video
    if srt_path and os.path.exists(srt_path) and os.path.getsize(srt_path) > 10:
        subbed_video = "work/subbed.mp4"
        style = (
            "FontName=Noto Sans Devanagari,FontSize=15,Bold=1,"
            "PrimaryColour=&H00FFFFFF,OutlineColour=&H00000000,"
            "BorderStyle=1,Outline=2,Shadow=1,Alignment=2,MarginV=95"
        )
        subprocess.run(
            [
                "ffmpeg", "-y", "-i", merged_video,
                "-vf", f"subtitles={srt_path}:force_style='{style}'",
                "-c:v", "libx264", "-preset", "fast", "-crf", "23", "-pix_fmt", "yuv420p",
                subbed_video,
            ],
            check=True,
        )
        video_input = subbed_video

    # ३. अडियो (Voiceover + Background Music) मिक्स गर्ने
    has_voice = bool(voice_path and os.path.exists(voice_path))
    has_bgm = bool(bgm_path and os.path.exists(bgm_path))

    if has_voice and has_bgm:
        cmd = [
            "ffmpeg", "-y",
            "-i", video_input,
            "-i", voice_path,
            "-stream_loop", "-1", "-i", bgm_path,
            "-filter_complex",
            "[1:a]volume=1.0[v];[2:a]volume=0.14[b];[v][b]amix=inputs=2:duration=first:dropout_transition=2[a]",
            "-map", "0:v", "-map", "[a]",
            "-c:v", "copy", "-c:a", "aac", "-b:a", "192k",
            "-t", f"{total_duration:.2f}", "-shortest",
            output_path,
        ]
    elif has_voice:
        cmd = [
            "ffmpeg", "-y", "-i", video_input, "-i", voice_path,
            "-map", "0:v", "-map", "1:a",
            "-c:v", "copy", "-c:a", "aac", "-b:a", "192k",
            "-t", f"{total_duration:.2f}", "-shortest",
            output_path,
        ]
    elif has_bgm:
        cmd = [
            "ffmpeg", "-y", "-i", video_input, "-stream_loop", "-1", "-i", bgm_path,
            "-map", "0:v", "-map", "1:a",
            "-c:v", "copy", "-c:a", "aac", "-b:a", "192k",
            "-t", f"{total_duration:.2f}", "-shortest",
            output_path,
        ]
    else:
        cmd = [
            "ffmpeg", "-y", "-i", video_input,
            "-f", "lavfi", "-i", "anullsrc=r=44100:cl=stereo",
            "-map", "0:v", "-map", "1:a",
            "-c:v", "copy", "-c:a", "aac",
            "-t", f"{total_duration:.2f}", "-shortest",
            output_path,
        ]

    subprocess.run(cmd, check=True)
