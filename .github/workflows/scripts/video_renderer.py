import glob
import html
import os
import random
import re
import subprocess
from PIL import Image


def get_media_duration(file_path: str) -> float:
    if not file_path or not os.path.exists(file_path):
        return 0.0
    probe = subprocess.run(
        [
            "ffprobe", "-v", "error", "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1", file_path,
        ],
        capture_output=True, text=True,
    )
    try:
        return float(probe.stdout.strip())
    except Exception:
        return 0.0


def pick_local_bgm(topic: str) -> str | None:
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


def _srt_time_to_sec(ts: str) -> float:
    ts = ts.strip().replace(",", ".")
    parts = ts.split(":")
    if len(parts) == 3:
        return int(parts[0]) * 3600 + int(parts[1]) * 60 + float(parts[2])
    if len(parts) == 2:
        return int(parts[0]) * 60 + float(parts[1])
    return 0.0


def parse_srt(srt_path: str) -> list[dict]:
    if not srt_path or not os.path.exists(srt_path):
        return []
    with open(srt_path, "r", encoding="utf-8", errors="ignore") as f:
        raw = f.read().replace("\r\n", "\n")

    entries = []
    for block in re.split(r"\n\s*\n", raw.strip()):
        lines = [l.strip() for l in block.split("\n") if l.strip()]
        ts_idx = next((i for i, l in enumerate(lines) if "-->" in l), None)
        if ts_idx is None:
            continue
        start_s, end_s = lines[ts_idx].split("-->")[:2]
        text = " ".join(lines[ts_idx + 1:]).strip()
        if text:
            entries.append({
                "start": _srt_time_to_sec(start_s),
                "end": _srt_time_to_sec(end_s),
                "text": text,
            })
    return entries


def render_pango_subtitle_png(text: str, out_png: str) -> bool:
    raw_png = out_png.replace(".png", "_raw.png")
    escaped = html.escape(text)
    # फन्ट साइज 42 बाट 50 बनाइएको (Reels/Shorts मा अझै स्पष्ट देखिने)
    markup = f"<span font='Noto Sans Devanagari Bold 50' foreground='white'>{escaped}</span>"

    cmd = [
        "convert",
        "-background", "none",
        "-size", "940x",
        "-define", "pango:align=center",
        f"pango:{markup}",
        raw_png,
    ]
    res = subprocess.run(cmd, capture_output=True, text=True)
    if res.returncode != 0 or not os.path.exists(raw_png):
        print(f"[Pango Render Warning]: {res.stderr}")
        return False

    fg = Image.open(raw_png).convert("RGBA")
    pad = 14
    canvas = Image.new("RGBA", (fg.width + pad * 2, fg.height + pad * 2), (0, 0, 0, 0))

    alpha = fg.split()[3]
    black_layer = Image.new("RGBA", fg.size, (0, 0, 0, 255))
    black_layer.putalpha(alpha)

    for dx in (-5, -3, 0, 3, 5):
        for dy in (-5, -3, 0, 3, 5):
            if dx != 0 or dy != 0:
                canvas.alpha_composite(black_layer, (pad + dx, pad + dy))

    canvas.alpha_composite(fg, (pad, pad))
    canvas.save(out_png)
    try:
        os.remove(raw_png)
    except Exception:
        pass
    return True


