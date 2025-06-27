#!/usr/bin/env python3
import subprocess
import smtplib
from email.mime.text import MIMEText

ALERT_THRESHOLD = 5         # Only alert if 5 or more messages are queued
TO_ADDR = "jstephens@eusd.org"  # <-- Change this!
FROM_ADDR = "mailrelay@eusd.org"
SMTP_SERVER = "localhost"

def get_queue_counts():
    try:
        output = subprocess.check_output(['mailq'], text=True)
        active = sum(1 for line in output.splitlines() if "active" in line)
        deferred = sum(1 for line in output.splitlines() if "deferred" in line)
        total_ids = sum(1 for line in output.splitlines() if line and line[0].isalnum() and '-' not in line and ':' not in line)
        return total_ids, active, deferred
    except Exception as e:
        return -1, -1, -1

def send_alert(total, active, deferred):
    msg_text = (
        f"Postfix Alert: There are {total} messages in the queue!\n"
        f"  Active: {active}\n"
        f"  Deferred: {deferred}\n\n"
        f"Please check mailq and /var/log/mail.log immediately.\n"
    )
    msg = MIMEText(msg_text)
    msg['Subject'] = "URGENT: Postfix Mail Queue Alert"
    msg['From'] = FROM_ADDR
    msg['To'] = TO_ADDR
    with smtplib.SMTP(SMTP_SERVER) as server:
        server.send_message(msg)

def main():
    total, active, deferred = get_queue_counts()
    if total >= ALERT_THRESHOLD:
        send_alert(total, active, deferred)

if __name__ == "__main__":
    main()
