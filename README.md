# Linear Product Feedback Triage Automation

Automatically assigns Product Feedback issues in Linear to the appropriate Product Manager based on AI-powered topic classification.

## How It Works

1. Fetches all unassigned issues in **Triage** status from the Product Feedback & Requests team
2. Uses Claude AI to classify each issue into a product bucket (Storage, AI, Components, etc.)
3. Assigns the issue to the bucket owner based on the CSV mapping
4. Adds an audit comment explaining the classification
5. Adds `needs-review` label if AI confidence is low

## Files

| File | Description |
|------|-------------|
| `triage_automation.py` | Main Python script |
| `.github/workflows/triage-automation.yml` | GitHub Actions workflow (cloud scheduling) |
| `run_triage.sh` | Shell wrapper for local scheduled runs |
| `.env` | API keys (not committed) |
| `.env.example` | Template for API keys |
| `com.keboola.triage-automation.plist` | macOS launchd schedule config |
| `Product Feedback Buckets & Features/` | CSV files with bucket-to-owner mapping |

## Setup

### 1. Install Dependencies

```bash
pip3 install anthropic requests
```

### 2. Configure API Keys

```bash
cp .env.example .env
# Edit .env and add your API keys
```

### 3. Test (Dry Run)

```bash
python3 triage_automation.py
```

### 4. Test (Single Issue)

```bash
python3 triage_automation.py --issue PROF-23
```

### 5. Execute

```bash
python3 triage_automation.py --execute
```

## Scheduled Automation

### Option 1: GitHub Actions (Recommended - Cloud-based)

The automation runs **every weekday at 7:00 AM CET** via GitHub Actions.

#### Setup

1. **Push this repository to GitHub**

2. **Add secrets** in GitHub repository settings (Settings → Secrets → Actions):
   - `LINEAR_API_KEY` - Your Linear API key
   - `ANTHROPIC_API_KEY` - Your Anthropic API key

3. **Enable the workflow** - Go to Actions tab and enable workflows

#### Manual Trigger

You can also run manually from GitHub:
1. Go to **Actions** → **Product Feedback Triage Automation**
2. Click **Run workflow**
3. Optionally set:
   - `dry_run: true` for preview only
   - `issue: PROF-23` to process a specific issue

#### View Results

- Go to **Actions** tab to see run history
- Click on a run to see detailed logs
- Each run creates a summary with results

---

### Option 2: macOS launchd (Local)

For local scheduling (requires Mac to be on at 7 AM).

#### Install the Schedule

```bash
# Copy plist to LaunchAgents
cp com.keboola.triage-automation.plist ~/Library/LaunchAgents/

# Load the schedule
launchctl load ~/Library/LaunchAgents/com.keboola.triage-automation.plist
```

### Manage the Schedule

```bash
# Check if loaded
launchctl list | grep keboola

# Unload (stop scheduling)
launchctl unload ~/Library/LaunchAgents/com.keboola.triage-automation.plist

# Reload after changes
launchctl unload ~/Library/LaunchAgents/com.keboola.triage-automation.plist
launchctl load ~/Library/LaunchAgents/com.keboola.triage-automation.plist

# Run immediately (for testing)
launchctl start com.keboola.triage-automation
```

### View Logs

```bash
# Main execution log
tail -f triage.log

# launchd logs
tail -f triage-launchd.log
tail -f triage-launchd-error.log
```

## Bucket Mapping

The bucket-to-owner mapping is defined in:
- `Product Feedback Buckets & Features/Feedback Buckets-Table 1.csv`

To update owners, edit the CSV file. No code changes required.

## Special Rules

- **Native Datatypes** issues are assigned to Zuzana Bednarova (override from Storage bucket)
- Issues with **low confidence** classification get the `needs-review` label
- Already assigned issues are **skipped**
- Issues stay in **Triage** status for PM review
