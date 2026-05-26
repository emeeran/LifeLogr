import json
import re
from pathlib import Path

# Paths
log_dir = Path(
    "/home/em/.gemini/antigravity-cli/brain/e138153a-122b-4a7c-81f1-0978913669de/.system_generated/logs"
)
transcript_path = log_dir / "transcript_full.jsonl"
output_path = Path("/home/em/code/wip/diary/agy_conv_230526.md")

if not transcript_path.exists():
    # Fallback to truncated transcript if full is not found
    transcript_path = log_dir / "transcript.jsonl"

markdown_lines = [
    "# Antigravity Pair Programming Conversation Transcript",
    "",
    "**Conversation ID:** `e138153a-122b-4a7c-81f1-0978913669de`  ",
    "**Date:** 2026-05-23/24  ",
    "**Topic:** Google Drive Sync & Backup Integration in Diarilinux",
    "",
    "---",
    "",
]

try:
    with open(transcript_path, "r", encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            try:
                data = json.loads(line)
            except Exception:
                continue

            source = data.get("source")
            step_type = data.get("type")
            content = data.get("content", "")

            # Process User input
            if source == "USER_EXPLICIT" and step_type == "USER_INPUT":
                # Clean up <USER_REQUEST> tags and metadata
                cleaned = re.sub(r"<USER_REQUEST>\s*", "", content)
                cleaned = re.sub(r"\s*</USER_REQUEST>", "", cleaned)
                cleaned = re.sub(
                    r"<ADDITIONAL_METADATA>[\s\S]*?</ADDITIONAL_METADATA>", "", cleaned
                )
                cleaned = re.sub(
                    r"<USER_SETTINGS_CHANGE>[\s\S]*?</USER_SETTINGS_CHANGE>", "", cleaned
                )
                cleaned = cleaned.strip()

                if cleaned:
                    markdown_lines.extend(["### 👤 User", "", cleaned, "", "---", ""])

            # Process Model responses (text replies to user)
            elif source == "MODEL" and step_type == "PLANNER_RESPONSE":
                # Check if it has non-empty text content (not just tool calls)
                if content and content.strip():
                    markdown_lines.extend(
                        ["### 🤖 Antigravity", "", content.strip(), "", "---", ""]
                    )

    # Save to file
    with open(output_path, "w", encoding="utf-8") as f:
        f.write("\n".join(markdown_lines))

    print(f"Conversation successfully exported to {output_path}")

except Exception as e:
    print(f"Error exporting conversation: {e}")
