from datetime import datetime, timedelta
import os
import sys
import requests
import argparse
import re

from zoneinfo import ZoneInfo


class GitHubAPI:
    def __init__(self, access_token, orgs=""):
        self.access_token = access_token
        self.headers = {
            "Authorization": f"Bearer {access_token}",
            "Accept": "application/vnd.github.v3+json",
        }
        self.current_user = self.get_current_user().get("login")
        if orgs == "":
            self.orgs = []
        else:
            self.orgs = [o for o in orgs.split(",") if o != ""]
        self.emails = self.get_current_user_emails()

    def get_current_user(self):
        url = "https://api.github.com/user"
        response = requests.get(url, headers=self.headers)
        response.raise_for_status()
        return response.json()

    def get_current_user_emails(self):
        url = "https://api.github.com/user/emails"
        response = requests.get(url, headers=self.headers)
        response.raise_for_status()
        return [e["email"] for e in response.json()]

    def get_user_events(self, page=1):
        url = f"https://api.github.com/users/{self.current_user}/events"
        params = {"page": page}
        response = requests.get(url, headers=self.headers, params=params)
        response.raise_for_status()
        return response.json()

    def get_org_events(self, org, page=1):
        url = f"https://api.github.com/users/{self.current_user}/events/orgs/{org}"
        params = {"page": page}
        response = requests.get(url, headers=self.headers, params=params)
        response.raise_for_status()
        return response.json()

    def get_orgs(self):
        url = "https://api.github.com/user/orgs"
        response = requests.get(url, headers=self.headers)
        response.raise_for_status()
        return response.json()

    def get_events_date(self, local_date, events_filter):
        local_tz = datetime.now().astimezone().tzinfo
        start_dt = datetime.combine(local_date, datetime.min.time()).replace(
            tzinfo=local_tz
        )
        end_dt = datetime.combine(local_date, datetime.max.time()).replace(
            tzinfo=local_tz
        )

        events_filter = [e.lower() for e in events_filter.split(",") if e != ""]

        yield from self.get_method_events_date(
            local_tz, start_dt, end_dt, events_filter, self.get_user_events
        )
        for org in self.orgs:
            yield from self.get_method_events_date(
                local_tz,
                start_dt,
                end_dt,
                events_filter,
                lambda page: self.get_org_events(org, page),
            )

    def get_method_events_date(self, local_tz, start_dt, end_dt, events_filter, method):
        page = 1
        fetch_more = True

        while fetch_more:
            try:
                events = method(page)
            except requests.exceptions.RequestException as e:
                print(f"Error fetching GitHub log: {e}", file=sys.stderr)
                break
            for event in events:
                if (
                    events_filter
                    and event["type"].lower() not in events_filter
                    and event["type"].replace("Event", "").lower() not in events_filter
                ):
                    continue

                logins = []
                emails = []
                find_user_logins(logins, emails, event)
                if self.current_user not in logins and not set(
                    self.emails
                ).intersection(emails):
                    continue

                event_dt = (
                    datetime.strptime(event["created_at"], "%Y-%m-%dT%H:%M:%SZ")
                    .replace(tzinfo=ZoneInfo("UTC"))
                    .astimezone(local_tz)
                )

                event["created_at"] = event_dt
                if event_dt < start_dt:
                    fetch_more = False
                if start_dt <= event_dt <= end_dt:
                    yield event
            page += 1


def find_user_logins(logins, emails, event):
    if not isinstance(event, dict):
        return
    for k, v in event.items():
        if k == "login":
            logins.append(v)
        if k == "email":
            emails.append(v)
        elif isinstance(v, dict):
            find_user_logins(logins, emails, v)
        elif isinstance(v, list):
            for item in v:
                find_user_logins(logins, emails, item)


def get_pretty_event_type(event):
    switcher = {
        "DeleteEvent": "Delete",
        "PushEvent": "Push",
        "PullRequestEvent": "PR",
        "CreateEvent": "Create",
        "ForkEvent": "Fork",
        "ReleaseEvent": "Release",
        "PullRequestReviewEvent": "PR Review",
        "PullRequestReviewCommentEvent": "PR Comment",
        "IssueCommentEvent": "Issue Comment",
    }
    return switcher.get(event["type"], event["type"])


