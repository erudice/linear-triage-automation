#!/usr/bin/env python3
"""
Linear Product Feedback Triage Automation

This script automatically assigns Product Feedback issues in Linear
to the appropriate Product Manager based on topic classification using AI.

Usage:
    python triage_automation.py                  # Dry run (preview only)
    python triage_automation.py --execute        # Actually assign issues
    python triage_automation.py --issue PROF-23  # Process specific issue
"""

import os
import csv
import json
import argparse
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import anthropic
import requests

# =============================================================================
# CONFIGURATION
# =============================================================================

LINEAR_API_URL = "https://api.linear.app/graphql"
LINEAR_TEAM_KEY = "PROF"  # Product Feedback & Requests team key

# Paths to CSV files with topic-to-owner mapping
SCRIPT_DIR = Path(__file__).parent
BUCKETS_CSV = SCRIPT_DIR / "Product Feedback Buckets & Features" / "Feedback Buckets-Table 1.csv"
FEATURES_CSV = SCRIPT_DIR / "Product Feedback Buckets & Features" / "Specific Features-Table 1.csv"

# =============================================================================
# TOPIC-TO-OWNER MAPPING
# =============================================================================

def load_bucket_mapping() -> dict[str, str]:
    """Load the bucket-to-owner mapping from CSV files."""
    mapping = {}

    # Load main buckets
    with open(BUCKETS_CSV, encoding="utf-8") as f:
        reader = csv.DictReader(f, delimiter=";")
        for row in reader:
            name = row.get("Name", "").strip()
            owner = row.get("Owner", "").strip()
            if name and owner:
                mapping[name.lower()] = owner

    return mapping


def get_bucket_descriptions() -> str:
    """Get formatted bucket descriptions for the AI prompt."""
    buckets = []

    with open(BUCKETS_CSV, encoding="utf-8") as f:
        reader = csv.DictReader(f, delimiter=";")
        for row in reader:
            name = row.get("Name", "").strip()
            note = row.get("Note", "").strip()
            if name:
                if note:
                    buckets.append(f"- {name}: {note}")
                else:
                    buckets.append(f"- {name}")

    return "\n".join(buckets)


# Owner name normalization (CSV names -> Linear display names)
OWNER_NAME_MAP = {
    "Vladimir Krska": "Vladimír Kriška",
    "Zuzana Bednarova": "Zuzana Bednářová",
    "Jiri Zavora": "Jiří Závora",
}

# Special feature overrides - these features belong to a different owner than their parent bucket
FEATURE_OWNER_OVERRIDES = {
    "native datatypes": "Zuzana Bednarova",  # Exception: belongs to Zuzana, not Storage owner
}

# Label to add when AI confidence is low (different possible owners)
NEEDS_REVIEW_LABEL = "needs-review"


def normalize_owner_name(name: str) -> str:
    """Normalize owner name from CSV to Linear display name."""
    return OWNER_NAME_MAP.get(name, name)


# =============================================================================
# LINEAR API
# =============================================================================

