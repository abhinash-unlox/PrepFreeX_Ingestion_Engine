'use client';

import React, { useState, useEffect } from 'react';
import katex from 'katex';
import { 
  CheckCircle2, XCircle, AlertTriangle, ArrowUpRight, RefreshCw, 
  Layers, FileText, Cpu, Check, X, Eye, ChevronDown, ChevronRight, Zap 
} from 'lucide-react';

function MathSpan({ text }: { text: string }) {
  if (!text) return null;
  // Simple LaTeX rendering helper
  const parts = text.split(/(\$[^\$]+\$)/g);
  return (
    <span className="whitespace-pre-wrap">
      {parts.map((part, idx) => {
        if (part.startsWith('$') && part.endsWith('$') && part.length > 2) {
          const rawMath = part.slice(1, -1);
          try {
            const html = katex.renderToString(rawMath, { throwOnError: false, displayMode: false });
            return <span key={idx} dangerouslySetInnerHTML={{ __html: html }} className="inline-katex px-0.5" />;
          } catch (e) {
            return <code key={idx} className="text-violet-600 bg-slate-100 px-1 rounded">{part}</code>;
          }
        }
        return <span key={idx}>{part}</span>;
      })}
    </span>
  );
}

export function StagingReviewView() {
  const [summary, setSummary] = useState<any>(null);
  const [questions, setQuestions] = useState<any[]>([]);
  const [manifest, setManifest] = useState<any[]>([]);
  const [filterStatus, setFilterStatus] = useState<string>('ALL');
  const [activeTab, setActiveTab] = useState<'questions' | 'manifest'>('questions');
  const [loading, setLoading] = useState<boolean>(true);
  const [promoting, setPromoting] = useState<boolean>(false);
  const [promoteMsg, setPromoteMsg] = useState<string | null>(null);
  const [extracting, setExtracting] = useState<boolean>(false);
  const [extractMsg, setExtractMsg] = useState<string | null>(null);
  const [expandedReasoning, setExpandedReasoning] = useState<Record<number, boolean>>({});

  const handleExtractNext = async (pdfPath?: string) => {
    setExtracting(true);
    setExtractMsg(null);
    try {
      const res = await fetch('http://127.0.0.1:8000/api/v1/staging/ingest-next', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(pdfPath ? { pdf_path: pdfPath, max_pages: 2 } : { max_pages: 2 })
      });
      if (res.ok) {
        const data = await res.json();
        setExtractMsg(data.message || 'Extracted new questions successfully.');
        setActiveTab('questions');
        fetchData();
      } else {
        const err = await res.json();
        setExtractMsg(err.detail || 'Failed to extract questions.');
      }
    } catch (err) {
      setExtractMsg('Network error while running extraction pipeline.');
    } finally {
      setExtracting(false);
    }
  };

  const fetchData = async () => {
    setLoading(true);
    try {
      const sumRes = await fetch('http://127.0.0.1:8000/api/v1/staging/summary');
      if (sumRes.ok) setSummary(await sumRes.json());

      let qUrl = 'http://127.0.0.1:8000/api/v1/staging/questions?limit=100';
      if (filterStatus !== 'ALL') qUrl += `&review_status=${filterStatus}`;
      const qRes = await fetch(qUrl);
      if (qRes.ok) {
        const qData = await qRes.json();
        setQuestions(qData.questions || []);
      }

      const mRes = await fetch('http://127.0.0.1:8000/api/v1/staging/manifest?limit=50');
      if (mRes.ok) {
        const mData = await mRes.json();
        setManifest(mData.pdfs || []);
      }
    } catch (err) {
      console.error('Failed to load staging data:', err);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchData();
  }, [filterStatus]);

  const handleApprove = async (qid: number) => {
    try {
      const res = await fetch(`http://127.0.0.1:8000/api/v1/staging/questions/${qid}/approve`, { method: 'POST' });
      if (res.ok) {
        setQuestions(prev => prev.map(q => q.id === qid ? { ...q, review_status: 'APPROVED' } : q));
        fetchData();
      }
    } catch (err) {
      console.error(err);
    }
  };

  const handleReject = async (qid: number) => {
    try {
      const res = await fetch(`http://127.0.0.1:8000/api/v1/staging/questions/${qid}/reject`, { method: 'POST' });
      if (res.ok) {
        setQuestions(prev => prev.map(q => q.id === qid ? { ...q, review_status: 'REJECTED' } : q));
        fetchData();
      }
    } catch (err) {
      console.error(err);
    }
  };

  const handleSelectAnswer = async (qid: number, optLabel: string) => {
    try {
      const res = await fetch(`http://127.0.0.1:8000/api/v1/staging/questions/${qid}/answer`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ correct_option: optLabel, auto_approve: true })
      });
      if (res.ok) {
        const data = await res.json();
        const updated = data.question;
        setQuestions(prev => prev.map(q => q.id === qid ? {
          ...q,
          correct_option: updated.correct_option,
          solver_status: updated.solver_status,
          review_status: updated.review_status
        } : q));
        fetchData();
      }
    } catch (err) {
      console.error('Failed to update answer:', err);
    }
  };

  const handlePromoteAll = async () => {
    setPromoting(true);
    setPromoteMsg(null);
    try {
      const res = await fetch('http://127.0.0.1:8000/api/v1/staging/promote', { method: 'POST' });
      if (res.ok) {
        const data = await res.json();
        setPromoteMsg(data.message || `Promoted ${data.promoted_count} questions.`);
        fetchData();
      }
    } catch (err) {
      setPromoteMsg('Failed to promote questions.');
    } finally {
      setPromoting(false);
    }
  };

  const toggleReasoning = (id: number) => {
    setExpandedReasoning(prev => ({ ...prev, [id]: !prev[id] }));
  };

  const qStats = summary?.questions || {};
  const mStats = summary?.manifest || {};

  return (
    <div className="space-y-6 max-w-7xl mx-auto pb-16">
      {/* HEADER & SUMMARY METRICS */}
      <div className="flex flex-col md:flex-row md:items-center justify-between gap-4 border-b border-slate-200 pb-5">
        <div>
          <h1 className="text-2xl font-bold tracking-tight text-slate-900 flex items-center gap-2">
            <Layers className="h-6 w-6 text-indigo-600" />
            Safe Question Ingestion & Staging Review
          </h1>
          <p className="text-sm text-slate-500 mt-1">
            Air-gapped verification staging area. Guardrail validation, 3-tier taxonomy, and Blind Solver parity before live database promotion.
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-3">
          <button
            onClick={() => handleExtractNext()}
            disabled={extracting}
            className="flex items-center gap-2 px-4 py-2 text-sm font-semibold text-white bg-violet-600 rounded-lg hover:bg-violet-700 disabled:opacity-50 transition-all shadow-xs cursor-pointer"
          >
            <Zap className={`h-4 w-4 ${extracting ? 'animate-bounce text-amber-300' : ''}`} />
            {extracting ? 'Extracting & Verifying PDF...' : 'Extract Next Questions from PDF'}
          </button>
          <button
            onClick={fetchData}
            disabled={loading}
            className="flex items-center gap-1.5 px-3.5 py-2 text-sm font-medium text-slate-700 bg-white border border-slate-200 rounded-lg hover:bg-slate-50 transition-colors shadow-2xs cursor-pointer"
          >
            <RefreshCw className={`h-4 w-4 ${loading ? 'animate-spin' : ''}`} />
            Refresh
          </button>
          <button
            onClick={handlePromoteAll}
            disabled={promoting || (qStats.approved || 0) === 0}
            className="flex items-center gap-1.5 px-4 py-2 text-sm font-semibold text-white bg-indigo-600 rounded-lg hover:bg-indigo-700 disabled:opacity-50 transition-all shadow-xs cursor-pointer"
          >
            <ArrowUpRight className="h-4 w-4" />
            {promoting ? 'Promoting...' : `Promote ${qStats.approved || 0} Approved to Live`}
          </button>
        </div>
      </div>

      {extractMsg && (
        <div className="p-4 bg-violet-50 border border-violet-200 text-violet-900 rounded-xl flex items-center justify-between text-sm shadow-2xs">
          <span className="flex items-center gap-2">
            <Zap className="h-4 w-4 text-violet-600 shrink-0" />
            {extractMsg}
          </span>
          <button onClick={() => setExtractMsg(null)} className="text-violet-600 hover:text-violet-900 cursor-pointer">
            <X className="h-4 w-4" />
          </button>
        </div>
      )}

      {promoteMsg && (
        <div className="p-4 bg-emerald-50 border border-emerald-200 text-emerald-800 rounded-xl flex items-center justify-between text-sm">
          <span>{promoteMsg}</span>
          <button onClick={() => setPromoteMsg(null)} className="text-emerald-600 hover:text-emerald-900">
            <X className="h-4 w-4" />
          </button>
        </div>
      )}

      {/* KPI METRIC CARDS */}
      <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-6 gap-3">
        <div className="bg-white p-4 rounded-xl border border-slate-200/80 shadow-2xs">
          <div className="text-xs font-semibold text-slate-500 uppercase tracking-wider">Total Staged</div>
          <div className="text-2xl font-bold text-slate-900 mt-1">{qStats.total_staged || 0}</div>
          <div className="text-xs text-slate-400 mt-1">Across all PDFs</div>
        </div>
        <div className="bg-white p-4 rounded-xl border border-emerald-200/80 bg-emerald-50/20 shadow-2xs">
          <div className="text-xs font-semibold text-emerald-700 uppercase tracking-wider">Approved</div>
          <div className="text-2xl font-bold text-emerald-600 mt-1">{qStats.approved || 0}</div>
          <div className="text-xs text-emerald-600/80 mt-1">Parity Verified</div>
        </div>
        <div className="bg-white p-4 rounded-xl border border-amber-200/80 bg-amber-50/20 shadow-2xs">
          <div className="text-xs font-semibold text-amber-700 uppercase tracking-wider">Pending Review</div>
          <div className="text-2xl font-bold text-amber-600 mt-1">{qStats.pending_review || 0}</div>
          <div className="text-xs text-amber-600/80 mt-1">Needs human check</div>
        </div>
        <div className="bg-white p-4 rounded-xl border border-red-200/80 bg-red-50/20 shadow-2xs">
          <div className="text-xs font-semibold text-red-700 uppercase tracking-wider">Rejected</div>
          <div className="text-2xl font-bold text-red-600 mt-1">{qStats.rejected || 0}</div>
          <div className="text-xs text-red-600/80 mt-1">Guardrail violations</div>
        </div>
        <div className="bg-white p-4 rounded-xl border border-indigo-200/80 bg-indigo-50/20 shadow-2xs">
          <div className="text-xs font-semibold text-indigo-700 uppercase tracking-wider">Promoted Live</div>
          <div className="text-2xl font-bold text-indigo-600 mt-1">{qStats.promoted || 0}</div>
          <div className="text-xs text-indigo-600/80 mt-1">In active DB</div>
        </div>
        <div className="bg-white p-4 rounded-xl border border-purple-200/80 bg-purple-50/20 shadow-2xs">
          <div className="text-xs font-semibold text-purple-700 uppercase tracking-wider">Tokens Used</div>
          <div className="text-xl font-bold text-purple-600 mt-1">
            {Number(qStats.total_tokens_used || 0).toLocaleString()}
          </div>
          <div className="text-xs text-purple-600/80 mt-1">Qwen + Solver tokens</div>
        </div>
      </div>

      {/* NAVIGATION TABS */}
      <div className="flex border-b border-slate-200">
        <button
          onClick={() => setActiveTab('questions')}
          className={`px-4 py-2.5 text-sm font-semibold border-b-2 transition-colors cursor-pointer ${
            activeTab === 'questions' ? 'border-indigo-600 text-indigo-600' : 'border-transparent text-slate-500 hover:text-slate-800'
          }`}
        >
          Staged Questions ({questions.length})
        </button>
        <button
          onClick={() => setActiveTab('manifest')}
          className={`px-4 py-2.5 text-sm font-semibold border-b-2 transition-colors cursor-pointer ${
            activeTab === 'manifest' ? 'border-indigo-600 text-indigo-600' : 'border-transparent text-slate-500 hover:text-slate-800'
          }`}
        >
          PDF Ingestion Tracker ({mStats.completed_pdfs || 0} / {mStats.total_pdfs || 0} Completed)
        </button>
      </div>

      {/* TAB CONTENT */}
      {activeTab === 'questions' ? (
        <div className="space-y-4">
          {/* FILTER BAR */}
          <div className="flex items-center gap-2 overflow-x-auto pb-1 text-xs">
            {['ALL', 'APPROVED', 'PENDING_REVIEW', 'REJECTED', 'PROMOTED'].map(st => (
              <button
                key={st}
                onClick={() => setFilterStatus(st)}
                className={`px-3 py-1.5 rounded-full font-medium transition-colors cursor-pointer ${
                  filterStatus === st 
                    ? 'bg-indigo-600 text-white' 
                    : 'bg-white border border-slate-200 text-slate-600 hover:bg-slate-50'
                }`}
              >
                {st.replace('_', ' ')}
              </button>
            ))}
          </div>

          {/* QUESTIONS LIST */}
          {questions.length === 0 ? (
            <div className="p-12 text-center bg-white rounded-xl border border-slate-200">
              <Layers className="h-10 w-10 text-slate-300 mx-auto mb-3" />
              <div className="text-base font-semibold text-slate-700">No staged questions found</div>
              <p className="text-xs text-slate-500 mt-1">
                Run <code className="bg-slate-100 px-1 py-0.5 rounded">python -m scripts.safe_ingest --next-pending</code> in your terminal to ingest from the next pending PDF.
              </p>
            </div>
          ) : (
            <div className="space-y-4">
              {questions.map((q, idx) => {
                const opts = Array.isArray(q.options) ? q.options : (typeof q.options === 'string' ? JSON.parse(q.options || '[]') : []);
                const notes = Array.isArray(q.guardrail_notes) ? q.guardrail_notes : (typeof q.guardrail_notes === 'string' ? JSON.parse(q.guardrail_notes || '[]') : []);
                const hasDiscrepancy = q.solver_status === 'DISCREPANCY';
                const isApproved = q.review_status === 'APPROVED';
                const isRejected = q.review_status === 'REJECTED';
                const isPromoted = q.review_status === 'PROMOTED';

                return (
                  <div key={q.id} className="bg-white rounded-xl border border-slate-200 shadow-2xs p-5 transition-all hover:border-slate-300">
                    <div className="flex flex-wrap items-center justify-between gap-2 border-b border-slate-100 pb-3 mb-3">
                      <div className="flex flex-wrap items-center gap-2 text-xs">
                        <span className="font-mono font-bold text-slate-700 bg-slate-100 px-2 py-0.5 rounded">
                          #{q.id} ({q.staging_uid})
                        </span>
                        <span className="px-2 py-0.5 bg-indigo-50 text-indigo-700 font-semibold rounded">
                          {q.subject}
                        </span>
                        <span className="px-2 py-0.5 bg-slate-100 text-slate-700 rounded">
                          {q.chapter_name}
                        </span>
                        <span className="px-2 py-0.5 bg-violet-50 text-violet-700 font-mono rounded">
                          {q.primary_topic_code}
                        </span>
                        <span className="text-slate-400">
                          {q.source_pdf} (p.{q.page_number})
                        </span>
                      </div>

                      <div className="flex items-center gap-2">
                        {/* Guardrail Badge */}
                        {q.guardrail_status === 'PASSED' ? (
                          <span className="flex items-center gap-1 text-xs px-2 py-0.5 bg-emerald-50 text-emerald-700 font-semibold rounded">
                            <Check className="h-3 w-3" /> Guardrails Passed
                          </span>
                        ) : (
                          <span className="flex items-center gap-1 text-xs px-2 py-0.5 bg-red-50 text-red-700 font-semibold rounded">
                            <X className="h-3 w-3" /> Guardrail Issues
                          </span>
                        )}

                        {/* Solver Badge */}
                        {q.solver_status === 'MATCHED' && (
                          <span className="flex items-center gap-1 text-xs px-2 py-0.5 bg-emerald-50 text-emerald-700 font-semibold rounded">
                            <CheckCircle2 className="h-3 w-3" /> Solver Matched ({q.solver_option})
                          </span>
                        )}
                        {q.solver_status === 'DISCREPANCY' && (
                          <span className="flex items-center gap-1 text-xs px-2 py-0.5 bg-amber-50 text-amber-700 font-semibold rounded">
                            <AlertTriangle className="h-3 w-3" /> Solver Discrepancy (Ext: {q.correct_option} vs Sol: {q.solver_option})
                          </span>
                        )}

                        {/* Review Status Badge */}
                        <span className={`text-xs px-2 py-0.5 font-bold uppercase rounded ${
                          isApproved ? 'bg-emerald-100 text-emerald-800' :
                          isRejected ? 'bg-red-100 text-red-800' :
                          isPromoted ? 'bg-indigo-100 text-indigo-800' :
                          'bg-amber-100 text-amber-800'
                        }`}>
                          {q.review_status}
                        </span>

                        <span className="flex items-center gap-1 text-xs font-mono text-purple-600 bg-purple-50 px-2 py-0.5 rounded">
                          <Cpu className="h-3 w-3" /> {q.total_tokens} tok
                        </span>
                      </div>
                    </div>

                    {/* STEM */}
                    <div className="text-base text-slate-900 leading-relaxed font-serif my-3 whitespace-pre-wrap">
                      <MathSpan text={q.question_text_latex} />
                    </div>

                    {/* DISCREPANCY QUICK-RESOLVER BANNER */}
                    {hasDiscrepancy && (
                      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-2 p-3 bg-amber-50/90 border border-amber-200 rounded-lg text-xs my-3 text-amber-900 shadow-2xs">
                        <div className="flex items-center gap-2">
                          <AlertTriangle className="h-4 w-4 text-amber-600 shrink-0" />
                          <span>
                            Qwen extracted <b>Option {q.correct_option}</b>, but AIR-1 Blind Solver derived <b>Option {q.solver_option}</b>.
                          </span>
                        </div>
                        <div className="flex items-center gap-2 shrink-0">
                          <button
                            onClick={() => handleSelectAnswer(q.id, q.solver_option)}
                            className="px-2.5 py-1 bg-amber-600 hover:bg-amber-700 text-white font-semibold rounded cursor-pointer transition-colors shadow-2xs"
                          >
                            Set to Solver ({q.solver_option}) & Approve
                          </button>
                          <button
                            onClick={() => handleSelectAnswer(q.id, q.correct_option)}
                            className="px-2.5 py-1 bg-white hover:bg-amber-100 text-amber-800 border border-amber-300 font-semibold rounded cursor-pointer transition-colors"
                          >
                            Keep Extracted ({q.correct_option})
                          </button>
                        </div>
                      </div>
                    )}

                    {/* OPTIONS */}
                    {opts.length > 0 && (
                      <div className="space-y-1 my-3">
                        <div className="text-[11px] font-semibold text-slate-400 uppercase tracking-wider mb-1">
                          Options (Click any option to set as correct answer):
                        </div>
                        <div className="grid grid-cols-1 md:grid-cols-2 gap-2">
                          {opts.map((opt: any, optIdx: number) => {
                            const optLabel = String.fromCharCode(65 + optIdx);
                            const isSelectedCorrectKey = q.correct_option === optLabel;
                            const isSolverKey = q.solver_option === optLabel;

                            return (
                              <div 
                                key={optIdx} 
                                onClick={() => handleSelectAnswer(q.id, optLabel)}
                                title={`Click to set Option ${optLabel} as the correct answer`}
                                className={`p-3 rounded-lg border text-sm flex items-start gap-2.5 cursor-pointer transition-all hover:scale-[1.005] ${
                                  isSelectedCorrectKey 
                                    ? 'bg-emerald-50 border-emerald-400 ring-2 ring-emerald-500/20 text-emerald-950 font-medium'
                                    : 'bg-slate-50/70 border-slate-200 text-slate-800 hover:bg-indigo-50/50 hover:border-indigo-300'
                                }`}
                              >
                                <span className={`font-semibold text-xs rounded px-2 py-0.5 border shrink-0 transition-colors ${
                                  isSelectedCorrectKey ? 'bg-emerald-600 text-white border-emerald-600' : 'bg-white text-slate-700 border-slate-200'
                                }`}>
                                  {optLabel}
                                </span>
                                <div className="grow">
                                  <MathSpan text={typeof opt === 'string' ? opt : (opt.text || '')} />
                                </div>
                                {isSelectedCorrectKey && (
                                  <span className="text-[10px] font-bold uppercase bg-emerald-200 text-emerald-800 px-2 py-0.5 rounded shrink-0 flex items-center gap-1 shadow-2xs">
                                    <Check className="h-3 w-3" /> Correct Answer
                                  </span>
                                )}
                                {isSolverKey && !isSelectedCorrectKey && (
                                  <span className="text-[10px] font-bold uppercase bg-amber-100 text-amber-800 border border-amber-200 px-1.5 py-0.5 rounded shrink-0">
                                    Solver Derived: {optLabel}
                                  </span>
                                )}
                              </div>
                            );
                          })}
                        </div>
                      </div>
                    )}

                    {/* GUARDRAIL FLAW WARNINGS */}
                    {notes.length > 0 && (
                      <div className="p-3 bg-red-50/80 border border-red-200 rounded-lg text-xs text-red-800 my-2">
                        <div className="font-semibold flex items-center gap-1.5 mb-1">
                          <XCircle className="h-3.5 w-3.5" /> Guardrail Issues Detected:
                        </div>
                        <ul className="list-disc list-inside space-y-0.5">
                          {notes.map((n: string, i: number) => (
                            <li key={i}>{n}</li>
                          ))}
                        </ul>
                      </div>
                    )}

                    {/* SOLVER REASONING TOGGLE */}
                    {q.solver_reasoning && (
                      <div className="my-2 border-t border-slate-100 pt-2">
                        <button
                          onClick={() => toggleReasoning(q.id)}
                          className="flex items-center gap-1 text-xs font-semibold text-indigo-600 hover:text-indigo-800 cursor-pointer"
                        >
                          {expandedReasoning[q.id] ? <ChevronDown className="h-3 w-3" /> : <ChevronRight className="h-3 w-3" />}
                          {expandedReasoning[q.id] ? 'Hide Blind Solver Derivation' : 'View AIR-1 Blind Solver Derivation'}
                        </button>
                        {expandedReasoning[q.id] && (
                          <div className="mt-2 p-3 bg-slate-50 border border-slate-200 rounded-lg text-xs text-slate-800 font-mono leading-relaxed">
                            <MathSpan text={q.solver_reasoning} />
                          </div>
                        )}
                      </div>
                    )}

                    {/* ACTION BUTTONS */}
                    <div className="flex items-center justify-end gap-2 pt-3 border-t border-slate-100">
                      <button
                        onClick={() => handleReject(q.id)}
                        disabled={isRejected || isPromoted}
                        className="flex items-center gap-1 px-3 py-1.5 text-xs font-semibold text-red-600 bg-white border border-red-200 rounded-lg hover:bg-red-50 disabled:opacity-40 transition-colors cursor-pointer"
                      >
                        <X className="h-3 w-3" /> Reject
                      </button>
                      <button
                        onClick={() => handleApprove(q.id)}
                        disabled={isApproved || isPromoted}
                        className="flex items-center gap-1 px-3.5 py-1.5 text-xs font-semibold text-emerald-700 bg-emerald-50 border border-emerald-300 rounded-lg hover:bg-emerald-100 disabled:opacity-40 transition-colors cursor-pointer"
                      >
                        <Check className="h-3 w-3" /> Approve for Production
                      </button>
                    </div>
                  </div>
                );
              })}
            </div>
          )}
        </div>
      ) : (
        /* MANIFEST TABLE */
        <div className="bg-white rounded-xl border border-slate-200 overflow-hidden shadow-2xs">
          <div className="p-4 border-b border-slate-200 bg-slate-50 flex items-center justify-between">
            <div className="text-xs font-bold text-slate-700 uppercase tracking-wider">
              Discovered PDF Ingestion Queue
            </div>
            <div className="text-xs text-slate-500">
              Total 801 Chapter & Test PDFs
            </div>
          </div>
          <div className="overflow-x-auto">
            <table className="w-full text-left text-xs">
              <thead className="bg-slate-100/70 text-slate-600 uppercase border-b border-slate-200 font-semibold">
                <tr>
                  <th className="px-4 py-3">#</th>
                  <th className="px-4 py-3">Subject</th>
                  <th className="px-4 py-3">PDF Filename</th>
                  <th className="px-4 py-3">Chapter</th>
                  <th className="px-4 py-3">Status</th>
                  <th className="px-4 py-3 text-right">Extracted</th>
                  <th className="px-4 py-3 text-right">Passed</th>
                  <th className="px-4 py-3 text-right">Tokens</th>
                  <th className="px-4 py-3 text-right">Action</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100 text-slate-700">
                {manifest.map(m => (
                  <tr key={m.id} className="hover:bg-slate-50/50">
                    <td className="px-4 py-2.5 font-mono text-slate-400">{m.id}</td>
                    <td className="px-4 py-2.5 font-semibold text-indigo-700">{m.subject}</td>
                    <td className="px-4 py-2.5 font-medium max-w-xs truncate" title={m.pdf_filename}>{m.pdf_filename}</td>
                    <td className="px-4 py-2.5 text-slate-500">{m.chapter_guess || '—'}</td>
                    <td className="px-4 py-2.5">
                      <span className={`px-2 py-0.5 rounded text-[11px] font-bold ${
                        m.status === 'COMPLETED' ? 'bg-emerald-100 text-emerald-800' :
                        m.status === 'IN_PROGRESS' ? 'bg-indigo-100 text-indigo-800 animate-pulse' :
                        m.status === 'FAILED' ? 'bg-red-100 text-red-800' :
                        'bg-slate-100 text-slate-600'
                      }`}>
                        {m.status}
                      </span>
                    </td>
                    <td className="px-4 py-2.5 text-right font-mono">{m.extracted_questions}</td>
                    <td className="px-4 py-2.5 text-right font-mono text-emerald-600 font-semibold">{m.passed_guardrails}</td>
                    <td className="px-4 py-2.5 text-right font-mono text-purple-600">{Number(m.total_tokens_used || 0).toLocaleString()}</td>
                    <td className="px-4 py-2.5 text-right">
                      {m.status === 'PENDING' ? (
                        <button
                          onClick={() => handleExtractNext(m.pdf_path)}
                          disabled={extracting}
                          className="px-2.5 py-1 bg-violet-50 hover:bg-violet-100 text-violet-700 border border-violet-200 rounded font-semibold text-[11px] cursor-pointer transition-colors shadow-2xs"
                        >
                          Extract Now
                        </button>
                      ) : (
                        <span className="text-slate-400 text-[11px] font-mono">Done</span>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  );
}

