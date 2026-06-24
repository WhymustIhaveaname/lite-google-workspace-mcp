import asyncio
import base64
import binascii
import logging
import mimetypes
from email.message import EmailMessage
from email.policy import SMTP
from email.utils import formataddr
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, Literal

logger = logging.getLogger(__name__)

GMAIL_BATCH_SIZE = 25
GMAIL_REQUEST_DELAY = 0.1
HTML_BODY_TRUNCATE_LIMIT = 20000
RAW_BODY_TRUNCATE_LIMIT = 20000


def check_allowed_recipients(
    allowed: list[str], to: str | None, cc: str | None, bcc: str | None
) -> list[str]:
    """Return list of disallowed addresses. Empty means all OK."""
    if not allowed:
        return []
    import email.utils

    allowed_lower = {a.lower() for a in allowed}
    disallowed = []
    for field in (to, cc, bcc):
        if not field:
            continue
        for _, addr in email.utils.getaddresses([field]):
            if addr and addr.lower() not in allowed_lower:
                disallowed.append(addr)
    return disallowed


METADATA_HEADERS = [
    "Subject",
    "From",
    "To",
    "Cc",
    "Message-ID",
    "In-Reply-To",
    "References",
    "Date",
    "List-Unsubscribe",
    "Precedence",
    "List-Id",
]

LOW_VALUE_TEXT_PLACEHOLDERS = (
    "your client does not support html",
    "view this email in your browser",
    "open this email in your browser",
)
LOW_VALUE_TEXT_FOOTER_MARKERS = (
    "mailing list",
    "mailman/listinfo",
    "unsubscribe",
    "list-unsubscribe",
    "manage preferences",
)
LOW_VALUE_TEXT_HTML_DIFF_MIN = 80


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class _HTMLTextExtractor(HTMLParser):
    def __init__(self):
        super().__init__()
        self._text: list[str] = []
        self._skip = False

    def handle_starttag(self, tag, attrs):
        self._skip = tag in ("script", "style")

    def handle_endtag(self, tag):
        if tag in ("script", "style"):
            self._skip = False

    def handle_data(self, data):
        if not self._skip:
            self._text.append(data)

    def get_text(self) -> str:
        return " ".join("".join(self._text).split())


def html_to_text(html: str) -> str:
    try:
        parser = _HTMLTextExtractor()
        parser.feed(html)
        return parser.get_text()
    except Exception:
        return html


def extract_headers(payload: dict, header_names: list[str]) -> dict[str, str]:
    headers: dict[str, str] = {}
    target = {name.lower(): name for name in header_names}
    for header in payload.get("headers", []):
        key = header["name"].lower()
        if key in target:
            headers[target[key]] = header["value"]
    return headers


def extract_message_bodies(payload: dict) -> dict[str, str]:
    text_body = ""
    html_body = ""
    queue = [payload] if "parts" not in payload else list(payload.get("parts", []))
    while queue:
        part = queue.pop(0)
        mime_type = part.get("mimeType", "")
        body_data = part.get("body", {}).get("data")
        if body_data:
            try:
                decoded = base64.urlsafe_b64decode(body_data).decode("utf-8", errors="ignore")
                if mime_type == "text/plain" and not text_body:
                    text_body = decoded
                elif mime_type == "text/html" and not html_body:
                    html_body = decoded
            except Exception:
                pass
        if mime_type.startswith("multipart/") and "parts" in part:
            queue.extend(part.get("parts", []))

    if payload.get("body", {}).get("data"):
        try:
            decoded = base64.urlsafe_b64decode(payload["body"]["data"]).decode(
                "utf-8", errors="ignore"
            )
            mime_type = payload.get("mimeType", "")
            if mime_type == "text/plain" and not text_body:
                text_body = decoded
            elif mime_type == "text/html" and not html_body:
                html_body = decoded
        except Exception:
            pass

    return {"text": text_body, "html": html_body}


