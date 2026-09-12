import hashlib
import os
import shutil
import subprocess
import tempfile

from collections import OrderedDict
from time import monotonic, perf_counter

import gradio as gr
from dotenv import load_dotenv
from elevenlabs import ElevenLabs

from blog_summarizer import summarize_blog
from multi_agent import build_conversation

load_dotenv()

VOICES = {
    "George — Warm & Captivating Storyteller (British)": "JBFqnCBsd6RMkjVDRZzb",
    "Rachel — Calm & Professional Narrator (American)": "21m00Tcm4TlvDq8ikWAM",
    "Adam — Deep & Engaging Voice (American)": "pNInz6obpgDQGcFmaJgB",
    "Sarah — Soft, Warm & Expressive (American)": "EXAVITQu4vr4xnSDxMaL",
    "Antoni — Well-Rounded & Friendly (American)": "ErXwobaYiN019PkySvjV",
    "Domi — Energetic & Confident (American)": "AZnzlk1XvdvUeBnXmlld",
    "Arnold — Crisp & Articulate (American)": "VR6AewLTigWG4xSOukaG",
}

SINGLE_VOICE_MODE = "Single Voice Podcast"
MULTI_AGENT_MODE = "Multi-Agent Podcast"
DEFAULT_HOST_VOICE_ID = "JBFqnCBsd6RMkjVDRZzb"  # George
DEFAULT_EXPERT_VOICE_ID = "Xb7hH8MSUJpSbSDYk0k2"  # Alice

_account_voices_cache = None
_ACCOUNT_VOICES_TTL = 60.0

_audio_cache_dir = None
_audio_cache_lru = OrderedDict()
_AUDIO_CACHE_MAX = 12


def _elevenlabs_client():
    api_key = os.environ.get("ELEVENLABS_API_KEY")
    if not api_key:
        raise ValueError("ELEVENLABS_API_KEY must be configured.")
    return ElevenLabs(api_key=api_key, timeout=90)


def _fetch_account_voices():
    """Return {voice_name: voice_id} for voices the account may actually use."""
    api_key = os.environ.get("ELEVENLABS_API_KEY")
    if not api_key:
        return {}
    try:
        client = ElevenLabs(api_key=api_key, timeout=8)
        voices = client.voices.get_all().voices
        available = {v.name: v.voice_id for v in voices if getattr(v, "voice_id", None)}
        available_ids = set(available.values())
        print(f"[ElevenLabs] Found {len(available)} voices on this account.", flush=True)
        for label, voice_id in VOICES.items():
            if voice_id in available_ids:
                print(f"  - usable curated voice: {voice_id} ({label.split(' — ')[0]})", flush=True)
        return available
    except Exception as error:
        print(
            f"[ElevenLabs] Could not list account voices ({type(error).__name__}); "
            "using curated defaults for this run.",
            flush=True,
        )
        return {}


def account_voices():
    """Cached account voices; empty results are retried after a short TTL."""
    global _account_voices_cache
    now = perf_counter()
    if _account_voices_cache is None or not _account_voices_cache[1]:
        if _account_voices_cache is None or now - _account_voices_cache[0] > _ACCOUNT_VOICES_TTL:
            _account_voices_cache = (now, _fetch_account_voices())
    return _account_voices_cache[1]


def _build_voice_choices():
    """Curated voices the account owns, then any other account voices."""
    available = account_voices()
    available_ids = set(available.values())
    choices = []
    seen = set()
    for label, voice_id in VOICES.items():
        if voice_id in available_ids:
            choices.append(label)
            seen.add(voice_id)
    for name, voice_id in available.items():
        if voice_id not in seen:
            choices.append(f"{name} ({voice_id})")
            seen.add(voice_id)
    if not choices:
        choices = list(VOICES.keys())
    return choices


def _voice_id_for_choice(choice):
    if choice in VOICES:
        return VOICES[choice]
    if choice and "(" in choice and choice.rstrip().endswith(")"):
        inside = choice.rsplit("(", 1)[-1].rstrip(")")
        if inside.strip():
            return inside.strip()
    return ""


def _ensure_usable_voice(voice_id):
    """Return a voice ID this account can actually use, falling back gracefully."""
    available_ids = set(account_voices().values())
    if available_ids and voice_id not in available_ids:
        replacement = next(iter(available_ids))
        print(
            f"[ElevenLabs] Voice {voice_id} is not available on this account; using {replacement}.",
            flush=True,
        )
        return replacement
    return voice_id