class LinearClient:
    """Simple Linear GraphQL API client."""

    def __init__(self, api_key: str):
        self.api_key = api_key
        self.headers = {
            "Authorization": api_key,
            "Content-Type": "application/json",
        }

    def _query(self, query: str, variables: dict = None) -> dict:
        """Execute a GraphQL query."""
        response = requests.post(
            LINEAR_API_URL,
            headers=self.headers,
            json={"query": query, "variables": variables or {}},
        )
        response.raise_for_status()
        result = response.json()
        if "errors" in result:
            raise Exception(f"GraphQL errors: {result['errors']}")
        return result["data"]

    def get_triage_issues(self, team_key: str = LINEAR_TEAM_KEY) -> list[dict]:
        """Get all issues in Triage status for the team."""
        query = """
        query GetTriageIssues($teamKey: String!) {
            team(id: $teamKey) {
                id
                issues(filter: { state: { type: { eq: "triage" } } }) {
                    nodes {
                        id
                        identifier
                        title
                        description
                        url
                        assignee {
                            id
                            name
                        }
                        labels {
                            nodes {
                                name
                            }
                        }
                    }
                }
            }
        }
        """
        # First get team ID from key
        team_query = """
        query GetTeam {
            teams(filter: { key: { eq: "PROF" } }) {
                nodes {
                    id
                    name
                }
            }
        }
        """
        team_data = self._query(team_query)
        team_id = team_data["teams"]["nodes"][0]["id"]

        # Now get issues
        issues_query = """
        query GetTriageIssues($teamId: String!) {
            team(id: $teamId) {
                issues(filter: { state: { type: { eq: "triage" } } }) {
                    nodes {
                        id
                        identifier
                        title
                        description
                        url
                        assignee {
                            id
                            name
                        }
                        labels {
                            nodes {
                                name
                            }
                        }
                    }
                }
            }
        }
        """
        data = self._query(issues_query, {"teamId": team_id})
        return data["team"]["issues"]["nodes"]

    def get_issue_by_identifier(self, identifier: str) -> dict:
        """Get a specific issue by its identifier (e.g., PROF-23)."""
        query = """
        query GetIssue($identifier: String!) {
            issue(id: $identifier) {
                id
                identifier
                title
                description
                url
                assignee {
                    id
                    name
                }
                labels {
                    nodes {
                        name
                    }
                }
                state {
                    name
                    type
                }
            }
        }
        """
        # Linear API uses issue filter for identifier lookup
        search_query = """
        query SearchIssue($filter: IssueFilter!) {
            issues(filter: $filter, first: 1) {
                nodes {
                    id
                    identifier
                    title
                    description
                    url
                    assignee {
                        id
                        name
                    }
                    labels {
                        nodes {
                            name
                        }
                    }
                    state {
                        name
                        type
                    }
                }
            }
        }
        """
        # Parse identifier (e.g., "PROF-23" -> team "PROF", number 23)
        parts = identifier.split("-")
        team_key = parts[0]
        number = int(parts[1])

        data = self._query(search_query, {
            "filter": {
                "team": {"key": {"eq": team_key}},
                "number": {"eq": number}
            }
        })
        issues = data["issues"]["nodes"]
        if not issues:
            raise ValueError(f"Issue {identifier} not found")
        return issues[0]

    def get_team_members(self) -> list[dict]:
        """Get all members of the Product Feedback team."""
        query = """
        query GetTeamMembers {
            teams(filter: { key: { eq: "PROF" } }) {
                nodes {
                    members {
                        nodes {
                            id
                            name
                            email
                        }
                    }
                }
            }
        }
        """
        data = self._query(query)
        return data["teams"]["nodes"][0]["members"]["nodes"]

    def assign_issue(self, issue_id: str, assignee_id: str, label_ids: list[str] = None) -> dict:
        """Assign an issue to a user, optionally adding labels."""
        input_data = {"assigneeId": assignee_id}
        if label_ids:
            input_data["labelIds"] = label_ids

        mutation = """
        mutation AssignIssue($issueId: String!, $input: IssueUpdateInput!) {
            issueUpdate(id: $issueId, input: $input) {
                success
                issue {
                    id
                    identifier
                    assignee {
                        name
                    }
                    labels {
                        nodes {
                            name
                        }
                    }
                }
            }
        }
        """
        data = self._query(mutation, {"issueId": issue_id, "input": input_data})
        return data["issueUpdate"]

    def add_comment(self, issue_id: str, body: str) -> dict:
        """Add a comment to an issue."""
        mutation = """
        mutation AddComment($issueId: String!, $body: String!) {
            commentCreate(input: { issueId: $issueId, body: $body }) {
                success
                comment {
                    id
                    body
                }
            }
        }
        """
        data = self._query(mutation, {"issueId": issue_id, "body": body})
        return data["commentCreate"]

    def get_or_create_label(self, team_id: str, label_name: str) -> str:
        """Get a label by name or create it if it doesn't exist. Returns label ID."""
        # First try to find existing label
        query = """
        query GetLabel($teamId: String!, $labelName: String!) {
            issueLabels(filter: { team: { id: { eq: $teamId } }, name: { eq: $labelName } }) {
                nodes {
                    id
                    name
                }
            }
        }
        """
        data = self._query(query, {"teamId": team_id, "labelName": label_name})
        labels = data["issueLabels"]["nodes"]
        if labels:
            return labels[0]["id"]

        # Create new label
        mutation = """
        mutation CreateLabel($teamId: String!, $name: String!) {
            issueLabelCreate(input: { teamId: $teamId, name: $name, color: "#f59e0b" }) {
                success
                issueLabel {
                    id
                    name
                }
            }
        }
        """
        data = self._query(mutation, {"teamId": team_id, "name": label_name})
        return data["issueLabelCreate"]["issueLabel"]["id"]

    def get_team_id(self) -> str:
        """Get the team ID for PROF team."""
        query = """
        query GetTeam {
            teams(filter: { key: { eq: "PROF" } }) {
                nodes {
                    id
                }
            }
        }
        """
        data = self._query(query)
        return data["teams"]["nodes"][0]["id"]