def extract_attachments(payload: dict) -> list[dict[str, Any]]:
    attachments: list[dict[str, Any]] = []

    def search_parts(part: dict) -> None:
        if part.get("filename") and part.get("body", {}).get("attachmentId"):
            attachments.append(
                {
                    "filename": part["filename"],
                    "mimeType": part.get("mimeType", "application/octet-stream"),
                    "size": part.get("body", {}).get("size", 0),
                    "attachmentId": part["body"]["attachmentId"],
                }
            )
        for subpart in part.get("parts", []):
            search_parts(subpart)

    search_parts(payload)
    return attachments


def format_body_content(
    text_body: str,
    html_body: str,
    body_format: Literal["text", "html"] = "text",
) -> str:
    if body_format == "html":
        html_stripped = html_body.strip()
        if html_stripped:
            if len(html_stripped) > HTML_BODY_TRUNCATE_LIMIT:
                return html_stripped[:HTML_BODY_TRUNCATE_LIMIT] + "\n\n[Content truncated...]"
            return html_stripped
        text_stripped = text_body.strip()
        return text_stripped if text_stripped else "[No readable content found]"

    text_stripped = text_body.strip()
    html_stripped = html_body.strip()
    html_text = html_to_text(html_stripped).strip() if html_stripped else ""

    plain_lower = " ".join(text_stripped.split()).lower()
    html_lower = " ".join(html_text.split()).lower()
    plain_is_low_value = plain_lower and (
        any(marker in plain_lower for marker in LOW_VALUE_TEXT_PLACEHOLDERS)
        or (
            any(marker in plain_lower for marker in LOW_VALUE_TEXT_FOOTER_MARKERS)
            and len(html_lower) >= len(plain_lower) + LOW_VALUE_TEXT_HTML_DIFF_MIN
        )
    )

    use_html = html_text and (not text_stripped or "<!--" in text_stripped or plain_is_low_value)

    if use_html:
        if len(html_text) > HTML_BODY_TRUNCATE_LIMIT:
            return html_text[:HTML_BODY_TRUNCATE_LIMIT] + "\n\n[Content truncated...]"
        return html_text
    elif text_stripped:
        return text_body
    else:
        return "[No readable content found]"


def format_message_header_lines(
    headers: dict[str, str], message_id: str | None = None
) -> list[str]:
    lines: list[str] = []
    if message_id:
        lines.append(f"Message ID: {message_id}")
    lines.extend(
        [
            f"Subject: {headers.get('Subject', '(no subject)')}",
            f"From: {headers.get('From', '(unknown sender)')}",
            f"Date: {headers.get('Date', '(unknown date)')}",
        ]
    )
    for key in (
        "Message-ID",
        "In-Reply-To",
        "References",
        "To",
        "Cc",
        "List-Unsubscribe",
        "Precedence",
        "List-Id",
    ):
        val = headers.get(key, "")
        if val:
            lines.append(f"{key}: {val}")
    return lines


def _generate_gmail_web_url(item_id: str) -> str:
    return f"https://mail.google.com/mail/u/0/#all/{item_id}"


def format_gmail_results(messages: list, query: str, next_page_token: str | None = None) -> str:
    if not messages:
        return f"No messages found for query: '{query}'"

    lines = [f"Found {len(messages)} messages matching '{query}':", "", "MESSAGES:"]
    for i, msg in enumerate(messages, 1):
        if not msg or not isinstance(msg, dict):
            lines.extend([f"  {i}. Invalid message data", ""])
            continue
        mid = msg.get("id", "unknown")
        tid = msg.get("threadId", "unknown")
        lines.extend(
            [
                f"  {i}. Message ID: {mid}",
                f"     Web Link: {_generate_gmail_web_url(mid) if mid != 'unknown' else 'N/A'}",
                f"     Thread ID: {tid}",
                f"     Thread Link: {_generate_gmail_web_url(tid) if tid != 'unknown' else 'N/A'}",
                "",
            ]
        )

    lines.extend(
        [
            "USAGE:",
            "  - Pass Message IDs as a list to get_gmail_messages_content_batch()",
            "  - Pass Thread IDs to get_gmail_thread_content() or "
            "get_gmail_threads_content_batch()",
        ]
    )
    if next_page_token:
        lines.append(
            f"\nPAGINATION: call search_gmail_messages with page_token='{next_page_token}'"
        )
    return "\n".join(lines)


