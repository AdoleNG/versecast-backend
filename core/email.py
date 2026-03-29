import os
import resend


def send_operator_invitation_email(
    to_email: str,
    church_name: str,
    invitation_token: str,
) -> None:
    print("EMAIL FUNCTION: entered function body")

    # --------------------------------------------------
    # LOAD ENV VARIABLES (INSIDE FUNCTION — CRITICAL FIX)
    # --------------------------------------------------
    RESEND_API_KEY = os.getenv("RESEND_API_KEY")
    RESEND_FROM_EMAIL = os.getenv(
        "RESEND_FROM_EMAIL",
        "VerseCast <noreply@versecast.ca>"
    )
    INVITE_BASE_URL = os.getenv("INVITE_BASE_URL")

    # --------------------------------------------------
    # DEBUG LOGS
    # --------------------------------------------------
    print("RESEND_API_KEY loaded:", bool(RESEND_API_KEY))
    print("RESEND_FROM_EMAIL:", RESEND_FROM_EMAIL)
    print("INVITE_BASE_URL:", INVITE_BASE_URL)
    print("TO EMAIL:", to_email)

    # --------------------------------------------------
    # VALIDATION
    # --------------------------------------------------
    if not RESEND_API_KEY:
        raise ValueError("RESEND_API_KEY is not configured.")

    if not INVITE_BASE_URL:
        raise ValueError("INVITE_BASE_URL is not configured.")

    # --------------------------------------------------
    # INIT RESEND
    # --------------------------------------------------
    resend.api_key = RESEND_API_KEY

    # --------------------------------------------------
    # BUILD INVITE LINK (FIXED FORMAT)
    # --------------------------------------------------
    invite_link = f"{INVITE_BASE_URL}/accept-invite?token={invitation_token}"
    print("INVITE LINK:", invite_link)

    # --------------------------------------------------
    # EMAIL CONTENT
    # --------------------------------------------------
    subject = f"You're invited to join VerseCast for {church_name}"

    html_body = f"""
      <div style="font-family: Arial, sans-serif; padding: 24px; background: #f9fafb;">
        <div style="max-width: 520px; margin: auto; background: #ffffff; border: 1px solid #e5e7eb; border-radius: 10px; padding: 32px;">
          
          <h2 style="margin: 0 0 16px 0; color: #111827; font-size: 24px;">
            You're invited to join VerseCast
          </h2>

          <p style="color: #374151; font-size: 14px; line-height: 22px;">
            You have been invited to join <strong>{church_name}</strong> as an operator.
          </p>

          <p style="margin: 24px 0; text-align: center;">
            <a href="{invite_link}" target="_blank"
               style="background:#2b124c;color:#ffffff;text-decoration:none;padding:12px 20px;border-radius:8px;display:inline-block;font-size:14px;font-weight:600;">
              Accept Invitation
            </a>
          </p>

          <p style="color:#6b7280;font-size:13px;line-height:20px;">
            If the button does not work, copy and paste this link into your browser:
          </p>

          <p style="font-size:13px;line-height:20px;word-break:break-all;">
            <a href="{invite_link}" target="_blank" style="color:#2563eb;text-decoration:underline;">
              {invite_link}
            </a>
          </p>

          <p style="color:#9ca3af;font-size:12px;line-height:18px;">
            If you were not expecting this invitation, you can safely ignore this email.
          </p>

          <p style="margin-top:16px;color:#9ca3af;font-size:12px;line-height:18px;">
            — VerseCast
          </p>

        </div>
      </div>
    """

    # --------------------------------------------------
    # SEND EMAIL
    # --------------------------------------------------
    try:
        response = resend.Emails.send({
            "from": RESEND_FROM_EMAIL,
            "to": to_email,
            "subject": subject,
            "html": html_body,
        })

        print("RESEND RESPONSE:", response)

    except Exception as e:
        print("EMAIL SEND ERROR:", str(e))
        raise