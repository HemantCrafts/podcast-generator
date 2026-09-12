# 🎙️ AI Podcast Generator

An intelligent application that transforms blog posts into engaging podcast episodes using AI agents and text-to-speech technology.


## 📋 Overview

This application uses CrewAI agents powered by Google's Gemini 2.0 Flash to scrape and summarize blog content, then converts the summary into high-quality audio using ElevenLabs text-to-speech technology.

## ✨ Features

- 🤖 **AI-Powered Summarization**: Uses CrewAI agents with Gemini 2.0 Flash LLM
- 🌐 **Web Scraping**: Extracts content from any blog URL using Firecrawl
- 🎵 **Text-to-Speech**: Converts summaries to natural-sounding audio with ElevenLabs
- 🗣️ **Multi-Agent Podcast Mode**: Researcher → Host + Expert conversational podcasts with two distinct ElevenLabs voices combined into one MP3
- 🖥️ **User-Friendly Interface**: Built with Gradio for easy interaction
- 🔒 **Secure Access**: Password-protected interface
- 🐳 **Docker Support**: Containerized for easy deployment

## 🛠️ Tech Stack

- **Python 3.13**
- **CrewAI**: Multi-agent AI framework
- **Google Gemini 2.0 Flash**: Large Language Model
- **ElevenLabs**: Text-to-speech API
- **Firecrawl**: Web scraping tool
- **Gradio**: Web UI framework
- **Docker**: Containerization

## 📦 Installation

### Prerequisites

- Python 3.13+
- Docker (optional, for containerized deployment)
- API Keys for:
  - Google Gemini AI
  - Firecrawl
  - ElevenLabs

### Local Setup

1. **Clone the repository**

   ```bash
   git clone https://github.com/HemantCrafts/podcast-generator
   cd podcast-generator
   ```

2. **Create a virtual environment**

   ```bash
   python -m venv .venv
   ```

3. **Activate the virtual environment**

   On Windows (PowerShell):

   ```powershell
   .\.venv\Scripts\Activate.ps1
   ```

   On macOS/Linux:

   ```bash
   source .venv/bin/activate
   ```

4. **Install dependencies**

   ```bash
   pip install --upgrade pip
   pip install -r requirements.txt
   ```

5. **Set up environment variables**

   Create a `.env` file in the project root:

   ```env
   GEMINI_API_KEY=your_gemini_api_key_here
   FIRECRAWL_API_KEY=your_firecrawl_api_key_here
   ELEVENLABS_API_KEY=your_elevenlabs_api_key_here

   # Optional: multi-agent podcast voices (defaults to George + Alice if unset)
   HOST_VOICE_ID=your_elevenlabs_host_voice_id
   EXPERT_VOICE_ID=your_elevenlabs_expert_voice_id
   ```

   > Note: voices are resolved against the voices available on your ElevenLabs account when possible, so the app avoids `paid_plan_required` (402) errors on free plans. Library-only voices such as Rachel require a paid subscription; if you see a 402, switch to a premade voice you own or set the voice IDs above to your own voice IDs.

6. **Run the application**

   ```bash
   python app.py
   ```

7. **Access the application**
   - Open your browser and go to: `http://localhost:7860`
   - Login credentials:
     - Username: `devmode`
     - Password: `testdeployment8721`

## 🐳 Docker Deployment

### Build the Docker image

```bash
docker build -t ai-podcast-generator .
```

### Run the container

```bash
docker run -it -p 7860:7860 --env-file .env ai-podcast-generator
```

Access at: `http://localhost:7860`

## 📝 Usage

1. Open the application in your browser
2. Enter the credentials (username: `devmode`, password: `testdeployment8721`)
3. Paste a blog URL into the input field
4. Choose a podcast mode:
   - **Single Voice Podcast**: pick a narrator voice and narration length, then generate. This is the original workflow.
   - **Multi-Agent Podcast**: a Researcher extracts facts, a Host writes questions, and an Expert answers them. Each speaker is voiced by a different ElevenLabs voice and the audio is combined into one MP3.
