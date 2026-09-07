# Deploying on a fresh Linux host (Oracle Cloud)

Tested on Oracle Cloud Ubuntu 22.04 (both ARM `VM.Standard.A1.Flex` and x86
`VM.Standard.E2.1.Micro`). The notifier runs Firefox under a virtual X display
(`Xvfb`) — "headed under Xvfb" passes Cloudflare more reliably than true headless.

## 1. System packages

```bash
# 3 GB swap (essential on the 1 GB E2.1.Micro so Firefox doesn't OOM)
sudo fallocate -l 3G /swapfile && sudo chmod 600 /swapfile
sudo mkswap /swapfile && sudo swapon /swapfile
echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab

sudo apt-get update
sudo apt-get install -y python3-pip git wget xvfb ca-certificates

# Firefox as a real .deb (NOT the Ubuntu snap, which fights Selenium)
sudo install -d -m 0755 /etc/apt/keyrings
wget -q https://packages.mozilla.org/apt/repo-signing-key.gpg -O- \
  | sudo tee /etc/apt/keyrings/packages.mozilla.org.asc >/dev/null
echo "deb [signed-by=/etc/apt/keyrings/packages.mozilla.org.asc] https://packages.mozilla.org/apt mozilla main" \
  | sudo tee /etc/apt/sources.list.d/mozilla.list
printf 'Package: *\nPin: origin packages.mozilla.org\nPin-Priority: 1000\n' \
  | sudo tee /etc/apt/preferences.d/mozilla
sudo apt-get update && sudo apt-get install -y firefox

# geckodriver
GV=$(wget -qO- https://api.github.com/repos/mozilla/geckodriver/releases/latest | grep -oP '"tag_name":\s*"\K[^"]+')
wget -q "https://github.com/mozilla/geckodriver/releases/download/${GV}/geckodriver-${GV}-linux64.tar.gz" -O /tmp/gd.tar.gz
sudo tar -xzf /tmp/gd.tar.gz -C /usr/local/bin && sudo chmod +x /usr/local/bin/geckodriver
```

> On ARM (A1.Flex) download `geckodriver-${GV}-linux-aarch64.tar.gz` instead.

## 2. App

```bash
cd ~ && git clone https://github.com/kaloyanpetkovv/cars.git && cd cars
sudo pip3 install -r requirements.txt
cp .env.example .env && nano .env      # fill in the real values
mkdir -p firefox_profile               # OpenLane's search page is public, so no manual --setup login is needed
```

Lean Firefox prefs (helps a lot on the 1 GB box) — `firefox_profile/user.js`:

```
user_pref("browser.cache.disk.enable", false);
user_pref("dom.ipc.processCount", 1);
user_pref("browser.tabs.remote.autostart", false);
user_pref("app.update.enabled", false);
```

## 3. systemd service

```bash
chmod +x run.sh
sudo cp openlane-notifier.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now openlane-notifier
journalctl -u openlane-notifier -f
```

`run.sh` wraps the script in `xvfb-run`. `Restart=always` plus the script's own
browser-restart logic keep it running across Firefox crashes (frequent on 1 GB,
rare on the 6–12 GB ARM shape).
```
