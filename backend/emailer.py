import asyncio
import logging
import os

import resend

logger = logging.getLogger("emailer")


def configured() -> bool:
    return bool(os.environ.get("RESEND_API_KEY"))


async def send_email(to: str, subject: str, html: str) -> bool:
    """Send via Resend when configured; otherwise log and return False so callers can fall back."""
    if not configured():
        logger.warning("RESEND_API_KEY not set — email to %s NOT sent (subject: %s)", to, subject)
        return False
    resend.api_key = os.environ["RESEND_API_KEY"]
    params = {"from": os.environ.get("SENDER_EMAIL", "onboarding@resend.dev"), "to": [to], "subject": subject, "html": html}
    try:
        res = await asyncio.to_thread(resend.Emails.send, params)
        logger.info("email sent to %s id=%s", to, res.get("id") if isinstance(res, dict) else res)
        return True
    except Exception as e:  # noqa: BLE001
        logger.error("Resend send failed: %s", e)
        return False


def reset_email_html(name: str, link: str) -> str:
    return f"""
<table width="100%" cellpadding="0" cellspacing="0" style="background:#0A0E17;padding:32px;font-family:Arial,sans-serif;color:#F8FAFC">
  <tr><td align="center">
    <table width="520" cellpadding="0" cellspacing="0" style="background:#162032;border:1px solid #334155;border-radius:8px;padding:28px">
      <tr><td style="font-size:20px;font-weight:bold">Sentinel<span style="color:#00F0FF">Mar</span> — password reset</td></tr>
      <tr><td style="padding-top:14px;font-size:14px;line-height:20px;color:#CBD5E1">Hello {name},<br/>A password reset was requested for your authority account. This link expires in 60 minutes and can be used once.</td></tr>
      <tr><td style="padding-top:20px"><a href="{link}" style="background:#00F0FF;color:#0A0E17;padding:10px 18px;border-radius:4px;text-decoration:none;font-weight:bold;font-size:13px">Reset password</a></td></tr>
      <tr><td style="padding-top:18px;font-size:11px;color:#94A3B8">If you did not request this, ignore this email. The request has been recorded in the audit log.</td></tr>
    </table>
  </td></tr>
</table>"""
