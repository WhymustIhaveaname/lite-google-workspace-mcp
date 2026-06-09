from workspace_mcp_lite.calendar import (
    correct_time_format,
    format_attachment_details,
    format_attendee_details,
    get_meeting_link,
    parse_reminders,
)


class TestCorrectTimeFormat:
    def test_date_only(self):
        result = correct_time_format("2026-06-15")
        assert result == "2026-06-15T00:00:00Z"

    def test_full_rfc3339(self):
        result = correct_time_format("2026-06-15T10:00:00Z")
        assert result == "2026-06-15T10:00:00Z"

    def test_none(self):
        assert correct_time_format(None) is None

    def test_with_offset(self):
        result = correct_time_format("2026-06-15T10:00:00-04:00")
        assert result == "2026-06-15T10:00:00-04:00"


class TestFormatAttendeeDetails:
    def test_with_attendees(self):
        attendees = [
            {"email": "a@x.com", "responseStatus": "accepted"},
            {"email": "b@x.com", "responseStatus": "declined", "organizer": True},
        ]
        result = format_attendee_details(attendees)
        assert "a@x.com" in result
        assert "accepted" in result
        assert "organizer" in result

    def test_empty(self):
        assert format_attendee_details([]) == "None"

    def test_optional_flag(self):
        att = {"email": "c@x.com", "responseStatus": "tentative", "optional": True}
        result = format_attendee_details([att])
        assert "optional" in result


class TestGetMeetingLink:
    def test_hangout_link(self):
        event = {"hangoutLink": "https://meet.google.com/abc-def"}
        assert get_meeting_link(event) == "https://meet.google.com/abc-def"

    def test_conference_data(self):
        event = {
            "conferenceData": {
                "entryPoints": [{"entryPointType": "video", "uri": "https://meet.google.com/xyz"}]
            }
        }
        assert "meet.google.com" in get_meeting_link(event)

    def test_no_meeting(self):
        assert get_meeting_link({}) is None

    def test_prefers_hangout_link(self):
        event = {
            "hangoutLink": "https://meet.google.com/hangout",
            "conferenceData": {
                "entryPoints": [{"entryPointType": "video", "uri": "https://meet.google.com/conf"}]
            },
        }
        assert get_meeting_link(event) == "https://meet.google.com/hangout"


class TestFormatAttachmentDetails:
    def test_with_attachments(self):
        atts = [
            {
                "title": "doc.pdf",
                "fileUrl": "https://drive.google.com/x",
                "mimeType": "application/pdf",
            },
        ]
        result = format_attachment_details(atts)
        assert "doc.pdf" in result
        assert "drive.google.com" in result

    def test_empty(self):
        assert format_attachment_details([]) == "None"


class TestParseReminders:
    def test_valid_list(self):
        result = parse_reminders([{"method": "popup", "minutes": 10}])
        assert len(result) == 1
        assert result[0]["method"] == "popup"

    def test_json_string(self):
        result = parse_reminders('[{"method": "email", "minutes": 30}]')
        assert len(result) == 1

    def test_invalid_string(self):
        assert parse_reminders("not json") == []

    def test_none(self):
        assert parse_reminders(None) == []

    def test_max_five(self):
        items = [{"method": "popup", "minutes": i} for i in range(10)]
        result = parse_reminders(items)
        assert len(result) == 5