def _decode_raw_mime(raw_data: str) -> str:
    if not raw_data:
        return "[No raw content found]"
    padded = raw_data + "=" * (-len(raw_data) % 4)
    try:
        decoded = base64.urlsafe_b64decode(padded).decode("utf-8", errors="replace")
    except (binascii.Error, ValueError) as exc:
        return f"[Failed to decode raw MIME: {exc}]"
    if len(decoded) > RAW_BODY_TRUNCATE_LIMIT:
        return decoded[:RAW_BODY_TRUNCATE_LIMIT] + "\n\n[Content truncated...]"
    return decoded


def format_thread_content(
    thread_data: dict,
    thread_id: str,
    body_format: Literal["text", "html", "raw"] = "text",
    raw_contents: dict[str, str] | None = None,
) -> str:
    messages = thread_data.get("messages", [])
    if not messages:
        return f"No messages found in thread '{thread_id}'."

    first_headers = {
        h["name"]: h["value"] for h in messages[0].get("payload", {}).get("headers", [])
    }
    thread_subject = first_headers.get("Subject", "(no subject)")

    lines = [
        f"Thread ID: {thread_id}",
        f"Subject: {thread_subject}",
        f"Messages: {len(messages)}",
        "",
    ]

    for i, message in enumerate(messages, 1):
        payload = message.get("payload", {})
        headers = {h["name"]: h["value"] for h in payload.get("headers", [])}

        if body_format == "raw":
            body_data = (raw_contents or {}).get(message.get("id", ""), "[No raw content found]")
            body_label = "RAW MIME"
        else:
            bodies = extract_message_bodies(payload)
            body_data = format_body_content(
                bodies["text"], bodies["html"], body_format=body_format
            )
            body_label = "BODY"

        attachments = extract_attachments(payload)
        mid = message.get("id", "")

        lines.extend(
            [
                f"=== Message {i} ===",
                f"From: {headers.get('From', '(unknown)')}",
                f"Date: {headers.get('Date', '(unknown)')}",
            ]
        )
        for key in ("Message-ID", "In-Reply-To", "References"):
            if headers.get(key):
                lines.append(f"{key}: {headers[key]}")
        if headers.get("Subject", "") != thread_subject:
            lines.append(f"Subject: {headers.get('Subject', '')}")

        if body_format == "raw":
            lines.extend(["", f"--- {body_label} ---", body_data, ""])
        else:
            lines.extend(["", body_data, ""])

        if attachments:
            lines.append("--- ATTACHMENTS ---")
            for j, att in enumerate(attachments, 1):
                size_kb = att["size"] / 1024
                lines.append(
                    f"{j}. {att['filename']} ({att['mimeType']}, {size_kb:.1f} KB)\n"
                    f"   Attachment ID: {att['attachmentId']}\n"
                    f"   Use get_gmail_attachment_content(message_id='{mid}', "
                    f"attachment_id='{att['attachmentId']}') to download"
                )
            lines.append("")

    return "\n".join(lines)


