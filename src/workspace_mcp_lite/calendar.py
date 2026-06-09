import asyncio
import datetime
import json
import logging
import re
import uuid
from typing import Any

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def correct_time_format(time_str: str | None) -> str | None:
    if time_str is None:
        return None
    time_str = time_str.strip()
    if re.match(r"^\d{4}-\d{2}-\d{2}$", time_str):
        return f"{time_str}T00:00:00Z"
    return time_str


def format_attendee_details(attendees: list[dict], indent: str = "  ") -> str:
    if not attendees:
        return "None"
    lines = []
    for a in attendees:
        email = a.get("email", "")
        status = a.get("responseStatus", "needsAction")
        parts = [f"{email} ({status})"]
        if a.get("organizer"):
            parts.append("organizer")
        if a.get("optional"):
            parts.append("optional")
        lines.append(f"{indent}- {', '.join(parts)}")
    return "\n" + "\n".join(lines)


def get_meeting_link(event: dict) -> str | None:
    if event.get("hangoutLink"):
        return event["hangoutLink"]
    conf = event.get("conferenceData", {})
    for ep in conf.get("entryPoints", []):
        if ep.get("entryPointType") == "video" and ep.get("uri"):
            return ep["uri"]
    return None


def format_attachment_details(attachments: list[dict], indent: str = "  ") -> str:
    if not attachments:
        return "None"
    lines = []
    for a in attachments:
        title = a.get("title", "Untitled")
        url = a.get("fileUrl", "")
        mime = a.get("mimeType", "")
        lines.append(f"{indent}- {title} ({mime}) {url}")
    return "\n" + "\n".join(lines)


def parse_reminders(reminders_input) -> list[dict]:
    if not reminders_input:
        return []
    if isinstance(reminders_input, str):
        try:
            reminders = json.loads(reminders_input)
            if not isinstance(reminders, list):
                return []
        except json.JSONDecodeError:
            return []
    elif isinstance(reminders_input, list):
        reminders = reminders_input
    else:
        return []

    validated = []
    for r in reminders[:5]:
        if isinstance(r, dict) and "method" in r and "minutes" in r:
            validated.append({"method": r["method"], "minutes": int(r["minutes"])})
    return validated


def _build_event_body(
    summary: str | None = None,
    start_time: str | None = None,
    end_time: str | None = None,
    description: str | None = None,
    location: str | None = None,
    attendees: list | None = None,
    timezone: str | None = None,
    add_google_meet: bool | None = None,
    reminders: Any = None,
    use_default_reminders: bool | None = None,
    transparency: str | None = None,
    visibility: str | None = None,
    color_id: str | None = None,
    recurrence: list[str] | None = None,
    guests_can_modify: bool | None = None,
    guests_can_invite_others: bool | None = None,
    guests_can_see_other_guests: bool | None = None,
    event_type: str | None = None,
) -> dict[str, Any]:
    body: dict[str, Any] = {}
    if summary is not None:
        body["summary"] = summary
    if description is not None:
        body["description"] = description
    if location is not None:
        body["location"] = location

    if start_time:
        is_date = re.match(r"^\d{4}-\d{2}-\d{2}$", start_time.strip())
        if is_date:
            body["start"] = {"date": start_time.strip()}
        else:
            entry: dict[str, str] = {"dateTime": start_time}
            if timezone:
                entry["timeZone"] = timezone
            body["start"] = entry

    if end_time:
        is_date = re.match(r"^\d{4}-\d{2}-\d{2}$", end_time.strip())
        if is_date:
            body["end"] = {"date": end_time.strip()}
        else:
            entry = {"dateTime": end_time}
            if timezone:
                entry["timeZone"] = timezone
            body["end"] = entry

    if attendees is not None:
        att_list = []
        for a in attendees:
            if isinstance(a, str):
                att_list.append({"email": a})
            elif isinstance(a, dict):
                att_list.append(a)
        body["attendees"] = att_list

    if transparency is not None:
        body["transparency"] = transparency
    if visibility is not None:
        body["visibility"] = visibility
    if color_id is not None:
        body["colorId"] = color_id
    if recurrence is not None:
        body["recurrence"] = recurrence
    if guests_can_modify is not None:
        body["guestsCanModify"] = guests_can_modify
    if guests_can_invite_others is not None:
        body["guestsCanInviteOthers"] = guests_can_invite_others
    if guests_can_see_other_guests is not None:
        body["guestsCanSeeOtherGuests"] = guests_can_see_other_guests
    if event_type is not None:
        body["eventType"] = event_type

    if add_google_meet is True:
        body["conferenceData"] = {
            "createRequest": {
                "requestId": str(uuid.uuid4()),
                "conferenceSolutionKey": {"type": "hangoutsMeet"},
            }
        }
    elif add_google_meet is False:
        body["conferenceData"] = None

    parsed_reminders = parse_reminders(reminders)
    if use_default_reminders is True:
        body["reminders"] = {"useDefault": True}
    elif parsed_reminders:
        body["reminders"] = {"useDefault": False, "overrides": parsed_reminders}
    elif use_default_reminders is False:
        body["reminders"] = {"useDefault": False}

    return body


