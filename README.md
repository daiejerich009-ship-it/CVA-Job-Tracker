# CVA Job Tracker

A Windows-compatible job-search automation project designed to collect, filter, organize, and track relevant remote job opportunities in a Google Sheets workspace.

The project is designed around entry-level and general virtual-assistant-oriented opportunities, including non-voice, administrative, chat, email, data-entry, customer-support, lead-follow-up, and healthcare virtual-assistant roles.

## What It Does

- Searches multiple legitimate remote-job sources
- Filters listings based on configured target roles and eligibility criteria
- Prioritizes Philippines/Filipino-eligible opportunities
- Filters out clearly unsuitable voice/call and senior-role listings
- Removes duplicate job listings using stable identifiers
- Stores job listings in Google Sheets
- Preserves manual application-tracking information during updates
- Provides direct clickable application URLs
- Supports manual application tracking
- Includes dashboard-style job and application monitoring
- Runs continuously or as a one-time search
- Supports Windows Task Scheduler for automatic background execution
- Does not automatically submit job applications

## Job Sources

The tracker is configured to work with:

- Remotive
- Remote OK
- Arbeitnow
- Himalayas
- Jobicy

Job availability and source data may change over time.

## Target Job Categories

The configured search focuses on opportunities such as:

- General Virtual Assistant
- Administrative Virtual Assistant
- Chat Support
- Email Support
- Data Entry
- Customer Support
- Lead Follow-Up
- Healthcare Virtual Assistant
- Other relevant non-voice remote roles

The tracker also excludes clearly unsuitable listings based on the configured filtering rules.

## Google Sheets Workspace

The project uses Google Sheets as the tracking interface.

The workspace includes:

### Dashboard

Provides an overview of job and application activity.

### Jobs

Contains collected job listings, including:

- Job title
- Company
- Location/eligibility information
- Source
- Application URL
- Job status
- Stable job identifier

### Applications

Provides manual application tracking so the user can record progress such as:

- Applied
- Interview
- Follow-up
- Rejected
- Other manually tracked statuses

### Settings

Contains the configurable search interval, target roles, exclusions, sources, and automation settings.

## Automation

The tracker supports two main modes.

### One-time search

```bash
python job_tracker.py --once
Continuous mode
python job_tracker.py

The configured default search interval is 360 minutes (6 hours).

For Windows background execution, the project can be configured with Windows Task Scheduler and Python's pythonw.exe.

This allows the tracker to start automatically when Windows logs in without requiring a PowerShell window to remain open.

Testing

The project includes a test file:

test_job_tracker.py

Testing can be performed with:

pytest

An offline testing mode is also available:

python job_tracker.py --offline-test
Security

Private credentials and local runtime files are intentionally excluded from the public repository.

The project should never publish:

credentials.json
token.json
.env
sheet_id.txt
job_tracker.log

A .gitignore file is included to help prevent accidental publication.

Important Limitation

This project does not automatically apply to jobs.

It only collects, filters, organizes, and tracks job opportunities. The user remains responsible for reviewing each listing and submitting applications manually.

Job listings can change or expire because the project depends on external job sources.

Project Structure
CVA-Job-Tracker/
├── job_tracker.py
├── test_job_tracker.py
├── config.py
├── auth.py
├── setup_login.py
├── requirements.txt
├── README.md
└── .gitignore
Skills Demonstrated
Python automation
Job-search workflow automation
Data filtering
Duplicate detection
Google Sheets integration
OAuth authentication
Windows Task Scheduler
Data organization
Application tracking
Basic testing
Configuration management
Security-conscious credential handling
Technical documentation
Portfolio Purpose

CVA Job Tracker demonstrates how a repetitive job-search workflow can be organized into a practical automation system combining data collection, filtering, spreadsheet organization, application tracking, and scheduled execution.

The system keeps the final application decision under the user's control and does not automatically submit applications.
