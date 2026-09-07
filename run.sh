#!/bin/bash
# Launch the notifier inside a virtual X display (Firefox runs "headed" under Xvfb,
# which passes Cloudflare more reliably than true headless).
cd /home/ubuntu/cars
exec xvfb-run -a --server-args="-screen 0 1920x1080x24" /usr/bin/python3 -u /home/ubuntu/cars/openlane_notifier_final.py
