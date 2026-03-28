# LinkFlow — Deployment Guide

## Local Development

```bash
# 1. Clone / copy files to your project folder
cd urlshortener

# 2. Create virtual environment
python -m venv venv
source venv/bin/activate      # Windows: venv\Scripts\activate

# 3. Install dependencies
pip install -r requirements.txt

# 4. Configure environment
cp .env.example .env
# Edit .env with your values

# 5. Load .env and run
python app.py
# → http://localhost:5000
```

## MongoDB Setup

Option A — Local (free):
  Install MongoDB Community: https://www.mongodb.com/try/download/community
  MONGO_URI=mongodb://localhost:27017/

Option B — MongoDB Atlas (free tier, recommended for production):
  1. Create account at https://cloud.mongodb.com
  2. Create free M0 cluster
  3. Get connection string
  4. Set MONGO_URI=mongodb+srv://user:pass@cluster.mongodb.net/

## Ad Network Setup

### PopAds (popunder)
1. Sign up at https://www.popads.net
2. Add your website
3. Get your site-specific <script> tag
4. Paste the full script tag content into POPADS_SCRIPT in .env

### Adsterra (direct link)
1. Sign up at https://publishers.adsterra.com
2. Create a "Direct Link" ad unit
3. Copy the direct link URL
4. Set ADSTERRA_URL=https://your-link in .env

### Monetag (smart link)
1. Sign up at https://monetag.com
2. Create a "Smart Link" campaign
3. Copy the link
4. Set MONETAG_URL=https://your-link in .env

## Telegram Bot Integration

In your bot (python-telegram-bot example):

```python
import httpx

async def check_token(token: str, base_url: str) -> bool:
    r = await httpx.get(f"{base_url}/api/check_token", params={"token": token})
    return r.json().get("valid", False)

# In your bot handler:
@bot.message_handler(func=lambda m: True)
async def handle(message):
    token = message.text.strip()
    valid = await check_token(token, "https://your-app.onrender.com")
    if valid:
        await bot.reply_to(message, "✅ Access granted!")
    else:
        await bot.reply_to(message, "❌ Invalid or expired token.")
```

## Deploy to Render (free tier)

1. Push code to GitHub
2. New Web Service → connect repo
3. Build command: pip install -r requirements.txt
4. Start command:  gunicorn app:app --bind 0.0.0.0:$PORT
5. Add environment variables in Render dashboard

## Deploy to Koyeb

1. Push to GitHub
2. New App → GitHub → select repo
3. Run command: gunicorn app:app --bind 0.0.0.0:8000
4. Set env vars in Koyeb settings

## API Reference

| Method | Endpoint              | Description                          |
|--------|-----------------------|--------------------------------------|
| POST   | /create               | Create short URL                     |
| GET    | /go/<id>              | Start redirect/ad flow               |
| GET    | /verify?token=X       | Consume & validate token             |
| GET    | /api/check_token?token=X | Bot check (read-only)             |
| GET    | /stats/<id>           | Analytics for a short URL            |
| GET    | /                     | Frontend URL creation page           |
