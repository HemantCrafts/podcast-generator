import os
import re
from time import perf_counter
from urllib.parse import quote, urldefrag, urlparse

from dotenv import load_dotenv

from blog_summarizer import (
    GEMINI_TIMEOUT_RETRIES,
    GEMINI_TIMEOUT_SECONDS,
    MAX_ARTICLE_CHARS,
    _get_cached,
    _post_json,
    _scrape_article,
    _store_cached,
)

load_dotenv()

DEFAULT_MODEL = "gemini/gemini-3.6-flash"
CONVERSATION_CACHE_SUFFIX = "conversation"

RESEARCHER_INSTRUCTIONS = (
    "You are a podcast research analyst. Extract the key facts, statistics, "
    "arguments, examples, and important details from the supplied article. "
    "Organize them into concise bullet points so they are easy to reference. "
    "Preserve who, what, when, where, and why, along with any meaningful numbers "
    "or direct quotes. Do not invent facts and do not add commentary. "
    "Output plain text with no markdown, links, or URLs."
)

HOST_INSTRUCTIONS = (
    "You are the host of an engaging podcast interview for a knowledgeable expert guest. "
    "Strictly use the supplied research notes as your only source material; do not invent facts. "
    "Produce a warm spoken introduction (under 40 words) that frames the topic and why it matters, "
    "then exactly 3 natural, curious questions (under 30 words each) your expert can answer from the notes. "
    "End with a short outro (under 25 words). Format your reply exactly with these labels, one label per line:\n"
    "INTRO: <host intro>\n"
    "QUESTION 1: <question>\n"
    "QUESTION 2: <question>\n"
    "QUESTION 3: <question>\n"
    "OUTRO: <host outro>\n"
    "Do not include your own answers, markdown, links, or URLs."
)

EXPERT_INSTRUCTIONS = (
    "You are an expert guest on a podcast. The host has asked you a series of questions "
    "about the supplied topic. Answer each question in natural spoken language, one short "
    "spoken section per question, 50-70 words each. Explain concepts clearly, give one or two "
    "concrete examples from the research notes, and add useful perspective. Sound like a person "
    "talking, not an essay: use short sentences and plain words. Stay strictly within the "
    "research notes and do not invent facts. Format your reply exactly with these labels, "
    "one label per line:\n"
    "ANSWER 1: <your answer>\n"
    "ANSWER 2: <your answer>\n"
    "ANSWER 3: <your answer>\n"
    "If there are more answers than questions, stop at the last question. "
    "Do not use markdown, links, or URLs."
)

MAX_HOST_TURN_CHARS = 320
MAX_EXPERT_TURN_CHARS = 640


def _normalize_model(model):
    return model.strip().removeprefix("gemini/").removeprefix("models/")


def _require_keys():
    firecrawl_key = os.getenv("FIRECRAWL_API_KEY", "").strip()
    gemini_key = os.getenv("GEMINI_API_KEY", "").strip()
    if not firecrawl_key or not gemini_key:
        raise ValueError("FIRECRAWL_API_KEY and GEMINI_API_KEY must both be configured.")
    return firecrawl_key, gemini_key


def _generate_agent_reply(system_prompt, user_text, model, api_key, *, max_output_tokens=8192):
    url = ("https://generativelanguage.googleapis.com/v1beta/models/"
           + quote(model, safe="") + ":generateContent")
    result = _post_json(
        url,
        {
            "systemInstruction": {"parts": [{"text": system_prompt}]},
            "contents": [{"role": "user", "parts": [{"text": user_text}]}],
            "generationConfig": {"temperature": 0.8, "maxOutputTokens": max_output_tokens},
        },
        {"x-goog-api-key": api_key},
        stage="Gemini",
        timeout=GEMINI_TIMEOUT_SECONDS,
        retries=GEMINI_TIMEOUT_RETRIES,
    )
    candidates = result.get("candidates") or []
    if not candidates:
        raise RuntimeError("Gemini returned no agent output. Try a different article.")
    candidate = candidates[0]
    if candidate.get("finishReason") != "STOP":
        raise RuntimeError("Gemini did not complete the agent output. Please try again.")
    parts = (candidate.get("content") or {}).get("parts") or []
    text = "".join(
        part["text"] for part in parts
        if isinstance(part.get("text"), str) and not part.get("thought")
    ).strip()
    if not text:
        raise RuntimeError("Gemini returned an empty agent output. Try a different article.")
    return text


_SECTION_LINE = re.compile(
    r"^(?:HOST\s*)?(INTRO|OUTRO|QUESTION|ANSWER)\s*(?:(\d+))?\s*[:.)-]+?\s*(.*)$",
    re.IGNORECASE,
)
_SPEAKER_LINE = re.compile(r"^(HOST|EXPERT)\s*[:.]\s*(.*)$", re.IGNORECASE)


def _parse_sections(text):
    """Parse labelled sections into [(kind, number, content_lines)]."""
    sections = []
    current = None
    for raw in (text or "").splitlines():
        line = raw.strip()
        if not line:
            continue
        label_match = _SECTION_LINE.match(line)
        speaker_match = None
        if not label_match:
            speaker_match = _SPEAKER_LINE.match(line)
        if label_match or speaker_match:
            if current is not None:
                sections.append(current)
            if label_match:
                kind = label_match.group(1).upper()
                number = label_match.group(2)
                content = label_match.group(3)
            else:
                kind = speaker_match.group(1).upper()
                number = None
                content = speaker_match.group(2)
            current = [kind, number, [content] if content else []]
        elif current is not None:
            current[2].append(line)
        else:
            current = ["INTRO", None, [line]]
    if current is not None:
        sections.append(current)
    return sections