def get_prefix(event):
    branch = (event.get("payload", {}).get("ref") or "").split("/")[-1]
    if branch:
        return f"{event['created_at']} {event['actor']['login']}/{get_pretty_event_type(event)}\t{event['repo']['name']}:{branch}"
    return f"{event['created_at']} {event['actor']['login']}/{get_pretty_event_type(event)}\t{event['repo']['name']}"


def push_formatter(logLines, event):
    for commit in event["payload"]["commits"]:
        logLines.append(f"{get_prefix(event)} - {commit['message'].replace('\n', ',')}")


def pull_request_formatter(logLines, event):
    logLines.append(
        f"{get_prefix(event)} -{event['payload']['action']} - {event['payload']['pull_request']['title']}"
    )


def create_formatter(logLines, event):
    if event["payload"]["ref_type"] == "repository":
        logLines.append(
            f"{get_prefix(event)} - {event['payload']['ref_type']} {event['repo']['name']}"
        )
    else:
        logLines.append(
            f"{get_prefix(event)} - {event['payload']['ref_type']} {event['payload']['ref'] or ''}"
        )


def pull_request_review_comment_formatter(logLines, event):
    logLines.append(
        f"{get_prefix(event)} - on PR {event['payload']['pull_request']['title']}"
    )


def pull_request_review_formatter(logLines, event):
    logLines.append(
        f"{get_prefix(event)} - on PR {event['payload']['pull_request']['title']}"
    )


def issue_comment_formatter(logLines, event):
    logLines.append(
        f"{get_prefix(event)} - on Issue {event['payload']['issue']['title']}"
    )


def default_formatter(logLines, event):
    logLines.append(f"{get_prefix(event)} - {event['payload']}")


def activity_formatter(logLines, event):
    switcher = {
        "PushEvent": push_formatter,
        "PullRequestEvent": pull_request_formatter,
        "CreateEvent": create_formatter,
        "DeleteEvent": create_formatter,
        "PullRequestReviewEvent": pull_request_review_formatter,
        "PullRequestReviewCommentEvent": pull_request_review_comment_formatter,
        "IssueCommentEvent": issue_comment_formatter,
    }
    return switcher.get(event["type"], default_formatter)(logLines, event)


def get_github_activity(gh, target_date, events_filter):
    logLines = []
    for event in gh.get_events_date(target_date, events_filter):
        activity_formatter(logLines, event)
    return logLines


def print_activity(logLines):
    for line in logLines:
        print(line)


def main():
    parser = argparse.ArgumentParser(
        description="Fetch GitHub log for a specific user on a given date",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    parser.add_argument(
        "-u", "--user", required=True, help="GitHub username to fetch activity for"
    )

    parser.add_argument(
        "-d",
        "--date",
        default=datetime.now().date().strftime("%Y-%m-%d"),
        help="Date to fetch activity for (YYYY-MM-DD format, defaults to today)",
    )

    parser.add_argument(
        "-t",
        "--token",
        help="GitHub API token (can also be set via GITHUB_TOKEN environment variable)",
    )

    parser.add_argument(
        "-e",
        "--events",
        default="",
        help="Comma-separated list of events to include in the log",
    )

    parser.add_argument(
        "-o",
        "--orgs",
        default="",
        help="Comma-separated list of organizations to include in the log",
    )

    args = parser.parse_args()
    token = args.token or os.getenv("GITHUB_TOKEN")
    if not token:
        print("Please set GITHUB_TOKEN environment variable")
        exit(1)

    if re.match(r"^\d{4}-\d{2}-\d{2}$", args.date):
        target_date = datetime.strptime(args.date, "%Y-%m-%d").date()
    elif re.match(r"^-?\d+$", args.date):
        target_date = datetime.now().date() + timedelta(days=int(args.date))

    try:
        gh = GitHubAPI(token, args.orgs)
        activity = get_github_activity(gh, target_date, args.events)
        print_activity(activity)
    except requests.exceptions.RequestException as e:
        print(f"Error fetching GitHub log: {e}", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"An error occurred: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
