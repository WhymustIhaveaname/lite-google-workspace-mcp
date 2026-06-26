import base64
from unittest.mock import MagicMock

from lite_google_workspace_mcp.gmail import (
    check_allowed_recipients,
    extract_attachments,
    extract_headers,
    extract_message_bodies,
    format_body_content,
    format_gmail_results,
    format_message_header_lines,
    format_thread_content,
    html_to_text,
    prepare_gmail_message,
    register_gmail_tools,
)


class TestCheckAllowedRecipients:
    def test_empty_allowlist_permits_all(self):
        assert check_allowed_recipients([], "anyone@example.com", None, None) == []

    def test_allowed(self):
        assert check_allowed_recipients(["a@x.com"], "a@x.com", None, None) == []

    def test_blocked(self):
        assert check_allowed_recipients(["a@x.com"], "b@x.com", None, None) == ["b@x.com"]

    def test_case_insensitive(self):
        assert check_allowed_recipients(["A@X.COM"], "a@x.com", None, None) == []

    def test_cc_bcc_checked(self):
        bad = check_allowed_recipients(["a@x.com"], "a@x.com", "b@x.com", "c@x.com")
        assert sorted(bad) == ["b@x.com", "c@x.com"]

    def test_display_name_parsed(self):
        assert check_allowed_recipients(["a@x.com"], "Alice <a@x.com>", None, None) == []

    def test_multiple_in_field(self):
        bad = check_allowed_recipients(["a@x.com"], "a@x.com, b@x.com", None, None)
        assert bad == ["b@x.com"]


class TestHtmlToText:
    def test_basic(self):
        assert "Hello world" in html_to_text("<p>Hello <b>world</b></p>")

    def test_strips_script(self):
        result = html_to_text("<p>ok</p><script>evil()</script>")
        assert "evil" not in result
        assert "ok" in result


class TestExtractHeaders:
    def test_extracts_matching(self):
        payload = {
            "headers": [
                {"name": "Subject", "value": "Test"},
                {"name": "From", "value": "alice@example.com"},
                {"name": "X-Custom", "value": "ignored"},
            ]
        }
        result = extract_headers(payload, ["Subject", "From"])
        assert result == {"Subject": "Test", "From": "alice@example.com"}

    def test_case_insensitive(self):
        payload = {"headers": [{"name": "subject", "value": "lower"}]}
        result = extract_headers(payload, ["Subject"])
        assert result["Subject"] == "lower"


class TestExtractMessageBodies:
    def test_plain_text(self):
        data = base64.urlsafe_b64encode(b"Hello plain").decode()
        payload = {"mimeType": "text/plain", "body": {"data": data}}
        bodies = extract_message_bodies(payload)
        assert bodies["text"] == "Hello plain"

    def test_multipart(self):
        text_data = base64.urlsafe_b64encode(b"Plain text").decode()
        html_data = base64.urlsafe_b64encode(b"<b>HTML</b>").decode()
        payload = {
            "mimeType": "multipart/alternative",
            "parts": [
                {"mimeType": "text/plain", "body": {"data": text_data}},
                {"mimeType": "text/html", "body": {"data": html_data}},
            ],
        }
        bodies = extract_message_bodies(payload)
        assert bodies["text"] == "Plain text"
        assert bodies["html"] == "<b>HTML</b>"


class TestExtractAttachments:
    def test_finds_attachments(self):
        payload = {
            "parts": [
                {
                    "filename": "report.pdf",
                    "mimeType": "application/pdf",
                    "body": {"attachmentId": "att123", "size": 1024},
                },
                {"mimeType": "text/plain", "body": {"data": "dGVzdA=="}},
            ]
        }
        atts = extract_attachments(payload)
        assert len(atts) == 1
        assert atts[0]["filename"] == "report.pdf"
        assert atts[0]["attachmentId"] == "att123"

    def test_empty_payload(self):
        assert extract_attachments({}) == []


class TestFormatBodyContent:
    def test_prefers_text(self):
        result = format_body_content("Plain body", "<b>HTML</b>", body_format="text")
        assert result == "Plain body"

    def test_html_mode(self):
        result = format_body_content("Plain", "<b>HTML</b>", body_format="html")
        assert "<b>HTML</b>" in result

    def test_no_content(self):
        result = format_body_content("", "", body_format="text")
        assert "No readable content" in result


