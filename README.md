# cars

Telegram bot notifier for new electric-car listings on [OpenLane](https://www.openlane.eu).

Polls the OpenLane search page every 60 s through a logged-in Selenium browser and sends a
Telegram message for each listing it hasn't seen before.

## Setup

1. Install dependencies:

   ```
   pip install selenium beautifulsoup4 requests
   ```

2. Copy `.env.example` to `.env` and fill in your credentials:

   ```
   cp .env.example .env
   ```

   The script refuses to start if anything is missing, and verifies the Telegram token
   against `getMe` before entering the loop.

3. Create the browser profile once, solving the Cloudflare check and logging in by hand:

   ```
   python openlane_notifier_final.py --setup
   ```

   This stores the session in `edge_profile/` (Windows) or `firefox_profile/` (Linux).

4. Run it:

   ```
   python openlane_notifier_final.py
   ```

## Browsers

| Platform | Browser | Driver |
| --- | --- | --- |
| Windows | Edge | msedgedriver (auto-resolved by Selenium Manager) |
| Linux   | Firefox | geckodriver at `/usr/local/bin/geckodriver` |

Firefox is used on Linux because the Oracle Ampere host is ARM64, where Chrome has no build.

## Behaviour

- **Seen listings** persist in `seen_listings.json`, so a restart does not re-notify or
  silently skip listings posted while the notifier was down.
- **Burst cap**: after long downtime at most `MAX_BURST_NOTIFICATIONS` individual messages
  are sent, then one summary line for the rest.
- **Failed sends** are not marked as seen — they are retried on the next cycle.
- **Cloudflare** challenges retry with exponential backoff (5 → 30 min), indefinitely.
- **Maintenance** pages retry every 10 min, with a single Telegram heads-up.
- **Session expiry** triggers an automatic re-login; only after 3 genuine auth failures
  does it give up and send a Telegram alert asking for a manual `--setup`.
- The browser restarts every 6 h to keep memory in check.

## Deployment (Oracle host)

Runs under systemd as `openlane-notifier.service`:

```
sudo systemctl status openlane-notifier
sudo systemctl restart openlane-notifier
journalctl -u openlane-notifier -f
```

## Security

Credentials live in `.env` only, which is gitignored. Do not hard-code them in the source —
this repository is public and a committed bot token gets revoked automatically.
