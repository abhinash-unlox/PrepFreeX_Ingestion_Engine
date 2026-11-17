from __future__ import annotations

from typing import Any
import streamlit as st


def render_question_detail(question: dict[str, Any] | None):
    """Renders the comprehensive administrative view of a selected question."""
    if not question:
        st.warning("Select a question to inspect its complete administrative record.")
        return

    public_id = question.get("public_id", "Unknown")
    subject = (question.get("subject") or "").capitalize()
    q_type = question.get("question_type", "")
    status = question.get("status", "draft")

    st.markdown(f"### Question Record: `{public_id}` (v{question.get('version', 1)})")

    # Header badges row
    col_sub, col_type, col_diff, col_cog, col_status = st.columns(5)
    with col_sub:
        st.metric("Subject", subject)
    with col_type:
        st.metric("Question Type", q_type)
    with col_diff:
        st.metric("Difficulty", f"{question.get('difficulty') or '-'}/5")
    with col_cog:
        st.metric("Cognitive Level", (question.get("cognitive_level") or "-").capitalize())
    with col_status:
        st.metric("Review Status", status)

    st.markdown("---")

    # 1. Full question statement
    st.markdown("#### Question Statement")
    stem_md = question.get("stem_md") or "*(No statement text)*"
    st.markdown(stem_md)

    # 2. Options in original order
    options = question.get("options", [])
    answer = question.get("answer", {})
    correct_positions = set(answer.get("positions", [])) if isinstance(answer, dict) else set()

    if options:
        st.markdown("#### Options")
        for opt in options:
            pos = opt.get("position")
            lbl = opt.get("label_printed") or f"({chr(64 + pos)})"
            txt = opt.get("text_md", "")
            is_correct = pos in correct_positions

            if is_correct:
                st.success(f"**{lbl}** {txt}  *(CORRECT ANSWER)*")
            else:
                st.markdown(f"**{lbl}** {txt}")

    # 3. Answer summary for admin
    with st.expander("Admin Answer & Solution Details", expanded=True):
        col_ans, col_time = st.columns(2)
        with col_ans:
            st.markdown(f"**Correct Answer Key Payload:** `{answer}`")
            st.markdown(f"**Answer Key Verified:** `{question.get('answer_key_verified')}`")
            if question.get("answer_verification_notes"):
                st.caption(f"Verification Note: {question.get('answer_verification_notes')}")

        with col_time:
            est_time = question.get("estimated_time_sec")
            st.markdown(f"**Estimated Solving Time:** {est_time}s" if est_time else "**Estimated Solving Time:** -")
            st.markdown(f"**Explanation Verified:** `{question.get('explanation_verified')}`")

        st.markdown("##### Worked Explanation")
        expl = question.get("explanation_md") or question.get("source_explanation_md")
        if expl:
            st.markdown(expl)
        else:
            st.info("No worked explanation available for this record.")

    # 4. Taxonomy & Classification
    st.markdown("#### Academic Taxonomy & Classification")
    col_prim, col_sec = st.columns(2)

    with col_prim:
        st.markdown("**Primary Taxonomy Tag:**")
        prim_tag = question.get("primary_tag")
        if prim_tag:
            st.info(
                f"**Code:** `{prim_tag.get('code')}`\n\n"
                f"**Name:** {prim_tag.get('name')}\n\n"
                f"**Level:** {prim_tag.get('level')} | **Confidence:** {prim_tag.get('confidence') or '-'}"
            )
        else:
            unit_code = question.get("unit_code") or "-"
            unit_name = question.get("unit_name") or "-"
            sub_code = question.get("subtopic_code") or "-"
            sub_name = question.get("subtopic_name") or "-"
            st.info(f"**Unit:** `{unit_code}` - {unit_name}\n\n**Subtopic:** `{sub_code}` - {sub_name}")

    with col_sec:
        st.markdown("**Secondary Taxonomy Tags:**")
        sec_tags = question.get("secondary_tags", [])
        if sec_tags:
            for stag in sec_tags:
                st.markdown(f"- `{stag.get('code')}`: {stag.get('name')} *(conf: {stag.get('confidence') or '-'})*")
        else:
            st.caption("No secondary tags assigned.")

    # 5. Metadata tags (Formulas, Concepts, Skills, Keywords, Mistakes)
    st.markdown("#### Metadata & Learning Attributes")
    col_m1, col_m2 = st.columns(2)

    with col_m1:
        formulas = question.get("formulas_used", [])
        st.markdown(f"**Formulas Used ({len(formulas)}):**")
        if formulas:
            for f in formulas:
                st.code(f, language="latex")
        else:
            st.caption("None recorded.")

        concepts = question.get("concept_tags", [])
        st.markdown(f"**Concept Tags ({len(concepts)}):**")
        if concepts:
            st.write(", ".join([f"`{c}`" for c in concepts]))
        else:
            st.caption("None recorded.")

    with col_m2:
        skills = question.get("skill_tags", [])
        st.markdown(f"**Skill Tags ({len(skills)}):**")
        if skills:
            st.write(", ".join([f"`{s}`" for s in skills]))
        else:
            st.caption("None recorded.")

        keywords = question.get("keywords", [])
        st.markdown(f"**Keywords ({len(keywords)}):**")
        if keywords:
            st.write(", ".join([f"`{k}`" for k in keywords]))
        else:
            st.caption("None recorded.")

    if question.get("common_mistakes"):
        st.warning(f"**Common Student Mistakes:** {question.get('common_mistakes')}")

    # 6. Source Provenance & Audit Info
    with st.expander("Source Provenance & Audit Info", expanded=False):
        src = question.get("source", {})
        col_s1, col_s2 = st.columns(2)
        with col_s1:
            st.markdown(f"**Source Document:** {src.get('title', 'Unknown')}")
            st.markdown(f"**Publisher / Exam:** {src.get('publisher', '-')} | {src.get('exam', '-')}")
            st.markdown(f"**Licensing Status:** `{src.get('license_status', 'unverified')}`")
            st.markdown(f"**File Path:** `{src.get('file_path', '-')}`")

        with col_s2:
            st.markdown(f"**Source Question Label:** {question.get('source_q_label', '-')}")
            st.markdown(f"**Local / Global Number:** {question.get('source_local_number', '-')} / {question.get('source_global_number', '-')}")
            st.markdown(f"**Source Page:** {question.get('source_page_start', '-')}")
            st.markdown(f"**Figure Status:** `{question.get('figure_status', 'none')}` (has_figure={question.get('has_figure')})")

        st.caption(f"Created: {question.get('created_at')} | Last Updated: {question.get('updated_at')}")

        revisions = question.get("revisions", [])
        if revisions:
            st.markdown(f"##### Revisions ({len(revisions)})")
            for rev in revisions:
                st.caption(f"v{rev.get('version')} changed by {rev.get('changed_by')} at {rev.get('changed_at')}: {rev.get('reason')}")

