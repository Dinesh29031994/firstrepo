"""Concrete implementations of Gmail and Calendar services using Google APIs."""

from __future__ import print_function
import base64
import os.path
import pickle
from email.mime.text import MIMEText
from datetime import datetime, timedelta, date
from typing import List, Dict, Optional, Union

from googleapiclient.discovery import build
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
import datetime

from interfaces import (
    AuthenticationService,
    EmailService,
    CalendarService,
    GoogleServiceProvider,
    SheetService,
)

# Scopes for Gmail + Calendar access
SCOPES = [
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.send",
    "https://www.googleapis.com/auth/gmail.modify",
    "https://www.googleapis.com/auth/gmail.compose",
    "https://www.googleapis.com/auth/calendar",
]


class GoogleAuthenticationService(AuthenticationService):
    """Google OAuth2 authentication implementation."""

    def __init__(self, credentials_file: str = "credentials.json", token_file: str = "token.pickle"):
        """Initialize the authentication service.

        Args:
            credentials_file: Path to the Google OAuth2 credentials JSON file.
            token_file: Path to store/load the cached token.
        """
        self.credentials_file = credentials_file
        self.token_file = token_file

    def get_credentials(self):
        """Authenticate user and return credentials."""
        creds = None

        # Load existing token if present
        if os.path.exists(self.token_file):
            with open(self.token_file, "rb") as token:
                creds = pickle.load(token)

        # If no valid token → ask user to log in
        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                creds.refresh(Request())
            else:
                flow = InstalledAppFlow.from_client_secrets_file(
                    self.credentials_file, SCOPES
                )
                creds = flow.run_local_server(port=0)

            # Save the new token
            with open(self.token_file, "wb") as token:
                pickle.dump(creds, token)

        return creds


class GoogleGmailService(EmailService):
    """Gmail API implementation for email operations."""

    def __init__(self, auth_service: AuthenticationService):
        """Initialize Gmail service.

        Args:
            auth_service: AuthenticationService instance for credentials.
        """
        self.auth_service = auth_service
        self._service = None

    @property
    def service(self):
        """Lazy load Gmail service."""
        if self._service is None:
            creds = self.auth_service.get_credentials()
            self._service = build("gmail", "v1", credentials=creds)
        return self._service

    def list_messages(self, query: str = "") -> List[Dict]:
        """Return list of message IDs based on search query."""
        results = self.service.users().messages().list(userId="me", q=query).execute()
        return results.get("messages", [])

    def read_message(self, msg_id: str) -> Dict:
        """Read full email details from inbox only."""
        msg = self.service.users().messages().get(
            userId="me", id=msg_id, format="full"
        ).execute()
        headers = msg["payload"]["headers"]
        sender = next((h["value"] for h in headers if h["name"] == "From"), "")
        subject = next((h["value"] for h in headers if h["name"] == "Subject"), "")
        snippet = msg.get("snippet", "")
        timestamp = datetime.datetime.fromtimestamp(int(msg["internalDate"])/1000)

        print("-------------------------------------------------")
        print("From:", sender)
        print("Subject:", subject)
        print("Snippet:", snippet)
        print("Timestamp:", timestamp)
        print("ID:", msg_id)
        print("-------------------------------------------------")

        return [msg_id, sender, subject, snippet, timestamp]

        #return msg

    def create_message(
        self, sender: str, to: str, subject: str, message_text: str
    ) -> Dict:
        """Create a MIME text email."""
        message = MIMEText(message_text)
        message["to"] = to
        message["from"] = sender
        message["subject"] = subject

        raw = base64.urlsafe_b64encode(message.as_bytes()).decode()
        return {"raw": raw}

    def send_message(
        self, sender: str, to: str, subject: str, message_text: str
    ) -> Dict:
        """Send email through Gmail API."""
        body = self.create_message(sender, to, subject, message_text)
        sent_msg = self.service.users().messages().send(
            userId="me", body=body
        ).execute()

        print("Message sent! ID:", sent_msg["id"])
        return sent_msg


