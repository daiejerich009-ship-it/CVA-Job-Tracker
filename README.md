# CVA Job Tracker

A Windows-friendly job-search automation project that collects remote job listings, filters them for Philippines/Filipino eligibility and entry-level non-voice/VA work, and syncs the results to Google Sheets for easy browsing and application tracking.

## What it does

- Collects listings from legitimate public job sources:
  - Remotive
  - Remote OK
  - Arbeitnow
  - Himalayas
  - Jobicy
- Filters listings for:
  - Philippines/Filipino eligibility
  - VA, administrative, chat, email, data-entry, customer-support, lead-follow-up, healthcare VA and related roles
  - Entry-level / beginner-friendly signals
- Excludes clear voice/call-center listings and listings requiring multiple years of experience.
- Creates stable job IDs and removes duplicates.
- Keeps direct, clickable application URLs.
- Syncs results to one reusable Google Sheet.
- Preserves manual application-tracking fields during updates.
- Provides four Google Sheets tabs:
  - Dashboard
  - Jobs
  - Applications
  - Settings
- Supports one-time runs with `--once` and continuous background mode.
- Never submits applications automatically.

## Google Sheets dashboard

The workbook is designed for quick public viewing and practical job tracking.

**Dashboard**
- Total jobs found
- Jobs found today
- Not applied
- Applications submitted
- Follow-ups needed
- Interviews scheduled
- Offers received
- Rejections
- Follow-ups due
- Last local sync time
- Quick "How to Use" instructions

**Jobs**
- Search results with filters
- Match reasoning and matched keywords
- Direct application links
- Application status and follow-up fields

**Applications**
- Application-focused view for tracking progress and responses

**Settings**
- Search interval
- Target applicant group
- Target roles
- Exclusions
- Source list
- Automation notes

## Automation behavior

The default search interval is **360 minutes (6 hours)**. This conservative interval is used to avoid unnecessary polling of public job sources.

On Windows, the tracker can be started automatically with Task Scheduler and run in the background using `pythonw.exe`, so no PowerShell window needs to stay open.

Useful commands:

```text
python job_tracker.py --once
python job_tracker.py
python job_tracker.py --offline-test
python job_tracker.py --open-sheet
```

## Setup overview

1. Install Python 3.10+.
2. Install dependencies:

```text
pip install -r requirements.txt
```

3. Create a Google Cloud project and enable the Google Sheets API.
4. Create a Desktop OAuth client and place the downloaded file beside `job_tracker.py` as:

```text
credentials.json
```

5. Run the tracker once and complete Google OAuth.
6. The tracker creates/reuses the configured Google Sheet and saves its spreadsheet ID locally in `sheet_id.txt`.
7. For Windows automation, create a Task Scheduler task that starts:

```text
pythonw.exe "C:\Path\To\CVA Job Tracker\job_tracker.py"
```

## Security and public-demo rules

Do **not** publish any of these private files:

```text
credentials.json
token.json
.env
sheet_id.txt
job_tracker.log
```

A public portfolio/demo should contain only sanitized sample data and documentation. The live tracker and private Google credentials should remain private.

The public Google Sheet demo should be shared as **Viewer** so visitors can inspect the project without changing the workbook.

## Testing

The project includes automated tests for core filtering and URL behavior, including:

- Philippines/entry-level non-voice matching
- Call-center/voice exclusion
- Multi-year experience exclusion
- Foreign-only location exclusion
- Duplicate-job removal
- HTTP/HTTPS URL validation

The current final tracker passes the included 7-test suite.

## Important limitation

Job availability, eligibility wording, and application pages are controlled by the original job sources and can change after a listing is collected. The tracker therefore helps discover and organize opportunities; users should always verify the original posting before applying.

## Project structure

```text
CVA Job Tracker/
├── job_tracker.py
├── auth.py
├── setup_login.py
├── config.py
├── requirements.txt
├── .env.example
├── tests/
│   └── test_job_tracker.py
├── credentials.json        # private; do not publish
├── token.json              # private; do not publish
├── sheet_id.txt            # private; do not publish
└── job_tracker.log         # private/local diagnostic file
```

## Portfolio note

This project demonstrates practical skills in:

- Python automation
- API/HTTP data collection
- text-based job filtering
- data normalization and deduplication
- Google Sheets API integration
- spreadsheet workflow design
- Windows Task Scheduler automation
- basic security hygiene
- testing and troubleshooting

It is intended as a working automation project and portfolio demonstration, not as an automatic application-submission system.
