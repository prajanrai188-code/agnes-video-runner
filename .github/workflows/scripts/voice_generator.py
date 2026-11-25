import base64
import os
import re
import subprocess
import requests

# Upgraded Male-first Voice Catalog (Free Edge TTS Fallback)
VOICE_CATALOG = {
    "ne": {"male": "ne-NP-SagarNeural", "female": "ne-NP-HemkalaNeural"},
    "hi": {"male": "en-US-BrianMultilingualNeural", "female": "en-US-EmmaMultilingualNeural"},
    "en": {"male": "en-US-BrianMultilingualNeural", "female": "en-US-EmmaMultilingualNeural"},
}

# Kokoro-82M English Voices (Free English Fallback)
KOKORO_VOICES = {
    "male": "am_michael",
    "female": "af_heart",
}

# ElevenLabs Default Voices (Adam = Male, Rachel = Female)
ELEVENLABS_DEFAULT_VOICES = {
    "male": "pNInz6obpgDQGcFmaJgB",
    "female": "21m00Tcm4TlvDq8ikWAM",
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


def _detect_narration_tag(text: str, topic: str = "") -> str:
    """भिडियोको थिम/भावना अनुसार ElevenLabs v4 को लागि उपयुक्त Narration ट्याग छान्छ"""
    combined = f"{topic} {text}".lower()

    mood_tags = [
        ("[softly, emotional]", [
            "sad", "cry", "heartbreak", "lonely", "pain", "hurt", "miss", "tears", "alone", "lost",
            "दुख", "पीडा", "आँसु", "एक्लो", "बिछोड", "याद", "टुटेको", "रुनु", "दर्द", "तन्हा", "अकेला",
        ]),
        ("[warm, tender]", [
            "love", "romantic", "heart", "couple", "forever", "soulmate", "affection", "care",
            "माया", "प्रेम", "मुटु", "साथ", "प्यार", "मोहब्बत", "दिल", "इश्क",
        ]),
        ("[inspiring, confident]", [
            "motivat", "success", "goal", "dream", "focus", "discipline", "strong", "win", "hustle", "rise",
            "प्रेरणा", "सफलता", "लक्ष्य", "सपना", "मेहनत", "हिम्मत", "जित", "संघर्ष", "कामयाबी",
        ]),
        ("[mysterious, calm]", [
            "mystery", "secret", "dark", "shadow", "ancient", "history", "story", "legend", "night",
            "रहस्य", "अँध्यारो", "कथा", "इतिहास", "रात", "चमत्कार",
        ]),
    ]

    for tag, keywords in mood_tags:
        if any(k in combined for k in keywords):
            return tag

    return "[warm, calm]"


def _fmt_srt_time(sec: float) -> str:
    sec = max(0.0, float(sec))
    h = int(sec // 3600)
    m = int((sec % 3600) // 60)
    s = int(sec % 60)
    ms = int(round((sec - int(sec)) * 1000))
    if ms >= 1000:
        s += 1
        ms -= 1000
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def _vtt_to_srt(vtt_text: str) -> str:
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


def _alignment_to_srt(alignment: dict, max_words: int = 7) -> str:
    chars = alignment.get("characters") or []
    starts = alignment.get("character_start_times_seconds") or []
    ends = alignment.get("character_end_times_seconds") or []
    n = min(len(chars), len(starts), len(ends))
    if n == 0:
        return ""

    words = []
    cur_word = ""
    w_start = None
    w_end = None

    for i in range(n):
        ch = chars[i]
        if ch.isspace():
            if cur_word:
                words.append((cur_word, w_start, w_end))
                cur_word = ""
                w_start = None
                w_end = None
        else:
            if w_start is None:
                w_start = starts[i]
            cur_word += ch
            w_end = ends[i]

    if cur_word:
        words.append((cur_word, w_start, w_end))

    if not words:
        return ""

    srt_blocks = []
    idx = 1
    buf = []
    for w_text, st, en in words:
        # यदि [warm, calm] जस्ता ट्याग शब्दको रूपमा आएमा सबटाइटलमा नदेखाउने
        clean_w = re.sub(r"\[[^\]]*\]", "", w_text).strip()
        if not clean_w:
            continue
        buf.append((clean_w, st, en))
        ends_sentence = clean_w.endswith((".", "!", "?", "।"))
        if len(buf) >= max_words or ends_sentence:
            line_text = " ".join(x[0] for x in buf)
            srt_blocks.append(
                f"{idx}\n{_fmt_srt_time(buf[0][1])} --> {_fmt_srt_time(buf[-1][2])}\n{line_text}"
            )
            idx += 1
            buf = []

    if buf:
        line_text = " ".join(x[0] for x in buf)
        srt_blocks.append(
            f"{idx}\n{_fmt_srt_time(buf[0][1])} --> {_fmt_srt_time(buf[-1][2])}\n{line_text}"
        )

    return "\n\n".join(srt_blocks) + "\n"


def _write_proportional_srt(text: str, total_dur: float, srt_path: str, max_words: int = 7) -> None:
    words = text.split()
    if not words or total_dur <= 0:
        return
    chunks = [" ".join(words[i:i + max_words]) for i in range(0, len(words), max_words)]
    per_chunk = total_dur / len(chunks)
    blocks = []
    for i, ch in enumerate(chunks, start=1):
        st = (i - 1) * per_chunk
        en = min(total_dur, i * per_chunk - 0.05)
        blocks.append(f"{i}\n{_fmt_srt_time(st)} --> {_fmt_srt_time(en)}\n{ch}")
    with open(srt_path, "w", encoding="utf-8") as f:
        f.write("\n\n".join(blocks) + "\n")


def _generate_with_elevenlabs(
    text: str,
    gender: str,
    audio_path: str,
    srt_path: str,
    api_key: str,
    voice_id: str = "",
    topic: str = "",
) -> tuple[bool, float]:
    """पहिले ElevenLabs v4 (Narration ट्यागसहित) प्रयास गर्छ, नचले Multilingual v2 मा Fallback गर्छ"""
    key = (api_key or "").strip()
    if not key:
        return False, 0.0

    vid = (voice_id or "").strip() or ELEVENLABS_DEFAULT_VOICES.get(gender, ELEVENLABS_DEFAULT_VOICES["male"])
    url = f"https://api.elevenlabs.io/v1/text-to-speech/{vid}/with-timestamps?output_format=mp3_44100_128"
    headers = {
        "xi-api-key": key,
        "Content-Type": "application/json",
    }

    narration_tag = _detect_narration_tag(text, topic)

    for model_id in ["eleven_v4", "eleven_multilingual_v2"]:
        # v4 मा मात्र Expression Tag थप्ने (v2 ले ट्यागलाई शब्दकै रूपमा पढ्न सक्छ)
        narration_text = f"{narration_tag} {text}" if model_id == "eleven_v4" else text

        payload = {
            "text": narration_text,
            "model_id": model_id,
            "voice_settings": {
                "stability": 0.40,
                "similarity_boost": 0.80,
                "style": 0.50,
                "use_speaker_boost": True,
                "speed": 0.92,
            },
        }

        res = requests.post(url, headers=headers, json=payload, timeout=90)
        if res.status_code == 200:
            data = res.json()
            audio_b64 = data.get("audio_base64")
            if not audio_b64:
                continue

            with open(audio_path, "wb") as f:
                f.write(base64.b64decode(audio_b64))

            dur = _probe_duration(audio_path)
            if dur <= 0:
                continue

            alignment = data.get("normalized_alignment") or data.get("alignment") or {}
            srt_content = _alignment_to_srt(alignment, max_words=7)
            srt_content = re.sub(r"\[[^\]]+\]\s*", "", srt_content)
            if srt_content.strip():
                with open(srt_path, "w", encoding="utf-8") as f:
                    f.write(srt_content)
            else:
                _write_proportional_srt(text, dur, srt_path)

            print(f"[ElevenLabs] Success with model={model_id}, tag={narration_tag if model_id == 'eleven_v4' else 'none'}")
            return True, dur

        if res.status_code in (401, 402, 429):
            print(f"[ElevenLabs] Quota/Auth Error (HTTP {res.status_code}): {res.text[:200]}")
            return False, 0.0

        print(f"[ElevenLabs] Model '{model_id}' failed (HTTP {res.status_code}), trying next...")

    return False, 0.0


def _ensure_kokoro_files() -> tuple[str, str]:
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
    voice_name = VOICE_CATALOG.get(lang_code, VOICE_CATALOG["ne"]).get(
        gender, VOICE_CATALOG[lang_code]["male"]
    )

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
    elevenlabs_api_key: str = "",
    elevenlabs_voice_id: str = "",
    topic: str = "",
) -> tuple[bool, float]:
    clean_text = " ".join((text or "").split()).strip()
    if not clean_text:
        return False, 0.0

    lang_code = normalize_lang(language)
    gender = (voice_gender or "male").strip().lower()
    if gender not in ("male", "female"):
        gender = "male"

    # १. पहिले ElevenLabs (v4 Narration -> Multilingual v2) प्रयास गर्ने
    el_key = (elevenlabs_api_key or os.environ.get("ELEVENLABS_API_KEY", "")).strip()
    el_vid = (elevenlabs_voice_id or os.environ.get("ELEVENLABS_VOICE_ID", "")).strip()

    if el_key:
        try:
            ok, dur = _generate_with_elevenlabs(
                clean_text, gender, audio_path, srt_path, el_key, el_vid, topic=topic
            )
            if ok and dur > 0:
                print(f"[Voice] Generated {lang_code.upper()} via ElevenLabs (voice={el_vid or ELEVENLABS_DEFAULT_VOICES[gender]})")
                return True, dur
            print("[Voice] ElevenLabs credits exhausted or failed -> Switching to Free Voice Engine...")
        except Exception as e:
            print(f"[Voice] ElevenLabs error ({e}) -> Switching to Free Voice Engine...")

    # २. Free Voice Fallback (English को लागि Kokoro-82M)
    if lang_code == "en":
        try:
            ok, dur = _generate_with_kokoro(clean_text, gender, audio_path, srt_path)
            if ok and dur > 0:
                print(f"[Voice] Generated English via Kokoro-82M ({KOKORO_VOICES.get(gender)})")
                return True, dur
        except Exception as e:
            print(f"[Voice] Kokoro-82M failed, falling back to Edge TTS: {e}")

    # ३. Free Voice Fallback (Nepali / Hindi / English Edge TTS)
    print(f"[Voice] Generating {lang_code.upper()} via Edge TTS ({gender})")
    return _generate_with_edge_tts(clean_text, lang_code, gender, audio_path, srt_path)