# =============================================================================
# AI CLASSIFICATION
# =============================================================================


@dataclass
class ClassificationResult:
    """Result of AI classification with confidence info."""
    primary_bucket: str
    secondary_bucket: Optional[str]
    confidence: str  # "high" or "low"
    reasoning: str


def classify_issue(
    client: anthropic.Anthropic,
    issue: dict,
    bucket_descriptions: str,
    bucket_names: list[str],
    bucket_mapping: dict[str, str],
) -> ClassificationResult:
    """Use Claude to classify an issue into a bucket with confidence scoring."""

    title = issue.get("title", "")
    description = issue.get("description", "") or ""
    labels = [l["name"] for l in issue.get("labels", {}).get("nodes", [])]

    prompt = f"""You are a Product Operations assistant helping to triage product feedback issues.

Given the following product feedback issue, classify it into the available buckets.

## Available Buckets:
{bucket_descriptions}

## Special Features (override parent bucket):
- Native Datatypes: belongs to Zuzana Bednarova (not Storage owner)

## Issue to Classify:
**Title:** {title}

**Description:** {description}

**Labels:** {', '.join(labels) if labels else 'None'}

## Instructions:
Analyze the issue and provide your classification in this exact JSON format:
{{
    "primary_bucket": "BucketName",
    "secondary_bucket": "OtherBucketName or null if confident",
    "confidence": "high or low",
    "reasoning": "Brief explanation of why this bucket was chosen"
}}

Rules:
1. primary_bucket: The most appropriate bucket (must match a bucket name exactly)
2. secondary_bucket: If you're torn between two buckets, provide the alternative. Set to null if confident.
3. confidence: "high" if clearly one bucket, "low" if could reasonably be multiple buckets
4. reasoning: 1-2 sentences explaining the classification

Respond with ONLY the JSON, nothing else."""

    message = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=300,
        messages=[{"role": "user", "content": prompt}]
    )

    response_text = message.content[0].text.strip()

    # Parse JSON response
    try:
        # Handle potential markdown code blocks
        if response_text.startswith("```"):
            response_text = response_text.split("```")[1]
            if response_text.startswith("json"):
                response_text = response_text[4:]
        result = json.loads(response_text)
    except json.JSONDecodeError:
        # Fallback: treat entire response as bucket name
        return ClassificationResult(
            primary_bucket=response_text,
            secondary_bucket=None,
            confidence="low",
            reasoning="Failed to parse AI response",
        )

    primary = result.get("primary_bucket", "UX")
    secondary = result.get("secondary_bucket")
    confidence = result.get("confidence", "low")
    reasoning = result.get("reasoning", "")

    # Validate primary bucket exists (case-insensitive match)
    primary_lower = primary.lower()
    for name in bucket_names:
        if name.lower() == primary_lower:
            primary = name
            break

    # Check if secondary bucket has different owner (affects confidence)
    if secondary and confidence == "low":
        primary_owner = bucket_mapping.get(primary.lower(), "")
        secondary_owner = bucket_mapping.get(secondary.lower(), "")
        # If same owner, treat as high confidence (doesn't matter which bucket)
        if primary_owner and secondary_owner and primary_owner == secondary_owner:
            confidence = "high"

    return ClassificationResult(
        primary_bucket=primary,
        secondary_bucket=secondary,
        confidence=confidence,
        reasoning=reasoning,
    )


# =============================================================================
# MAIN LOGIC
# =============================================================================

