# Adding missing callback handlers for balance and withdraw functionality.
import logging
from telegram import Update
from telegram.ext import ContextTypes
from telegram.constants import ParseMode
from telegram.error import BadRequest
import re

import database
from . import commands
from . import helpers

logger = logging.getLogger(__name__)

def escape_markdown(text: str) -> str:
    """Helper function to escape telegram markdown v2 characters."""
    if not isinstance(text, str): text = str(text)
    escape_chars = r'_*[]()~`>#+-=|{}.!'
    return re.sub(f'([{re.escape(escape_chars)}])', r'\\\1', text)

async def on_callback_query(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handles all non-admin callback queries from inline buttons."""
    query = update.callback_query
    if not query or not query.data: return

    if query.data.startswith("admin_"):
        await query.answer()
        logger.debug(f"Ignoring admin callback '{query.data}' in user handler.")
        return

    try:
        await query.answer()
    except Exception as e:
        logger.warning(f"Failed to answer callback query for data {query.data}: {e}")

    data = query.data
    user_id = query.from_user.id

    text, keyboard = None, None

    if data == "nav_start": text, keyboard = commands.get_start_menu_content(context)
    elif data == "nav_balance": text, keyboard = commands.get_balance_content(context, user_id)
    elif data == "nav_cap": text, keyboard = commands.get_cap_content(context)
    elif data == "nav_rules": text, keyboard = commands.get_rules_content(context)
    elif data == "nav_support": text, keyboard = commands.get_support_content(context)
    elif data == "withdraw":
        await handle_withdraw_request(update, context)
        return
    elif data == "withdraw_disabled":
        min_withdraw = float(context.bot_data.get('min_withdraw', 1.0))
        min_withdraw_str = escape_markdown(f"{min_withdraw:.2f}")
        await query.answer(f"⚠️ Minimum withdrawal amount is ${min_withdraw_str}", show_alert=True)
        return
    else:
        logger.info(f"[USER] Unhandled callback query from {user_id}: {data}")
        return

    if text and keyboard:
        try:
            await helpers.reply_and_mirror(
                update, context, text=text,
                reply_markup=keyboard,
                parse_mode=ParseMode.MARKDOWN_V2,
                disable_web_page_preview=True,
                edit_original=True
            )
        except BadRequest as e:
            if "Message is not modified" not in str(e).lower():
                logger.error(f"Error editing message for callback {data}: {e}")

async def handle_withdraw_request(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = update.effective_user.id

    # Check if user has sufficient balance
    _, balance, _, _, _ = database.get_user_balance_details(user_id)
    min_withdraw = float(context.bot_data.get('min_withdraw', 1.0))

    if balance < min_withdraw:
        balance_str = escape_markdown(f"{balance:.2f}")
        min_withdraw_str = escape_markdown(f"{min_withdraw:.2f}")
        await query.edit_message_text(
            f"❌ *Insufficient Balance*\n\nYour balance: *\\${balance_str}*\nMinimum withdrawal: *\\${min_withdraw_str}*",
            parse_mode=ParseMode.MARKDOWN_V2
        )
        return

    # Ask for wallet address
    context.user_data['state'] = "waiting_for_address"
    balance_str = escape_markdown(f"{balance:.2f}")
    await query.edit_message_text(
        f"💳 *Withdrawal Request*\n\nAvailable balance: *\\${balance_str}*\n\nPlease send your wallet address to continue\\.\nType /cancel to abort\\.",
        parse_mode=ParseMode.MARKDOWN_V2
    )

async def handle_admin_withdrawal_confirmation(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    withdrawal_id = int(query.data.split(':')[1])

    withdrawal = database.confirm_withdrawal(withdrawal_id)
    if not withdrawal:
        await query.edit_message_text("❌ Withdrawal request not found or already processed.")
        return

    # Notify user
    try:
        user_id = withdrawal['user_id']
        amount_str = escape_markdown(f"{withdrawal['amount']:.2f}")
        address_str = escape_markdown(withdrawal['address'])

        await context.bot.send_message(
            user_id,
            f"✅ *Withdrawal Completed*\n\n💰 Amount: *${amount_str}*\n📬 Address: `{address_str}`\n\nYour withdrawal has been processed successfully\\.",
            parse_mode=ParseMode.MARKDOWN_V2
        )
    except Exception as e:
        logger.error(f"Failed to notify user about withdrawal completion: {e}")

    # Update admin message
    await query.edit_message_text(
        f"✅ *Withdrawal Confirmed*\n\nWithdrawal ID: `{withdrawal_id}`\nAmount: `${withdrawal['amount']:.2f}`\nProcessed successfully.",
        parse_mode=ParseMode.MARKDOWN_V2
    )

from telegram import InlineKeyboardButton, InlineKeyboardMarkup
async def handle_balance_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    user_id = update.effective_user.id
    account_summary, total_balance, earned_balance, manual_adjustment, withdrawable_accounts = database.get_user_balance_details(user_id)

    if not account_summary:
        await query.edit_message_text("💰 **Your Balance: $0.00**\n\nYou haven't added any accounts yet. Send a phone number to get started!", parse_mode=ParseMode.MARKDOWN)
        return

    summary_text = "\n".join([f"• {status.title()}: {count}" for status, count in account_summary.items()])

    text = f"💰 **Your Balance Details**\n\n💵 **Total Balance: ${total_balance:.2f}**\n\n📊 **Account Summary:**\n{summary_text}\n\n💎 **Earned Balance: ${earned_balance:.2f}**"

    if manual_adjustment != 0:
        adjustment_text = f"➕ Manual Adjustment: ${manual_adjustment:.2f}" if manual_adjustment > 0 else f"➖ Manual Adjustment: ${abs(manual_adjustment):.2f}"
        text += f"\n{adjustment_text}"

    keyboard = []
    if total_balance >= float(context.bot_data.get('min_withdraw', '1.0')):
        keyboard.append([InlineKeyboardButton("💸 Withdraw", callback_data="withdraw_start")])

    keyboard.append([InlineKeyboardButton("🔄 Refresh", callback_data="refresh_balance")])

    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=ParseMode.MARKDOWN)

async def handle_withdraw_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    user_id = update.effective_user.id
    _, total_balance, _, _, _ = database.get_user_balance_details(user_id)

    min_withdraw = float(context.bot_data.get('min_withdraw', '1.0'))
    max_withdraw = float(context.bot_data.get('max_withdraw', '100.0'))

    if total_balance < min_withdraw:
        await query.answer(f"❌ Minimum withdrawal amount is ${min_withdraw:.2f}", show_alert=True)
        return

    text = f"💸 **Withdrawal Request**\n\n💰 Available Balance: ${total_balance:.2f}\n💎 Min: ${min_withdraw:.2f} | Max: ${max_withdraw:.2f}\n\n📝 Please send your withdrawal address (TRC20/USDT):"

    context.user_data['withdrawal_balance'] = total_balance
    context.user_data['withdrawal_step'] = 'address'

    await query.edit_message_text(text, parse_mode=ParseMode.MARKDOWN)

async def handle_callback_query(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle general callback queries."""
    query = update.callback_query
    await query.answer()
    
    data = query.data
    if data == "countries_rates":
        # Handle countries rates callback
        pass
    elif data == "rules":
        # Handle rules callback
        pass
    elif data == "contact_support":
        # Handle contact support callback
        pass
    elif data in ["confirm_withdrawal", "cancel_withdrawal"]:
        # Handle withdrawal confirmation callbacks
        pass

from telegram.ext import CallbackQueryHandler
def get_callback_handlers():
    return [
        CallbackQueryHandler(handle_balance_callback, pattern="^my_balance$"),
        CallbackQueryHandler(handle_balance_callback, pattern="^refresh_balance$"),
        CallbackQueryHandler(handle_withdraw_start, pattern="^withdraw_start$"),
        CallbackQueryHandler(on_callback_query, pattern="^(countries_rates|rules|contact_support|confirm_withdrawal|cancel_withdrawal)$")
    ]