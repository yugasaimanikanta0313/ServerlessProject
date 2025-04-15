import json
import os
import urllib.request
import requests
import time
from flask import Flask, request, jsonify

# Environment Variables (set these in your environment or .env file)
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN", "7688154062:AAHx7_p6pH_XMhgfdzhAlZKaEM6LQahs5r8")
OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
OLLAMA_MODEL = "llama3.2"
OLLAMA_IMAGE_MODEL ="llama3.2"

TELEGRAM_API_URL = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}"

# Track user modes and document texts
user_modes = {}
document_texts = {}  # chat_id : extracted_text
conversation_history = []  # Simple in-memory history instead of DynamoDB

app = Flask(__name__)


# Utility functions
def send_message(chat_id, text):
    url = f"{TELEGRAM_API_URL}/sendMessage"
    data = json.dumps({"chat_id": chat_id, "text": text}).encode()
    req = urllib.request.Request(url, data, headers={"Content-Type": "application/json"})
    urllib.request.urlopen(req)


def send_photo(chat_id, image_path):
    url = f"{TELEGRAM_API_URL}/sendPhoto"
    with open(image_path, "rb") as photo:
        files = {'photo': photo}
        data = {'chat_id': chat_id}
        requests.post(url, data=data, files=files)


def send_menu(chat_id):
    menu = {
        "chat_id": chat_id,
        "text": "Please select an option:",
        "reply_markup": {
            "inline_keyboard": [
                [
                    {"text": "🖼 Generate Image", "callback_data": "generate_image"},
                    {"text": "🧠 Ask a Question", "callback_data": "ask_question"}
                ],
                [
                    {"text": "❤️ Sentiment Analysis", "callback_data": "sentiment"}
                ]
            ]
        }
    }
    url = f"{TELEGRAM_API_URL}/sendMessage"
    req = urllib.request.Request(url, json.dumps(menu).encode(), headers={"Content-Type": "application/json"})
    urllib.request.urlopen(req)


def log_conversation(chat_id, mode, user_input, bot_response):
    conversation_history.append({
        "chat_id": str(chat_id),
        "timestamp": int(time.time()),
        "mode": mode,
        "user_input": user_input,
        "bot_response": bot_response
    })
    print(f"Logged conversation: {conversation_history[-1]}")


# Ollama Functions
def query_ollama(prompt, chat_id=None, document_context=None):
    try:
        url = f"{OLLAMA_BASE_URL}/api/generate"

        full_prompt = prompt
        if document_context:
            full_prompt = f"Context: {document_context}\n\nQuestion: {prompt}\n\nAnswer:"
        else:
            full_prompt = f"Answer the question concisely with a short explanation.\nQuestion: {prompt}"

        payload = {
            "model": OLLAMA_MODEL,
            "prompt": full_prompt,
            "stream": False,
            "options": {
                "temperature": 0.7,
                "max_tokens": 150
            }
        }

        response = requests.post(url, json=payload)
        if response.status_code == 200:
            result = response.json()
            return result['response'].strip()
        else:
            print("Ollama error:", response.text)
            return "Sorry, I couldn't think of a reply!"
    except Exception as e:
        print("Ollama query exception:", str(e))
        return "Error processing your request."


def analyze_sentiment(text):
    try:
        prompt = f"""Analyze the sentiment of this text and respond with only one word: 
        "Positive", "Negative", or "Neutral". Text: {text}"""

        response = query_ollama(prompt)
        sentiment = response.split()[0].lower()

        emoji_map = {
            "positive": "Positive 😊",
            "negative": "Negative 😞",
            "neutral": "Neutral 😐"
        }

        for key in emoji_map:
            if key in sentiment:
                return f"Sentiment: {emoji_map[key]}"
        return f"Sentiment: {response}"
    except Exception as e:
        print("Sentiment exception:", str(e))
        return "Could not analyze sentiment."


