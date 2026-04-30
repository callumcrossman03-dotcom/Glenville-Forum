# Security Notes

This project is now configured with basic production security defaults, but a public deployment should still be reviewed carefully.

## Included

- Passwords are hashed with Werkzeug.
- CSRF protection is applied to POST forms.
- Sessions are HTTP-only.
- Production mode supports secure cookies with `SESSION_COOKIE_SECURE=1`.
- Security headers are added for content sniffing, framing, referrer policy, and browser permissions.
- Uploads are limited to 8 MB and image extensions are restricted.
- Admin users can be bootstrapped with `ADMIN_EMAILS`.

