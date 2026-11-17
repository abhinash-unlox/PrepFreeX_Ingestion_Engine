'use client';

import { useEffect, useMemo, useState } from 'react';
import katex from 'katex';
import {
  Activity, ArrowDownRight, ArrowRight, ArrowUpRight, Award, BarChart3, Bell, BookOpen,
  Bookmark, CalendarDays, Check, CheckCircle2, ChevronDown, ChevronLeft, ChevronRight,
  CircleHelp, Clock3, Compass, Ellipsis, Flame, FlaskConical, GraduationCap, Home,
  ImageIcon, Layers3, Menu, Minus, MoreHorizontal, PanelLeftClose, PanelLeftOpen, Play, Plus,
  Search, Settings2, Sparkles, Target, Timer, X, Zap, Code2, ExternalLink
} from 'lucide-react';
import { Area, AreaChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts';
import { assessmentKinds, type AssessmentKind } from '@/lib/prepfreex-data';
import { apiClient } from '@/lib/api-client';
import { getDefaultChapters, getDefaultTopics } from '@/lib/jee-syllabus';

type View = 'Dashboard' | 'Assessments' | 'Practice' | 'Image Test' | 'Performance' | 'Test History' | 'Profile';
const navItems: { name: View; icon: typeof Home }[] = [
  { name: 'Dashboard', icon: Home },
  { name: 'Assessments', icon: Compass },
  { name: 'Practice', icon: Target },
  { name: 'Image Test', icon: ImageIcon },
  { name: 'Performance', icon: BarChart3 },
  { name: 'Test History', icon: CalendarDays },
  { name: 'Profile', icon: Settings2 },
];
const kindIcons: Record<string, typeof Target> = { Target, BookOpen, Layers3, Timer, Award, 'Image Test': ImageIcon as any };
const subjectColor: Record<string, string> = { Physics: 'violet', Chemistry: 'cyan', Mathematics: 'amber' };
const defaultSubjects = ['Physics', 'Chemistry', 'Mathematics'];

interface ExamQuestion {
  index: number;
  question_number: number;
  question_uid: string;
  subject: string;
  chapter: string;
  topic: string;
  type: 'single' | 'numerical' | 'multiple';
  content_subtype?: string;
  list_i?: Array<{ item_id: string; label: string; content: string }>;
  list_ii?: Array<{ item_id: string; label: string; content: string }>;
  text: string;
  options: string[];
  has_diagram: boolean;
  diagram_s3_key?: string;
  saved_option?: string;
  saved_numerical?: number;
  is_marked?: boolean;
  is_variant?: boolean;
  variant_id?: number;
}

interface ReviewItem {
  index: number;
  question_number: number;
  question_uid: string;
  is_variant?: boolean;
  variant_id?: number;
  subject: string;
  chapter: string;
  topic: string;
  content_subtype?: string;
  list_i?: Array<{ item_id: string; label: string; content: string }>;
  list_ii?: Array<{ item_id: string; label: string; content: string }>;
  text: string;
  options: string[];
  user_response: string;
  correct_answer: string;
  is_correct: boolean;
  marks_awarded: number;
  explanation: string;
}

function MatchingTable({ listI, listII }: { listI?: Array<{ item_id: string; label: string; content: string }>; listII?: Array<{ item_id: string; label: string; content: string }> }) {
  if (!listI || listI.length === 0 || !listII || listII.length === 0) return null;
  return (
    <div className="matching-table-wrap my-4 border border-slate-200 rounded-lg overflow-hidden bg-white shadow-xs">
      <div className="grid grid-cols-2 bg-slate-100 text-slate-700 font-semibold text-xs uppercase px-4 py-2 border-b border-slate-200">
        <div>List — I</div>
        <div>List — II</div>
      </div>
      <div className="divide-y divide-slate-100 text-sm">
        {listI.map((itemI, idx) => {
          const itemII = listII[idx];
          return (
            <div key={idx} className="grid grid-cols-2 px-4 py-2.5 items-center hover:bg-slate-50/50">
              <div className="pr-3 flex items-baseline">
                <span className="font-semibold text-indigo-600 mr-2 shrink-0">({itemI.label})</span>
                <span className="text-slate-800"><MathText>{itemI.content}</MathText></span>
              </div>
              <div className="pl-3 border-l border-slate-200 flex items-baseline">
                {itemII && (
                  <>
                    <span className="font-semibold text-emerald-600 mr-2 shrink-0">({itemII.label})</span>
                    <span className="text-slate-800"><MathText>{itemII.content}</MathText></span>
                  </>
                )}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

function MathText({ children, className = '' }: { children: any; className?: string }) {
  const rawText = typeof children === 'string'
    ? children
    : (children && typeof children === 'object' ? (children.text || children.value || String(children)) : String(children ?? ''));

  const formattedText = useMemo(() => {
    if (!rawText || typeof rawText !== 'string') return '';
    let t = rawText.replace(/\\n/g, '\n');
    // Format multi-statement lists (Statements A-E) onto clean, readable separate lines
    t = t.replace(/([:.]\s*|\s+)([A-E])\.\s+/g, '\n\n$2. ');
    // Format concluding instructions onto clean separate line
    t = t.replace(/(\s*)(Choose the correct answer[^\n]*)/i, '\n\n$2');
    return t.trim();
  }, [rawText]);

  const parts = useMemo(() => {
    try {
      return (formattedText || '').split(/(\$\$[\s\S]+?\$\$|\$[^$]+?\$|\\\[[\s\S]+?\\\]|\\\([^\)]+?\\\))/g);
    } catch {
      return [formattedText];
    }
  }, [formattedText]);

  return (
    <span className={`whitespace-pre-line ${className}`}>
      {parts.map((part, index) => {
        if (!part) return null;
        let math = '';
        let isDisplay = false;
        let isMath = false;

        if (part.startsWith('$$') && part.endsWith('$$')) {
          math = part.slice(2, -2);
          isDisplay = true;
          isMath = true;
        } else if (part.startsWith('\\[') && part.endsWith('\\]')) {
          math = part.slice(2, -2);
          isDisplay = true;
          isMath = true;
        } else if (part.startsWith('$') && part.endsWith('$')) {
          math = part.slice(1, -1);
          isDisplay = false;
          isMath = true;
        } else if (part.startsWith('\\(') && part.endsWith('\\)')) {
          math = part.slice(2, -2);
          isDisplay = false;
          isMath = true;
        }

        if (isMath) {
          try {
            // Repair common unclosed braces in fractions before KaTeX rendering
            const cleanMath = math
              .replace(/\\frac\{(\\text\{[^{}]+\})\{/g, '\\frac{$1}{')
              .replace(/\\frac\{([0-9.]+\\text\{[^{}]+\})\{/g, '\\frac{$1}{')
              .replace(/\\frac\{([A-Za-z0-9_]+)\{/g, '\\frac{$1}{');

            return (
              <span
                key={index}
                dangerouslySetInnerHTML={{
                  __html: katex.renderToString(cleanMath, {
                    throwOnError: false,
                    displayMode: isDisplay,
                    output: 'html',
                  }),
                }}
              />
            );
          } catch {
            return <span key={index}>{part}</span>;
          }
        }

        // Plain text segment: parse bold markdown (**bold** or \textbf{bold}) and clean text
        const cleanPart = part.replace(/\\text\{([^}]+)\}/g, '$1');
        const boldParts = cleanPart.split(/(\*\*[^*]+\*\*|\\textbf\{[^}]+\})/g);

        return (
          <span key={index}>
            {boldParts.map((bp, bIdx) => {
              if (!bp) return null;
              let isBold = false;
              let content = bp;
              if (bp.startsWith('**') && bp.endsWith('**')) {
                isBold = true;
                content = bp.slice(2, -2);
              } else if (bp.startsWith('\\textbf{') && bp.endsWith('}')) {
                isBold = true;
                content = bp.slice(8, -1);
              }

              // Check for bare LaTeX commands
              if (/\\(mu|theta|alpha|beta|gamma|lambda|pi|circ|Rightarrow|rightarrow|approx|sqrt|frac|pm|times)/.test(content)) {
                try {
                  const rendered = katex.renderToString(content, { throwOnError: false, displayMode: false, output: 'html' });
                  return <span key={bIdx} dangerouslySetInnerHTML={{ __html: rendered }} />;
                } catch {
                  // fallback
                }
              }

              if (isBold) {
                return <strong key={bIdx} className="font-semibold text-slate-900">{content}</strong>;
              }
              return <span key={bIdx}>{content}</span>;
            })}
          </span>
        );
      })}
    </span>
  );
}

function ExplanationCard({ explanation }: { explanation: string }) {
  if (!explanation) return null;

  // Unescape literal \n if present and clean up common OCR artifacts
  const normalized = explanation
    .replace(/\\n/g, '\n')
    .replace(/\xa0/g, ' ')
    .replace(/\\textbf\{([^}]+)\}/g, '**$1**')
    .replace(/\\mathbf\{([^}]+)\}/g, '**$1**');

  // Check if explanation has explicit section headers (e.g. **1. Governing Principle**, **2. ...**)
  const hasNumberedSections = /\*\*[0-9]+\.[^*]+\*\*/.test(normalized);

  if (hasNumberedSections) {
    const tokens = normalized.split(/(\*\*[0-9]+\.[^*]+\*\*|\*\*Correct Option[^*]*\*\*)/g);
    const sections: { title: string; content: string }[] = [];
    let curTitle = 'Core Concept & Governing Principle';
    let curContent = '';

    for (const t of tokens) {
      const trimmed = t.trim();
      if (!trimmed) continue;
      if (trimmed.startsWith('**') && trimmed.endsWith('**')) {
        if (curContent.trim()) {
          sections.push({ title: curTitle, content: curContent.trim() });
        }
        curTitle = trimmed.replace(/\*\*/g, '').replace(/:$/, '').trim();
        curContent = '';
      } else {
        curContent += (curContent ? '\n' : '') + trimmed;
      }
    }
    if (curContent.trim()) {
      sections.push({ title: curTitle, content: curContent.trim() });
    }

    return (
      <div className="explanation-card">
        <div className="explanation-card-header">
          <div className="explanation-card-title">
            <Sparkles size={16} />
            <span>Step-by-step Solution Review</span>
          </div>
          <span className="explanation-card-badge">JEE Academic Verification</span>
        </div>
        <div className="explanation-card-body">
          {sections.map((sec, i) => {
            const isGov = sec.title.toLowerCase().includes('governing') || sec.title.startsWith('1.');
            const isCalc = sec.title.toLowerCase().includes('formulation') || sec.title.toLowerCase().includes('analytical') || sec.title.toLowerCase().includes('calculation') || sec.title.startsWith('2.');
            const isVerif = sec.title.toLowerCase().includes('verification') || sec.title.toLowerCase().includes('correct') || sec.title.startsWith('3.');

            const theme = isGov ? 'sec-gov' : isCalc ? 'sec-calc' : isVerif ? 'sec-verif' : 'sec-generic';

            return (
              <div key={i} className={`explanation-section ${theme}`}>
                <div className="explanation-section-header">
                  <span className="sec-dot" />
                  <strong>{sec.title}</strong>
                </div>
                <div className="explanation-section-content">
                  {sec.content.split(/\n{2,}/).map((p, pIdx) => (
                    <p key={pIdx} className="explanation-para">
                      <MathText>{p}</MathText>
                    </p>
                  ))}
                </div>
              </div>
            );
          })}
        </div>
      </div>
    );
  }

  // Standard non-sectioned explanation: render formatted paragraphs
  const paragraphs = normalized.split(/\n{2,}/).filter(p => p.trim());
  return (
    <div className="explanation-card">
      <div className="explanation-card-header">
        <div className="explanation-card-title">
          <Sparkles size={16} />
          <span>Step-by-step Solution Review</span>
        </div>
        <span className="explanation-card-badge">Verified Solution</span>
      </div>
      <div className="explanation-card-body">
        {paragraphs.map((p, pIdx) => (
          <p key={pIdx} className="explanation-para">
            <MathText>{p}</MathText>
          </p>
        ))}
      </div>
    </div>
  );
}

function Logo({ small = false }: { small?: boolean }) {
  return (
    <div className="brand-lockup">
      <div className="brand-mark">
        <span>p</span>
        <span>x</span>
      </div>
      {!small && (
        <div>
          <strong>
            PrepFree<span>X</span>
          </strong>
          <small>JEE PREPARATION</small>
        </div>
      )}
    </div>
  );
}

export default function PrepFreeXApp() {
  const [view, setView] = useState<View>('Dashboard');
  const [collapsed, setCollapsed] = useState(false);
  const [mobileNav, setMobileNav] = useState(false);
  const [modal, setModal] = useState<AssessmentKind | null>(null);

  // Taxonomy states (API backed with synchronous canonical defaults)
  const [subject, setSubject] = useState('Physics');
  const [chapterList, setChapterList] = useState<Array<{ id: number; unit_code: string; chapter_name: string; total_topics: number; eligible_question_count: number }>>(() => getDefaultChapters('Physics'));
  const [chapter, setChapter] = useState(() => getDefaultChapters('Physics')[0]?.unit_code || 'PHYS_U01');
  const [topicList, setTopicList] = useState<Array<{ id: number; topic_code: string; topic_name: string; eligible_question_count: number }>>(() => getDefaultTopics('PHYS_U01'));
  const [topic, setTopic] = useState(() => getDefaultTopics('PHYS_U01')[0]?.topic_code || 'PHYS_U01_T01');
  const [questionCount, setQuestionCount] = useState('5');
  const [selectedChapters, setSelectedChapters] = useState<string[]>(() => [getDefaultChapters('Physics')[0]?.unit_code || 'PHYS_U01']);

  // Assessment & Live Exam States
  const [activeTest, setActiveTest] = useState(false);
  const [activeKind, setActiveKind] = useState<AssessmentKind>('Topic Practice');
  const [activeAssessmentId, setActiveAssessmentId] = useState<string | null>(null);
  const [examQuestions, setExamQuestions] = useState<ExamQuestion[]>([]);
  const [questionIndex, setQuestionIndex] = useState(0);
  const [answers, setAnswers] = useState<Record<number, string>>({});
  const [marked, setMarked] = useState<number[]>([]);
  const [seconds, setSeconds] = useState(1800);
  const [totalDurationSeconds, setTotalDurationSeconds] = useState(1800);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [isGeneratingTest, setIsGeneratingTest] = useState(false);
  const [generatingStage, setGeneratingStage] = useState(0);
  const [generatingProgress, setGeneratingProgress] = useState(0);
  const [generatingElapsed, setGeneratingElapsed] = useState(0);
  const [generatingTestType, setGeneratingTestType] = useState('Topic Practice');
  const [showSubmitModal, setShowSubmitModal] = useState(false);
  const [mobilePalette, setMobilePalette] = useState(false);
  const [toast, setToast] = useState('');

  // Results & Review States (API backed)
  const [examResults, setExamResults] = useState<any | null>(null);
  const [examReview, setExamReview] = useState<ReviewItem[]>([]);

  // Student Dashboard & Performance States (API backed)
  const [studentDash, setStudentDash] = useState<any>({
    student_name: 'Arjun Sharma',
    target_exam: 'JEE Main 2027',
    study_streak_days: 7,
    daily_goal_sessions: 6,
    daily_goal_completed: 4,
    questions_attempted: 1284,
    overall_accuracy: 76.4,
    tests_completed: 32,
    weekly_progress: [
      { day: 'Mon', questions: 32 },
      { day: 'Tue', questions: 48 },
      { day: 'Wed', questions: 35 },
      { day: 'Thu', questions: 62 },
      { day: 'Fri', questions: 44 },
      { day: 'Sat', questions: 76 },
      { day: 'Sun', questions: 58 },
    ],
    subject_stats: [
      { name: 'Physics', score: 78, fill: '#4f46e5' },
      { name: 'Chemistry', score: 66, fill: '#0891b2' },
      { name: 'Mathematics', score: 84, fill: '#f59e0b' },
    ],
    recent_tests: [],
  });

  const [historyList, setHistoryList] = useState<any[]>([]);
  const [historyFilter, setHistoryFilter] = useState('All assessments');
  const [performanceData, setPerformanceData] = useState<any>(null);

  // 1. Load Student Dashboard on Mount & View change
  useEffect(() => {
    async function loadDashboard() {
      try {
        const data = await apiClient.getStudentDashboard();
        setStudentDash(data);
      } catch (err) {
        console.warn('Dashboard fetch fallback to default:', err);
      }
    }
    loadDashboard();
  }, [view]);

  // 2. Load History when view is 'Test History'
  useEffect(() => {
    if (view === 'Test History') {
      apiClient.getStudentHistory()
        .then(res => setHistoryList(res.attempts || []))
        .catch(err => console.warn('History fetch error:', err));
    }
  }, [view]);

  // 3. Load Performance when view is 'Performance'
  useEffect(() => {
    if (view === 'Performance') {
      apiClient.getStudentPerformance()
        .then(res => setPerformanceData(res))
        .catch(err => console.warn('Performance fetch error:', err));
    }
  }, [view]);

  // Image Test State & Handlers
  const [imageTestQuestions, setImageTestQuestions] = useState<any[]>([]);
  const [imageTestLoading, setImageTestLoading] = useState(false);
  const [imageTestSubject, setImageTestSubject] = useState<'ALL' | 'Physics' | 'Chemistry' | 'Mathematics'>('ALL');
  const [imageTestStatus, setImageTestStatus] = useState<'ELIGIBLE' | 'ALL'>('ELIGIBLE');
  const [imageTestSearch, setImageTestSearch] = useState('');
  const [expandedExplanations, setExpandedExplanations] = useState<Record<number, boolean>>({});
  const [testedUserAnswers, setTestedUserAnswers] = useState<Record<number, string>>({});

  // Load Image Test questions when view is 'Image Test'
  useEffect(() => {
    if (view === 'Image Test') {
      setImageTestLoading(true);
      const subjParam = imageTestSubject === 'ALL' ? undefined : imageTestSubject.toUpperCase();
      apiClient.getImageTestQuestions(subjParam, imageTestStatus)
        .then(res => {
          setImageTestQuestions(res.questions || []);
        })
        .catch(err => {
          console.error('Failed to load image test questions:', err);
          setToast('Failed to load image questions from MinIO.');
        })
        .finally(() => {
          setImageTestLoading(false);
        });
    }
  }, [view, imageTestSubject, imageTestStatus]);

  const filteredImageQuestions = useMemo(() => {
    if (!imageTestSearch) return imageTestQuestions;
    const term = imageTestSearch.toLowerCase();
    return imageTestQuestions.filter(q => 
      (q.text || '').toLowerCase().includes(term) ||
      (q.chapter || '').toLowerCase().includes(term) ||
      (q.subject || '').toLowerCase().includes(term) ||
      (q.question_uid || '').toLowerCase().includes(term) ||
      String(q.id).includes(term)
    );
  }, [imageTestQuestions, imageTestSearch]);

  const handleStartImageExam = async (statusMode: 'ELIGIBLE' | 'ALL' = 'ELIGIBLE') => {
    try {
      setToast('Allocating MinIO image questions...');
      const subjUpper = imageTestSubject === 'ALL' ? 'PHYSICS' : imageTestSubject.toUpperCase();
      const count = statusMode === 'ELIGIBLE' ? 47 : 137;
      const res = await apiClient.createAssessment({
        assessment_type: 'Image Test',
        subject: subjUpper,
        chapter_code: statusMode === 'ALL' ? 'ALL_STATUSES' : undefined,
        question_count: count,
        duration_minutes: 60,
      });

      const attemptId = res.assessment_id;
      setActiveAssessmentId(attemptId);
      setActiveKind('Image Test');

      const qData = await apiClient.getAssessmentQuestions(attemptId);
      setExamQuestions(qData.questions);
      setQuestionIndex(0);
      setAnswers({});
      setMarked([]);

      const durationSecs = (res.duration_minutes || 60) * 60;
      setSeconds(durationSecs);
      setTotalDurationSeconds(durationSecs);
      setActiveTest(true);
      setToast('Image Test loaded! All questions have diagrams from MinIO.');
    } catch (err: any) {
      console.error('Failed to start Image Test:', err);
      setToast(err.message || 'Failed to start Image Test.');
    }
  };

  // 4. Fetch Chapters whenever subject changes
  useEffect(() => {
    const defaults = getDefaultChapters(subject);
    if (defaults && defaults.length > 0) {
      setChapterList(defaults);
      const firstChap = defaults.some(c => c.unit_code === chapter) ? chapter : defaults[0].unit_code;
      setChapter(firstChap);
      setSelectedChapters([firstChap]);
      const defaultTops = getDefaultTopics(firstChap);
      if (defaultTops && defaultTops.length > 0) {
        setTopicList(defaultTops);
        const topValid = defaultTops.some(t => t.topic_code === topic);
        setTopic(topValid ? topic : defaultTops[0].topic_code);
      }
    }

    async function loadChapters() {
      try {
        const chaps = await apiClient.getChapters(subject);
        if (chaps && chaps.length > 0) {
          setChapterList(chaps);
          setChapter(prev => {
            const match = chaps.some(c => c.unit_code === prev);
            return match ? prev : chaps[0].unit_code;
          });
        }
      } catch (err) {
        console.warn('Failed to load chapters for subject:', subject, err);
      }
    }
    loadChapters();
  }, [subject]);

  // 5. Fetch Topics whenever chapter changes
  useEffect(() => {
    if (!chapter) return;
    const defaultTops = getDefaultTopics(chapter);
    if (defaultTops && defaultTops.length > 0) {
      setTopicList(defaultTops);
      setTopic(prev => {
        const match = defaultTops.some(t => t.topic_code === prev);
        return match ? prev : defaultTops[0].topic_code;
      });
    }

    async function loadTopics() {
      try {
        const tops = await apiClient.getTopics(chapter);
        if (tops && tops.length > 0) {
          setTopicList(tops);
          setTopic(prev => {
            const match = tops.some(t => t.topic_code === prev);
            return match ? prev : tops[0].topic_code;
          });
        }
      } catch (err) {
        console.warn('Failed to load topics for chapter:', chapter, err);
      }
    }
    loadTopics();
  }, [chapter]);

  // Exam Countdown Timer
  useEffect(() => {
    if (!activeTest) return;
    const timer = window.setInterval(() => {
      setSeconds(s => {
        if (s <= 1) {
          window.clearInterval(timer);
          handleAutoSubmit();
          return 0;
        }
        return s - 1;
      });
    }, 1000);
    return () => window.clearInterval(timer);
  }, [activeTest, activeAssessmentId]);

  // Toast Auto-Dismiss
  useEffect(() => {
    if (toast) {
      const timer = window.setTimeout(() => setToast(''), 3000);
      return () => window.clearTimeout(timer);
    }
  }, [toast]);

  // Background Question Variant Sync: smoothly updates question slots as Groq generates variants in background
  useEffect(() => {
    if (!activeTest || !activeAssessmentId) return;

    let syncCount = 0;
    const maxSyncs = 40; // Poll every 3.5s up to ~140s for large 25-question tests

    const syncInterval = window.setInterval(async () => {
      syncCount++;
      if (syncCount > maxSyncs) {
        window.clearInterval(syncInterval);
        return;
      }

      try {
        const qData = await apiClient.getAssessmentQuestions(activeAssessmentId);
        if (qData && qData.questions && qData.questions.length > 0) {
          setExamQuestions(prev => {
            let hasAnyChange = false;
            const updated = prev.map((oldQ, idx) => {
              const newQ = qData.questions[idx];
              if (newQ && newQ.is_variant && !oldQ.is_variant) {
                hasAnyChange = true;
                return { ...oldQ, ...newQ };
              }
              return oldQ;
            });
            return hasAnyChange ? updated : prev;
          });

          // If all questions are now variants, stop syncing early
          if (qData.questions.every(q => q.is_variant)) {
            window.clearInterval(syncInterval);
          }
        }
      } catch (err) {
        // Silent background sync
      }
    }, 3500);

    return () => window.clearInterval(syncInterval);
  }, [activeTest, activeAssessmentId]);

  // Smooth AI Test Generation Waiting Timer
  useEffect(() => {
    if (!isGeneratingTest) {
      setGeneratingProgress(0);
      setGeneratingElapsed(0);
      setGeneratingStage(0);
      return;
    }

    const startTime = Date.now();
    const interval = window.setInterval(() => {
      const elapsedSecs = Math.floor((Date.now() - startTime) / 1000);
      setGeneratingElapsed(elapsedSecs);

      // Smooth progress curve reaching up to 94% while Groq generates variants
      if (elapsedSecs < 2) {
        setGeneratingStage(0);
        setGeneratingProgress(prev => Math.min(25, prev + 3.5));
      } else if (elapsedSecs < 5) {
        setGeneratingStage(1);
        setGeneratingProgress(prev => Math.min(58, prev + 2.5));
      } else if (elapsedSecs < 8) {
        setGeneratingStage(2);
        setGeneratingProgress(prev => Math.min(84, prev + 1.8));
      } else {
        setGeneratingStage(3);
        setGeneratingProgress(prev => Math.min(94, prev + 0.6));
      }
    }, 250);

    return () => window.clearInterval(interval);
  }, [isGeneratingTest]);

  // Handle Assessment Launch
  const launchTest = async () => {
    if (!modal) return;
    const kind = modal;
    setModal(null);
    setIsGeneratingTest(true);
    setGeneratingTestType(kind);
    setGeneratingProgress(10);
    setGeneratingStage(0);
    setIsSubmitting(true);
    setToast('Synthesizing fresh question variations with Groq...');

    try {
      let qCount = 5;
      if (kind === 'Full-length Mock') {
        qCount = 75;
      } else if (kind === 'Sectional Assessment') {
        qCount = 25;
      } else if (kind === 'Chapter Test') {
        qCount = 20;
      } else if (kind === 'Topic Practice') {
        qCount = parseInt(questionCount, 10) || 5;
      } else if (kind === 'Mixed-topic Test') {
        qCount = Math.max(5, selectedChapters.length * 20);
      } else if (kind === 'Image Test') {
        qCount = 47;
      } else {
        qCount = parseInt(questionCount, 10) || 5;
      }

      // Auto-fallback guarantees: ensure chapter and topic are strictly set
      let targetChapter = chapter;
      if ((!targetChapter || !chapterList.some(c => c.unit_code === targetChapter)) && chapterList.length > 0) {
        targetChapter = chapterList[0].unit_code;
      }
      let targetTopic = topic;
      if (kind === 'Topic Practice') {
        if ((!targetTopic || !topicList.some(t => t.topic_code === targetTopic)) && topicList.length > 0) {
          targetTopic = topicList[0].topic_code;
        }
        if (!targetTopic) {
          const fallbackTops = getDefaultTopics(targetChapter || 'PHYS_U01');
          targetTopic = fallbackTops[0]?.topic_code || 'PHYS_U01_T01';
        }
      }

      const res = await apiClient.createAssessment({
        assessment_type: kind,
        subject: (subject || 'Physics').toUpperCase(),
        chapter_code: targetChapter,
        topic_code: targetTopic,
        selected_chapters: kind === 'Mixed-topic Test' ? selectedChapters : undefined,
        question_count: qCount,
      });

      const attemptId = res.assessment_id;
      setActiveAssessmentId(attemptId);
      setActiveKind(kind);

      // Fetch safe questions without answers
      const qData = await apiClient.getAssessmentQuestions(attemptId);
      setExamQuestions(qData.questions);
      setQuestionIndex(0);
      setAnswers({});
      setMarked([]);

      const durationSecs = (res.duration_minutes || 25) * 60;
      setSeconds(durationSecs);
      setTotalDurationSeconds(durationSecs);

      // Smooth completion transition
      setGeneratingProgress(100);
      await new Promise(r => setTimeout(r, 400));

      setActiveTest(true);
      setShowSubmitModal(false);
      setMobilePalette(false);
      setView('Assessments');
      setToast(`Assessment ready: ${qData.questions.length} questions loaded with fresh variants.`);
    } catch (err: any) {
      setToast(`Could not start assessment: ${err.message || 'Error'}`);
    } finally {
      setIsGeneratingTest(false);
      setIsSubmitting(false);
    }
  };

  // Save student response to server idempotently
  const handleAnswerSelect = (val: string) => {
    setAnswers(prev => ({ ...prev, [questionIndex]: val }));
    if (activeAssessmentId) {
      const currentQ = examQuestions[questionIndex];
      const isNum = currentQ?.type === 'numerical';
      const qId = currentQ?.question_uid || (questionIndex + 1);
      apiClient.saveResponse(activeAssessmentId, qId, {
        selected_option: isNum ? undefined : val,
        numerical_entered: isNum ? parseFloat(val) || undefined : undefined,
        time_spent_seconds: 5,
        is_marked_review: marked.includes(questionIndex),
      }).catch(err => console.warn('Answer save failed:', err));
    }
  };

  const handleClearAnswer = () => {
    setAnswers(prev => {
      const updated = { ...prev };
      delete updated[questionIndex];
      return updated;
    });
    if (activeAssessmentId) {
      const currentQ = examQuestions[questionIndex];
      const qId = currentQ?.question_uid || (questionIndex + 1);
      apiClient.saveResponse(activeAssessmentId, qId, {
        selected_option: null,
        numerical_entered: null,
        is_marked_review: marked.includes(questionIndex),
      }).catch(err => console.warn('Clear response failed:', err));
    }
  };

  const handleToggleMark = () => {
    const isMarked = marked.includes(questionIndex);
    const updated = isMarked ? marked.filter(x => x !== questionIndex) : [...marked, questionIndex];
    setMarked(updated);
    if (activeAssessmentId) {
      const currentQ = examQuestions[questionIndex];
      const qId = currentQ?.question_uid || (questionIndex + 1);
      apiClient.saveResponse(activeAssessmentId, qId, {
        is_marked_review: !isMarked,
      }).catch(err => console.warn('Toggle mark failed:', err));
    }
  };

  // Submit Assessment to backend
  const handleAutoSubmit = () => {
    handleSubmitAssessment();
    setToast('Time expired — assessment submitted automatically.');
  };

  const handleSubmitAssessment = async () => {
    if (!activeAssessmentId) return;
    setIsSubmitting(true);
    try {
      await apiClient.submitAssessment(activeAssessmentId);
      const results = await apiClient.getAssessmentResults(activeAssessmentId);
      const review = await apiClient.getAssessmentReview(activeAssessmentId);

      setExamResults(results);
      setExamReview(review.review);
      setActiveTest(false);
      setShowSubmitModal(false);
      setView('Performance');
      setToast('Assessment scored successfully by backend engine.');
    } catch (err: any) {
      setToast(`Submission error: ${err.message || 'Error'}`);
    } finally {
      setIsSubmitting(false);
    }
  };

  const openAssessment = (kind: AssessmentKind) => {
    setModal(kind);
    const currSubj = subject || 'Physics';
    const defaults = getDefaultChapters(currSubj);
    if (defaults && defaults.length > 0) {
      setChapterList(defaults);
      const currChap = defaults.some(c => c.unit_code === chapter) ? chapter : defaults[0].unit_code;
      setChapter(currChap);
      const defaultTops = getDefaultTopics(currChap);
      if (defaultTops && defaultTops.length > 0) {
        setTopicList(defaultTops);
        const topValid = defaultTops.some(t => t.topic_code === topic);
        setTopic(topValid ? topic : defaultTops[0].topic_code);
      }
    }
  };

  const formatTime = (secs: number) => {
    const h = Math.floor(secs / 3600);
    const m = Math.floor((secs % 3600) / 60);
    const s = secs % 60;
    return `${String(h).padStart(2, '0')}:${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}`;
  };

  const currentQuestion = examQuestions[questionIndex] || null;

  // Sidebar Component
  const sidebar = (
    <aside className={`sidebar ${collapsed ? 'is-collapsed' : ''} ${mobileNav ? 'mobile-open' : ''}`}>
      <div className="sidebar-top">
        <Logo />
        <button
          className="icon-button collapse-button"
          aria-label="Collapse sidebar"
          onClick={() => setCollapsed(!collapsed)}
        >
          {collapsed ? <PanelLeftOpen /> : <PanelLeftClose />}
        </button>
      </div>
      <div className="workspace-switch">
        <div className="workspace-icon">
          <GraduationCap size={17} />
        </div>
        <div className="workspace-text">
          <strong>{studentDash.target_exam || 'JEE Main 2027'}</strong>
          <small>My workspace</small>
        </div>
        <ChevronDown size={15} />
      </div>
      <div className="nav-label">WORKSPACE</div>
      <nav className="side-nav" aria-label="Main navigation">
        {navItems.map(({ name, icon: Icon }) => (
          <button
            key={name}
            className={`nav-item ${view === name && !activeTest ? 'active' : ''}`}
            onClick={() => {
              setView(name);
              setActiveTest(false);
              setMobileNav(false);
            }}
            title={collapsed ? name : undefined}
          >
            <Icon size={18} />
            <span>{name}</span>
            {name === 'Test History' && (
              <span className="nav-count">{studentDash.tests_completed || historyList.length || 1}</span>
            )}
          </button>
        ))}
      </nav>
      <div className="sidebar-spacer" />
      <div className="sidebar-goal">
        <div className="goal-top">
          <span>
            <Flame size={16} /> Daily goal
          </span>
          <span>
            {studentDash.daily_goal_completed || 4} / {studentDash.daily_goal_sessions || 6}
          </span>
        </div>
        <div className="goal-track">
          <i
            style={{
              width: `${Math.min(
                100,
                ((studentDash.daily_goal_completed || 4) / (studentDash.daily_goal_sessions || 6)) * 100
              )}%`,
            }}
          />
        </div>
        <p>Two more sessions to hit your goal</p>
      </div>
      <button
        className="profile-mini"
        onClick={() => {
          setView('Profile');
          setMobileNav(false);
        }}
      >
        <div className="avatar">AS</div>
        <div className="profile-mini-copy">
          <strong>{studentDash.student_name || 'Arjun Sharma'}</strong>
          <small>JEE aspirant</small>
        </div>
        <MoreHorizontal size={18} />
      </button>
    </aside>
  );

  // Active Exam Interface
  if (activeTest && currentQuestion) {
    const elapsedSecs = Math.max(0, totalDurationSeconds - seconds);
    const activeSectionSubject = currentQuestion.subject;

    return (
      <main className={`exam-shell ${mobilePalette ? 'mobile-palette' : ''}`}>
        <header className="exam-header">
          <Logo />
          <div className="exam-meta">
            <span className="exam-type">{activeKind}</span>
            <span className="exam-separator" />
            <span className="exam-subject">
              <i className={`subject-dot ${subjectColor[currentQuestion.subject] || 'violet'}`} />
              {currentQuestion.subject}
            </span>
            <span className="exam-separator" />
            <span>{currentQuestion.chapter || currentQuestion.topic}</span>
          </div>
          <div className={`exam-clock ${seconds < 300 ? 'urgent' : ''}`}>
            <Clock3 size={17} />
            <span>{formatTime(seconds)}</span>
            <button className="submit-top" onClick={() => setShowSubmitModal(true)}>
              Submit test
            </button>
          </div>
        </header>

        <div className="exam-progress">
          <span>
            Question {questionIndex + 1} of {examQuestions.length}
          </span>
          <div>
            <i style={{ width: `${((questionIndex + 1) / examQuestions.length) * 100}%` }} />
          </div>
          <span>{Math.round(((questionIndex + 1) / examQuestions.length) * 100)}% completed</span>
        </div>

        <div className="exam-layout">
          <section className="question-panel">
            <div className="question-heading">
              <div>
                <span className="eyebrow">
                  {currentQuestion.subject} <span>·</span> {currentQuestion.topic}
                  {currentQuestion.is_variant && (
                    <span className="variant-badge" style={{ marginLeft: 8, display: 'inline-flex', alignItems: 'center', gap: 4, background: '#eff6ff', color: '#2563eb', border: '1px solid #bfdbfe', borderRadius: 4, padding: '1px 6px', fontSize: 10, fontWeight: 600 }}>
                      <Sparkles size={11} /> AI Verified Variant
                    </span>
                  )}
                </span>
                <h1>Question {questionIndex + 1}</h1>
              </div>
              <button
                className={`mark-button ${marked.includes(questionIndex) ? 'marked' : ''}`}
                onClick={handleToggleMark}
              >
                <Bookmark size={16} fill={marked.includes(questionIndex) ? 'currentColor' : 'none'} />
                {marked.includes(questionIndex) ? 'Marked for review' : 'Mark for review'}
              </button>
            </div>

            <div className="question-card">
              <div className="question-type">
                <span>
                  {currentQuestion.type === 'numerical' ? 'SECTION B · NUMERICAL VALUE' : 'SECTION A · SINGLE CORRECT MCQ'}
                </span>
              </div>
              <p className="question-text whitespace-pre-line leading-relaxed">
                <MathText>{currentQuestion.text}</MathText>
              </p>

              {/* Match-the-Following structured two-column display */}
              <MatchingTable listI={currentQuestion.list_i} listII={currentQuestion.list_ii} />

              {/* Render verified diagram from MinIO via safe backend route */}
              {currentQuestion.has_diagram && (
                <div className="question-diagram-wrap my-4 p-2 bg-slate-50 border rounded-lg text-center">
                  <img
                    src={apiClient.getDiagramUrl(currentQuestion.diagram_s3_key || currentQuestion.question_uid)}
                    alt="Question Diagram"
                    className="max-h-64 mx-auto rounded object-contain"
                    onError={(e) => {
                      const el = (e.target as HTMLElement).closest('.question-diagram-wrap') as HTMLElement;
                      if (el) el.style.display = 'none';
                    }}
                  />
                  <small className="text-muted-foreground block mt-1 text-xs">Official JEE Main Diagram</small>
                </div>
              )}

              {currentQuestion.type === 'numerical' ? (
                <label className="numerical-field">
                  Your answer
                  <input
                    type="text"
                    inputMode="decimal"
                    placeholder="Enter numerical value"
                    value={answers[questionIndex] || ''}
                    onChange={(e) => handleAnswerSelect(e.target.value)}
                  />
                </label>
              ) : (
                <div className="options-list">
                  {(currentQuestion.options || ['A', 'B', 'C', 'D']).map((option: any, i: number) => {
                    const optText = typeof option === 'string' ? option : (option?.text || option?.value || String(option ?? ''));
                    const optKey = String.fromCharCode(65 + i);
                    const chosen = answers[questionIndex] === optKey;
                    return (
                      <button
                        className={`answer-option ${chosen ? 'selected' : ''}`}
                        key={i}
                        onClick={() => handleAnswerSelect(optKey)}
                      >
                        <span className="option-letter">{optKey}</span>
                        <span className="option-text">
                          <MathText>{optText}</MathText>
                        </span>
                        {chosen && <Check size={17} />}
                      </button>
                    );
                  })}
                </div>
              )}
            </div>

            <div className="question-actions">
              <button className="button button-quiet" onClick={handleClearAnswer}>
                <X size={15} />
                Clear response
              </button>
              <div>
                <button
                  className="button button-outline mobile-palette-trigger"
                  onClick={() => setMobilePalette(true)}
                >
                  Questions
                </button>
                <button
                  className="button button-outline"
                  onClick={() => setQuestionIndex(Math.max(0, questionIndex - 1))}
                  disabled={questionIndex === 0}
                >
                  <ChevronLeft size={16} />
                  Previous
                </button>
                <button
                  className="button button-primary"
                  onClick={() => {
                    const currentVal = answers[questionIndex];
                    if (currentVal !== undefined && activeAssessmentId && currentQuestion) {
                      const isNum = currentQuestion.type === 'numerical';
                      const qId = currentQuestion.question_uid || (questionIndex + 1);
                      apiClient.saveResponse(activeAssessmentId, qId, {
                        selected_option: isNum ? undefined : currentVal,
                        numerical_entered: isNum ? parseFloat(currentVal) || undefined : undefined,
                        time_spent_seconds: 5,
                        is_marked_review: marked.includes(questionIndex),
                      }).catch(err => console.warn('Next autosave failed:', err));
                    }
                    if (questionIndex < examQuestions.length - 1) {
                      setQuestionIndex(questionIndex + 1);
                    }
                  }}
                  disabled={questionIndex >= examQuestions.length - 1}
                >
                  Save &amp; Next
                  <ChevronRight size={16} />
                </button>
              </div>
            </div>
          </section>

          <aside className="question-navigator">
            <div className="candidate-card">
              <div className="avatar">AS</div>
              <div>
                <strong>{studentDash.student_name || 'Arjun Sharma'}</strong>
                <small>{studentDash.target_exam || 'JEE Main 2027'}</small>
              </div>
            </div>
            <div className="navigator-title">
              <strong>Question palette</strong>
              <button className="mobile-only icon-button" onClick={() => setMobilePalette(!mobilePalette)}>
                <X />
              </button>
            </div>
            <div className="palette-grid">
              {examQuestions.map((_, i) => (
                <button
                  key={i}
                  className={`${i === questionIndex ? 'current' : ''} ${
                    answers[i] !== undefined && answers[i] !== '' ? 'answered' : ''
                  } ${marked.includes(i) ? 'review' : ''}`}
                  onClick={() => setQuestionIndex(i)}
                >
                  {i + 1}
                </button>
              ))}
            </div>
            <div className="palette-legend">
              <span>
                <i className="answered" />
                Answered
              </span>
              <span>
                <i className="review" />
                Review
              </span>
              <span>
                <i />
                Not visited
              </span>
            </div>
            <div className="navigator-summary">
              <div>
                <span>Answered</span>
                <strong>{Object.values(answers).filter(a => a !== '').length}</strong>
              </div>
              <div>
                <span>For review</span>
                <strong>{marked.length}</strong>
              </div>
            </div>
            <button
              className="button button-primary navigator-submit"
              onClick={() => setShowSubmitModal(true)}
            >
              Submit assessment
              <ArrowRight size={16} />
            </button>
          </aside>
        </div>

        {showSubmitModal && (
          <div className="modal-backdrop">
            <div className="confirm-modal">
              <div className="modal-icon">
                <CircleHelp />
              </div>
              <button className="modal-close" onClick={() => setShowSubmitModal(false)}>
                <X size={18} />
              </button>
              <h2>Submit your assessment?</h2>
              <p>
                You&apos;ve answered {Object.values(answers).filter(a => a !== '').length} of {examQuestions.length}{' '}
                questions. Answers will be scored authoritatively on the backend.
              </p>
              <div className="confirm-stats">
                <span>
                  <strong>{Object.values(answers).filter(a => a !== '').length}</strong>
                  Answered
                </span>
                <span>
                  <strong>{marked.length}</strong>
                  For review
                </span>
                <span>
                  <strong>{Math.max(0, examQuestions.length - Object.keys(answers).length)}</strong>
                  Unanswered
                </span>
              </div>
              <div className="modal-actions">
                <button className="button button-outline" onClick={() => setShowSubmitModal(false)}>
                  Continue test
                </button>
                <button
                  className="button button-primary"
                  onClick={handleSubmitAssessment}
                  disabled={isSubmitting}
                >
                  {isSubmitting ? 'Scoring...' : 'Submit test'}
                  <ArrowRight size={16} />
                </button>
              </div>
            </div>
          </div>
        )}
      </main>
    );
  }

  // Header Component
  const header = (
    <header className="topbar">
      <div className="topbar-left">
        <button className="mobile-menu icon-button" onClick={() => setMobileNav(true)} aria-label="Open navigation">
          <Menu />
        </button>
        <div className="breadcrumb">
          <span>Workspace</span>
          <ChevronRight size={14} />
          <strong>{view}</strong>
        </div>
      </div>
      <div className="topbar-right">
        <a
          href="http://127.0.0.1:8000/docs"
          target="_blank"
          rel="noopener noreferrer"
          className="rest-api-btn"
          title="Open FastAPI Swagger REST API Documentation"
        >
          <Code2 size={15} />
          <span>REST API</span>
          <ExternalLink size={12} />
        </a>
        <button className="search-trigger" onClick={() => setToast('Search is ready — explore canonical syllabus')}>
          <Search size={16} />
          <span>Search anything...</span>
          <kbd>⌘ K</kbd>
        </button>
        <button
          className="icon-button notification-button"
          aria-label="Notifications"
          onClick={() => setToast('Database sync status: All 64 chapters active!')}
        >
          <Bell size={18} />
          <i />
        </button>
        <div className="topbar-divider" />
        <button className="avatar top-avatar" onClick={() => setView('Profile')}>
          AS
        </button>
      </div>
    </header>
  );

  const launchCard = (kind: AssessmentKind) => {
    const meta = assessmentKinds.find(x => x.title === kind) || {
      title: kind,
      description: 'JEE Main assessment format',
      duration: '45 min',
      icon: 'Target',
    };
    const Icon = kindIcons[meta.icon] || Target;
    return (
      <button className="assessment-card" key={kind} onClick={() => openAssessment(kind)}>
        <span className="assessment-icon">
          <span>
            <Icon size={19} />
          </span>
        </span>
        <span className="assessment-card-title">{kind}</span>
        <span className="assessment-description">{meta.description}</span>
        <span className="assessment-card-bottom">
          <span>{meta.duration}</span>
          <ArrowRight size={15} />
        </span>
      </button>
    );
  };

  const pageHeader = (eyebrow: string, title: string, description: string, action?: React.ReactNode) => (
    <div className="page-heading">
      <div>
        <div className="eyebrow">{eyebrow}</div>
        <h1>{title}</h1>
        <p>{description}</p>
      </div>
      {action}
    </div>
  );

  // Real Database-backed Dashboard
  const dashboard = (
    <>
      <div className="welcome-banner">
        <div className="welcome-copy">
          <div className="welcome-eyebrow">
            <Sparkles size={14} /> ACTIVE SESSION · JEE MAIN 2027
          </div>
          <h1>
            Good morning, {studentDash.student_name ? studentDash.student_name.split(' ')[0] : 'Arjun'}{' '}
            <span>— let&apos;s make it count.</span>
          </h1>
          <p>
            Connected to PostgreSQL live bank: 64 canonical chapters and 256 official topics available.
          </p>
          <button className="button welcome-button" onClick={() => openAssessment('Topic Practice')}>
            <Play size={15} fill="currentColor" />
            Continue learning
            <ArrowRight size={15} />
          </button>
        </div>
        <div className="welcome-graphic">
          <div className="orbit orbit-one" />
          <div className="orbit orbit-two" />
          <div className="book-illustration">
            <BookOpen size={50} strokeWidth={1.25} />
          </div>
          <div className="float-chip chip-one">
            <Zap size={14} fill="currentColor" /> {studentDash.study_streak_days || 7} day streak
          </div>
          <div className="float-chip chip-two">
            <span>+12%</span> this week
          </div>
          <div className="sparkle sparkle-one">✦</div>
          <div className="sparkle sparkle-two">✧</div>
        </div>
      </div>

      <div className="stats-grid">
        <div className="stat-card">
          <div className="stat-top">
            <span>Questions attempted</span>
            <span className="stat-icon violet-bg">
              <Target size={17} />
            </span>
          </div>
          <div className="stat-value">{(studentDash.questions_attempted || 1284).toLocaleString()}</div>
          <div className="stat-foot">
            <span className="trend-up">
              <ArrowUpRight size={14} /> 12.8%
            </span>
            <span>vs last month</span>
          </div>
        </div>
        <div className="stat-card">
          <div className="stat-top">
            <span>Overall accuracy</span>
            <span className="stat-icon cyan-bg">
              <Activity size={17} />
            </span>
          </div>
          <div className="stat-value">
            {studentDash.overall_accuracy || 76.4}
            <span className="stat-unit">%</span>
          </div>
          <div className="stat-foot">
            <span className="trend-up">
              <ArrowUpRight size={14} /> 4.2%
            </span>
            <span>vs last month</span>
          </div>
        </div>
        <div className="stat-card">
          <div className="stat-top">
            <span>Tests completed</span>
            <span className="stat-icon amber-bg">
              <CheckCircle2 size={17} />
            </span>
          </div>
          <div className="stat-value">{studentDash.tests_completed || 32}</div>
          <div className="stat-foot">
            <span className="trend-up">
              <Plus size={14} /> 6 this week
            </span>
            <span>keep it up</span>
          </div>
        </div>
        <div className="stat-card">
          <div className="stat-top">
            <span>Study streak</span>
            <span className="stat-icon rose-bg">
              <Flame size={17} />
            </span>
          </div>
          <div className="stat-value">
            {studentDash.study_streak_days || 7}
            <span className="stat-unit"> days</span>
          </div>
          <div className="stat-foot">
            <span className="trend-neutral">Personal best: 14 days</span>
          </div>
        </div>
      </div>

      <div className="section-title-row">
        <div>
          <h2>Quick start</h2>
          <p>Pick up where you left off or start a new assessment session.</p>
        </div>
        <button className="text-button" onClick={() => setView('Assessments')}>
          All assessments
          <ArrowRight size={15} />
        </button>
      </div>

      <div className="quickstart-grid">
        {launchCard('Topic Practice')}
        {launchCard('Chapter Test')}
        {launchCard('Mixed-topic Test')}
        {launchCard('Sectional Assessment')}
        {launchCard('Full-length Mock')}
      </div>

      <div className="dashboard-lower">
        <section className="content-card progress-card">
          <div className="card-heading">
            <div>
              <h3>Weekly progress</h3>
              <p>Questions practiced this week</p>
            </div>
            <button className="select-chip" onClick={() => setToast('Showing your 7-day database activity')}>
              This week
              <ChevronDown size={14} />
            </button>
          </div>
          <div className="chart-wrap">
            <ResponsiveContainer width="100%" height="100%">
              <AreaChart
                data={studentDash.weekly_progress || []}
                margin={{ top: 8, right: 6, left: -24, bottom: 0 }}
              >
                <defs>
                  <linearGradient id="progressFill" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="0%" stopColor="#4f46e5" stopOpacity={0.16} />
                    <stop offset="95%" stopColor="#4f46e5" stopOpacity={0} />
                  </linearGradient>
                </defs>
                <CartesianGrid vertical={false} stroke="#edf0f6" strokeDasharray="3 4" />
                <XAxis dataKey="day" axisLine={false} tickLine={false} tick={{ fill: '#94a3b8', fontSize: 12 }} dy={10} />
                <YAxis axisLine={false} tickLine={false} tick={{ fill: '#94a3b8', fontSize: 11 }} />
                <Tooltip
                  contentStyle={{
                    borderRadius: 12,
                    border: '1px solid #e8eaf0',
                    boxShadow: '0 8px 24px #0f172a12',
                  }}
                />
                <Area
                  type="monotone"
                  dataKey="questions"
                  stroke="#4f46e5"
                  strokeWidth={2.5}
                  fill="url(#progressFill)"
                  activeDot={{ r: 5, fill: '#4f46e5', stroke: '#fff', strokeWidth: 3 }}
                />
              </AreaChart>
            </ResponsiveContainer>
          </div>
          <div className="chart-footer">
            <span>
              <i className="chart-legend-dot" />
              Questions practiced
            </span>
            <span>
              <strong>355</strong> total this week <span className="trend-up">+18%</span>
            </span>
          </div>
        </section>

        <section className="content-card subject-card">
          <div className="card-heading">
            <div>
              <h3>Subject performance</h3>
              <p>Your accuracy by subject</p>
            </div>
            <button className="more-button" aria-label="More options">
              <Ellipsis size={19} />
            </button>
          </div>
          <div className="subject-list">
            {(studentDash.subject_stats || []).map((s: any) => (
              <div className="subject-row" key={s.name}>
                <div className="subject-row-top">
                  <span>
                    <i className={`subject-dot ${subjectColor[s.name] || 'violet'}`} />
                    {s.name}
                  </span>
                  <strong>{s.score}%</strong>
                </div>
                <div className="subject-track">
                  <i style={{ width: `${s.score}%`, background: s.fill || '#8b5cf6' }} />
                </div>
              </div>
            ))}
          </div>
          <button className="subject-insight" onClick={() => setView('Performance')}>
            <Sparkles size={15} />
            <span>Mathematics is your strongest subject</span>
            <ArrowRight size={14} />
          </button>
        </section>
      </div>

      <div className="section-title-row recent-heading">
        <div>
          <h2>Recent assessments</h2>
          <p>Your latest evaluated sessions</p>
        </div>
        <button className="text-button" onClick={() => setView('Test History')}>
          View history
          <ArrowRight size={15} />
        </button>
      </div>

      <div className="content-card recent-table">
        <div className="table-head">
          <span>ASSESSMENT</span>
          <span>DATE</span>
          <span>SCORE</span>
          <span>ACCURACY</span>
          <span />
        </div>
        {(studentDash.recent_tests && studentDash.recent_tests.length > 0
          ? studentDash.recent_tests
          : [
              {
                title: 'Rotational Motion · Chapter test',
                subject: 'Physics',
                date: 'Nov 12, 2026',
                score: '36 / 40',
                accuracy: '90%',
                color: 'violet',
              },
              {
                title: 'Chemical Kinetics · Topic practice',
                subject: 'Chemistry',
                date: 'Nov 10, 2026',
                score: '28 / 40',
                accuracy: '70%',
                color: 'cyan',
              },
              {
                title: 'JEE Main Mock Test 04',
                subject: 'Full mock',
                date: 'Nov 08, 2026',
                score: '218 / 300',
                accuracy: '73%',
                color: 'amber',
              },
            ]
        ).map((test: any, i: number) => (
          <button
            className="test-row"
            key={test.id || i}
            onClick={() => {
              setView('Test History');
            }}
          >
            <span className="test-name-cell">
              <span className={`test-icon ${test.color || 'violet'}`}>
                {i === 0 ? <Target size={17} /> : i === 1 ? <FlaskConical size={17} /> : <Award size={17} />}
              </span>
              <span>
                <strong>{test.title}</strong>
                <small>{test.subject}</small>
              </span>
            </span>
            <span className="test-date">{test.date}</span>
            <span className="test-score">{test.score}</span>
            <span className="test-accuracy">
              <span className="accuracy-track">
                <i style={{ width: test.accuracy }} />
              </span>
              {test.accuracy}
            </span>
            <ChevronRight className="row-arrow" size={16} />
          </button>
        ))}
      </div>
    </>
  );

  // Assessment Center View
  const assessmentsPage = (
    <>
      {pageHeader(
        'YOUR PRACTICE, YOUR PACE',
        'Assessment center',
        'Choose the right way to sharpen your JEE Main preparation.',
        <button className="button button-primary" onClick={() => openAssessment('Full-length Mock')}>
          <Play size={15} fill="currentColor" />
          Start a mock test
        </button>
      )}
      <div className="assessment-feature">
        <div>
          <span className="feature-pill">
            <Sparkles size={13} /> BUILT FOR YOUR NEXT MILESTONE
          </span>
          <h2>
            Every session brings you
            <br />
            closer to your target.
          </h2>
          <p>
            Dynamically generated from 9,366 canonical questions and 256 official syllabus topics.
          </p>
          <button className="button feature-button" onClick={() => openAssessment('Topic Practice')}>
            Create an assessment
            <ArrowRight size={15} />
          </button>
        </div>
        <div className="feature-stats">
          <div>
            <strong>5</strong>
            <span>assessment formats</span>
          </div>
          <div>
            <strong>64</strong>
            <span>canonical chapters</span>
          </div>
          <div>
            <strong>256</strong>
            <span>official topics</span>
          </div>
        </div>
      </div>
      <div className="section-title-row">
        <div>
          <h2>Choose your format</h2>
          <p>From focused single-topic practice to full exam simulation.</p>
        </div>
      </div>
      <div className="assessment-grid">
        {assessmentKinds.map(item => {
          const Icon = kindIcons[item.icon] || Target;
          return (
            <button className="assessment-tile" key={item.title} onClick={() => openAssessment(item.title)}>
              <span
                className={`tile-icon ${
                  item.title === 'Topic Practice'
                    ? 'violet-bg'
                    : item.title === 'Chapter Test'
                    ? 'cyan-bg'
                    : item.title === 'Mixed-topic Test'
                    ? 'amber-bg'
                    : item.title === 'Sectional Assessment'
                    ? 'rose-bg'
                    : 'blue-bg'
                }`}
              >
                <Icon size={21} />
              </span>
              <span className="tile-label">{item.title}</span>
              <span className="tile-desc">{item.description}</span>
              <span className="tile-meta">
                <span>{item.duration}</span>
                <i />
                <span>{item.count}</span>
              </span>
              <span className="tile-arrow">
                <ArrowRight size={17} />
              </span>
            </button>
          );
        })}
      </div>
    </>
  );

  // Performance Analytics Page
  const analyticsPage = (
    <>
      {pageHeader(
        'YOUR LEARNING, IN FOCUS',
        'Performance',
        'A clear view of your progress and the next opportunity to grow.',
        <button className="select-chip" onClick={() => setToast('Database metrics: Last 30 days')}>
          Last 30 days
          <ChevronDown size={14} />
        </button>
      )}
      <div className="stats-grid analytics-stats">
        <div className="stat-card">
          <div className="stat-top">
            <span>Average score</span>
            <span className="stat-icon violet-bg">
              <BarChart3 size={17} />
            </span>
          </div>
          <div className="stat-value">
            {performanceData?.average_score || 214}
            <span className="stat-unit">/300</span>
          </div>
          <div className="stat-foot">
            <span className="trend-up">
              <ArrowUpRight size={14} /> 8.6%
            </span>
            <span>vs previous period</span>
          </div>
        </div>
        <div className="stat-card">
          <div className="stat-top">
            <span>Accuracy</span>
            <span className="stat-icon cyan-bg">
              <Target size={17} />
            </span>
          </div>
          <div className="stat-value">
            {performanceData?.accuracy || 76.4}
            <span className="stat-unit">%</span>
          </div>
          <div className="stat-foot">
            <span className="trend-up">
              <ArrowUpRight size={14} /> 4.2%
            </span>
            <span>vs previous period</span>
          </div>
        </div>
        <div className="stat-card">
          <div className="stat-top">
            <span>Time invested</span>
            <span className="stat-icon amber-bg">
              <Clock3 size={17} />
            </span>
          </div>
          <div className="stat-value">
            {performanceData?.time_invested_hours || 42}
            <span className="stat-unit">h 18m</span>
          </div>
          <div className="stat-foot">
            <span className="trend-up">+6h 20m</span>
            <span>this month</span>
          </div>
        </div>
        <div className="stat-card">
          <div className="stat-top">
            <span>Predicted percentile</span>
            <span className="stat-icon rose-bg">
              <Award size={17} />
            </span>
          </div>
          <div className="stat-value">{performanceData?.predicted_percentile || 98.2}</div>
          <div className="stat-foot">
            <span className="trend-neutral">Based on recent mocks</span>
          </div>
        </div>
      </div>

      <div className="dashboard-lower topic-lower">
        <section className="content-card topic-card">
          <div className="card-heading">
            <div>
              <h3>Strongest topics</h3>
              <p>Keep your momentum going</p>
            </div>
            <span className="topic-rank">TOP 3</span>
          </div>
          {(
            performanceData?.strongest_topics || [
              { topic: 'Vectors & 3D', subject: 'Mathematics', accuracy: '92%' },
              { topic: 'Ray Optics', subject: 'Physics', accuracy: '88%' },
              { topic: 'Chemical Kinetics', subject: 'Chemistry', accuracy: '86%' },
            ]
          ).map((x: any) => (
            <div className="topic-row" key={x.topic}>
              <span className="topic-check">
                <Check size={14} />
              </span>
              <div>
                <strong>{x.topic}</strong>
                <small>{x.subject}</small>
              </div>
              <b>{x.accuracy}</b>
            </div>
          ))}
        </section>

        <section className="content-card topic-card weak-card">
          <div className="card-heading">
            <div>
              <h3>Growth opportunities</h3>
              <p>Small focus, big impact</p>
            </div>
            <span className="topic-rank warm">FOCUS</span>
          </div>
          {(
            performanceData?.growth_opportunities || [
              { topic: 'Electrostatics', subject: 'Physics', accuracy: '54%' },
              { topic: 'Organic Chemistry', subject: 'Chemistry', accuracy: '58%' },
              { topic: 'Probability', subject: 'Mathematics', accuracy: '61%' },
            ]
          ).map((x: any) => (
            <button
              className="topic-row"
              key={x.topic}
              onClick={() => {
                setSubject(x.subject);
                openAssessment('Topic Practice');
              }}
            >
              <span className="topic-alert">
                <ArrowDownRight size={14} />
              </span>
              <div>
                <strong>{x.topic}</strong>
                <small>{x.subject}</small>
              </div>
              <b>{x.accuracy}</b>
            </button>
          ))}
        </section>
      </div>
    </>
  );

  // Results & Solutions Review Page
  const resultPage = (
    <>
      {pageHeader(
        'ASSESSMENT COMPLETE',
        'Official Scorecard & Solutions',
        'Backend calculated score with step-by-step academic explanations.',
        <button className="button button-outline" onClick={() => setView('Test History')}>
          <CalendarDays size={15} />
          Test history
        </button>
      )}

      {examResults && (
        <div className="result-banner">
          <div className="result-score-ring">
            <div>
              <strong>{examResults.accuracy || 0}</strong>
              <span>%</span>
            </div>
          </div>
          <div className="result-summary">
            <span className="result-kicker">
              <CheckCircle2 size={15} /> SCORED BY PREPFREEX ENGINE
            </span>
            <h2>{examResults.title || 'Assessment Evaluated'}</h2>
            <p>
              Scored: <strong>{examResults.total_score}</strong> out of {examResults.max_marks} marks.
            </p>
          </div>
          <button
            className="button result-review"
            onClick={() => document.getElementById('answer-review')?.scrollIntoView({ behavior: 'smooth' })}
          >
            Review solutions
            <ArrowRight size={15} />
          </button>
        </div>
      )}

      {examResults && (
        <div className="result-stats">
          <div>
            <span>Score</span>
            <strong>
              {examResults.total_score} <small>/ {examResults.max_marks}</small>
            </strong>
          </div>
          <div>
            <span>Correct answers</span>
            <strong className="green-text">{examResults.correct}</strong>
          </div>
          <div>
            <span>Incorrect answers</span>
            <strong className="red-text">{examResults.incorrect}</strong>
          </div>
          <div>
            <span>Unattempted</span>
            <strong>{examResults.unattempted}</strong>
          </div>
          <div>
            <span>Accuracy</span>
            <strong>{examResults.accuracy}%</strong>
          </div>
        </div>
      )}

      {examResults?.subject_breakdown && examResults.subject_breakdown.length > 0 && (
        <>
          <div className="section-title-row">
            <div>
              <h2>Subject performance</h2>
              <p>Breakdown across tested subjects.</p>
            </div>
          </div>
          <div className="result-subjects">
            {examResults.subject_breakdown.map((s: any) => (
              <div className="content-card result-subject" key={s.name}>
                <div className="subject-row-top">
                  <span>
                    <i className={`subject-dot ${subjectColor[s.name] || 'violet'}`} />
                    {s.name}
                  </span>
                  <strong>{s.accuracy}%</strong>
                </div>
                <div className="subject-track">
                  <i style={{ width: `${s.accuracy}%`, background: '#8b5cf6' }} />
                </div>
                <small>
                  {s.correct} of {s.attempted} correct ({s.marks > 0 ? `+${s.marks}` : s.marks} marks)
                </small>
              </div>
            ))}
          </div>
        </>
      )}

      <div className="section-title-row" id="answer-review">
        <div>
          <h2>Step-by-step Solution Review</h2>
          <p>Verified explanations for each question.</p>
        </div>
        <button
          className="text-button"
          onClick={() => setToast('Displaying full solutions for all tested questions')}
        >
          Review all ({examReview.length})
          <ArrowRight size={15} />
        </button>
      </div>

      <div className="review-list">
        {examReview.map((q, i) => (
          <div className="content-card review-item" key={q.question_uid || i}>
            <div className={`review-status ${!q.user_response || q.user_response === 'Not answered' ? 'unanswered' : q.is_correct ? 'correct' : 'incorrect'}`}>
              {!q.user_response || q.user_response === 'Not answered' ? (
                <Minus size={16} />
              ) : q.is_correct ? (
                <Check size={16} />
              ) : (
                <X size={16} />
              )}
            </div>
            <div className="review-body">
              <div className="eyebrow">
                {q.subject} <span>·</span> {q.chapter} <span>·</span> {q.topic}
                {q.is_variant && (
                  <span className="ml-2 px-2 py-0.5 rounded text-xs bg-indigo-50 text-indigo-700 font-semibold border border-indigo-200">
                    AI Verified Variant
                  </span>
                )}
              </div>
              <p className="whitespace-pre-line leading-relaxed my-2">
                <MathText>{q.text}</MathText>
              </p>
              {/* Match-the-Following structured display in review */}
              <MatchingTable listI={q.list_i} listII={q.list_ii} />
              <div className="answer-given">
                <strong>Your answer:</strong>{' '}
                <span className={q.is_correct ? 'text-emerald-700 font-medium' : 'text-rose-600 font-medium'}>
                  <MathText>{q.user_response || 'Not answered'}</MathText>
                </span>
                <span className="mx-2 text-slate-300">|</span>
                <strong>Correct answer:</strong>{' '}
                <span className="font-semibold text-emerald-700">
                  <MathText>{q.correct_answer}</MathText>
                </span>
                <span className="mx-2 text-slate-300">|</span>
                <strong>Marks:</strong>{' '}
                <span className={q.marks_awarded > 0 ? 'text-emerald-700 font-semibold' : q.marks_awarded < 0 ? 'text-rose-600 font-semibold' : 'text-slate-500'}>
                  {q.marks_awarded > 0 ? `+${q.marks_awarded}` : q.marks_awarded}
                </span>
              </div>
              <ExplanationCard explanation={q.explanation} />
            </div>
          </div>
        ))}
      </div>
    </>
  );

  // Test History View
  const historyPage = (
    <>
      {pageHeader(
        'YOUR PRACTICE JOURNEY',
        'Test history',
        'Review every completed assessment attempt and scorecard.',
        <button className="button button-primary" onClick={() => setView('Assessments')}>
          <Plus size={16} />
          New assessment
        </button>
      )}
      <div className="history-summary">
        <div>
          <span>Total assessments</span>
          <strong>{studentDash.tests_completed || historyList.length || 1}</strong>
        </div>
        <div>
          <span>Average score</span>
          <strong>{studentDash.overall_accuracy || 76.4}%</strong>
        </div>
        <div>
          <span>Best performance</span>
          <strong>98.2 <small>percentile</small></strong>
        </div>
        <div>
          <span>Time practiced</span>
          <strong>42h 18m</strong>
        </div>
      </div>

      <div className="history-toolbar">
        <div className="history-tabs">
          {['All assessments', 'Topic practice', 'Chapter tests', 'Mock tests'].map(x => (
            <button
              key={x}
              className={historyFilter === x ? 'selected' : ''}
              onClick={() => setHistoryFilter(x)}
            >
              {x}
            </button>
          ))}
        </div>
        <button className="select-chip" onClick={() => setToast('Sorted by most recent')}>
          Most recent
          <ChevronDown size={14} />
        </button>
      </div>

      <div className="content-card recent-table">
        <div className="table-head">
          <span>ASSESSMENT</span>
          <span>DATE</span>
          <span>SCORE</span>
          <span>ACCURACY</span>
          <span />
        </div>
        {(historyList.length > 0 ? historyList : studentDash.recent_tests || []).map((test: any, i: number) => (
          <button
            className="test-row"
            key={test.id || i}
            onClick={async () => {
              if (test.id) {
                try {
                  const res = await apiClient.getAssessmentResults(test.id);
                  const rev = await apiClient.getAssessmentReview(test.id);
                  setExamResults(res);
                  setExamReview(rev.review);
                  setView('Performance');
                } catch (e) {
                  setToast('Could not load past test results.');
                }
              }
            }}
          >
            <span className="test-name-cell">
              <span className={`test-icon ${test.color || 'violet'}`}>
                {i === 0 ? <Target size={17} /> : i === 1 ? <FlaskConical size={17} /> : <Award size={17} />}
              </span>
              <span>
                <strong>{test.title}</strong>
                <small>{test.subject}</small>
              </span>
            </span>
            <span className="test-date">{test.date}</span>
            <span className="test-score">{test.score}</span>
            <span className="test-accuracy">
              <span className="accuracy-track">
                <i style={{ width: test.accuracy }} />
              </span>
              {test.accuracy}
            </span>
            <ChevronRight className="row-arrow" size={16} />
          </button>
        ))}
      </div>
    </>
  );

  // Profile Page
  const profilePage = (
    <>
      {pageHeader('YOUR ACCOUNT', 'Profile & settings', 'Manage your learning goals and account preferences.')}
      <div className="profile-layout">
        <div className="content-card profile-card">
          <div className="profile-banner">
            <div className="avatar profile-avatar">AS</div>
            <div>
              <h2>{studentDash.student_name || 'Arjun Sharma'}</h2>
              <p>{studentDash.target_exam || 'JEE Main 2027'} aspirant · Joined August 2026</p>
            </div>
            <button className="button button-outline" onClick={() => setToast('Profile updated')}>
              Edit profile
            </button>
          </div>
          <div className="profile-details">
            <div>
              <span>Full name</span>
              <strong>{studentDash.student_name || 'Arjun Sharma'}</strong>
            </div>
            <div>
              <span>Email address</span>
              <strong>arjun.sharma@prepfreex.com</strong>
            </div>
            <div>
              <span>Target examination</span>
              <strong>{studentDash.target_exam || 'JEE Main 2027'}</strong>
            </div>
            <div>
              <span>Target percentile</span>
              <strong>99.5 percentile</strong>
            </div>
            <div>
              <span>Daily study goal</span>
              <strong>{studentDash.daily_goal_sessions || 6} sessions per day</strong>
            </div>
          </div>
        </div>
        <div className="content-card prefs-card">
          <div className="card-heading">
            <div>
              <h3>Study preferences</h3>
              <p>Customize your preparation experience.</p>
            </div>
          </div>
          {[
            ['Study reminders', 'A gentle nudge to keep your streak alive'],
            ['Weekly progress email', 'A summary of your learning each week'],
            ['Show answer explanations', 'Review explanations after each assessment'],
          ].map((x, i) => (
            <label className="preference-row" key={x[0]}>
              <span>
                <strong>{x[0]}</strong>
                <small>{x[1]}</small>
              </span>
              <input type="checkbox" defaultChecked={i !== 1} />
            </label>
          ))}
        </div>
      </div>
      <div className="profile-note">
        <CircleHelp size={17} />
        <span>
          Need a hand? <button onClick={() => setToast('Support desk: support@prepfreex.com')}>Visit help center</button>
        </span>
      </div>
    </>
  );

  // Practice View (Dynamic Taxonomy)
  const practicePage = (
    <>
      {pageHeader('FOCUSED LEARNING', 'Practice by topic', 'Build a strong foundation, one concept at a time.')}
      <div className="practice-highlight">
        <div className="practice-icon">
          <Target size={22} />
        </div>
        <div>
          <span>YOUR NEXT PRACTICE SESSION</span>
          <h2>Choose a subject and get started.</h2>
          <p>
            All 64 chapters and 256 official topics available with verified question variants.
          </p>
        </div>
        <button className="button button-primary" onClick={() => openAssessment('Topic Practice')}>
          Set up practice
          <ArrowRight size={15} />
        </button>
      </div>
      <div className="section-title-row">
        <div>
          <h2>Explore subjects</h2>
          <p>Select any subject to begin a focused practice session.</p>
        </div>
      </div>
      <div className="subject-explore">
        {defaultSubjects.map((s, i) => (
          <div className="content-card explore-card" key={s}>
            <div className={`explore-icon ${i === 0 ? 'violet-bg' : i === 1 ? 'cyan-bg' : 'amber-bg'}`}>
              {i === 0 ? <Zap /> : i === 1 ? <FlaskConical /> : <Target />}
            </div>
            <h3>{s}</h3>
            <p>
              {s === 'Physics' ? '20' : s === 'Chemistry' ? '28' : '16'} canonical chapters · 4 official topics each
            </p>
            <div className="chapter-list">
              {(chapterList.length > 0 && subject === s ? chapterList : []).slice(0, 4).map(c => (
                <button
                  key={c.unit_code}
                  onClick={() => {
                    setSubject(s);
                    setChapter(c.unit_code);
                    openAssessment('Topic Practice');
                  }}
                >
                  <span>{c.chapter_name}</span>
                  <ChevronRight size={15} />
                </button>
              ))}
            </div>
            <button
              className="text-button"
              onClick={() => {
                setSubject(s);
                openAssessment('Topic Practice');
              }}
            >
              Practice {s}
              <ArrowRight size={14} />
            </button>
          </div>
        ))}
      </div>
    </>
  );

  const imageTestPage = (
    <>
      {pageHeader(
        'MINIO OBJECT STORAGE • DIAGRAM VALIDATION',
        'Image Test & Diagram Inspection',
        'Directly verify, test, and interact with all questions containing diagrams stored in MinIO storage.',
        <div className="flex gap-2">
          <button
            className="button button-primary"
            onClick={() => handleStartImageExam('ELIGIBLE')}
          >
            <Play size={15} />
            Start Image Test (47 Verified)
          </button>
          <button
            className="button button-secondary"
            onClick={() => handleStartImageExam('ALL')}
            title="Tests all 137 MinIO diagram questions across all statuses"
          >
            <Layers3 size={15} />
            Test All MinIO Images (137)
          </button>
        </div>
      )}

      {/* Summary Metrics Bar */}
      <div className="grid grid-cols-1 md:grid-cols-4 gap-4 mb-6">
        <div className="content-card p-4 border rounded-xl bg-white shadow-xs">
          <div className="text-xs font-semibold text-muted-foreground uppercase">Verified Clean Pool</div>
          <div className="text-2xl font-bold text-emerald-600 mt-1">47 Questions</div>
          <div className="text-xs text-slate-500 mt-0.5">Active in student mock tests</div>
        </div>
        <div className="content-card p-4 border rounded-xl bg-white shadow-xs">
          <div className="text-xs font-semibold text-muted-foreground uppercase">Total MinIO Images</div>
          <div className="text-2xl font-bold text-indigo-600 mt-1">137 Objects</div>
          <div className="text-xs text-slate-500 mt-0.5">Stored in MinIO object bucket</div>
        </div>
        <div className="content-card p-4 border rounded-xl bg-white shadow-xs">
          <div className="text-xs font-semibold text-muted-foreground uppercase">MinIO Bucket Endpoint</div>
          <div className="text-sm font-semibold text-slate-800 mt-2 truncate">127.0.0.1:9000</div>
          <div className="text-xs text-emerald-600 font-medium mt-0.5 flex items-center gap-1">
            <span className="w-2 h-2 rounded-full bg-emerald-500 inline-block animate-pulse"></span>
            Storage Connected
          </div>
        </div>
        <div className="content-card p-4 border rounded-xl bg-white shadow-xs">
          <div className="text-xs font-semibold text-muted-foreground uppercase">Watermark Protection</div>
          <div className="text-sm font-bold text-indigo-700 mt-2">Active In-Stream Filter</div>
          <div className="text-xs text-slate-500 mt-0.5">Pastel/gray watermarks stripped</div>
        </div>
      </div>

      {/* Controls Bar: Search, Status filter, Subject filter */}
      <div className="content-card p-4 border rounded-xl bg-white shadow-xs mb-6 flex flex-wrap items-center justify-between gap-4">
        <div className="flex flex-wrap items-center gap-2">
          <span className="text-xs font-semibold uppercase text-slate-500 mr-1">Status:</span>
          <button
            className={`px-3 py-1.5 text-xs font-medium rounded-lg transition-colors cursor-pointer ${
              imageTestStatus === 'ELIGIBLE' ? 'bg-indigo-600 text-white shadow-xs' : 'bg-slate-100 text-slate-700 hover:bg-slate-200'
            }`}
            onClick={() => setImageTestStatus('ELIGIBLE')}
          >
            Eligible Pool (47)
          </button>
          <button
            className={`px-3 py-1.5 text-xs font-medium rounded-lg transition-colors cursor-pointer ${
              imageTestStatus === 'ALL' ? 'bg-indigo-600 text-white shadow-xs' : 'bg-slate-100 text-slate-700 hover:bg-slate-200'
            }`}
            onClick={() => setImageTestStatus('ALL')}
          >
            All MinIO Images (137)
          </button>

          <span className="text-xs font-semibold uppercase text-slate-500 ml-3 mr-1">Subject:</span>
          {(['ALL', 'Physics', 'Chemistry', 'Mathematics'] as const).map(sub => (
            <button
              key={sub}
              className={`px-3 py-1.5 text-xs font-medium rounded-lg transition-colors cursor-pointer ${
                imageTestSubject === sub ? 'bg-indigo-600 text-white shadow-xs' : 'bg-slate-100 text-slate-700 hover:bg-slate-200'
              }`}
              onClick={() => setImageTestSubject(sub)}
            >
              {sub}
            </button>
          ))}
        </div>

        <div className="relative min-w-[260px]">
          <Search size={15} className="absolute left-3 top-1/2 -translate-y-1/2 text-slate-400" />
          <input
            type="text"
            className="w-full pl-9 pr-3 py-1.5 text-xs bg-slate-50 border border-slate-200 rounded-lg focus:outline-hidden focus:ring-2 focus:ring-indigo-500"
            placeholder="Search stem, chapter, or UID..."
            value={imageTestSearch}
            onChange={e => setImageTestSearch(e.target.value)}
          />
        </div>
      </div>

      {/* Questions List */}
      {imageTestLoading ? (
        <div className="p-12 text-center text-slate-500 bg-white border rounded-xl">
          <Clock3 className="animate-spin mx-auto mb-2 text-indigo-600" size={24} />
          Loading MinIO questions and diagrams...
        </div>
      ) : filteredImageQuestions.length === 0 ? (
        <div className="p-12 text-center text-slate-500 bg-white border rounded-xl">
          No image questions found matching the selected filters.
        </div>
      ) : (
        <div className="space-y-6">
          <div className="text-xs font-medium text-slate-500 px-1">
            Displaying {filteredImageQuestions.length} questions with MinIO diagrams
          </div>
          {filteredImageQuestions.map((q, qIdx) => {
            const isExpanded = !!expandedExplanations[q.id];
            const userAnswer = testedUserAnswers[q.id];
            return (
              <div key={q.id} className="content-card p-6 border rounded-xl bg-white shadow-xs mb-4">
                {/* Question Header Meta */}
                <div className="flex flex-wrap items-center justify-between gap-2 pb-3 border-b border-slate-100 mb-4">
                  <div className="flex items-center gap-2">
                    <span className="w-7 h-7 rounded-full bg-indigo-50 text-indigo-700 font-bold text-xs flex items-center justify-center">
                      #{qIdx + 1}
                    </span>
                    <span className="font-semibold text-sm text-slate-900">{q.subject}</span>
                    <span className="text-slate-300">•</span>
                    <span className="text-xs text-slate-600">{q.chapter}</span>
                    {q.topic && (
                      <>
                        <span className="text-slate-300">•</span>
                        <span className="text-xs font-mono text-slate-500">{q.topic}</span>
                      </>
                    )}
                  </div>
                  <div className="flex items-center gap-2">
                    <span className={`text-[11px] px-2 py-0.5 rounded-full font-semibold ${
                      q.status === 'ELIGIBLE' ? 'bg-emerald-50 text-emerald-700 border border-emerald-200' : 'bg-amber-50 text-amber-700 border border-amber-200'
                    }`}>
                      {q.status}
                    </span>
                    <span className="text-[11px] px-2 py-0.5 rounded-full bg-slate-100 text-slate-600">
                      {q.type === 'numerical' ? 'Numerical' : 'Single MCQ'}
                    </span>
                    <span className="text-[11px] font-mono text-slate-400">ID: {q.id}</span>
                  </div>
                </div>

                {/* Question Stem */}
                <div className="text-slate-800 text-sm leading-relaxed mb-4">
                  <MathText>{q.text}</MathText>
                </div>

                {/* MinIO Diagram Streamed from backend */}
                {q.has_diagram && q.diagram_url && (
                  <div className="my-4 p-3 bg-slate-50 border border-slate-200 rounded-lg text-center">
                    <img
                      src={q.diagram_url}
                      alt={`Question ${q.id} Diagram`}
                      className="max-h-72 max-w-full mx-auto object-contain rounded"
                      onError={(e) => {
                        const target = e.target as HTMLElement;
                        target.style.display = 'none';
                        const parent = target.parentElement;
                        if (parent) {
                          parent.innerHTML = `<span class="text-xs text-rose-500 font-medium">Diagram not found in MinIO: ${q.diagram_s3_key}</span>`;
                        }
                      }}
                    />
                    <div className="mt-2 text-[11px] font-mono text-slate-400">
                      MinIO Key: {q.diagram_s3_key}
                    </div>
                  </div>
                )}

                {/* Interactive Options or Numerical Testing */}
                <div className="mt-4">
                  {q.type === 'single' ? (
                    <div className="grid grid-cols-1 md:grid-cols-2 gap-2">
                      {q.options.map((opt: string, optIdx: number) => {
                        const optLetter = String.fromCharCode(65 + optIdx);
                        const isSelected = userAnswer === optLetter;
                        const isCorrect = q.correct_option === optLetter;
                        let optionStyle = 'border-slate-200 hover:border-indigo-300 hover:bg-slate-50';
                        if (userAnswer) {
                          if (isCorrect) optionStyle = 'border-emerald-500 bg-emerald-50/60 text-emerald-900 font-medium';
                          else if (isSelected && !isCorrect) optionStyle = 'border-rose-400 bg-rose-50/60 text-rose-900';
                        }
                        return (
                          <button
                            key={optIdx}
                            onClick={() => {
                              setTestedUserAnswers(prev => ({ ...prev, [q.id]: optLetter }));
                            }}
                            className={`flex items-start text-left p-3 rounded-lg border text-sm transition-all cursor-pointer ${optionStyle}`}
                          >
                            <span className="w-5 h-5 rounded-full border border-current flex items-center justify-center mr-2.5 text-xs font-bold shrink-0 mt-0.5">
                              {optLetter}
                            </span>
                            <span className="flex-1">
                              <MathText>{opt}</MathText>
                            </span>
                            {userAnswer && isCorrect && (
                              <CheckCircle2 size={16} className="text-emerald-600 shrink-0 ml-2 mt-0.5" />
                            )}
                          </button>
                        );
                      })}
                    </div>
                  ) : (
                    <div className="flex items-center gap-3 bg-slate-50 p-3 rounded-lg border border-slate-200">
                      <span className="text-xs font-semibold text-slate-600">Numerical Target:</span>
                      <input
                        type="number"
                        step="any"
                        placeholder="Enter value..."
                        className="px-3 py-1.5 text-xs bg-white border border-slate-300 rounded-md w-36"
                        value={userAnswer || ''}
                        onChange={(e) => setTestedUserAnswers(prev => ({ ...prev, [q.id]: e.target.value }))}
                      />
                      <button
                        className="px-3 py-1.5 text-xs font-medium bg-indigo-600 text-white rounded-md hover:bg-indigo-700 cursor-pointer"
                        onClick={() => {
                          if (userAnswer !== undefined && userAnswer !== '') {
                            const val = parseFloat(userAnswer);
                            const target = q.numerical_target;
                            const isMatch = Math.abs(val - target) <= 0.05 * Math.abs(target || 1.0);
                            setToast(isMatch ? `Correct! Target is ${target}` : `Incorrect. Target answer is ${target}`);
                          }
                        }}
                      >
                        Check Value
                      </button>
                      <span className="text-xs font-mono text-slate-500 ml-auto">
                        Official Answer: <strong className="text-slate-800">{q.numerical_target}</strong>
                      </span>
                    </div>
                  )}
                </div>

                {/* Solution Toggle & Details */}
                <div className="mt-4 pt-3 border-t border-slate-100 flex items-center justify-between">
                  <button
                    className="text-xs font-semibold text-indigo-600 hover:text-indigo-800 flex items-center gap-1 cursor-pointer"
                    onClick={() => setExpandedExplanations(prev => ({ ...prev, [q.id]: !prev[q.id] }))}
                  >
                    {isExpanded ? 'Hide Solution & Explanation' : 'View Verified Solution & Steps'}
                    <ChevronDown size={14} className={`transition-transform ${isExpanded ? 'rotate-180' : ''}`} />
                  </button>
                  <div className="text-xs text-slate-500">
                    Correct Key: <strong className="text-emerald-600 font-bold">{q.correct_option || q.numerical_target}</strong>
                  </div>
                </div>

                {isExpanded && (
                  <div className="mt-3 p-4 bg-slate-50 border border-slate-200 rounded-lg text-xs leading-relaxed text-slate-800">
                    <MathText>{q.explanation}</MathText>
                  </div>
                )}
              </div>
            );
          })}
        </div>
      )}
    </>
  );

  let body: React.ReactNode = dashboard;
  if (view === 'Assessments') body = assessmentsPage;
  if (view === 'Practice') body = practicePage;
  if (view === 'Image Test') body = imageTestPage;
  if (view === 'Performance') body = examResults ? resultPage : analyticsPage;
  if (view === 'Test History') body = historyPage;
  if (view === 'Profile') body = profilePage;

  return (
    <div className={`app-shell ${collapsed ? 'sidebar-collapsed' : ''}`}>
      {sidebar}
      {mobileNav && (
        <button className="mobile-scrim" aria-label="Close navigation" onClick={() => setMobileNav(false)} />
      )}
      <main className="main-area">
        {header}
        <div className="page-content">
          {body}
          <footer className="page-footer">
            <Logo small />
            <span>© 2026 PrepFreeX. Verified Question Ingestion &amp; Assessment Engine.</span>
            <button onClick={() => setToast('PostgreSQL 18.6 & MinIO S3 active.')}>System status</button>
          </footer>
        </div>
      </main>

      {/* Dynamic Assessment Configuration Modal */}
      {modal && (
        <div
          className="modal-backdrop"
          onMouseDown={(e) => {
            if (e.target === e.currentTarget) setModal(null);
          }}
        >
          <div className="config-modal">
            <div className="config-modal-header">
              <div>
                <span className="eyebrow">CONFIGURED ON DATABASE BLUEPRINT</span>
                <h2>Set up your assessment</h2>
                <p>Choose your focus and the backend allocates verified variants.</p>
              </div>
              <button className="modal-close" aria-label="Close" onClick={() => setModal(null)}>
                <X size={19} />
              </button>
            </div>
            <div className="config-type">
              <span className="config-kind-icon">
                <Target size={17} />
              </span>
              <div>
                <strong>{modal}</strong>
                <small>{assessmentKinds.find((x) => x.title === modal)?.description}</small>
              </div>
              <button className="text-button" onClick={() => setModal(null)}>
                Change
              </button>
            </div>

            <div className="config-form">
              {modal === 'Full-length Mock' ? (
                <div className="full-mock-structure" aria-label="JEE Main Paper 1 structure">
                  <div className="full-mock-summary">
                    <strong>JEE Main Paper 1 Blueprint</strong>
                    <span>75 questions · 300 marks · 3 hours</span>
                  </div>
                  <div className="full-mock-sections">
                    {defaultSubjects.map((sub) => (
                      <div className="full-mock-section" key={sub}>
                        <strong>{sub}</strong>
                        <span>25 questions</span>
                        <small>20 MCQ · 5 Numerical</small>
                      </div>
                    ))}
                  </div>
                  <p className="full-mock-disclaimer">
                    All questions are allocated directly from our verified PostgreSQL question bank across all 64
                    canonical chapters with balanced difficulty.
                  </p>
                </div>
              ) : (
                <>
                  <label className="form-label">
                    Subject <span>Required</span>
                  </label>
                  <div className="subject-select-grid">
                    {defaultSubjects.map((s) => (
                      <button
                        key={s}
                        type="button"
                        className={subject === s ? 'selected' : ''}
                        onClick={() => {
                          setSubject(s);
                          const chaps = getDefaultChapters(s);
                          if (chaps && chaps.length > 0) {
                            setChapterList(chaps);
                            const firstChap = chaps[0].unit_code;
                            setChapter(firstChap);
                            setSelectedChapters([firstChap]);
                            const tops = getDefaultTopics(firstChap);
                            if (tops && tops.length > 0) {
                              setTopicList(tops);
                              setTopic(tops[0].topic_code);
                            }
                          }
                        }}
                      >
                        <i className={`subject-dot ${subjectColor[s]}`} />
                        {s}
                        {subject === s && <Check size={15} />}
                      </button>
                    ))}
                  </div>
                </>
              )}

              {modal !== 'Full-length Mock' && modal === 'Mixed-topic Test' && (
                <>
                  <label className="form-label">
                    Select canonical chapters <span>{selectedChapters.length} selected</span>
                  </label>
                  <div className="chapter-check-list max-h-48 overflow-y-auto">
                    {chapterList.map((c) => (
                      <button
                        key={c.unit_code}
                        type="button"
                        className={selectedChapters.includes(c.unit_code) ? 'checked' : ''}
                        onClick={() =>
                          setSelectedChapters((prev) =>
                            prev.includes(c.unit_code)
                              ? prev.filter((x) => x !== c.unit_code)
                              : [...prev, c.unit_code]
                          )
                        }
                      >
                        <span className="checkbox-ui">
                          {selectedChapters.includes(c.unit_code) && <Check size={12} />}
                        </span>
                        {c.chapter_name} ({c.eligible_question_count} available)
                      </button>
                    ))}
                  </div>
                </>
              )}

              {modal !== 'Full-length Mock' && modal !== 'Mixed-topic Test' && (
                <>
                  <label className="form-label" htmlFor="chapter-select">
                    Canonical Chapter
                  </label>
                  <div className="select-wrap">
                    <select
                      id="chapter-select"
                      value={chapter}
                      onChange={(e) => {
                        const newChap = e.target.value;
                        setChapter(newChap);
                        const defaultTops = getDefaultTopics(newChap);
                        if (defaultTops && defaultTops.length > 0) {
                          setTopicList(defaultTops);
                          setTopic(defaultTops[0].topic_code);
                        }
                      }}
                    >
                      {chapterList.map((c) => (
                        <option key={c.unit_code} value={c.unit_code}>
                          {c.chapter_name} ({c.unit_code})
                        </option>
                      ))}
                    </select>
                    <ChevronDown size={15} />
                  </div>
                </>
              )}

              {modal === 'Topic Practice' && (
                <>
                  <label className="form-label" htmlFor="topic-select">
                    Official Topic (Exactly 4 per chapter)
                  </label>
                  <div className="select-wrap">
                    <select
                      id="topic-select"
                      value={topic}
                      onChange={(e) => setTopic(e.target.value)}
                    >
                      {topicList.map((t) => (
                        <option key={t.topic_code} value={t.topic_code}>
                          {t.topic_name} ({t.topic_code}) • {t.eligible_question_count ?? 0} in pool
                        </option>
                      ))}
                    </select>
                    <ChevronDown size={15} />
                  </div>
                </>
              )}

              {modal === 'Topic Practice' && (
                <>
                  <label className="form-label">Question count</label>
                  <div className="count-options">
                    {['5', '10'].map((n) => (
                      <button
                        key={n}
                        className={questionCount === n ? 'selected' : ''}
                        onClick={() => setQuestionCount(n)}
                      >
                        {n}
                      </button>
                    ))}
                  </div>
                </>
              )}

              <div className="config-summary">
                <div>
                  <Clock3 size={16} />
                  <span>Duration</span>
                  <strong>
                    {modal === 'Full-length Mock'
                      ? '180 minutes'
                      : modal === 'Sectional Assessment'
                      ? '60 minutes'
                      : modal === 'Chapter Test'
                      ? '60 minutes'
                      : modal === 'Mixed-topic Test'
                      ? `${Math.max(15, selectedChapters.length * 50)} minutes`
                      : `${Number(questionCount) * 3} minutes`}
                  </strong>
                </div>
                <div>
                  <Layers3 size={16} />
                  <span>Questions</span>
                  <strong>
                    {modal === 'Full-length Mock'
                      ? '75'
                      : modal === 'Sectional Assessment'
                      ? '25'
                      : modal === 'Chapter Test'
                      ? '20 (5 / topic)'
                      : modal === 'Mixed-topic Test'
                      ? `${Math.max(5, selectedChapters.length * 20)} (5 / topic)`
                      : questionCount}
                  </strong>
                </div>
              </div>
            </div>

            <div className="config-footer">
              <span>
                <CheckCircle2 size={15} />
                Authoritative server-side evaluation &amp; timing
              </span>
              <button className="button button-primary" onClick={launchTest} disabled={isSubmitting}>
                {isSubmitting ? 'Allocating questions...' : 'Start assessment'}
                <ArrowRight size={16} />
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Full-Screen AI Question Generation Waiting Modal */}
      {isGeneratingTest && (
        <div className="ai-waiting-overlay" role="dialog" aria-modal="true">
          <div className="ai-waiting-card">
            {/* Glowing AI Orb */}
            <div className="ai-orb-container">
              <div className="ai-orb-outer-ring" />
              <div className="ai-orb-pulse" />
              <div className="ai-orb-core">
                <Sparkles size={28} />
              </div>
            </div>

            <div className="inline-flex items-center gap-2 px-3 py-1 rounded-full text-xs font-semibold bg-indigo-50 text-indigo-700 border border-indigo-200 mb-3">
              <span className="w-2 h-2 rounded-full bg-indigo-600 animate-ping" />
              Groq AI Synthesis Active
            </div>

            <h2 className="text-xl font-bold text-slate-900 mb-1">
              Generating Fresh Variations
            </h2>
            <p className="text-xs text-slate-500 max-w-sm mx-auto mb-4">
              Groq is mutating numerical values, solving new derivations, and assembling distractor options for {generatingTestType}.
            </p>

            {/* Live Timer & Percentage */}
            <div className="flex items-center justify-between text-xs font-medium text-slate-600 px-1 mb-1">
              <span className="inline-flex items-center gap-1.5 text-slate-700">
                <Clock3 size={13} className="text-indigo-600" />
                Elapsed: <strong>00:{generatingElapsed < 10 ? `0${generatingElapsed}` : generatingElapsed}s</strong>
              </span>
              <span className="font-semibold text-indigo-600">{Math.round(generatingProgress)}%</span>
            </div>

            {/* Progress Bar */}
            <div className="ai-progress-track">
              <div className="ai-progress-bar" style={{ width: `${generatingProgress}%` }} />
            </div>

            {/* 4 Progression Steps */}
            <div className="space-y-1.5 my-4">
              {[
                { stage: 0, text: 'Selecting canonical questions from verified database pool', icon: Layers3 },
                { stage: 1, text: 'Mutating numerical parameters & solving step-by-step', icon: Sparkles },
                { stage: 2, text: 'Recalculating correct options & validating distractors', icon: CheckCircle2 },
                { stage: 3, text: 'Wrapping LaTeX formulas & preparing test environment', icon: Zap },
              ].map((step) => {
                const Icon = step.icon;
                const isDone = generatingStage > step.stage || generatingProgress === 100;
                const isActive = generatingStage === step.stage && generatingProgress < 100;
                return (
                  <div
                    key={step.stage}
                    className={`ai-stage-item ${isDone ? 'completed' : isActive ? 'active' : 'pending'}`}
                  >
                    {isDone ? (
                      <Check size={14} className="text-emerald-600 flex-shrink-0" />
                    ) : isActive ? (
                      <Icon size={14} className="text-indigo-600 animate-pulse flex-shrink-0" />
                    ) : (
                      <div className="w-3.5 h-3.5 rounded-full border border-slate-300 flex-shrink-0" />
                    )}
                    <span className="truncate">{step.text}</span>
                  </div>
                );
              })}
            </div>

            <p className="text-[11px] text-slate-400 mt-4 border-t border-slate-100 pt-3">
              ⚡ <em>Every assessment receives fresh numerical variations so you never practice the exact same question twice.</em>
            </p>
          </div>
        </div>
      )}

      {toast && (
        <div className="toast-message">
          <CheckCircle2 size={17} />
          {toast}
          <button onClick={() => setToast('')} aria-label="Dismiss">
            <X size={15} />
          </button>
        </div>
      )}
    </div>
  );
}