def _join(section):
    return " ".join(" ".join(section[2]).split())


def _split_dialogue(text):
    """Turn a labelled script into [(speaker, spoken_text)] turns."""
    sections = _parse_sections(text)
    intros = [s for s in sections if s[0] == "INTRO"]
    questions = [s for s in sections if s[0] == "QUESTION"]
    answers = [s for s in sections if s[0] == "ANSWER"]
    outros = [s for s in sections if s[0] == "OUTRO"]

    speaker_sections = [s for s in sections if s[0] in ("HOST", "EXPERT")]
    if not questions and speaker_sections:
        dialogue = []
        for section in speaker_sections:
            text = _join(section)
            if text:
                dialogue.append((section[0], text))
        return dialogue

    if not questions:
        intro = " ".join(_join(s) for s in intros) or "Welcome to the show."
        outro = " ".join(_join(s) for s in outros) or "Thanks for listening. See you next time."
        expert = " ".join(_join(s) for s in answers)
        dialogue = [("HOST", intro)]
        if expert:
            dialogue.append(("EXPERT", expert))
        dialogue.append(("HOST", outro))
        return dialogue
    dialogue = []
    if intros:
        dialogue.append(("HOST", _join(intros[0])))
    for index, question in enumerate(questions):
        question_text = _join(question)
        if question_text:
            dialogue.append(("HOST", question_text))
        answer = answers[index] if index < len(answers) else None
        answer_text = _join(answer) if answer else ""
        if answer_text:
            dialogue.append(("EXPERT", answer_text))
    if outros:
        outro_text = _join(outros[-1])
        if outro_text:
            dialogue.append(("HOST", outro_text))
    return dialogue


def format_script(dialogue):
    return "\n\n".join(f"{speaker}: {text}" for speaker, text in dialogue)


def _trim_turn(text, limit):
    text = " ".join(text.split())
    if len(text) <= limit:
        return text
    piece = text[:limit]
    cut = piece.rfind(" ")
    return piece[:cut].rstrip() + "…" if cut > limit * 0.6 else piece.rstrip() + "…"


def trim_dialogue(dialogue):
    """Enforce per-turn character caps so audio stays short and cheap."""
    trimmed = []
    for speaker, text in dialogue:
        limit = MAX_HOST_TURN_CHARS if speaker == "HOST" else MAX_EXPERT_TURN_CHARS
        text = _trim_turn(text, limit)
        if text:
            trimmed.append((speaker, text))
    return trimmed


def build_conversation(url, *, use_cache=True, progress=None, timings=None):
    """Scrape one article and run Researcher, Host, and Expert agents.

    Returns a (script_text, dialogue) tuple where dialogue is an ordered list
    of (speaker, text) turns with HOST and EXPERT speakers.
    """
    timings = timings if timings is not None else {}
    timings.update(firecrawl=0.0, researcher=0.0, host=0.0, expert=0.0)
    if not isinstance(url, str):
        raise ValueError("Enter a complete article URL.")
    url = urldefrag(url.strip())[0]
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        raise ValueError("Enter an article URL starting with http:// or https://.")

    model = _normalize_model(os.getenv("GEMINI_MODEL", DEFAULT_MODEL))
    if not model:
        raise ValueError("GEMINI_MODEL must name a model.")
    firecrawl_key, gemini_key = _require_keys()

    cache_key = (url, model, CONVERSATION_CACHE_SUFFIX)
    if use_cache:
        cached = _get_cached(cache_key)
        if cached is not None:
            timings["cache_hit"] = True
            print("[Multi-agent cache] Reusing conversation; skipping agents.", flush=True)
            if progress:
                progress(0.65, "Reusing a recent conversation…")
            script_text, dialogue = cached
            return script_text, dialogue

    def timed_call(stage, function, *args):
        started_at = perf_counter()
        print(f"[{stage}] Starting agent request…", flush=True)
        try:
            return function(*args)
        finally:
            timings[stage] = perf_counter() - started_at
            print(f"[{stage}] Request ended after {timings[stage]:.1f}s", flush=True)

    if progress:
        progress(0.02, "Fetching article text with Firecrawl…")
    article = timed_call("firecrawl", _scrape_article, url, firecrawl_key)

    if progress:
        progress(0.18, "Researcher agent is extracting key facts…")
    research_notes = timed_call(
        "researcher", _generate_agent_reply,
        RESEARCHER_INSTRUCTIONS, article[:MAX_ARTICLE_CHARS], model, gemini_key,
    )

    if progress:
        progress(0.38, "Host agent is writing the interview…")
    host_script = timed_call(
        "host", _generate_agent_reply,
        HOST_INSTRUCTIONS, research_notes, model, gemini_key,
    )

    if progress:
        progress(0.55, "Expert agent is preparing answers…")
    expert_script = timed_call(
        "expert", _generate_agent_reply,
        EXPERT_INSTRUCTIONS, research_notes + "\n\n" + host_script, model, gemini_key,
    )

    dialogue = trim_dialogue(_split_dialogue(host_script + "\n" + expert_script))
    if len(dialogue) < 2:
        raise RuntimeError("Conversation assembly produced no dialogue. Please try again.")
    script_text = format_script(dialogue)
    _store_cached(cache_key, (script_text, dialogue))
    return script_text, dialogue


if __name__ == "__main__":
    script_text, _dialogue = build_conversation(input("Enter blog URL: "))
    with open("conversation_script.txt", "w", encoding="utf-8") as output:
        output.write(script_text)
    print("\n=== CONVERSATION SCRIPT ===\n", script_text)