import asyncio
import os
import random
import string
import aiohttp
import requests
from playwright.async_api import async_playwright

BASE_URL = "https://guns.lol/{}"
CLAIM_URL = "https://guns.lol/api/account/username"

CHARS = string.ascii_lowercase + string.digits
RATE_RETRY_DELAY = 120

# -------- ENV -------- #
WEBHOOK_AVAILABLE = os.getenv("WEBHOOK_AVAILABLE")
WEBHOOK_TAKEN = os.getenv("WEBHOOK_TAKEN")
WEBHOOK_BANNED = os.getenv("WEBHOOK_BANNED")
WEBHOOK_RATE = os.getenv("WEBHOOK_RATE")
WEBHOOK_CLAIMED = os.getenv("WEBHOOK_CLAIMED")

MODE = os.getenv("MODE", "2c")
WORDLIST = os.getenv("WORDLIST", "words.txt")
AMOUNT = int(os.getenv("AMOUNT", "5000"))
CONCURRENCY = int(os.getenv("PAGES", "3"))

# -------- AUTH COOKIES (update when expired) -------- #
COOKIES = {
    "GUNS_LOCALE": "en",
    "GUNS_PATH_LOCALE": "en",
    "__guns_access_v1": "__DO_NOT_SHARE__eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiI2OWI4NzA2ZTE5ZGYwYjA3NjM4MWViMjQiLCJzaWQiOiIwMUtLVzdHOVlBSFozWEY3Vlc4MTE1UFc3SyIsImp0aSI6IjhkZWI2OGUzLTI0ZmQtNGMyNy1hNzliLTEyZWE0ZTk3MjM0NyIsImlzcyI6Imd1bnMubG9sIiwiYXVkIjoiZ3Vucy5sb2w6d2ViIiwiaWF0IjoxNzczNjk1MTUwLCJleHAiOjE3NzQ5MDQ3NTB9.j-lHZ1kDMX3KbKJY4wJszVg1PvFZKwFh0QPO7_ScMAc",
    "cf_clearance": "U78_APn2gncyDRjoqCH1FSfFNL_OVxNdKAa6OCPy7tA-1773695173-1.2.1.1-OivNfJIHM0PqbmF_HCaqdMFPFjX8sq_ilBxbqqEbE_T6h81FCNQI9eunX2uMqe9V7JvjNh5UsCAcd1dlB9hrvZVhdFEk0C_Dm7.fyjo6agfQzAo11M7zmDieI1919JwpPpKGVqv.L4AP_p7OgbECw8UC39aB1XgTf7pZyeNcuD9yyXTUD.JU36.WW7cc4Qr7BcCnY48I7S5xOjhOyIEwCVo0oHUzNS2Is3LX4K84sTM",
    "guns_clearance": "fc1cdad7ffaef4c97368015eb03707ff75adfdd72ca3b8fb5a98e0736407c2b4.1773695174.b0RhSdK51K_2-faed7a78b4829fedf0f552313b209080a29680ac8383369241de42315a45c9e3",
}

CLAIM_HEADERS = {
    "accept": "*/*",
    "accept-language": "en-US,en;q=0.9",
    "content-type": "text/plain;charset=UTF-8",
    "origin": "https://guns.lol",
    "referer": "https://guns.lol/account/settings",
    "sec-ch-ua": '"Chromium";v="146", "Not-A.Brand";v="24", "Microsoft Edge";v="146"',
    "sec-ch-ua-mobile": "?1",
    "sec-ch-ua-platform": '"Android"',
    "sec-fetch-dest": "empty",
    "sec-fetch-mode": "cors",
    "sec-fetch-site": "same-origin",
    "user-agent": "Mozilla/5.0 (Linux; Android 6.0; Nexus 5 Build/MRA58N) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/146.0.0.0 Mobile Safari/537.36 Edg/146.0.0.0",
}

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36"
)

available_list = []
banned_list = []
taken_list = []
claimed_list = []

# -------- CLAIM -------- #
def claim_username(username):
    try:
        r = requests.post(
            CLAIM_URL,
            data=f'{{"username":"{username}"}}',
            headers=CLAIM_HEADERS,
            cookies=COOKIES,
            timeout=10,
        )
        data = r.json()
        msg = data.get("message", "")
        if "updated successfully" in msg.lower():
            print(f"  [CLAIM] ✅ CLAIMED @{username}!")
            return True
        else:
            print(f"  [CLAIM] ❌ Failed @{username}: {msg}")
            return False
    except Exception as e:
        print(f"  [CLAIM] Error @{username}: {e}")
        return False

