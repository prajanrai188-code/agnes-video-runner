import os
import re
import subprocess
import requests

# Upgraded Male-first Voice Catalog (Edge TTS)
VOICE_CATALOG = {
    "ne": {"male": "ne-NP-SagarNeural", "female": "ne-NP-HemkalaNeural"},
    "hi": {"male": "en-US-BrianMultilingualNeural", "female": "en-US-EmmaMultilingualNeural"},
    "en": {"male": "en-US-BrianMultilingualNeural", "female": "en-US-EmmaMultilingualNeural"},
}

# Kokoro-82M English Voices
KOKORO_VOICES = {
    "male": "am_michael",
    "female": "af_heart",
}

KOKORO_MODEL_URL = "https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/kokoro-v1.0.onnx"
KOKORO_VOICES_URL = "https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/voices-v1.0.bin"

LANG_ALIASES = {
    "nepali": "ne", "ne": "ne",
    "hindi": "hi", "hi": "hi",
    "english": "en", "en": "en",
}


def normalize_lang(language: str) -> str:
    return LANG_ALIASES.get((language or "ne").strip().lower(), "ne")


def _fmt_srt_time(sec: float) -> str:
    sec = max(0.0, sec)
    h = int(sec // 3600)
    m = int((sec % 3600) // 60)
    s = int(sec % 60)
    ms = int(round((sec - int(sec)) * 1000))
    if ms >= 1000:
        s += 1
        ms -= 1000
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


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
        ts_idx = next((i for i, l in enumerate(blk) if "-->" in l), None)
        if ts_idx is None:
            continue
        ts_line = blk[ts_idx].replace(".", ",")
        ts_line = re.sub(r"(?<!\d:)(\d{2}:\d{2},\d{3})", r"00:\1", ts_line)
        text_lines = blk[ts_idx + 1:]
        if not text_lines:
            continue
        srt_out.append(f"{idx}\n{ts_line}\n" + "\n".join(text_lines))
        idx += 1
    return "\n\n".join(srt_out) + "\n"


def _probe_duration(audio_path: str) -> float:
    probe = subprocess.run(
        [
            "ffprobe", "-v", "error", "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1", audio_path,
        ],
        capture_output=True, text=True,
    )
    try:
        return float(probe.stdout.strip())
    except Exception:
        return 0.0


def _ensure_kokoro_files() -> tuple[str, str]:
    """Kokoro-82M ONNX र voices फाइल ~/.cache/kokoro-onnx मा डाउनलोड/क्यास गर्छ"""
    cache_dir = os.path.expanduser("~/.cache/kokoro-onnx")
    os.makedirs(cache_dir, exist_ok=True)
    model_path = os.path.join(cache_dir, "kokoro-v1.0.onnx")
    voices_path = os.path.join(cache_dir, "voices-v1.0.bin")

    for url, path in [(KOKORO_MODEL_URL, model_path), (KOKORO_VOICES_URL, voices_path)]:
        if not os.path.exists(path) or os.path.getsize(path) < 100_000:
            print(f"[Kokoro] Downloading {os.path.basename(path)}...")
            r = requests.get(url, stream=True, timeout=180)
            r.raise_for_status()
            with open(path, "wb") as f:
                for chunk in r.iter_content(chunk_size=1024 * 1024):
                    if chunk:
                        f.write(chunk)

    return model_path, voices_path


def _split_english_chunks(text: str, max_words: int = 10) -> list[str]:
    """अङ्ग्रेजी टेक्स्टलाई प्राकृतिक सबटाइटल खण्डमा विभाजन गर्छ"""
    raw_sentences = re.split(r"(?<=[.!?])\s+", text.strip())
    chunks = []
    for sent in raw_sentences:
        words = sent.split()
        if not words:
            continue
        if len(words) <= max_words:
            chunks.append(sent)
        else:
            for i in range(0, len(words), max_words):
                chunks.append(" ".join(words[i:i + max_words]))
    return chunks or [text]


def _generate_with_kokoro(
    text: str,
    gender: str,
    audio_path: str,
    srt_path: str,
) -> tuple[bool, float]:
    """Kokoro-82M बाट उच्च-गुणस्तरको English Male अडियो र Synchronized SRT बनाउँछ"""
    import numpy as np
    import soundfile as sf
    from kokoro_onnx import Kokoro

    model_path, voices_path = _ensure_kokoro_files()
    kokoro = Kokoro(model_path, voices_path)
    voice_id = KOKORO_VOICES.get(gender, "am_michael")

    chunks = _split_english_chunks(text, max_words=9)
    audio_segments = []
    srt_blocks = []
    sample_rate = 24000
    cur_sec = 0.0
    pause_sec = 0.18

    for idx, chunk in enumerate(chunks, start=1):
        samples, sr = kokoro.create(chunk, voice=voice_id, speed=0.95, lang="en-us")
        sample_rate = sr
        dur = len(samples) / float(sr)

        srt_blocks.append(
            f"{idx}\n{_fmt_srt_time(cur_sec)} --> {_fmt_srt_time(cur_sec + dur)}\n{chunk}"
        )
        audio_segments.append(samples)
        audio_segments.append(np.zeros(int(sr * pause_sec), dtype=samples.dtype))
        cur_sec += dur + pause_sec

    if not audio_segments:
        return False, 0.0

    full_audio = np.concatenate(audio_segments)
    wav_path = audio_path.replace(".mp3", ".wav")
    sf.write(wav_path, full_audio, sample_rate)

    # WAV लाई MP3 मा रूपान्तरण गर्ने
    subprocess.run(
        ["ffmpeg", "-y", "-i", wav_path, "-c:a", "libmp3lame", "-b:a", "192k", audio_path],
        check=True,
    )
    if os.path.exists(wav_path):
        os.remove(wav_path)

    with open(srt_path, "w", encoding="utf-8") as f:
        f.write("\n\n".join(srt_blocks) + "\n")

    return os.path.exists(audio_path), _probe_duration(audio_path)


def _generate_with_edge_tts(
    text: str,
    lang_code: str,
    gender: str,
    audio_path: str,
    srt_path: str,
) -> tuple[bool, float]:
    """Upgraded Multilingual Edge TTS बाट MP3 र Auto-SRT बनाउँछ"""
    voice_name = VOICE_CATALOG.get(lang_code, VOICE_CATALOG["ne"]).get(
        gender, VOICE_CATALOG[lang_code]["male"]
    )

    # Male आवाजलाई प्राकृतिक र शान्त बनाउने ट्युनिङ
    rate = "-10%" if lang_code == "ne" else ("-8%" if lang_code == "hi" else "-6%")
    pitch = "-2Hz" if gender == "male" else "+0Hz"

    raw_sub = srt_path + ".raw"
    cmd = [
        "edge-tts",
        "--voice", voice_name,
        f"--rate={rate}",
        f"--pitch={pitch}",
        "--text", text,
        "--write-media", audio_path,
        "--write-subtitles", raw_sub,
    ]
    subprocess.run(cmd, check=True)

    if os.path.exists(raw_sub):
        with open(raw_sub, "r", encoding="utf-8", errors="ignore") as f:
            content = f.read()
        if content.lstrip().startswith("WEBVTT"):
            content = _vtt_to_srt(content)
        with open(srt_path, "w", encoding="utf-8") as f:
            f.write(content)
        os.remove(raw_sub)

    return os.path.exists(audio_path), _probe_duration(audio_path)


def generate_voice_and_subtitles(
    text: str,
    language: str,
    voice_gender: str,
    audio_path: str,
    srt_path: str,
) -> tuple[bool, float]:
    """
    - English: Kokoro-82M Male (am_michael) + Edge TTS Fallback
    - Hindi: Multilingual Edge TTS Male (en-US-BrianMultilingualNeural)
    - Nepali: Edge TTS Male (ne-NP-SagarNeural)
    """
    clean_text = " ".join((text or "").split()).strip()
    if not clean_text:
        return False, 0.0

    lang_code = normalize_lang(language)
    gender = (voice_gender or "male").strip().lower()
    if gender not in ("male", "female"):
        gender = "male"

    if lang_code == "en":
        try:
            ok, dur = _generate_with_kokoro(clean_text, gender, audio_path, srt_path)
            if ok and dur > 0:
                print(f"[Voice] Generated English via Kokoro-82M ({KOKORO_VOICES.get(gender)})")
                return True, dur
        except Exception as e:
            print(f"[Voice] Kokoro-82M failed, falling back to Edge TTS: {e}")

    print(f"[Voice] Generating {lang_code.upper()} via Edge TTS ({gender})")
    return _generate_with_edge_tts(clean_text, lang_code, gender, audio_path, srt_path)
