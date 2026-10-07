from flask import Flask, request, jsonify, render_template, session
from google import genai
from google.genai import types
from google.cloud import texttospeech
from langdetect import detect
import os
import base64
import re
import requests
from bs4 import BeautifulSoup
import concurrent.futures
from dotenv import load_dotenv

# ==================================================
# 1. BASIC SETUP
# ==================================================

load_dotenv()

app = Flask(__name__)
app.secret_key = os.environ.get("FLASK_SECRET_KEY") or os.urandom(32)

# Secrets come from the environment (see .env.example); nothing is hard-coded.
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
if not GEMINI_API_KEY:
    raise RuntimeError("GEMINI_API_KEY is not set. Copy .env.example to .env and fill it in.")

client = genai.Client(api_key=GEMINI_API_KEY)

# Text-to-speech is optional: it needs GOOGLE_APPLICATION_CREDENTIALS to point at a
# Google Cloud service-account JSON file. Without it, the chat works and voice replies are skipped.
try:
    tts_client = texttospeech.TextToSpeechClient()
except Exception as exc:
    tts_client = None
    print(f"Text-to-speech disabled: {exc}")
MODEL_NAME = "gemini-flash-latest" # Switched to Flash for speed/cost, switch back to Pro if needed

# ==================================================
# 2. DATA LOADING (WEB SCRAPE + LOCAL FILE)
# ==================================================

def fetch_url_text(url):
    """Helper function to fetch and clean a single URL."""
    try:
        headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}
        response = requests.get(url, headers=headers, timeout=5)
        
        if response.status_code == 200:
            soup = BeautifulSoup(response.text, 'html.parser')
            for script in soup(["script", "style", "nav", "footer"]):
                script.decompose()
            text = soup.get_text(separator="\n", strip=True)
            return f"\n\n--- SOURCE: {url} ---\n{text}"
        else:
            return f"\n\n--- FAILED: {url} (Status: {response.status_code}) ---"
    except Exception as e:
        return f"\n\n--- ERROR: {url} ({str(e)}) ---"

def get_full_rdc_site_data():
    """Scrapes multiple key pages of the RDC website in parallel."""
    target_urls = [
        "https://www.rdc.in/",
        "https://www.rdc.in/careers",
        "https://www.rdc.in/contactus"
    ]
    
    print(f"Starting scrape of {len(target_urls)} pages...")
    full_content = ""
    
    with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
        future_to_url = {executor.submit(fetch_url_text, url): url for url in target_urls}
        for future in concurrent.futures.as_completed(future_to_url):
            full_content += future.result()
            
    return full_content[:50000] # Limit web content size

def read_local_locations():
    """Reads the local locations.txt file."""
    file_path = "locations.txt"
    if os.path.exists(file_path):
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                content = f.read()
            print("✓ Local locations.txt loaded successfully.")
            return f"\n\n--- INTERNAL DATA: LOCATIONS & BRANCHES (high priority) ---\n{content}"
        except Exception as e:
            print(f"Error reading locations.txt: {e}")
            return ""
    else:
        print("Warning: locations.txt not found. Skipping.")
        return ""

# --- LOAD DATA ON STARTUP ---
print("Loading RDC Knowledge Base...")
web_data = get_full_rdc_site_data()
local_data = read_local_locations()

# Combine both sources
WEBSITE_DATA_CONTEXT = web_data + local_data
print("RDC Knowledge Base Ready.")

# ==================================================
# 3. SYSTEM PROMPT
# ==================================================

SYSTEM_PROMPT = f"""
You are RDC Chatbot, the official AI assistant for RDC Concrete (India) Limited.

*** OFFICIAL KNOWLEDGE BASE ***
The following text contains data scraped from the website AND internal location files.
ALWAYS CHECK THIS DATA FIRST.

--------------------------------------------------
{WEBSITE_DATA_CONTEXT}
--------------------------------------------------

CRITICAL INSTRUCTIONS:
1. **Locations & Branches:** Use the "INTERNAL DATA" section provided above to answer specific questions about plant locations, addresses, and managers.
2. **Search Mandate:** Use google search to answer any question for which you do not have information about.
3. **Scope:** Answer ONLY construction, concrete, and RDC-related questions.
4. **Tone:** Professional, helpful, and concise.
5. **Language:** Detect and match the user's language. Response should also be in that same language. 
6. **Response:** Keep it maximum 3 sentences. Not too long, not too short. 

EMPLOYEE & PERSON IDENTIFICATION RULES:
- If it's mentioned on google, use that information to answer the question, use google's help to identify people working in RDC. 

• NEVER guess, infer, or assume company association.

NUMERIC & CONTACT RULES:
• Phone numbers must be treated as contact identifiers, not quantities.
• When speaking phone numbers, read digits individually.

"""

# ==================================================
# 4. UTILITIES
# ==================================================