# -------- WEBHOOK -------- #
async def send_live(webhook, session, msg, allow_mentions=False):
    if not webhook:
        return
    payload = {
        "content": msg,
        "allowed_mentions": (
            {"parse": ["everyone", "roles"]} if allow_mentions else {"parse": []}
        ),
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
            wait_until="domcontentloaded",
        )

        await page.wait_for_timeout(300)

        body_text = (await page.inner_text("body")).lower()
        if "too many requests" in body_text:
            await send_live(
                WEBHOOK_RATE,
                session,
                f"⏳ RATE LIMITED — sleeping {RATE_RETRY_DELAY}s",
            )
            await asyncio.sleep(RATE_RETRY_DELAY)
            return

        try:
            h1_text = (await page.locator("h1").first.inner_text()).strip().lower()
        except:
            h1_text = ""

        # ---- AVAILABLE — try to claim immediately ----
        if h1_text == "username not found":
            available_list.append(username)
            print(f"  [AVAILABLE] @{username} — attempting claim...")
            await send_live(
                WEBHOOK_AVAILABLE,
                session,
                f"✅ AVAILABLE: `{username}` — claiming now... @everyone",
                allow_mentions=True,
            )

            loop = asyncio.get_event_loop()
            success = await loop.run_in_executor(None, claim_username, username)

            if success:
                claimed_list.append(username)
                await send_live(
                    WEBHOOK_CLAIMED or WEBHOOK_AVAILABLE,
                    session,
                    f"🎯 **CLAIMED:** `@{username}` @everyone",
                    allow_mentions=True,
                )
            else:
                await send_live(
                    WEBHOOK_AVAILABLE,
                    session,
                    f"⚠️ Available but claim failed: `{username}`",
                )
            return

        # ---- BANNED ----
        if h1_text == "this user has been banned":
            banned_list.append(username)
            await send_live(
                WEBHOOK_BANNED,
                session,
                f"⚠️ BANNED: `{username}`",
                allow_mentions=True,
            )
            return

        # ---- TAKEN ----
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
        "embeds": [
            {
                "title": title,
                "description": "```\n" + "\n".join(names[:50]) + "\n```",
                "color": color,
            }
        ],
        "allowed_mentions": {"parse": []},
    }
    async with aiohttp.ClientSession() as s:
        async with s.post(url, json=payload) as resp:
            if resp.status >= 400:
                print(f"[SUMMARY ERROR {resp.status}] {await resp.text()}")


# -------- MAIN -------- #
async def main():
    if MODE == "2c":
        usernames = [
            "".join(random.choice(CHARS) for _ in range(2)) for _ in range(AMOUNT)
        ]
    elif MODE == "3c":
        usernames = [
            "".join(random.choice(CHARS) for _ in range(3)) for _ in range(AMOUNT)
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

    queue = asyncio.Queue()
    for u in usernames:
        queue.put_nowait(u)

    print(f"Checking {len(usernames)} usernames | {CONCURRENCY} concurrent pages\n")

    async with aiohttp.ClientSession() as session:
        async with async_playwright() as p:
            browser = await p.chromium.launch(
                headless=True,
                args=["--no-sandbox", "--disable-dev-shm-usage"],
            )

            pages = [
                await browser.new_page(user_agent=USER_AGENT)
                for _ in range(CONCURRENCY)
            ]

            workers = [
                asyncio.create_task(worker(f"W{i}", queue, pages[i], session))
                for i in range(CONCURRENCY)
            ]

            await queue.join()

            for w in workers:
                w.cancel()

            await browser.close()

    print(f"\n✅ Available: {len(available_list)} | 🎯 Claimed: {len(claimed_list)} | ❌ Taken: {len(taken_list)} | ⚠️ Banned: {len(banned_list)}")

    await send_summary(WEBHOOK_AVAILABLE, "✅ Available Names", available_list, 0x57F287)
    await send_summary(WEBHOOK_CLAIMED or WEBHOOK_AVAILABLE, "🎯 Claimed Names", claimed_list, 0x00FF00)
    await send_summary(WEBHOOK_TAKEN, "❌ Taken Names", taken_list, 0xED4245)
    await send_summary(WEBHOOK_BANNED, "⚠️ Banned Names", banned_list, 0xFEE75C)

    print("Done.")


if __name__ == "__main__":
    asyncio.run(main())