5. Click "Generate Podcast"
6. Wait for the AI agents to scrape, summarize, and generate audio
7. Listen to the generated podcast audio and view the text

## 🏗️ Project Structure

```
Podcast Generator/
├── app.py                 # Main Gradio application (both podcast modes)
├── blog_summarizer.py     # Single-voice scrape + summarization via Gemini
├── multi_agent.py         # Multi-agent conversation pipeline (Researcher/Host/Expert)
├── test_blog_summarizer.py # Unit tests for single-voice mode
├── test_multi_agent.py    # Unit tests for multi-agent mode
├── requirements.txt       # Python dependencies
├── Dockerfile            # Docker configuration
├── .dockerignore         # Docker ignore rules
├── .gitignore           # Git ignore rules
├── .env                 # Environment variables (not in git)
└── README.md            # This file
```

## 🤖 How It Works

### Single Voice Podcast

1. **Blog Scraper Agent**:

   - Uses Firecrawl to extract main content from blog URLs
   - Filters out navigation, ads, and non-essential elements

2. **Blog Summarizer Agent**:

   - Analyzes the scraped content
   - Creates a concise 500-700 word summary
   - Formats content for podcast delivery

3. **Text-to-Speech**:
   - Converts the summary to audio using ElevenLabs
   - Uses high-quality voice synthesis (eleven_flash_v2_5)
   - Outputs in MP3 format (44.1kHz, 128kbps)

### Multi-Agent Podcast

1. **Firecrawl Scrape**: extracts the article text (same step as single voice)
2. **Researcher Agent**: pulls out the key facts, statistics, examples, and arguments into bullet-point research notes
3. **Host Agent**: writes a spoken intro, a series of natural interview questions, and an outro from the research notes
4. **Expert Agent**: answers each question conversationally, explaining concepts and adding examples and perspective
5. **Dialogue Assembly**: turns the labelled agent output into an interleaved `HOST:` / `EXPERT:` script
6. **Multi-Voice Text-to-Speech**: each `HOST` line is spoken with `HOST_VOICE_ID` and each `EXPERT` line with `EXPERT_VOICE_ID` using ElevenLabs
7. **Audio Combination**: all spoken segments are merged into one continuous MP3 with ffmpeg (bundled via `imageio-ffmpeg`)

The conversation text is cached per URL for up to one hour, so repeating a request skips the agent calls.

## 🔑 API Keys Setup

### Google Gemini API

1. Visit [Google AI Studio](https://makersuite.google.com/app/apikey)
2. Create a new API key
3. Add to `.env` as `GEMINI_API_KEY`

### Firecrawl API

1. Visit [Firecrawl](https://firecrawl.dev/)
2. Sign up and get your API key
3. Add to `.env` as `FIRECRAWL_API_KEY`

### ElevenLabs API

1. Visit [ElevenLabs](https://elevenlabs.io/)
2. Create an account and get your API key
3. Add to `.env` as `ELEVENLABS_API_KEY`

## 🚀 Deployment

To deploy your own:

1. Fork this repository
2. Create a new Space on Hugging Face
3. Connect your repository
4. Add your API keys as Space secrets
5. Deploy!

## 🤝 Contributing

Contributions are welcome! Please feel free to submit a Pull Request.

## 📄 License

This project is open source and available under the MIT License.

## 👤 Author

**Hemant**

- GitHub: [@HemantCrafts](https://github.com/HemantCrafts)
- Hugging Face: [@Hemantkohli18](https://huggingface.co/Hemantkohli18)
- GitHub Repo: (https://github.com/HemantCrafts/podcast-generator)

## 🙏 Acknowledgments

- [CrewAI](https://www.crewai.com/) - Multi-agent AI framework
- [Google Gemini](https://deepmind.google/technologies/gemini/) - Large Language Model
- [ElevenLabs](https://elevenlabs.io/) - Text-to-speech API
- [Firecrawl](https://firecrawl.dev/) - Web scraping tool
- [Gradio](https://gradio.app/) - UI framework


---