class GoogleCalendarService(CalendarService):
    """Google Calendar API implementation for calendar operations."""

    def __init__(self, auth_service: AuthenticationService):
        """Initialize Calendar service.

        Args:
            auth_service: AuthenticationService instance for credentials.
        """
        self.auth_service = auth_service
        self._service = None

    @property
    def service(self):
        """Lazy load Calendar service."""
        if self._service is None:
            creds = self.auth_service.get_credentials()
            self._service = build("calendar", "v3", credentials=creds)
        return self._service

    def list_events(
        self,
        calendar_id: str = "primary",
        max_results: int = 10,
        only_today: bool = False,
        for_date: Optional[Union[str, date]] = None,
        next_days: int = 10,
    ) -> List[Dict]:
        """Retrieve calendar events."""
        params = {
            "calendarId": calendar_id,
            "maxResults": max_results,
            "singleEvents": True,
            "orderBy": "startTime",
        }

        if only_today or for_date is not None:
            # Determine the target date
            if for_date:
                if isinstance(for_date, str):
                    target_date = datetime.datetime.fromisoformat(for_date).date()
                    #target_date = datetime.fromisoformat(for_date).date()
                else:
                    target_date = for_date
            else:
                target_date = datetime.datetime.now().date()

            # Create timezone-aware start and end datetimes for the local timezone
            tz = datetime.datetime.now().astimezone().tzinfo
            start_dt = datetime.datetime(
                target_date.year,
                target_date.month,
                target_date.day,
                0,
                0,
                0,
                tzinfo=tz,
            )
            end_dt = start_dt + timedelta(days=next_days)

            params["timeMin"] = start_dt.isoformat()
            params["timeMax"] = end_dt.isoformat()
            print(f"Fetching events for date: {target_date} from {params}")

        events_result = self.service.events().list(**params).execute()
        return events_result.get("items", [])

    def create_event(
        self,
        title: str,
        description: str,
        start_time: str,
        end_time: str,
        calendar_id: str = "primary",
    ) -> Dict:
        """Create a new calendar event."""
        event = {
            "summary": title,
            "description": description,
            "start": {"dateTime": start_time, "timeZone": "UTC"},
            "end": {"dateTime": end_time, "timeZone": "UTC"},
        }

        created_event = self.service.events().insert(
            calendarId=calendar_id, body=event
        ).execute()

        print(f"Event created! ID: {created_event['id']}")
        return created_event

    def delete_event(self, event_id: str, calendar_id: str = "primary") -> None:
        """Delete a calendar event."""
        self.service.events().delete(
            calendarId=calendar_id, eventId=event_id
        ).execute()

        print(f"Event {event_id} deleted!")


class GoogleServiceProvider(GoogleServiceProvider):
    """Unified Google service provider for both Gmail and Calendar."""

    def __init__(
        self,
        credentials_file: str = "credentials.json",
        token_file: str = "token.pickle",
    ):
        """Initialize the Google service provider.

        Args:
            credentials_file: Path to the Google OAuth2 credentials JSON file.
            token_file: Path to store/load the cached token.
        """
        self.auth_service = GoogleAuthenticationService(credentials_file, token_file)
        self.gmail_service = GoogleGmailService(self.auth_service)
        self.calendar_service = GoogleCalendarService(self.auth_service)
        self.sheets_service = GmailToSheetSync(self.auth_service)

    def get_gmail_service(self) -> EmailService:
        """Return Gmail API service instance."""
        return self.gmail_service

    def get_calendar_service(self) -> CalendarService:
        """Return Calendar API service instance."""
        return self.calendar_service
    
    def get_sheets_service(self):
        """Return Sheets API service instance."""
        #creds = self.auth_service.get_credentials()
        return self.sheets_service
    
class GmailToSheetSync(SheetService):
    """Sync Gmail messages into Google Sheets."""

    def __init__(self, sheet_service):
        self.sheet_service = sheet_service

    def extract_email_data(self, message: Dict) -> List[str]:
        """Convert a Gmail API message → sheet-compatible row."""
        msg_id = message.get("id", "")
        snippet = message.get("snippet", "")

        headers = message.get("payload", {}).get("headers", [])

        def get_header(name):
            return next(
                (h["value"] for h in headers if h["name"].lower() == name.lower()), ""
            )

        from_ = get_header("From")
        to_ = get_header("To")
        subject = get_header("Subject")

        epoch_ms = int(message.get("internalDate", "0"))
        timestamp = datetime.fromtimestamp(epoch_ms / 1000).isoformat()

        return [msg_id, from_, to_, subject, snippet, str(epoch_ms), timestamp]
    
    def write_rows(
        self,
        spreadsheet_id: str,
        range_name: str,
        rows: List[List[Union[str, int, float]]],
        append: bool = True,
    ) -> Dict:

        body = {"values": rows}

        if append:
            result = (
                self.service.spreadsheets()
                .values()
                .append(
                    spreadsheetId=spreadsheet_id,
                    range=range_name,
                    valueInputOption="RAW",
                    insertDataOption="INSERT_ROWS",
                    body=body,
                )
                .execute()
            )
        else:
            # overwrite mode
            result = (
                self.service.spreadsheets()
                .values()
                .update(
                    spreadsheetId=spreadsheet_id,
                    range=range_name,
                    valueInputOption="RAW",
                    body=body,
                )
                .execute()
            )

        return result

    def sync_messages_to_sheet(
        self,
        messages: List[Dict],
        spreadsheet_id: str,
        range_name: str = "Sheet1!A1",
    ) -> None:

        rows = [
            ["Message ID", "From", "Subject", "Snippet", "Epoch", "Timestamp"]
        ]

        for msg in messages:
            rows.append(msg)

        # overwrite sheet starting from A1
        self.sheet_service.write_rows(
            spreadsheet_id=spreadsheet_id,
            range_name=range_name,
            rows=rows,
            append=True,
        )
