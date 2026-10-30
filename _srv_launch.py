
import os
from dotenv import load_dotenv
load_dotenv()
os.environ.setdefault("ENKRIPSIH_PASSWORD", "npg_z25gJGferdMK")
os.environ.setdefault("ENKRIPSIH_KEYBCA_SECRET", "ugCC-4DHQ8fXxcAJ7hkO17TWkp2oi3-s6AUc1GVzf0w")
os.environ.setdefault("ENKRIPSIH_DB_PASSPHRASE", "muhammadakhdaan2005")
from backend.main import app
import uvicorn
uvicorn.run(app, host="127.0.0.1", port=8000, log_level="error")
