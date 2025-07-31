
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
    if not isinstance(text, str): 
        text = str(text)
    escape_chars = r'_*[]()~`>#+-=|{}.!'
    return re.sub(f'([{re.escape(escape_chars)}])', r'\\\1', text)

# --- Navigation Content Generators ---
def get_start_menu_content(context: ContextTypes.DEFAULT_TYPE) -> tuple[str, InlineKeyboardMarkup]:
    welcome_text = escape_markdown(context.bot_data.get('welcome_message', "Welcome!"))
    keyboard = [
        [InlineKeyboardButton("💼 My Balance", callback_data="nav_balance"), InlineKeyboardButton("📋 Countries & Rates", callback_data="nav_cap")],
        [InlineKeyboardButton("📜 Rules", callback_data="nav_rules"), InlineKeyboardButton("🆘 Contact Support", callback_data="nav_support")]
    ]
    return welcome_text, InlineKeyboardMarkup(keyboard)

def get_balance_content(user_id: int) -> tuple[str, InlineKeyboardMarkup]:
    account_summary, total_balance, earned_balance, manual_adjustment, withdrawable_accounts = database.get_user_balance_details(user_id)
    
    if not account_summary:
        text = "💼 *Your Balance*\n\n💰 Current Balance: `$0.00`\n\n📦 You haven't added any accounts yet\\. Send a phone number to get started\\!"
        keyboard = [[InlineKeyboardButton("📋 Countries & Rates", callback_data="nav_cap")], [InlineKeyboardButton("⬅️ Back to Menu", callback_data="nav_start")]]
    else:
        account_count = sum(account_summary.values())
        status_emojis = {'ok': '✅', 'restricted': '⚠️', 'banned': '🚫', 'limited': '⏳', 'error': '❌', 'pending_confirmation': '⏳', 'pending_session_termination': '🔄', 'withdrawn': '💸'}
        
        text = f"💼 *Your Balance*\n\n💰 Current Balance: `${escape_markdown(f'{total_balance:.2f}')}`\n📦 Total Accounts: `{account_count}`\n\n📊 *Account Status:*\n"
        for status, count in account_summary.items():
            emoji = status_emojis.get(status, '❓')
            text += f"{emoji} {escape_markdown(status.replace('_', ' ').title())}: `{count}`\n"
        
        keyboard = []
        if total_balance >= float(database.get_setting('min_withdraw', 1.0)):
            keyboard.append([InlineKeyboardButton("💸 Withdraw Funds", callback_data="withdraw_start")])
        
        keyboard.extend([
            [InlineKeyboardButton("📋 Countries & Rates", callback_data="nav_cap")],
            [InlineKeyboardButton("⬅️ Back to Menu", callback_data="nav_start")]
        ])
    
    return text, InlineKeyboardMarkup(keyboard)

def get_cap_content() -> tuple[str, InlineKeyboardMarkup]:
    countries = database.get_countries_config()
    if not countries:
        text = "📋 *Countries & Rates*\n\nNo countries configured\\."
        keyboard = [[InlineKeyboardButton("⬅️ Back to Menu", callback_data="nav_start")]]
        return text, InlineKeyboardMarkup(keyboard)
    
    text = "📋 *Countries & Rates*\n\nHere are the supported countries and their rates:\n\n"
    
    for country_data in sorted(countries.values(), key=lambda x: x['name']):
        flag = country_data.get('flag', '')
        name = escape_markdown(country_data['name'])
        code = escape_markdown(country_data['code'])
        price_ok = escape_markdown(f"{country_data.get('price_ok', 0.0):.2f}")
        price_restricted = escape_markdown(f"{country_data.get('price_restricted', 0.0):.2f}")
        capacity = country_data.get('capacity', -1)
        
        current_count = database.get_country_account_count(country_data['code'])
        capacity_text = "Unlimited" if capacity == -1 else f"{current_count}/{capacity}"
        
        text += f"{flag} *{name}* \\({code}\\)\n"
        text += f"✅ Free: `${price_ok}`\n"
        text += f"⚠️ Register: `${price_restricted}`\n"
        text += f"📦 Capacity: {escape_markdown(capacity_text)}\n\n"
    
    keyboard = [[InlineKeyboardButton("⬅️ Back to Menu", callback_data="nav_start")]]
    return text, InlineKeyboardMarkup(keyboard)

def get_rules_content(context: ContextTypes.DEFAULT_TYPE) -> tuple[str, InlineKeyboardMarkup]:
    rules_text = escape_markdown(context.bot_data.get('rules_message', "Rules not set."))
    keyboard = [[InlineKeyboardButton("⬅️ Back to Menu", callback_data="nav_start")]]
    return rules_text, InlineKeyboardMarkup(keyboard)

# --- Command Handlers ---
async def balance_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    
    # Check if user is blocked
    user_data = database.get_user_by_id(user_id)
    if user_data and user_data['is_blocked']:
        await update.message.reply_text("🚫 Your account has been restricted. Contact support for assistance.")
        return
    
    try:
        text, keyboard = get_balance_content(user_id)
        await helpers.reply_and_mirror(update, context, text, parse_mode=ParseMode.MARKDOWN_V2, reply_markup=keyboard)
    except Exception as e:
        logger.error(f"Error in balance_cmd: {e}", exc_info=True)
        await update.message.reply_text("❌ An error occurred while fetching your balance. Please try again later.")

