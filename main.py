import asyncio
import os
import random
import string
import time
import aiohttp
from playwright.async_api import async_playwright

MAX_RUNTIME = 5.5 * 60 * 60
START_TIME = time.time()

BASE_URL = "https://guns.lol/{}"

CHARS = string.ascii_lowercase + string.digits
RATE_RETRY_DELAY = 120

# -------- ENV -------- #
WEBHOOK_AVAILABLE = os.getenv("WEBHOOK_AVAILABLE")
WEBHOOK_TAKEN = os.getenv("WEBHOOK_TAKEN")
WEBHOOK_BANNED = os.getenv("WEBHOOK_BANNED")
WEBHOOK_RATE = os.getenv("WEBHOOK_RATE")

MODE = os.getenv("MODE", "wordlist")
WORDLIST = os.getenv("WORDLIST", "newwords.txt")
AMOUNT = int(os.getenv("AMOUNT", "10000"))
CONCURRENCY = int(os.getenv("PAGES", "3"))

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36"
)

available_list = []
banned_list = []
taken_list = []

# -------- WEBHOOK -------- #
async def send_live(webhook, session, msg, allow_mentions=False):
    if not webhook:
        return

    payload = {
        "content": msg,
        "allowed_mentions": (
            {"parse": ["everyone", "roles"]} if allow_mentions else {"parse": []}
        )
    }

    async with session.post(webhook, json=payload) as resp:
        if resp.status == 429:
            retry = float(resp.headers.get("Retry-After", "1"))
            await asyncio.sleep(retry)
        elif resp.status >= 400:
            text = await resp.text()
            print(f"[WEBHOOK ERROR {resp.status}] {text}")

# -------- CHECK -------- #
async def check_username(page, username, session):
    try:
        await page.goto(
            BASE_URL.format(username),
            timeout=20000,
            wait_until="domcontentloaded"
        )

        await page.wait_for_timeout(300)

        # ---- RATE LIMIT (still body-based) ----
        body_text = (await page.inner_text("body")).lower()
        if "too many requests" in body_text:
            await send_live(
                WEBHOOK_RATE,
                session,
                f"⏳ RATE LIMITED — sleeping {RATE_RETRY_DELAY}s"
            )
            await asyncio.sleep(RATE_RETRY_DELAY)
            return

        # ---- READ STATUS FROM H1 ONLY ----
        try:
            h1_text = (await page.locator("h1").first.inner_text()).strip().lower()
        except:
            h1_text = ""

        # ---- AVAILABLE ----
        if h1_text == "username not found":
            available_list.append(username)
            await send_live(
                WEBHOOK_AVAILABLE,
                session,
                f"✅ AVAILABLE: `{username}` @everyone",
                allow_mentions=True
            )
            return

        # ---- BANNED ----
        if h1_text == "this user has been banned":
            banned_list.append(username)
            await send_live(
                WEBHOOK_BANNED,
                session,
                f"⚠️ BANNED: `{username}` <@&1465095383259549818>",
                allow_mentions=True
            )
            return

        # ---- TAKEN (default) ----
        taken_list.append(username)

    except Exception:
        taken_list.append(username)


# -------- WORKER -------- #
async def worker(name, queue, page, session):
    while not queue.empty():
        username = await queue.get()
        await check_username(page, username, session)
        await asyncio.sleep(0.6)
        queue.task_done()

# -------- SUMMARY -------- #
async def send_summary(url, title, names, color):
    if not url:
        return

    if not names:
        names = ["None"]

    payload = {
        "embeds": [{
            "title": title,
            "description": "```\n" + "\n".join(names[:50]) + "\n```",
            "color": color
        }],
        "allowed_mentions": {"parse": []}
    }

    async with aiohttp.ClientSession() as s:
        async with s.post(url, json=payload) as resp:
            if resp.status >= 400:
                print(f"[SUMMARY ERROR {resp.status}] {await resp.text()}")

# -------- MAIN -------- #
async def main():
    if MODE == "2c":
        usernames = [
            "".join(random.choice(CHARS) for _ in range(2))
            for _ in range(AMOUNT)
        ]
    elif MODE == "3c":
        usernames = [
            "".join(random.choice(CHARS) for _ in range(3))
            for _ in range(AMOUNT)
        ]
    elif MODE == "wordlist":
        wordlist_path = os.getenv("WORDLIST")
        if not wordlist_path or not os.path.exists(wordlist_path):
            print("WORDLIST file not found")
            return
        with open(wordlist_path, "r", encoding="utf-8") as f:
            usernames = [line.strip() for line in f if line.strip()]
    else:
        print("Invalid MODE")
        return

    print(f"Loaded {len(usernames)} usernames | {CONCURRENCY} pages | running up to 5.5hrs")

    cycle = 1
    async with aiohttp.ClientSession() as session:
        async with async_playwright() as p:
            browser = await p.chromium.launch(
                headless=True,
                args=["--no-sandbox", "--disable-dev-shm-usage"]
            )
            pages = [
                await browser.new_page(user_agent=USER_AGENT)
                for _ in range(CONCURRENCY)
            ]

            while True:
                elapsed = time.time() - START_TIME
                if elapsed > MAX_RUNTIME:
                    print("Approaching 6hr limit — stopping cleanly.")
                    break

                print(f"\n--- CYCLE {cycle} | Elapsed: {int(elapsed // 60)}m ---")
                random.shuffle(usernames)

                queue = asyncio.Queue()
                for u in usernames:
                    queue.put_nowait(u)

                workers = [
                    asyncio.create_task(worker(f"W{i}", queue, pages[i], session))
                    for i in range(CONCURRENCY)
                ]

                await queue.join()
                for w in workers:
                    w.cancel()

                cycle += 1
                await asyncio.sleep(5)

            await browser.close()

    await send_summary(WEBHOOK_AVAILABLE, "✅ Available Names", available_list, 0x57F287)
    await send_summary(WEBHOOK_TAKEN, "❌ Taken Names", taken_list, 0xED4245)
    await send_summary(WEBHOOK_BANNED, "⚠️ Banned Names", banned_list, 0xFEE75C)
    print("Done.")

if __name__ == "__main__":
    asyncio.run(main())
