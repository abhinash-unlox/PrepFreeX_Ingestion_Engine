from __future__ import annotations

import streamlit as st
from typing import Any
from apps.admin.api_client import AdminAPIClient


def render_taxonomy_review_page(api_client: AdminAPIClient):
    st.subheader("🎯 Immediate Question Taxonomy Review & Correction")
    st.caption("Inspect each canonical question against its original PDF source, verify Subject → Unit → Topic → Subtopic hierarchy, and apply corrections immediately on the same screen.")

    # 1. Fetch live review summary metrics from PostgreSQL
    summary, _, _, s_err = api_client.get_taxonomy_review_summary()
    if s_err or not summary:
        st.error(f"Failed to fetch review summary: {s_err}")
        return

    # Metrics Section: Separate Original Taxonomy Accuracy from Corrected Coverage
    total_canonical = summary["total_canonical"]
    reviewed_count = summary["reviewed_count"]
    completion_pct = summary["completion_pct"]
    confirmed_count = summary["confirmed_count"]
    reclassified_count = summary["reclassified_count"]
    applied_count = summary["corrections_applied_count"]
    proposals_count = summary["proposals_count"]
    uncertain_count = summary["uncertain_count"]
    source_prob_count = summary["source_problem_count"]
    not_reviewed_count = summary["not_reviewed_count"]
    orig_accuracy = summary.get("original_accuracy_pct", summary.get("accuracy_pct", 100.0))
    corrected_coverage = summary.get("corrected_coverage_pct", 0.0)

    m1, m2, m3, m4, m5 = st.columns(5)
    with m1:
        st.metric("Canonical Total", f"{total_canonical} questions")
    with m2:
        st.metric("Reviewed Progress", f"{reviewed_count} / {total_canonical}", delta=f"{completion_pct}% done")
    with m3:
        st.metric("Confirmed Correct", confirmed_count)
    with m4:
        st.metric("Reclassified & Applied", applied_count)
    with m5:
        st.metric("Original Taxonomy Accuracy", f"{orig_accuracy}%", help="Confirmed / (Confirmed + Reclassified) - uncertain cases excluded")

    m6, m7, m8, m9, m10 = st.columns(5)
    with m6:
        st.metric("Awaiting Review", not_reviewed_count)
    with m7:
        st.metric("Taxonomy Proposals", proposals_count)
    with m8:
        st.metric("Uncertain (Needs QA)", uncertain_count)
    with m9:
        st.metric("Source PDF Problems", source_prob_count)
    with m10:
        st.metric("Verified / Corrected Coverage", f"{corrected_coverage}%", help="(Confirmed + Applied Corrections) / Total Canonical")

    st.markdown("---")

    # 2. Taxonomy Tree for Cascading Selectors
    tax_tree, _, _, _ = api_client.get_taxonomy_tree()
    if not tax_tree:
        st.error("Could not load taxonomy tree from API.")
        return

    # 3. Filter Bar
    with st.expander("🔍 Filter Question Queue", expanded=False):
        fcol1, fcol2, fcol3, fcol4 = st.columns(4)

        with fcol1:
            subj_filter = st.selectbox(
                "Filter Subject",
                ["ALL", "mathematics", "physics", "chemistry"],
                index=0,
                key="tax_rev_subj"
            )

        avail_units = tax_tree.get("units", [])
        if subj_filter != "ALL":
            avail_units = [u for u in avail_units if u.get("subject") == subj_filter]
        unit_options = ["ALL"] + [f"{u['code']} - {u['name']}" for u in avail_units]

        with fcol2:
            unit_selected = st.selectbox("Filter Unit", unit_options, index=0, key="tax_rev_unit")
            unit_code = unit_selected.split(" - ")[0] if unit_selected != "ALL" else None

        avail_topics = tax_tree.get("topics", [])
        if unit_code:
            avail_topics = [t for t in avail_topics if t.get("parent_unit") == unit_code]
        topic_options = ["ALL"] + [f"{t['code']} - {t['name']}" for t in avail_topics]

        with fcol3:
            topic_selected = st.selectbox("Filter Topic", topic_options, index=0, key="tax_rev_topic")
            topic_code = topic_selected.split(" - ")[0] if topic_selected != "ALL" else None

        with fcol4:
            status_filter = st.selectbox(
                "Filter Status",
                [
                    "ALL",
                    "NOT_REVIEWED",
                    "CONFIRM_CORRECT",
                    "RECLASSIFY",
                    "NEEDS_TAXONOMY_PROPOSAL",
                    "UNCERTAIN",
                    "SOURCE_PROBLEM",
                    "CORRECTIONS_APPLIED"
                ],
                index=0,
                key="tax_rev_status"
            )

    # Build query params
    query_params: dict[str, Any] = {
        "page_size": 1,
        "review_status": status_filter,
    }
    if subj_filter != "ALL":
        query_params["subject"] = subj_filter
    if unit_code:
        query_params["unit_code"] = unit_code
    if topic_code:
        query_params["topic_code"] = topic_code

    # Reset page on filter change
    filter_sig = f"{subj_filter}_{unit_selected}_{topic_selected}_{status_filter}"
    if st.session_state.get("tax_rev_last_filter_sig") != filter_sig:
        st.session_state.tax_rev_page = 1
        st.session_state.tax_rev_last_filter_sig = filter_sig

    if "tax_rev_page" not in st.session_state:
        st.session_state.tax_rev_page = 1

    query_params["page"] = st.session_state.tax_rev_page

    # 4. Fetch Question for Review
    qlist_resp, _, _, q_err = api_client.get_taxonomy_review_questions(query_params)
    if q_err or not qlist_resp:
        st.error(f"Error loading questions: {q_err}")
        return

    total_matching = qlist_resp.get("total", 0)
    total_pages = qlist_resp.get("total_pages", 1)
    items = qlist_resp.get("items", [])

    if total_matching == 0 or not items:
        st.info("No questions match the selected filter criteria. Try clearing filters or selecting 'ALL'.")
        return

    # Ensure page is within range
    if st.session_state.tax_rev_page > total_pages:
        st.session_state.tax_rev_page = total_pages
        st.rerun()

    curr_item = items[0]
    public_id = curr_item["public_id"]

    # 5. Interactive Navigation Bar (Prev, Next, Skip, Resume, Jump)
    nav_col1, nav_col2, nav_col3, nav_col4, nav_col5, nav_col6 = st.columns([1.2, 1.2, 1.2, 1.5, 1.5, 2.4])

    with nav_col1:
        if st.button("⏮️ Previous", disabled=(st.session_state.tax_rev_page <= 1), key="nav_prev_btn"):
            st.session_state.tax_rev_page -= 1
            st.rerun()

    with nav_col2:
        if st.button("Next ⏭️", disabled=(st.session_state.tax_rev_page >= total_pages), key="nav_next_btn"):
            st.session_state.tax_rev_page += 1
            st.rerun()

    with nav_col3:
        if st.button("⏭️ Skip for Now", key="nav_skip_btn", help="Advances to next question without marking this question as reviewed"):
            if st.session_state.tax_rev_page < total_pages:
                st.session_state.tax_rev_page += 1
            else:
                st.session_state.tax_rev_page = 1
            st.rerun()

    with nav_col4:
        if st.button("▶️ Resume Unreviewed", key="nav_resume_btn", help="Jumps immediately to the next question needing review"):
            unrev_res, _, _, _ = api_client.get_next_unreviewed_question(subject=subj_filter if subj_filter != "ALL" else None)
            if unrev_res and unrev_res.get("public_id"):
                next_pid = unrev_res["public_id"]
                # Query page index for this public ID
                st.session_state.tax_rev_page = 1
                query_params["page"] = 1
                st.success(f"Resuming at unreviewed question: {next_pid}")
                st.rerun()
            else:
                st.info("All questions in this view have already been reviewed!")

    with nav_col5:
        # Display Current Position & Review Status Badge
        lat_dec = curr_item.get("latest_decision")
        if lat_dec == "CONFIRM_CORRECT":
            st.markdown("Status: **🟢 Confirmed**")
        elif lat_dec == "RECLASSIFY":
            st.markdown("Status: **🟠 Reclassified**")
        elif lat_dec == "NEEDS_TAXONOMY_PROPOSAL":
            st.markdown("Status: **🔵 Proposal**")
        elif lat_dec == "UNCERTAIN":
            st.markdown("Status: **🟡 Uncertain**")
        elif lat_dec == "SOURCE_PROBLEM":
            st.markdown("Status: **🔴 Source Issue**")
        else:
            st.markdown("Status: **⚪ Not Reviewed**")

    with nav_col6:
        # Jump directly to question by ID
        c_j1, c_j2 = st.columns([3, 1])
        with c_j1:
            jump_input = st.text_input("Jump to ID:", placeholder="e.g. Q00000042", label_visibility="collapsed", key="jump_input_val")
        with c_j2:
            if st.button("Go", key="jump_go_btn"):
                if jump_input:
                    clean_pid = jump_input.strip().upper()
                    det_check, _, _, _ = api_client.get_taxonomy_review_question_detail(clean_pid)
                    if det_check:
                        # Find its position by searching
                        st.session_state.target_jump_pid = clean_pid
                        st.success(f"Loaded {clean_pid}")
                        st.rerun()
                    else:
                        st.error(f"'{clean_pid}' not found.")

    st.caption(f"**Viewing Question {st.session_state.tax_rev_page} of {total_matching}** in current queue (`{public_id}`)")
    st.markdown("---")

    # 6. Fetch Question Detail & Source Preview
    q_detail, _, _, d_err = api_client.get_taxonomy_review_question_detail(public_id)
    if d_err or not q_detail:
        st.error(f"Could not load details for {public_id}: {d_err}")
        return

    # Two-Column Layout: Question & Options (Left) | Source PDF (Right)
    left_col, right_col = st.columns([5, 5])

    with left_col:
        st.markdown(f"### 📝 Question: `{q_detail['public_id']}`")
        b1, b2, b3 = st.columns(3)
        with b1:
            st.markdown(f"**Subject:** `{q_detail['subject'].capitalize()}`")
        with b2:
            st.markdown(f"**Type:** `{q_detail['question_type']}`")
        with b3:
            diff = q_detail.get("difficulty", "N/A")
            cog = q_detail.get("cognitive_level", "N/A")
            st.markdown(f"**Diff / Cog:** `{diff}` / `{cog}`")

        # Statement
        st.markdown("#### Statement")
        st.markdown(q_detail["stem_md"])

        # Options
        options = q_detail.get("options", [])
        if options:
            st.markdown("#### Options")
            for opt in options:
                lbl = opt.get("label_printed") or str(opt.get("position"))
                st.markdown(f"- **({lbl})** {opt.get('text_md')}")

        # Internal Correct Answer & Explanation
        ans = q_detail.get("answer", {})
        correct_val = ans.get("value") or ans.get("text") or ans
        st.info(f"🔑 **Correct Answer (Internal):** `{correct_val}` | Key Verified: `{q_detail.get('answer_key_verified')}`")

        if q_detail.get("explanation_md"):
            with st.expander("📖 Step-by-Step Solution & Explanation", expanded=False):
                st.markdown(q_detail["explanation_md"])

        # Tags
        f_used = q_detail.get("formulas_used", [])
        if f_used:
            st.caption(f"**Formulas:** {', '.join(f_used)}")

    with right_col:
        st.markdown("### 📄 Original PDF Ground Truth")
        st.markdown(f"**Source File:** `{q_detail.get('source_title', 'Unknown')}`")
        s1, s2, s3 = st.columns(3)
        with s1:
            st.caption(f"**Publisher:** {q_detail.get('source_publisher', 'N/A')}")
        with s2:
            st.caption(f"**Exam:** {q_detail.get('source_exam_name', 'JEE Main')}")
        with s3:
            p_start = q_detail.get('source_page_start', 1)
            q_num = q_detail.get('source_local_number', 'N/A')
            st.caption(f"**Page:** {p_start} (Q#{q_num})")

        # High-Clarity PDF Page Render
        img_bytes, _, _, img_err = api_client.get_source_page_preview(public_id)
        if img_bytes:
            st.image(img_bytes, caption=f"Original PDF Page {p_start} (Question #{q_num})", width=600)
        else:
            st.warning(f"Could not render PDF preview: {img_err or 'File not found on disk'}")

    st.markdown("---")

    # 7. Taxonomy Inspection & Immediate In-Place Correction
    curr_tax = q_detail.get("current_taxonomy", {})
    sub_node = curr_tax.get("subtopic", {})
    top_node = curr_tax.get("topic", {})
    unit_node = curr_tax.get("unit", {})
    subj_node = curr_tax.get("subject", {})

    st.markdown("### 🏷️ Taxonomy Inspection & Immediate Action")

    # Show Current Hierarchy Box
    cur_box_col1, cur_box_col2 = st.columns([5, 5])
    with cur_box_col1:
        st.markdown(f"""
        **Currently Assigned Hierarchy:**
        - **Subject:** `{subj_node.get('code', 'N/A')}` — {subj_node.get('name', 'N/A')}
        - **Unit:** `{unit_node.get('code', 'N/A')}` — {unit_node.get('name', 'N/A')}
        - **Topic:** `{top_node.get('code', 'N/A')}` — {top_node.get('name', 'N/A')}
        - **Subtopic:** `{sub_node.get('code', 'N/A')}` — **{sub_node.get('name', 'N/A')}**
        """)
        st.caption(f"Tag Level: `{curr_tax.get('tag_level')}` | Primary Tag: `{curr_tax.get('is_primary')}`")

    with cur_box_col2:
        latest_audit = q_detail.get("latest_audit")
        if latest_audit:
            status_text = "✅ Correction Applied" if latest_audit.get("is_applied") else "Confirmed / Logged"
            st.info(f"**Latest Review Event:** `{latest_audit['decision']}` ({status_text})\n\n"
                    f"*Reviewer:* `{latest_audit['reviewer_id']}` on `{latest_audit['reviewed_at'][:19]}`\n\n"
                    f"*Notes:* {latest_audit.get('reviewer_notes') or 'None'}")
        else:
            st.caption("ℹ️ *This question has not yet been reviewed.*")

    # Offline Heuristic Suggestion Expander
    with st.expander("💡 View Offline Keyword-Overlap Suggestion (0 Groq Tokens)", expanded=False):
        sugg_data, _, _, _ = api_client.get_taxonomy_suggestion(public_id)
        if sugg_data and sugg_data.get("suggestions"):
            for sg in sugg_data["suggestions"]:
                st.markdown(f"- **`{sg['subtopic_code']}`** — {sg['subtopic_name']} (*{sg['topic_name']}*) | Match Score: `{sg['confidence_score']}`")
        else:
            st.caption("No strong keyword overlap found.")

    st.markdown("#### Choose Review Decision:")

    # Decision Radio Selection
    decision_choice = st.radio(
        "Decision:",
        [
            "CONFIRM_CORRECT",
            "RECLASSIFY",
            "NEEDS_TAXONOMY_PROPOSAL",
            "UNCERTAIN",
            "SOURCE_PROBLEM"
        ],
        index=0,
        horizontal=True,
        key="tax_rev_choice_radio",
        help="CONFIRM_CORRECT: Existing mapping is correct. RECLASSIFY: Correct it immediately. NEEDS_TAXONOMY_PROPOSAL: Subtopic missing."
    )

    # ----------------------------------------------------
    # WORKFLOW A: CONFIRM_CORRECT
    # ----------------------------------------------------
    if decision_choice == "CONFIRM_CORRECT":
        st.success("✅ The existing hierarchy will be confirmed and preserved in audit records.")
        confirm_notes = st.text_input("Reviewer Notes (Optional):", placeholder="e.g. Verified against textbook standard definition", key="notes_confirm")

        if st.button("✅ Confirm Correct & Next Question ➡️", type="primary", key="btn_confirm_next"):
            res, _, status, err = api_client.submit_taxonomy_decision(
                public_id=public_id,
                reviewer_decision="CONFIRM_CORRECT",
                reviewer_notes=confirm_notes,
                reviewer_id="lead_assessor"
            )
            if err or status != 200:
                st.error(f"Failed to confirm question: {err}")
            else:
                st.toast(f"Confirmed `{public_id}` as correct! Moving to next question...", icon="✅")
                # Advance to next page automatically
                if st.session_state.tax_rev_page < total_pages:
                    st.session_state.tax_rev_page += 1
                st.rerun()

    # ----------------------------------------------------
    # WORKFLOW B: RECLASSIFY (Immediate In-Place Correction)
    # ----------------------------------------------------
    elif decision_choice == "RECLASSIFY":
        st.markdown("#### 🔄 Select Corrected Taxonomy Hierarchy")
        st.caption("Cascading selectors strictly restrict each selection to valid children of the previous node.")

        subtopics_pool = tax_tree.get("subtopics", [])
        topics_pool = tax_tree.get("topics", [])
        units_pool = tax_tree.get("units", [])

        # Step 1: Subject Selector
        curr_subj = q_detail["subject"].lower()
        rc_c1, rc_c2, rc_c3, rc_c4 = st.columns(4)

        with rc_c1:
            reclass_subj = st.selectbox(
                "1. Correct Subject:",
                ["mathematics", "physics", "chemistry"],
                index=["mathematics", "physics", "chemistry"].index(curr_subj),
                key="reclass_subj_sel"
            )

        # Step 2: Unit Selector (filtered to Subject)
        subj_units = [u for u in units_pool if u.get("subject") == reclass_subj]
        unit_codes = [u["code"] for u in subj_units]
        
        # Try to default to current unit if subject matches
        default_unit_idx = 0
        if unit_node.get("code") in unit_codes and reclass_subj == curr_subj:
            default_unit_idx = unit_codes.index(unit_node.get("code"))

        with rc_c2:
            rc_unit_sel = st.selectbox(
                "2. Correct Unit:",
                [f"{u['code']} - {u['name']}" for u in subj_units],
                index=default_unit_idx,
                key="reclass_unit_sel"
            )
            chosen_unit_code = rc_unit_sel.split(" - ")[0]

        # Step 3: Topic Selector (filtered to Unit)
        unit_topics = [t for t in topics_pool if t.get("parent_unit") == chosen_unit_code]
        topic_codes = [t["code"] for t in unit_topics]

        default_topic_idx = 0
        if top_node.get("code") in topic_codes:
            default_topic_idx = topic_codes.index(top_node.get("code"))

        with rc_c3:
            rc_topic_sel = st.selectbox(
                "3. Correct Topic:",
                [f"{t['code']} - {t['name']}" for t in unit_topics] if unit_topics else ["None"],
                index=default_topic_idx if unit_topics else 0,
                key="reclass_topic_sel"
            )
            chosen_topic_code = rc_topic_sel.split(" - ")[0] if rc_topic_sel != "None" else None

        # Step 4: Subtopic Selector (filtered to Topic)
        topic_subtopics = [s for s in subtopics_pool if s.get("parent_topic") == chosen_topic_code]
        sub_codes = [s["code"] for s in topic_subtopics]

        default_sub_idx = 0
        if sub_node.get("code") in sub_codes:
            default_sub_idx = sub_codes.index(sub_node.get("code"))

        with rc_c4:
            rc_subtopic_sel = st.selectbox(
                "4. Correct Subtopic:",
                [f"{s['code']} - {s['name']}" for s in topic_subtopics] if topic_subtopics else ["None"],
                index=default_sub_idx if topic_subtopics else 0,
                key="reclass_subtopic_sel"
            )

        chosen_subtopic_id = None
        chosen_subtopic_obj = None
        if rc_subtopic_sel != "None":
            chosen_sub_code = rc_subtopic_sel.split(" - ")[0]
            chosen_subtopic_obj = next((s for s in topic_subtopics if s["code"] == chosen_sub_code), None)
            if chosen_subtopic_obj:
                chosen_subtopic_id = chosen_subtopic_obj["id"]

        # Side-by-Side Comparison Box
        st.markdown("##### ⚖️ Side-by-Side Taxonomy Comparison")
        comp_c1, comp_c2 = st.columns(2)
        with comp_c1:
            st.error(f"""
            **Current Hierarchy (To Replace):**
            - **Subject:** {q_detail['subject'].capitalize()}
            - **Unit:** `{unit_node.get('code', 'N/A')}` {unit_node.get('name', 'N/A')}
            - **Topic:** `{top_node.get('code', 'N/A')}` {top_node.get('name', 'N/A')}
            - **Subtopic:** `{sub_node.get('code', 'N/A')}` **{sub_node.get('name', 'N/A')}**
            """)

        with comp_c2:
            st.success(f"""
            **Proposed Corrected Hierarchy (New Target):**
            - **Subject:** {reclass_subj.capitalize()}
            - **Unit:** `{chosen_unit_code}`
            - **Topic:** `{chosen_topic_code}`
            - **Subtopic:** `{chosen_subtopic_obj['code'] if chosen_subtopic_obj else 'None'}` **{chosen_subtopic_obj['name'] if chosen_subtopic_obj else 'None'}**
            """)

        reclass_notes = st.text_input(
            "Academic Justification / Notes for Reclassification:",
            placeholder="Explain why this question belongs to the new subtopic...",
            key="reclass_notes_input"
        )

        # Single Action Button: SAVE & APPLY CORRECTION
        if st.button("⚡ SAVE & APPLY CORRECTION & NEXT QUESTION ➡️", type="primary", key="btn_save_apply_reclass"):
            if not chosen_subtopic_id:
                st.error("Please select a valid subtopic before saving.")
            else:
                res, _, status, err = api_client.submit_taxonomy_decision(
                    public_id=public_id,
                    reviewer_decision="RECLASSIFY",
                    proposed_subtopic_id=chosen_subtopic_id,
                    reviewer_notes=reclass_notes,
                    reviewer_id="lead_assessor",
                    apply_immediately=True
                )
                if err or status != 200:
                    st.error(f"Correction failed: {err}")
                else:
                    st.toast(f"✅ Reclassified `{public_id}` to `{chosen_subtopic_obj['code']}`! Moving to next question...", icon="⚡")
                    if st.session_state.tax_rev_page < total_pages:
                        st.session_state.tax_rev_page += 1
                    st.rerun()

    # ----------------------------------------------------
    # WORKFLOW C: NEEDS_TAXONOMY_PROPOSAL
    # ----------------------------------------------------
    elif decision_choice == "NEEDS_TAXONOMY_PROPOSAL":
        st.info("💡 Record a proposal for a missing subtopic without altering canonical tags automatically.")
        prop_parent = st.text_input("Proposed Parent Topic or Code:", placeholder="e.g. PHY.U14.T04", key="prop_parent_code")
        prop_title = st.text_input("Proposed New Subtopic Title:", placeholder="e.g. Transformer Energy Losses in Real Cores", key="prop_subtopic_title")
        prop_notes = st.text_area("Reviewer Notes & Justification:", key="prop_notes_area")

        if st.button("📝 Save Proposal & Next Question ➡️", type="primary", key="btn_save_prop_next"):
            proposal_str = f"Parent: {prop_parent} | New Subtopic: {prop_title} | Notes: {prop_notes}"
            res, _, status, err = api_client.submit_taxonomy_decision(
                public_id=public_id,
                reviewer_decision="NEEDS_TAXONOMY_PROPOSAL",
                proposal_details=proposal_str,
                reviewer_notes=prop_notes,
                reviewer_id="lead_assessor"
            )
            if err or status != 200:
                st.error(f"Failed to record proposal: {err}")
            else:
                st.toast(f"Proposal recorded for `{public_id}`! Moving to next question...", icon="📝")
                if st.session_state.tax_rev_page < total_pages:
                    st.session_state.tax_rev_page += 1
                st.rerun()

    # ----------------------------------------------------
    # WORKFLOW D: UNCERTAIN
    # ----------------------------------------------------
    elif decision_choice == "UNCERTAIN":
        st.warning("⚠️ Flag this question as uncertain for secondary peer review without altering taxonomy.")
        unc_notes = st.text_area("Questions / Open issues requiring academic consensus:", key="unc_notes_area")

        if st.button("❓ Flag as Uncertain & Next Question ➡️", type="primary", key="btn_unc_next"):
            res, _, status, err = api_client.submit_taxonomy_decision(
                public_id=public_id,
                reviewer_decision="UNCERTAIN",
                reviewer_notes=unc_notes,
                reviewer_id="lead_assessor"
            )
            if err or status != 200:
                st.error(f"Failed to flag question: {err}")
            else:
                st.toast(f"Flagged `{public_id}` as uncertain! Moving to next question...", icon="❓")
                if st.session_state.tax_rev_page < total_pages:
                    st.session_state.tax_rev_page += 1
                st.rerun()

    # ----------------------------------------------------
    # WORKFLOW E: SOURCE_PROBLEM
    # ----------------------------------------------------
    elif decision_choice == "SOURCE_PROBLEM":
        st.error("🔴 Report that the source PDF page, question statement, or diagram is illegible or corrupted.")
        src_prob_notes = st.text_area("Describe the source issue (e.g. missing circuit figure on page 12, illegible exponents):", key="src_prob_area")

        if st.button("🔴 Report Source Problem & Next Question ➡️", type="primary", key="btn_src_prob_next"):
            res, _, status, err = api_client.submit_taxonomy_decision(
                public_id=public_id,
                reviewer_decision="SOURCE_PROBLEM",
                reviewer_notes=src_prob_notes,
                reviewer_id="lead_assessor"
            )
            if err or status != 200:
                st.error(f"Failed to record source issue: {err}")
            else:
                st.toast(f"Reported source problem for `{public_id}`! Moving to next question...", icon="🔴")
                if st.session_state.tax_rev_page < total_pages:
                    st.session_state.tax_rev_page += 1
                st.rerun()

    # 8. Complete Audit History Expander
    hist = q_detail.get("review_history", [])
    if hist:
        with st.expander(f"📜 Audit History for {public_id} ({len(hist)} events)", expanded=False):
            for h in hist:
                app_badge = "✅ Applied" if h.get("is_applied") else "Preserved / Draft"
                st.markdown(f"**`{h['decision']}`** | By `{h['reviewer_id']}` on `{h['reviewed_at'][:19]}` | Status: **{app_badge}**")
                if h.get("reviewer_notes"):
                    st.caption(f"Notes: {h['reviewer_notes']}")
                if h.get("proposed_taxonomy"):
                    st.caption(f"Proposed Snapshot: {h['proposed_taxonomy']}")
                st.markdown("---")
