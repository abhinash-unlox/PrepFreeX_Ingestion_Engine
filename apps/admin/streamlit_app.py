from __future__ import annotations

import streamlit as st

from apps.admin.api_client import AdminAPIClient
from apps.admin.components.filters import render_filters
from apps.admin.components.question_table import render_question_table
from apps.admin.components.question_detail import render_question_detail
from apps.admin.components.taxonomy_review import render_taxonomy_review_page
from apps.admin.components.question_variation import render_question_variation_page


# Page configuration
st.set_page_config(
    page_title="PrepFreeX — Question Bank Explorer",
    page_icon="📚",
    layout="wide",
    initial_sidebar_state="expanded",
)

# Initialize API client
api_client = AdminAPIClient()


def main():
    st.sidebar.title("PrepFreeX Admin")
    nav_mode = st.sidebar.radio(
        "Navigation",
        ["🧪 Question Variation Playground", "🎯 Question Taxonomy Review", "📚 Question Bank Explorer"],
        index=0,
        key="main_nav_mode"
    )

    if nav_mode == "🧪 Question Variation Playground":
        render_question_variation_page(api_client)
        return

    if nav_mode == "🎯 Question Taxonomy Review":
        render_taxonomy_review_page(api_client)
        return

    st.title("📚 PrepFreeX Question Bank Explorer")
    st.caption("Internal QA & Content Verification Dashboard (Streamlit UI → FastAPI REST API → PostgreSQL 18.6)")

    # 1. Health & Connection Check
    health_data, health_time, health_status, health_err = api_client.get_health()

    col_h1, col_h2 = st.columns([4, 1])
    with col_h2:
        if health_data and health_data.get("database_connected"):
            db_name = health_data.get("database_name", "prepfreex")
            st.success(f"🟢 Database Connected ({db_name})")
        else:
            st.error(f"🔴 Database Offline: {health_err or 'Connection failed'}")

    # 2. Live Dashboard Metrics Rows
    summary_data, _, _, _ = api_client.get_summary()

    if summary_data:
        st.markdown("##### 🏛️ Canonical Question Bank (Production Database)")
        m1, m2, m3, m4, m5, m6 = st.columns(6)
        by_sub = summary_data.get("by_subject", {})
        by_stat = summary_data.get("by_review_status", {})

        with m1:
            st.metric("Canonical Questions", summary_data.get("total_questions", 0))
        with m2:
            st.metric("Mathematics", by_sub.get("mathematics", 0))
        with m3:
            st.metric("Physics", by_sub.get("physics", 0))
        with m4:
            st.metric("Chemistry", by_sub.get("chemistry", 0))
        with m5:
            st.metric("Canonical Verified", by_stat.get("verified", 0))
        with m6:
            elig_count = summary_data.get("eligible_question_count", 0)
            st.metric("Student-Eligible", elig_count, delta="Zero published" if elig_count == 0 else "Active")

        st.markdown("##### 📥 Ingestion Pipeline & Staged Candidates (Cumulative Tracker)")
        c1, c2, c3, c4 = st.columns(4)
        with c1:
            st.metric("Cumulative Candidates (DB)", summary_data.get("total_staged_candidates", 0))
        with c2:
            st.metric("Staging Awaiting QA", summary_data.get("total_staged_candidates", 0))
        with c3:
            st.metric("Pending Figures", summary_data.get("pending_figures_count", 0))
        with c4:
            st.metric("Source Documents", len(summary_data.get("by_source", [])))

    st.markdown("---")

    # 3. Load Taxonomy Data for Filter Dropdowns
    taxonomy_data, _, _, _ = api_client.get_taxonomy()

    # 4. Filters & Search Section
    filter_params = render_filters(taxonomy_data, summary_data)

    # Pagination controls in sidebar or sub-header
    st.sidebar.header("Pagination Settings")
    page_size = st.sidebar.selectbox("Questions per page", [10, 20, 50, 100], index=1, key="page_size_select")
    
    # Store page in session state
    if "current_page" not in st.session_state:
        st.session_state.current_page = 1

    # Reset to page 1 if search/filter changed
    filter_signature = str(filter_params)
    if st.session_state.get("last_filter_sig") != filter_signature:
        st.session_state.current_page = 1
        st.session_state.last_filter_sig = filter_signature

    filter_params["page"] = st.session_state.current_page
    filter_params["page_size"] = page_size

    # 5. Fetch Question List via REST API
    questions_data, q_time, q_status, q_err = api_client.get_questions(filter_params)

    # 6. Two-Column Layout: Table on Left, Details on Right (or Stacked)
    left_col, right_col = st.columns([5, 5])

    selected_public_id = None

    with left_col:
        st.subheader("Question Catalog")
        if q_err:
            st.error(f"Failed to fetch questions: {q_err}")
        else:
            selected_public_id = render_question_table(
                questions_data,
                current_page=st.session_state.current_page,
                page_size=page_size,
            )

            # Pagination buttons
            total_pages = questions_data.get("total_pages", 1) if questions_data else 1
            col_prev, col_page_disp, col_next = st.columns([1, 2, 1])
            with col_prev:
                if st.button("⬅️ Previous", disabled=(st.session_state.current_page <= 1)):
                    st.session_state.current_page -= 1
                    st.rerun()
            with col_page_disp:
                st.caption(f"Page {st.session_state.current_page} of {total_pages}")
            with col_next:
                if st.button("Next ➡️", disabled=(st.session_state.current_page >= total_pages)):
                    st.session_state.current_page += 1
                    st.rerun()

    with right_col:
        st.subheader("Question Inspection")
        if selected_public_id:
            # Fetch single question detail via REST API
            q_detail, d_time, d_status, d_err = api_client.get_question_detail(selected_public_id)
            if d_err:
                st.error(f"Failed to fetch details for {selected_public_id}: {d_err}")
            else:
                render_question_detail(q_detail)
        else:
            st.info("Select a question on the left to inspect full mathematical expressions, options, answers, and tags.")

    # 7. Expandable API Diagnostics
    st.markdown("---")
    with st.expander("🔍 API Diagnostics & Network Telemetry", expanded=False):
        last_diag = api_client.last_diagnostic
        d1, d2, d3, d4 = st.columns(4)
        with d1:
            st.markdown(f"**Last Endpoint:** `{last_diag['endpoint']}`")
        with d2:
            st.markdown(f"**HTTP Status:** `{last_diag['status_code']}`")
        with d3:
            st.markdown(f"**Response Latency:** `{last_diag['response_time_ms']} ms`")
        with d4:
            st.markdown(f"**Records Processed:** `{last_diag['record_count']}`")

        if last_diag.get("error"):
            st.error(f"API Error: {last_diag['error']}")
        else:
            st.success("REST API connection operational.")


if __name__ == "__main__":
    main()

