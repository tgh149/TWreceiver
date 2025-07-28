import logging, asyncio, os, re, zipfile, json
from enum import Enum, auto
from functools import wraps
from datetime import datetime, timedelta
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, InputFile, User
from telegram.ext import ContextTypes, ConversationHandler, CommandHandler, MessageHandler, filters, CallbackQueryHandler
from telegram.constants import ParseMode
from telegram.error import BadRequest
from telethon import TelegramClient
from telethon.errors import SessionPasswordNeededError
import database
from handlers import login, helpers
from config import BOT_TOKEN, SESSION_LOG_CHANNEL_ID

logger = logging.getLogger(__name__)

class AdminState(Enum):
    GET_USER_INFO_ID, BLOCK_USER_ID, UNBLOCK_USER_ID, ADD_ADMIN_ID, REMOVE_ADMIN_ID, BROADCAST_MSG, BROADCAST_CONFIRM, ADD_PROXY, REMOVE_PROXY_ID, EDIT_SETTING_VALUE, ADD_COUNTRY_CODE, ADD_COUNTRY_NAME, ADD_COUNTRY_FLAG, ADD_COUNTRY_PRICE_OK, ADD_COUNTRY_PRICE_RESTRICTED, ADD_COUNTRY_TIME, ADD_COUNTRY_CAPACITY, DELETE_COUNTRY_CODE, DELETE_COUNTRY_CONFIRM, DELETE_USER_DATA_ID, DELETE_USER_DATA_CONFIRM, RECHECK_BY_USER_ID, EDIT_COUNTRY_VALUE, EDIT_SETTING_START, ADJ_BALANCE_ID, ADJ_BALANCE_AMOUNT, FM_PHONE, FM_CODE, FM_PASSWORD, ADD_API_ID, ADD_API_HASH, REMOVE_API_ID, LIVE_CHAT_REPLY, RESET_DATABASE_CONFIRM = auto(),auto(),auto(),auto(),auto(),auto(),auto(),auto(),auto(),auto(),auto(),auto(),auto(),auto(),auto(),auto(),auto(),auto(),auto(),auto(),auto(),auto(),auto(),auto(),auto(),auto(),auto(),auto(),auto(),auto(),auto(),auto(),auto(),auto()
    BROADCAST_SINGLE_USER_ID = auto()
    BROADCAST_SINGLE_MESSAGE = auto()
    ADD_COUNTRY_STEP_2 = auto()
    ADD_COUNTRY_STEP_3 = auto()
    ADD_COUNTRY_STEP_4 = auto()
    ADD_COUNTRY_STEP_5 = auto()
    ADD_COUNTRY_STEP_6 = auto()
    ADD_COUNTRY_STEP_7 = auto()

def escape_markdown(text: str) -> str:
    if not isinstance(text, str): 
        text = str(text)
    escape_chars = r'_*[]()~`>#+-=|{}.!'
    return re.sub(f'([{re.escape(escape_chars)}])', r'\\\1', text)

def admin_required(func):
    @wraps(func)
    async def wrapped(update, context, *args, **kwargs):
        user_id = update.effective_user.id
        if not database.is_admin(user_id):
            if update.callback_query: 
                await update.callback_query.answer("🚫 Access Denied", show_alert=True)
            return
        return await func(update, context, *args, **kwargs)
    return wrapped

async def try_edit_message(query, text, reply_markup):
    try: 
        if query and query.message:
            await query.answer() 
            await query.edit_message_text(text, reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN_V2, disable_web_page_preview=True)
    except BadRequest as e:
        if "Message is not modified" not in str(e).lower(): 
            logger.error(f"Error editing message for cb {getattr(query, 'data', 'unknown')}: {e}. Text: {text}")

def create_pagination_keyboard(prefix, current_page, total_items, item_per_page=5):
    btns, total_pages = [], (total_items + item_per_page - 1) // item_per_page if total_items > 0 else 1
    if total_pages <= 1: return []
    row = []
    if current_page > 1: row.append(InlineKeyboardButton("⬅️ Prev", callback_data=f"{prefix}_{current_page-1}"))
    if current_page < total_pages: row.append(InlineKeyboardButton("Next ➡️", callback_data=f"{prefix}_{current_page+1}"))
    if row: btns.append(row)
    return btns

async def get_main_admin_keyboard():
    unread_count = database.get_unread_message_count()
    chat_text = f"💬 Live Chat ({unread_count})" if unread_count > 0 else "💬 Live Chat"

    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🎯 TWFOCUS Management Dashboard", callback_data="admin_dashboard")],
        [InlineKeyboardButton("📊 Bot Statistics", callback_data="admin_stats"), InlineKeyboardButton("⚙️ Bot Settings", callback_data="admin_settings_main")],
        [InlineKeyboardButton("👥 User Management", callback_data="admin_users_main_page_1"), InlineKeyboardButton("🌐 Country Management", callback_data="admin_country_list")],
        [InlineKeyboardButton("📦 Account Management", callback_data="admin_confirm_main"), InlineKeyboardButton("💰 Financial Management", callback_data="admin_finance_main")],
        [InlineKeyboardButton("📢 Messaging", callback_data="admin_broadcast_main"), InlineKeyboardButton("🔧 System & Data", callback_data="admin_system_main")],
        [InlineKeyboardButton("👑 Admin Management", callback_data="admin_admins_main"), InlineKeyboardButton("🗂️ File Manager", callback_data="admin_fm_main")],
        [InlineKeyboardButton(chat_text, callback_data="admin_live_chat_main")]
    ])

async def cancel_conv(update, context):
    context.user_data.clear()
    await update.message.reply_text("✅ Operation cancelled\\.")
    await update.message.reply_text("👑 *Super Admin Panel*", parse_mode=ParseMode.MARKDOWN_V2, reply_markup=await get_main_admin_keyboard())
    return ConversationHandler.END

class FakeCallbackQuery:
    def __init__(self, update_or_query_obj, data):
        self.message = update_or_query_obj.message
        self.data = data
        self.from_user = getattr(update_or_query_obj, 'from_user', None) or getattr(update_or_query_obj, 'effective_user', None)
    async def answer(self, *args, **kwargs): pass
    async def edit_message_text(self, text, reply_markup, **kwargs): await self.message.reply_text(text, reply_markup=reply_markup, **kwargs)

# --- Admin Panel Main Sections (Restored) ---
@admin_required
async def admin_panel(update, context):
    if update.callback_query: 
        await update.callback_query.answer()

    stats = database.get_bot_stats()
    unread_count = database.get_unread_message_count()

    text = f"👑 *Super Admin Panel*\n\n🎯 *TWFOCUS Management Dashboard*\n\n📊 *Quick Stats:*\n• Users: {stats.get('total_users', 0)}\n• Accounts: {stats.get('total_accounts', 0)}\n• Withdrawals: ${escape_markdown(f'{stats.get("total_withdrawals_amount", 0):.2f}')}\n"

    if unread_count > 0:
        text += f"• 🔴 Unread Messages: {unread_count}\n"

    text += "\nSelect a category to manage the bot\\."

    if update.callback_query: 
        await try_edit_message(update.callback_query, text, await get_main_admin_keyboard())
    else: 
        await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN_V2, reply_markup=await get_main_admin_keyboard())

@admin_required
async def admin_dashboard(update, context):
    if update.callback_query: await update.callback_query.answer()

    stats = database.get_bot_stats()
    api_count = len(database.get_active_api_credentials())
    unread_count = database.get_unread_message_count()

    text = f"🎯 *TWFOCUS Management Dashboard*\n\n📈 *System Overview:*\n• Total Users: `{stats.get('total_users', 0)}`\n• Active Accounts: `{stats.get('total_accounts', 0)}`\n• API Credentials: `{api_count}`\n• Proxy Pool: `{stats.get('total_proxies', 0)}`\n• Unread Messages: `{unread_count}`\n\n💰 *Financial Summary:*\n• Total Withdrawn: `${escape_markdown(f'{stats.get("total_withdrawals_amount", 0):.2f}')}`\n• Withdrawal Requests: `{stats.get('total_withdrawals_count', 0)}`\n\n🔧 *System Status:* All systems operational"

    keyboard = [
        [InlineKeyboardButton("🔄 Refresh Stats", callback_data="admin_dashboard")],
        [InlineKeyboardButton("⬅️ Back to Main", callback_data="admin_panel")]
    ]

    await try_edit_message(update.callback_query, text, InlineKeyboardMarkup(keyboard))

# --- Live Chat Management ---
@admin_required
async def live_chat_main(update, context):
    if update.callback_query: await update.callback_query.answer()

    users_with_unread = database.get_users_with_unread_messages()
    unread_total = database.get_unread_message_count()

    text = f"💬 *Live Chat Management*\n\nMonitor and respond to user messages in real\\-time\\.\n\n📊 *Chat Overview:*\n• Total Unread: `{unread_total}`\n• Active Conversations: `{len(users_with_unread)}`\n\n"

    keyboard = []

    if users_with_unread:
        text += "*🔴 Users with unread messages:*\n"
        for user in users_with_unread[:10]:  # Show top 10
            username = escape_markdown(user['username'] or f"ID:{user['user_id']}")
            last_msg = datetime.fromisoformat(user['last_message']).strftime('%H:%M')
            text += f"• @{username} \\(`{user['unread_count']}` unread\\) \\- {last_msg}\n"
            keyboard.append([InlineKeyboardButton(f"💬 Chat with @{user['username'] or user['user_id']}", callback_data=f"admin_live_chat_user:{user['user_id']}")])
    else:
        text += "✅ No unread messages\\."

    keyboard.extend([
        [InlineKeyboardButton("📋 View All Chats", callback_data="admin_live_chat_all_page_1")],
        [InlineKeyboardButton("🔄 Refresh", callback_data="admin_live_chat_main")],
        [InlineKeyboardButton("⬅️ Back", callback_data="admin_panel")]
    ])

    await try_edit_message(update.callback_query, text, InlineKeyboardMarkup(keyboard))

