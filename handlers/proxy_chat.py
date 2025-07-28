
import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from telegram.constants import ParseMode
import database

logger = logging.getLogger(__name__)

async def forward_to_admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Direct P2P chat - Send user messages directly to admin as if from the user"""
    support_id = context.bot_data.get('support_id', '')
    if not support_id or not support_id.isdigit():
        return

    user = update.effective_user
    text = update.message.text

    # Check for flood control
    last_forward_key = f"last_forward_{user.id}"
    import time
    current_time = time.time()
    last_forward = context.user_data.get(last_forward_key, 0)

    if current_time - last_forward < 2:  # 2 second cooldown
        return

    context.user_data[last_forward_key] = current_time

    # Send message as if it's coming directly from the user
    try:
        # Create a more natural chat experience
        user_name = user.full_name or user.username or f"User {user.id}"
        
        await context.bot.send_message(
            chat_id=int(support_id),
            text=f"👤 **{user_name}** (`{user.id}`):\n{text}",
            parse_mode=ParseMode.MARKDOWN
        )
        
        # Send auto-reply to user to acknowledge message
        await update.message.reply_text(
            "✅ Your message has been sent to support. You will receive a reply shortly.",
            parse_mode=ParseMode.MARKDOWN
        )
        
    except Exception as e:
        logger.error(f"Failed to forward message to admin {support_id}: {e}")

async def reply_to_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Enhanced admin reply system with user ID detection"""
    admin_user = update.effective_user
    admin_id_str = context.bot_data.get('support_id')

    # This handler is only for the configured admin
    if not admin_id_str or str(admin_user.id) != admin_id_str:
        return

    message_text = update.message.text
    
    # Auto-detect user ID from replied message or manual command
    target_user_id = None
    reply_message = None
    
    # Check if replying to a forwarded message
    if update.message.reply_to_message:
        replied_text = update.message.reply_to_message.text
        if replied_text and "(`" in replied_text and "`)" in replied_text:
            # Extract user ID from the format: User Name (`12345`):
            import re
            match = re.search(r'\(`(\d+)`\)', replied_text)
            if match:
                target_user_id = int(match.group(1))
                reply_message = message_text
    
    # Check if using manual /reply command
    elif message_text.startswith('/reply'):
        try:
            parts = message_text.split(' ', 2)
            if len(parts) >= 3:
                target_user_id = int(parts[1])
                reply_message = parts[2]
            else:
                await update.message.reply_text("Usage: /reply USER_ID Your message here")
                return
        except (ValueError, IndexError):
            await update.message.reply_text("❌ Invalid format. Usage: /reply USER_ID Your message here")
            return
    
    if target_user_id and reply_message:
        try:
            # Send reply to user
            await context.bot.send_message(
                chat_id=target_user_id,
                text=f"💬 **Support Reply:**\n\n{reply_message}",
                parse_mode=ParseMode.MARKDOWN
            )

            await update.message.reply_text(f"✅ Reply sent to user {target_user_id}")

        except Exception as e:
            logger.error(f"Failed to send admin reply: {e}")
            await update.message.reply_text(f"❌ Could not send reply: {e}")
