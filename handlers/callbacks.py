import logging
from datetime import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ParseMode
from telegram.ext import ContextTypes
import re

import database
from . import login, helpers

logger = logging.getLogger(__name__)

def escape_markdown(text: str) -> str:
    """Helper function to escape telegram markdown v2 characters."""
    if not isinstance(text, str): 
        text = str(text)
    escape_chars = r'_*[]()~`>#+-=|{}.!'
    return re.sub(f'([{re.escape(escape_chars)}])', r'\\\1', text)

async def handle_callback_query(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    data = query.data

    try:
        await query.answer()

        # Account verification status check
        if data.startswith("check_account_status:"):
            await handle_account_status_check(update, context)
            return

        # Navigation callbacks
        if data == "nav_start":
            from .commands import get_start_menu_content
            text, keyboard = get_start_menu_content(context)
            await query.edit_message_text(text, reply_markup=keyboard, parse_mode=ParseMode.MARKDOWN_V2)

        elif data == "nav_balance":
            from .commands import get_balance_content
            text, keyboard = get_balance_content(update.effective_user.id)
            await query.edit_message_text(text, reply_markup=keyboard, parse_mode=ParseMode.MARKDOWN_V2)

        elif data == "nav_cap":
            from .commands import get_cap_content
            text, keyboard = get_cap_content()
            await query.edit_message_text(text, reply_markup=keyboard, parse_mode=ParseMode.MARKDOWN_V2)

        elif data == "nav_rules":
            from .commands import get_rules_content
            text, keyboard = get_rules_content(context)
            await query.edit_message_text(text, reply_markup=keyboard, parse_mode=ParseMode.MARKDOWN_V2)

        elif data == "nav_support":
            support_text = escape_markdown(context.bot_data.get('support_message', "Contact our support team for assistance."))
            keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Back to Menu", callback_data="nav_start")]])
            await query.edit_message_text(support_text, reply_markup=keyboard, parse_mode=ParseMode.MARKDOWN_V2)

        # Withdrawal callbacks
        elif data == "withdraw_start":
            user_id = update.effective_user.id
            account_summary, total_balance, earned_balance, manual_adjustment, withdrawable_accounts = database.get_user_balance_details(user_id)

            min_withdraw = float(database.get_setting('min_withdraw', 1.0))
            max_withdraw = float(database.get_setting('max_withdraw', 100.0))

            if total_balance < min_withdraw:
                await query.answer(f"Minimum withdrawal amount is ${min_withdraw:.2f}", show_alert=True)
                return

            available_amount = min(total_balance, max_withdraw)
            text = f"💸 *Withdrawal Request*\n\n💰 Available Balance: `${escape_markdown(f'{total_balance:.2f}')}`\n💵 Withdrawal Amount: `${escape_markdown(f'{available_amount:.2f}')}`\n\nPlease send your wallet address to proceed\\."

            context.user_data['withdrawal_amount'] = available_amount
            context.user_data['state'] = "waiting_for_address"

            keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("❌ Cancel", callback_data="nav_balance")]])
            await query.edit_message_text(text, reply_markup=keyboard, parse_mode=ParseMode.MARKDOWN_V2)

    except Exception as e:
        logger.error(f"Error in callback handler: {e}", exc_info=True)
        await query.answer("❌ An error occurred. Please try again.", show_alert=True)

async def handle_account_status_check(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle account status check button"""
    query = update.callback_query
    job_id = query.data.split(':')[-1]

    account = database.get_account_time_remaining(job_id)

    if not account:
        await query.answer("Account not found or already processed!", show_alert=True)
        return

    time_remaining = account.get('time_remaining', 0)
    phone = account['phone_number']

    if time_remaining <= 0:
        await query.answer("⏰ Time expired! Processing will begin shortly.", show_alert=True)
        return

    # Format time remaining
    minutes = time_remaining // 60
    seconds = time_remaining % 60

    # Show dynamic popup with exact time
    await query.answer(
        f"👆 You must wait for {minutes * 60 + seconds} seconds more.", 
        show_alert=True
    )

    # Update the message with current countdown
    all_countries = database.get_countries_config()
    country_info, _ = login._get_country_info(phone, all_countries)
    price = country_info.get('price_ok', 0.0) if country_info else 0.0

    text = f"⏳ *Account Verification*\n\n"
    text += f"📱 Number: `{escape_markdown(phone)}`\n"
    text += f"💰 Price: `${escape_markdown(f'{price:.2f}')}`\n"
    text += f"⏰ Remaining: *{minutes:02d}:{seconds:02d}*\n\n"
    text += f"🔍 Spam Status: 🟡 New Registration\n\n"
    text += f"👆 The bot will automatically verify your account\\."

    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ Account Verification", callback_data=f"check_account_status:{job_id}")]
    ])

    try:
        await query.edit_message_text(
            text,
            reply_markup=keyboard,
            parse_mode=ParseMode.MARKDOWN_V2
        )
    except Exception as e:
        logger.error(f"Error updating countdown message: {e}")