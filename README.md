# Forgenix web app (with Interswitch Web Checkout)

Flow: goal -> learning path -> matched opportunities -> Pro plan -> redirect to the Interswitch payment page -> back to the app -> server confirms the payment -> Pro unlocks.

## Run it
    pip install -r requirements.txt
    python app.py

On this computer, open http://localhost:5000.

## Open it on another device on the same Wi-Fi
1. Start the app with `python app.py` and leave that terminal open.
2. On this computer, run `ipconfig` and find the **IPv4 Address** for the Wi-Fi adapter (for example, `192.168.0.102`).
3. On the other device, open `http://<IPv4-address>:5000` (for example, `http://192.168.0.102:5000`). Both devices must be on the same network.
4. If Windows asks, allow Python through Windows Defender Firewall on **Private networks**. If it does not ask and the page cannot be reached, allow inbound TCP port 5000 on the Private profile.

The address may change when the computer reconnects to Wi-Fi. This is only for devices on your local network; for access over the internet, deploy to a Python host or use a secure tunnel as described below.

## Interswitch settings (environment variables)
- `ISW_MERCHANT_CODE`, `ISW_PAY_ITEM_ID`: from your Interswitch developer console. The defaults are the sample sandbox values from Interswitch's docs and may not work; see their "Default Test Credentials" page.
- `ISW_MODE`: `TEST` (default) or `LIVE`.
- `PUBLIC_URL`: where Interswitch sends the customer back. Default `http://localhost:5000` works on your own computer. When deployed, set it to your real https address.
- `SECRET_KEY`: any long random string (needed in production).

Test with Interswitch test cards: https://docs.interswitchgroup.com/docs/test-cards

## Share with teammates
For a public HTTPS URL, deploy this app folder to a Python host such as Render:
1. Put only this app folder in its own Git repository and push it to GitHub. Do not publish the folder that contains it.
2. Create a Python web service on your host, using `pip install -r requirements.txt` as the build command and `gunicorn app:app` as the start command.
3. Set `SECRET_KEY` to a long, random value, and set `PUBLIC_URL` to the service's public HTTPS URL (for example, `https://your-app.onrender.com`). HTTPS is required for installation and is enabled for session cookies when `PUBLIC_URL` starts with `https://`.
4. Open that HTTPS URL on your phone. On iPhone, use Safari's **Share → Add to Home Screen**; on Android, use Chrome's **Install app** or **Add to Home screen**.

The manifest and service worker make the app installable and let its shell load offline; payment and other server features still require an internet connection. Do not use the local-network address as `PUBLIC_URL` for payment callbacks; Interswitch needs a publicly reachable URL.

## Before real money
- Pending orders are kept in memory and the Pro unlock lives in a cookie. Move both to a database tied to user accounts.
- Price (NGN 2,000/month) is a placeholder.
- Web Checkout is one-time. Auto-renewal needs Interswitch's Recurring Payments API.
- Payments are confirmed with a server-side requery in `payment_response`. Keep that check.

## Source and licence lines
Each module in the learning path shows its source and licence. They are read from `static/sources.json`, so you can edit them without touching code. Entries marked "to be added" are placeholders: only list material whose licence you have checked yourself, and avoid non-commercial (NC) licences for the paid plan. Check the licence of any source on the day you add it, because licences can change.
