# Modernize UI, Styling, Voice Selection, and Audio Controls

Update `app.py` with a modernized studio design, voice selection, narration length slider, audio playback controls, and generation telemetry metrics.

## Proposed Changes

### UI & Audio Studio Controls (`app.py`)

#### [MODIFY] [app.py](file:///c:/Users/dkohl/OneDrive/Desktop/Projects/podcast-generator/app.py)
- **ElevenLabs Voice Selection**:
  - Add a curated dictionary of popular ElevenLabs voices with descriptive labels (Voice name, tone, accent):
    - *George — Warm & Captivating Storyteller (British)* (Default)
    - *Rachel — Calm & Professional Narrator (American)*
    - *Adam — Deep & Engaging Voice (American)*
    - *Sarah — Soft, Warm & Expressive (American)*
    - *Antoni — Well-Rounded & Friendly (American)*
    - *Domi — Energetic & Confident (American)*
    - *Arnold — Crisp & Articulate (American)*
  - Pass the selected voice ID into `client.text_to_speech.convert(voice_id=...)`.

- **Narration Length & Audio Controls**:
  - Add a slider for narration character limit (300 to 1,500 characters, default 700) with a readout of estimated spoken duration (~1–2 minutes).
  - Add an optional "Autoplay on completion" checkbox toggle for seamless listening.
  - Enable `show_download_button=True` on `gr.Audio` with clean audio player styling.

- **Theme & Visual Aesthetics**:
  - Elevate the theme to an obsidian-violet studio palette using Google Fonts (`Plus Jakarta Sans` and `Outfit`).
  - Introduce glassmorphism card styling (`backdrop-filter: blur(12px)`, subtle glowing neon borders, elevation drop shadows).
  - Add a hero banner with status indicator badge ("🟢 Studio Ready"), capability pills (*⚡ Gemini Flash*, *🎙️ ElevenLabs Voices*, *🌐 Firecrawl Scraping*).
  - Add timing telemetry pill badges to show extraction, summary, and audio generation durations.
  - Enhance focus rings, hover micro-animations, and smooth transitions for button clicks.
  - Ensure responsive layout adjustments for small screens.

- **Backend Integration**:
  - Update `process_url` signature to accept `voice`, `narration_chars`, `autoplay`, and pass them to ElevenLabs TTS.
  - Ensure graceful fallbacks and clear error handling.

## Verification Plan

### Automated Tests
- Run existing unit test suite to verify no regressions in summarization logic:
  ```powershell
  python -m unittest test_blog_summarizer.py
  ```
- Run Python syntax and import check on `app.py`:
  ```powershell
  python -c "import app; print('App syntax and structure verified successfully')"
  ```

### Manual / Browser Verification
- Launch the application locally:
  ```powershell
  python app.py
  ```
- Use the browser agent or test script to verify:
  - Page renders with new glassmorphic dark theme, fonts, and hero section.
  - Voice selector dropdown contains all options with George selected by default.
  - Narration slider works across the 300–1500 range.
  - Audio output component displays download and playback controls.
