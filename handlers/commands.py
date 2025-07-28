import logging
from datetime import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ParseMode
from telegram.ext import ContextTypes
import re

import database
from . import login, helpers, proxy_chat

logger = logging.getLogger(__name__)

def escape_markdown(text: str) -> str:
    """Helper function to escape telegram markdown v2 characters."""
    if not isinstance(text, str): text = str(text)
    escape_chars = r'_*[]()~`>#+-=|{}.!'
    return re.sub(f'([{re.escape(escape_chars)}])', r'\\\1', text, )

# --- Navigation Content Generators ---
def get_start_menu_content(context: ContextTypes.DEFAULT_TYPE) -> tuple[str, InlineKeyboardMarkup]:
    welcome_text = escape_markdown(context.bot_data.get('welcome_message', "Welcome!"))
    keyboard = [
        [InlineKeyboardButton("💼 My Balance", callback_data="nav_balance"), InlineKeyboardButton("📋 Countries & Rates", callback_data="nav_cap")],
        [InlineKeyboardButton("📜 Rules", callback_data="nav_rules"), InlineKeyboardButton("🆘 Contact Support", callback_data="nav_support")]
    ]
    return welcome_text, InlineKeyboardMarkup(keyboard)

def get_balance_content(context: ContextTypes.DEFAULT_TYPE, telegram_id: int) -> tuple[str, InlineKeyboardMarkup]:
    summary, balance, _, _, _ = database.get_user_balance_details(telegram_id)
    balance_str = escape_markdown(f"{balance:.2f}")

    msg_parts = [f"📊 *Balance Summary for `{telegram_id}`*", f"💰 *Available Balance: ${balance_str}*"]

    if summary:
        summary_items = []
        for k, v in summary.items():
            status_name = escape_markdown(str(k))
            count = escape_markdown(str(v))
            summary_items.append(f"  \\- {status_name}: {count}")
        summary_text = "\n".join(summary_items)
        msg_parts.append(f"\nAccount Statuses:\n{summary_text}")

    pending_withdrawal_sum = database.fetch_one("SELECT SUM(amount) FROM withdrawals WHERE user_id = ? AND status = 'pending'", (telegram_id,))
    pending_amount = (pending_withdrawal_sum or {'SUM(amount)': 0.0})['SUM(amount)'] or 0.0
    if pending_amount > 0:
        pending_str = escape_markdown(f'{pending_amount:.2f}')
        msg_parts.append(f"\n\n*⏳ You have ${pending_str} in pending withdrawals\\.*")

    min_w = float(context.bot_data.get('min_withdraw', 1.0))
    keyboard_buttons = []

    # Always show withdraw button, but disable if balance is too low
    if balance >= min_w:
        keyboard_buttons.append([InlineKeyboardButton("💳 Withdraw Balance", callback_data="withdraw")])
    else:
        min_w_str = escape_markdown(f"{min_w:.2f}")
        msg_parts.append(f"\n\n*⚠️ Minimum withdrawal amount: ${min_w_str}*")
        keyboard_buttons.append([InlineKeyboardButton("💳 Withdraw Balance", callback_data="withdraw_disabled")])

    keyboard_buttons.append([InlineKeyboardButton("⬅️ Back", callback_data="nav_start")])

    return "\n".join(msg_parts), InlineKeyboardMarkup(keyboard_buttons)

def get_cap_content(context: ContextTypes.DEFAULT_TYPE) -> tuple[str, InlineKeyboardMarkup]:
    countries_config = context.bot_data.get("countries_config", {})
    text = "📋 *Available Countries & Rates*\n\n"
    if countries_config:
        lines = []
        for code, info in sorted(countries_config.items(), key=lambda item: item[1]['name']):
            price_ok_str = escape_markdown(f"{info.get('price_ok', 0.0):.2f}")
            price_restricted_str = escape_markdown(f"{info.get('price_restricted', 0.0):.2f}")

            line = (
                f"{info.get('flag', '🏳️')} `{escape_markdown(code)}` *{escape_markdown(info.get('name', 'N/A'))}*\n"
                f"  \\- OK: `${price_ok_str}` \\| Restricted: `${price_restricted_str}` \\| ⏳{info.get('time', 0) // 60}min"
            )
            lines.append(line)
        text += "\n".join(lines)
    else:
        text += "No countries configured\\."
    return text, InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Back", callback_data="nav_start")]])

