from __future__ import annotations

from typing import Any
import pandas as pd
import streamlit as st


def render_question_table(
    question_data: dict[str, Any] | None,
    current_page: int,
    page_size: int,
) -> str | None:
    """Renders the paginated table of questions and returns the selected Public ID if chosen."""
    if not question_data or not question_data.get("items"):
        st.info("No questions found matching the selected filter criteria.")
        return None

    items = question_data["items"]
    total = question_data["total"]
    total_pages = question_data["total_pages"]

    st.markdown(
        f"**Showing {len(items)} of {total} question(s)** (Page {current_page} of {total_pages})"
    )

    # Format table for display
    table_rows = []
    for item in items:
        unit_display = f"{item['unit_code']}" if item.get("unit_code") else "-"
        topic_display = f"{item['topic_code']}" if item.get("topic_code") else "-"
        subtopic_display = f"{item['subtopic_code']}" if item.get("subtopic_code") else "-"

        table_rows.append({
            "Public ID": item["public_id"],
            "Subject": (item["subject"] or "").capitalize(),
            "Unit": unit_display,
            "Topic": topic_display,
            "Primary Subtopic": subtopic_display,
            "Type": item["question_type"],
            "Diff": item["difficulty"] or "-",
            "Source": item["source_title"] or "Unknown",
            "Status": item["status"],
            "Preview": item["stem_preview"],
        })

    df = pd.DataFrame(table_rows)

    # Display dataframe
    st.dataframe(
        df[["Public ID", "Subject", "Unit", "Topic", "Primary Subtopic", "Type", "Diff", "Status", "Source", "Preview"]],
        use_container_width=True,
        hide_index=True,
    )

    # Question Selector
    public_ids = [item["public_id"] for item in items]
    selected_id = st.selectbox(
        "Select a question from this page to view details:",
        options=public_ids,
        key="selected_question_selector",
    )

    return selected_id