def _format_event_basic(item: dict) -> str:
    summary = item.get("summary", "No Title")
    start = item["start"].get("dateTime", item["start"].get("date"))
    end = item["end"].get("dateTime", item["end"].get("date"))
    link = item.get("htmlLink", "No Link")
    eid = item.get("id", "No ID")
    meeting = get_meeting_link(item)
    line = f'- "{summary}" (Starts: {start}, Ends: {end})'
    if meeting:
        line += f" Meeting: {meeting}"
    line += f" ID: {eid} | Link: {link}"
    return line


def _format_event_detailed(item: dict, include_attachments: bool = False) -> str:
    summary = item.get("summary", "No Title")
    start = item["start"].get("dateTime", item["start"].get("date"))
    end = item["end"].get("dateTime", item["end"].get("date"))
    link = item.get("htmlLink", "No Link")
    desc = item.get("description", "No Description")
    loc = item.get("location", "No Location")
    attendees = item.get("attendees", [])
    meeting = get_meeting_link(item)
    eid = item.get("id", "No ID")

    parts = (
        f"- Title: {summary}\n"
        f"  Starts: {start}\n"
        f"  Ends: {end}\n"
        f"  Description: {desc}\n"
        f"  Location: {loc}\n"
    )
    if meeting:
        parts += f"  Meeting Link: {meeting}\n"
    parts += f"  Attendees: {format_attendee_details(attendees, '    ')}\n"
    if include_attachments:
        atts = item.get("attachments", [])
        parts += f"  Attachments: {format_attachment_details(atts, '    ')}\n"
    parts += f"  ID: {eid} | Link: {link}"
    return parts


def _ooo_time_entry(time_str: str, timezone: str | None = None) -> dict[str, str]:
    if "T" not in time_str:
        time_str = f"{time_str}T00:00:00"
    entry: dict[str, str] = {"dateTime": time_str}
    if timezone:
        entry["timeZone"] = timezone
    return entry


# ---------------------------------------------------------------------------
# Tool registration
# ---------------------------------------------------------------------------


