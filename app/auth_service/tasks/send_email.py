import asyncio
from app.taskiq import broker
from app.core.config import Settings

settings = Settings()

from loguru import logger

@broker.task
async def send_email_task(email: str, subject: str, content: str):
    """
    Simulate sending email.
    In real world, use aiosmtplib.
    """
    logger.info(f"Task [send_email] started. To: {email}")

    # For now, just log or simulate
    # We can use aiosmtplib if we want real implementation
    import aiosmtplib
    from email.message import EmailMessage

    message = EmailMessage()
    message["From"] = f"{settings.emails_from_name} <{settings.emails_from_email}>"
    message["To"] = email
    message["Subject"] = subject
    message.set_content(content)

    if settings.work_environment == "development":
        logger.debug(f"Sending email to {email}: {subject}\n{content}")
        # In dev, maybe don't actually send if not configured, or use localhost mailhog
    
    try:
        await aiosmtplib.send(
            message,
            hostname=settings.smtp_host,
            port=settings.smtp_port,
            username=settings.smtp_user,
            password=settings.smtp_password,
        )
        logger.info(f"Task [send_email] completed.")
    except Exception as e:
        logger.error(f"Failed to send email: {e}")
        # Re-raise to let taskiq retry?
        raise e
