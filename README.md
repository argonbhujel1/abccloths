# ABC Clothing

Premium animated fashion e-commerce storefront with a minimal admin panel.

**Technology by [BAM Studio](https://bamstudio.argan.com.np/)**

## Features

- Responsive public storefront (HTML/CSS/vanilla JS)
- Five selectable color themes (persisted in localStorage)
- Product catalog with category filters, search, sorting, quick-view
- Functional cart (localStorage) and order-request checkout
- Homepage notice (banner or modal) managed from admin
- Logo & favicon branding via ImgBB URLs
- Fallback product catalog when Neon PostgreSQL is unavailable
- Flask API on Vercel Python runtime
- Neon PostgreSQL for products, settings, notices, orders
- Resend email for order & contact notifications
- Secure admin at `/siteadmin/login/admin` (session auth, CSRF, rate limiting)
- Exactly three admin sections: Products, Homepage Notice, Website Branding

## Stack

| Layer        | Technology                          |
|--------------|-------------------------------------|
| Frontend     | HTML5, CSS3, vanilla JavaScript     |
| Backend      | Python Flask                        |
| Database     | Neon PostgreSQL                     |
| Email        | Resend                              |
| Images       | ImgBB direct URLs (admin-pasted)    |
| Hosting      | Vercel (Python serverless)          |

## Project structure

```
abc-clothing/
├── api/
│   └── index.py          # Flask app (API + admin)
├── public/
│   ├── index.html
│   ├── shop.html
│   ├── product.html
│   ├── checkout.html
│   ├── contact.html
│   ├── css/styles.css
│   ├── js/
│   │   ├── app.js
│   │   ├── api.js
│   │   ├── cart.js
│   │   └── fallback-data.js
│   └── assets/
├── requirements.txt
├── vercel.json
├── .env.example
├── .python-version
├── .gitignore
└── README.md
```

## Local setup

1. Clone / unzip the project.
2. Create a virtualenv and install dependencies:

```bash
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

3. Copy environment variables:

```bash
cp .env.example .env
# Edit .env with your values
```

4. Run Flask locally (for API testing):

```bash
cd api
# Or from project root with PYTHONPATH
export FLASK_APP=api/index.py
python -m flask --app api.index run --port 5000
```

For a production-like local experience, use the Vercel CLI:

```bash
npm i -g vercel
vercel dev
```

Static files are served from `public/`. API routes are handled by `api/index.py`.

## Environment variables

| Variable                 | Description                                              |
|--------------------------|----------------------------------------------------------|
| `DATABASE_URL`           | Neon PostgreSQL connection string                        |
| `RESEND_API_KEY`         | Resend API key                                           |
| `SHOP_EMAIL`             | Destination for order/contact emails (default set)       |
| `EMAIL_FROM`             | Verified sender, e.g. `ABC Clothing <orders@domain.com>` |
| `SESSION_SECRET`         | Long random string for Flask sessions                    |
| `INITIAL_ADMIN_USERNAME` | Created on first successful DB connection if no admin    |
| `INITIAL_ADMIN_PASSWORD` | Strong password for the initial admin                    |

**Never commit a real `.env` file.** Configure secrets in the Vercel project settings for production.

## Neon database

1. Create a project at [neon.tech](https://neon.tech).
2. Copy the connection string into `DATABASE_URL`.
3. Schema is created automatically on first successful connection (products, website_settings, homepage_notice, orders, admin_users, login_attempts).
4. The first admin user is inserted from `INITIAL_ADMIN_*` when the `admin_users` table is empty.

## Admin

- **Login URL:** `/siteadmin/login/admin`
- **Dashboard:** `/siteadmin/dashboard` (after login)
- **Logout:** `/siteadmin/logout`

### Products

- Add / edit / delete products
- Fields: name, price (NPR), image URL (ImgBB), description, category, colors, sizes, active
- Upload images at [imgbb.com](https://imgbb.com/), copy the **direct** image URL (e.g. `https://i.ibb.co/...`)
- Disable a product to hide it from the storefront without deleting it

### Homepage notice

- Title, message, optional image, button text/URL
- Type: top banner or modal popup
- Enable/disable and optional start/end dates

### Website branding

- Logo URL and favicon URL (ImgBB)
- Leave empty to use the default text logo / bundled favicon

## Fallback catalog

When Neon is unreachable, the public site loads the bundled catalog from `public/js/fallback-data.js`. Navigation, themes, cart, search, and filtering continue to work. Order submission and admin writes require a live database and will show honest errors if unavailable.

## Resend

1. Create an account at [resend.com](https://resend.com).
2. Verify your sending domain.
3. Set `RESEND_API_KEY` and `EMAIL_FROM` (must use the verified domain).
4. Order notifications and contact form messages are sent to `SHOP_EMAIL`.

## Deploy on Vercel

1. Push the project to GitHub (or import the folder).
2. Create a new Vercel project and import the repository.
3. Set **Root Directory** to the project root (where `vercel.json` lives).
4. Add all environment variables in Project Settings → Environment Variables.
5. Deploy.

`vercel.json` rewrites `/api/*` and `/siteadmin/*` to the Flask function. Static assets under `public/` are served by the CDN.

Python version is pinned via `.python-version` (3.12).

## Security notes

- Admin write endpoints require a logged-in session and CSRF token.
- Login is rate-limited (DB-backed).
- Passwords are hashed with Werkzeug.
- Order prices are verified server-side against the database.
- No payment gateway — orders are **requests** only.
- Secrets are never exposed to the frontend.

## Testing checklist

- [ ] Homepage loads with fallback products when DB is unset
- [ ] Live products replace fallback when Neon is configured
- [ ] Theme switcher persists across reloads
- [ ] Cart add/update/remove and localStorage persistence
- [ ] Checkout rejects empty cart and invalid fields
- [ ] Admin login at `/siteadmin/login/admin`
- [ ] Product CRUD and enable/disable
- [ ] Notice and branding updates appear on the public site
- [ ] Footer credit links to https://bamstudio.argan.com.np/

## Known limitations

- No online payment processing (by design).
- Image hosting is external (ImgBB); broken URLs fall back to a placeholder SVG.
- Live email and DB features require configured credentials; without them the public site still works via fallbacks.
- Vercel function duration and memory are set in `vercel.json` (30s / 1024 MB).

## License

Proprietary — built for ABC Clothing. Technology credit: BAM Studio.
