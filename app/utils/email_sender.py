from flask import current_app
from flask_mail import Message
from app import mail


def send_otp_email(email, otp_token, teacher_name=None):
    """Send OTP email. Falls back to logging if mail not configured."""
    name = teacher_name or email.split('@')[0]

    subject = 'Your Login OTP - MCQ Examiner'
    body = f"""Hello {name},

Your one-time password (OTP) for MCQ Examiner is:

    {otp_token}

This OTP is valid for 5 minutes. Do not share it with anyone.

If you did not request this, please ignore this email.

Best regards,
MCQ Examiner Team
"""
    html_body = f"""
<div style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto;">
    <h2 style="color: #2c3e50;">MCQ Examiner Login</h2>
    <p>Hello <strong>{name}</strong>,</p>
    <p>Your one-time password (OTP) is:</p>
    <div style="background: #f8f9fa; border: 2px solid #dee2e6; border-radius: 8px;
                padding: 20px; text-align: center; margin: 20px 0;">
        <span style="font-size: 36px; font-weight: bold; letter-spacing: 8px; color: #2c3e50;">
            {otp_token}
        </span>
    </div>
    <p>This OTP is valid for <strong>{current_app.config.get('OTP_EXPIRY_MINUTES', 5)} minutes</strong>.</p>
    <p style="color: #dc3545;">Do not share this OTP with anyone.</p>
    <hr>
    <p style="color: #6c757d; font-size: 12px;">
        If you did not request this, please ignore this email.
    </p>
</div>
"""

    mail_configured = bool(
        current_app.config.get('MAIL_USERNAME') and
        current_app.config.get('MAIL_PASSWORD')
    )

    if mail_configured:
        try:
            msg = Message(
                subject=subject,
                recipients=[email],
                body=body,
                html=html_body,
            )
            mail.send(msg)
            return True, None
        except Exception as e:
            current_app.logger.error(f'Failed to send email: {e}')
            return False, str(e)
    else:
        current_app.logger.info(f'[DEV MODE] OTP for {email}: {otp_token}')
        return False, 'dev_mode'
