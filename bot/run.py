from aiogram import Bot, Dispatcher
from aiogram.enums import ParseMode
from aiogram.filters.command import Command, CommandStart
from aiogram.types import Message
from aiogram import F
from aiogram.utils.keyboard import InlineKeyboardBuilder
from func.functions import *
import asyncio
import traceback
import io
import base64

bot = Bot(token=token)
dp = Dispatcher()
prompt_prefix = os.getenv("PROMPT_PREFIX")

# Context variables for OllamaAPI
ACTIVE_CHATS = {}
ACTIVE_CHATS_LOCK = contextLock()
modelname = os.getenv("INITMODEL")
mention = None

# Telegram group types
CHAT_TYPE_GROUP = "group"
CHAT_TYPE_SUPERGROUP = "supergroup"

def is_mentioned_in_group(message):
    return (message.chat.type in [CHAT_TYPE_GROUP, CHAT_TYPE_SUPERGROUP] and (message.text.find(mention) >=0))

async def get_bot_info():
    global mention
    if mention is None:
        get = await bot.get_me()
        mention = (f"@{get.username}")
    return mention

# React on message | LLM will respond on user's message or mention in groups
@dp.message()
@perms_allowed
async def handle_message(message: types.Message):
    await get_bot_info()
    if message.chat.type == "private":
        await ollama_request(message)

    if is_mentioned_in_group(message):
        await ollama_request(types.Message(
            message_id=message.message_id,
            from_user=message.from_user,
            date=message.date,
            chat=message.chat,
            text=f'The following message was received in a group and you were explicitly mentioned: {message.text}'
        ))

async def ollama_request(message: types.Message):
    try:
        await bot.send_chat_action(message.chat.id, "typing")
        prompt = message.text or message.caption
        image_base64 = ''
        if message.content_type == 'photo':
            image_buffer = io.BytesIO()
            await bot.download(
                message.photo[-1],
                destination=image_buffer
            )
            image_base64 = base64.b64encode(image_buffer.getvalue()).decode('utf-8')
        full_response = ""

        async with ACTIVE_CHATS_LOCK:
            # Add prompt to active chats object
            if ACTIVE_CHATS.get(message.from_user.id) is None:
                ACTIVE_CHATS[message.from_user.id] = {
                    "model": modelname,
                    "messages": [{"role": "user", "content": f'{prompt_prefix} {message.from_user.first_name} is speaking to you and said the following: {prompt}', "images": ([image_base64] if image_base64 else [])}],
                    "stream": True,
                }
            else:
                ACTIVE_CHATS[message.from_user.id]["messages"].append(
                    {"role": "user", "content": prompt, "images": ([image_base64] if image_base64 else [])}
                )
        logging.info(
            f"[Request]: Processing '{prompt}' for {message.from_user.first_name} {message.from_user.last_name}"
        )
        payload = ACTIVE_CHATS.get(message.from_user.id)
        async for response_data in generate(payload, modelname, prompt):
            msg = response_data.get("message")
            if msg is None:
                continue
            chunk = msg.get("content", "")
            full_response += chunk

            if response_data.get("done"):
                full_response_stripped = full_response.strip().replace("As Isabelle Talbot", "").replace("As an AI", "").replace("Isabelle Talbot: ", "")
                # Check if there's any response to send
                if full_response_stripped:
                    await bot.send_message(
                        chat_id=message.chat.id,
                        text=md_autofixer(
                            full_response_stripped
                        ),
                        parse_mode=ParseMode.MARKDOWN_V2,
                        reply_to_message_id=message.message_id,
                    )
                    logging.info(f"\n\nCurrent Model: `{modelname}`**\n**Generated in {response_data.get('total_duration') / 1e9:.2f}s")
                    async with ACTIVE_CHATS_LOCK:
                        if ACTIVE_CHATS.get(message.from_user.id) is not None:
                            # Add response to active chats object
                            ACTIVE_CHATS[message.from_user.id]["messages"].append(
                                {"role": "assistant", "content": full_response_stripped}
                            )
                            logging.info(
                                f"[Response]: '{full_response_stripped}' for {message.from_user.first_name} {message.from_user.last_name}"
                            )
                break
    except Exception as e:
        await bot.send_message(
            chat_id=message.chat.id,
            text="i'm having some issues now and may not respond. sorry.",
            parse_mode=ParseMode.MARKDOWN_V2,
        )
        logging.info(f"""Error occurred\n```\n{traceback.format_exc()}\n```""")


async def main():
    await dp.start_polling(bot, skip_update=True)


if __name__ == "__main__":
    asyncio.run(main())
