"""Oracle's Elixir match data, read from the Google Drive folder it publishes to.

Drive refuses anonymous downloads of popular files for up to a day at a time, so requests are made as a
service account (GOOGLE_APPLICATION_CREDENTIALS) with read-only access.
"""
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import google.auth
from google.auth.exceptions import DefaultCredentialsError
from google.auth.transport.requests import AuthorizedSession

FOLDER_ID = "1gLSw0RLjBbtaNy0dgnGQDAZOHIgCe-HH"
API = "https://www.googleapis.com/drive/v3/files"
SCOPES = ["https://www.googleapis.com/auth/drive.readonly"]


class MissingCredentials(Exception):
    pass


@dataclass(frozen=True)
class SourceFile:
    id: str
    name: str
    modified_at: datetime

    @property
    def year(self) -> int:
        return int(self.name[:4])


class Drive:
    def __init__(self):
        try:
            credentials, _ = google.auth.default(scopes=SCOPES)
        except DefaultCredentialsError as e:
            raise MissingCredentials(
                "No Google service account key; set GOOGLE_CREDENTIALS in .env (see README), "
                "or load a downloaded file with --file."
            ) from e
        self.session = AuthorizedSession(credentials)

    def files(self) -> list[SourceFile]:
        """The yearly CSVs, oldest first. IDs change when a year's file is replaced, so they're looked up each time."""
        resp = self.session.get(API, timeout=60, params={
            "q": f"'{FOLDER_ID}' in parents and trashed = false",
            "fields": "files(id,name,modifiedTime)",
            "pageSize": 1000,
        })
        resp.raise_for_status()
        files = [
            SourceFile(f["id"], f["name"], datetime.fromisoformat(f["modifiedTime"]))
            for f in resp.json()["files"]
            if f["name"][:4].isdigit() and f["name"].endswith(".csv")
        ]
        return sorted(files, key=lambda f: f.name)

    def download(self, file: SourceFile, dest: Path) -> Path:
        path = dest / file.name
        with self.session.get(f"{API}/{file.id}", params={"alt": "media"}, stream=True, timeout=600) as resp:
            resp.raise_for_status()
            with path.open("wb") as out:
                for chunk in resp.iter_content(1 << 20):
                    out.write(chunk)
        return path
