from __future__ import annotations

from typing import Any
import streamlit as st


def render_filters(taxonomy_data: dict[str, Any] | None, summary_data: dict[str, Any] | None) -> dict[str, Any]:
    """Renders comprehensive filter controls in Streamlit and returns query parameters."""
    st.subheader("Filter & Search Questions")

    col_search, col_subj, col_diff, col_type = st.columns([3, 2, 1, 2])

    with col_search:
        search_query = st.text_input(
            "Search question text or Public ID",
            placeholder="e.g. Q00000001, matrix, calorimetry, ozone...",
            key="search_input",
        )

    with col_subj:
        subject_options = ["All", "mathematics", "physics", "chemistry"]
        selected_subject = st.selectbox("Subject", subject_options, key="filter_subject")

    with col_diff:
        diff_options = ["All", "1", "2", "3", "4", "5"]
        selected_diff = st.selectbox("Difficulty", diff_options, key="filter_diff")

    with col_type:
        type_options = ["All", "mcq_single", "mcq_multi", "numerical", "match_list", "assertion_reason"]
        selected_type = st.selectbox("Question Type", type_options, key="filter_type")

    # Second row of filters in an expander for clean UI
    with st.expander("Advanced Taxonomy & Source Filters", expanded=False):
        col_unit, col_topic, col_subtopic = st.columns(3)

        # Build cascading taxonomy lists
        units_list = taxonomy_data.get("units", []) if taxonomy_data else []
        topics_list = taxonomy_data.get("topics", []) if taxonomy_data else []
        subtopics_list = taxonomy_data.get("subtopics", []) if taxonomy_data else []

        if selected_subject != "All":
            filtered_units = [u for u in units_list if u.get("subject") == selected_subject]
        else:
            filtered_units = units_list

        unit_labels = ["All"] + [f"{u['code']} - {u['name']}" for u in filtered_units]

        with col_unit:
            selected_unit_label = st.selectbox("Taxonomy Unit", unit_labels, key="filter_unit")
            selected_unit_code = selected_unit_label.split(" - ")[0] if selected_unit_label != "All" else None

        # Filter topics
        if selected_unit_code:
            filtered_topics = [t for t in topics_list if t.get("parent_unit") == selected_unit_code]
        elif selected_subject != "All":
            u_codes = {u["code"] for u in filtered_units}
            filtered_topics = [t for t in topics_list if t.get("parent_unit") in u_codes]
        else:
            filtered_topics = topics_list

        topic_labels = ["All"] + [f"{t['code']} - {t['name']}" for t in filtered_topics]

        with col_topic:
            selected_topic_label = st.selectbox("Taxonomy Topic", topic_labels, key="filter_topic")
            selected_topic_code = selected_topic_label.split(" - ")[0] if selected_topic_label != "All" else None

        # Filter subtopics
        if selected_topic_code:
            filtered_subs = [s for s in subtopics_list if s.get("parent_topic") == selected_topic_code]
        else:
            filtered_subs = subtopics_list

        subtopic_labels = ["All"] + [f"{s['code']} - {s['name']}" for s in filtered_subs]

        with col_subtopic:
            selected_subtopic_label = st.selectbox("Taxonomy Subtopic", subtopic_labels, key="filter_subtopic")
            selected_subtopic_code = selected_subtopic_label.split(" - ")[0] if selected_subtopic_label != "All" else None

        col_src, col_status, col_fig = st.columns(3)

        # Sources from summary
        sources = summary_data.get("by_source", []) if summary_data else []
        source_labels = ["All"] + [s["title"] for s in sources]
        with col_src:
            selected_source = st.selectbox("Source Document", source_labels, key="filter_source")

        with col_status:
            status_options = ["All", "needs_review", "verified", "draft", "rejected"]
            selected_status = st.selectbox("Review Status", status_options, key="filter_status")

        with col_fig:
            fig_options = ["All", "Yes", "No"]
            selected_fig = st.selectbox("Has Figure", fig_options, key="filter_fig")

    # Construct query parameter dictionary
    params: dict[str, Any] = {}
    if search_query.strip():
        params["search"] = search_query.strip()
    if selected_subject != "All":
        params["subject"] = selected_subject
    if selected_diff != "All":
        params["difficulty"] = int(selected_diff)
    if selected_type != "All":
        params["question_type"] = selected_type
    if selected_unit_code:
        params["unit_code"] = selected_unit_code
    if selected_topic_code:
        params["topic_code"] = selected_topic_code
    if selected_subtopic_code:
        params["subtopic_code"] = selected_subtopic_code
    if selected_source != "All":
        params["source"] = selected_source
    if selected_status != "All":
        params["status"] = selected_status
    if selected_fig == "Yes":
        params["has_figure"] = True
    elif selected_fig == "No":
        params["has_figure"] = False

    return params

