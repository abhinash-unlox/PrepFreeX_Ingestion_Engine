from __future__ import annotations

import json
from typing import Any
import streamlit as st

from apps.admin.api_client import AdminAPIClient


def render_question_variation_page(api_client: AdminAPIClient):
    st.title("🧪 Question Variation Playground")
    st.caption("Proof of Concept: Concept-Preserving Parameter Mutation & Mathematical Verification powered by Groq")

    # State init
    if "selected_var_qid" not in st.session_state:
        st.session_state.selected_var_qid = "Q00000001"
    if "latest_generation" not in st.session_state:
        st.session_state.latest_generation = None
    if "gen_loading" not in st.session_state:
        st.session_state.gen_loading = False

    # Top Tabs: [Playground / Generator, Past Experiments]
    tab_play, tab_history = st.tabs(["⚡ Variant Generator", "📜 Historical Experiments & Audits"])

    with tab_play:
        # Load Filters
        filters_data, _, _, _ = api_client.get_variation_filters()
        subjects = ["All"] + (filters_data.get("subjects", []) if filters_data else [])

        # Filters Sidebar / Top Bar
        st.markdown("#### 1. Select Canonical Question")
        f_col1, f_col2, f_col3, f_col4 = st.columns([1.5, 2, 2, 2])

        with f_col1:
            sel_subject = st.selectbox("Subject", subjects, index=0, key="var_sel_subject")

        hierarchy = filters_data.get("hierarchy", []) if filters_data else []
        unit_options = ["All"]
        if sel_subject != "All":
            filtered_units = sorted(list({f"{h['unit_code']}: {h['unit_name']}" for h in hierarchy if h.get("subject") == sel_subject}))
            unit_options.extend(filtered_units)
        else:
            all_units = sorted(list({f"{h['unit_code']}: {h['unit_name']}" for h in hierarchy if h.get("unit_code")}))
            unit_options.extend(all_units)

        with f_col2:
            sel_unit = st.selectbox("Syllabus Unit", unit_options, index=0, key="var_sel_unit")

        unit_code_arg = sel_unit.split(":")[0].strip() if sel_unit != "All" else None

        topic_options = ["All"]
        if unit_code_arg:
            filtered_topics = sorted(list({f"{h['topic_code']}: {h['topic_name']}" for h in hierarchy if h.get("unit_code") == unit_code_arg and h.get("topic_code")}))
            topic_options.extend(filtered_topics)
        with f_col3:
            sel_topic = st.selectbox("Topic", topic_options, index=0, key="var_sel_topic")

        topic_code_arg = sel_topic.split(":")[0].strip() if sel_topic != "All" else None

        with f_col4:
            search_query = st.text_input("Search ID / Keyword", placeholder="e.g. Q00000050 or capacitor", key="var_search")

        # Question List fetch
        q_resp, _, _, q_err = api_client.list_variation_questions(
            subject=sel_subject if sel_subject != "All" else None,
            unit_code=unit_code_arg,
            topic_code=topic_code_arg,
            search=search_query if search_query else None,
            limit=50
        )

        q_list = q_resp.get("questions", []) if q_resp else []
        total_matching = q_resp.get("total", 0) if q_resp else 0

        st.caption(f"Found **{total_matching}** canonical questions matching filters (showing first {len(q_list)})")

        if not q_list:
            st.warning("No questions found matching current criteria.")
            return

        # Selectbox to pick active question
        q_options_display = [
            f"{q['public_id']} | {q['subject'].upper()} | {q['question_type']} | {q.get('unit_code', 'NoUnit')} | {q['stem_plain'][:60]}..."
            for q in q_list
        ]
        chosen_idx = 0
        current_qid = st.session_state.selected_var_qid
        for i, q in enumerate(q_list):
            if q["public_id"] == current_qid:
                chosen_idx = i
                break

        picked_display = st.selectbox("Choose Canonical Question to Vary:", q_options_display, index=chosen_idx, key="picked_q_box")
        picked_qid = picked_display.split(" | ")[0].strip()
        st.session_state.selected_var_qid = picked_qid

        # Fetch full question detail
        q_detail, _, _, d_err = api_client.get_variation_question_detail(picked_qid)
        if not q_detail:
            st.error(f"Failed to load details for {picked_qid}: {d_err}")
            return

        # Warning banner if diagram is required
        has_fig = q_detail.get("has_figure", False)
        if has_fig:
            st.info("⚠️ **Note:** Original question contains a figure/diagram. The variation engine will automatically preserve geometry or adapt into prose.")

        st.markdown("---")
        # Layout: Side by Side (Left: Original, Right: Generator / Variant)
        col_orig, col_var = st.columns([1, 1], gap="medium")

        with col_orig:
            st.subheader(f"📌 Original Question: `{q_detail['public_id']}`")
            st.markdown(f"**Subject:** {q_detail.get('subject', '').title()} | **Type:** `{q_detail.get('question_type')}` | **Difficulty:** Level {q_detail.get('difficulty')}/5")
            st.markdown(f"**Taxonomy:** `{q_detail.get('unit_code')}` → `{q_detail.get('topic_code')}` → `{q_detail.get('subtopic_code')}` ({q_detail.get('subtopic_name')})")

            st.markdown("##### Statement:")
            st.markdown(q_detail.get("stem_md", ""))

            # Options
            if q_detail.get("options"):
                st.markdown("##### Options:")
                for opt in q_detail["options"]:
                    st.markdown(f"**({opt.get('label_printed', opt.get('position'))})** {opt.get('text_md')}")

            # Answer & Explanation
            with st.expander("🔑 Correct Answer & Explanation (Admin Eyes Only)", expanded=False):
                st.json(q_detail.get("answer"))
                st.markdown("##### Derivation:")
                st.markdown(q_detail.get("explanation_md", "No explanation recorded."))

        with col_var:
            st.subheader("⚡ Groq Variant Generator")

            # Generation Controls
            guidance = st.text_input(
                "Optional Operator Guidance (e.g., 'Make numbers larger', 'Change to kinetic energy'):",
                placeholder="Leave blank for automatic concept-preserving mutation",
                key="custom_guidance_input"
            )
            run_audit = st.checkbox("Run Independent LLM Mathematical Auditor", value=True, key="chk_run_audit")

            if st.button("🚀 Generate New Question Variant", type="primary", use_container_width=True):
                with st.spinner("🤖 Groq Qwen-3.8-27B is generating variant and recalculating math..."):
                    gen_res, elapsed, status_code, err = api_client.generate_question_variant(
                        public_id=picked_qid,
                        custom_guidance=guidance if guidance.strip() else None,
                        run_llm_review=run_audit
                    )
                    if gen_res:
                        st.session_state.latest_generation = gen_res
                        st.success(f"Variant generated successfully in {elapsed/1000:.1f}s! (Consumed {gen_res.get('tokens_consumed', 0)} tokens)")
                    else:
                        st.error(f"Generation failed: {err}")

            # Display Generated Variant if present
            latest = st.session_state.latest_generation
            if latest and latest.get("source_question", {}).get("public_id") == picked_qid:
                var = latest.get("variant", {})
                st.markdown(f"#### 🆕 Generated Variant: `{latest.get('variant_public_id')}`")
                st.markdown(f"**Status:** `{latest.get('status')}` | **Type:** `{var.get('question_type')}` | **Difficulty:** Level {var.get('difficulty', 3)}/5")

                st.markdown("##### New Question Statement:")
                st.markdown(var.get("stem_md", ""))

                if var.get("options"):
                    st.markdown("##### New Options:")
                    for opt in var["options"]:
                        st.markdown(f"**({opt.get('label_printed', opt.get('position'))})** {opt.get('text_md')}")

                with st.expander("🔑 Variant Recalculated Answer & Step-by-Step Derivation", expanded=True):
                    st.json(var.get("correct_answer"))
                    st.markdown("##### Derivation:")
                    st.markdown(var.get("explanation_md", ""))

                # Transformation diff table
                trans = var.get("transformation_spec", {})
                if trans.get("parameters_changed"):
                    st.markdown("##### 🔄 Parameter Mutation Spec:")
                    st.table(trans["parameters_changed"])

                # Validation & Audit Results
                st.markdown("##### 🛡️ Validation & Audit Checklist:")
                s_val = latest.get("structural_validation", {})
                if s_val.get("passed"):
                    st.success("✅ **Structural Checks Passed:** 4 distinct options, single valid key, balanced LaTeX.")
                else:
                    st.error(f"❌ **Structural Errors:** {', '.join(s_val.get('errors', []))}")

                # Deterministic SymPy / Domain Validator
                det_val = latest.get("deterministic_validation")
                if det_val:
                    if det_val.get("verified"):
                        st.success(f"🧮 **Deterministic Verification (SymPy/Domain Engine):** PASSED\n\n"
                                   f"- **Domain:** `{det_val.get('domain')}`\n"
                                   f"- **Calculated Value:** `{det_val.get('independent_value')}`")
                    elif det_val.get("discrepancy"):
                        st.error(f"🚨 **Deterministic Discrepancy Caught:** {det_val.get('discrepancy')}\n\n"
                                 f"- **Operator:** `{det_val.get('operator')}`")
                    else:
                        st.caption(f"ℹ️ **Deterministic Verification:** Not supported for this specific question type/domain (`{det_val.get('domain')}`).")

                # Difficulty Drift Analysis
                diff_val = latest.get("difficulty_analysis")
                if diff_val:
                    st.info(f"📊 **Difficulty Drift Analysis:** `{diff_val.get('drift_verdict', 'PRESERVED')}`\n\n"
                            f"- **Word Count Δ:** {diff_val.get('stem_word_count_delta')} words\n"
                            f"- **Math Tokens Δ:** {diff_val.get('math_token_count_delta')}\n"
                            f"- **Original Ops:** {diff_val.get('original_math_ops', 0)} | **Variant Ops:** {diff_val.get('variant_math_ops', 0)}")

                groq_audit = latest.get("groq_review")
                if groq_audit:
                    v_icon = "🟢" if groq_audit.get("overall_verdict") == "APPROVED" else "🟡"
                    st.info(f"{v_icon} **LLM Auditor Verdict:** `{groq_audit.get('overall_verdict')}`\n\n"
                            f"- **Mathematically Sound:** {groq_audit.get('mathematically_sound')}\n"
                            f"- **Concept Preserved:** {groq_audit.get('concept_preserved')}\n"
                            f"- **Answer Recalculation Valid:** {groq_audit.get('calculated_answer_matches')}\n"
                            f"- **Independent Derivation:** {groq_audit.get('independent_solution_summary')}\n"
                            f"- **Identified Flaws:** {groq_audit.get('identified_flaws_or_discrepancies')}")

                # Human Operator Review Buttons
                st.markdown("##### ✍️ Human Operator Assessment:")
                h_col1, h_col2, h_col3 = st.columns(3)
                exp_id = latest.get("experiment_id")

                with h_col1:
                    if st.button("👍 Mark as GOOD (Approve)", key=f"btn_good_{exp_id}", use_container_width=True):
                        res, _, _, _ = api_client.review_variation_experiment(exp_id, "GOOD", "Verified mathematically by operator.")
                        st.success("Variant marked as APPROVED!")
                with h_col2:
                    if st.button("👎 Mark as INCORRECT", key=f"btn_bad_{exp_id}", use_container_width=True):
                        res, _, _, _ = api_client.review_variation_experiment(exp_id, "INCORRECT", "Flaw flagged by operator.")
                        st.error("Variant marked as REJECTED.")
                with h_col3:
                    if st.button("📝 Flag for Edit", key=f"btn_edit_{exp_id}", use_container_width=True):
                        res, _, _, _ = api_client.review_variation_experiment(exp_id, "NEEDS_EDIT", "Requires minor correction.")
                        st.warning("Variant flagged for NEEDS_REVIEW.")

    with tab_history:
        st.subheader("📜 Historical Generation Experiments")
        exp_resp, _, _, _ = api_client.list_variation_experiments(limit=50)
        exps = exp_resp.get("experiments", []) if exp_resp else []
        st.caption(f"Total experiments logged: **{exp_resp.get('total', 0) if exp_resp else 0}**")

        if exps:
            import pandas as pd
            df = pd.DataFrame(exps)
            available_cols = [c for c in ["experiment_id", "source_public_id", "variant_public_id", "subject", "validation_status", "variant_status", "human_verdict", "tokens_consumed", "created_at"] if c in df.columns]
            st.dataframe(df[available_cols], use_container_width=True)
        else:
            st.info("No past variation experiments found yet. Run generations from the Generator tab.")

