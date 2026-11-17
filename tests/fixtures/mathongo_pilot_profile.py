from __future__ import annotations

from pathlib import Path

from engines.ingestion.models import ExtractedQuestion, Option, Tag


def mathongo_ac_questions(pdf_path: Path | None = None) -> list[ExtractedQuestion]:
    """Curated pilot fixture for the 5-question MathonGo Alternating Current PDF."""
    common = {
        "origin": "pyq",
        "exam_name": "JEE Main 2026",
        "exam_year": 2026,
        "subject": "physics",
        "language": "en",
        "status": "needs_review",
        "extraction_method": "manual_visual_assisted",
        "extraction_confidence": 0.95,
        "source_page_start": 1,
        "source_page_end": 1,
        "difficulty": 3,
        "difficulty_source": "ai_estimated",
    }

    q1 = ExtractedQuestion(
        **common,
        source_q_label="Q1", source_question_key="Q1", exam_date="2026-01-21", exam_shift=2,
        question_type="mcq_single",
        stem_md=("A capacitor $C$ is first charged fully with potential difference of $V_0$ and "
                 "disconnected from the battery. The charged capacitor is connected across an "
                 "inductor having inductance $L$. In $t$ s, 25% of the initial energy in the "
                 "capacitor is transferred to the inductor. The value of $t$ is ____ s."),
        options=[
            Option(position=1, label_printed="(1)", text_md=r"$\dfrac{\pi\sqrt{LC}}{3}$"),
            Option(position=2, label_printed="(2)", text_md=r"$\dfrac{\pi\sqrt{LC}}{6}$"),
            Option(position=3, label_printed="(3)", text_md=r"$\dfrac{\pi\sqrt{LC}}{2}$"),
            Option(position=4, label_printed="(4)", text_md=r"$\pi\sqrt{\dfrac{LC}{2}}$"),
        ],
        answer={"type": "option", "positions": [2]},
        source_explanation_md=(r"In an LC circuit, energy oscillates sinusoidally. Initially "
            r"$E_0=\frac12CV_0^2$. When 25% is transferred to the inductor, 75% remains "
            r"in the capacitor. Thus $E_C(t)=E_0\cos^2(\omega t)$ and "
            r"$\cos^2(\omega t)=0.75$. Hence $\sin(\omega t)=0.5$, "
            r"$\omega t=\pi/6$. With $\omega=1/\sqrt{LC}$, "
            r"$t=\pi\sqrt{LC}/6$."),
        explanation_md=(r"$E_C(t)=E_0\cos^2(\omega t)$. Since 25% of the initial energy "
            r"moves to the inductor, $\cos^2(\omega t)=0.75$. Therefore "
            r"$\sin(\omega t)=0.5$, giving $\omega t=\pi/6$. Using "
            r"$\omega=1/\sqrt{LC}$, $t=\pi\sqrt{LC}/6$."),
        explanation_source="source",
        formulas_used=[r"E_C=E_0\cos^2(\omega t)", r"\omega=1/\sqrt{LC}"],
        keywords=["LC oscillation", "energy transfer", "capacitor", "inductor"],
        estimated_time_sec=90,
        tags=[Tag(code="PHY.U14.T04.S02", is_primary=True, source="human")],
        classification_confidence=1.0,
        classification_status="needs_review",
        flags={"source_visual_transcription": True},
    )

    q2 = ExtractedQuestion(
        **common,
        source_q_label="Q2", source_question_key="Q2", exam_date="2026-01-23", exam_shift=1,
        question_type="numerical",
        stem_md=(r"Using a variable-frequency a.c. voltage source, the maximum current measured "
                 r"in the given LCR circuit is 50 mA for $V=5\sin(100t)$. The values are "
                 r"$L=2\,\mathrm{H}$ and $R=100\,\Omega$. The capacitance of the capacitor "
                 r"$C$ used is ____ $\mu\mathrm{F}$."),
        options=[],
        answer={"type": "numeric", "value": 50, "tolerance": 0, "unit": "μF"},
        source_explanation_md=(r"The printed solution identifies resonance and uses "
            r"$X_L=X_C$, hence $\omega L=1/(\omega C)$. It also prints an intermediate "
            r"current substitution using $V_{rms}=5/\sqrt2$ while the stem gives "
            r"$V=5\sin(100t)$ and the stated maximum current is 50 mA. The intermediate "
            r"current line is internally inconsistent with the peak-voltage convention."),
        explanation_md=(r"At resonance, $\omega^2LC=1$. Given $\omega=100\,\mathrm{rad/s}$ "
            r"and $L=2\,\mathrm{H}$, $C=1/(100^2\times2)=5\times10^{-5}\,\mathrm{F}" 
            r"=50\,\mu\mathrm{F}$."),
        explanation_source="human",
        answer_key_verified=True,
        explanation_verified=False,
        explanation_verification_notes="Source solution contains an inconsistent RMS/peak-voltage substitution; independently recomputed value is 50 μF.",
        has_figure=True,
        figure_status="pending",
        figure_description="Series LCR circuit showing L = 2 H, unknown C, R = 100 Ω and source V = 5 sin(100t).",
        figure_source_page=1,
        estimated_time_sec=120,
        tags=[Tag(code="PHY.U14.T05.S01", is_primary=True, source="human")],
        classification_confidence=1.0,
        classification_status="needs_review",
        flags={"source_explanation_inconsistency": True, "figure_required": True},
    )

    q3 = ExtractedQuestion(
        **common,
        source_q_label="Q3", source_question_key="Q3", exam_date="2026-01-28", exam_shift=2,
        question_type="numerical",
        stem_md=(r"An inductor stores 16 J of magnetic-field energy and dissipates 32 W of "
                 r"thermal energy due to its resistance when an a.c. current of 2 A (rms) "
                 r"and frequency 50 Hz flows through it. The ratio of inductive reactance "
                 r"to its resistance is ____ . ($\pi=3.14$)"),
        options=[],
        answer={"type": "numeric", "value": 314, "tolerance": 0, "unit": None},
        source_explanation_md=(r"Using $\frac12LI_{rms}^2=16$, obtain $L=8\,\mathrm{H}$. "
            r"Using $I_{rms}^2R=32$, obtain $R=8\,\Omega$. Then "
            r"$X_L=2\pi fL=2(3.14)(50)(8)=2512\,\Omega$, so $X_L/R=314$."),
        explanation_md=(r"$\frac12L(2)^2=16$ gives $L=8\,\mathrm{H}$. "
            r"$2^2R=32$ gives $R=8\,\Omega$. "
            r"$X_L=2\pi(50)(8)=2512\,\Omega$, therefore $X_L/R=314$."),
        explanation_source="source",
        answer_key_verified=True,
        explanation_verified=True,
        estimated_time_sec=120,
        formulas_used=[r"E_L=\frac12LI_{rms}^2", r"P=I_{rms}^2R", r"X_L=2\pi fL"],
        keywords=["inductive reactance", "inductor energy", "resistance"],
        tags=[Tag(code="PHY.U14.T03.S01", is_primary=True, source="human")],
        classification_confidence=1.0,
        classification_status="needs_review",
        flags={"source_visual_transcription": True},
    )

    q4 = ExtractedQuestion(
        **common,
        source_q_label="Q4", source_question_key="Q4", exam_date="2026-01-28", exam_shift=1,
        question_type="mcq_single",
        stem_md=(r"The electric current in a circuit is given by $i=i_0(t/T)$. The r.m.s. "
                 r"current for the period from $t=0$ to $t=T$ is ____ ."),
        options=[
            Option(position=1, label_printed="(1)", text_md=r"$i_0$"),
            Option(position=2, label_printed="(2)", text_md=r"$i_0/\sqrt{6}$"),
            Option(position=3, label_printed="(3)", text_md=r"$i_0/\sqrt{3}$"),
            Option(position=4, label_printed="(4)", text_md=r"$i_0/\sqrt{2}$"),
        ],
        answer={"type": "option", "positions": [3]},
        source_explanation_md=(r"$I_{rms}=\sqrt{\frac1T\int_0^T i^2dt}$. Substituting "
            r"$i=i_0(t/T)$ gives $I_{rms}=i_0/\sqrt3$."),
        explanation_md=(r"$I_{rms}=\sqrt{\frac1T\int_0^T i_0^2(t/T)^2dt}="
            r"i_0/\sqrt3$."),
        explanation_source="source",
        answer_key_verified=True,
        explanation_verified=True,
        estimated_time_sec=90,
        formulas_used=[r"I_{rms}=\sqrt{\frac1T\int_0^T i^2dt}"],
        keywords=["RMS", "alternating current", "non-sinusoidal waveform"],
        tags=[Tag(code="PHY.U14.T02.S01", is_primary=True, source="human")],
        classification_confidence=1.0,
        classification_status="needs_review",
        flags={"source_visual_transcription": True},
    )

    q5 = ExtractedQuestion(
        **common,
        source_q_label="Q5", source_question_key="Q5", exam_date="2026-01-24", exam_shift=1,
        question_type="mcq_single",
        stem_md=(r"For the series LCR circuit connected with a 220 V, 50 Hz a.c. source, "
                 r"the inductive reactance is $X_L=70\,\Omega$, capacitive reactance is "
                 r"$X_C=150\,\Omega$ and resistance is $R=60\,\Omega$. The power factor "
                 r"is $\alpha/10$. Find $\alpha$."),
        options=[
            Option(position=1, label_printed="(1)", text_md="10"),
            Option(position=2, label_printed="(2)", text_md="4"),
            Option(position=3, label_printed="(3)", text_md="6"),
            Option(position=4, label_printed="(4)", text_md="8"),
        ],
        answer={"type": "option", "positions": [3]},
        source_explanation_md=(r"Net reactance $X=X_C-X_L=150-70=80\,\Omega$. "
            r"Impedance $Z=\sqrt{R^2+X^2}=100\,\Omega$. Power factor "
            r"$\cos\phi=R/Z=60/100=0.6$. Since $0.6=\alpha/10$, $\alpha=6$."),
        explanation_md=(r"$X=150-70=80\,\Omega$, and "
            r"$Z=\sqrt{60^2+80^2}=100\,\Omega$. Thus the power factor is "
            r"$R/Z=0.6=\alpha/10$, giving $\alpha=6$."),
        explanation_source="source",
        answer_key_verified=True,
        explanation_verified=True,
        has_figure=True,
        figure_status="pending",
        figure_description="Series LCR circuit with 220 V, 50 Hz source; XL = 70 Ω, XC = 150 Ω and R = 60 Ω.",
        figure_source_page=1,
        estimated_time_sec=90,
        formulas_used=[r"Z=\sqrt{R^2+(X_C-X_L)^2}", r"\cos\phi=R/Z"],
        keywords=["power factor", "impedance", "series LCR circuit"],
        tags=[
            Tag(code="PHY.U14.T06.S01", is_primary=True, source="human"),
            Tag(code="PHY.U14.T04.S01", is_primary=False, source="human"),
        ],
        classification_confidence=1.0,
        classification_status="needs_review",
        flags={"source_visual_transcription": True, "figure_required": True},
    )

    return [q1, q2, q3, q4, q5]

