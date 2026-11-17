"""Download the two MMS-TTS models once (needs internet). After this the app runs offline.

    python download_models.py
"""
from pathlib import Path

from transformers import AutoTokenizer, VitsModel

MODEL_DIR = Path(__file__).resolve().parent / "models"
MODELS = {"English": "facebook/mms-tts-eng", "Tagalog": "facebook/mms-tts-tgl"}

for label, name in MODELS.items():
    print(f"Downloading {label}: {name} ...")
    AutoTokenizer.from_pretrained(name, cache_dir=str(MODEL_DIR))
    VitsModel.from_pretrained(name, cache_dir=str(MODEL_DIR))
print(f"\nDone. Models cached in {MODEL_DIR}\nYou can now run:  python app.py")