def prepare_gmail_message(
    subject: str,
    body: str,
    to: str | None = None,
    cc: str | None = None,
    bcc: str | None = None,
    thread_id: str | None = None,
    in_reply_to: str | None = None,
    references: str | None = None,
    body_format: Literal["plain", "html"] = "plain",
    from_email: str | None = None,
    from_name: str | None = None,
    attachments: list[dict[str, str]] | None = None,
) -> tuple[str, str | None, int, list[str]]:
    reply_subject = subject
    if in_reply_to and not subject.lower().startswith("re:"):
        reply_subject = f"Re: {subject}"

    attached_count = 0
    attachment_errors: list[str] = []
    message = EmailMessage(policy=SMTP)
    message["Subject"] = reply_subject

    if from_email:
        if from_name:
            safe_name = from_name.replace("\r", "").replace("\n", "").replace("\x00", "")
            message["From"] = formataddr((safe_name, from_email))
        else:
            message["From"] = from_email
    if to:
        message["To"] = to
    if cc:
        message["Cc"] = cc
    if bcc:
        message["Bcc"] = bcc
    if in_reply_to:
        message["In-Reply-To"] = in_reply_to
    if references:
        message["References"] = references

    if body_format == "html":
        plain_body = html_to_text(body).strip()
        message.set_content(plain_body)
        message.add_alternative(body, subtype="html")
    else:
        message.set_content(body)

    for attachment in attachments or []:
        file_path = attachment.get("path")
        filename = attachment.get("filename")
        content_base64 = attachment.get("content")
        mime_type = attachment.get("mime_type")

        try:
            if file_path:
                path_obj = Path(file_path)
                if not path_obj.exists():
                    attachment_errors.append(f"File not found: {file_path}")
                    continue
                file_data = path_obj.read_bytes()
                if not filename:
                    filename = path_obj.name
                if not mime_type:
                    mime_type, _ = mimetypes.guess_type(str(path_obj))
                    mime_type = mime_type or "application/octet-stream"
            elif content_base64:
                if not filename:
                    attachment_errors.append("Missing filename for base64 attachment")
                    continue
                file_data = base64.b64decode(content_base64)
                mime_type = mime_type or "application/octet-stream"
            else:
                attachment_errors.append("Attachment missing path and content")
                continue

            safe_filename = (
                (filename or "attachment").replace("\r", "").replace("\n", "").replace("\x00", "")
            ) or "attachment"
            main_type, sub_type = (
                mime_type.split("/", 1)
                if mime_type and "/" in mime_type
                else ("application", "octet-stream")
            )
            message.add_attachment(
                file_data, maintype=main_type, subtype=sub_type, filename=safe_filename
            )
            attached_count += 1
        except (binascii.Error, ValueError) as e:
            attachment_errors.append(f"Decode error for {filename or file_path}: {e}")
        except Exception as e:
            attachment_errors.append(f"Attach error for {filename or file_path}: {e}")

    raw_message = base64.urlsafe_b64encode(message.as_bytes(policy=SMTP)).decode()
    return raw_message, thread_id, attached_count, attachment_errors


# ---------------------------------------------------------------------------
# Tool registration
# ---------------------------------------------------------------------------