def generate_image(prompt, chat_id):
    try:
        send_message(chat_id, "🎨 Generating your image, please wait...")

        url = f"{OLLAMA_BASE_URL}/api/generate"
        payload = {
            "model": OLLAMA_IMAGE_MODEL,
            "prompt": prompt,
            "stream": False
        }

        response = requests.post(url, json=payload)

        if response.status_code == 200:
            result = response.json()
            if 'image' in result:
                import base64
                from io import BytesIO
                from PIL import Image

                image_data = base64.b64decode(result['image'])
                image_path = "generated_image.png"

                with open(image_path, "wb") as f:
                    f.write(image_data)

                send_photo(chat_id, image_path)
                return True
        return False
    except Exception as e:
        print("Image generation exception:", str(e))
        return False


# Simplified document processing (no AWS Textract)
def process_document(chat_id, file_id):
    try:
        # In a local version, we can't process PDFs as thoroughly without Textract
        # This is a placeholder that just acknowledges receipt
        send_message(chat_id, "📄 Document received. For local testing, please type your question directly.")
        document_texts[
            chat_id] = "Sample document text - in a full implementation this would be extracted text from the PDF"
        return True
    except Exception as e:
        print("Document processing error:", str(e))
        send_message(chat_id, "⚠️ Could not process the document in local mode.")
        return False


# Flask endpoint to handle Telegram webhooks
@app.route('/webhook', methods=['POST'])
def webhook():
    try:
        print("✅ Local Ollama Telegram bot running")
        body = request.json

        if "callback_query" in body:
            callback = body["callback_query"]
            chat_id = callback["message"]["chat"]["id"]
            data = callback["data"]
            user_modes[chat_id] = data

            if data == "generate_image":
                send_message(chat_id, "Send a prompt to generate an image.")
            elif data == "ask_question":
                send_message(chat_id, "Ask your question.")
            elif data == "sentiment":
                send_message(chat_id, "Send a message to analyze sentiment.")
            return jsonify({"status": "success"})

        message = body.get("message", {})
        chat_id = message.get("chat", {}).get("id")
        user_input = message.get("text")
        document = message.get("document")

        if user_input == "/start":
            send_menu(chat_id)
            return jsonify({"status": "success"})

        mode = user_modes.get(chat_id)

        if document and mode == "document_qa":
            file_id = document.get("file_id")
            send_message(chat_id, "📄 Received your document (local mode has limited processing)")
            process_document(chat_id, file_id)
            return jsonify({"status": "success"})

        if not chat_id or not user_input:
            return jsonify({"status": "no valid input"})

        if mode == "document_qa" and chat_id in document_texts:
            answer = query_ollama(user_input, chat_id, document_texts[chat_id])
            send_message(chat_id, answer)
            log_conversation(chat_id, mode, user_input, answer)
        elif mode == "generate_image":
            success = generate_image(user_input, chat_id)
            if success:
                log_conversation(chat_id, mode, user_input, "Image generated")
            else:
                send_message(chat_id, "⚠️ Failed to generate image. Please try again later.")
        elif mode == "sentiment":
            sentiment = analyze_sentiment(user_input)
            send_message(chat_id, sentiment)
            log_conversation(chat_id, mode, user_input, sentiment)
        elif mode == "ask_question":
            bot_reply = query_ollama(user_input, chat_id)
            send_message(chat_id, bot_reply)
            log_conversation(chat_id, mode, user_input, bot_reply)
        else:
            send_message(chat_id, "Please select an option from the menu with /start.")

        return jsonify({"status": "success"})
    except Exception as e:
        print("Error:", str(e))
        return jsonify({"status": "error", "message": str(e)}), 500


if __name__ == '__main__':
    # Set up Telegram webhook (you'll need to do this once)
    # Replace YOUR_PUBLIC_URL with your ngrok or local tunnel URL
    # requests.get(f"{TELEGRAM_API_URL}/setWebhook?url=YOUR_PUBLIC_URL/webhook")

    # Run the Flask app
    app.run(host='0.0.0.0', port=5000)