def render_final_video(
    clip_paths: list[str],
    output_path: str,
    voice_path: str | None = None,
    srt_path: str | None = None,
    bgm_path: str | None = None,
    total_duration: float = 20.0,
) -> None:
    concat_file = "work/concat.txt"
    with open(concat_file, "w", encoding="utf-8") as f:
        for cp in clip_paths:
            f.write(f"file '{os.path.abspath(cp)}'\n")

    merged_video = "work/merged.mp4"
    subprocess.run(
        ["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", concat_file, "-c", "copy", merged_video],
        check=True,
    )

    has_voice = bool(voice_path and os.path.exists(voice_path))
    has_bgm = bool(bgm_path and os.path.exists(bgm_path))

    final_dur = float(total_duration)
    if has_voice:
        voice_dur = get_media_duration(voice_path)
        if voice_dur > 0:
            final_dur = max(final_dur, voice_dur + 0.6)

    video_dur = get_media_duration(merged_video)
    pad_needed = max(0.0, final_dur - video_dur + 0.5)

    sub_entries = parse_srt(srt_path) if srt_path else []
    rendered_subs = []
    for idx, entry in enumerate(sub_entries):
        png_path = f"work/sub_{idx}.png"
        if render_pango_subtitle_png(entry["text"], png_path):
            rendered_subs.append((png_path, entry["start"], entry["end"]))

    video_input = merged_video
    if rendered_subs or pad_needed > 0.05:
        subbed_video = "work/subbed.mp4"
        cmd = ["ffmpeg", "-y", "-i", merged_video]
        for png_path, _, _ in rendered_subs:
            cmd.extend(["-i", png_path])

        filter_chains = []
        if pad_needed > 0.05:
            filter_chains.append(f"[0:v]tpad=stop_mode=clone:stop_duration={pad_needed:.2f}[v0]")
        else:
            filter_chains.append("[0:v]null[v0]")

        cur_stream = "v0"
        for i, (_, st, en) in enumerate(rendered_subs, start=1):
            next_stream = f"v{i}"
            # Top Safe Zone (माथिबाट 360px तल, सेन्टरमा)
            filter_chains.append(
                f"[{cur_stream}][{i}:v]overlay=(W-w)/2:360:enable='between(t,{st:.2f},{en:.2f})'[{next_stream}]"
            )
            cur_stream = next_stream

        cmd.extend([
            "-filter_complex", ";".join(filter_chains),
            "-map", f"[{cur_stream}]",
            "-t", f"{final_dur:.2f}",
            "-c:v", "libx264", "-preset", "fast", "-crf", "23", "-pix_fmt", "yuv420p",
            subbed_video,
        ])
        subprocess.run(cmd, check=True)
        video_input = subbed_video

    if has_voice and has_bgm:
        cmd = [
            "ffmpeg", "-y",
            "-i", video_input,
            "-i", voice_path,
            "-stream_loop", "-1", "-i", bgm_path,
            "-filter_complex",
            "[1:a]volume=1.0,apad=pad_dur=0.6[v];[2:a]volume=0.14[b];[v][b]amix=inputs=2:duration=first:dropout_transition=2[a]",
            "-map", "0:v", "-map", "[a]",
            "-c:v", "copy", "-c:a", "aac", "-b:a", "192k",
            "-t", f"{final_dur:.2f}",
            output_path,
        ]
    elif has_voice:
        cmd = [
            "ffmpeg", "-y", "-i", video_input, "-i", voice_path,
            "-filter_complex", "[1:a]apad=pad_dur=0.6[a]",
            "-map", "0:v", "-map", "[a]",
            "-c:v", "copy", "-c:a", "aac", "-b:a", "192k",
            "-t", f"{final_dur:.2f}",
            output_path,
        ]
    elif has_bgm:
        cmd = [
            "ffmpeg", "-y", "-i", video_input, "-stream_loop", "-1", "-i", bgm_path,
            "-map", "0:v", "-map", "1:a",
            "-c:v", "copy", "-c:a", "aac", "-b:a", "192k",
            "-t", f"{final_dur:.2f}",
            output_path,
        ]
    else:
        cmd = [
            "ffmpeg", "-y", "-i", video_input,
            "-f", "lavfi", "-i", "anullsrc=r=44100:cl=stereo",
            "-map", "0:v", "-map", "1:a",
            "-c:v", "copy", "-c:a", "aac",
            "-t", f"{final_dur:.2f}",
            output_path,
        ]

    subprocess.run(cmd, check=True)
