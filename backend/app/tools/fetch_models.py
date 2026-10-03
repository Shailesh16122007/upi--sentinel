"""One-time download of the speech-to-text model (needs internet once).

    python -m app.tools.fetch_models
"""
from app.services.audio import stt

if __name__ == "__main__":
    m = stt._load()
    print("Speech-to-text ready." if m else f"Failed: {stt.status()['error']}")
