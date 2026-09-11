import os
from time import perf_counter

import gradio as gr
from dotenv import load_dotenv
from elevenlabs import ElevenLabs

from blog_summarizer import summarize_blog

load_dotenv()


STUDIO_CSS = """
body { background: #090e1a; }
.gradio-container {
    max-width: 1180px !important;
    margin: 0 auto !important;
    padding: 32px 20px !important;
    background: radial-gradient(ellipse at top right, #1c2240 0%, #090e1a 65%) !important;
    color-scheme: dark;
}
#studio-header { padding: 18px 4px 24px; }
#studio-header h1 {
    color: #f8fafc;
    font-size: clamp(2rem, 5vw, 3.25rem);
    line-height: 1.15;
    letter-spacing: -0.04em;
    margin: 12px 0;
}
#studio-header p { color: #b8c4d9; font-size: 1.05rem; }
.studio-badge {
    display: inline-block;
    color: #c4b5fd;
    background: #231e3d;
    border: 1px solid #66518b;
    border-radius: 999px;
    padding: 6px 12px;
    font-size: 0.75rem;
    font-weight: 700;
    letter-spacing: 0.12em;
}
.studio-card {
    background: #111a2b !important;
    border: 1px solid #334155 !important;
    border-radius: 18px !important;
    padding: 24px !important;
    box-shadow: 0 12px 28px #00000026;
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


def process_url(url, progress=gr.Progress()):
    started_at = perf_counter()
    try:
        if not url or not url.strip():
            return None, None, "Enter a blog URL to get started."

        progress(0.05, desc="Reading the article and generating your summary…")
        summary = summarize_blog(url.strip())
        print("-" * 40)
        print("Blog Summary:", summary)
        print("-" * 40)

        progress(0.65, desc="Generating narration with ElevenLabs…")
        api_key = os.environ.get("ELEVENLABS_API_KEY")
        client = ElevenLabs(api_key=api_key)
        response = client.text_to_speech.convert(
            voice_id="JBFqnCBsd6RMkjVDRZzb",
            output_format="mp3_44100_128",
            text=summary[:700],  # Preserve the longer narration limit.
            model_id="eleven_flash_v2_5",
        )

        audio_path = "output.mp3"
        with open(audio_path, "wb") as f:
            for chunk in response:
                f.write(chunk)

        progress(1, desc="Your podcast is ready")
        elapsed = perf_counter() - started_at
        return summary, audio_path, f"Podcast ready! Generated in {elapsed:.0f} seconds."
    except Exception as e:
        print("Error processing URL:", str(e))
        return None, None, f"Error: {str(e)}"


with gr.Blocks(title="AI Podcast Studio", theme=studio_theme, css=STUDIO_CSS) as demo:
    gr.HTML(
        '<header id="studio-header">'
        '<span class="studio-badge">AI PODCAST STUDIO</span>'
        '<h1>Good reads. Great listening.</h1>'
        '<p>Turn a blog post into a clear summary and a narrated audio preview.</p>'
        '</header>'
    )

    with gr.Column(elem_classes=["studio-card"]):
        gr.Markdown("## Create your podcast")
        gr.Markdown("Paste a public article link, then generate. You can also press Enter.")
        url_input = gr.Textbox(
            label="Blog URL",
            placeholder="https://example.com/your-favourite-article",
            lines=1,
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
            audio_output = gr.Audio(label="Podcast audio", interactive=False)
            gr.Markdown(
                "Narration covers the **first 700 characters** of your summary. "
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

    for event in (generate_btn.click, url_input.submit):
        event(
            fn=process_url,
            inputs=[url_input],
            outputs=[summary_output, audio_output, status_output],
            concurrency_limit=1,
            concurrency_id="podcast-generation",
            show_progress="full",
        )

if __name__ == "__main__":
    demo.queue().launch(server_name="0.0.0.0", server_port=7860,
                        auth=("devmode", "testdeployment8721"))
