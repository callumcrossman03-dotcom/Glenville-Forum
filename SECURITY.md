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

## Recommended Before Public Launch

- Use HTTPS only.
- Use a long random `SECRET_KEY`.
- Store uploads outside the repo or in object storage.
- Add email verification.
- Add password reset.
- Add rate limiting for login, registration, posting, and messaging.
- Add virus scanning or stronger MIME validation for uploads.
- Add privacy policy and terms pages.
