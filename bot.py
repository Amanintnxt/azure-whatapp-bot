import os
import time
import openai
import logging
from dotenv import load_dotenv
from flask import Flask, request, Response
from twilio.twiml.messaging_response import MessagingResponse
from twilio.rest import Client

# Load environment variables
load_dotenv()

# Twilio credentials
TWILIO_ACCOUNT_SID = os.getenv("TWILIO_ACCOUNT_SID")
TWILIO_AUTH_TOKEN = os.getenv("TWILIO_AUTH_TOKEN")
TWILIO_WHATSAPP_NUMBER = os.getenv(
    "TWILIO_WHATSAPP_NUMBER", "whatsapp:+14155238886")  # Sandbox default

# Azure OpenAI
AZURE_OPENAI_API_KEY = os.getenv("AZURE_OPENAI_API_KEY")
AZURE_OPENAI_ENDPOINT = os.getenv("AZURE_OPENAI_ENDPOINT")
ASSISTANT_ID = os.getenv("ASSISTANT_ID")

# Configure OpenAI Azure API
openai.api_type = "azure"
openai.api_version = "2024-05-01-preview"
openai.api_key = AZURE_OPENAI_API_KEY
openai.azure_endpoint = AZURE_OPENAI_ENDPOINT.rstrip("/")

# Flask app
app = Flask(__name__)

# Simple memory store for user threads
thread_map = {}

# Twilio client
twilio_client = Client(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)

# WhatsApp message length limit
MAX_WHATSAPP_LENGTH = 1500  # Keep it under 1600 to be safe


def split_message(message: str, max_length: int = MAX_WHATSAPP_LENGTH) -> list:
    """
    Split a long message into chunks that fit within WhatsApp's character limit
    """
    if len(message) <= max_length:
        return [message]

    chunks = []
    current_chunk = ""

    # Split by sentences first to maintain readability
    sentences = message.split('. ')

    for i, sentence in enumerate(sentences):
        # Add period back except for last sentence
        if i < len(sentences) - 1:
            sentence += '. '

        # Check if adding this sentence would exceed limit
        if len(current_chunk + sentence) > max_length:
            if current_chunk:
                chunks.append(current_chunk.strip())
                current_chunk = sentence
            else:
                # Single sentence is too long, split by words
                words = sentence.split(' ')
                for word in words:
                    if len(current_chunk + ' ' + word) > max_length:
                        if current_chunk:
                            chunks.append(current_chunk.strip())
                            current_chunk = word
                        else:
                            # Single word is too long, force split
                            chunks.append(word[:max_length])
                            current_chunk = word[max_length:]
                    else:
                        if current_chunk:
                            current_chunk += ' ' + word
                        else:
                            current_chunk = word
        else:
            current_chunk += sentence

    # Add remaining chunk
    if current_chunk:
        chunks.append(current_chunk.strip())

    return chunks


def send_whatsapp_message(to_number: str, message: str):
    """
    Send a WhatsApp message through Twilio, splitting if necessary
    """
    try:
        message_chunks = split_message(message)

        for i, chunk in enumerate(message_chunks):
            # Add part indicator for multi-part messages
            if len(message_chunks) > 1:
                part_info = f" ({i+1}/{len(message_chunks)})"
                # Ensure the part info doesn't exceed the limit
                if len(chunk + part_info) <= MAX_WHATSAPP_LENGTH:
                    chunk += part_info

            twilio_client.messages.create(
                from_=TWILIO_WHATSAPP_NUMBER,
                body=chunk,
                to=to_number
            )

            # Small delay between messages to ensure proper ordering
            if i < len(message_chunks) - 1:
                time.sleep(0.5)

        logging.info(f"Sent {len(message_chunks)} message(s) to {to_number}")

    except Exception as e:
        logging.error(f"Error sending WhatsApp message: {e}")


def process_with_assistant(user_id: str, user_input: str) -> str:
    """
    Send user input to Azure OpenAI Assistant and return reply
    """
    try:
        # Get or create thread
        thread_id = thread_map.get(user_id)
        if not thread_id:
            thread = openai.beta.threads.create()
            thread_id = thread.id
            thread_map[user_id] = thread_id

        # Add message
        openai.beta.threads.messages.create(
            thread_id=thread_id,
            role="user",
            content=user_input
        )

        # Run assistant
        run = openai.beta.threads.runs.create(
            assistant_id=ASSISTANT_ID,
            thread_id=thread_id
        )

        # Poll until complete
        while run.status not in ["completed", "failed", "cancelled"]:
            time.sleep(1)
            run = openai.beta.threads.runs.retrieve(
                thread_id=thread_id,
                run_id=run.id
            )

        # Get last assistant reply
        messages = openai.beta.threads.messages.list(thread_id=thread_id)
        assistant_reply = None
        for message in messages.data:
            if message.role == "assistant":
                assistant_reply = message.content[0].text.value
                break

        return assistant_reply or "Sorry, I didn't get a reply."

    except Exception as e:
        logging.error(f"Assistant error: {e}")
        return "Something went wrong while processing your request."


@app.route("/twilio/whatsapp", methods=["POST"])
def whatsapp_webhook():
    """
    Twilio webhook for incoming WhatsApp messages
    """
    try:
        incoming_msg = request.form.get("Body", "").strip()
        from_number = request.form.get("From", "")

        if not incoming_msg:
            # Send short error message
            send_whatsapp_message(from_number, "Please send a valid message.")
            return str(MessagingResponse())

        # Process with Azure OpenAI Assistant
        reply = process_with_assistant(from_number, incoming_msg)

        # Send response using our custom function that handles splitting
        send_whatsapp_message(from_number, reply)

        # Return empty TwiML response since we're sending messages directly
        return str(MessagingResponse())

    except Exception as e:
        logging.error(f"Webhook error: {e}")
        send_whatsapp_message(from_number, "Error processing your message.")
        return str(MessagingResponse())


@app.route("/", methods=["GET"])
def health_check():
    return "WhatsApp Bot with Azure OpenAI is running!"


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    app.run(host="0.0.0.0", port=3978)