def process_issues(
    linear: LinearClient,
    anthropic_client: anthropic.Anthropic,
    issues: list[dict],
    bucket_mapping: dict[str, str],
    bucket_descriptions: str,
    team_members: list[dict],
    team_id: str,
    dry_run: bool = True,
) -> list[dict]:
    """Process a list of issues and assign them to owners."""

    results = []
    bucket_names = list(set(bucket_mapping.keys()))

    # Build member lookup by name
    member_lookup = {}
    for member in team_members:
        member_lookup[member["name"].lower()] = member
        # Also add normalized versions
        for csv_name, linear_name in OWNER_NAME_MAP.items():
            if member["name"] == linear_name:
                member_lookup[csv_name.lower()] = member

    # Get needs-review label ID (only if we'll need it)
    needs_review_label_id = None

    for issue in issues:
        identifier = issue["identifier"]
        title = issue["title"]
        current_assignee = issue.get("assignee")
        existing_labels = [l["name"] for l in issue.get("labels", {}).get("nodes", [])]

        print(f"\n{'='*60}")
        print(f"Processing: {identifier} - {title}")

        # Skip if already assigned
        if current_assignee:
            print(f"  ⏭️  Already assigned to: {current_assignee['name']}")
            results.append({
                "identifier": identifier,
                "title": title,
                "action": "skipped",
                "reason": f"Already assigned to {current_assignee['name']}",
            })
            continue

        # Classify the issue
        print("  🤖 Classifying with AI...")
        classification = classify_issue(
            anthropic_client, issue, bucket_descriptions, bucket_names, bucket_mapping
        )
        bucket = classification.primary_bucket
        print(f"  📂 Classified as: {bucket}")
        print(f"  📝 Reasoning: {classification.reasoning}")
        if classification.secondary_bucket:
            print(f"  🔀 Alternative: {classification.secondary_bucket}")
        print(f"  🎯 Confidence: {classification.confidence}")

        # Check for feature overrides (e.g., Native Datatypes -> Zuzana)
        title_lower = title.lower()
        owner_name = None
        for feature, override_owner in FEATURE_OWNER_OVERRIDES.items():
            if feature in title_lower:
                owner_name = override_owner
                print(f"  🔄 Feature override: '{feature}' -> {override_owner}")
                break

        # If no override, use bucket owner
        if not owner_name:
            owner_name = bucket_mapping.get(bucket.lower())

        if not owner_name:
            print(f"  ⚠️  No owner found for bucket '{bucket}'")
            results.append({
                "identifier": identifier,
                "title": title,
                "bucket": bucket,
                "action": "error",
                "reason": f"No owner found for bucket '{bucket}'",
            })
            continue

        print(f"  👤 Owner: {owner_name}")

        # Find member in Linear
        normalized_owner = normalize_owner_name(owner_name)
        member = member_lookup.get(owner_name.lower()) or member_lookup.get(normalized_owner.lower())

        if not member:
            print(f"  ⚠️  Owner '{owner_name}' not found in Linear team")
            results.append({
                "identifier": identifier,
                "title": title,
                "bucket": bucket,
                "owner": owner_name,
                "action": "error",
                "reason": f"Owner '{owner_name}' not found in Linear team",
            })
            continue

        # Determine if we need to add needs-review label
        add_needs_review = classification.confidence == "low"
        if add_needs_review:
            print(f"  ⚠️  Low confidence - will add '{NEEDS_REVIEW_LABEL}' label")

        # Build audit comment
        comment_parts = [
            f"**Auto-triage classification**",
            f"",
            f"- **Bucket:** {bucket}",
            f"- **Assigned to:** {member['name']}",
            f"- **Confidence:** {classification.confidence}",
        ]
        if classification.secondary_bucket:
            comment_parts.append(f"- **Alternative bucket:** {classification.secondary_bucket}")
        comment_parts.append(f"- **Reasoning:** {classification.reasoning}")
        comment_body = "\n".join(comment_parts)

        # Assign the issue
        if dry_run:
            print(f"  🔍 DRY RUN: Would assign to {member['name']}")
            if add_needs_review:
                print(f"  🔍 DRY RUN: Would add label '{NEEDS_REVIEW_LABEL}'")
            print(f"  🔍 DRY RUN: Would add comment:")
            print(f"      {comment_body[:100]}...")
            results.append({
                "identifier": identifier,
                "title": title,
                "bucket": bucket,
                "owner": member["name"],
                "confidence": classification.confidence,
                "action": "would_assign",
            })
        else:
            print(f"  ✅ Assigning to {member['name']}...")
            try:
                # Get label ID if needed
                label_ids = None
                if add_needs_review:
                    if needs_review_label_id is None:
                        needs_review_label_id = linear.get_or_create_label(team_id, NEEDS_REVIEW_LABEL)
                    label_ids = [needs_review_label_id]

                # Assign issue (with optional label)
                linear.assign_issue(issue["id"], member["id"], label_ids)
                print(f"  ✅ Assigned successfully!")

                # Add audit comment
                linear.add_comment(issue["id"], comment_body)
                print(f"  💬 Added audit comment")

                results.append({
                    "identifier": identifier,
                    "title": title,
                    "bucket": bucket,
                    "owner": member["name"],
                    "confidence": classification.confidence,
                    "action": "assigned",
                })
            except Exception as e:
                print(f"  ❌ Failed to assign: {e}")
                results.append({
                    "identifier": identifier,
                    "title": title,
                    "bucket": bucket,
                    "owner": member["name"],
                    "action": "error",
                    "reason": str(e),
                })

    return results


