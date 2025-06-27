# CLAUDE.md - Email Relay Notifications Project

## Project Overview
A comprehensive email monitoring and notification system for Postfix mail relays with professional reporting and alerting capabilities.

## Current Configuration
- **Primary Script**: `/usr/local/bin/postfix_daily_summary.py`
- **Queue Monitor**: `/usr/local/bin/postfix_queue_alert.py`
- **Cron Schedule**: Daily reports at 4:00 PM, queue alerts every 15 minutes
- **Report Recipient**: jstephens@eusd.org
- **Sender Address**: mailrelay@eusd.org

## Key Features
- Professional HTML email reports with consistent table-based layout
- Real-time hostname tracking for message sources
- High-volume monitoring (thousands of emails/day)
- Historical trend analysis (7-day comparisons)
- Security analysis (auth failures, compromised accounts, rate limiting)
- Performance metrics (throughput, queue times, defer rates)
- Comprehensive error categorization by domain and host
- Message flow analysis and operational intelligence

## System Health Scoring
- 100-point health score based on:
  - Success rate (95%+ target)
  - Queue processing time (<30s target)
  - Authentication failures
  - Mail loop detection

## Alert Thresholds
- Minimum success rate: 95%
- Maximum queue time: 30 seconds
- Maximum auth failures: 50
- High volume threshold: 5% of total traffic
- Maximum hourly volume: 500 messages
- Maximum defer rate: 5%

## File Locations
- Main scripts: `/usr/local/bin/postfix_*.py`
- Historical data: `/var/log/postfix_daily_history.json`
- Mail logs: `/var/log/mail.log*`

## Postfix Server Configuration
- **Server**: se-ubuntu.eusd.int (Ubuntu 24.10)
- **Version**: Postfix 3.9.0
- **Mail Origin**: eusd.org (from /etc/mailname)
- **Relay**: Gmail SMTP relay (smtp-relay.gmail.com:587)
- **Authentication**: SASL enabled with TLS encryption
- **Local Networks**: 127.0.0.0/8, 10.15.0.0/16, 192.168.1.0/24
- **Internet Protocols**: IPv4 only
- **Compatibility Level**: 3.6

## Recent Enhancements
- Fixed hostname tracking for accurate sender identification
- Standardized email template with professional table layouts
- Added high-volume monitoring capabilities
- Implemented comprehensive security and performance analysis
- Fixed variable interpolation in HTML templates
- Integrated consistent typography and color scheme

## Technical Notes
- Uses two-pass log processing for accurate message correlation
- Handles both regular SMTP and local pickup messages
- Email-client compatible table-based layouts (not CSS grid)
- Configurable alert thresholds for different environments
- JSON-based historical data storage with 30-day retention