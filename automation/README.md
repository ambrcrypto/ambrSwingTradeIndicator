# AMB Automation (Hostinger VPS)

This folder contains a minimal webhook bot to execute TradingView alerts on Bybit.

## What this setup does

- Receives alerts via `POST /webhook`
- Validates shared secret (`WEBHOOK_SECRET`)
- Deduplicates events (`event_id` hash in SQLite)
- Executes one-way position actions on Bybit:
  - `ENTER_LONG`
  - `ENTER_SHORT`
  - `EXIT_LONG`
  - `EXIT_SHORT`
- Starts in safe mode (`DRY_RUN=true`)

## 1. VPS install (Ubuntu)

```bash
sudo apt update
sudo apt install -y python3 python3-venv nginx
sudo mkdir -p /opt/ambbot
sudo chown -R $USER:$USER /opt/ambbot
```

Copy files from this repository folder `automation/` to `/opt/ambbot`.

## 2. Python environment

```bash
cd /opt/ambbot
python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
cp .env.example .env
```

Edit `.env`:

- set `WEBHOOK_SECRET` to a long random string
- keep `DRY_RUN=true` for first tests
- set `BYBIT_API_KEY` and `BYBIT_API_SECRET`
- start with `BYBIT_TESTNET=true`
- set `SYMBOL=BTC/USDT:USDT`
- set `ORDER_NOTIONAL_USDT` to a small value

## 3. Test local service

```bash
cd /opt/ambbot
source .venv/bin/activate
uvicorn main:app --host 127.0.0.1 --port 8080
```

Health check:

```bash
curl http://127.0.0.1:8080/health
```

## 4. Test webhook manually

```bash
curl -X POST http://127.0.0.1:8080/webhook \
  -H "Content-Type: application/json" \
  -d '{"secret":"replace_with_long_random_secret","action":"ENTER_LONG","ticker":"BTCUSDT","bar_time":"2026-04-11T00:00:00Z"}'
```

Expected with dry-run:

- Response includes `"mode": "dry_run"`
- No live order is sent

## 5. Run as system service

Copy service file:

```bash
sudo cp systemd/amb-bot.service /etc/systemd/system/amb-bot.service
sudo systemctl daemon-reload
sudo systemctl enable amb-bot
sudo systemctl start amb-bot
sudo systemctl status amb-bot
```

Logs:

```bash
journalctl -u amb-bot -f
```

## 6. Nginx reverse proxy (HTTPS)

Use your domain (for example `bot.example.com`) and point DNS A record to VPS IP.

Minimal nginx site:

```nginx
server {
    listen 80;
    server_name bot.example.com;

    location / {
        proxy_pass http://127.0.0.1:8080;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

Then enable TLS:

```bash
sudo apt install -y certbot python3-certbot-nginx
sudo certbot --nginx -d bot.example.com
```

Webhook URL for TradingView:

- `https://bot.example.com/webhook`

## 7. TradingView alert payloads

Create 4 alerts in TradingView (one per condition). Use these JSON messages:

ENTER LONG:

```json
{"secret":"YOUR_SECRET","action":"ENTER_LONG","ticker":"{{ticker}}","bar_time":"{{time}}"}
```

ENTER SHORT:

```json
{"secret":"YOUR_SECRET","action":"ENTER_SHORT","ticker":"{{ticker}}","bar_time":"{{time}}"}
```

EXIT LONG:

```json
{"secret":"YOUR_SECRET","action":"EXIT_LONG","ticker":"{{ticker}}","bar_time":"{{time}}"}
```

EXIT SHORT:

```json
{"secret":"YOUR_SECRET","action":"EXIT_SHORT","ticker":"{{ticker}}","bar_time":"{{time}}"}
```

Important:

- In TradingView alert dialog, keep `Once Per Bar Close`
- Use the matching condition from the indicator
- Make sure secret matches `.env`

## 8. Go live safely

1. Keep `DRY_RUN=true` and run for at least 3-5 days.
2. Verify each signal in logs.
3. Switch to `BYBIT_TESTNET=false` and still keep `DRY_RUN=true` for one day.
4. Set `DRY_RUN=false` only after validation.

## 9. Operational checklist

- Daily: check `journalctl -u amb-bot -n 100`
- Weekly: verify API keys and exchange permissions
- Monthly: rotate `WEBHOOK_SECRET`

## Notes

- This bot expects one-way mode behavior.
- Keep leverage and margin mode configured directly on Bybit account.
- If your account uses hedge mode, extend order parameters before going live.