def register_gmail_tools(server, service, allowed_recipients: list[str] | None = None) -> None:
    _allowed = allowed_recipients or []

    @server.tool()
    async def search_gmail_messages(
        query: str,
        page_size: int = 10,
        page_token: str | None = None,
    ) -> str:
        """Search Gmail messages by query. Returns message IDs and thread IDs."""
        params: dict[str, Any] = {"userId": "me", "q": query, "maxResults": page_size}
        if page_token:
            params["pageToken"] = page_token
        response = await asyncio.to_thread(service.users().messages().list(**params).execute)
        if response is None:
            return f"No response from Gmail API for query: '{query}'"
        messages = response.get("messages") or []
        npt = response.get("nextPageToken")
        return format_gmail_results(messages, query, npt)

    @server.tool()
    async def get_gmail_message_content(
        message_id: str,
        body_format: Literal["text", "html", "raw"] = "text",
    ) -> str:
        """Get the full content of a Gmail message."""
        meta = await asyncio.to_thread(
            service.users()
            .messages()
            .get(
                userId="me",
                id=message_id,
                format="metadata",
                metadataHeaders=METADATA_HEADERS,
            )
            .execute
        )
        headers = extract_headers(meta.get("payload", {}), METADATA_HEADERS)

        if body_format == "raw":
            raw_msg = await asyncio.to_thread(
                service.users().messages().get(userId="me", id=message_id, format="raw").execute
            )
            lines = format_message_header_lines(headers)
            lines.append(f"\n--- RAW MIME ---\n{_decode_raw_mime(raw_msg.get('raw', ''))}")
            return "\n".join(lines)

        full = await asyncio.to_thread(
            service.users().messages().get(userId="me", id=message_id, format="full").execute
        )
        payload = full.get("payload", {})
        bodies = extract_message_bodies(payload)
        body_data = format_body_content(bodies["text"], bodies["html"], body_format=body_format)
        attachments = extract_attachments(payload)

        lines = format_message_header_lines(headers)
        lines.append(f"\n--- BODY ---\n{body_data or '[No text/plain body found]'}")
        if attachments:
            lines.append("\n--- ATTACHMENTS ---")
            for i, att in enumerate(attachments, 1):
                size_kb = att["size"] / 1024
                lines.append(
                    f"{i}. {att['filename']} ({att['mimeType']}, {size_kb:.1f} KB)\n"
                    f"   Attachment ID: {att['attachmentId']}\n"
                    f"   Use get_gmail_attachment_content(message_id='{message_id}', "
                    f"attachment_id='{att['attachmentId']}') to download"
                )
        return "\n".join(lines)

    @server.tool()
    async def get_gmail_messages_content_batch(
        message_ids: list[str],
        format: Literal["full", "metadata"] = "full",
        body_format: Literal["text", "html", "raw"] = "text",
    ) -> str:
        """Get the content of multiple Gmail messages in batch."""
        if not message_ids:
            raise ValueError("No message IDs provided")

        output: list[str] = []
        for chunk_start in range(0, len(message_ids), GMAIL_BATCH_SIZE):
            chunk = message_ids[chunk_start : chunk_start + GMAIL_BATCH_SIZE]
            for mid in chunk:
                try:
                    is_meta = format == "metadata" or body_format == "raw"
                    msg_format = "metadata" if is_meta else "full"
                    get_kwargs: dict[str, Any] = {
                        "userId": "me",
                        "id": mid,
                        "format": msg_format,
                    }
                    if msg_format == "metadata":
                        get_kwargs["metadataHeaders"] = METADATA_HEADERS
                    msg = await asyncio.to_thread(
                        service.users().messages().get(**get_kwargs).execute
                    )
                    payload = msg.get("payload", {})
                    headers = extract_headers(payload, METADATA_HEADERS)

                    if format == "metadata":
                        msg_out = "\n".join(format_message_header_lines(headers, message_id=mid))
                        msg_out += f"\nWeb Link: {_generate_gmail_web_url(mid)}\n"
                    else:
                        if body_format == "raw":
                            raw_msg = await asyncio.to_thread(
                                service.users()
                                .messages()
                                .get(userId="me", id=mid, format="raw")
                                .execute
                            )
                            body_data = _decode_raw_mime(raw_msg.get("raw", ""))
                            body_label = "RAW MIME"
                        else:
                            bodies = extract_message_bodies(payload)
                            body_data = format_body_content(
                                bodies["text"], bodies["html"], body_format=body_format
                            )
                            body_label = "BODY"

                        msg_out = "\n".join(format_message_header_lines(headers, message_id=mid))
                        msg_out += f"\nWeb Link: {_generate_gmail_web_url(mid)}\n"
                        msg_out += f"\n--- {body_label} ---\n{body_data}\n"

                        attachments = extract_attachments(payload)
                        if attachments:
                            msg_out += "\n--- ATTACHMENTS ---\n"
                            for i, att in enumerate(attachments, 1):
                                size_kb = att["size"] / 1024
                                msg_out += (
                                    f"{i}. {att['filename']} "
                                    f"({att['mimeType']}, {size_kb:.1f} KB)\n"
                                    f"   ID: {att['attachmentId']}\n"
                                )
                    output.append(msg_out)
                except Exception as e:
                    output.append(f"Message {mid}: {e}\n")
                await asyncio.sleep(GMAIL_REQUEST_DELAY)

        return f"Retrieved {len(message_ids)} messages:\n\n" + "\n---\n\n".join(output)

    @server.tool()
    async def get_gmail_thread_content(
        thread_id: str,
        body_format: Literal["text", "html", "raw"] = "text",
    ) -> str:
        """Get the complete content of a Gmail thread."""
        thread = await asyncio.to_thread(
            service.users().threads().get(userId="me", id=thread_id, format="full").execute
        )
        raw_contents = None
        if body_format == "raw":
            mids = [m["id"] for m in thread.get("messages", []) if m.get("id")]
            raw_contents = {}
            for mid in mids:
                raw_msg = await asyncio.to_thread(
                    service.users().messages().get(userId="me", id=mid, format="raw").execute
                )
                raw_contents[mid] = _decode_raw_mime(raw_msg.get("raw", ""))
                await asyncio.sleep(GMAIL_REQUEST_DELAY)
        return format_thread_content(
            thread, thread_id, body_format=body_format, raw_contents=raw_contents
        )

    @server.tool()
    async def get_gmail_threads_content_batch(
        thread_ids: list[str],
        body_format: Literal["text", "html", "raw"] = "text",
    ) -> str:
        """Get the content of multiple Gmail threads."""
        if not thread_ids:
            raise ValueError("No thread IDs provided")

        output: list[str] = []
        for tid in thread_ids:
            try:
                thread = await asyncio.to_thread(
                    service.users().threads().get(userId="me", id=tid, format="full").execute
                )
                raw_contents = None
                if body_format == "raw":
                    mids = [m["id"] for m in thread.get("messages", []) if m.get("id")]
                    raw_contents = {}
                    for mid in mids:
                        raw_msg = await asyncio.to_thread(
                            service.users()
                            .messages()
                            .get(userId="me", id=mid, format="raw")
                            .execute
                        )
                        raw_contents[mid] = _decode_raw_mime(raw_msg.get("raw", ""))
                        await asyncio.sleep(GMAIL_REQUEST_DELAY)
                output.append(
                    format_thread_content(
                        thread, tid, body_format=body_format, raw_contents=raw_contents
                    )
                )
            except Exception as e:
                output.append(f"Thread {tid}: {e}\n")
            await asyncio.sleep(GMAIL_REQUEST_DELAY)

        return f"Retrieved {len(thread_ids)} threads:\n\n" + "\n---\n\n".join(output)

    @server.tool()
    async def get_gmail_attachment_content(
        message_id: str,
        attachment_id: str,
        return_base64: bool = False,
    ) -> str:
        """Download a Gmail attachment."""
        attachment = await asyncio.to_thread(
            service.users()
            .messages()
            .attachments()
            .get(userId="me", messageId=message_id, id=attachment_id)
            .execute
        )
        data = attachment.get("data", "")
        size = attachment.get("size", 0)

        msg = await asyncio.to_thread(
            service.users()
            .messages()
            .get(
                userId="me",
                id=message_id,
                format="metadata",
                metadataHeaders=["Subject"],
            )
            .execute
        )
        filename = "attachment"
        mime_type = "application/octet-stream"
        for part in _iter_parts(msg.get("payload", {})):
            if part.get("body", {}).get("attachmentId") == attachment_id:
                filename = part.get("filename", filename)
                mime_type = part.get("mimeType", mime_type)
                break

        result = f"Attachment: {filename}\nMIME Type: {mime_type}\nSize: {size / 1024:.1f} KB\n"
        if return_base64:
            std_b64 = base64.b64encode(base64.urlsafe_b64decode(data + "==")).decode()
            result += f"\n--- BASE64 CONTENT ---\n{std_b64}\n"
        return result

    @server.tool()
    async def send_gmail_message(
        to: str,
        subject: str,
        body: str,
        body_format: Literal["plain", "html"] = "plain",
        cc: str | None = None,
        bcc: str | None = None,
        from_name: str | None = None,
        from_email: str | None = None,
        thread_id: str | None = None,
        in_reply_to: str | None = None,
        references: str | None = None,
        attachments: list[dict[str, str]] | None = None,
    ) -> str:
        """Send an email via Gmail. Supports replies and attachments."""
        bad = check_allowed_recipients(_allowed, to, cc, bcc)
        if bad:
            return f"Blocked: recipients not in allowed list: {', '.join(bad)}"
        raw, tid, count, errors = prepare_gmail_message(
            subject=subject,
            body=body,
            to=to,
            cc=cc,
            bcc=bcc,
            thread_id=thread_id,
            in_reply_to=in_reply_to,
            references=references,
            body_format=body_format,
            from_email=from_email,
            from_name=from_name,
            attachments=attachments,
        )
        send_body: dict[str, Any] = {"raw": raw}
        if tid:
            send_body["threadId"] = tid

        sent = await asyncio.to_thread(
            service.users().messages().send(userId="me", body=send_body).execute
        )
        mid = sent.get("id")
        if count > 0:
            return f"Email sent with {count} attachment(s)! Message ID: {mid}"
        return f"Email sent! Message ID: {mid}"

    @server.tool()
    async def draft_gmail_message(
        subject: str,
        body: str,
        body_format: Literal["plain", "html"] = "plain",
        to: str | None = None,
        cc: str | None = None,
        bcc: str | None = None,
        from_name: str | None = None,
        from_email: str | None = None,
        thread_id: str | None = None,
        in_reply_to: str | None = None,
        references: str | None = None,
        attachments: list[dict[str, str]] | None = None,
    ) -> str:
        """Create a draft email in Gmail."""
        # Drafts are never delivered, so the recipient allowlist (a guard
        # against accidental sends) does not apply here. It is enforced only
        # at actual send time, in send_gmail_message.
        raw, tid, count, errors = prepare_gmail_message(
            subject=subject,
            body=body,
            to=to,
            cc=cc,
            bcc=bcc,
            thread_id=thread_id,
            in_reply_to=in_reply_to,
            references=references,
            body_format=body_format,
            from_email=from_email,
            from_name=from_name,
            attachments=attachments,
        )
        draft_body: dict[str, Any] = {"message": {"raw": raw}}
        if tid:
            draft_body["message"]["threadId"] = tid

        draft = await asyncio.to_thread(
            service.users().drafts().create(userId="me", body=draft_body).execute
        )
        draft_id = draft.get("id")
        if count > 0:
            return f"Draft created with {count} attachment(s)! Draft ID: {draft_id}"
        return f"Draft created! Draft ID: {draft_id}"

    @server.tool()
    async def list_gmail_labels() -> str:
        """List all labels in the Gmail account."""
        response = await asyncio.to_thread(service.users().labels().list(userId="me").execute)
        labels = response.get("labels", [])
        if not labels:
            return "No labels found."

        system_labels = [lb for lb in labels if lb.get("type") == "system"]
        user_labels = [lb for lb in labels if lb.get("type") != "system"]

        lines = [f"Found {len(labels)} labels:", ""]
        if system_labels:
            lines.append("SYSTEM LABELS:")
            for label in system_labels:
                lines.append(f"  - {label['name']} (ID: {label['id']})")
            lines.append("")
        if user_labels:
            lines.append("USER LABELS:")
            for label in user_labels:
                lines.append(f"  - {label['name']} (ID: {label['id']})")
        return "\n".join(lines)

    @server.tool()
    async def manage_gmail_label(
        action: Literal["create", "update", "delete"],
        name: str | None = None,
        label_id: str | None = None,
        label_list_visibility: Literal["labelShow", "labelHide"] = "labelShow",
        message_list_visibility: Literal["show", "hide"] = "show",
    ) -> str:
        """Create, update, or delete a Gmail label."""
        if action == "create" and not name:
            raise ValueError("Label name is required for create action.")
        if action in ("update", "delete") and not label_id:
            raise ValueError("Label ID is required for update and delete actions.")

        if action == "create":
            label_obj = {
                "name": name,
                "labelListVisibility": label_list_visibility,
                "messageListVisibility": message_list_visibility,
            }
            created = await asyncio.to_thread(
                service.users().labels().create(userId="me", body=label_obj).execute
            )
            return f"Label created! Name: {created['name']}, ID: {created['id']}"
        elif action == "update":
            current = await asyncio.to_thread(
                service.users().labels().get(userId="me", id=label_id).execute
            )
            label_obj = {
                "id": label_id,
                "name": name if name is not None else current["name"],
                "labelListVisibility": label_list_visibility,
                "messageListVisibility": message_list_visibility,
            }
            updated = await asyncio.to_thread(
                service.users().labels().update(userId="me", id=label_id, body=label_obj).execute
            )
            return f"Label updated! Name: {updated['name']}, ID: {updated['id']}"
        else:
            label = await asyncio.to_thread(
                service.users().labels().get(userId="me", id=label_id).execute
            )
            await asyncio.to_thread(
                service.users().labels().delete(userId="me", id=label_id).execute
            )
            return f"Label '{label['name']}' (ID: {label_id}) deleted!"

    @server.tool()
    async def list_gmail_filters() -> str:
        """List all Gmail filters."""
        response = await asyncio.to_thread(
            service.users().settings().filters().list(userId="me").execute
        )
        filters = response.get("filter") or response.get("filters") or []
        if not filters:
            return "No filters found."

        lines = [f"Found {len(filters)} filters:", ""]
        for f in filters:
            fid = f.get("id", "(no id)")
            criteria = f.get("criteria", {})
            action = f.get("action", {})
            lines.append(f"Filter ID: {fid}")
            lines.append("  Criteria:")
            for key in ("from", "to", "subject", "query", "negatedQuery"):
                if criteria.get(key):
                    lines.append(f"    {key}: {criteria[key]}")
            lines.append("  Actions:")
            if action.get("addLabelIds"):
                lines.append(f"    Add labels: {', '.join(action['addLabelIds'])}")
            if action.get("removeLabelIds"):
                lines.append(f"    Remove labels: {', '.join(action['removeLabelIds'])}")
            if action.get("forward"):
                lines.append(f"    Forward to: {action['forward']}")
            lines.append("")
        return "\n".join(lines).rstrip()

    @server.tool()
    async def manage_gmail_filter(
        action: Literal["create", "delete"],
        criteria: dict[str, Any] | None = None,
        filter_action: dict[str, Any] | None = None,
        filter_id: str | None = None,
    ) -> str:
        """Create or delete a Gmail filter."""
        if action == "create":
            if not criteria or not filter_action:
                raise ValueError("criteria and filter_action are required for create.")
            body = {"criteria": criteria, "action": filter_action}
            created = await asyncio.to_thread(
                service.users().settings().filters().create(userId="me", body=body).execute
            )
            return f"Filter created! Filter ID: {created.get('id', '(unknown)')}"
        elif action == "delete":
            if not filter_id:
                raise ValueError("filter_id is required for delete.")
            await asyncio.to_thread(
                service.users().settings().filters().delete(userId="me", id=filter_id).execute
            )
            return f"Filter {filter_id} deleted!"
        else:
            raise ValueError(f"Invalid action '{action}'. Must be 'create' or 'delete'.")

    @server.tool()
    async def modify_gmail_message_labels(
        message_id: str,
        add_label_ids: list[str] | None = None,
        remove_label_ids: list[str] | None = None,
    ) -> str:
        """Add or remove labels from a Gmail message."""
        if not add_label_ids and not remove_label_ids:
            raise ValueError("At least one of add_label_ids or remove_label_ids must be provided.")
        body: dict[str, Any] = {}
        if add_label_ids:
            body["addLabelIds"] = add_label_ids
        if remove_label_ids:
            body["removeLabelIds"] = remove_label_ids
        await asyncio.to_thread(
            service.users().messages().modify(userId="me", id=message_id, body=body).execute
        )
        actions = []
        if add_label_ids:
            actions.append(f"Added: {', '.join(add_label_ids)}")
        if remove_label_ids:
            actions.append(f"Removed: {', '.join(remove_label_ids)}")
        return f"Message {message_id} labels updated! {'; '.join(actions)}"

    @server.tool()
    async def batch_modify_gmail_message_labels(
        message_ids: list[str],
        add_label_ids: list[str] | None = None,
        remove_label_ids: list[str] | None = None,
    ) -> str:
        """Add or remove labels from multiple Gmail messages."""
        if not add_label_ids and not remove_label_ids:
            raise ValueError("At least one of add_label_ids or remove_label_ids must be provided.")
        body: dict[str, Any] = {"ids": message_ids}
        if add_label_ids:
            body["addLabelIds"] = add_label_ids
        if remove_label_ids:
            body["removeLabelIds"] = remove_label_ids
        await asyncio.to_thread(
            service.users().messages().batchModify(userId="me", body=body).execute
        )
        actions = []
        if add_label_ids:
            actions.append(f"Added: {', '.join(add_label_ids)}")
        if remove_label_ids:
            actions.append(f"Removed: {', '.join(remove_label_ids)}")
        return f"Labels updated for {len(message_ids)} messages: {'; '.join(actions)}"


def _iter_parts(payload: dict):
    yield payload
    for part in payload.get("parts", []):
        yield from _iter_parts(part)