def get_rules_content(context: ContextTypes.DEFAULT_TYPE) -> tuple[str, InlineKeyboardMarkup]:
    rules_text = escape_markdown(context.bot_data.get('rules_message', "Rules not set."))
    return rules_text, InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Back", callback_data="nav_start")]])

def get_support_content(context: ContextTypes.DEFAULT_TYPE) -> tuple[str, InlineKeyboardMarkup | None]:
    support_id = context.bot_data.get('support_id', '')
    if support_id.isdigit():
        return "If you have questions or need help, you can talk to support\\. Just send your message here and it will be forwarded\\.", InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Back", callback_data="nav_start")]])
    return f"Support contact not configured correctly\\.", InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Back", callback_data="nav_start")]])

# --- Command Handlers ---
async def balance_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show user's current balance."""
    user_id = update.effective_user.id
    text, keyboard = get_balance_content(context, user_id)
    await helpers.reply_and_mirror(update, context, text, parse_mode=ParseMode.MARKDOWN_V2, reply_markup=keyboard)

async def cap(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text, keyboard = get_cap_content(context)
    await helpers.reply_and_mirror(update, context, text, parse_mode=ParseMode.MARKDOWN_V2, reply_markup=keyboard)

async def rules_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text, keyboard = get_rules_content(context)
    await helpers.reply_and_mirror(update, context, text, parse_mode=ParseMode.MARKDOWN_V2, reply_markup=keyboard)

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    help_text = escape_markdown(context.bot_data.get('help_message', "Help message not set."))
    await helpers.reply_and_mirror(update, context, help_text, parse_mode=ParseMode.MARKDOWN_V2)

# --- Message Handlers ---
async def on_text_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    text = update.message.text.strip()
    user_id = user.id

    # Log user message for admin monitoring (unless it's an admin)
    if not database.is_admin(user_id):
        database.log_user_message(user_id, user.username, text)

    # Check if user is blocked
    user_data = database.get_user_by_id(user_id)
    if user_data and user_data['is_blocked']:
        await update.message.reply_text("🚫 Your account has been restricted. Contact support for assistance.")
        return

    # Handle withdrawal address input
    if context.user_data.get('state') == "waiting_for_address":
        await handle_withdrawal_address(update, context)
        return

    # Handle login flow
    if isinstance(context.user_data.get('login_flow'), dict):
        await login.handle_login(update, context)
        return

    # Check if it's a phone number for login
    if text.startswith("+") and len(text) > 5 and text[1:].isdigit():
        await login.handle_login(update, context)
        return

    # Forward non-admin messages to support
    if not database.is_admin(user_id):
        await proxy_chat.forward_to_admin(update, context)

async def handle_withdrawal_address(update: Update, context: ContextTypes.DEFAULT_TYPE):
    wallet_address = update.message.text.strip()
    telegram_id = update.effective_user.id

    context.user_data.pop('state', None)

    if not wallet_address:
        await helpers.reply_and_mirror(update, context, "❌ The address cannot be empty\\. Please try again or use /cancel\\.", parse_mode=ParseMode.MARKDOWN_V2)
        return

    # MODIFIED: Logic now submits a request, not an instant withdrawal.
    _, total_balance, _, _, _ = database.get_user_balance_details(telegram_id)

    if total_balance <= 0:
        await helpers.reply_and_mirror(update, context, "⚠️ Your available balance for withdrawal is zero\\.", parse_mode=ParseMode.MARKDOWN_V2)
        return

    # This function now creates a PENDING request and returns its ID.
    withdrawal_id = database.process_withdrawal_request(telegram_id, wallet_address, total_balance)

    # Notify user that request is submitted for approval.
    total_balance_str = escape_markdown(f"{total_balance:.2f}")
    msg = (f"✅ *Withdrawal Request Submitted*\n\n"
           f"💰 Amount: *${total_balance_str}*\n"
           f"📬 Address: `{escape_markdown(wallet_address)}`\n\n"
           f"Your request is now pending admin approval\\. You will receive a notification once it has been paid\\.")
    await helpers.reply_and_mirror(update, context, msg, parse_mode=ParseMode.MARKDOWN_V2)

    # Send actionable notification to admin channel.
    admin_channel_id_str = context.bot_data.get('admin_channel')
    admin_channel_id = None
    if admin_channel_id_str and admin_channel_id_str.startswith("@"):
        admin_channel_id = admin_channel_id_str
    elif admin_channel_id_str and admin_channel_id_str.lstrip('-').isdigit():
        admin_channel_id = int(admin_channel_id_str)

    if admin_channel_id:
        try:
            keyboard = InlineKeyboardMarkup([[
                InlineKeyboardButton("✅ Mark as Paid", callback_data=f"admin_confirm_withdrawal:{withdrawal_id}")
            ]])
            admin_msg = (f"💸 *New Withdrawal Request*\n\n"
                         f"👤 User: @{escape_markdown(update.effective_user.username)} \\(`{telegram_id}`\\)\n"
                         f"💰 Amount: *${total_balance_str}*\n"
                         f"📬 Address: `{escape_markdown(wallet_address)}`")
            await context.bot.send_message(admin_channel_id, admin_msg, parse_mode=ParseMode.MARKDOWN_V2, reply_markup=keyboard)
        except Exception as e:
            logger.error(f"Failed to send admin withdrawal notification to {admin_channel_id}: {e}")

async def cancel_operation(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if 'login_flow' in context.user_data:
        await login.cleanup_login_flow(context)
    context.user_data.clear()
    await helpers.reply_and_mirror(update, context, "✅ Operation canceled\\.", parse_mode=ParseMode.MARKDOWN_V2)

async def balance_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user, _ = database.get_or_create_user(user_id, update.effective_user.username)

    if user.get('is_blocked'):
        await update.message.reply_text("🚫 Your account has been blocked. Contact support for assistance.")
        return

    account_summary, total_balance, earned_balance, manual_adjustment, withdrawable_accounts = database.get_user_balance_details(user_id)

    if not account_summary:
        await update.message.reply_text("💰 **Your Balance: $0.00**\n\nYou haven't added any accounts yet. Send a phone number to get started!", parse_mode=ParseMode.MARKDOWN)
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

    await update.message.reply_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=ParseMode.MARKDOWN)

async def on_text_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handles all text messages from users."""
    user_id = update.effective_user.id
    username = update.effective_user.username
    message_text = update.message.text

    # Check if user is blocked
    user, is_new_user = database.get_or_create_user(user_id, username)
    if user['is_blocked']:
        return

    # Log the message for admin support
    database.log_user_message(user_id, username, message_text)

    # Handle withdrawal flow
    if context.user_data.get('state') == "waiting_for_address":
        await handle_withdrawal_address(update, context)
        return

    # Check if it's a phone number
    phone_pattern = r'^\+\d{10,15}$'
    if re.match(phone_pattern, message_text.strip()):
        await login.handle_login(update, context)
    else:
        # Forward message to support
        await proxy_chat.forward_to_admin(update, context)

async def show_account_status_with_confirmation(update: Update, context: ContextTypes.DEFAULT_TYPE, user_id: int):
    """Show account status with confirmation buttons for pending accounts"""
    pending_accounts = database.get_pending_accounts_for_user(user_id)

    if not pending_accounts:
        return

    for account in pending_accounts:
        time_remaining = account.get('time_remaining', 0)

        if time_remaining > 0:
            phone = account['phone_number']
            minutes = time_remaining // 60
            seconds = time_remaining % 60

            # Get country info for pricing
            all_countries = database.get_countries_config()
            country_info, _ = login._get_country_info(phone, all_countries)
            price = country_info.get('price_ok', 0.0) if country_info else 0.0

            text = f"⏳ *Account Verification*\n\n"
            text += f"📱 Number: `{escape_markdown(phone)}`\n"
            text += f"💰 Price: `${escape_markdown(f'{price:.2f}')}`\n"
            text += f"⏰ Remaining: *{minutes:02d}:{seconds:02d}*\n\n"
            text += f"The bot will automatically verify your account\\."

            keyboard = InlineKeyboardMarkup([
                [InlineKeyboardButton("⏱️ Check Status", callback_data=f"check_account_status:{account['job_id']}")]
            ])

            await update.message.reply_text(
                text,
                reply_markup=keyboard,
                parse_mode=ParseMode.MARKDOWN_V2
            )