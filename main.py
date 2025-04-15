import ollama
import time
import asyncio
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, filters, ContextTypes
from io import BytesIO

API_TOKEN = '7688154062:AAHx7_p6pH_XMhgfdzhAlZKaEM6LQahs5r8'
BOT_USERNAME = '@Yugasai_AssistantBot'

client = ollama.AsyncClient()
ongoing_tasks = {}
last_messages = {}

# Supported image formats
SUPPORTED_IMAGE_EXTENSIONS = ['.jpg', '.jpeg', '.png', '.webp']


def truncate_text(text, max_length=4000):
    """Ensure text doesn't exceed Telegram message limits"""
    return text[:max_length] + " [truncated]" if len(text) > max_length else text


async def generate_text_response(user_input, chat_id):
    try:
        async for chunk in await client.generate(
                model="llama3.2",  # Replace with your preferred model
                prompt=user_input,
                stream=True,
                options={
                    "num_predict": 1024,
                    "temperature": 0.7,
                    "num_thread": 4,
                    "num_ctx": 4096,
                    "repeat_last_n": 64
                }
        ):
            yield chunk["response"]
            if chat_id not in ongoing_tasks:
                break
    finally:
        ongoing_tasks.pop(chat_id, None)


async def generate_image_response(image_bytes, prompt=None, chat_id=None):
    try:
        if prompt is None:
            prompt = "Describe this image in detail."

        response = await client.generate(
            model="moondream",  # Using LLaVA model for image understanding
            prompt=prompt,
            images=[image_bytes],
            options={
                "num_predict": 512,
                "temperature": 0.6
            }
        )
        return response['response']
    except Exception as e:
        print(f"Image processing error: {e}")
        return "Sorry, I couldn't process that image."


async def chat_with_bot_streaming(chat_id: int, user_input: str, context: ContextTypes.DEFAULT_TYPE, image_bytes=None):
    try:
        message = await context.bot.send_message(
            chat_id=chat_id,
            text="⚡ Generating..." + (" (processing image)" if image_bytes else ""),
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🛑 Stop", callback_data="stop")]])
        )

        last_messages[chat_id] = {'user_input': user_input, 'message_id': message.message_id,
                                  'image_bytes': image_bytes}
        full_response = ""
        displayed_response = ""
        last_update = time.time()

        if image_bytes:
            # Handle image processing (non-streaming)
            response = await generate_image_response(image_bytes, user_input, chat_id)
            full_response = response
        else:
            # Handle text processing (streaming)
            async for chunk in generate_text_response(user_input, chat_id):
                full_response += chunk
                current_part = chunk.replace("  ", " ").strip()

                # Update only if significant changes occur
                if (len(full_response) - len(displayed_response) > 100 or
                        (time.time() - last_update > 0.5)):
                    try:
                        displayed_response = full_response
                        await context.bot.edit_message_text(
                            chat_id=chat_id,
                            message_id=message.message_id,
                            text=truncate_text(full_response + "▌"),
                            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🛑 Stop", callback_data="stop")]])
                        )
                        last_update = time.time()
                    except Exception as e:
                        if "Message is not modified" not in str(e):
                            print(f"Edit error: {e}")

        # Final update with full response
        final_text = truncate_text(full_response)
        await context.bot.edit_message_text(
            chat_id=chat_id,
            message_id=message.message_id,
            text=final_text,
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔄 Regenerate", callback_data="regen")]])
        )

        # Handle multi-part responses
        if len(full_response) > 4000:
            remaining_text = full_response[4000:]
            while remaining_text:
                chunk = remaining_text[:4000]
                remaining_text = remaining_text[4000:]
                await context.bot.send_message(
                    chat_id=chat_id,
                    text=truncate_text(chunk),
                    reply_to_message_id=message.message_id
                )

    except asyncio.CancelledError:
        final_text = truncate_text(full_response + "\n\n❌ Stopped by user")
        await context.bot.edit_message_text(
            chat_id=chat_id,
            message_id=message.message_id,
            text=final_text,
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔄 Regenerate", callback_data="regen")]])
        )
    finally:
        ongoing_tasks.pop(chat_id, None)


async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    chat_id = query.message.chat_id
    message_id = query.message.message_id

    if query.data == "stop":
        task = ongoing_tasks.get(chat_id)
        if task:
            task.cancel()
            await query.edit_message_text(text=truncate_text(query.message.text + "\n\n❌ Stopped by user"))
        ongoing_tasks.pop(chat_id, None)

    elif query.data == "regen":
        if chat_id in last_messages:
            await context.bot.delete_message(chat_id, message_id)
            user_input = last_messages[chat_id]['user_input']
            image_bytes = last_messages[chat_id].get('image_bytes')
            task = asyncio.create_task(chat_with_bot_streaming(chat_id, user_input, context, image_bytes))
            ongoing_tasks[chat_id] = task


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🚀 Advanced AI Bot\n"
        "• Stop responses with 🛑\n"
        "• Regenerate with 🔄\n"
        "• Handles long messages!\n"
        "• Can analyze images (send me a photo with optional text)")


async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.message.chat_id
    if chat_id in ongoing_tasks:
        await update.message.reply_text("⚠ Please wait for current response to complete!")
        return

    user_input = update.message.text
    task = asyncio.create_task(chat_with_bot_streaming(chat_id, user_input, context))
    ongoing_tasks[chat_id] = task


