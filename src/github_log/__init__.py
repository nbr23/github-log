from datetime import datetime
import os
import sys
import requests
import argparse

from zoneinfo import ZoneInfo

class GitHubAPI:
    def __init__(self, access_token):
        self.access_token = access_token
        self.headers = {
            'Authorization': f'Bearer {access_token}',
            'Accept': 'application/vnd.github.v3+json'
        }
    
    def get_user_events(self, username, page=1):
        url = f'https://api.github.com/users/{username}/events'
        params = {'page': page}
        response = requests.get(url, headers=self.headers, params=params)
        response.raise_for_status()
        return response.json()
    
    def get_user_events_date(self, username, local_date):
        page = 1
        fetch_more = True


        local_tz = datetime.now().astimezone().tzinfo
        start_dt = datetime.combine(local_date, datetime.min.time()).replace(tzinfo=local_tz)
        end_dt = datetime.combine(local_date, datetime.max.time()).replace(tzinfo=local_tz)

        while fetch_more:
            events = self.get_user_events(username, page)
            for event in events:
                event_dt = datetime.strptime(
                    event['created_at'], 
                    '%Y-%m-%dT%H:%M:%SZ'
                ).replace(tzinfo=ZoneInfo('UTC')).astimezone(local_tz)
                
                event['created_at'] = event_dt
                if event_dt < start_dt:
                    fetch_more = False
                if start_dt <= event_dt <= end_dt:
                    yield event
            page += 1

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
    return switcher.get(event['type'], event['type'])

def get_prefix(event):
    branch = event.get('payload').get('ref').split('/')[-1]
    if branch:
        return f"{event['created_at']} {event['actor']['login']}/{get_pretty_event_type(event)}\t{event['repo']['name']}:{branch}"
    return f"{event['created_at']} {event['actor']['login']}/{get_pretty_event_type(event)}\t{event['repo']['name']}"

def push_formatter(logLines, event):
    for commit in event['payload']['commits']:
        logLines.append(f"{get_prefix(event)} - {commit['message'].replace('\n', ',')}")

def pull_request_formatter(logLines, event):
    logLines.append(f"{get_prefix(event)} -{event['payload']['action']} - {event['payload']['pull_request']['title']}")

def create_formatter(logLines, event):
    logLines.append(f"{get_prefix(event)} - {event['payload']['ref_type']} {event['payload']['ref'] or ''}")

def pull_request_review_comment_formatter(logLines, event):
    logLines.append(f"{get_prefix(event)} - on PR {event['payload']['pull_request']['title']}")

def pull_request_review_formatter(logLines, event):
    logLines.append(f"{get_prefix(event)} - on PR {event['payload']['pull_request']['title']}")

def issue_comment_formatter(logLines, event):
    logLines.append(f"{get_prefix(event)} - on Issue {event['payload']['issue']['title']}")

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
    return switcher.get(event['type'], default_formatter)(logLines, event)


def get_github_activity(github_token, username, target_date):
    gh = GitHubAPI(github_token)
    target_date = datetime.strptime(target_date, '%Y-%m-%d').date()
    logLines = []
    for event in gh.get_user_events_date(username, target_date):
        actor = event['actor']['login']
        if actor == username:
            activity_formatter(logLines, event)
    return logLines

def print_activity(logLines):
    for line in logLines:
        print(line)

def main():
    parser = argparse.ArgumentParser(
        description='Fetch GitHub log for a specific user on a given date',
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    
    parser.add_argument('-u', '--user', 
                        required=True,
                        help='GitHub username to fetch activity for')
    
    parser.add_argument('-d', '--date',
                        default=datetime.now().date().strftime('%Y-%m-%d'),
                        help='Date to fetch activity for (YYYY-MM-DD format, defaults to today)')
    
    parser.add_argument('-t', '--token',
                        help='GitHub API token (can also be set via GITHUB_TOKEN environment variable)')

    args = parser.parse_args()
    token = args.token or os.getenv('GITHUB_TOKEN')
    if not token:
        print("Please set GITHUB_TOKEN environment variable")
        exit(1)

    try:
        activity = get_github_activity(token, args.user, args.date)
        print_activity(activity)
    except requests.exceptions.RequestException as e:
        print(f"Error fetching GitHub log: {e}", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"An error occurred: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
