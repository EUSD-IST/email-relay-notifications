#!/usr/bin/env python3
import re
from collections import Counter, defaultdict
from datetime import datetime, timedelta
import gzip
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import os
import socket
import json
import csv
import io

# ===== USER CONFIGURATION =====
LOG_PATHS = ["/var/log/mail.log", "/var/log/mail.log.1"]
RECIPIENT = "jstephens@eusd.org"         # <-- Change me!
SENDER = "mailrelay@eusd.org"          # <-- Change me!
SMTP_SERVER = "localhost"
SMTP_PORT = 25
HOSTNAME = socket.gethostname()

# Phase 2 Configuration
HISTORY_FILE = "/var/log/postfix_daily_history.json"  # Historical data storage
ALERT_THRESHOLDS = {
    "min_success_rate": 95,  # Higher threshold for high volume
    "max_queue_time": 30,    # Stricter for high volume
    "max_auth_failures": 50,  # Increased for high volume
    "high_volume_threshold_pct": 0.05,  # 5% of total traffic
    "max_hourly_volume": 500,  # Alert if any hour exceeds this
    "min_hourly_volume": 10,   # Alert if any hour below this (during business hours)
    "max_avg_size": 10485760,  # 10MB average message size alert
    "max_defer_rate": 5,       # Max 5% defer rate
}
ENABLE_EXPORTS = True  # Enable CSV/JSON exports
HIGH_VOLUME_MODE = True  # Enable high-volume optimizations
# ==============================

# CSS styling for HTML email
CSS = """
<style>
    body {
        font-family: Arial, sans-serif;
        line-height: 1.6;
        color: #333;
        max-width: 900px;
        margin: 0 auto;
        padding: 20px;
    }
    h1 {
        color: #2c3e50;
        border-bottom: 3px solid #3498db;
        padding-bottom: 15px;
        text-align: center;
        margin-bottom: 5px;
        font-size: 2.2em;
    }
    h2 {
        color: #2980b9;
        margin-top: 25px;
    }
    .summary-box {
        background: linear-gradient(135deg, #f8f9fa 0%, #e9ecef 100%);
        border-left: 5px solid #3498db;
        padding: 20px;
        margin: 25px 0;
        border-radius: 8px;
        box-shadow: 0 2px 4px rgba(0,0,0,0.1);
    }
    .stats {
        display: flex;
        justify-content: space-between;
        flex-wrap: wrap;
        margin: 20px 0;
    }
    .stat-item {
        flex: 1;
        min-width: 200px;
        padding: 15px;
        margin: 5px;
        text-align: center;
        border-radius: 8px;
    }
    .sent {
        background-color: #d5f5e3;
        border: 1px solid #2ecc71;
    }
    .deferred {
        background-color: #fef9e7;
        border: 1px solid #f1c40f;
    }
    .bounced {
        background-color: #fadbd8;
        border: 1px solid #e74c3c;
    }
    .stat-value {
        font-size: 28px;
        font-weight: bold;
        margin: 10px 0;
    }
    .stat-label {
        font-size: 16px;
        color: #555;
    }
    table {
        width: 100%;
        border-collapse: collapse;
        margin: 30px 0;
        font-family: Arial, sans-serif;
        font-size: 14px;
    }
    th, td {
        padding: 12px 15px;
        text-align: left;
        border-bottom: 1px solid #eee;
    }
    th {
        background-color: #f8f9fa;
        font-weight: bold;
        color: #2c3e50;
        border-bottom: 2px solid #3498db;
    }
    tr:hover {
        background-color: #f8f9fa;
    }
    .section-header {
        text-align: center;
        padding: 15px 0 20px 0;
        border-bottom: 2px solid #3498db;
        margin: 30px 0 0 0;
    }
    .section-header h2 {
        margin: 0;
        color: #2c3e50;
        font-size: 18px;
        font-weight: bold;
        font-family: Arial, sans-serif;
    }
    .error-box {
        background-color: #fadbd8;
        border-left: 4px solid #e74c3c;
        padding: 15px;
        margin: 20px 0;
        border-radius: 4px;
        overflow-x: auto;
    }
    .error-item {
        font-family: monospace;
        white-space: pre-wrap;
        margin: 8px 0;
        padding: 5px;
        background-color: #f9f9f9;
        border-radius: 3px;
    }
    .footer {
        margin-top: 30px;
        padding-top: 20px;
        border-top: 1px solid #eee;
        font-size: 12px;
        color: #777;
        text-align: center;
    }
    .hourly-chart {
        margin: 20px 0;
        overflow-x: auto;
    }
    .hourly-bar {
        display: inline-block;
        width: 30px;
        margin: 0 2px;
        background-color: #3498db;
        vertical-align: bottom;
        position: relative;
    }
    .hourly-label {
        font-size: 10px;
        text-align: center;
        margin-top: 5px;
    }
</style>
"""

def log_lines_today(logfile, today):
    """Yield log lines for ISO-style logs matching today's date."""
    opener = gzip.open if logfile.endswith('.gz') else open
    try:
        with opener(logfile, "rt") as f:
            for line in f:
                if line.startswith(today):
                    yield line
    except FileNotFoundError:
        pass

def get_domain(email):
    """Extract domain from email address"""
    if not email or '@' not in email:
        return "unknown"
    return email.split('@')[-1]

def format_bytes(size):
    """Format bytes to human-readable format"""
    for unit in ['B', 'KB', 'MB', 'GB']:
        if size < 1024.0:
            return f"{size:.1f} {unit}"
        size /= 1024.0
    return f"{size:.1f} TB"

def load_historical_data():
    """Load historical data from JSON file"""
    try:
        with open(HISTORY_FILE, 'r') as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}

