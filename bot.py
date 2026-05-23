import discord
from discord.ext import commands
from discord import app_commands
import requests
import certifi
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
    format="%(asctime)s - %(levelname)s - %(message)s",
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

# Near your other file constants
LAST_EVENTS_FILE = os.path.join(DATA_DIR, "last_events.txt")
TARGET_KEYWORDS = config.get("TARGET_KEYWORDS", [])

def read_last_events():
    if os.path.exists(LAST_EVENTS_FILE):
        with open(LAST_EVENTS_FILE, "r") as f:
            return set(line.strip() for line in f if line.strip())
    return set()

def save_last_events(events):
    with open(LAST_EVENTS_FILE, "w") as f:
        f.write("\n".join(sorted(events)))

# Discord bot setup
intents = discord.Intents.default()
bot = commands.Bot(command_prefix="!", intents=intents)

async def check_website():
    global monitoring
    await bot.wait_until_ready()
    channel = bot.get_channel(CHANNEL_ID)
    target_notified = set()  # Tracks which keyword matches we've already alerted on
    known_events = read_last_events()

    while monitoring:
        try:
            response = requests.get(URL, timeout=10, verify=certifi.where())
            response.raise_for_status()
            soup = BeautifulSoup(response.text, "html.parser")

            # --- TARGET EVENT WATCH ---
            # Look for any event block that contains a target keyword AND a ticket link
            event_blocks = soup.select("li, div.event, article")  # cast wide net
            # Fallback: scan all <strong> tags with their parent context
            for strong in soup.select("strong"):
                title = strong.get_text(strip=True)
                title_lower = title.lower()

                matched_keyword = next(
                    (kw for kw in TARGET_KEYWORDS if kw.lower() in title_lower), None
                )
                if not matched_keyword:
                    continue

                # Check if a ticket link exists near this element
                parent = strong.find_parent()
                has_ticket = False
                if parent:
                    ticket_link = parent.find("a", href=lambda h: h and "nortic.se" in h)
                    has_ticket = ticket_link is not None

                alert_key = title  # Use full title so same keyword can re-alert for new events
                if alert_key not in target_notified:
                    if has_ticket:
                        ticket_url = ticket_link["href"]
                        await channel.send(
                            f"🚨 **Target event found with tickets!**\n"
                            f"**{title}**\n"
                            f"🎟️ Buy tickets: {ticket_url}"
                        )
                        logging.info(f"Target event with ticket found: {title}")
                    else:
                        await channel.send(
                            f"👀 **Target event appeared (no ticket link yet)**\n"
                            f"**{title}**\n"
                            f"Keep watching: {URL}"
                        )
                        logging.info(f"Target event without ticket found: {title}")
                    target_notified.add(alert_key)

            # --- GENERAL PROGRAMME CHANGES ---
            all_titles = set(
                el.get_text(strip=True)
                for el in soup.select("strong")
                if el.get_text(strip=True)
            )

            if known_events:
                new_events = all_titles - known_events
                if new_events:
                    merged = known_events | all_titles
                    save_last_events(merged)
                    known_events = merged

                    lines = "\n".join(f"• {e}" for e in sorted(new_events))
                    # Discord has a 2000 char limit — chunk if needed
                    message = f"📋 **Programme updated! {len(new_events)} new event(s):**\n{lines}"
                    if len(message) > 1900:
                        message = (
                            f"📋 **Programme updated! {len(new_events)} new event(s):**\n"
                            + "\n".join(f"• {e}" for e in sorted(new_events))[:1800]
                            + "\n…(truncated)"
                        )
                    await channel.send(message)
                    logging.info(f"{len(new_events)} new events added to known list.")
            else:
                # First run — just store what's there, don't alert
                known_events = all_titles
                save_last_events(known_events)
                logging.info(f"Initial event list saved: {len(known_events)} events.")

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
        await asyncio.sleep(259200)  # 3 x 24 hours in seconds
        
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

@bot.tree.command(name="list_events", description="List all known programme events")
async def list_events(interaction: discord.Interaction):
    events = read_last_events()
    if not events:
        await interaction.response.send_message("No events stored yet. The bot hasn't done a check, or the programme is empty.")
        return

    sorted_events = sorted(events)
    lines = "\n".join(f"• {e}" for e in sorted_events)
    full_text = f"**Known programme events ({len(sorted_events)} total):**\n{lines}"

    if len(full_text) <= 1900:
        await interaction.response.send_message(full_text)
    else:
        # Write to a temp file and send as attachment
        file_path = os.path.join(DATA_DIR, "events_list.txt")
        with open(file_path, "w") as f:
            f.write("\n".join(sorted_events))
        await interaction.response.send_message(
            f"📋 Too many events to list inline ({len(sorted_events)} total). Here's the full list as a file:",
            file=discord.File(file_path)
        )


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







