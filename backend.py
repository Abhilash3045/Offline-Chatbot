import os
import random
import wave
import json
import pytesseract
import sqlite3
from PIL import Image
from vosk import Model, KaldiRecognizer
from flask import Flask, request, jsonify, session
from llama_cpp import Llama
from flask_cors import CORS
from werkzeug.security import generate_password_hash, check_password_hash
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# --- Configuration ---
MODEL_PATH = os.getenv("MODEL_PATH", "models/llama-2-7b-chat.Q4_K_M.gguf")
VOSK_MODEL_PATH = "models/vosk-model-small-en-us-0.15"

pytesseract.pytesseract.tesseract_cmd = r"C:\\Program Files\\Tesseract-OCR\\tesseract.exe"

if not os.path.exists(MODEL_PATH):
    print(f"\u274c ERROR: AI Model file not found at: {os.path.abspath(MODEL_PATH)}")
    print("Please ensure the 'llama-2-7b-chat.Q4_K_M.gguf' file is in the 'models' directory relative to backend.py, or update MODEL_PATH in your .env file.")
    raise ValueError(f"\u274c AI Model file not found at: {MODEL_PATH}")

# --- Flask App Initialization ---
app = Flask(__name__)
app.secret_key = os.getenv("SECRET_KEY", "supersecret")
CORS(app, supports_credentials=True)
app.json.compact = False

# --- Model Initialization ---
llm = None
try:
    print(f"\u2705 Initializing Llama model from: {os.path.abspath(MODEL_PATH)}")
    llm = Llama(model_path=MODEL_PATH, n_ctx=4096, seed=42, n_threads=8, n_batch=512)
    print("\u2705 Llama model initialized successfully.")
except Exception as e:
    print(f"\u274c ERROR: Failed to load Llama model: {e}")
    llm = None

# --- DB Initialization ---
DB_PATH = "flask_users.db"
conn = sqlite3.connect(DB_PATH, check_same_thread=False)
c = conn.cursor()
c.execute("""
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    email TEXT UNIQUE NOT NULL,
    password TEXT NOT NULL
);
""")
c.execute("""
CREATE TABLE IF NOT EXISTS history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER,
    message TEXT,
    response TEXT,
    FOREIGN KEY(user_id) REFERENCES users(id)
);
""")
conn.commit()
print(f"\u2705 Connected to Flask SQLite database: {DB_PATH}")


# --- Utilities ---

def detect_emotion(user_input):
    emotions = {
        "happy": ["happy", "great", "awesome", "good", "fantastic", "excited", "love"],
        "sad": ["sad", "unhappy", "depressed", "bad", "terrible", "upset", "lonely"],
        "angry": ["angry", "mad", "furious", "annoyed", "frustrated"],
        "confused": ["confused", "don't know", "not sure", "lost"],
        "greeting": ["hi", "hello", "hey", "howdy", "morning", "evening"]
    }
    user_input = user_input.lower()
    for emotion, keywords in emotions.items():
        if any(word in user_input for word in keywords):
            return emotion
    return "neutral"

def generate_ai_response(user_input):
    if llm is None:
        print("\🫢 Llama model not loaded. Cannot generate AI response.")
        return "😞 Sorry, the AI model is not available right now."

    prompt = f"""
    You are a friendly, emotionally aware AI assistant. Respond with a warm, engaging, and human-like tone.
    Add emotions and enthusiasm to your responses, using emojis when appropriate.
    ---
    User: {user_input}
    AI:"""
    try:
        response = llm.create_completion(prompt=prompt, max_tokens=2048, temperature=0.6, top_p=0.9, stop=["\n\n", "User:"])
        text = response.get("choices", [{}])[0].get("text", "").strip()
        if len(text) < 50 and not text.endswith(('.', '!', '?')):
            print("Detected short/incomplete response, regenerating with more detail prompt.")
            prompt = f"""
            You are an emotionally aware AI chatbot. Make responses detailed, engaging, and human-like.
            Ensure a full, thoughtful response that does not stop mid-sentence.
            ---
            User: {user_input}
            AI:"""
            response = llm.create_completion(prompt=prompt, max_tokens=2048, temperature=0.6, top_p=0.9, stop=["\n\n", "User:"])
            text = response.get("choices", [{}])[0].get("text", "").strip()

        # REMOVED: .encode().decode() from here. It will be applied universally before DB save.
        return text if text else "\ud83e\udde0 Sorry, I couldn't generate a coherent AI response."
    except Exception as e:
        print(f"❌ Error during AI response generation: {e}")
        return "🤯 Sorry, I encountered an issue generating a response."