@admin_required
async def live_chat_user(update, context):
    if update.callback_query: await update.callback_query.answer()

    user_id = int(update.callback_query.data.split(':')[-1])
    messages = database.get_user_chat_history(user_id, 20)
    user_info = database.get_user_by_id(user_id)

    if not user_info:
        await update.callback_query.answer("User not found!", show_alert=True)
        return

    # Mark messages as read
    database.mark_messages_read(user_id)

    username = escape_markdown(user_info['username'] or f"ID:{user_id}")
    status = "🔴 BLOCKED" if user_info['is_blocked'] else "🟢 ACTIVE"

    text = f"💬 *Chat with @{username}*\n\nStatus: {status}\n\n📝 *Recent Messages:*\n"

    if messages:
        for msg in reversed(messages[-10:]):  # Show last 10 messages
            timestamp = datetime.fromisoformat(msg['timestamp']).strftime('%H:%M')
            message_preview = escape_markdown(msg['message_text'][:50] + ("..." if len(msg['message_text']) > 50 else ""))
            text += f"`{timestamp}` {message_preview}\n"
    else:
        text += "No messages found\\."

    keyboard = [
        [InlineKeyboardButton("✍️ Reply to User", callback_data=f"admin_live_chat_reply:{user_id}")],
        [InlineKeyboardButton("📊 User Info", callback_data=f"admin_user_info_quick:{user_id}")],
        [InlineKeyboardButton("⬅️ Back to Live Chat", callback_data="admin_live_chat_main")]
    ]

    await try_edit_message(update.callback_query, text, InlineKeyboardMarkup(keyboard))

@admin_required
async def live_chat_all(update, context):
    if update.callback_query: await update.callback_query.answer()

    page = int(update.callback_query.data.split('_')[-1])
    limit = 15

    all_chats = database.get_all_user_chats(page, limit)
    total_messages = database.fetch_one("SELECT COUNT(*) as count FROM user_messages")['count']

    text = f"📋 *All User Chats* \\(Page {page}\\)\n\n"

    if all_chats:
        for chat in all_chats:
            timestamp = datetime.fromisoformat(chat['timestamp']).strftime('%m/%d %H:%M')
            username = escape_markdown(chat['username'] or f"ID:{chat['user_id']}")
            message_preview = escape_markdown(chat['message_text'][:30] + ("..." if len(chat['message_text']) > 30 else ""))
            status_icon = "🔴" if chat['is_blocked'] else ("🟡" if not chat['is_read'] else "🟢")
            text += f"{status_icon} `{timestamp}` @{username}\n   {message_preview}\n\n"
    else:
        text += "No messages found\\."

    keyboard = create_pagination_keyboard("admin_live_chat_all_page", page, total_messages, limit)
    keyboard.append([InlineKeyboardButton("⬅️ Back to Live Chat", callback_data="admin_live_chat_main")])

    await try_edit_message(update.callback_query, text, InlineKeyboardMarkup(keyboard))

# --- API Credentials Management ---
@admin_required
async def api_management_panel(update, context):
    if update.callback_query: await update.callback_query.answer()

    credentials = database.get_all_api_credentials()
    active_count = len([c for c in credentials if c['is_active']])

    text = f"🔑 *API Credentials Management*\n\nManage multiple Telegram API credentials for rotation and ban prevention\\.\n\n📊 *Status:*\n• Total Credentials: `{len(credentials)}`\n• Active: `{active_count}`\n• Inactive: `{len(credentials) - active_count}`\n\n"

    keyboard = []

    if credentials:
        text += "*Current Credentials:*\n"
        for i, cred in enumerate(credentials, 1):
            status = "🟢 Active" if cred['is_active'] else "🔴 Inactive"
            last_used = "Never" if not cred['last_used'] else datetime.fromisoformat(cred['last_used']).strftime('%m/%d %H:%M')
            text += f"{i}\\. API ID: `{escape_markdown(cred['api_id'])}` \\- {status}\n   Last Used: {escape_markdown(last_used)}\n"

            keyboard.append([
                InlineKeyboardButton(f"{'🔴 Disable' if cred['is_active'] else '🟢 Enable'} #{i}", callback_data=f"admin_api_toggle:{cred['id']}"),
                InlineKeyboardButton(f"🗑️ Delete #{i}", callback_data=f"admin_api_delete:{cred['id']}")
            ])
    else:
        text += "⚠️ No API credentials configured\\. Add at least one to use the bot\\."

    keyboard.extend([
        [InlineKeyboardButton("➕ Add New API Credential", callback_data="admin_conv_start:ADD_API_ID")],
        [InlineKeyboardButton("🔄 Test All Credentials", callback_data="admin_api_test_all")],
        [InlineKeyboardButton("⬅️ Back to Settings", callback_data="admin_settings_main")]
    ])

    await try_edit_message(update.callback_query, text, InlineKeyboardMarkup(keyboard))

# --- Enhanced Settings Panel ---
@admin_required
async def settings_main_panel(update, context):
    if update.callback_query: await update.callback_query.answer()

    s = context.bot_data
    get_status = lambda k, v='True': "✅ ON" if s.get(k, 'False') == v else "❌ OFF"

    api_count = len(database.get_active_api_credentials())
    proxy_count = database.count_all_proxies()

    # Get 2FA status
    two_step_status = "✅ ON" if s.get('enable_2fa', 'False') == 'True' else "❌ OFF"

    text = f"⚙️ *Bot Settings*\n\nConfigure bot behavior and features\\.\n\n🔧 *Current Status:*\n"

    keyboard = [
        [InlineKeyboardButton(f"Spam Check: {get_status('enable_spam_check')}", callback_data="admin_toggle:enable_spam_check:True:False")],
        [InlineKeyboardButton(f"Device Check: {get_status('enable_device_check')}", callback_data="admin_toggle:enable_device_check:True:False")],
        [InlineKeyboardButton(f"2FA Authentication: {two_step_status}", callback_data="admin_toggle:enable_2fa:True:False")],
        [InlineKeyboardButton(f"Bot Status: {get_status('bot_status', 'ON')}", callback_data="admin_toggle:bot_status:ON:OFF")],
        [InlineKeyboardButton(f"Add Account: {get_status('add_account_status', 'UNLOCKED')}", callback_data="admin_toggle:add_account_status:UNLOCKED:LOCKED")],
        [InlineKeyboardButton("✍️ Edit Text/Values", callback_data="admin_edit_values_list")],
        [InlineKeyboardButton(f"🔑 API Management ({api_count})", callback_data="admin_api_management")],
        [InlineKeyboardButton(f"🌐 Proxy Management ({proxy_count})", callback_data="admin_proxies_main_page_1")],
        [InlineKeyboardButton("⬅️ Back", callback_data="admin_panel")]
    ]

    await try_edit_message(update.callback_query, text, InlineKeyboardMarkup(keyboard))

# --- Enhanced Statistics Panel ---
@admin_required
async def stats_panel(update, context):
    if update.callback_query: await update.callback_query.answer()

    stats = database.get_bot_stats()
    api_stats = database.get_all_api_credentials()
    unread_count = database.get_unread_message_count()

    acc_stats = "\n".join([f"  \\- `{s}`: {c}" for s, c in stats.get('accounts_by_status', {}).items()]) or "  \\- No accounts found\\."
    withdrawn_amount_str = escape_markdown(f'{stats.get("total_withdrawals_amount", 0):.2f}')

    text = f"📊 *Bot Statistics*\n\n👤 *Users*\n  \\- Total: {stats.get('total_users', 0)}\n  \\- Blocked: {stats.get('blocked_users', 0)}\n\n💰 *Finance*\n  \\- Total Withdrawn: `${withdrawn_amount_str}`\n  \\- Withdrawal Count: {stats.get('total_withdrawals_count', 0)}\n\n💳 *Accounts*\n  \\- Total: {stats.get('total_accounts', 0)}\n{acc_stats}\n\n🔑 *API Credentials*\n  \\- Total: {len(api_stats)}\n  \\- Active: {len([a for a in api_stats if a['is_active']])}\n\n🌐 *Infrastructure*\n  \\- Proxies: {stats.get('total_proxies', 0)}\n  \\- Unread Messages: {unread_count}"

    keyboard = [
        [InlineKeyboardButton("🔄 Refresh", callback_data="admin_stats")],
        [InlineKeyboardButton("📈 Detailed Analytics", callback_data="admin_analytics_main")],
        [InlineKeyboardButton("⬅️ Back", callback_data="admin_panel")]
    ]

    await try_edit_message(update.callback_query, text, InlineKeyboardMarkup(keyboard))

@admin_required
async def country_list_panel(update,context):
    if update.callback_query: await update.callback_query.answer()
    countries = database.get_countries_config()
    text = "🌍 *Country Management*\n\nSelect a country to configure its settings\\."
    kb = [[InlineKeyboardButton(f"{d.get('flag',' ')} {d.get('name','N/A')} \\({escape_markdown(d.get('code','N/A'))}\\)", callback_data=f"admin_country_view:{d.get('code','N/A')}")] for d in sorted(countries.values(),key=lambda x:x['name'])]
    kb.extend([[InlineKeyboardButton("➕ Add", callback_data="admin_conv_start:ADD_COUNTRY_CODE"), InlineKeyboardButton("➖ Del", callback_data="admin_conv_start:DELETE_COUNTRY_CODE")], [InlineKeyboardButton("⬅️ Back", callback_data="admin_panel")]])
    await try_edit_message(update.callback_query, text, InlineKeyboardMarkup(kb))

