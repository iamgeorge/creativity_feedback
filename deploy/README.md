# Running the site as a service

The site runs under systemd as `creativity-feedback` (gunicorn on port 5555).
It starts when the machine boots and restarts if it crashes. A watchdog timer
checks `/healthz` every 2 minutes and restarts it if it has stopped answering.

```bash
sudo systemctl status creativity-feedback        # is it running?
sudo journalctl -u creativity-feedback -f         # live logs
sudo systemctl restart creativity-feedback        # after changing code, templates or .env
```

Install or update the unit files (from the project root):

```bash
sudo cp deploy/creativity-feedback*.service deploy/creativity-feedback-watchdog.timer /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now creativity-feedback creativity-feedback-watchdog.timer
```

Notes:
- The service runs as user `george`, so `data/` must be writable by `george`.
- Port 5555 can only be used by one program. Stop the service before running
  `python app.py` on the same port, or use `PORT=5556 python app.py`.
- This machine is WSL: the service only runs while Windows is on and WSL is started.