def main():
    parser = argparse.ArgumentParser(description="Linear Product Feedback Triage Automation")
    parser.add_argument("--execute", action="store_true", help="Actually assign issues (default is dry run)")
    parser.add_argument("--issue", type=str, help="Process a specific issue by identifier (e.g., PROF-23)")
    args = parser.parse_args()

    dry_run = not args.execute

    # Check environment variables
    linear_api_key = os.environ.get("LINEAR_API_KEY")
    anthropic_api_key = os.environ.get("ANTHROPIC_API_KEY")

    if not linear_api_key:
        print("❌ ERROR: LINEAR_API_KEY environment variable not set")
        print("   Get your API key from: https://linear.app/settings/api")
        return 1

    if not anthropic_api_key:
        print("❌ ERROR: ANTHROPIC_API_KEY environment variable not set")
        return 1

    # Initialize clients
    linear = LinearClient(linear_api_key)
    anthropic_client = anthropic.Anthropic(api_key=anthropic_api_key)

    # Load bucket mapping
    print("📂 Loading bucket mapping...")
    bucket_mapping = load_bucket_mapping()
    bucket_descriptions = get_bucket_descriptions()
    print(f"   Loaded {len(bucket_mapping)} buckets")

    # Get team ID and members
    print("👥 Fetching team info...")
    team_id = linear.get_team_id()
    team_members = linear.get_team_members()
    print(f"   Found {len(team_members)} team members")

    # Get issues to process
    if args.issue:
        print(f"🎯 Fetching issue {args.issue}...")
        issue = linear.get_issue_by_identifier(args.issue)
        issues = [issue]
    else:
        print("📋 Fetching Triage issues...")
        issues = linear.get_triage_issues()

    print(f"   Found {len(issues)} issue(s) to process")

    if not issues:
        print("\n✅ No issues to process!")
        return 0

    # Process issues
    mode = "DRY RUN" if dry_run else "EXECUTE"
    print(f"\n{'='*60}")
    print(f"🚀 Starting triage automation ({mode})")
    print(f"{'='*60}")

    results = process_issues(
        linear=linear,
        anthropic_client=anthropic_client,
        issues=issues,
        bucket_mapping=bucket_mapping,
        bucket_descriptions=bucket_descriptions,
        team_members=team_members,
        team_id=team_id,
        dry_run=dry_run,
    )

    # Summary
    print(f"\n{'='*60}")
    print("📊 SUMMARY")
    print(f"{'='*60}")

    assigned = [r for r in results if r["action"] in ("assigned", "would_assign")]
    skipped = len([r for r in results if r["action"] == "skipped"])
    errors = len([r for r in results if r["action"] == "error"])
    high_conf = len([r for r in assigned if r.get("confidence") == "high"])
    low_conf = len([r for r in assigned if r.get("confidence") == "low"])

    print(f"   {'Would assign' if dry_run else 'Assigned'}: {len(assigned)}")
    print(f"      - High confidence: {high_conf}")
    print(f"      - Low confidence (needs-review): {low_conf}")
    print(f"   Skipped (already assigned): {skipped}")
    print(f"   Errors: {errors}")

    if dry_run and len(assigned) > 0:
        print(f"\n💡 Run with --execute to actually assign these issues")

    return 0


if __name__ == "__main__":
    exit(main())