@admin_required
async def country_view_panel(update, context):
    if update.callback_query: await update.callback_query.answer()
    q, code = update.callback_query, update.callback_query.data.split(':')[-1]; country = database.get_country_by_code(code)
    if not country: await q.answer("Country not found!", show_alert=True); return await country_list_panel(update, context)
    c_count, cap = database.get_country_account_count(code), country.get('capacity',-1); cap_text = "Unlimited" if cap == -1 else f"{c_count}/{cap}"; cspam, gmail = ("✅ ON" if country.get('accept_restricted') == 'True' else "❌ OFF"), ("✅ ON" if country.get('accept_gmail') == 'True' else "❌ OFF")
    text = f"⚙️ *Configuration* {country.get('flag','') if country.get('flag') else ''} *{escape_markdown(country.get('name','N/A'))}*\n\n🌍 Country: `{escape_markdown(country.get('code','N/A'))}`\n💲 Base Price: `${escape_markdown(f'{country.get("price_ok",0.0):.2f}')}`\n🟢 Free: `${escape_markdown(f'{country.get("price_ok",0.0):.2f}')}`\n🟡 Register \\(Restricted\\): `${escape_markdown(f'{country.get("price_restricted",0.0):.2f}')}`\n🔴 Limit: `$0\\.00`\n📧 Gmail: *{gmail}*\n🛡️ CSpam: *{cspam}*\n📦 Capacity: *{escape_markdown(cap_text)}*\n⏳ Confirm Time: *{country.get('time',0)} seconds*"
    kb = [[InlineKeyboardButton("💲 Price (OK)", callback_data=f"admin_country_edit_start:{code}:price_ok"), InlineKeyboardButton("💲 Price (Restricted)", callback_data=f"admin_country_edit_start:{code}:price_restricted")], [InlineKeyboardButton("📧 Toggle Gmail", callback_data=f"admin_country_toggle_gmail:{code}"), InlineKeyboardButton("🛡️ Toggle CSpam", callback_data=f"admin_country_toggle_restricted:{code}")], [InlineKeyboardButton("📦 Capacity", callback_data=f"admin_country_edit_start:{code}:capacity"), InlineKeyboardButton("⏳ Time", callback_data=f"admin_country_edit_start:{code}:time")], [InlineKeyboardButton("⬅️ Back", callback_data="admin_country_list")]]
    await try_edit_message(q, text, InlineKeyboardMarkup(kb))

@admin_required
async def finance_main_panel(update, context):
    if update.callback_query: await update.callback_query.answer()
    stats = database.get_bot_stats()
    withdrawn_amount_str = escape_markdown(f'{stats.get("total_withdrawals_amount",0):.2f}')
    text = f"💰 *Finance Overview*\n\n💸 Total Withdrawn: `${withdrawn_amount_str}` from {stats.get('total_withdrawals_count',0)} requests\\."
    await try_edit_message(update.callback_query, text, InlineKeyboardMarkup([[InlineKeyboardButton("📜 View Withdrawal History", callback_data="admin_withdrawal_main_page_1")], [InlineKeyboardButton("⬅️ Back", callback_data="admin_panel")]]))

@admin_required
async def withdrawal_main_panel(update, context):
    if update.callback_query: await update.callback_query.answer()
    page,limit,kb = int(update.callback_query.data.split('_')[-1]), 5, []
    w, total = database.get_all_withdrawals(page,limit), database.count_all_withdrawals()
    text = "📜 *Withdrawal History*\n\n"
    if not w: text += "No withdrawals found\\."
    else:
        status_emojis = {'pending': '⏳', 'completed': '✅'}
        for item in w: 
            ts = datetime.fromisoformat(item['timestamp']).strftime('%Y-%m-%d %H:%M') 
            status_emoji = status_emojis.get(item['status'], '❓')
            text += f"{status_emoji} `@{escape_markdown(item.get('username','N/A'))}` \\(`{item['user_id']}`\\)\n💰 Amount: `${escape_markdown(f'{item["amount"]:.2f}')}`\n📬 Address: `{escape_markdown(item['address'])}`\n🗓️ Date: `{escape_markdown(ts)}`\n" + "\\-"*20 + "\n"
    kb.extend(create_pagination_keyboard("admin_withdrawal_main_page", page, total, limit)); kb.append([InlineKeyboardButton("⬅️ Back", callback_data="admin_finance_main")])
    await try_edit_message(update.callback_query, text, InlineKeyboardMarkup(kb))

@admin_required
async def confirm_main_panel(update, context):
    if update.callback_query: await update.callback_query.answer()
    stuck, error, reprocessing = database.get_stuck_pending_accounts(), database.get_error_accounts(), database.get_accounts_for_reprocessing()
    text = f"♻️ *Account Management*\n\nManage accounts that are stuck, have errors, or are awaiting reprocessing\\.\n\n⏳ Stuck \\(`pending_confirmation`\\): *{len(stuck)}*\n❗️ `error` status: *{len(error)}*\n⏰ Awaiting session termination: *{len(reprocessing)}*"
    kb = [[InlineKeyboardButton(f"🔄 Re-check all {len(stuck)+len(error)} stuck/error accounts", callback_data="admin_recheck_all")], [InlineKeyboardButton("🔍 Re-check by User ID", callback_data="admin_conv_start:RECHECK_BY_USER_ID")], [InlineKeyboardButton("⬅️ Back", callback_data="admin_panel")]]
    await try_edit_message(update.callback_query, text, InlineKeyboardMarkup(kb))

@admin_required
async def broadcast_main_panel(update, context): 
    await try_edit_message(update.callback_query, "📢 *Broadcast*", InlineKeyboardMarkup([[InlineKeyboardButton("✍️ Create Broadcast Message", callback_data="admin_conv_start:BROADCAST_MSG")], [InlineKeyboardButton("👤 Send to Single User", callback_data="admin_conv_start:BROADCAST_SINGLE_USER_ID")], [InlineKeyboardButton("⬅️ Back", callback_data="admin_panel")]]))

@admin_required
async def users_main_panel(update, context):
    if update.callback_query: await update.callback_query.answer()
    page, limit, kb = int(update.callback_query.data.split('_')[-1]), 5, []
    users, total_users = database.get_all_users(page,limit), database.count_all_users()
    total_pages = (total_users + limit - 1) // limit if total_users > 0 else 1
    text = f"👥 *User Management* \\(Page {page} / {total_pages}\\)\n\n"
    if not users: text += "No users found\\."
    else:
        for user in users: 
            status = "🔴 BLOCKED" if user['is_blocked'] else "🟢 ACTIVE"
            text += f"👤 `@{escape_markdown(user.get('username','N/A'))}` \\(`{user['telegram_id']}`\\)\n   Status: {status} \\| Accounts: {user['account_count']}\n"
    kb.extend(create_pagination_keyboard("admin_users_main_page", page, total_users, limit))
    kb.extend([[InlineKeyboardButton("🔍 Get Info", callback_data="admin_conv_start:GET_USER_INFO_ID")], [InlineKeyboardButton("🚫 Block", callback_data="admin_conv_start:BLOCK_USER_ID"), InlineKeyboardButton("✅ Unblock", callback_data="admin_conv_start:UNBLOCK_USER_ID")], [InlineKeyboardButton("💰 Adjust Balance", callback_data="admin_conv_start:ADJ_BALANCE_ID")], [InlineKeyboardButton("⬅️ Back", callback_data="admin_panel")]])
    await try_edit_message(update.callback_query, text, InlineKeyboardMarkup(kb))

@admin_required
async def proxies_main_panel(update, context):
    if update.callback_query: await update.callback_query.answer()
    page, limit, kb = int(update.callback_query.data.split('_')[-1]), 10, []
    proxies, total_proxies = database.get_all_proxies(page,limit), database.count_all_proxies()
    text = f"🌐 *Proxy Management* \\(Total: {total_proxies}\\)\n\n" + (escape_markdown("\n".join([f"`{p['id']}`: `{p['proxy']}`" for p in proxies])) or "No proxies added\\.")
    kb.extend(create_pagination_keyboard("admin_proxies_main_page", page, total_proxies, limit))
    kb.extend([[InlineKeyboardButton("➕ Add Proxy", callback_data="admin_conv_start:ADD_PROXY"), InlineKeyboardButton("➖ Remove Proxy", callback_data="admin_conv_start:REMOVE_PROXY_ID")], [InlineKeyboardButton("⬅️ Back", callback_data="admin_settings_main")]])
    await try_edit_message(update.callback_query, text, InlineKeyboardMarkup(kb))

@admin_required
async def edit_values_list_panel(update, context):
    if update.callback_query: await update.callback_query.answer()
    settings, kb, text = context.bot_data, [], "✍️ *Edit Bot Settings*\n\nSelect a setting to change its value\\."
    exclude_keys = ['scheduler','user_topics','countries_config']; keys = sorted([k for k in settings.keys() if k not in exclude_keys])
    kb = [[InlineKeyboardButton(key, callback_data=f"admin_edit_setting_start:{key}")] for key in keys]
    kb.append([InlineKeyboardButton("⬅️ Back", callback_data="admin_settings_main")]); await try_edit_message(update.callback_query, text, InlineKeyboardMarkup(kb))

