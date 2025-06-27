# Email Relay Notifications

A comprehensive monitoring system for Postfix email relays with professional reporting and alerting capabilities.

## Features

### 📧 Daily Summary Reports
- Professional HTML email reports with consistent styling
- System overview with health scoring (0-100 scale)
- Message status breakdown (sent/deferred/bounced) with percentages
- Hourly traffic visualization
- Top senders, recipients, and sending hosts
- Performance metrics for high-volume environments

### ⚡ Real-Time Queue Monitoring
- Queue size alerts every 15 minutes
- Configurable threshold-based notifications
- Automatic silence when issues resolve

### 🔍 Advanced Analytics
- **Security Analysis**: Authentication failures, rate limiting, compromised account detection
- **Performance Tracking**: Throughput, queue times, defer rates, message size distribution
- **Error Intelligence**: Categorized by type, destination domain, and sending host
- **Historical Trends**: 7-day comparisons with trend indicators
- **Operational Insights**: Mail loop detection, retry patterns, relay performance

### 📊 Hostname Tracking
- Accurate identification of sending hosts for each message
- Breakdown of message sources per recipient
- Support for both external SMTP and local system messages

## System Environment

### Current Host Configuration
- **Hostname**: se-ubuntu.eusd.int
- **Operating System**: Ubuntu 24.10 (Oracular)
- **Postfix Version**: 3.9.0
- **Python Version**: 3.12.7
- **Mail Domain**: eusd.org

### Postfix Configuration
- **Relay Host**: smtp-relay.gmail.com:587 (with TLS encryption)
- **Local Networks**: 127.0.0.0/8, 10.15.0.0/16, 192.168.1.0/24
- **SASL Authentication**: Enabled for Gmail relay
- **TLS Security**: Enforced for outbound SMTP connections
- **Service Status**: Active and running

## Installation

### Prerequisites
- Postfix mail server with logging enabled
- Python 3.6+ with standard library
- Cron daemon for scheduled execution
- SMTP access for sending reports

### Setup
1. Copy monitoring scripts to `/usr/local/bin/`:
   ```bash
   sudo cp postfix_daily_summary.py /usr/local/bin/
   sudo cp postfix_queue_alert.py /usr/local/bin/
   sudo chmod +x /usr/local/bin/postfix_*.py
   ```

2. Configure email settings in scripts:
   ```python
   RECIPIENT = "your-email@domain.com"
   SENDER = "mailrelay@domain.com"
   SMTP_SERVER = "localhost"
   ```

3. Add cron jobs:
   ```bash
   # Daily summary at 4 PM
   0 16 * * * /usr/local/bin/postfix_daily_summary.py
   
   # Queue monitoring every 15 minutes
   */15 * * * * /usr/local/bin/postfix_queue_alert.py >/dev/null 2>&1
   ```

## Configuration

### Alert Thresholds
Customize monitoring sensitivity in `postfix_daily_summary.py`:
```python
ALERT_THRESHOLDS = {
    "min_success_rate": 95,      # Minimum acceptable success rate (%)
    "max_queue_time": 30,        # Maximum queue processing time (seconds)
    "max_auth_failures": 50,     # Authentication failure limit
    "high_volume_threshold_pct": 0.05,  # High-volume sender threshold (5%)
    "max_hourly_volume": 500,    # Peak hour message limit
    "max_defer_rate": 5,         # Maximum defer rate (%)
}
```

### High-Volume Mode
Enable enhanced monitoring for high-traffic environments:
```python
HIGH_VOLUME_MODE = True  # Enables additional performance metrics
```

## System Requirements

### Log Format
Requires standard Postfix logging format with ISO timestamps:
```
2025-06-22T04:00:01.686038-07:00 hostname postfix/smtp[pid]: message_id: to=<recipient>, relay=host, status=sent
```

### Permissions
- Read access to `/var/log/mail.log*`
- Write access to `/var/log/` for historical data storage
- SMTP send permissions through configured relay

### Performance
- Handles thousands of messages per day efficiently
- Two-pass log processing minimizes memory usage
- Historical data limited to 30 days for performance

## Troubleshooting

### Common Issues
1. **"Unknown" hostnames**: Check log format and message ID regex patterns
2. **Missing reports**: Verify cron configuration and script permissions
3. **Email delivery failures**: Confirm SMTP settings and relay configuration

### Debugging
Enable verbose output by running scripts manually:
```bash
python3 /usr/local/bin/postfix_daily_summary.py
```

### Log Analysis
Historical trends require at least 2 days of data. Initial runs will show limited analytics until trend data accumulates.

## Output Examples

### Health Score Calculation
- **100**: Perfect operation (95%+ success, <30s queue times, no security issues)
- **90-99**: Excellent (minor performance variations)
- **70-89**: Good (some issues but stable)
- **<70**: Needs attention (multiple problems detected)

### Report Sections
1. **System Overview**: Health score, success rate, volume, timing
2. **Performance Metrics**: Throughput, peak hours, defer rates (high-volume mode)
3. **Message Status**: Visual breakdown of sent/deferred/bounced
4. **Hourly Traffic**: Bar chart visualization
5. **Security Analysis**: Auth failures, rate limiting, suspicious accounts
6. **Detailed Analytics**: Error categorization, host analysis, trends

## License

This project is designed for internal system monitoring and is provided as-is for educational and operational use.