import json
import sys
from datetime import datetime
from adr_commands import REQUIRED_SECTIONS, is_maintainer, AdrStatus
from adr_parser import parse_comment
from adr_state import create_empty_state, load_state, save_state
from adr_template import inject_sections

STATE_FILE = "adr_state.json"
BOT_OUTPUT = "bot_output.json"


def bot_error(message: str, missing=None):
    payload = {
        "status": "error",
        "message": message,
        "details": {}
    }
    if missing:
        payload["details"]["missing"] = missing
    with open(BOT_OUTPUT, "w") as f:
        json.dump(payload, f, indent=2)
    sys.exit(0)


def bot_success(message: str, adr_file: str = None):
    payload = {
        "status": "success",
        "message": message,
        "adr_file": adr_file
    }
    with open(BOT_OUTPUT, "w") as f:
        json.dump(payload, f, indent=2)


def adr_filename_from_state(state: dict) -> str:
    approved_at = state["state"].get("approved_at")
    if approved_at:
        dt = datetime.fromisoformat(approved_at.replace("Z", "+00:00"))
    else:
        dt = datetime.utcnow()
    return f"ADR-{dt.strftime('%Y%m%d-%H%M%S')}.md"


def main(input_file: str):
    with open(input_file, "r") as f:
        payload = json.load(f)

    comments = payload["comments"]
    meta = payload["meta"]

    try:
        state = load_state(STATE_FILE)
    except FileNotFoundError:
        state = create_empty_state(meta)

    approve_requested = False
    approver = None
    approve_time = None

    for c in comments:
        parsed = parse_comment(c["body"])
        if not parsed:
            continue

        action = parsed["action"]
        section = parsed["section"]
        content = parsed["content"]

        if action in {"approve", "reject"}:
            if not is_maintainer(c["author_role"]):
                bot_error(f"User @{c['author']} is not allowed to execute /adr {action}")

        if action == "fill":
            if not section or not content or not content.strip():
                bot_error("/adr fill requires a section and non-empty content")
            state["sections"][section]["content"] = content.strip()

        elif action == "append":
            if not section or not content or not content.strip():
                bot_error("/adr append requires a section and non-empty content")
            cur = state["sections"][section]["content"]
            state["sections"][section]["content"] = (
                cur + "\n\n" + content.strip() if cur else content.strip()
            )

        elif action == "approve":
            approve_requested = True
            approver = c["author"]
            approve_time = c["created_at"]

        elif action == "reject":
            state["state"]["status"] = AdrStatus.REJECTED.value
            save_state(state, STATE_FILE)
            bot_success("ADR rejected")
            return

    if approve_requested:
        non_empty = [
            s for s, v in state["sections"].items()
            if v["content"].strip()
        ]
        if not non_empty:
            bot_error(
                "Cannot approve ADR: ADR is empty",
                missing=list(REQUIRED_SECTIONS)
            )

        missing = [
            s for s in REQUIRED_SECTIONS
            if not state["sections"][s]["content"].strip()
        ]
        if missing:
            bot_error(
                "Cannot approve ADR: missing required sections",
                missing=missing
            )

        state["state"]["status"] = AdrStatus.APPROVED.value
        state["state"]["approved_by"] = approver
        state["state"]["approved_at"] = approve_time

        save_state(state, STATE_FILE)

        with open("adr_template.md", "r") as f:
            template = f.read()

        body = inject_sections(template, state)
        filename = adr_filename_from_state(state)
        path = f"docs/adr/{filename}"

        with open(path, "w") as f:
            f.write(body)

        bot_success("ADR approved successfully", path)
        return

    save_state(state, STATE_FILE)


if __name__ == "__main__":
    main(sys.argv[1])