@admin_required
async def system_main_panel(update, context):
    if update.callback_query: await update.callback_query.answer()

    text = "🔧 *System & Data Management*\n\nManage system operations and data maintenance\\."
    keyboard = [
        [InlineKeyboardButton("🗂️ File Manager", callback_data="admin_fm_main")],
        [InlineKeyboardButton("🔥 Purge User Data", callback_data="admin_conv_start:DELETE_USER_DATA_ID")],
        [InlineKeyboardButton("♻️ Account Reprocessing", callback_data="admin_confirm_main")],
        [InlineKeyboardButton("💥 Reset Database", callback_data="admin_conv_start:RESET_DATABASE_CONFIRM")],
        [InlineKeyboardButton("⬅️ Back", callback_data="admin_panel")]
    ]
    await try_edit_message(update.callback_query, text, InlineKeyboardMarkup(keyboard))

@admin_required
async def admins_main_panel(update, context):
    if update.callback_query: await update.callback_query.answer()
    admins, text, kb = database.get_all_admins(), "⚠️ *Admin Management*", []
    for admin_user_db in admins:
        try: 
            chat = await context.bot.get_chat(admin_user_db['telegram_id']); text += f"\n\\- @{escape_markdown(chat.username)} \\(`{admin_user_db['telegram_id']}`\\)"
        except Exception: text += f"\n\\- ID: `{admin_user_db['telegram_id']}` \\(Could not fetch info\\)"
    kb.extend([[InlineKeyboardButton("➕ Add Admin", callback_data="admin_conv_start:ADD_ADMIN_ID"), InlineKeyboardButton("➖ Remove Admin", callback_data="admin_conv_start:REMOVE_ADMIN_ID")], [InlineKeyboardButton("⬅️ Back", callback_data="admin_panel")]])
    await try_edit_message(update.callback_query, text, InlineKeyboardMarkup(kb))

# --- File Manager (Rebuilt with User-based Login) ---

ADMIN_SESSION_FILE = "admin_downloader.session"

@admin_required
async def fm_main_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.callback_query: await update.callback_query.answer()
    countries = database.get_countries_config()
    text = "🗂️ *File Manager*\n\nSelect a country to download sessions from\\."
    kb = []

    countries_with_accounts = [c for c in countries.values() if database.get_country_account_count(c['code']) > 0]

    if countries_with_accounts:
        for country in sorted(countries_with_accounts, key=lambda x: x['name']):
            kb.append([InlineKeyboardButton(f"{country['flag']} {country['name']}", callback_data=f"admin_fm_country:{country['code']}")])
    else:
        text += "\n\nNo accounts have been added yet for any country\\."

    kb.append([InlineKeyboardButton("💾 Download Database (bot.db)", callback_data="admin_fm_get_db")])
    kb.append([InlineKeyboardButton("⬅️ Back", callback_data="admin_panel")])
    await try_edit_message(update.callback_query, text, InlineKeyboardMarkup(kb))

@admin_required
async def fm_choose_status_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.callback_query:
        await update.callback_query.answer()
    query = update.callback_query
    country_code = query.data.split(':')[-1]
    country = database.get_country_by_code(country_code)
    if not country:
        await query.answer("Country not found!", show_alert=True)
        return

    context.user_data['fm_country_code'] = country_code

    # Get counts for the main categories we care about
    ok_count = len(database.get_sessions_by_status_and_country('ok', country_code))
    restricted_count = len(database.get_sessions_by_status_and_country('restricted', country_code))
    limited_count = len(database.get_sessions_by_status_and_country('limited', country_code))
    banned_count = len(database.get_sessions_by_status_and_country('banned', country_code))
    
    total_sessions = ok_count + restricted_count + limited_count + banned_count

    text = f"📁 *{country['flag']} {escape_markdown(country['name'])} Sessions*\n\n"
    text += f"Total Available: *{total_sessions}*\n\n"
    text += "📂 *Categories:*\n"

    keyboard = []
    
    # Main categories with enhanced options
    if ok_count > 0:
        text += f"✅ Free: *{ok_count}* sessions\n"
        keyboard.append([
            InlineKeyboardButton(f"📥 Free ({ok_count})", callback_data=f"admin_fm_status_menu:ok"),
            InlineKeyboardButton(f"📦 All Free", callback_data=f"admin_fm_download_all:ok")
        ])
    
    if restricted_count > 0:
        text += f"⚠️ Register: *{restricted_count}* sessions\n"
        keyboard.append([
            InlineKeyboardButton(f"📥 Register ({restricted_count})", callback_data=f"admin_fm_status_menu:restricted"),
            InlineKeyboardButton(f"📦 All Register", callback_data=f"admin_fm_download_all:restricted")
        ])
    
    if limited_count > 0 or banned_count > 0:
        limit_total = limited_count + banned_count
        text += f"🚫 Limit: *{limit_total}* sessions\n"
        keyboard.append([
            InlineKeyboardButton(f"📥 Limit ({limit_total})", callback_data=f"admin_fm_status_menu:limit"),
            InlineKeyboardButton(f"📦 All Limit", callback_data=f"admin_fm_download_all:limit")
        ])

    if total_sessions > 0:
        keyboard.append([InlineKeyboardButton("📦 Download All Categories", callback_data=f"admin_fm_download_all:all")])
    
    keyboard.append([InlineKeyboardButton("⬅️ Back", callback_data="admin_fm_main")])
    await try_edit_message(query, text, InlineKeyboardMarkup(keyboard))