def clean_text(text: str) -> str:
    if not text: return ""
    text = re.sub(r'```.*?```', '', text, flags=re.DOTALL)
    text = text.replace('`', '').replace('*', '').replace('_', '')
    text = re.sub(r'tool_code', '', text, flags=re.IGNORECASE)
    text = re.sub(r'\[\d+\]', '', text)
    text = re.sub(r'\[([^\]]+)\]\([^\)]+\)', r'\1', text)
    return text.strip()

def synthesize_voice(text: str) -> str:
    if tts_client is None:
        return ""
    try:
        lang = detect(text)
    except:
        lang = "en"

    VOICE_MAPPING = {
        "hi": {"code": "hi-IN", "name": "hi-IN-Neural2-A"},
        "mr": {"code": "mr-IN", "name": "mr-IN-Standard-A"},
        "te": {"code": "te-IN", "name": "te-IN-Standard-A"},
        "en": {"code": "en-IN", "name": "en-IN-Neural2-D"}
    }
    # Fallback to English if detected lang is not in mapping
    voice_config = VOICE_MAPPING.get(lang, VOICE_MAPPING["en"])

    synthesis_input = texttospeech.SynthesisInput(text=text)
    voice = texttospeech.VoiceSelectionParams(language_code=voice_config["code"], name=voice_config["name"])
    audio_config = texttospeech.AudioConfig(audio_encoding=texttospeech.AudioEncoding.MP3)

    response = tts_client.synthesize_speech(input=synthesis_input, voice=voice, audio_config=audio_config)
    return base64.b64encode(response.audio_content).decode("utf-8")

def process_chat_with_history(user_text, history):
    try:
        gemini_history = []
        for turn in history:
            role = "user" if turn["role"] == "user" else "model"
            gemini_history.append(types.Content(role=role, parts=[types.Part(text=turn["text"])]))

        gemini_history.append(types.Content(role="user", parts=[types.Part(text=user_text)]))

        config = types.GenerateContentConfig(
            tools=[types.Tool(google_search=types.GoogleSearch())],
            system_instruction=SYSTEM_PROMPT,
            temperature=0.3
        )

        response = client.models.generate_content(
            model=MODEL_NAME,
            contents=gemini_history,
            config=config
        )

        if response.text:
            return clean_text(response.text)
        else:
            return "I couldn't generate a response. Please try again."

    except Exception as e:
        print(f"GenAI Error: {e}")
        return "I encountered a technical error."

# ==================================================
# 5. ROUTES
# ==================================================

@app.route("/")
def index():
    return render_template("index.html")

@app.route("/chat", methods=["POST"])
def chat():
    user_message = request.json.get("message", "")
    
    if 'history' not in session:
        session['history'] = []
    
    response_text = process_chat_with_history(user_message, session['history'])

    session['history'].append({"role": "user", "text": user_message})
    session['history'].append({"role": "model", "text": response_text})
    
    if len(session['history']) > 10:
        session['history'] = session['history'][-10:]
    
    session.modified = True

    return jsonify({
        "success": True,
        "response": response_text
    })

@app.route("/chat-voice", methods=["POST"])
def chat_voice():
    if "audio" not in request.files:
        return jsonify({"success": False, "error": "No audio file"})

    audio_file = request.files["audio"]
    audio_bytes = audio_file.read()
    mime_type = audio_file.content_type or "audio/webm"

    try:
        if 'history' not in session:
            session['history'] = []

        contents = []
        # Add history text (context)
        for turn in session['history']:
             role = "user" if turn["role"] == "user" else "model"
             contents.append(types.Content(role=role, parts=[types.Part(text=turn["text"])]))

        # Add current Audio
        contents.append(
            types.Content(
                role="user",
                parts=[types.Part.from_bytes(data=audio_bytes, mime_type=mime_type)]
            )
        )

        config = types.GenerateContentConfig(
            tools=[types.Tool(google_search=types.GoogleSearch())],
            system_instruction=SYSTEM_PROMPT,
            temperature=0.3
        )

        response = client.models.generate_content(
            model=MODEL_NAME,
            contents=contents,
            config=config
        )

        final_text = clean_text(response.text) if response.text else "I didn't catch that."

        # Add to history (User input approximated as [Voice Query] since we rely on Multimodal for understanding)
        session['history'].append({"role": "user", "text": "[Voice Query related to: " + final_text[:20] + "...]"}) 
        session['history'].append({"role": "model", "text": final_text})
        session.modified = True

        audio_b64 = synthesize_voice(final_text)

        return jsonify({
            "success": True,
            "response_text": final_text,
            "audio_content": audio_b64
        })

    except Exception as e:
        print(f"Voice Route Error: {e}")
        return jsonify({"success": False, "error": str(e)})

# ==================================================
# 6. RUN
# ==================================================

if __name__ == "__main__":
    app.run(debug=os.environ.get("FLASK_DEBUG") == "1", port=int(os.environ.get("PORT", "5000")))