class TestFormatGmailResults:
    def test_empty(self):
        result = format_gmail_results([], "test query")
        assert "No messages found" in result

    def test_with_messages(self):
        messages = [{"id": "msg1", "threadId": "t1"}, {"id": "msg2", "threadId": "t2"}]
        result = format_gmail_results(messages, "test")
        assert "msg1" in result
        assert "msg2" in result
        assert "2 messages" in result

    def test_pagination(self):
        result = format_gmail_results([{"id": "m1", "threadId": "t1"}], "q", "next123")
        assert "next123" in result


class TestFormatMessageHeaderLines:
    def test_basic(self):
        headers = {"Subject": "Test", "From": "a@x.com", "Date": "2026-01-01"}
        lines = format_message_header_lines(headers)
        assert any("Test" in ln for ln in lines)
        assert any("a@x.com" in ln for ln in lines)

    def test_with_message_id(self):
        headers = {"Subject": "S", "From": "a@x.com", "Date": "d"}
        lines = format_message_header_lines(headers, message_id="mid123")
        assert any("mid123" in ln for ln in lines)


class TestPrepareGmailMessage:
    def test_basic(self):
        raw, tid, count, errors = prepare_gmail_message(
            subject="Hello", body="World", to="bob@example.com"
        )
        assert isinstance(raw, str)
        assert count == 0
        decoded = base64.urlsafe_b64decode(raw)
        assert b"Hello" in decoded
        assert b"World" in decoded

    def test_reply(self):
        raw, tid, count, errors = prepare_gmail_message(
            subject="Meeting",
            body="Sure",
            to="bob@example.com",
            thread_id="t123",
            in_reply_to="<orig@gmail.com>",
        )
        decoded = base64.urlsafe_b64decode(raw)
        assert b"Re: Meeting" in decoded
        assert b"In-Reply-To" in decoded
        assert tid == "t123"

    def test_html_format(self):
        raw, _, _, _ = prepare_gmail_message(
            subject="Hi", body="<b>Bold</b>", to="a@x.com", body_format="html"
        )
        decoded = base64.urlsafe_b64decode(raw)
        assert b"<b>Bold</b>" in decoded


class TestFormatThreadContent:
    def test_basic(self):
        text_data = base64.urlsafe_b64encode(b"Thread msg body").decode()
        thread_data = {
            "messages": [
                {
                    "id": "m1",
                    "payload": {
                        "headers": [
                            {"name": "Subject", "value": "Topic"},
                            {"name": "From", "value": "alice@x.com"},
                            {"name": "Date", "value": "2026-01-01"},
                        ],
                        "mimeType": "text/plain",
                        "body": {"data": text_data},
                    },
                }
            ]
        }
        result = format_thread_content(thread_data, "t1")
        assert "Topic" in result
        assert "Thread msg body" in result

    def test_empty_thread(self):
        result = format_thread_content({"messages": []}, "t1")
        assert "No messages" in result


class TestRecipientAllowlistEnforcement:
    """The allowlist guards real sends only. A draft is never delivered, so
    creating one must not be blocked by it."""

    @staticmethod
    def _register_tools(allowed):
        captured: dict = {}

        class _Server:
            def tool(self):
                def decorator(fn):
                    captured[fn.__name__] = fn
                    return fn

                return decorator

        service = MagicMock()
        service.users().drafts().create().execute.return_value = {"id": "draft1"}
        register_gmail_tools(_Server(), service, allowed_recipients=allowed)
        return captured

    async def test_draft_skips_allowlist(self):
        tools = self._register_tools(["only@allowed.com"])
        result = await tools["draft_gmail_message"](
            subject="s", body="b", to="outsider@example.com"
        )
        assert "Draft created" in result
        assert "Blocked" not in result

    async def test_send_still_enforces_allowlist(self):
        tools = self._register_tools(["only@allowed.com"])
        result = await tools["send_gmail_message"](
            to="outsider@example.com", subject="s", body="b"
        )
        assert "Blocked" in result
        assert "draft_gmail_message" in result