def save_historical_data(history, today_stats):
    """Save today's stats to historical data"""
    today_key = datetime.now().strftime("%Y-%m-%d")
    history[today_key] = today_stats
    
    # Keep only last 30 days
    cutoff_date = (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d")
    history = {k: v for k, v in history.items() if k >= cutoff_date}
    
    try:
        with open(HISTORY_FILE, 'w') as f:
            json.dump(history, f, indent=2)
    except PermissionError:
        pass  # Continue without saving if we can't write

def calculate_trends(history):
    """Calculate 7-day trends from historical data"""
    if len(history) < 2:
        return {}
    
    dates = sorted(history.keys())[-8:]  # Last 8 days (including today)
    if len(dates) < 2:
        return {}
    
    trends = {}
    for metric in ['sent_count', 'success_rate', 'avg_queue_time', 'total_size']:
        values = [history[date].get(metric, 0) for date in dates if metric in history[date]]
        if len(values) >= 2:
            recent_avg = sum(values[-3:]) / len(values[-3:])  # Last 3 days
            older_avg = sum(values[:-3]) / len(values[:-3]) if len(values) > 3 else values[0]
            
            if older_avg > 0:
                trend_pct = ((recent_avg - older_avg) / older_avg) * 100
                trends[metric] = {
                    'direction': '↑' if trend_pct > 5 else '↓' if trend_pct < -5 else '→',
                    'percentage': trend_pct,
                    'recent_avg': recent_avg,
                    'baseline_avg': older_avg
                }
    
    return trends

def analyze_errors_by_domain(errors):
    """Analyze errors grouped by destination domain"""
    domain_errors = defaultdict(list)
    
    for error in errors:
        # Extract destination domain from error
        to_match = re.search(r'to=<[^@]*@([^>]+)>', error)
        if to_match:
            domain = to_match.group(1)
            domain_errors[domain].append(error)
    
    # Summarize by domain
    domain_summary = {}
    for domain, error_list in domain_errors.items():
        domain_summary[domain] = {
            'count': len(error_list),
            'errors': error_list[:3]  # Keep first 3 examples
        }
    
    return domain_summary

def analyze_errors_by_host(errors, message_clients):
    """Analyze errors grouped by sending host"""
    host_errors = defaultdict(int)
    
    for error in errors:
        # Extract message ID from error
        msg_id_match = re.search(r'([A-Za-z0-9]+):', error)
        if msg_id_match:
            msg_id = msg_id_match.group(1)
            hostname = message_clients.get(msg_id, "unknown")
            host_errors[hostname] += 1
    
    return dict(host_errors)

def export_to_csv(data):
    """Export data to CSV format"""
    output = io.StringIO()
    writer = csv.writer(output)
    
    # Write basic stats
    writer.writerow(['Metric', 'Value'])
    writer.writerow(['Date', datetime.now().strftime('%Y-%m-%d')])
    writer.writerow(['Sent Messages', data.get('sent_count', 0)])
    writer.writerow(['Deferred Messages', data.get('deferred_count', 0)])
    writer.writerow(['Bounced Messages', data.get('bounced_count', 0)])
    writer.writerow(['Success Rate %', f"{data.get('success_rate', 0):.1f}"])
    writer.writerow(['Health Score', data.get('health_score', 0)])
    writer.writerow(['Total Size Bytes', data.get('total_size', 0)])
    writer.writerow([])
    
    # Write top senders
    if 'top_senders' in data:
        writer.writerow(['Top Senders'])
        writer.writerow(['Email', 'Count'])
        for email, count in data['top_senders']:
            writer.writerow([email, count])
    
    return output.getvalue()

def export_to_json(data):
    """Export data to JSON format"""
    export_data = {
        'timestamp': datetime.now().isoformat(),
        'hostname': HOSTNAME,
        'metrics': data
    }
    return json.dumps(export_data, indent=2)

def main():
    today_date = datetime.now().strftime("%Y-%m-%d")
    # Also check for very early runs—the previous day, in case of recent rotation
    yesterday_date = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
    
    # Calculate time range for reporting
    start_time = datetime.now() - timedelta(days=1)
    end_time = datetime.now()
    time_range = f"{start_time.strftime('%Y-%m-%d %H:%M')} to {end_time.strftime('%Y-%m-%d %H:%M')}"
    
    # Load historical data for trend analysis
    historical_data = load_historical_data()

    sent_count = 0
    deferred_count = 0
    bounced_count = 0
    total_size = 0
    senders = Counter()
    recipients = Counter()
    sender_domains = Counter()
    recipient_domains = Counter()
    sending_hosts = Counter()  # New counter for sending hostnames
    recipient_hosts = defaultdict(Counter)  # Track all hosts per recipient
    message_clients = {}  # Map message IDs to client hostnames
    message_sizes = {}   # Map message IDs to sizes
    errors = []
    delivery_times = []
    error_categories = Counter()
    hourly_traffic = Counter()  # Track messages by hour
    
    # Phase 1 additions
    sender_recipient_pairs = Counter()  # Track sender→recipient flow
    queue_times = []  # Track queue processing times
    auth_failures = Counter()  # Track authentication failures
    suspicious_senders = Counter()  # High-volume senders
    retry_patterns = defaultdict(int)  # Track delivery attempts
    mail_loops = []  # Detect potential mail loops
    rate_limit_violations = Counter()  # Track rate limiting
    
    # High-volume specific tracking
    if HIGH_VOLUME_MODE:
        relay_performance = defaultdict(list)  # Track performance per relay
        service_patterns = Counter()  # Track different service types
        size_distribution = defaultdict(int)  # Track message size distribution
        peak_hour_details = defaultdict(list)  # Detailed peak hour analysis
        connection_patterns = defaultdict(int)  # Track connection patterns
        throughput_samples = []  # Sample throughput every few minutes

    # First pass: collect client information for message IDs
    for logpath in LOG_PATHS:
        for date in [today_date, yesterday_date]:
            for line in log_lines_today(logpath, date):
                # Extract client hostname and message ID - Fixed regex for alphanumeric IDs
                client_match = re.search(r'([A-Za-z0-9]+): client=([^[]+)\[', line)
                if client_match:
                    message_id = client_match.group(1)
                    hostname = client_match.group(2)
                    message_clients[message_id] = hostname
                    sending_hosts[hostname] += 1
                
                # Handle local pickup messages (uid=1000) as localhost
                pickup_match = re.search(r'postfix/pickup\[[^\]]+\]:\s+([A-Za-z0-9]+):\s+uid=', line)
                if pickup_match:
                    message_id = pickup_match.group(1)
                    message_clients[message_id] = "localhost"
                    sending_hosts["localhost"] += 1
                
                # Extract message size from qmgr lines
                size_match = re.search(r'([A-Za-z0-9]+): from=<[^>]*>, size=(\d+)', line)
                if size_match:
                    message_id = size_match.group(1)
                    message_sizes[message_id] = int(size_match.group(2))
                
                # Track authentication failures
                if "authentication failed" in line.lower() or "sasl login failed" in line.lower():
                    user_match = re.search(r'user=([^,\\s]+)', line)
                    if user_match:
                        auth_failures[user_match.group(1)] += 1
                    else:
                        auth_failures["unknown"] += 1
                
                # Track rate limiting
                if "too many" in line.lower() and "reject" in line.lower():
                    client_match = re.search(r'client=([^[]+)', line)
                    if client_match:
                        rate_limit_violations[client_match.group(1)] += 1

    # Second pass: process delivery status and link to hostnames
    for logpath in LOG_PATHS:
        for date in [today_date, yesterday_date]:
            for line in log_lines_today(logpath, date):
                # Extract hour for traffic analysis
                time_match = re.match(r'(\d{4}-\d{2}-\d{2})T(\d{2}):', line)
                if time_match:
                    hour = int(time_match.group(2))
                    
                # Extract message ID from status lines - Fixed regex to avoid timestamp
                message_id_match = re.search(r'postfix/smtp\[[^\]]+\]:\s+([A-Za-z0-9]+):', line)
                message_id = message_id_match.group(1) if message_id_match else None
                hostname = message_clients.get(message_id, "unknown")
                
                # Message sent successfully
                if " status=sent " in line:
                    sent_count += 1
                    if time_match:
                        hourly_traffic[hour] += 1
                    sm = re.search(r"from=<([^>]*)>", line)
                    rm = re.search(r"to=<([^>]*)>", line)
                    size_match = re.search(r"size=(\d+)", line)
                    delay_match = re.search(r"delay=(\d+\.?\d*)", line)
                    
                    if sm: 
                        sender = sm.group(1)
                        senders[sender] += 1
                        sender_domains[get_domain(sender)] += 1
                        
                        # Track suspicious high-volume senders
                        suspicious_senders[sender] += 1
                    
                    if rm: 
                        recipient = rm.group(1)
                        recipients[recipient] += 1
                        recipient_domains[get_domain(recipient)] += 1
                        # Track hostname for this recipient
                        recipient_hosts[recipient][hostname] += 1
                        
                        # Track sender→recipient flow
                        if sm:
                            pair = f"{sender} → {recipient}"
                            sender_recipient_pairs[pair] += 1
                    
                    # Add size from tracked data
                    if message_id in message_sizes:
                        msg_size = message_sizes[message_id]
                        total_size += msg_size
                        
                        # High-volume mode: Track size distribution
                        if HIGH_VOLUME_MODE:
                            if msg_size < 1024:
                                size_distribution["<1KB"] += 1
                            elif msg_size < 10240:
                                size_distribution["1-10KB"] += 1
                            elif msg_size < 102400:
                                size_distribution["10-100KB"] += 1
                            elif msg_size < 1048576:
                                size_distribution["100KB-1MB"] += 1
                            else:
                                size_distribution[">1MB"] += 1
                    
                    # Track queue processing time and detect anomalies
                    if delay_match:
                        queue_time = float(delay_match.group(1))
                        queue_times.append(queue_time)
                        delivery_times.append(queue_time)
                        
                        # High-volume mode: Track relay performance
                        if HIGH_VOLUME_MODE:
                            relay_match = re.search(r'relay=([^[]+)', line)
                            if relay_match:
                                relay = relay_match.group(1)
                                relay_performance[relay].append(queue_time)
                        
                        # Detect potential mail loops (very fast processing + internal domains)
                        if queue_time < 0.1 and sm and rm:
                            if sender == recipient:
                                mail_loops.append(f"Self-loop: {sender}")
                            elif get_domain(sender) == get_domain(recipient) and get_domain(sender) == "eusd.org":
                                mail_loops.append(f"Internal loop: {sender} → {recipient}")
                
                # Deferred messages
                elif "status=deferred" in line:
                    deferred_count += 1
                    rm = re.search(r"to=<([^>]*)>", line)
                    sm = re.search(r"from=<([^>]*)>", line)
                    if rm: 
                        recipient = rm.group(1)
                        recipients[recipient] += 1
                        recipient_domains[get_domain(recipient)] += 1
                        # Track hostname for this recipient
                        recipient_hosts[recipient][hostname] += 1
                        
                        # Track retry patterns for deferred messages
                        if sm:
                            sender = sm.group(1)
                            retry_patterns[sender] += 1
                    
                    # Categorize errors
                    if "Connection timed out" in line:
                        error_categories["Connection Timeout"] += 1
                    elif "Connection refused" in line:
                        error_categories["Connection Refused"] += 1
                    elif "Temporary lookup failure" in line:
                        error_categories["DNS Issues"] += 1
                    elif "Temporary failure" in line:
                        error_categories["Temporary Failure"] += 1
                    elif "Greylisted" in line:
                        error_categories["Greylisted"] += 1
                    else:
                        error_categories["Other Deferred"] += 1
                    
                    errors.append(line.strip())
                
                # Bounced or rejected messages
                elif "status=bounced" in line or "status=reject" in line:
                    bounced_count += 1
                    rm = re.search(r"to=<([^>]*)>", line)
                    if rm: 
                        recipient = rm.group(1)
                        recipients[recipient] += 1
                        recipient_domains[get_domain(recipient)] += 1
                        # Track hostname for this recipient
                        recipient_hosts[recipient][hostname] += 1
                    
                    # Categorize bounces
                    if "user unknown" in line.lower() or "recipient address rejected" in line:
                        error_categories["Unknown Recipient"] += 1
                    elif "mailbox full" in line.lower() or "quota exceeded" in line.lower():
                        error_categories["Mailbox Full"] += 1
                    elif "rejected" in line.lower() and "spam" in line.lower():
                        error_categories["Rejected as Spam"] += 1
                    elif "blocked" in line.lower() or "blacklisted" in line.lower():
                        error_categories["Blocked/Blacklisted"] += 1
                    else:
                        error_categories["Other Bounced"] += 1
                    
                    errors.append(line.strip())

    # Calculate performance metrics
    avg_delivery_time = sum(delivery_times) / len(delivery_times) if delivery_times else 0
    avg_queue_time = sum(queue_times) / len(queue_times) if queue_times else 0
    max_queue_time = max(queue_times) if queue_times else 0
    total_messages = sent_count + deferred_count + bounced_count
    success_rate = (sent_count / total_messages * 100) if total_messages > 0 else 0
    
    # Phase 2: Advanced Analysis (do this before alerts)
    trends = calculate_trends(historical_data)
    error_by_domain = analyze_errors_by_domain(errors)
    error_by_host = analyze_errors_by_host(errors, message_clients)
    
    # High-volume specific analysis
    avg_message_size = total_size / total_messages if total_messages > 0 else 0
    defer_rate = (deferred_count / total_messages * 100) if total_messages > 0 else 0
    max_hourly = max(hourly_traffic.values()) if hourly_traffic else 0
    min_hourly = min(hourly_traffic.values()) if hourly_traffic else 0
    
    # Calculate throughput (messages per minute)
    throughput_per_minute = total_messages / (24 * 60) if total_messages > 0 else 0
    
    # Calculate health score (0-100)
    health_score = 100
    if success_rate < 95: health_score -= (95 - success_rate) * 2
    if avg_queue_time > 30: health_score -= min(avg_queue_time - 30, 20)
    if auth_failures: health_score -= min(len(auth_failures) * 5, 30)
    if mail_loops: health_score -= len(mail_loops) * 10
    health_score = max(0, health_score)
    
    # Identify alerts using configurable thresholds
    alerts = []
    if success_rate < ALERT_THRESHOLDS["min_success_rate"]:
        alerts.append(f"⚠️ Low success rate: {success_rate:.1f}%")
    if avg_queue_time > ALERT_THRESHOLDS["max_queue_time"]:
        alerts.append(f"⚠️ High queue time: {avg_queue_time:.1f}s")
    if sum(auth_failures.values()) > ALERT_THRESHOLDS["max_auth_failures"]:
        alerts.append(f"⚠️ {sum(auth_failures.values())} authentication failures")
    if mail_loops:
        alerts.append(f"⚠️ {len(mail_loops)} potential mail loops detected")
    
    # Add trend-based alerts
    if 'success_rate' in trends and trends['success_rate']['percentage'] < -10:
        alerts.append(f"📉 Success rate declining: {trends['success_rate']['percentage']:.1f}% trend")
    if 'avg_queue_time' in trends and trends['avg_queue_time']['percentage'] > 50:
        alerts.append(f"📈 Queue time increasing: {trends['avg_queue_time']['percentage']:.1f}% trend")
    
    # High-volume specific alerts
    if HIGH_VOLUME_MODE:
        if max_hourly > ALERT_THRESHOLDS["max_hourly_volume"]:
            alerts.append(f"📈 Peak hour volume: {max_hourly} messages/hour")
        if defer_rate > ALERT_THRESHOLDS["max_defer_rate"]:
            alerts.append(f"📤 High defer rate: {defer_rate:.1f}%")
        if avg_message_size > ALERT_THRESHOLDS["max_avg_size"]:
            alerts.append(f"📊 Large average message size: {format_bytes(avg_message_size)}")
        if throughput_per_minute > 100:  # Alert if over 100 msgs/minute
            alerts.append(f"🚀 High throughput: {throughput_per_minute:.1f} msgs/minute")
    
    # Find high-volume senders (potential compromised accounts)
    high_volume_threshold = max(50, total_messages * ALERT_THRESHOLDS["high_volume_threshold_pct"])
    compromised_candidates = [sender for sender, count in suspicious_senders.items() 
                             if count > high_volume_threshold and "@eusd.org" in sender]
    
    # Prepare today's stats for historical storage
    today_stats = {
        'sent_count': sent_count,
        'deferred_count': deferred_count,
        'bounced_count': bounced_count,
        'success_rate': success_rate,
        'avg_queue_time': avg_queue_time,
        'total_size': total_size,
        'health_score': health_score,
        'auth_failures_count': sum(auth_failures.values()),
        'mail_loops_count': len(mail_loops)
    }
    
    # Save historical data
    save_historical_data(historical_data, today_stats)
    
    # Prepare export data
    export_data = {
        **today_stats,
        'top_senders': list(senders.most_common(10)),
        'top_recipients': list(recipients.most_common(10)),
        'top_hosts': list(sending_hosts.most_common(10)),
        'error_categories': dict(error_categories),
        'hourly_traffic': dict(hourly_traffic)
    }

    # Create HTML content
    html_parts = []
    html_parts.append(f"""
    <!DOCTYPE html>
    <html>
    <head>
        {CSS}
    </head>
    <body>
        <h1>📧 Postfix Mail Summary</h1>
        <p style="text-align: center; font-size: 1.1em; color: #666; margin-bottom: 30px;">
            Mail server: <strong>{HOSTNAME}</strong><br>
            Time range: <strong>{time_range}</strong>
        </p>
        <!-- System Overview -->
        <div class="summary-box">
            <table style="width: 100%; border-collapse: collapse; font-family: Arial, sans-serif; font-size: 14px;">
                <tr>
                    <td colspan="4" style="text-align: center; padding: 15px 0 20px 0; border-bottom: 2px solid #3498db;">
                        <h2 style="margin: 0; color: #2c3e50; font-size: 18px; font-weight: bold;">
                            🎯 System Overview
                        </h2>
                    </td>
                </tr>
                <tr>
                    <td style="padding: 12px 15px; width: 25%; border-right: 1px solid #eee;">
                        <strong style="color: #555;">Health Score</strong><br>
                        <span style="color: {'green' if health_score >= 90 else 'orange' if health_score >= 70 else 'red'}; font-size: 20px; font-weight: bold;">
                            {health_score:.0f}/100
                        </span>
                    </td>
                    <td style="padding: 12px 15px; width: 25%; border-right: 1px solid #eee;">
                        <strong style="color: #555;">Success Rate</strong><br>
                        <span style="font-size: 16px; font-weight: bold;">
                            {success_rate:.1f}%
                        </span>
                        {f" {trends['success_rate']['direction']} {trends['success_rate']['percentage']:+.1f}%" if 'success_rate' in trends else ''}
                    </td>
                    <td style="padding: 12px 15px; width: 25%; border-right: 1px solid #eee;">
                        <strong style="color: #555;">Total Volume</strong><br>
                        <span style="font-size: 16px; font-weight: bold;">
                            {format_bytes(total_size)}
                        </span>
                        {f" {trends['total_size']['direction']} {trends['total_size']['percentage']:+.1f}%" if 'total_size' in trends else ''}
                    </td>
                    <td style="padding: 12px 15px; width: 25%;">
                        <strong style="color: #555;">Messages</strong><br>
                        <span style="font-size: 16px; font-weight: bold;">
                            {total_messages:,}
                        </span>
                    </td>
                </tr>
                <tr>
                    <td style="padding: 12px 15px; border-right: 1px solid #eee; border-top: 1px solid #eee;">
                        <strong style="color: #555;">Avg Delivery</strong><br>
                        <span style="font-size: 16px; font-weight: bold;">
                            {avg_delivery_time:.2f}s
                        </span>
                    </td>
                    <td style="padding: 12px 15px; border-right: 1px solid #eee; border-top: 1px solid #eee;">
                        <strong style="color: #555;">Avg Queue Time</strong><br>
                        <span style="font-size: 16px; font-weight: bold;">
                            {avg_queue_time:.2f}s
                        </span>
                        {f" {trends['avg_queue_time']['direction']} {trends['avg_queue_time']['percentage']:+.1f}%" if 'avg_queue_time' in trends else ''}
                    </td>
                    <td style="padding: 12px 15px; border-right: 1px solid #eee; border-top: 1px solid #eee;">
                        <strong style="color: #555;">Avg Message Size</strong><br>
                        <span style="font-size: 16px; font-weight: bold;">
                            {format_bytes(avg_message_size)}
                        </span>
                    </td>
                    <td style="padding: 12px 15px; border-top: 1px solid #eee;">
                        <strong style="color: #555;">Generated</strong><br>
                        <span style="font-size: 12px; color: #666;">
                            {datetime.now().strftime('%Y-%m-%d %H:%M')}
                        </span>
                    </td>
                </tr>
            </table>""")
    
    # High-volume performance metrics
    if HIGH_VOLUME_MODE and total_messages > 100:
        html_parts.append(f"""
            <table style="width: 100%; border-collapse: collapse; font-family: Arial, sans-serif; font-size: 14px; margin-top: 20px;">
                <tr>
                    <td colspan="3" style="text-align: center; padding: 15px 0 20px 0; border-bottom: 2px solid #e67e22;">
                        <h2 style="margin: 0; color: #2c3e50; font-size: 18px; font-weight: bold;">
                            📈 Performance Metrics
                        </h2>
                    </td>
                </tr>
                <tr>
                    <td style="padding: 12px 15px; width: 33%; border-right: 1px solid #eee;">
                        <strong style="color: #555;">Throughput</strong><br>
                        <span style="font-size: 16px; font-weight: bold;">
                            {throughput_per_minute:.1f} msgs/min
                        </span>
                    </td>
                    <td style="padding: 12px 15px; width: 33%; border-right: 1px solid #eee;">
                        <strong style="color: #555;">Peak Hour</strong><br>
                        <span style="font-size: 16px; font-weight: bold;">
                            {max_hourly} messages
                        </span>
                    </td>
                    <td style="padding: 12px 15px; width: 33%;">
                        <strong style="color: #555;">Defer Rate</strong><br>
                        <span style="font-size: 16px; font-weight: bold;">
                            {defer_rate:.1f}%
                        </span>
                    </td>
                </tr>
                <tr>
                    <td style="padding: 12px 15px; border-right: 1px solid #eee; border-top: 1px solid #eee;">
                        <strong style="color: #555;">Peak/Min Ratio</strong><br>
                        <span style="font-size: 16px; font-weight: bold;">
                            {(max_hourly/min_hourly):.1f}x
                        </span>
                    </td>
                    <td style="padding: 12px 15px; border-right: 1px solid #eee; border-top: 1px solid #eee;">
                        <strong style="color: #555;">Min Hour Volume</strong><br>
                        <span style="font-size: 16px; font-weight: bold;">
                            {min_hourly} messages
                        </span>
                    </td>
                    <td style="padding: 12px 15px; border-top: 1px solid #eee;">
                        <strong style="color: #555;">High Volume Mode</strong><br>
                        <span style="font-size: 12px; color: #27ae60; font-weight: bold;">
                            ✓ ENABLED
                        </span>
                    </td>
                </tr>
            </table>""")
    
    # Calculate percentages for status summary
    sent_pct = (sent_count/total_messages*100) if total_messages > 0 else 0
    deferred_pct = (deferred_count/total_messages*100) if total_messages > 0 else 0
    bounced_pct = (bounced_count/total_messages*100) if total_messages > 0 else 0
    
    html_parts.append(f"""
        </div>
        
        <!-- Message Status Summary -->
        <table style="width: 100%; border-collapse: collapse; font-family: Arial, sans-serif; font-size: 14px; margin-top: 30px;">
            <tr>
                <td colspan="3" style="text-align: center; padding: 15px 0 20px 0; border-bottom: 2px solid #27ae60;">
                    <h2 style="margin: 0; color: #2c3e50; font-size: 18px; font-weight: bold;">
                        📊 Message Status Summary
                    </h2>
                </td>
            </tr>
            <tr>
                <td style="padding: 15px; width: 33%; border-right: 1px solid #eee; text-align: center; background-color: #f8fff8;">
                    <strong style="color: #27ae60; font-size: 16px;">✓ SENT</strong><br>
                    <span style="font-size: 24px; font-weight: bold; color: #2c3e50;">
                        {sent_count:,}
                    </span><br>
                    <span style="font-size: 12px; color: #666;">
                        {sent_pct:.1f}% of total
                    </span>
                </td>
                <td style="padding: 15px; width: 33%; border-right: 1px solid #eee; text-align: center; background-color: #fffdf8;">
                    <strong style="color: #f39c12; font-size: 16px;">⏳ DEFERRED</strong><br>
                    <span style="font-size: 24px; font-weight: bold; color: #2c3e50;">
                        {deferred_count:,}
                    </span><br>
                    <span style="font-size: 12px; color: #666;">
                        {deferred_pct:.1f}% of total
                    </span>
                </td>
                <td style="padding: 15px; width: 33%; text-align: center; background-color: #fdf8f8;">
                    <strong style="color: #e74c3c; font-size: 16px;">✗ BOUNCED</strong><br>
                    <span style="font-size: 24px; font-weight: bold; color: #2c3e50;">
                        {bounced_count:,}
                    </span><br>
                    <span style="font-size: 12px; color: #666;">
                        {bounced_pct:.1f}% of total
                    </span>
                </td>
            </tr>
        </table>
    """)

    # Hourly traffic chart
    if hourly_traffic:
        html_parts.append("""
        <div class="section-header">
            <h2>📈 Hourly Email Traffic</h2>
        </div>
        <div class="hourly-chart">
        """)
        max_count = max(hourly_traffic.values()) if hourly_traffic else 1
        for hour in range(24):
            count = hourly_traffic.get(hour, 0)
            height = int((count / max_count) * 100) if max_count > 0 else 0
            html_parts.append(f"""
            <div style="display: inline-block; vertical-align: bottom; text-align: center;">
                <div class="hourly-bar" style="height: {height}px;" title="{count} messages"></div>
                <div class="hourly-label">{hour:02d}</div>
            </div>
            """)
        html_parts.append("</div>")

    # Alerts section
    if alerts:
        html_parts.append("""
        <div class="section-header">
            <h2 style="color: #e74c3c;">🚨 Alerts & Warnings</h2>
        </div>
        <div class="error-box">
        """)
        for alert in alerts:
            html_parts.append(f'<div style="margin: 10px 0; font-weight: bold;">{alert}</div>')
        html_parts.append("</div>")

    # Message Flow Analysis
    if sender_recipient_pairs:
        html_parts.append("""
        <h2>📊 Top Message Flows</h2>
        <table>
            <tr>
                <th>Sender → Recipient</th>
                <th>Messages</th>
            </tr>
        """)
        for pair, count in sender_recipient_pairs.most_common(10):
            html_parts.append(f"""
            <tr>
                <td>{pair}</td>
                <td>{count}</td>
            </tr>
            """)
        html_parts.append("</table>")

    # Security Analysis
    if auth_failures or rate_limit_violations or compromised_candidates:
        html_parts.append("""
        <h2>🔒 Security Analysis</h2>
        """)
        
        if auth_failures:
            html_parts.append("""
            <h3>Authentication Failures</h3>
            <table>
                <tr>
                    <th>User</th>
                    <th>Failed Attempts</th>
                </tr>
            """)
            for user, count in auth_failures.most_common(10):
                html_parts.append(f"""
                <tr>
                    <td>{user}</td>
                    <td>{count}</td>
                </tr>
                """)
            html_parts.append("</table>")
        
        if compromised_candidates:
            html_parts.append("""
            <h3 style="color: #e74c3c;">⚠️ Potential Compromised Accounts</h3>
            <div class="error-box">
            """)
            for sender in compromised_candidates:
                count = suspicious_senders[sender]
                html_parts.append(f'<div>{sender}: {count} messages (>{high_volume_threshold:.0f} threshold)</div>')
            html_parts.append("</div>")
        
        if rate_limit_violations:
            html_parts.append("""
            <h3>Rate Limit Violations</h3>
            <table>
                <tr>
                    <th>Client</th>
                    <th>Violations</th>
                </tr>
            """)
            for client, count in rate_limit_violations.most_common(5):
                html_parts.append(f"""
                <tr>
                    <td>{client}</td>
                    <td>{count}</td>
                </tr>
                """)
            html_parts.append("</table>")

    # Operational Intelligence
    if mail_loops or retry_patterns:
        html_parts.append("""
        <h2>⚙️ Operational Intelligence</h2>
        """)
        
        if mail_loops:
            html_parts.append("""
            <h3 style="color: #e74c3c;">🔄 Mail Loop Detection</h3>
            <div class="error-box">
            """)
            for loop in mail_loops[:10]:
                html_parts.append(f'<div>{loop}</div>')
            html_parts.append("</div>")
        
        if retry_patterns:
            html_parts.append("""
            <h3>📈 Retry Patterns (Deferred Messages)</h3>
            <table>
                <tr>
                    <th>Sender</th>
                    <th>Retry Count</th>
                </tr>
            """)
            for sender, count in retry_patterns.most_common(10):
                html_parts.append(f"""
                <tr>
                    <td>{sender}</td>
                    <td>{count}</td>
                </tr>
                """)
            html_parts.append("</table>")

    # Detailed Error Analysis
    if error_by_domain or error_by_host:
        html_parts.append("""
        <h2>🔍 Detailed Error Analysis</h2>
        """)
        
        if error_by_domain:
            html_parts.append("""
            <h3>Errors by Destination Domain</h3>
            <table>
                <tr>
                    <th>Domain</th>
                    <th>Error Count</th>
                    <th>Sample Error</th>
                </tr>
            """)
            for domain, info in sorted(error_by_domain.items(), key=lambda x: x[1]['count'], reverse=True)[:10]:
                sample_error = info['errors'][0][:100] + "..." if info['errors'] else "N/A"
                html_parts.append(f"""
                <tr>
                    <td>{domain}</td>
                    <td>{info['count']}</td>
                    <td style="font-family: monospace; font-size: 10px;">{sample_error}</td>
                </tr>
                """)
            html_parts.append("</table>")
        
        if error_by_host:
            html_parts.append("""
            <h3>Errors by Sending Host</h3>
            <table>
                <tr>
                    <th>Hostname</th>
                    <th>Error Count</th>
                </tr>
            """)
            for hostname, count in sorted(error_by_host.items(), key=lambda x: x[1], reverse=True)[:10]:
                html_parts.append(f"""
                <tr>
                    <td>{hostname}</td>
                    <td>{count}</td>
                </tr>
                """)
            html_parts.append("</table>")

    # Historical Trends
    if trends:
        html_parts.append("""
        <h2>📈 Historical Trends (7-day)</h2>
        <table>
            <tr>
                <th>Metric</th>
                <th>Recent Average</th>
                <th>Baseline Average</th>
                <th>Trend</th>
            </tr>
        """)
        for metric, trend_data in trends.items():
            metric_name = metric.replace('_', ' ').title()
            html_parts.append(f"""
            <tr>
                <td>{metric_name}</td>
                <td>{trend_data['recent_avg']:.1f}</td>
                <td>{trend_data['baseline_avg']:.1f}</td>
                <td>{trend_data['direction']} {trend_data['percentage']:+.1f}%</td>
            </tr>
            """)
        html_parts.append("</table>")

    # Top sending hosts (new section)
    if sending_hosts:
        html_parts.append("""
        <h2>🖥️ Top Sending Hosts</h2>
        <table>
            <tr>
                <th>Hostname</th>
                <th>Messages</th>
            </tr>
        """)
        for hostname, count in sending_hosts.most_common(10):
            html_parts.append(f"""
            <tr>
                <td>{hostname}</td>
                <td>{count}</td>
            </tr>
            """)
        html_parts.append("</table>")

    # Error categories
    if error_categories:
        html_parts.append("""
        <div class="section-header">
            <h2>⚠️ Error Categories</h2>
        </div>
        <table>
            <tr>
                <th>Category</th>
                <th>Count</th>
            </tr>
        """)
        for category, count in error_categories.most_common():
            html_parts.append(f"""
            <tr>
                <td>{category}</td>
                <td>{count}</td>
            </tr>
            """)
        html_parts.append("</table>")

    # Top sender domains
    if sender_domains:
        html_parts.append("""
        <div class="section-header">
            <h2>🌐 Top Sender Domains</h2>
        </div>
        <table>
            <tr>
                <th>Domain</th>
                <th>Messages</th>
            </tr>
        """)
        for domain, count in sender_domains.most_common(10):
            html_parts.append(f"""
            <tr>
                <td>{domain}</td>
                <td>{count}</td>
            </tr>
            """)
        html_parts.append("</table>")


    # Top senders
    if senders:
        html_parts.append("""
        <div class="section-header">
            <h2>👤 Top Senders</h2>
        </div>
        <table>
            <tr>
                <th>Email</th>
                <th>Messages</th>
            </tr>
        """)
        for email, count in senders.most_common(10):
            html_parts.append(f"""
            <tr>
                <td>{email}</td>
                <td>{count}</td>
            </tr>
            """)
        html_parts.append("</table>")
    
    # Top recipients with detailed hostname information
    if recipients:
        html_parts.append("""
        <div class="section-header">
            <h2>📫 Top Recipients</h2>
        </div>
        <table>
            <tr>
                <th>Email</th>
                <th>Messages</th>
                <th>Sending Hosts</th>
            </tr>
        """)
        for email, count in recipients.most_common(10):
            hosts = recipient_hosts[email].most_common(3)
            host_details = []
            for host, host_count in hosts:
                percentage = (host_count / count) * 100
                host_details.append(f"{host} ({percentage:.0f}%)")
            host_string = ", ".join(host_details) if host_details else "N/A"
            
            html_parts.append(f"""
            <tr>
                <td>{email}</td>
                <td>{count}</td>
                <td>{host_string}</td>
            </tr>
            """)
        html_parts.append("</table>")

    # Recent errors
    if errors:
        html_parts.append("""
        <div class="section-header">
            <h2>🚨 Recent Delivery Issues</h2>
        </div>
        <div class="error-box">
        """)
        for err in errors[-10:]:
            html_parts.append(f'<div class="error-item">{err}</div>')
        html_parts.append("</div>")

    # High-volume specific sections
    if HIGH_VOLUME_MODE and total_messages > 100:
        # Message Size Distribution
        if size_distribution:
            html_parts.append("""
            <h2>📊 Message Size Distribution</h2>
            <table>
                <tr>
                    <th>Size Range</th>
                    <th>Count</th>
                    <th>Percentage</th>
                </tr>
            """)
            for size_range, count in size_distribution.items():
                percentage = (count / total_messages) * 100
                html_parts.append(f"""
                <tr>
                    <td>{size_range}</td>
                    <td>{count}</td>
                    <td>{percentage:.1f}%</td>
                </tr>
                """)
            html_parts.append("</table>")
        
        # Relay Performance Analysis
        if relay_performance:
            html_parts.append("""
            <h2>🔄 Relay Performance Analysis</h2>
            <table>
                <tr>
                    <th>Relay</th>
                    <th>Messages</th>
                    <th>Avg Delay (s)</th>
                    <th>Max Delay (s)</th>
                    <th>Performance</th>
                </tr>
            """)
            for relay, times in relay_performance.items():
                avg_delay = sum(times) / len(times)
                max_delay = max(times)
                performance = "🟢 Good" if avg_delay < 5 else "🟡 Fair" if avg_delay < 15 else "🔴 Slow"
                html_parts.append(f"""
                <tr>
                    <td>{relay}</td>
                    <td>{len(times)}</td>
                    <td>{avg_delay:.2f}</td>
                    <td>{max_delay:.2f}</td>
                    <td>{performance}</td>
                </tr>
                """)
            html_parts.append("</table>")

    # Footer
    html_parts.append("""
        <div class="footer">
            <p>This is an automated report from your mail server. Do not reply to this email.</p>
        </div>
    </body>
    </html>
    """)

    html_content = "".join(html_parts)

    # Create plain text version as fallback
    text_summary = []
    text_summary.append(f"Postfix Mail Log Summary for {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    text_summary.append(f"Mail server: {HOSTNAME}")
    text_summary.append("-" * 40)
    text_summary.append(f"System Health Score: {health_score:.0f}/100")
    text_summary.append(f"Sent: {sent_count}")
    text_summary.append(f"Deferred: {deferred_count}")
    text_summary.append(f"Bounced/Rejected: {bounced_count}")
    text_summary.append(f"Success rate: {success_rate:.1f}%")
    text_summary.append(f"Average delivery time: {avg_delivery_time:.2f} seconds")
    text_summary.append(f"Average queue time: {avg_queue_time:.2f} seconds")
    text_summary.append(f"Total message volume: {format_bytes(total_size)}")
    
    if alerts:
        text_summary.append("")
        text_summary.append("🚨 ALERTS:")
        for alert in alerts:
            text_summary.append(f"  {alert}")
    text_summary.append("")

    # Add top sending hosts to plain text
    if sending_hosts:
        text_summary.append("Top 5 Sending Hosts:")
        for hostname, count in sending_hosts.most_common(5):
            text_summary.append(f"  {hostname}: {count}")
        text_summary.append("")

    if error_categories:
        text_summary.append("Error Categories:")
        for category, count in error_categories.most_common():
            text_summary.append(f"  {category}: {count}")
        text_summary.append("")

    if sender_domains:
        text_summary.append("Top 5 Sender Domains:")
        for domain, count in sender_domains.most_common(5):
            text_summary.append(f"  {domain}: {count}")
        text_summary.append("")

    if senders:
        text_summary.append("Top 5 Senders:")
        for email, count in senders.most_common(5):
            text_summary.append(f"  {email}: {count}")
        text_summary.append("")


    if recipients:
        text_summary.append("Top 5 Recipients (with sending host breakdown):")
        for email, count in recipients.most_common(5):
            text_summary.append(f"  {email}: {count}")
            hosts = recipient_hosts[email].most_common(3)
            for host, host_count in hosts:
                percentage = (host_count / count) * 100
                text_summary.append(f"    - {host}: {host_count} ({percentage:.0f}%)")
        text_summary.append("")

    # Add intelligence sections
    if sender_recipient_pairs:
        text_summary.append("Top 5 Message Flows:")
        for pair, count in sender_recipient_pairs.most_common(5):
            text_summary.append(f"  {pair}: {count}")
        text_summary.append("")
    
    if auth_failures:
        text_summary.append("Authentication Failures:")
        for user, count in auth_failures.most_common(5):
            text_summary.append(f"  {user}: {count}")
        text_summary.append("")
    
    if compromised_candidates:
        text_summary.append("⚠️ Potential Compromised Accounts:")
        for sender in compromised_candidates:
            count = suspicious_senders[sender]
            text_summary.append(f"  {sender}: {count} messages")
        text_summary.append("")
    
    if mail_loops:
        text_summary.append("🔄 Mail Loops Detected:")
        for loop in mail_loops[:5]:
            text_summary.append(f"  {loop}")
        text_summary.append("")
    
    # Phase 2 additions to plain text
    if trends:
        text_summary.append("📈 7-Day Trends:")
        for metric, trend_data in trends.items():
            metric_name = metric.replace('_', ' ').title()
            text_summary.append(f"  {metric_name}: {trend_data['direction']} {trend_data['percentage']:+.1f}%")
        text_summary.append("")
    
    if error_by_domain:
        text_summary.append("🔍 Top Error Domains:")
        for domain, info in sorted(error_by_domain.items(), key=lambda x: x[1]['count'], reverse=True)[:5]:
            text_summary.append(f"  {domain}: {info['count']} errors")
        text_summary.append("")
    
    if error_by_host and len(error_by_host) > 1:  # Only show if multiple hosts have errors
        text_summary.append("🖥️ Errors by Host:")
        for hostname, count in sorted(error_by_host.items(), key=lambda x: x[1], reverse=True)[:5]:
            text_summary.append(f"  {hostname}: {count} errors")
        text_summary.append("")

    if errors:
        text_summary.append("Recent Delivery Issues (last 10):")
        for err in errors[-10:]:
            text_summary.append("  " + err)

    text_content = '\n'.join(text_summary)

    # Create email
    msg = MIMEMultipart('alternative')
    msg['Subject'] = f"Mail Summary ({time_range}) - {HOSTNAME}"
    msg['From'] = SENDER
    msg['To'] = RECIPIENT
    
    # Attach plain text and HTML versions
    part1 = MIMEText(text_content, 'plain')
    part2 = MIMEText(html_content, 'html')
    msg.attach(part1)
    msg.attach(part2)

    try:
        with smtplib.SMTP(SMTP_SERVER, SMTP_PORT) as server:
            server.send_message(msg)
        print("Daily summary sent!")
    except Exception as e:
        print("Failed to send email:", e)
        print(text_content)
    
    # Optional: Save exports to files if enabled
    if ENABLE_EXPORTS and "--export" in os.sys.argv:
        try:
            csv_data = export_to_csv(export_data)
            with open(f"/tmp/postfix_report_{today_date}.csv", 'w') as f:
                f.write(csv_data)
            
            json_data = export_to_json(export_data)
            with open(f"/tmp/postfix_report_{today_date}.json", 'w') as f:
                f.write(json_data)
            
            print(f"Exports saved: /tmp/postfix_report_{today_date}.csv and .json")
        except Exception as e:
            print(f"Export failed: {e}")

if __name__ == "__main__":
    import sys
    main()