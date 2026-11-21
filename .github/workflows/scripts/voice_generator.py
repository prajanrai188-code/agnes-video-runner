import os
import re
import subprocess

VOICE_CATALOG = {
    "ne": {"male": "ne-NP-SagarNeural", "female": "ne-NP-HemkalaNeural"},
    "hi": {"male": "hi-IN-MadhurNeural", "female": "hi-IN-SwaraNeural"},
    "en": {"male": "en-US-ChristopherNeural", "female": "en-US-JennyNeural"},
}

LANG_ALIASES = {
    "nepali": "ne", "ne": "ne",
    "hindi": "hi", "hi": "hi",
    "english": "en", "en": "en",
}


def normalize_lang(language: str) -> str:
    return LANG_ALIASES.get((language or "ne").strip().lower(), "ne")


def _vtt_to_srt(vtt_text: str) -> str:
    """यदि edge-tts ले VTT फर्म्याट दियो भने त्यसलाई सफा SRT मा रूपान्तरण गर्छ"""
    lines = vtt_text.replace("\r\n", "\n").split("\n")
    blocks = []
    cur = []
    for line in lines:
        s = line.strip()
        if s.startswith("WEBVTT") or s.startswith("Kind:") or s.startswith("Language:"):
            continue
        if s == "":
            if cur:
                blocks.append(cur)
                cur = []
        else:
            cur.append(s)
    if cur:
        blocks.append(cur)

    srt_out = []
    idx = 1
    for blk in blocks:
        # टाइमस्ट्याम्प लाइन खोज्ने
        ts_idx = next((i for i, l in enumerate(blk) if "-->" in l), None)
        if ts_idx is None:
            continue
        ts_line = blk[ts_idx].replace(".", ",")
        # MM:SS,mmm भए 00:MM:SS,mmm बनाउने
        ts_line = re.sub(r"(?<!\d:)(\d{2}:\d{2},\d{3})", r"00:\1", ts_line)
        text_lines = blk[ts_idx + 1:]
        if not text_lines:
            continue
        srt_out.append(f"{idx}\n{ts_line}\n" + "\n".join(text_lines))
        idx += 1
    return "\n\n".join(srt_out) + "\n"


def generate_voice_and_subtitles(
    text: str,
    language: str,
    voice_gender: str,
    audio_path: str,
    srt_path: str,
) -> tuple[bool, float]:
    """Edge TTS बाट MP3 र SRT बनाउँछ, र अडियोको वास्तविक लम्बाइ (seconds) फर्काउँछ"""
    clean_text = " ".join((text or "").split()).strip()
    if not clean_text:
        return False, 0.0

    lang_code = normalize_lang(language)
    gender = (voice_gender or "male").strip().lower()
    voice_name = VOICE_CATALOG.get(lang_code, VOICE_CATALOG["ne"]).get(
        gender, VOICE_CATALOG[lang_code]["male"]
    )

    raw_sub = srt_path + ".raw"
    cmd = [
        "edge-tts",
        "--voice", voice_name,
        "--text", clean_text,
        "--write-media", audio_path,
        "--write-subtitles", raw_sub,
    ]
    subprocess.run(cmd, check=True)

    # SRT सुनिश्चित गर्ने
    if os.path.exists(raw_sub):
        with open(raw_sub, "r", encoding="utf-8", errors="ignore") as f:
            content = f.read()
        if content.lstrip().startswith("WEBVTT"):
            content = _vtt_to_srt(content)
        with open(srt_path, "w", encoding="utf-8") as f:
            f.write(content)
        os.remove(raw_sub)

    # ffprobe बाट अडियोको वास्तविक अवधि निकाल्ने
    probe = subprocess.run(
        [
            "ffprobe", "-v", "error", "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1", audio_path,
        ],
        capture_output=True, text=True,
    )
    try:
        dur = float(probe.stdout.strip())
    except Exception:
        dur = 0.0

    return os.path.exists(audio_path), dur
