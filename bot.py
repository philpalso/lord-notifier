import discord
from discord.ext import commands
from discord import app_commands
import requests
from bs4 import BeautifulSoup
import asyncio
import json
import logging
import os

# Logging setup
DATA_DIR = os.getenv("DATA_DIR", ".")  
LOG_FILE = os.path.join(DATA_DIR, "bot.log")
LAST_DATES_FILE = os.path.join(DATA_DIR, "last_dates.txt")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s"
    handlers=[
        logging.StreamHandler(),           # stdout → visible in Railway logs
        logging.FileHandler(LOG_FILE),     # file → only works with a Volume
    ]
)

# Load config
with open("config.json") as f:
    config = json.load(f)

TOKEN = os.getenv("DISCORD_TOKEN", config.get("TOKEN"))  # Prefer env var for Railway
CHANNEL_ID = int(os.getenv("DISCORD_CHANNEL", config.get("CHANNEL_ID")))  # Prefer env var for Railway
URL = config["URL"]
CHECK_INTERVAL = config["CHECK_INTERVAL"]

monitoring = True  # Global flag to control monitoring

# Read last dates from file
def read_last_dates():
    if os.path.exists(LAST_DATES_FILE):
        with open(LAST_DATES_FILE, "r") as f:
            return set(f.read().splitlines())
    return set()

# Save current dates to file
def save_last_dates(dates):
    with open(LAST_DATES_FILE, "w") as f:
        f.write("\n".join(dates))
        

# Read last N lines from log file
def read_log_lines(n=10):
    if not os.path.exists(LOG_FILE):
        return ["No logs available."]
    with open(LOG_FILE, "r") as f:
        lines = f.readlines()
    return lines[-n:] if len(lines) > n else lines


# Discord bot setup
intents = discord.Intents.default()
bot = commands.Bot(command_prefix="!", intents=intents)

async def check_website():
    global monitoring
    await bot.wait_until_ready()
    channel = bot.get_channel(CHANNEL_ID)
    last_dates = read_last_dates()


    while monitoring:
        try:
            response = requests.get(URL, timeout=10, verify="certificate.pem") #Certificate needs to change at some point
            response.raise_for_status()
            soup = BeautifulSoup(response.text, "html.parser")

            # Find all elements with ID starting with 'date-'
            elements = soup.select("[id^='date-']")
            current_dates = set(el.get("id") for el in elements if el.get("id"))

            logging.info(f"Current dates: {current_dates}")

            if last_dates and current_dates != last_dates:
                added = current_dates - last_dates
                removed = last_dates - current_dates

                message = "🔔 Festival programme updated!\n"
                if added:
                    message += f"✅ New dates added: {', '.join(sorted(added))}\n"
                if removed:
                    message += f"❌ Dates removed: {', '.join(sorted(removed))}\n"

                await channel.send(message)
                logging.info("Change detected and message sent.")

            last_dates = current_dates
            save_last_dates(current_dates)

        except Exception as e:
            logging.error(f"Error checking website: {e}")
            if channel:
                await channel.send(f"📛 Error checking website: {e}")

        await asyncio.sleep(CHECK_INTERVAL)

async def heartbeat():
    await bot.wait_until_ready()
    channel = bot.get_channel(CHANNEL_ID)
    while True:
        await channel.send("❤️‍🔥 Heartbeat: I am alive and checking for changes")
        logging.info("Heartbeat message sent to Discord.")
        await asyncio.sleep(86400)  # 24 hours in seconds
        
# Slash commands
@bot.tree.command(name="start", description="Start monitoring the festival programme")
async def start(interaction: discord.Interaction):
    global monitoring
    if monitoring:
        await interaction.response.send_message("⚠️ Monitoring is already running.")
    else:
        monitoring = True
        asyncio.create_task(check_website())
        await interaction.response.send_message("✅ Monitoring started!")

@bot.tree.command(name="stop", description="Stop monitoring the festival programme")
async def stop(interaction: discord.Interaction):
    global monitoring
    if monitoring:
        monitoring = False
        await interaction.response.send_message("⏹ Monitoring stopped!")
    else:
        await interaction.response.send_message("⚠️ Monitoring is not running.")

@bot.tree.command(name="status", description="Check bot status")
async def status(interaction: discord.Interaction):
    msg = "✅ Bot is running.\n"
    msg += "Monitoring: " + ("ON" if monitoring else "OFF")
    await interaction.response.send_message(msg)

@bot.tree.command(name="dates", description="Show currently detected festival dates")
async def dates(interaction: discord.Interaction):
    current_dates = read_last_dates()
    if current_dates:
        await interaction.response.send_message(f"📅 Current dates: {', '.join(sorted(current_dates))}")
    else:
        await interaction.response.send_message("No dates found yet.")


@bot.tree.command(name="help", description="Show all available commands")
async def help_command(interaction: discord.Interaction):
    help_text = (
        "**Available Commands:**\n"
        "/start - Start monitoring the festival programme\n"
        "/stop - Stop monitoring\n"
        "/status - Check bot status\n"
        "/dates - Show currently detected festival dates\n"
        "/show-log - Display the last 10 log entries\n"
    )
    await interaction.response.send_message(help_text)

@bot.tree.command(name="show-log", description="Show the last 10 log entries")
async def show_log(interaction: discord.Interaction):
    logs = read_log_lines(10)
    log_text = "```\n" + "".join(logs) + "\n```"
    await interaction.response.send_message(log_text)


@bot.event
async def on_ready():
    logging.info(f"Bot logged in as {bot.user}")
    try:
        await bot.tree.sync()
        logging.info("Slash commands synced!")
    except Exception as e:
        logging.error(f"Error syncing commands: {e}")

    # Start heartbeat task
    asyncio.create_task(heartbeat())


bot.run(TOKEN)







