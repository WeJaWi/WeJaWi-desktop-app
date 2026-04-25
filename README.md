# WeJaWi Desktop App

A cross-platform desktop application for video content creators. Built with PyQt5, it bundles 18 tools into a single sidebar-driven UI — covering everything from transcription and captions to AI image generation, motion graphics, and browser automation.

## Tools

| Tool | Description |
|---|---|
| 🌐 Browser | Built-in low-RAM web browser with pinned links |
| 🎙 Transcribe | Speech-to-text via Whisper (faster-whisper / mlx-whisper on Apple Silicon) |
| 💬 Captions | Generate and burn subtitles into video |
| ✂ Stitch Up | Concatenate video clips |
| 🎞 Motion Graphics | GSAP-powered animated text overlays with TTS narration |
| 🔁 Convert | Video/audio format conversion via FFmpeg |
| 🎚 Sound Waves | Render audio waveform overlays onto video |
| 🎬 Scenes + Images | AI image generation (OpenAI, WaveSpeed, FAL, Freepik) |
| 📼 Footage | Search and download stock footage (Pexels, Pixabay, Unsplash) |
| ✍ Script Writer | LLM-powered script drafting |
| 🌐 Translate | Text translation via Argos Translate |
| 💫 Channel Identity | YouTube channel analytics and identity tools |
| 📋 Jobs Center | Background job queue with progress tracking |
| 🦁 Brave Automation | Automate the Brave browser |
| 🖱 Mouse Automation | Record and replay mouse/keyboard sequences |
| ⚙ Automation Editor | Visual editor for automation workflows |
| 🔑 API Storage | Securely store API keys used across tools |
| … More | Additional utilities |

## Requirements

- Python 3.10+
- FFmpeg in PATH

## Installation

```bash
git clone https://github.com/WeJaWi/WeJaWi-desktop-app.git
cd WeJaWi-desktop-app
pip install -r requirements.txt
python app.py
```

> **Apple Silicon (M1/M2/M3):** `mlx-whisper` is installed automatically for faster on-device transcription.

## Configuration

API keys (OpenAI, xAI, Freepik, Pexels, etc.) are stored locally in:

| Platform | Path |
|---|---|
| macOS | `~/Library/Application Support/WeJaWi/api_keys.json` |
| Windows | `%APPDATA%\WeJaWi\api_keys.json` |
| Linux | `~/.config/wejawi/api_keys.json` |

Enter keys through the **API Storage** tool in the sidebar — never commit them to source control.

## Environment Variables

Optional overrides for LLM models:

```
WEJAWI_OPENAI_MODEL      (default: gpt-4o-mini)
WEJAWI_XAI_MODEL         (default: grok-3)
WEJAWI_ANTHROPIC_MODEL   (default: claude-sonnet-4-6)
WEJAWI_KIMI_MODEL        (default: moonshot-v1-32k)
WEJAWI_YT_COOKIES        path to a Netscape-format cookie file for yt-dlp
```

## License

See [LICENSE](LICENSE).