def generate_emotional_response(user_input):
    emotion = detect_emotion(user_input)
    if emotion == "greeting":
        return random.choice([
            "👋 Hey there! How can I make your day better?",
            "😊 Hi! What's up?",
            "🙌 Hello! I'm here to chat. What’s on your mind?"
        ])
    emotional_responses = {
        "happy": ["😁 That’s amazing! What’s making you so happy?", " 🎉 Yay! Share your good news!"],
        "sad": ["💙 I'm here for you. Want to talk about it?", "🤗 Sending a virtual hug your way!"],
        "angry": ["😡 That sounds frustrating! Want to vent?", "🔥 Take a deep breath! What’s bothering you?"],
        "confused": ["🤔 No worries! Let me explain.", " 😕 I can help clarify things for you."]
    }
    if emotion in emotional_responses:
        return random.choice(emotional_responses[emotion])
    return generate_ai_response(user_input)

# --- Routes ---

@app.route("/signup", methods=["POST"])
def signup():
    data = request.json
    email = data.get("email")
    password = data.get("password")
    if not email or not password:
        return jsonify({"error": "Email and password required."}), 400
    try:
        hashed = generate_password_hash(password)
        c.execute("INSERT INTO users (email, password) VALUES (?, ?)", (email, hashed))
        conn.commit()
        print(f"\u2705 New user signed up: {email}")
        return jsonify({"success": True})
    except sqlite3.IntegrityError:
        print(f"\u274c Signup failed: Email {email} already registered.")
        return jsonify({"error": "Email already registered."}), 409
    except Exception as e:
        print(f"\u274c Signup error: {e}")
        return jsonify({"error": "Server error during signup."}), 500

@app.route("/login", methods=["POST"])
def login():
    data = request.json
    email = data.get("email")
    password = data.get("password")
    c.execute("SELECT id, password FROM users WHERE email = ?", (email,))
    row = c.fetchone()
    if row and check_password_hash(row[1], password):
        session["user_id"] = row[0]
        print(f"\u2705 User logged in: {email}")
        return jsonify({"success": True})
    print(f"\u274c Login failed for: {email} - Invalid credentials.")
    return jsonify({"error": "Invalid credentials."}), 401

@app.route("/logout")
def logout():
    session.clear()
    print("\u2705 User logged out.")
    return jsonify({"success": True})

@app.route("/get", methods=["POST"])
def get_response():
    user_input = request.json.get("msd", "").strip()
    user_id = request.json.get("userId")
    print(f"\u2705 Received user input: '{user_input}' (User ID: {user_id})")

    if user_id is None:
        print("\u274c Error: user_id not provided in the request body.")
        return jsonify({"error": "User ID not provided"}), 400

    if not user_input:
        print("\u274c Invalid input: Empty message received.")
        return jsonify({"error": "Invalid input"}), 400
    try:
        raw_response = generate_emotional_response(user_input)

        # *** CRITICAL FIX: Apply encoding/decoding here, right before saving to DB ***
        # This cleans both AI-generated responses and hardcoded emotional responses.
        cleaned_response = raw_response.encode('utf-8', 'ignore').decode('utf-8')
        
        # It's also good practice to clean the user_input in case it contains odd characters
        cleaned_user_input = user_input.encode('utf-8', 'ignore').decode('utf-8')

        c.execute("INSERT INTO history (user_id, message, response) VALUES (?, ?, ?)",
                  (user_id, cleaned_user_input, cleaned_response))
        conn.commit()
        print(f"\u2705 AI response generated and saved: '{cleaned_response}'")
        return jsonify({"response": cleaned_response})
    except Exception as e:
        print(f"\u274c FATAL ERROR in /get: {e}")
        return jsonify({"error": "AI backend error: " + str(e)}), 500


@app.route("/image", methods=["POST"])
def process_image():
    if "file" not in request.files:
        return jsonify({"error": "No image file uploaded"}), 400
    try:
        image = Image.open(request.files["file"])
        text = pytesseract.image_to_string(image).strip()
        print(f"\u2705 Image OCR result: '{text}'")
        return jsonify({"text": text if text else "\ud83e\udde0 No text detected in image."})
    except Exception as e:
        print(f"\u274c Error processing image: {e}")
        return jsonify({"error": "Failed to process image."}), 500

if __name__ == "__main__":
    print(f"\u2705 AI Backend is starting on port 5000...")
    print(f"Using Llama model: {os.path.abspath(MODEL_PATH)}")
    app.run(host="0.0.0.0", port=5000, debug=False)