def register_calendar_tools(server, service) -> None:
    @server.tool()
    async def list_calendars() -> str:
        """List all calendars accessible to the user."""
        resp = await asyncio.to_thread(lambda: service.calendarList().list().execute())
        items = resp.get("items", [])
        if not items:
            return "No calendars found."
        lines = [
            f'- "{cal.get("summary", "No Summary")}"'
            f"{' (Primary)' if cal.get('primary') else ''}"
            f" (ID: {cal['id']})"
            for cal in items
        ]
        return f"Found {len(items)} calendars:\n" + "\n".join(lines)

    @server.tool()
    async def get_events(
        calendar_id: str = "primary",
        event_id: str | None = None,
        time_min: str | None = None,
        time_max: str | None = None,
        max_results: int = 25,
        query: str | None = None,
        detailed: bool = False,
        include_attachments: bool = False,
    ) -> str:
        """Get calendar events by ID or time range."""
        if event_id:
            event = await asyncio.to_thread(
                lambda: service.events().get(calendarId=calendar_id, eventId=event_id).execute()
            )
            items = [event]
        else:
            fmt_min = correct_time_format(time_min)
            if not fmt_min:
                now = datetime.datetime.now(datetime.timezone.utc)
                fmt_min = now.isoformat().replace("+00:00", "Z")
            fmt_max = correct_time_format(time_max)

            params: dict[str, Any] = {
                "calendarId": calendar_id,
                "timeMin": fmt_min,
                "maxResults": max_results,
                "singleEvents": True,
                "orderBy": "startTime",
            }
            if fmt_max:
                params["timeMax"] = fmt_max
            if query:
                params["q"] = query

            resp = await asyncio.to_thread(lambda: service.events().list(**params).execute())
            items = resp.get("items", [])

        if not items:
            return "No events found."

        if detailed:
            lines = [_format_event_detailed(e, include_attachments) for e in items]
        else:
            lines = [_format_event_basic(e) for e in items]
        return f"Retrieved {len(items)} events:\n" + "\n".join(lines)

    @server.tool()
    async def manage_event(
        action: str,
        summary: str | None = None,
        start_time: str | None = None,
        end_time: str | None = None,
        event_id: str | None = None,
        calendar_id: str = "primary",
        description: str | None = None,
        location: str | None = None,
        attendees: list | None = None,
        timezone: str | None = None,
        add_google_meet: bool | None = None,
        reminders: Any = None,
        use_default_reminders: bool | None = None,
        transparency: str | None = None,
        visibility: str | None = None,
        color_id: str | None = None,
        recurrence: list[str] | None = None,
        guests_can_modify: bool | None = None,
        guests_can_invite_others: bool | None = None,
        guests_can_see_other_guests: bool | None = None,
        response: str | None = None,
        rsvp_comment: str | None = None,
        send_updates: str | None = None,
    ) -> str:
        """Create, update, delete, or RSVP to a calendar event."""
        act = action.lower().strip()
        su = send_updates or "all"

        if act == "create":
            if not summary or not start_time or not end_time:
                raise ValueError("summary, start_time, and end_time are required for create.")
            body = _build_event_body(
                summary=summary,
                start_time=start_time,
                end_time=end_time,
                description=description,
                location=location,
                attendees=attendees,
                timezone=timezone,
                add_google_meet=add_google_meet or False,
                reminders=reminders,
                use_default_reminders=(
                    use_default_reminders if use_default_reminders is not None else True
                ),
                transparency=transparency,
                visibility=visibility,
                recurrence=recurrence,
                guests_can_modify=guests_can_modify,
                guests_can_invite_others=guests_can_invite_others,
                guests_can_see_other_guests=guests_can_see_other_guests,
            )
            conf_ver = 1 if add_google_meet else 0
            created = await asyncio.to_thread(
                lambda: (
                    service.events()
                    .insert(
                        calendarId=calendar_id,
                        body=body,
                        sendUpdates=su,
                        conferenceDataVersion=conf_ver,
                    )
                    .execute()
                )
            )
            eid = created.get("id", "")
            link = created.get("htmlLink", "")
            result = f"Event created! ID: {eid}\nLink: {link}"
            ml = get_meeting_link(created)
            if ml:
                result += f"\nMeeting: {ml}"
            return result

        elif act == "update":
            if not event_id:
                raise ValueError("event_id is required for update.")
            existing = await asyncio.to_thread(
                lambda: service.events().get(calendarId=calendar_id, eventId=event_id).execute()
            )
            body = _build_event_body(
                summary=summary,
                start_time=start_time,
                end_time=end_time,
                description=description,
                location=location,
                attendees=attendees,
                timezone=timezone,
                add_google_meet=add_google_meet,
                reminders=reminders,
                use_default_reminders=use_default_reminders,
                transparency=transparency,
                visibility=visibility,
                color_id=color_id,
                recurrence=recurrence,
                guests_can_modify=guests_can_modify,
                guests_can_invite_others=guests_can_invite_others,
                guests_can_see_other_guests=guests_can_see_other_guests,
            )
            existing.update(body)
            conf_ver = 1 if add_google_meet else 0
            updated = await asyncio.to_thread(
                lambda: (
                    service.events()
                    .update(
                        calendarId=calendar_id,
                        eventId=event_id,
                        body=existing,
                        sendUpdates=su,
                        conferenceDataVersion=conf_ver,
                    )
                    .execute()
                )
            )
            return f"Event updated! ID: {updated.get('id')}\nLink: {updated.get('htmlLink', '')}"

        elif act == "delete":
            if not event_id:
                raise ValueError("event_id is required for delete.")
            existing = await asyncio.to_thread(
                lambda: service.events().get(calendarId=calendar_id, eventId=event_id).execute()
            )
            await asyncio.to_thread(
                lambda: (
                    service.events()
                    .delete(
                        calendarId=calendar_id,
                        eventId=event_id,
                        sendUpdates=su,
                    )
                    .execute()
                )
            )
            return f"Event '{existing.get('summary', '')}' (ID: {event_id}) deleted!"

        elif act == "rsvp":
            if not event_id or not response:
                raise ValueError("event_id and response are required for rsvp.")
            existing = await asyncio.to_thread(
                lambda: service.events().get(calendarId=calendar_id, eventId=event_id).execute()
            )
            profile = await asyncio.to_thread(
                lambda: service.calendarList().get(calendarId="primary").execute()
            )
            user_email = profile.get("id", "")
            for att in existing.get("attendees", []):
                if att.get("email", "").lower() == user_email.lower() or att.get("self"):
                    att["responseStatus"] = response
                    if rsvp_comment:
                        att["comment"] = rsvp_comment
                    break
            updated = await asyncio.to_thread(
                lambda: (
                    service.events()
                    .update(
                        calendarId=calendar_id,
                        eventId=event_id,
                        body=existing,
                        sendUpdates=su,
                    )
                    .execute()
                )
            )
            return f"RSVP '{response}' sent for event '{updated.get('summary', '')}'"

        else:
            raise ValueError(f"Invalid action '{act}'. Must be create/update/delete/rsvp.")

    @server.tool()
    async def manage_out_of_office(
        action: str,
        start_time: str | None = None,
        end_time: str | None = None,
        calendar_id: str = "primary",
        event_id: str | None = None,
        summary: str | None = None,
        description: str | None = None,
        timezone: str | None = None,
        decline_mode: str | None = None,
        time_min: str | None = None,
        time_max: str | None = None,
    ) -> str:
        """Create, list, update, or delete Out of Office events."""
        act = action.lower().strip()

        if act == "create":
            if not start_time or not end_time:
                raise ValueError("start_time and end_time required for create.")
            body: dict[str, Any] = {
                "summary": summary or "Out of office",
                "eventType": "outOfOffice",
                "start": _ooo_time_entry(start_time, timezone),
                "end": _ooo_time_entry(end_time, timezone),
                "transparency": "opaque",
                "visibility": "public",
            }
            if description:
                body["description"] = description
            if decline_mode:
                body["outOfOfficeProperties"] = {"autoDeclineMode": decline_mode}
            created = await asyncio.to_thread(
                lambda: service.events().insert(calendarId=calendar_id, body=body).execute()
            )
            return f"OOO event created! ID: {created.get('id')}"

        elif act == "list":
            fmt_min = correct_time_format(time_min) or datetime.datetime.now(
                datetime.timezone.utc
            ).isoformat().replace("+00:00", "Z")
            fmt_max = correct_time_format(time_max)
            params: dict[str, Any] = {
                "calendarId": calendar_id,
                "timeMin": fmt_min,
                "singleEvents": True,
                "orderBy": "startTime",
                "eventTypes": ["outOfOffice"],
            }
            if fmt_max:
                params["timeMax"] = fmt_max
            resp = await asyncio.to_thread(lambda: service.events().list(**params).execute())
            items = resp.get("items", [])
            if not items:
                return "No OOO events found."
            lines = [_format_event_basic(e) for e in items]
            return f"Found {len(items)} OOO events:\n" + "\n".join(lines)

        elif act == "update":
            if not event_id:
                raise ValueError("event_id required for update.")
            existing = await asyncio.to_thread(
                lambda: service.events().get(calendarId=calendar_id, eventId=event_id).execute()
            )
            if summary is not None:
                existing["summary"] = summary
            if description is not None:
                existing["description"] = description
            if start_time:
                existing["start"] = _ooo_time_entry(start_time, timezone)
            if end_time:
                existing["end"] = _ooo_time_entry(end_time, timezone)
            updated = await asyncio.to_thread(
                lambda: (
                    service.events()
                    .update(
                        calendarId=calendar_id,
                        eventId=event_id,
                        body=existing,
                    )
                    .execute()
                )
            )
            return f"OOO event updated! ID: {updated.get('id')}"

        elif act == "delete":
            if not event_id:
                raise ValueError("event_id required for delete.")
            await asyncio.to_thread(
                lambda: service.events().delete(calendarId=calendar_id, eventId=event_id).execute()
            )
            return f"OOO event {event_id} deleted!"

        else:
            raise ValueError(f"Invalid action '{act}'. Must be create/list/update/delete.")

    @server.tool()
    async def manage_focus_time(
        action: str,
        start_time: str | None = None,
        end_time: str | None = None,
        calendar_id: str = "primary",
        event_id: str | None = None,
        summary: str | None = None,
        description: str | None = None,
        timezone: str | None = None,
        decline_mode: str | None = None,
        time_min: str | None = None,
        time_max: str | None = None,
    ) -> str:
        """Create, list, update, or delete Focus Time events."""
        act = action.lower().strip()

        if act == "create":
            if not start_time or not end_time:
                raise ValueError("start_time and end_time required for create.")
            start_entry: dict[str, str] = {"dateTime": start_time}
            end_entry: dict[str, str] = {"dateTime": end_time}
            if timezone:
                start_entry["timeZone"] = timezone
                end_entry["timeZone"] = timezone
            body: dict[str, Any] = {
                "summary": summary or "Focus time",
                "eventType": "focusTime",
                "start": start_entry,
                "end": end_entry,
                "transparency": "opaque",
            }
            if description:
                body["description"] = description
            if decline_mode:
                body["focusTimeProperties"] = {"autoDeclineMode": decline_mode}
            created = await asyncio.to_thread(
                lambda: service.events().insert(calendarId=calendar_id, body=body).execute()
            )
            return f"Focus time created! ID: {created.get('id')}"

        elif act == "list":
            fmt_min = correct_time_format(time_min) or datetime.datetime.now(
                datetime.timezone.utc
            ).isoformat().replace("+00:00", "Z")
            fmt_max = correct_time_format(time_max)
            params: dict[str, Any] = {
                "calendarId": calendar_id,
                "timeMin": fmt_min,
                "singleEvents": True,
                "orderBy": "startTime",
                "eventTypes": ["focusTime"],
            }
            if fmt_max:
                params["timeMax"] = fmt_max
            resp = await asyncio.to_thread(lambda: service.events().list(**params).execute())
            items = resp.get("items", [])
            if not items:
                return "No focus time events found."
            lines = [_format_event_basic(e) for e in items]
            return f"Found {len(items)} focus time events:\n" + "\n".join(lines)

        elif act == "update":
            if not event_id:
                raise ValueError("event_id required for update.")
            existing = await asyncio.to_thread(
                lambda: service.events().get(calendarId=calendar_id, eventId=event_id).execute()
            )
            if summary is not None:
                existing["summary"] = summary
            if description is not None:
                existing["description"] = description
            if start_time:
                entry = {"dateTime": start_time}
                if timezone:
                    entry["timeZone"] = timezone
                existing["start"] = entry
            if end_time:
                entry = {"dateTime": end_time}
                if timezone:
                    entry["timeZone"] = timezone
                existing["end"] = entry
            updated = await asyncio.to_thread(
                lambda: (
                    service.events()
                    .update(
                        calendarId=calendar_id,
                        eventId=event_id,
                        body=existing,
                    )
                    .execute()
                )
            )
            return f"Focus time updated! ID: {updated.get('id')}"

        elif act == "delete":
            if not event_id:
                raise ValueError("event_id required for delete.")
            await asyncio.to_thread(
                lambda: service.events().delete(calendarId=calendar_id, eventId=event_id).execute()
            )
            return f"Focus time event {event_id} deleted!"

        else:
            raise ValueError(f"Invalid action '{act}'. Must be create/list/update/delete.")

    @server.tool()
    async def query_freebusy(
        time_min: str,
        time_max: str,
        calendars: list[str] | None = None,
    ) -> str:
        """Query free/busy information for calendars."""
        cal_ids = calendars or ["primary"]
        body = {
            "timeMin": correct_time_format(time_min),
            "timeMax": correct_time_format(time_max),
            "items": [{"id": c} for c in cal_ids],
        }
        resp = await asyncio.to_thread(lambda: service.freebusy().query(body=body).execute())
        cals = resp.get("calendars", {})

        lines = []
        for cal_id, data in cals.items():
            busy = data.get("busy", [])
            if not busy:
                lines.append(f"  {cal_id}: Free")
            else:
                lines.append(f"  {cal_id}: {len(busy)} busy period(s)")
                for b in busy:
                    lines.append(f"    - {b.get('start')} to {b.get('end')}")
        return "Free/Busy:\n" + "\n".join(lines)

    @server.tool()
    async def create_calendar(
        summary: str,
        description: str | None = None,
        timezone: str | None = None,
    ) -> str:
        """Create a new Google Calendar."""
        body: dict[str, Any] = {"summary": summary}
        if description:
            body["description"] = description
        if timezone:
            body["timeZone"] = timezone
        created = await asyncio.to_thread(lambda: service.calendars().insert(body=body).execute())
        return f"Calendar created! ID: {created.get('id')}\nSummary: {created.get('summary')}"