def _resolve_speaker_voice(env_var, default_id):
    """Resolve one speaker's voice: env var override, then default, then account-usable."""
    override = os.getenv(env_var, "").strip()
    if not override:
        override = default_id
    return _ensure_usable_voice(override)


def _friendly_error(error):
    message = str(error)
    lowered = message.lower()
    if "quota_exceeded" in lowered or "credits remaining" in lowered or "exceeds your quota" in lowered:
        return (
            "ElevenLabs ran out of plan credits, so audio could not be generated. "
            "Top up credits in your ElevenLabs dashboard and try again."
        )
    if "paid_plan_required" in lowered or "payment_required" in lowered or "402" in lowered:
        return (
            "ElevenLabs can't use this voice on your plan (likely a library voice "
            "that needs a paid subscription). The app has switched to voices "
            "available on your account. You can also set HOST_VOICE_ID and "
            "EXPERT_VOICE_ID in .env to voice IDs you own."
        )
    return message


def _synthesize_text(client, text, voice_id, model_id="eleven_flash_v2_5"):
    return client.text_to_speech.convert(
        voice_id=voice_id,
        output_format="mp3_44100_128",
        text=text,
        model_id=model_id,
    )


def _concat_mp3(file_names, workdir, output_path):
    if not file_names:
        raise RuntimeError("No audio was generated to combine.")
    if len(file_names) == 1:
        shutil.copyfile(os.path.join(workdir, file_names[0]), output_path)
        return output_path
    import imageio_ffmpeg
    ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
    list_path = os.path.join(workdir, "concat.txt")
    with open(list_path, "w", encoding="utf-8") as f:
        for name in file_names:
            f.write(f"file '{name}'\n")
    result = subprocess.run(
        [ffmpeg, "-y", "-f", "concat", "-safe", "0", "-i", list_path, "-c", "copy", output_path],
        cwd=workdir,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0 or not os.path.exists(output_path):
        detail = (result.stderr or result.stdout or "")[-500:]
        raise RuntimeError(f"Failed to combine audio segments: {detail}")
    return output_path


def _audio_cache_path():
    global _audio_cache_dir
    if _audio_cache_dir is None:
        _audio_cache_dir = os.path.join(tempfile.gettempdir(), "podcast_generator_audio")
        os.makedirs(_audio_cache_dir, exist_ok=True)
    return _audio_cache_dir


def _audio_cache_store(key, source_path):
    cache_dir = _audio_cache_path()
    cached_path = os.path.join(cache_dir, key + ".mp3")
    shutil.copyfile(source_path, cached_path)
    _audio_cache_lru[key] = monotonic()
    while len(_audio_cache_lru) > _AUDIO_CACHE_MAX:
        _key, _used = _audio_cache_lru.popitem(last=False)
        try:
            os.remove(os.path.join(cache_dir, _key + ".mp3"))
        except OSError:
            pass
    return cached_path


def _synthesize_dialogue(dialogue, host_voice_id, expert_voice_id, progress, timings):
    client = _elevenlabs_client()
    payload = [(speaker, text.strip()) for speaker, text in dialogue if text and text.strip()]
    cache_key = hashlib.sha256(
        repr((payload, host_voice_id, expert_voice_id)).encode("utf-8")
    ).hexdigest()
    cached_path = os.path.join(_audio_cache_path(), cache_key + ".mp3")
    if os.path.exists(cached_path):
        print("[ElevenLabs] Reusing cached audio for this dialogue.", flush=True)
        return cached_path
    started_at = perf_counter()
    progress(0.68, desc="Synthesizing multi-voice narration…")
    with tempfile.TemporaryDirectory() as workdir:
        segment_names = []
        total_turns = len(payload)
        for index, (speaker, text) in enumerate(payload):
            voice_id = host_voice_id if speaker == "HOST" else expert_voice_id
            filename = f"segment_{index:03d}_{speaker.lower()}.mp3"
            response = _synthesize_text(client, text, voice_id)
            with open(os.path.join(workdir, filename), "wb") as f:
                for chunk in response:
                    f.write(chunk)
            segment_names.append(filename)
            progress(
                0.68 + 0.27 * (index + 1) / max(total_turns, 1),
                desc=f"{speaker.title()} turn {index + 1}/{total_turns} synthesized…",
            )
        audio_path = _concat_mp3(segment_names, workdir, "output.mp3")
    cached_path = _audio_cache_store(cache_key, audio_path)
    elapsed = perf_counter() - started_at
    print(f"[ElevenLabs] Combined {len(segment_names)} segments in {elapsed:.1f}s", flush=True)
    timings["audio"] = elapsed
    return cached_path


STUDIO_CSS = """
@import url('https://fonts.googleapis.com/css2?family=Outfit:wght@400;700&family=Plus+Jakarta+Sans:wght@400;700&display=swap');
body { background: #090e1a; font-family: 'Plus Jakarta Sans', sans-serif; }
.gradio-container {
    max-width: 1180px !important;
    margin: 0 auto !important;
    padding: 32px 20px !important;
    background: radial-gradient(ellipse at top right, #1c2240 0%, #090e1a 65%) !important;
    color-scheme: dark;
}
#studio-header { padding: 18px 4px 24px; text-align: center; }
#studio-header h1 {
    color: #f8fafc;
    font-size: clamp(2rem, 5vw, 3.25rem);
    line-height: 1.15;
    letter-spacing: -0.04em;
    margin: 12px 0;
    font-family: 'Outfit', sans-serif;
}
#studio-header p { color: #b8c4d9; font-size: 1.05rem; }
.studio-badge {
    display: inline-block;
    color: #c4b5fd;
    background: rgba(35, 30, 61, 0.6);
    backdrop-filter: blur(8px);
    border: 1px solid #66518b;
    border-radius: 999px;
    padding: 6px 12px;
    font-size: 0.75rem;
    font-weight: 700;
    letter-spacing: 0.12em;
    box-shadow: 0 0 10px rgba(139, 92, 246, 0.2);
}
.studio-card {
    background: rgba(17, 26, 43, 0.7) !important;
    backdrop-filter: blur(12px) !important;
    border: 1px solid rgba(139, 92, 246, 0.3) !important;
    border-radius: 18px !important;
    padding: 24px !important;
    box-shadow: 0 12px 28px #00000030, inset 0 0 20px rgba(139, 92, 246, 0.05) !important;
}
.studio-card h2 { color: #f1f5f9; font-size: 1.15rem; }
.studio-card p, #studio-footer p { color: #b8c4d9; }
#generate-button {
    min-height: 50px;
    border-radius: 12px;
    font-weight: 700;
    transition: transform 160ms ease, box-shadow 160ms ease;
}
#generate-button:hover {
    transform: translateY(-1px);
    box-shadow: 0 6px 22px #8b5cf640;
}
.gradio-container :is(button, input, textarea, a):focus-visible {
    outline: 3px solid #c4b5fd !important;
    outline-offset: 3px;
}
#summary-panel textarea { line-height: 1.75; }
#studio-footer { text-align: center; padding-top: 16px; }
@media (max-width: 640px) {
    .gradio-container { padding: 16px 12px !important; }
    .studio-card { padding: 16px !important; }
}
@media (prefers-reduced-motion: reduce) {
    #generate-button { transition: none; }
    #generate-button:hover { transform: none; }
}
"""

# Set both palettes so the studio stays dark regardless of browser preference.
studio_theme = gr.themes.Soft(
    primary_hue="violet",
    neutral_hue="slate",
    font=["Segoe UI", "Arial", "sans-serif"],
).set(
    body_background_fill="#090e1a",
    body_background_fill_dark="#090e1a",
    body_text_color="#e2e8f0",
    body_text_color_dark="#e2e8f0",
    block_background_fill="#111a2b",
    block_background_fill_dark="#111a2b",
    block_border_color="#334155",
    block_border_color_dark="#334155",
    block_label_background_fill="#111a2b",
    block_label_background_fill_dark="#111a2b",
    block_label_text_color="#cbd5e1",
    block_label_text_color_dark="#cbd5e1",
    block_title_text_color="#f1f5f9",
    block_title_text_color_dark="#f1f5f9",
    input_background_fill="#0b1220",
    input_background_fill_dark="#0b1220",
    input_border_color="#475569",
    input_border_color_dark="#475569",
    input_placeholder_color="#94a3b8",
    input_placeholder_color_dark="#94a3b8",
    button_primary_background_fill="#15803d",
    button_primary_background_fill_dark="#15803d",
    button_primary_background_fill_hover="#166534",
    button_primary_background_fill_hover_dark="#166534",
    button_primary_text_color="#ffffff",
    button_primary_text_color_dark="#ffffff",
    button_secondary_background_fill="#1e293b",
    button_secondary_background_fill_dark="#1e293b",
    button_secondary_background_fill_hover="#334155",
    button_secondary_background_fill_hover_dark="#334155",
    button_secondary_text_color="#e2e8f0",
    button_secondary_text_color_dark="#e2e8f0",
)


def generate_single(url, reuse_summary, voice_name, narration_chars, autoplay, progress=gr.Progress()):
    started_at = perf_counter()
    summary = None
    timings = {}
    try:
        if not url or not url.strip():
            return None, gr.Audio(value=None), "Enter a blog URL to get started."

        summary = summarize_blog(
            url.strip(),
            use_cache=reuse_summary,
            progress=lambda value, message: progress(value, desc=message),
            timings=timings,
        )

        progress(0.65, desc="Generating narration with ElevenLabs…")
        audio_started_at = perf_counter()
        print("[ElevenLabs] Starting narration…", flush=True)
        client = _elevenlabs_client()
        selected_voice_id = _voice_id_for_choice(voice_name) or DEFAULT_HOST_VOICE_ID
        selected_voice_id = _ensure_usable_voice(selected_voice_id)
        response = _synthesize_text(client, summary[:int(narration_chars)], selected_voice_id)

        audio_path = "output.mp3"
        with open(audio_path, "wb") as f:
            for chunk in response:
                f.write(chunk)

        audio_elapsed = perf_counter() - audio_started_at
        print(f"[ElevenLabs] Audio saved after {audio_elapsed:.1f}s", flush=True)
        progress(1, desc="Your podcast is ready")
        elapsed = perf_counter() - started_at
        summary_status = (
            "Summary cache hit"
            if timings["cache_hit"]
            else f"Firecrawl {timings['firecrawl']:.1f}s · Gemini {timings['gemini']:.1f}s"
        )
        return (
            summary,
            gr.Audio(value=audio_path, autoplay=autoplay),
            f"Ready in {elapsed:.1f}s · {summary_status} · Audio {audio_elapsed:.1f}s",
        )
    except Exception as e:
        elapsed = perf_counter() - started_at
        print(f"Error after {elapsed:.1f}s:", str(e), flush=True)
        return summary, gr.Audio(value=None), f"Error after {elapsed:.1f}s: {_friendly_error(e)}"


def generate_multi(url, reuse_summary, autoplay, progress=gr.Progress()):
    started_at = perf_counter()
    script_text = None
    timings = {}
    try:
        if not url or not url.strip():
            return None, gr.Audio(value=None), "Enter a blog URL to get started."

        script_text, dialogue = build_conversation(
            url.strip(),
            use_cache=reuse_summary,
            progress=lambda value, message: progress(value, desc=message),
            timings=timings,
        )

        host_voice_id = _resolve_speaker_voice("HOST_VOICE_ID", DEFAULT_HOST_VOICE_ID)
        expert_voice_id = _resolve_speaker_voice("EXPERT_VOICE_ID", DEFAULT_EXPERT_VOICE_ID)
        print(
            f"[ElevenLabs] Host voice={host_voice_id} · Expert voice={expert_voice_id}",
            flush=True,
        )

        audio_path = _synthesize_dialogue(dialogue, host_voice_id, expert_voice_id, progress, timings)

        progress(1, desc="Your podcast is ready")
        elapsed = perf_counter() - started_at
        if timings.get("cache_hit"):
            status = "Script cache hit"
        else:
            status = " · ".join([
                f"Firecrawl {timings['firecrawl']:.1f}s",
                f"Researcher {timings['researcher']:.1f}s",
                f"Host {timings['host']:.1f}s",
                f"Expert {timings['expert']:.1f}s",
                f"Audio {timings['audio']:.1f}s",
            ])
        return (
            script_text,
            gr.Audio(value=audio_path, autoplay=autoplay),
            f"Ready in {elapsed:.1f}s · {status}",
        )
    except Exception as e:
        elapsed = perf_counter() - started_at
        print(f"Error after {elapsed:.1f}s:", str(e), flush=True)
        return script_text, gr.Audio(value=None), f"Error after {elapsed:.1f}s: {_friendly_error(e)}"


def generate_podcast(url, mode, reuse_summary, voice_name, narration_chars, autoplay, progress=gr.Progress()):
    if mode == MULTI_AGENT_MODE:
        return generate_multi(url, reuse_summary, autoplay, progress)
    return generate_single(url, reuse_summary, voice_name, narration_chars, autoplay, progress)


def update_mode_visibility(mode):
    multi = mode == MULTI_AGENT_MODE
    return (
        gr.update(visible=not multi),
        gr.update(visible=not multi),
        gr.update(visible=multi),
        gr.update(label="Conversation script" if multi else "Blog summary"),
    )


with gr.Blocks(title="AI Podcast Studio", theme=studio_theme, css=STUDIO_CSS) as demo:
    gr.HTML(
        '<header id="studio-header">'
        '<div style="display: flex; gap: 8px; justify-content: center; margin-bottom: 16px; flex-wrap: wrap;">'
        '<span class="studio-badge">🟢 Studio Ready</span>'
        '<span class="studio-badge">⚡ Gemini Flash</span>'
        '<span class="studio-badge">🎙️ ElevenLabs Voices</span>'
        '<span class="studio-badge">🌐 Firecrawl Scraping</span>'
        '</div>'
        '<h1>Good reads. Great listening.</h1>'
        '<p>Turn a blog post into a clear summary and a narrated audio preview.</p>'
        '</header>'
    )

    with gr.Column(elem_classes=["studio-card"]):
        gr.Markdown("## Create your podcast")
        mode_selector = gr.Radio(
            label="Podcast Mode",
            choices=[SINGLE_VOICE_MODE, MULTI_AGENT_MODE],
            value=SINGLE_VOICE_MODE,
            info="Single Voice narrates one summary. Multi-Agent runs a Researcher + Host + Expert conversation.",
        )
        gr.Markdown("Paste a public article link, then generate. You can also press Enter.")
        url_input = gr.Textbox(
            label="Blog URL",
            placeholder="https://example.com/your-favourite-article",
            lines=1,
        )
        
        with gr.Row():
            voice_dropdown = gr.Dropdown(
                label="Narrator Voice",
                choices=_build_voice_choices(),
                value=_build_voice_choices()[0] if _build_voice_choices() else None,
                interactive=True
            )
            narration_slider = gr.Slider(
                label="Narration Length (Characters)",
                minimum=300,
                maximum=1500,
                value=700,
                step=50,
                info="~1-2 minutes of audio"
            )
        multi_mode_note = gr.Markdown(
            "**Multi-Agent mode:** a Host and an Expert discuss the article from "
            "Researcher-extracted facts. Their voices come from `HOST_VOICE_ID` and "
            "`EXPERT_VOICE_ID` in `.env` (defaults: George + Alice).",
            visible=False,
        )

        with gr.Row():
            reuse_summary = gr.Checkbox(
                label="Reuse a recent summary for this URL",
                value=True,
                info="Cached for up to one hour while the app runs.",
            )
            autoplay_toggle = gr.Checkbox(
                label="Autoplay on completion",
                value=False
            )
            
        generate_btn = gr.Button(
            "Generate podcast", variant="primary", elem_id="generate-button"
        )
        status_output = gr.Textbox(
            label="Generation status",
            value="Ready when you are. Add an article link above.",
            lines=2,
            interactive=False,
        )

    with gr.Row(equal_height=False):
        with gr.Column(scale=3, min_width=280, elem_classes=["studio-card"]):
            gr.Markdown("## Your article, summarized")
            summary_output = gr.Textbox(
                label="Blog summary",
                placeholder="Your summary will appear here after generation.",
                lines=14,
                max_lines=24,
                interactive=False,
                show_copy_button=True,
                elem_id="summary-panel",
            )
        with gr.Column(scale=2, min_width=280, elem_classes=["studio-card"]):
            gr.Markdown("## Listen to your podcast")
            audio_output = gr.Audio(label="Podcast audio", interactive=False, show_download_button=True)
            gr.Markdown(
                "Narration covers the selected length of your summary. "
                "Use the player to listen or download the MP3."
            )
            gr.Markdown(
                "### While you wait\n"
                "The app reads the article, summarizes it, and generates speech. "
                "Long articles and busy services can take several minutes. "
                "Progress shows processing stages, not estimated completion time."
            )

    gr.Markdown(
        "Powered by Gemini · Firecrawl · ElevenLabs",
        elem_id="studio-footer",
    )

    mode_selector.change(
        fn=update_mode_visibility,
        inputs=[mode_selector],
        outputs=[voice_dropdown, narration_slider, multi_mode_note, summary_output],
        queue=False,
    )

    for event in (generate_btn.click, url_input.submit):
        event(
            fn=generate_podcast,
            inputs=[url_input, mode_selector, reuse_summary, voice_dropdown, narration_slider, autoplay_toggle],
            outputs=[summary_output, audio_output, status_output],
            concurrency_limit=1,
            concurrency_id="podcast-generation",
            show_progress="full",
        )

if __name__ == "__main__":
    demo.queue().launch(server_name="0.0.0.0", server_port=7860,
                        auth=("devmode", "testdeployment8721"))