async def cap(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        text, keyboard = get_cap_content()
        await helpers.reply_and_mirror(update, context, text, parse_mode=ParseMode.MARKDOWN_V2, reply_markup=keyboard)
    except Exception as e:
        logger.error(f"Error in cap command: {e}", exc_info=True)
        await update.message.reply_text("❌ An error occurred while fetching country rates. Please try again later.")

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        help_text = escape_markdown(context.bot_data.get('help_message', "Help message not set."))
        await helpers.reply_and_mirror(update, context, help_text, parse_mode=ParseMode.MARKDOWN_V2)
    except Exception as e:
        logger.error(f"Error in help_command: {e}", exc_info=True)
        await update.message.reply_text("❌ An error occurred while fetching help information.")

async def rules_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        text, keyboard = get_rules_content(context)
        await helpers.reply_and_mirror(update, context, text, parse_mode=ParseMode.MARKDOWN_V2, reply_markup=keyboard)
    except Exception as e:
        logger.error(f"Error in rules_command: {e}", exc_info=True)
        await update.message.reply_text("❌ An error occurred while fetching rules.")

async def cancel_operation(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        # Clear any ongoing operations
        if 'login_flow' in context.user_data:
            await login.cleanup_login_flow(context)
        
        context.user_data.clear()
        
        text, keyboard = get_start_menu_content(context)
        await helpers.reply_and_mirror(update, context, text, parse_mode=ParseMode.MARKDOWN_V2, reply_markup=keyboard)
    except Exception as e:
        logger.error(f"Error in cancel_operation: {e}", exc_info=True)
        await update.message.reply_text("✅ Operation cancelled.")

# --- Withdrawal Handlers ---
async def handle_withdrawal_address(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    address = update.message.text.strip()
    
    try:
        # Validate address format (basic validation)
        if len(address) < 10 or len(address) > 100:
            await update.message.reply_text("❌ Invalid address format. Please enter a valid wallet address.")
            return
        
        amount = context.user_data.get('withdrawal_amount')
        if not amount:
            await update.message.reply_text("❌ Withdrawal session expired. Please start over.")
            context.user_data.clear()
            return
        
        # Process withdrawal
        withdrawal_id = database.process_withdrawal_request(user_id, address, amount)
        
        if withdrawal_id:
            context.user_data.clear()
            await update.message.reply_text(
                f"✅ Withdrawal request submitted!\n\n"
                f"💰 Amount: ${amount:.2f}\n"
                f"📬 Address: `{escape_markdown(address)}`\n"
                f"🆔 Request ID: #{withdrawal_id}\n\n"
                f"Your request is being processed and will be completed within 24 hours.",
                parse_mode=ParseMode.MARKDOWN_V2
            )
            
            # Notify admin about withdrawal
            try:
                admin_channel = context.bot_data.get('admin_channel')
                if admin_channel:
                    user = update.effective_user
                    admin_text = f"💸 *New Withdrawal Request*\n\n"
                    admin_text += f"👤 User: @{escape_markdown(user.username or 'N/A')} \\(`{user.id}`\\)\n"
                    admin_text += f"💰 Amount: `${amount:.2f}`\n"
                    admin_text += f"📬 Address: `{escape_markdown(address)}`\n"
                    admin_text += f"🆔 Request ID: `#{withdrawal_id}`\n"
                    admin_text += f"📅 Time: `{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}`"
                    
                    confirm_keyboard = InlineKeyboardMarkup([
                        [InlineKeyboardButton("✅ Mark as Paid", callback_data=f"admin_confirm_withdrawal:{withdrawal_id}")]
                    ])
                    
                    await context.bot.send_message(
                        chat_id=admin_channel,
                        text=admin_text,
                        parse_mode=ParseMode.MARKDOWN_V2,
                        reply_markup=confirm_keyboard
                    )
            except Exception as e:
                logger.error(f"Failed to notify admin about withdrawal: {e}")
        else:
            await update.message.reply_text("❌ Failed to process withdrawal request. Please try again later.")
            
    except Exception as e:
        logger.error(f"Error in handle_withdrawal_address: {e}", exc_info=True)
        await update.message.reply_text("❌ An error occurred while processing your withdrawal. Please try again later.")
        context.user_data.clear()

# --- Message Handlers ---
async def on_text_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    text = update.message.text.strip()
    user_id = user.id

    try:
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
            # Validate phone number format
            phone_pattern = r'^\+\d{10,15}$'
            if re.match(phone_pattern, text):
                await login.handle_login(update, context)
                return
            else:
                await update.message.reply_text(
                    "❌ Invalid phone number format. Please use international format (e.g., +12345678901)."
                )
                return
        
        # If not handled above, forward to support
        await proxy_chat.forward_to_admin(update, context)
        
    except Exception as e:
        logger.error(f"Error in on_text_message: {e}", exc_info=True)
        await update.message.reply_text("❌ An error occurred. Please try again or contact support.")

async def show_account_status_with_confirmation(update: Update, context: ContextTypes.DEFAULT_TYPE, user_id: int):
    """Show account status with confirmation buttons for pending accounts"""
    try:
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
                country_info = None
                for code, info in all_countries.items():
                    if phone.startswith(code):
                        country_info = info
                        break

                if country_info:
                    price_text = f"${country_info.get('price_ok', 0.0):.2f}"
                else:
                    price_text = "TBD"

                time_text = f"{minutes}m {seconds}s" if minutes > 0 else f"{seconds}s"
                
                text = f"⏳ *Account Pending Confirmation*\n\n"
                text += f"📱 Phone: `{escape_markdown(phone)}`\n"
                text += f"💰 Reward: `{price_text}`\n"
                text += f"⏰ Time Remaining: `{time_text}`\n\n"
                text += "Your account is being verified. You'll be notified once complete."

                await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN_V2)
                
    except Exception as e:
        logger.error(f"Error in show_account_status_with_confirmation: {e}", exc_info=True)
