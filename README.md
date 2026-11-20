# Forgenix

A mobile-first learning app for exploring a technology career, practising with original project briefs, and saving progress. The complete starter path is free. Accounts are optional and add progress sync across devices; Pro checkout is optional and is not required for learning.

## Run locally

```powershell
pip install -r requirements.txt
python app.py
```

Open http://localhost:5000. The SQLite database is created at `instance/forgenix.sqlite3` by default. Change its location with `DATABASE_PATH`.

Run the test suite:

```powershell
python -m unittest discover -s tests -v
```

## Learning and progress

- Each career path contains four original activities, concrete deliverables, and a self-review checklist. The app does not claim that completion is a credential or verified qualification.
- Guest progress is saved in browser storage on that device. Creating a free account uploads progress and makes it available when signing in elsewhere.
- Accounts store an email address, a password hash, the selected path, weekly pace, completed modules, and subscription expiry. They do not store payment-card details.
- Use a persistent database volume in a hosted deployment. For example, mount a durable volume at `/var/data` and set `DATABASE_PATH=/var/data/forgenix.sqlite3`. If the host's filesystem is ephemeral, account progress and subscriptions can be lost when the service restarts; migrate to a managed database before relying on them.
- The current Render service is on the Free plan, whose local filesystem is ephemeral. The account screen warns users; do not rely on cross-device account sync or subscriptions there until durable storage is configured.

## Deploy to a Python host

The GitHub repository is [davidwithskills/Forgenix---Webapp](https://github.com/davidwithskills/Forgenix---Webapp). On a Python web host such as Render, create a Web Service for its `main` branch:

- Build command: `pip install -r requirements.txt`
- Start command: `gunicorn app:app`
- Set `SECRET_KEY` to a long, unique random value.
- Set `PUBLIC_URL` to the service's public HTTPS URL, for example `https://your-app.onrender.com`.
- Set `DATABASE_PATH` to a file on a persistent mounted volume if the host supports one.

Render's `RENDER_EXTERNAL_URL` is used as the public URL if `PUBLIC_URL` is omitted. If `SECRET_KEY` is omitted, the app generates a new random key at startup, which signs sessions safely but signs users out after each restart. The host must be able to install the dependencies in `requirements.txt`. A successful deploy makes the site available at its HTTPS URL. On iPhone, open that URL in Safari and choose **Share → Add to Home Screen**. On Android, open it in Chrome and choose **Install app** or **Add to Home screen**.

## GitHub Pages landing page

The static introduction lives in `docs/index.html`; it links visitors to the full Flask app on Render. The plans dialog compares the free starter and optional Pro preview; continuing to Pro opens the app account page, where the server-side Interswitch test checkout lives. The dialog warns that test checkout cannot accept real payments. A GitHub Actions workflow publishes the landing page when `docs/` changes. The published page is at `https://davidwithskills.github.io/Forgenix---Webapp/`. GitHub Pages only hosts the static landing page; accounts, progress syncing, and checkout stay on the Flask service.

## Payments

Interswitch is configured in `TEST` mode by default. The credentials in the code are documented sample values and may not be valid merchant credentials. Configure these environment variables with values from your Interswitch account:

- `ISW_MERCHANT_CODE`
- `ISW_PAY_ITEM_ID`
- `ISW_MODE` (`TEST` or `LIVE`)
- `PUBLIC_URL` (required for the payment return URL)

Live mode refuses to start checkout when the sample or missing merchant credentials are detected. The ₦2,000 monthly price is a placeholder. Pro is optional, does not auto-renew, and must not be marketed as purchasable until the merchant account, price, callback, and persistence have been confirmed. Payment status is checked server-side with Interswitch; do not remove that check.

## Current limitations before production use

- No password reset, email verification, account deletion, or login rate limiting is included. Add those before inviting the public to create accounts.
- SQLite persistence depends on the host's persistent storage configuration. Back up the database and protect access to its volume.
- Guest progress only exists in that browser's local storage until the user signs into an account.
- The learning paths are starter activities, not accredited training or job placement. Opportunity matching and peer review are not implemented.
- Review the deployment host's security, privacy, and backup settings before storing real user data.
