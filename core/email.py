import os
import smtplib
from email.message import EmailMessage


SMTP_HOST = os.getenv("SMTP_HOST", "smtp.gmail.com")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
SMTP_USERNAME = os.getenv("SMTP_USERNAME")
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD")
SMTP_FROM_EMAIL = os.getenv("SMTP_FROM_EMAIL", SMTP_USERNAME)
INVITE_BASE_URL = os.getenv("INVITE_BASE_URL")


def send_operator_invitation_email(
    to_email: str,
    church_name: str,
    invitation_token: str,
) -> None:
    if not SMTP_USERNAME or not SMTP_PASSWORD:
        raise ValueError("SMTP credentials are not configured.")
    
    if INVITE_BASE_URL.startswith("INVITE_BASE_URL="):
        raise ValueError("INVITE_BASE_URL is malformed in .env. Remove the duplicated 'INVITE_BASE_URL=' prefix.")

    if not INVITE_BASE_URL:
        raise ValueError("INVITE_BASE_URL is not configured.")

    invite_link = f"{INVITE_BASE_URL}/accept-invite/{invitation_token}".strip()

    subject = f"You're invited to join VerseCast for {church_name}"

    text_body = (
        f"Hello,\n\n"
        f"You have been invited to join VerseCast as an operator for {church_name}.\n\n"
        f"Accept your invitation:\n"
        f"{invite_link}\n\n"
        f"If clicking does not work, copy and paste this link into your browser:\n"
        f"<{invite_link}>\n\n"
        f"If you were not expecting this invitation, you can ignore this email.\n\n"
        f"Blessings,\n"
        f"VerseCast\n"
    )

    html_body = f"""\
<!doctype html>
<html>
  <body style="margin:0;padding:24px;background:#f9fafb;font-family:Arial,sans-serif;">
    <table role="presentation" width="100%" cellspacing="0" cellpadding="0" border="0">
      <tr>
        <td align="center">
          <table role="presentation" width="520" cellspacing="0" cellpadding="0" border="0" style="max-width:520px;background:#ffffff;border:1px solid #e5e7eb;border-radius:10px;">
            <tr>
              <td style="padding:32px;">
                <h2 style="margin:0 0 16px 0;color:#111827;font-size:24px;line-height:32px;">
                  You're invited to join VerseCast
                </h2>

                <p style="margin:0 0 16px 0;color:#374151;font-size:14px;line-height:22px;">
                  You have been invited to join <strong>VerseCast</strong> as an operator for
                  <strong>{church_name}</strong>.
                </p>

                <p style="margin:24px 0;text-align:center;">
                  <a href="{invite_link}" target="_blank"
                     style="background:#2b124c;color:#ffffff;text-decoration:none;padding:12px 20px;border-radius:8px;display:inline-block;font-size:14px;font-weight:600;">
                    Accept Invitation
                  </a>
                </p>

                <p style="margin:0 0 10px 0;color:#6b7280;font-size:13px;line-height:20px;">
                  If the button does not work, copy and paste this link into your browser:
                </p>

                <p style="margin:0 0 20px 0;font-size:13px;line-height:20px;word-break:break-all;">
                  <a href="{invite_link}" target="_blank" style="color:#2563eb;text-decoration:underline;">
                    {invite_link}
                  </a>
                </p>

                <p style="margin:0;color:#9ca3af;font-size:12px;line-height:18px;">
                  If you were not expecting this invitation, you can safely ignore this email.
                </p>

                <p style="margin:16px 0 0 0;color:#9ca3af;font-size:12px;line-height:18px;">
                  — VerseCast
                </p>
              </td>
            </tr>
          </table>
        </td>
      </tr>
    </table>
  </body>
</html>
"""

    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = SMTP_FROM_EMAIL
    msg["To"] = to_email
    msg.set_content(text_body)
    msg.add_alternative(html_body, subtype="html")

    with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as server:
        server.starttls()
        server.login(SMTP_USERNAME, SMTP_PASSWORD)
        server.send_message(msg)