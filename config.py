import os
import glob
from pathlib import Path
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent

# Load .env from parent directories
for p in [BASE_DIR, BASE_DIR.parent, BASE_DIR.parent.parent]:
    env_path = p / ".env"
    if env_path.exists():
        load_dotenv(env_path)
        break

# API ID and Hash
API_ID = os.getenv("API_ID")
if API_ID:
    API_ID = int(API_ID)
else:
    API_ID = 

API_HASH = os.getenv("API_HASH", "")


def get_latest_session():
    """Retrieve the path to the newest Telethon session file.
    Keeps only the 20 most recent sessions to save space."""
    # List all session files
    session_files = glob.glob(str(BASE_DIR / "session_*.session"))
    
    # Also include the base session.session if it exists
    base_session = BASE_DIR / "session.session"
    if base_session.exists():
        session_files.append(str(base_session))
        
    if not session_files:
        return str(BASE_DIR / "session")
        
    # Sort session files by modification time (newest first)
    session_files.sort(key=os.path.getmtime, reverse=True)
    
    # Keep only the last 20 session files, remove the rest
    if len(session_files) > 20:
        for old_file in session_files[20:]:
            try:
                os.remove(old_file)
                # Also delete SQLite journal file if exists
                journal = old_file + "-journal"
                if os.path.exists(journal):
                    os.remove(journal)
            except Exception as e:
                print(f"Error removing old session file {old_file}: {e}")
                
    # Return the path of the newest session file (strip .session suffix for Telethon)
    newest_path = Path(session_files[0])
    return str(newest_path.parent / newest_path.stem)


# Dynmically loaded SESSION_FILE path
SESSION_FILE = get_latest_session()

# The 20 Bot tokens directly saved in config
BOT_TOKENS = [
    "8945582546:AAF757CVu0I8LnQ6mG0doDPELoRSrYM_yVI",
    "8924555053:AAFZXwbHQleUvps7YCrOCIuiwT86b6bhPZ8",
    "8723132087:AAF9-d0Mnd1APq1bsu9-pOCm-Td0Vh1Uxe0",
    "8987638292:AAHy4CG8RC-xIkK4RuQ6fr835O_NJY1jJUQ",
    "8831033952:AAGlZn3b4etI7jzEkBenKKb1PYaV1YsLIUE",
    "8638760469:AAEDGeM_LJwQqqaA92vSrJyyNoXzOfWnhKo",
    "8796268458:AAH8WJEydBdZPzQwKAzzlLeA1hDc9zWoDHM",
    "7888236518:AAEFoQCkNZw39hpQPMcnRDbQTsYW6B-s71s",
    "8988654332:AAF4UtKeA_io5iXgG15dBo0In6fRAtlKQDE",
    "8711702299:AAGOfjhGTrqt2M0eS2D_Qjtk4kWarfOeI5s",
    "8864553619:AAExc5mMJjt7_IxQuNX6U3Y2TxX1yvrZ0M8",
    "8961800479:AAEHo4Cru_fU_rOB3XQcg3hPcbG_WSd33NU",
    "8899410642:AAGBVeiTmDJToFcz23Phpks8fckNLf3eg1E",
    "8752122960:AAEh_gFmFsN64O59w77BBbUgUubuLlvFqY0",
    "8614597637:AAGoM-E5iu_ofAUD1oBQckOWU64OGwxyt7w",
    "8918392135:AAFlaV1gsaL6Lqkja_NYiV17Qzrt8IIedc8",
    "8912334411:AAE34kiGl_iguF2buM43WwBuHlW41u3drv4",
    "8656091727:AAFLA7VjuFXNa9xZ0rxoNy8D_HeO6aAlv7U",
    "8802340529:AAGFuFN8ntOR4WkGmabp7dzEP9AygviusE4",
    "8636192167:AAHRqev21W8kCnx84b2ZM5ag85lpGB0CthM"
]
