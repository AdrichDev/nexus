# -*- coding: utf-8 -*-
"""Shared read-only FAKE Gmail / Calendar / Tasks provider (Google client shapes).

Used by test_inbox_fake_gmail.py and test_inbox_scale.py. Pure Python, no network, no
credentials. Any Gmail method outside GMAIL_READS is recorded as FORBIDDEN and raises.
"""
from __future__ import annotations

import base64


# ───────────────────────────── fake Google API ─────────────────────────────
class HttpError(Exception):
    """Stand-in for googleapiclient.errors.HttpError (status + reason)."""

    def __init__(self, status=500, reason="backendError"):
        super().__init__(f"<HttpError {status} \"{reason}\">")
        self.status = status


def b64(text: str) -> str:
    return base64.urlsafe_b64encode(text.encode("utf-8")).decode("ascii")


def mail(mid, sender, subject, plain, *, multipart=False, unread=True, html_only=False):
    """A Gmail `users.messages` resource as the API returns it for format=full."""
    if html_only:                 # no text/plain part at all: the reader falls back to the snippet
        payload = {"mimeType": "text/html", "body": {"data": b64("<html><body><p>" + plain + "</p></body></html>")}}
    elif multipart:
        payload = {"mimeType": "multipart/alternative", "body": {"size": 0}, "parts": [
            {"mimeType": "text/html", "body": {"data": b64("<p>" + plain + "</p>")}},
            {"mimeType": "multipart/related", "body": {"size": 0}, "parts": [
                {"mimeType": "text/plain", "body": {"data": b64(plain)}}]}]}
    else:
        payload = {"mimeType": "text/plain", "body": {"data": b64(plain)}}
    payload["headers"] = [{"name": "From", "value": sender},
                          {"name": "Subject", "value": subject}]
    return {"id": mid, "threadId": "t" + mid, "snippet": plain[:100],
            "labelIds": ["INBOX"] + (["UNREAD"] if unread else []), "payload": payload}


class _Call:
    """The request object returned by every API method; nothing happens until .execute()."""

    def __init__(self, fake, name, result):
        self.fake, self.name, self.result = fake, name, result

    def execute(self):
        self.fake.log.append(self.name)
        if self.fake.fail_on and self.fake.fail_on(self.name):
            raise HttpError()
        return self.result()


class _Res:
    """A Google resource exposing only the methods in `ops`. Any other attribute (modify,
    trash, send, delete, ...) is recorded as FORBIDDEN and raises."""

    def __init__(self, fake, prefix, ops):
        self._fake, self._prefix, self._ops = fake, prefix, ops

    def __getattr__(self, name):
        full = f"{self._prefix}.{name}"
        if name not in self._ops:
            self._fake.log.append("FORBIDDEN:" + full)
            raise AttributeError(full)

        def method(**kw):
            self._fake.calls.append((full, kw))
            return _Call(self._fake, full, lambda: self._ops[name](kw))
        return method


class FakeGoogle:
    """Fake Gmail v1 / Calendar v3 / Tasks v1 service objects over one in-memory mailbox."""

    def __init__(self, messages=(), fail_on=None):
        self.messages = {m["id"]: m for m in messages}
        self.fail_on = fail_on          # callable(op_name) -> bool
        self.log: list[str] = []        # executed operations, in order
        self.calls: list[tuple] = []    # (operation, kwargs) as received
        self.events: list[dict] = []
        self.tasks: list[dict] = []

    def inserts(self, op):
        return [kw for name, kw in self.calls if name == op]

    def _labels_get(self, kw):
        unread = [m for m in self.messages.values() if "UNREAD" in m["labelIds"]]
        return {"id": kw["id"], "threadsUnread": len(unread),
                "threadsTotal": len(self.messages)}

    def _list(self, kw):
        want_unread = "is:unread" in kw.get("q", "")
        out = [m for m in self.messages.values()
               if kw["labelIds"][0] in m["labelIds"]
               and (not want_unread or "UNREAD" in m["labelIds"])]
        return {"messages": [{"id": m["id"], "threadId": m["threadId"]}
                             for m in out[:kw.get("maxResults", 100)]],
                "resultSizeEstimate": len(out)}          # single page: no nextPageToken

    def _get(self, kw):
        m = self.messages[kw["id"]]
        if kw.get("format", "full") == "metadata":
            keep = set(kw.get("metadataHeaders") or [])
            hdrs = [h for h in m["payload"]["headers"] if h["name"] in keep]
            return {"id": m["id"], "snippet": m["snippet"], "labelIds": m["labelIds"],
                    "payload": {"headers": hdrs}}
        return m

    def _insert_event(self, kw):
        self.events.append(kw["body"])
        return {"id": f"ev{len(self.events)}", "htmlLink": f"https://fake/ev{len(self.events)}"}

    def _insert_task(self, kw):
        self.tasks.append(kw["body"])
        return {"id": f"tk{len(self.tasks)}"}

    def build(self, api, version, **_kw):
        f = self
        if api == "gmail":
            class Users:
                def messages(_s):
                    return _Res(f, "gmail.messages", {"list": f._list, "get": f._get})

                def labels(_s):
                    return _Res(f, "gmail.labels", {"get": f._labels_get})

            class Svc:
                def users(_s):
                    return Users()
            return Svc()
        if api == "calendar":
            class Svc:
                def events(_s):
                    return _Res(f, "calendar.events", {"insert": f._insert_event})
            return Svc()
        if api == "tasks":
            class Svc:
                def tasks(_s):
                    return _Res(f, "tasks.tasks", {"insert": f._insert_task})
            return Svc()
        raise AssertionError("unexpected API " + api)


GMAIL_READS = {"gmail.labels.get", "gmail.messages.list", "gmail.messages.get"}