async def handle_image(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.message.chat_id
    if chat_id in ongoing_tasks:
        await update.message.reply_text("⚠ Please wait for current response to complete!")
        return

    # Get the highest quality photo available
    photo = update.message.photo[-1] if update.message.photo else None
    document = update.message.document if update.message.document else None

    if photo:
        file = await context.bot.get_file(photo.file_id)
    elif document and any(document.file_name.lower().endswith(ext) for ext in SUPPORTED_IMAGE_EXTENSIONS):
        file = await context.bot.get_file(document.file_id)
    else:
        await update.message.reply_text("Please send a valid image (JPG, PNG, or WEBP).")
        return

    # Download the image
    image_bytes = BytesIO()
    await file.download_to_memory(out=image_bytes)
    image_bytes.seek(0)

    # Get optional caption/prompt
    user_input = update.message.caption or "What's in this image?"

    task = asyncio.create_task(chat_with_bot_streaming(chat_id, user_input, context, image_bytes.getvalue()))
    ongoing_tasks[chat_id] = task


def main():
    app = Application.builder().token(API_TOKEN).build()
    app.add_handler(CommandHandler('start', start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    app.add_handler(MessageHandler(filters.PHOTO | filters.Document.IMAGE, handle_image))
    app.add_handler(CallbackQueryHandler(button_callback))

    print("Bot is running with text and image capabilities...")
    app.run_polling()


if __name__ == '__main__':
    main()

#
# import asyncio
# import google.generativeai as genai
# from telegram import (
#     Update,
#     InlineKeyboardButton,
#     InlineKeyboardMarkup,
# )
# from telegram.ext import (
#     ApplicationBuilder,
#     CommandHandler,
#     MessageHandler,
#     CallbackQueryHandler,
#     ContextTypes,
#     filters,
# )
#
# # ========== CONFIG ==========
#
# GEMINI_API_KEY = "AIzaSyD9xxrW_s37Q-QOosT4qSoPHJuu84RUg3k"
# TELEGRAM_BOT_TOKEN = "7688154062:AAHx7_p6pH_XMhgfdzhAlZKaEM6LQahs5r8"
#
# genai.configure(api_key=GEMINI_API_KEY)
# model = genai.GenerativeModel("gemini-2.0-flash")
#
# # ========== MEMORY ==========
#
# active_tasks = {}
# last_messages = {}
#
# # ========== UTILITY ==========
#
# def split_text(text, max_length=4000):
#     chunks = []
#     while text:
#         split_at = text[:max_length].rfind('\n')
#         if split_at == -1:
#             split_at = max_length
#         chunks.append(text[:split_at])
#         text = text[split_at:]
#     return chunks
#
# def get_keyboard():
#     return InlineKeyboardMarkup([
#         [InlineKeyboardButton("🛑 Stop", callback_data="stop")],
#         [InlineKeyboardButton("🔄 Regenerate", callback_data="regenerate")]
#     ])
#
# # ========== COMMANDS ==========
#
# async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
#     await update.message.reply_text("👋 Hello! Send me a message and I'll respond using Gemini AI!")
#
# async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
#     user_input = update.message.text
#     chat_id = update.effective_chat.id
#     if chat_id in active_tasks:
#         await update.message.reply_text("⚠️ Please wait for the current response or stop it.")
#         return
#
#     msg = await update.message.reply_text("💡 Thinking...", reply_markup=get_keyboard())
#     last_messages[chat_id] = {"input": user_input, "message_id": msg.message_id}
#     task = asyncio.create_task(stream_reply(chat_id, user_input, context))
#     active_tasks[chat_id] = task
#
# async def stream_reply(chat_id: int, user_input: str, context: ContextTypes.DEFAULT_TYPE):
#     try:
#         chat = model.start_chat()
#         response = chat.send_message(user_input)
#         text = response.text or "⚠️ No response received."
#
#         chunks = split_text(text)
#         for chunk in chunks:
#             await context.bot.send_message(chat_id=chat_id, text=chunk)
#         await context.bot.send_message(chat_id=chat_id, text="✅ Done!", reply_markup=get_keyboard())
#     except Exception as e:
#         await context.bot.send_message(chat_id=chat_id, text=f"❌ Error: {e}")
#     finally:
#         active_tasks.pop(chat_id, None)
#
# async def handle_buttons(update: Update, context: ContextTypes.DEFAULT_TYPE):
#     query = update.callback_query
#     await query.answer()
#     chat_id = query.message.chat.id
#
#     if query.data == "stop":
#         task = active_tasks.get(chat_id)
#         if task:
#             task.cancel()
#             active_tasks.pop(chat_id, None)
#             await context.bot.send_message(chat_id=chat_id, text="🛑 Stopped.")
#         else:
#             await context.bot.send_message(chat_id=chat_id, text="⚠️ No active task to stop.")
#
#     elif query.data == "regenerate":
#         if chat_id in last_messages:
#             user_input = last_messages[chat_id]["input"]
#             await context.bot.send_message(chat_id=chat_id, text="🔄 Regenerating...")
#             task = asyncio.create_task(stream_reply(chat_id, user_input, context))
#             active_tasks[chat_id] = task
#         else:
#             await context.bot.send_message(chat_id=chat_id, text="⚠️ No previous message to regenerate.")
#
# # ========== MAIN ==========
#
# if __name__ == "__main__":
#     app = ApplicationBuilder().token(TELEGRAM_BOT_TOKEN).build()
#     app.add_handler(CommandHandler("start", start))
#     app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
#     app.add_handler(CallbackQueryHandler(handle_buttons))
#
#     print("🤖 Bot is running...")
#     app.run_polling()