async def fm_download_sessions_logic(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """The core logic after a user account is authorized."""
    query = context.user_data.get('fm_query')
    status_to_fetch = context.user_data.get('fm_status')
    country_code = context.user_data.get('fm_country_code')

    if not all([query, status_to_fetch, country_code]):
        await context.bot.send_message(chat_id=update.effective_chat.id, text="❌ Critical error: Context lost during login. Please try again.")
        return ConversationHandler.END

    country = database.get_country_by_code(country_code)

    await query.message.reply_text(
        f"⏳ Logged in successfully. Fetching *{status_to_fetch.upper()}* sessions for *{escape_markdown(country['name'])}*\\.\\.\\. please wait\\.",
        parse_mode=ParseMode.MARKDOWN_V2
    )

    api_creds = database.get_active_api_credentials()
    if not api_creds:
        await query.message.reply_text("❌ No active API credentials found. Please add some API credentials in the admin panel.", parse_mode=ParseMode.MARKDOWN_V2)
        return ConversationHandler.END

    api_id = int(api_creds[0]['api_id'])
    api_hash = api_creds[0]['api_hash']

    client = TelegramClient(ADMIN_SESSION_FILE, api_id, api_hash)
    try:
        await client.connect()
        if not await client.is_user_authorized():
            if os.path.exists(ADMIN_SESSION_FILE): os.remove(ADMIN_SESSION_FILE)
            raise Exception("Admin session expired. Please try again to log in.")

        accounts_to_find = database.get_all_accounts_by_status_and_country(status_to_fetch, country_code)

        if not accounts_to_find:
            await query.message.reply_text(f"ℹ️ No session files are recorded in the database for this status and country.", parse_mode=ParseMode.MARKDOWN_V2)
            await client.disconnect()
            return ConversationHandler.END

        count = 0
        for acc in accounts_to_find:
             if acc.get('session_file') and os.path.exists(acc['session_file']):
                 await context.bot.send_document(
                     chat_id=query.from_user.id,
                     document=open(acc['session_file'], 'rb')
                 )
                 count += 1
                 await asyncio.sleep(0.1)

        if count > 0:
            await query.message.reply_text(f"✅ Sent *{count}* session file\\(s\\) from local storage.", parse_mode=ParseMode.MARKDOWN_V2)
        else:
            await query.message.reply_text(f"ℹ️ Could not find any matching session files on the server.", parse_mode=ParseMode.MARKDOWN_V2)

    except Exception as e:
        logger.error(f"Failed to download sessions: {e}", exc_info=True)
        await query.message.reply_text(f"❌ An error occurred: {escape_markdown(str(e))}", parse_mode=ParseMode.MARKDOWN_V2)
    finally:
        if client.is_connected():
            await client.disconnect()

    context.user_data.clear()
    return ConversationHandler.END

# --- File Manager Login Conversation ---
@admin_required
async def fm_status_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show download options for a specific status"""
    if update.callback_query:
        await update.callback_query.answer()
    
    query = update.callback_query
    status = query.data.split(':')[-1]
    country_code = context.user_data.get('fm_country_code')
    
    if not country_code:
        await query.answer("Session expired!", show_alert=True)
        return
    
    country = database.get_country_by_code(country_code)
    
    # Get session count for this status
    if status == 'limit':
        sessions = (database.get_sessions_by_status_and_country('limited', country_code) + 
                   database.get_sessions_by_status_and_country('banned', country_code))
        status_name = "Limit"
        status_emoji = "🚫"
    else:
        sessions = database.get_sessions_by_status_and_country(status, country_code)
        status_name = "Free" if status == 'ok' else "Register" if status == 'restricted' else status.title()
        status_emoji = "✅" if status == 'ok' else "⚠️" if status == 'restricted' else "🚫"
    
    total_count = len(sessions)
    
    text = f"{status_emoji} *{status_name} Sessions*\n\n"
    text += f"🗂️ Country: {country['flag']} {escape_markdown(country['name'])}\n"
    text += f"📊 Available: *{total_count}* sessions\n\n"
    text += "Choose download option:"
    
    keyboard = []
    
    # Quick download options
    if total_count > 0:
        if total_count >= 10:
            keyboard.append([
                InlineKeyboardButton("📦 10 Sessions", callback_data=f"admin_fm_download_count:{status}:10"),
                InlineKeyboardButton("📦 25 Sessions", callback_data=f"admin_fm_download_count:{status}:25")
            ])
        if total_count >= 50:
            keyboard.append([
                InlineKeyboardButton("📦 50 Sessions", callback_data=f"admin_fm_download_count:{status}:50"),
                InlineKeyboardButton("📦 100 Sessions", callback_data=f"admin_fm_download_count:{status}:100")
            ])
        
        keyboard.append([InlineKeyboardButton(f"📦 All {total_count} Sessions", callback_data=f"admin_fm_download_all:{status}")])
        keyboard.append([InlineKeyboardButton("🔢 Custom Amount", callback_data=f"admin_fm_custom_amount:{status}")])
    
    keyboard.append([InlineKeyboardButton("⬅️ Back", callback_data=f"admin_fm_country:{country_code}")])
    await try_edit_message(query, text, InlineKeyboardMarkup(keyboard))

async def fm_start_download_or_login(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    # Parse the callback data to get download parameters
    data_parts = query.data.split(':')
    action = data_parts[0].replace('admin_fm_', '')
    
    if action == 'download_count':
        status = data_parts[1]
        count = int(data_parts[2])
        context.user_data['fm_download_count'] = count
    elif action == 'download_all':
        status = data_parts[1]
        context.user_data['fm_download_count'] = None  # Download all
    else:
        status = data_parts[-1]
        context.user_data['fm_download_count'] = None

    context.user_data['fm_query'] = query
    context.user_data['fm_status'] = status

    # Check if we need login or can proceed directly
    api_creds = database.get_active_api_credentials()
    if not api_creds:
        await query.message.reply_text("❌ No active API credentials found. Please add some API credentials in the admin panel.", parse_mode=ParseMode.MARKDOWN_V2)
        return ConversationHandler.END

    # Try direct download without login prompt
    try:
        return await fm_download_sessions_logic(update, context)
    except Exception as e:
        logger.error(f"Direct download failed, requesting login: {e}")
        
        await try_edit_message(
            query,
            "🗂️ *File Manager Login*\n\nTo download files, I need to log in with a regular user account\\. This account must be a member of the session channel\\. Please provide the phone number for this account\\.",
            None
        )
        return AdminState.FM_PHONE

async def fm_get_phone(update: Update, context: ContextTypes.DEFAULT_TYPE):
    phone = update.message.text
    context.user_data['fm_phone'] = phone
    api_creds = database.get_active_api_credentials()
    if not api_creds:
        await update.message.reply_text("❌ No active API credentials found. Please add some API credentials in the admin panel.", parse_mode=ParseMode.MARKDOWN_V2)
        return ConversationHandler.END

    api_id = int(api_creds[0]['api_id'])
    api_hash = api_creds[0]['api_hash']
    client = TelegramClient(ADMIN_SESSION_FILE, api_id, api_hash)

    try:
        await client.connect()
        sent_code = await client.send_code_request(phone)
        context.user_data['fm_phone_hash'] = sent_code.phone_code_hash
        await update.message.reply_text("Please send the login code you received.")
    except Exception as e:
        await update.message.reply_text(f"❌ Error: {e}\nPlease try again or /cancel.")
        return AdminState.FM_PHONE
    finally:
        if client.is_connected():
            await client.disconnect()

    return AdminState.FM_CODE

async def fm_get_code(update: Update, context: ContextTypes.DEFAULT_TYPE):
    code = update.message.text
    phone = context.user_data['fm_phone']
    phone_hash = context.user_data['fm_phone_hash']
    api_creds = database.get_active_api_credentials()
    if not api_creds:
        await update.message.reply_text("❌ No active API credentials found. Please add some API credentials in the admin panel.", parse_mode=ParseMode.MARKDOWN_V2)
        return ConversationHandler.END

    api_id = int(api_creds[0]['api_id'])
    api_hash = api_creds[0]['api_hash']
    client = TelegramClient(ADMIN_SESSION_FILE, api_id, api_hash)

    try:
        await client.connect()
        await client.sign_in(phone, code, phone_code_hash=phone_hash)
        await client.disconnect()
        return await fm_download_sessions_logic(update, context)

    except SessionPasswordNeededError:
        await update.message.reply_text("This account has 2FA enabled. Please enter the password.")
        return AdminState.FM_PASSWORD
    except Exception as e:
        await update.message.reply_text(f"❌ Error: {e}\nPlease /cancel and try again.")
        return ConversationHandler.END
    finally:
        if client.is_connected():
            await client.disconnect()

async def fm_get_password(update: Update, context: ContextTypes.DEFAULT_TYPE):
    password = update.message.text
    api_creds = database.get_active_api_credentials()
    if not api_creds:
        await update.message.reply_text("❌ No active API credentials found. Please add some API credentials in the admin panel.", parse_mode=ParseMode.MARKDOWN_V2)
        return ConversationHandler.END

    api_id = int(api_creds[0]['api_id'])
    api_hash = api_creds[0]['api_hash']
    client = TelegramClient(ADMIN_SESSION_FILE, api_id, api_hash)

    try:
        await client.connect()
        await client.sign_in(password=password)
        await client.disconnect()
        return await fm_download_sessions_logic(update, context)
    except Exception as e:
        await update.message.reply_text(f"❌ Error: {e}\nPlease /cancel and try again.")
        return ConversationHandler.END
    finally:
        if client.is_connected():
            await client.disconnect()

# --- API Management Handlers ---
@admin_required
async def api_toggle_handler(update, context):
    if update.callback_query: await update.callback_query.answer()
    credential_id = int(update.callback_query.data.split(':')[-1])
    database.toggle_api_credential(credential_id)
    await update.callback_query.answer("API credential status toggled!")
    await api_management_panel(update, context)

@admin_required
async def api_delete_handler(update, context):
    if update.callback_query: await update.callback_query.answer()
    credential_id = int(update.callback_query.data.split(':')[-1])
    database.remove_api_credential(credential_id)
    await update.callback_query.answer("API credential deleted!")
    await api_management_panel(update, context)

@admin_required
async def api_test_all_handler(update, context):
    if update.callback_query: await update.callback_query.answer()
    credentials = database.get_active_api_credentials()
    
    if not credentials:
        await update.callback_query.answer("No active API credentials to test!", show_alert=True)
        return
    
    await try_edit_message(update.callback_query, f"🔍 Testing {len(credentials)} API credentials...", None)
    
    working_count = 0
    for cred in credentials:
        try:
            from telethon import TelegramClient
            client = TelegramClient(f"test_{cred['id']}", int(cred['api_id']), cred['api_hash'])
            await client.connect()
            if await client.is_user_authorized():
                working_count += 1
            await client.disconnect()
        except Exception as e:
            logger.error(f"API test failed for credential {cred['id']}: {e}")
    
    await update.callback_query.message.reply_text(
        f"✅ API Test Complete\n\n"
        f"Working: {working_count}/{len(credentials)} credentials",
        parse_mode=ParseMode.MARKDOWN_V2
    )
    await api_management_panel(update, context)

@admin_required
async def analytics_main_panel(update, context):
    if update.callback_query: await update.callback_query.answer()
    
    stats = database.get_bot_stats()
    
    # Get recent registrations (last 7 days)
    recent_users = database.fetch_one("SELECT COUNT(*) as count FROM users WHERE join_date >= datetime('now', '-7 days')")['count']
    recent_accounts = database.fetch_one("SELECT COUNT(*) as count FROM accounts WHERE reg_time >= datetime('now', '-7 days')")['count']
    
    text = f"📈 *Detailed Analytics*\n\n📊 *Last 7 Days:*\n• New Users: `{recent_users}`\n• New Accounts: `{recent_accounts}`\n\n🎯 *Performance Metrics:*\n• Success Rate: `{((stats.get('accounts_by_status', {}).get('ok', 0) / max(stats.get('total_accounts', 1), 1)) * 100):.1f}%`\n• Error Rate: `{((stats.get('accounts_by_status', {}).get('error', 0) / max(stats.get('total_accounts', 1), 1)) * 100):.1f}%`"
    
    keyboard = [
        [InlineKeyboardButton("🔄 Refresh", callback_data="admin_analytics_main")],
        [InlineKeyboardButton("⬅️ Back to Stats", callback_data="admin_stats")]
    ]
    
    await try_edit_message(update.callback_query, text, InlineKeyboardMarkup(keyboard))

# --- Other Handlers and Handler Registration ---
@admin_required
async def get_db_handler(update, context):
    if update.callback_query: await update.callback_query.answer()
    await context.bot.send_document(update.effective_chat.id, document=InputFile(database.DB_FILE, filename="bot.db"))

@admin_required
async def recheck_all_problematic_handler(update, context):
    if update.callback_query: await update.callback_query.answer()
    stuck, error = database.get_stuck_pending_accounts(), database.get_error_accounts(); accounts = list({acc['job_id']: acc for acc in stuck+error}.values())
    if not accounts: await update.callback_query.answer("✅ No problematic accounts found to re-check.", show_alert=True); return
    await try_edit_message(update.callback_query, f"⏳ Found {len(accounts)} accounts\\. Scheduling re-checks\\.\\.\\.", None)
    tasks = [login.schedule_initial_check(BOT_TOKEN, str(a['user_id']), a['user_id'], a['phone_number'], a['job_id']) for a in accounts]; await asyncio.gather(*tasks)
    await update.callback_query.message.reply_text(f"✅ Successfully scheduled *{len(accounts)}* accounts for a new check\\.", parse_mode=ParseMode.MARKDOWN_V2); await confirm_main_panel(update, context)

@admin_required
async def toggle_setting_handler(update, context):
    q, (_,key,on_v,off_v) = update.callback_query, update.callback_query.data.split(':'); current_val = context.bot_data.get(key); new_val = off_v if current_val == on_v else on_v
    database.set_setting(key, new_val); context.bot_data[key] = new_val
    await q.answer(f"Set {key} to {new_val}")
    await settings_main_panel(update, context)

@admin_required
async def toggle_accept_restricted(update, context):
    if update.callback_query: await update.callback_query.answer()
    code = update.callback_query.data.split(':')[-1]; country = database.get_country_by_code(code)
    if not country: return
    new_s = 'False' if country.get('accept_restricted') == 'True' else 'True'; database.update_country_value(code,'accept_restricted',new_s); context.bot_data['countries_config']=database.get_countries_config(); await country_view_panel(update, context)

@admin_required
async def toggle_gmail_handler(update, context):
    if update.callback_query: await update.callback_query.answer()
    code = update.callback_query.data.split(':')[-1]; country = database.get_country_by_code(code)
    if not country: return
    new_s = 'False' if country.get('accept_gmail') == 'True' else 'True'; database.update_country_value(code,'accept_gmail',new_s); context.bot_data['countries_config']=database.get_countries_config(); await country_view_panel(update, context)

@admin_required
async def confirm_withdrawal_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    admin_user = update.effective_user
    try:
        withdrawal_id = int(query.data.split(':')[-1])
    except (IndexError, ValueError):
        await query.answer("Invalid request data.", show_alert=True)
        return
    if "PAID" in query.message.text:
        await query.answer("This withdrawal has already been processed.", show_alert=True)
        return

    await query.answer("Processing payment...")

    withdrawal_info = database.confirm_withdrawal(withdrawal_id)
    if not withdrawal_info:
        await query.answer("Error: Withdrawal not found or already processed.", show_alert=True)
        await query.edit_message_reply_markup(reply_markup=None) 
        return
    user_id = withdrawal_info['user_id']
    amount_str = escape_markdown(f"{withdrawal_info['amount']:.2f}")
    user_message = f"✅ Your withdrawal request of *${amount_str}* has been successfully paid\\."
    try:
        await context.bot.send_message(chat_id=user_id, text=user_message, parse_mode=ParseMode.MARKDOWN_V2)
    except Exception as e:
        logger.error(f"Could not send withdrawal confirmation to user {user_id}: {e}")
        await query.answer(f"User notification failed, but withdrawal is marked as paid. Error: {e}", show_alert=True)

    original_text = query.message.text_markdown_v2
    admin_username = escape_markdown(f"@{admin_user.username}" if admin_user.username else f"ID:{admin_user.id}")
    new_text = f"{original_text}\n\n*✅ PAID by {admin_username}*"
    await query.edit_message_text(text=new_text, reply_markup=None, parse_mode=ParseMode.MARKDOWN_V2)

async def conv_starter(update, context):
    await update.callback_query.answer()
    q, action = update.callback_query, update.callback_query.data.split(':')[-1]

    prompts = {
        'GET_USER_INFO_ID': ("Enter User ID:", AdminState.GET_USER_INFO_ID),
        'BLOCK_USER_ID': ("Enter User ID to *BLOCK*:", AdminState.BLOCK_USER_ID),
        'UNBLOCK_USER_ID': ("Enter User ID to *UNBLOCK*:", AdminState.UNBLOCK_USER_ID),
        'ADJ_BALANCE_ID': ("Enter User ID to adjust balance for:", AdminState.ADJ_BALANCE_ID),
        'ADD_ADMIN_ID': ("Enter Telegram ID of new admin:", AdminState.ADD_ADMIN_ID),
        'REMOVE_ADMIN_ID': ("Enter Telegram ID of admin to remove:", AdminState.REMOVE_ADMIN_ID),
        'BROADCAST_MSG': ("Send message to broadcast:", AdminState.BROADCAST_MSG),
        'BROADCAST_SINGLE_USER_ID': ("Enter User ID to send message to:", AdminState.BROADCAST_SINGLE_USER_ID),
        'ADD_PROXY': ("Enter proxy \\(`ip:port` or `ip:port:user:pass`\\):", AdminState.ADD_PROXY),
        'REMOVE_PROXY_ID': ("Enter ID of proxy to remove:", AdminState.REMOVE_PROXY_ID),
        'ADD_COUNTRY_CODE': ("Step 1/7: Country code \\(e\\.g\\., `+44`\\):", AdminState.ADD_COUNTRY_CODE),
        'DELETE_COUNTRY_CODE': ("Enter country code to delete:", AdminState.DELETE_COUNTRY_CODE),
        'DELETE_USER_DATA_ID': ("🔥 Enter User ID to *PURGE ALL DATA*:", AdminState.DELETE_USER_DATA_ID),
        'RECHECK_BY_USER_ID': ("Enter User's Telegram ID to re\\-check accounts:", AdminState.RECHECK_BY_USER_ID),
        'ADD_API_ID': ("Enter new API ID:", AdminState.ADD_API_ID),
        'ADD_API_HASH': ("Enter new API Hash:", AdminState.ADD_API_HASH),
        'RESET_DATABASE_CONFIRM': ("⚠️ *DANGER ZONE* ⚠️\n\nThis will *PERMANENTLY DELETE*:\n• All users and accounts\n• All withdrawals and balances\n• All session files\n• All settings \\(except defaults\\)\n\nType exactly: `RESET DATABASE` to confirm\nType anything else to cancel", AdminState.RESET_DATABASE_CONFIRM),
    }

    prompt, state = prompts.get(action, (None, None))
    if not prompt: 
        logger.warning(f"Unhandled conv starter: {action}")
        return ConversationHandler.END

    await try_edit_message(q, f"{prompt}\n\nType /cancel to abort\\.", None)
    return state

async def edit_setting_starter(update, context):
    await update.callback_query.answer()
    q, key = update.callback_query, update.callback_query.data.split(':')[-1]; context.user_data['edit_setting_key'] = key
    prompt = f"Editing *{escape_markdown(key)}*\\.\nCurrent value: `{escape_markdown(context.bot_data.get(key,'Not set'))}`\n\nPlease send the new value\\.\nType /cancel to abort\\."
    await try_edit_message(q, prompt, None); return AdminState.EDIT_SETTING_VALUE

async def country_edit_starter(update, context):
    await update.callback_query.answer()
    q, (_,code,key) = update.callback_query, update.callback_query.data.split(':'); context.user_data.update({'edit_country_code':code,'edit_country_key':key}); country=database.get_country_by_code(code)
    prompt = f"Editing *{escape_markdown(key)}* for *{escape_markdown(country.get('name'))}*\\.\nCurrent value: `{escape_markdown(str(country.get(key,'Not set')))}`\n\nPlease send the new value\\.\nType /cancel to abort\\."
    await try_edit_message(q, prompt, None); return AdminState.EDIT_COUNTRY_VALUE

# Handler for API credential addition
async def handle_add_api_id(update, context):
    api_id = update.message.text.strip()
    if not api_id.isdigit():
        await update.message.reply_text("❌ Invalid API ID\\. Please enter a numeric API ID\\.", parse_mode=ParseMode.MARKDOWN_V2)
        return AdminState.ADD_API_ID

    context.user_data['new_api_id'] = api_id
    await update.message.reply_text("Now enter the corresponding API Hash:", parse_mode=ParseMode.MARKDOWN_V2)
    return AdminState.ADD_API_HASH

async def handle_add_api_hash(update, context):
    api_hash = update.message.text.strip()
    api_id = context.user_data.get('new_api_id')

    if len(api_hash) < 32:
        await update.message.reply_text("❌ Invalid API Hash\\. Please enter a valid API Hash\\.", parse_mode=ParseMode.MARKDOWN_V2)
        return AdminState.ADD_API_HASH

    try:
        database.add_api_credential(api_id, api_hash)
        await update.message.reply_text(f"✅ Successfully added API credential\\!\n\nAPI ID: `{escape_markdown(api_id)}`\nAPI Hash: `{escape_markdown(api_hash[:8])}...`", parse_mode=ParseMode.MARKDOWN_V2)
        await update.message.reply_text("👑 *Super Admin Panel*", parse_mode=ParseMode.MARKDOWN_V2, reply_markup=await get_main_admin_keyboard())
    except Exception as e:
        await update.message.reply_text(f"❌ Error adding API credential: {escape_markdown(str(e))}", parse_mode=ParseMode.MARKDOWN_V2)

    context.user_data.clear()
    return ConversationHandler.END

async def handle_broadcast_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = update.message.text
    user_ids = database.get_all_user_ids(only_non_blocked=True)

    sent_count = 0
    for user_id in user_ids:
        try:
            await context.bot.send_message(user_id, message)
            sent_count += 1
            await asyncio.sleep(0.1)  # Rate limiting
        except Exception as e:
            logger.error(f"Failed to send broadcast to user {user_id}: {e}")

    await update.message.reply_text(f"✅ Broadcast sent to {sent_count}/{len(user_ids)} users.")
    return ConversationHandler.END

async def handle_broadcast_single_user_id(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        user_id = int(update.message.text.strip())

        # Check if user exists
        user = database.get_user_by_id(user_id)
        if not user:
            await update.message.reply_text("❌ User not found. Please check the user ID and try again.")
            return AdminState.BROADCAST_SINGLE_USER_ID

        context.user_data['broadcast_target_user'] = user_id
        username = user.get('username', 'N/A')
        await update.message.reply_text(f"✅ Target user: {user_id} (@{username})\n\nNow send the message you want to send to this user:")
        return AdminState.BROADCAST_SINGLE_MESSAGE

    except ValueError:
        await update.message.reply_text("❌ Invalid user ID. Please enter a numeric user ID.")
        return AdminState.BROADCAST_SINGLE_USER_ID

async def handle_broadcast_single_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = update.message.text
    target_user_id = context.user_data.get('broadcast_target_user')

    if not target_user_id:
        await update.message.reply_text("❌ Target user not set. Please start over.")
        return ConversationHandler.END

    try:
        await context.bot.send_message(target_user_id, message)
        await update.message.reply_text(f"✅ Message sent successfully to user {target_user_id}")
    except Exception as e:
        logger.error(f"Failed to send message to user {target_user_id}: {e}")
        await update.message.reply_text(f"❌ Failed to send message: {e}")

    context.user_data.pop('broadcast_target_user', None)
    return ConversationHandler.END

async def handle_purge_user_data(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        user_id = int(update.message.text.strip())

        # Check if user exists
        user = database.get_user_by_id(user_id)
        if not user:
            await update.message.reply_text("❌ User not found.")
            return ConversationHandler.END

        # Purge user data
        deleted_count, session_files = database.purge_user_data(user_id)
        if deleted_count > 0:
            # Clean up session files
            import os
            cleaned_files = 0
            for session_file in session_files:
                try:
                    if os.path.exists(session_file):
                        os.remove(session_file)
                        cleaned_files += 1
                except Exception as e:
                    logger.error(f"Failed to delete session file {session_file}: {e}")

            await update.message.reply_text(
                f"🔥 *User Data Purged*\n\n"
                f"• User ID: {user_id}\n"
                f"• Username: @{user.get('username', 'N/A')}\n"
                f"• Session files cleaned: {cleaned_files}\n\n"
                f"✅ All user data has been permanently deleted.",
                parse_mode=ParseMode.MARKDOWN
            )
        else:
            await update.message.reply_text("❌ Failed to purge user data or user not found.")

    except ValueError:
        await update.message.reply_text("❌ Invalid user ID. Please enter a numeric user ID.")
        return AdminState.DELETE_USER_DATA_ID
    except Exception as e:
        logger.error(f"Error purging user data: {e}")
        await update.message.reply_text(f"❌ Error occurred: {str(e)}")

    await update.message.reply_text("👑 *Super Admin Panel*", parse_mode=ParseMode.MARKDOWN_V2, reply_markup=await get_main_admin_keyboard())
    return ConversationHandler.END

async def handle_reset_database_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = update.message.text.strip().upper()

    if message == "RESET DATABASE":
        try:
            import shutil

            # Close all database connections
            database.db_lock.acquire()

            # Remove the database file
            if os.path.exists(database.DB_FILE):
                os.remove(database.DB_FILE)

            # Remove all session directories
            sessions_dir = "sessions"
            if os.path.exists(sessions_dir):
                shutil.rmtree(sessions_dir)
                os.makedirs(sessions_dir, exist_ok=True)

            database.db_lock.release()

            # Reinitialize the database
            database.init_db()

            # Reload bot settings
            context.bot_data.update(database.get_all_settings())
            context.bot_data['countries_config'] = database.get_countries_config()

            await update.message.reply_text(
                "💥 *Database Reset Complete*\n\n"
                "✅ All data has been permanently deleted\\.\n"
                "✅ Database reinitialized with default settings\\.\n"
                "✅ All session files removed\\.\n\n"
                "🔄 Bot is ready for fresh start\\.",
                parse_mode=ParseMode.MARKDOWN_V2
            )

        except Exception as e:
            logger.error(f"Error resetting database: {e}")
            await update.message.reply_text(f"❌ Error resetting database: {escape_markdown(str(e))}", parse_mode=ParseMode.MARKDOWN_V2)

    else:
        await update.message.reply_text("❌ Confirmation text doesn't match\\. Database reset cancelled\\.", parse_mode=ParseMode.MARKDOWN_V2)

    await update.message.reply_text("👑 *Super Admin Panel*", parse_mode=ParseMode.MARKDOWN_V2, reply_markup=await get_main_admin_keyboard())
    return ConversationHandler.END

# Main router function
def get_admin_handlers():
    async def main_router(update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        if not query or not query.data: 
            return
        data = query.data

        if data == "admin_panel":
            await admin_panel(update, context)
        elif data == "admin_dashboard":
            await admin_dashboard(update, context)
        elif data == "admin_stats":
            await stats_panel(update, context)
        elif data == "admin_settings_main":
            await settings_main_panel(update, context)
        elif data == "admin_live_chat_main":
            await live_chat_main(update, context)
        elif data.startswith("admin_live_chat_user:"):
            await live_chat_user(update, context)
        elif data.startswith("admin_live_chat_all_page"):
            await live_chat_all(update, context)
        elif data == "admin_api_management":
            await api_management_panel(update, context)
        elif data == "admin_country_list":
            await country_list_panel(update, context)
        elif data.startswith("admin_country_view:"):
            await country_view_panel(update, context)
        elif data.startswith("admin_country_toggle_gmail:"):
            await toggle_gmail_handler(update, context)
        elif data.startswith("admin_country_toggle_restricted:"):
            await toggle_accept_restricted(update, context)
        elif data == "admin_finance_main":
            await finance_main_panel(update, context)
        elif data.startswith("admin_withdrawal_main_page"):
            await withdrawal_main_panel(update, context)
        elif data == "admin_confirm_main":
            await confirm_main_panel(update, context)
        elif data == "admin_broadcast_main":
            await broadcast_main_panel(update, context)
        elif data.startswith("admin_users_main_page"):
            await users_main_panel(update, context)
        elif data.startswith("admin_proxies_main_page"):
            await proxies_main_panel(update, context)
        elif data == "admin_edit_values_list":
            await edit_values_list_panel(update, context)
        elif data == "admin_admins_main":
            await admins_main_panel(update, context)
        elif data == "admin_system_main":
            await system_main_panel(update, context)
        elif data == "admin_fm_main":
            await fm_main_panel(update, context)
        elif data == "admin_fm_get_db":
            await get_db_handler(update, context)
        elif data.startswith("admin_fm_country:"):
            await fm_choose_status_panel(update, context)
        elif data.startswith("admin_fm_status_menu:"):
            await fm_status_menu(update, context)
        elif data.startswith("admin_fm_download_count:") or data.startswith("admin_fm_download_all:"):
            # These will be handled by the conversation handler
            pass
        elif data == "admin_recheck_all":
            await recheck_all_problematic_handler(update, context)
        elif data.startswith("admin_confirm_withdrawal:"):
            await confirm_withdrawal_handler(update, context)
        elif data.startswith("admin_api_toggle:"):
            await api_toggle_handler(update, context)
        elif data.startswith("admin_api_delete:"):
            await api_delete_handler(update, context)
        elif data == "admin_api_test_all":
            await api_test_all_handler(update, context)
        elif data == "admin_analytics_main":
            await analytics_main_panel(update, context)
        else:
            logger.warning(f"No route for admin callback: {data}")

    conv_handler = ConversationHandler(
        entry_points=[
            CallbackQueryHandler(conv_starter, pattern=r'^admin_conv_start:'),
            CallbackQueryHandler(edit_setting_starter, pattern=r'^admin_edit_setting_start:'),
            CallbackQueryHandler(country_edit_starter, pattern=r'^admin_country_edit_start:')
        ],
        states={
            AdminState.ADD_API_ID: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_add_api_id)],
            AdminState.ADD_API_HASH: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_add_api_hash)],
            AdminState.GET_USER_INFO_ID: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_get_user_info)],
            AdminState.BLOCK_USER_ID: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_block_user)],
            AdminState.UNBLOCK_USER_ID: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_unblock_user)],
            AdminState.ADJ_BALANCE_ID: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_adjust_balance_id)],
            AdminState.ADJ_BALANCE_AMOUNT: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_adjust_balance_amount)],
            AdminState.ADD_ADMIN_ID: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_add_admin)],
            AdminState.REMOVE_ADMIN_ID: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_remove_admin)],
            AdminState.BROADCAST_MSG: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_broadcast_message)],
            AdminState.BROADCAST_SINGLE_USER_ID: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_broadcast_single_user_id)],
            AdminState.BROADCAST_SINGLE_MESSAGE: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_broadcast_single_message)],
            AdminState.ADD_PROXY: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_add_proxy)],
            AdminState.REMOVE_PROXY_ID: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_remove_proxy)],
            AdminState.ADD_COUNTRY_CODE: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_add_country_code)],
            AdminState.DELETE_COUNTRY_CODE: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_delete_country)],
            AdminState.DELETE_USER_DATA_ID: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_purge_user_data)],
            AdminState.RESET_DATABASE_CONFIRM: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_reset_database_confirm)],
            AdminState.RECHECK_BY_USER_ID: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_recheck_user)],
            AdminState.EDIT_SETTING_VALUE: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_edit_setting_value)],
            AdminState.EDIT_COUNTRY_VALUE: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_edit_country_value)],
        },
        fallbacks=[CommandHandler('cancel', cancel_conv)],
        conversation_timeout=600, per_user=True, per_chat=True,
    )

    fm_conv_handler = ConversationHandler(
        entry_points=[
            CallbackQueryHandler(fm_start_download_or_login, pattern=r'^admin_fm_download:'),
            CallbackQueryHandler(fm_start_download_or_login, pattern=r'^admin_fm_download_count:'),
            CallbackQueryHandler(fm_start_download_or_login, pattern=r'^admin_fm_download_all:')
        ],
        states={
            AdminState.FM_PHONE: [MessageHandler(filters.TEXT & ~filters.COMMAND, fm_get_phone)],
            AdminState.FM_CODE: [MessageHandler(filters.TEXT & ~filters.COMMAND, fm_get_code)],
            AdminState.FM_PASSWORD: [MessageHandler(filters.TEXT & ~filters.COMMAND, fm_get_password)],
        },
        fallbacks=[CommandHandler('cancel', cancel_conv)],
        conversation_timeout=300, per_user=True, per_chat=True,
    )

    return [
        CommandHandler("admin", admin_panel),
        CallbackQueryHandler(toggle_setting_handler, pattern=r'^admin_toggle:'),
        conv_handler,
        fm_conv_handler,
        CallbackQueryHandler(main_router, pattern=r'^admin_')
    ]
# --- Missing Conversation State Handlers ---

async def handle_get_user_info(update, context):
    try:
        user_id = int(update.message.text.strip())
        user = database.get_user_by_id(user_id)
        
        if not user:
            await update.message.reply_text("❌ User not found.")
            return ConversationHandler.END
        
        account_summary, total_balance, earned_balance, manual_adjustment, _ = database.get_user_balance_details(user_id)
        account_count = sum(account_summary.values())
        status = "🔴 BLOCKED" if user['is_blocked'] else "🟢 ACTIVE"
        
        text = f"👤 *User Information*\n\n🆔 ID: `{user_id}`\n📛 Username: @{escape_markdown(user.get('username', 'N/A'))}\n📊 Status: {status}\n💰 Balance: `${total_balance:.2f}`\n📦 Accounts: `{account_count}`\n📅 Joined: `{user['join_date']}`"
        
        await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN_V2)
    except ValueError:
        await update.message.reply_text("❌ Invalid user ID.")
        return AdminState.GET_USER_INFO_ID
    except Exception as e:
        await update.message.reply_text(f"❌ Error: {escape_markdown(str(e))}", parse_mode=ParseMode.MARKDOWN_V2)
    
    await update.message.reply_text("👑 *Super Admin Panel*", parse_mode=ParseMode.MARKDOWN_V2, reply_markup=await get_main_admin_keyboard())
    return ConversationHandler.END

async def handle_block_user(update, context):
    try:
        user_id = int(update.message.text.strip())
        if database.block_user(user_id):
            await update.message.reply_text(f"✅ User {user_id} has been blocked.")
        else:
            await update.message.reply_text("❌ Failed to block user.")
    except ValueError:
        await update.message.reply_text("❌ Invalid user ID.")
        return AdminState.BLOCK_USER_ID
    
    await update.message.reply_text("👑 *Super Admin Panel*", parse_mode=ParseMode.MARKDOWN_V2, reply_markup=await get_main_admin_keyboard())
    return ConversationHandler.END

async def handle_unblock_user(update, context):
    try:
        user_id = int(update.message.text.strip())
        if database.unblock_user(user_id):
            await update.message.reply_text(f"✅ User {user_id} has been unblocked.")
        else:
            await update.message.reply_text("❌ Failed to unblock user.")
    except ValueError:
        await update.message.reply_text("❌ Invalid user ID.")
        return AdminState.UNBLOCK_USER_ID
    
    await update.message.reply_text("👑 *Super Admin Panel*", parse_mode=ParseMode.MARKDOWN_V2, reply_markup=await get_main_admin_keyboard())
    return ConversationHandler.END

async def handle_adjust_balance_id(update, context):
    try:
        user_id = int(update.message.text.strip())
        user = database.get_user_by_id(user_id)
        if not user:
            await update.message.reply_text("❌ User not found.")
            return ConversationHandler.END
        
        context.user_data['balance_user_id'] = user_id
        await update.message.reply_text(f"Enter the amount to add/subtract from user {user_id}'s balance:\n(Use negative numbers to subtract)")
        return AdminState.ADJ_BALANCE_AMOUNT
    except ValueError:
        await update.message.reply_text("❌ Invalid user ID.")
        return AdminState.ADJ_BALANCE_ID

async def handle_adjust_balance_amount(update, context):
    try:
        amount = float(update.message.text.strip())
        user_id = context.user_data.get('balance_user_id')
        
        if not user_id:
            await update.message.reply_text("❌ Session expired. Please start over.")
            return ConversationHandler.END
        
        database.adjust_user_balance(user_id, amount)
        action = "added to" if amount >= 0 else "subtracted from"
        await update.message.reply_text(f"✅ ${abs(amount):.2f} has been {action} user {user_id}'s balance.")
        
    except ValueError:
        await update.message.reply_text("❌ Invalid amount.")
        return AdminState.ADJ_BALANCE_AMOUNT
    
    context.user_data.clear()
    await update.message.reply_text("👑 *Super Admin Panel*", parse_mode=ParseMode.MARKDOWN_V2, reply_markup=await get_main_admin_keyboard())
    return ConversationHandler.END

async def handle_add_admin(update, context):
    try:
        admin_id = int(update.message.text.strip())
        database.add_admin(admin_id)
        await update.message.reply_text(f"✅ User {admin_id} has been added as admin.")
    except ValueError:
        await update.message.reply_text("❌ Invalid user ID.")
        return AdminState.ADD_ADMIN_ID
    
    await update.message.reply_text("👑 *Super Admin Panel*", parse_mode=ParseMode.MARKDOWN_V2, reply_markup=await get_main_admin_keyboard())
    return ConversationHandler.END

async def handle_remove_admin(update, context):
    try:
        admin_id = int(update.message.text.strip())
        if database.remove_admin(admin_id):
            await update.message.reply_text(f"✅ Admin {admin_id} has been removed.")
        else:
            await update.message.reply_text("❌ Admin not found.")
    except ValueError:
        await update.message.reply_text("❌ Invalid user ID.")
        return AdminState.REMOVE_ADMIN_ID
    
    await update.message.reply_text("👑 *Super Admin Panel*", parse_mode=ParseMode.MARKDOWN_V2, reply_markup=await get_main_admin_keyboard())
    return ConversationHandler.END

async def handle_add_proxy(update, context):
    proxy = update.message.text.strip()
    if database.add_proxy(proxy):
        await update.message.reply_text(f"✅ Proxy added: `{escape_markdown(proxy)}`", parse_mode=ParseMode.MARKDOWN_V2)
    else:
        await update.message.reply_text("❌ Failed to add proxy (might already exist).")
    
    await update.message.reply_text("👑 *Super Admin Panel*", parse_mode=ParseMode.MARKDOWN_V2, reply_markup=await get_main_admin_keyboard())
    return ConversationHandler.END

async def handle_remove_proxy(update, context):
    try:
        proxy_id = int(update.message.text.strip())
        if database.remove_proxy_by_id(proxy_id):
            await update.message.reply_text(f"✅ Proxy ID {proxy_id} has been removed.")
        else:
            await update.message.reply_text("❌ Proxy not found.")
    except ValueError:
        await update.message.reply_text("❌ Invalid proxy ID.")
        return AdminState.REMOVE_PROXY_ID
    
    await update.message.reply_text("👑 *Super Admin Panel*", parse_mode=ParseMode.MARKDOWN_V2, reply_markup=await get_main_admin_keyboard())
    return ConversationHandler.END

async def handle_add_country_code(update, context):
    code = update.message.text.strip()
    context.user_data['new_country_code'] = code
    await update.message.reply_text("Step 2/7: Enter country name:")
    return AdminState.ADD_COUNTRY_NAME

async def handle_delete_country(update, context):
    code = update.message.text.strip()
    if database.delete_country(code):
        await update.message.reply_text(f"✅ Country {code} has been deleted.")
        context.bot_data['countries_config'] = database.get_countries_config()
    else:
        await update.message.reply_text("❌ Country not found.")
    
    await update.message.reply_text("👑 *Super Admin Panel*", parse_mode=ParseMode.MARKDOWN_V2, reply_markup=await get_main_admin_keyboard())
    return ConversationHandler.END

async def handle_recheck_user(update, context):
    try:
        user_id = int(update.message.text.strip())
        accounts = database.get_problematic_accounts_by_user(user_id)
        
        if not accounts:
            await update.message.reply_text("✅ No problematic accounts found for this user.")
            return ConversationHandler.END
        
        # Schedule recheck for all problematic accounts
        from handlers import login
        tasks = [login.schedule_initial_check(context.bot.token, str(acc['user_id']), acc['user_id'], acc['phone_number'], acc['job_id']) for acc in accounts]
        await asyncio.gather(*tasks)
        
        await update.message.reply_text(f"✅ Scheduled recheck for {len(accounts)} accounts belonging to user {user_id}.")
        
    except ValueError:
        await update.message.reply_text("❌ Invalid user ID.")
        return AdminState.RECHECK_BY_USER_ID
    
    await update.message.reply_text("👑 *Super Admin Panel*", parse_mode=ParseMode.MARKDOWN_V2, reply_markup=await get_main_admin_keyboard())
    return ConversationHandler.END

async def handle_edit_setting_value(update, context):
    key = context.user_data.get('edit_setting_key')
    value = update.message.text.strip()
    
    if key:
        database.set_setting(key, value)
        context.bot_data[key] = value
        await update.message.reply_text(f"✅ Setting `{key}` updated to: `{escape_markdown(value)}`", parse_mode=ParseMode.MARKDOWN_V2)
    
    context.user_data.clear()
    await update.message.reply_text("👑 *Super Admin Panel*", parse_mode=ParseMode.MARKDOWN_V2, reply_markup=await get_main_admin_keyboard())
    return ConversationHandler.END

async def handle_edit_country_value(update, context):
    code = context.user_data.get('edit_country_code')
    key = context.user_data.get('edit_country_key')
    value = update.message.text.strip()
    
    if code and key:
        database.update_country_value(code, key, value)
        context.bot_data['countries_config'] = database.get_countries_config()
        await update.message.reply_text(f"✅ Country {code} {key} updated to: `{escape_markdown(value)}`", parse_mode=ParseMode.MARKDOWN_V2)
    
    context.user_data.clear()
    await update.message.reply_text("👑 *Super Admin Panel*", parse_mode=ParseMode.MARKDOWN_V2, reply_markup=await get_main_admin_keyboard())
    return ConversationHandler.END

# The code has been modified to include single user broadcast functionality.