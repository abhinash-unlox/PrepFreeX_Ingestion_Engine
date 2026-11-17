// PrepFreeX Typed REST API Client

const BASE_URL = typeof window !== 'undefined' ? '' : 'http://127.0.0.1:8000';

class ApiClient {
  private token: string | null = null;

  constructor() {
    if (typeof window !== 'undefined') {
      this.token = localStorage.getItem('prepfreex_token');
    }
  }

  setToken(token: string) {
    this.token = token;
    if (typeof window !== 'undefined') {
      localStorage.setItem('prepfreex_token', token);
    }
  }

  clearToken() {
    this.token = null;
    if (typeof window !== 'undefined') {
      localStorage.removeItem('prepfreex_token');
    }
  }

  private async fetch<T>(endpoint: string, options: RequestInit = {}): Promise<T> {
    const urlsToTry = [
      `${BASE_URL}${endpoint}`,
      `http://127.0.0.1:8000${endpoint}`,
    ];

    let lastError: any = null;

    for (const url of urlsToTry) {
      try {
        const headers: Record<string, string> = {
          'Content-Type': 'application/json',
          ...(options.headers as Record<string, string> || {}),
        };

        if (this.token) {
          headers['Authorization'] = `Bearer ${this.token}`;
        }

        const res = await fetch(url, {
          ...options,
          headers,
        });

        if (!res.ok) {
          let errorMsg = `Request failed with status ${res.status}`;
          try {
            const errorData = await res.json();
            errorMsg = errorData.detail || errorMsg;
          } catch {
            // ignore
          }
          // The server responded with an application error — do not mask it with CORS retry
          const appError: any = new Error(errorMsg);
          appError.status = res.status;
          throw appError;
        }

        return await res.json();
      } catch (err: any) {
        lastError = err;
        // If the server answered with an HTTP error code, surface that actual error
        if (err.status || (err.message && !err.message.includes('fetch'))) {
          throw err;
        }
      }
    }

    throw lastError || new Error('Network error');
  }

  // Health
  async health() {
    return this.fetch<{ status: string; database_connected: boolean; database_name: string }>('/api/v1/health');
  }

  // Auth
  async login(email: string, password: string) {
    const data = await this.fetch<{ access_token: string; user: any }>('/api/v1/auth/login', {
      method: 'POST',
      body: JSON.stringify({ email, password }),
    });
    if (data.access_token) {
      this.setToken(data.access_token);
    }
    return data;
  }

  async getMe() {
    return this.fetch<any>('/api/v1/auth/me');
  }

  // Taxonomy
  async getSubjects() {
    return this.fetch<Array<{ code: string; name: string; total_chapters: number; total_topics: number }>>('/api/v1/taxonomy/subjects');
  }

  async getChapters(subject?: string) {
    const q = subject ? `?subject=${encodeURIComponent(subject)}` : '';
    return this.fetch<Array<{
      id: number;
      unit_code: string;
      chapter_name: string;
      chapter_slug: string;
      subject: string;
      total_topics: number;
      eligible_question_count: number;
    }>>(`/api/v1/taxonomy/chapters${q}`);
  }

  async getTopics(chapterCode?: string) {
    const q = chapterCode ? `?chapter_code=${encodeURIComponent(chapterCode)}` : '';
    return this.fetch<Array<{
      id: number;
      topic_code: string;
      topic_name: string;
      topic_number: number;
      unit_code: string;
      subject: string;
      eligible_question_count: number;
    }>>(`/api/v1/taxonomy/topics${q}`);
  }

  async getTaxonomyTree() {
    return this.fetch<any>('/api/v1/taxonomy/tree');
  }

  // Assessments
  async getAssessmentTypes() {
    return this.fetch<Array<{
      type: string;
      description: string;
      default_duration_min: number;
      default_questions: number;
      icon: string;
    }>>('/api/v1/assessments/types');
  }

  async previewAssessment(payload: {
    assessment_type: string;
    subject: string;
    chapter_code?: string;
    topic_code?: string;
    selected_chapters?: string[];
    selected_topics?: string[];
    question_count?: number;
    duration_minutes?: number;
  }) {
    return this.fetch<{
      assessment_type: string;
      subject: string;
      available_questions: number;
      requested_count: number;
      can_fulfill: boolean;
      duration_minutes: number;
    }>('/api/v1/assessments/preview', {
      method: 'POST',
      body: JSON.stringify(payload),
    });
  }

  async createAssessment(payload: {
    assessment_type: string;
    subject: string;
    chapter_code?: string;
    topic_code?: string;
    selected_chapters?: string[];
    selected_topics?: string[];
    question_count?: number;
    duration_minutes?: number;
  }) {
    return this.fetch<{
      assessment_id: string;
      title: string;
      assessment_type: string;
      subject: string;
      total_questions: number;
      duration_minutes: number;
      server_start_time: string;
      server_deadline: string;
    }>('/api/v1/assessments', {
      method: 'POST',
      body: JSON.stringify(payload),
    });
  }

  async getAssessmentQuestions(assessmentId: string) {
    return this.fetch<{
      assessment_id: string;
      questions: Array<{
        id?: number;
        question_instance_id?: number;
        index: number;
        question_number: number;
        question_uid: string;
        subject: string;
        chapter: string;
        topic: string;
        type: 'single' | 'numerical' | 'multiple';
        text: string;
        options: string[];
        has_diagram: boolean;
        diagram_s3_key?: string;
        saved_option?: string;
        saved_numerical?: number;
        is_marked?: boolean;
        is_variant?: boolean;
        variant_id?: number;
      }>;
    }>(`/api/v1/assessments/${assessmentId}/questions`);
  }

  async getAssessmentQuestion(assessmentId: string, questionIdentifier: string | number) {
    return this.fetch<any>(`/api/v1/assessments/${assessmentId}/questions/${questionIdentifier}`);
  }

  async saveResponse(assessmentId: string, questionIdentifier: string | number, payload: {
    selected_option?: string | null;
    numerical_entered?: number | null;
    time_spent_seconds?: number;
    is_marked_review?: boolean;
  }) {
    return this.fetch<{ status: string; question_identifier: string | number }>(`/api/v1/assessments/${assessmentId}/responses/${questionIdentifier}`, {
      method: 'PUT',
      body: JSON.stringify(payload),
    });
  }

  async submitAssessment(assessmentId: string) {
    return this.fetch<{
      status: string;
      assessment_id: string;
      total_score: number;
      max_marks: number;
      accuracy_percentage: number;
      correct_questions: number;
      incorrect_questions: number;
      unattempted_questions: number;
    }>(`/api/v1/assessments/${assessmentId}/submit`, {
      method: 'POST',
    });
  }

  async getAssessmentResults(assessmentId: string) {
    return this.fetch<{
      assessment_id: string;
      title: string;
      assessment_type: string;
      status: string;
      total_score: number;
      max_marks: number;
      accuracy: number;
      total_questions: number;
      attempted: number;
      correct: number;
      incorrect: number;
      unattempted: number;
      subject_breakdown: Array<{
        name: string;
        total: number;
        attempted: number;
        correct: number;
        marks: number;
        accuracy: number;
      }>;
    }>(`/api/v1/assessments/${assessmentId}/results`);
  }

  async getAssessmentReview(assessmentId: string) {
    return this.fetch<{
      assessment_id: string;
      review: Array<{
        index: number;
        question_number: number;
        question_uid: string;
        subject: string;
        chapter: string;
        topic: string;
        text: string;
        options: string[];
        user_response: string;
        correct_answer: string;
        is_correct: boolean;
        marks_awarded: number;
        explanation: string;
      }>;
    }>(`/api/v1/assessments/${assessmentId}/review`);
  }

  // Student Dashboard & History
  async getStudentDashboard() {
    return this.fetch<{
      student_name: string;
      target_exam: string;
      study_streak_days: number;
      daily_goal_sessions: number;
      daily_goal_completed: number;
      questions_attempted: number;
      overall_accuracy: number;
      tests_completed: number;
      weekly_progress: Array<{ day: string; questions: number }>;
      subject_stats: Array<{ name: string; score: number; fill: string }>;
      recent_tests: Array<{
        id: string;
        title: string;
        subject: string;
        date: string;
        score: string;
        accuracy: string;
        color: string;
      }>;
    }>('/api/v1/students/me/dashboard');
  }

  async getStudentHistory() {
    return this.fetch<{
      total: number;
      attempts: Array<{
        id: string;
        title: string;
        subject: string;
        date: string;
        score: string;
        accuracy: string;
        color: string;
      }>;
    }>('/api/v1/students/me/history');
  }

  async getStudentPerformance() {
    return this.fetch<any>('/api/v1/students/me/performance');
  }

  // Image Test Helper
  async getImageTestQuestions(subject?: string, status: string = 'ELIGIBLE') {
    const params = new URLSearchParams();
    if (subject && subject !== 'ALL') params.append('subject', subject);
    if (status) params.append('status', status);
    return this.fetch<{
      total: number;
      status_filter: string;
      questions: Array<any>;
    }>(`/api/v1/assessments/image-test/questions?${params.toString()}`);
  }

  // Diagram URL helper
  getDiagramUrl(s3KeyOrAssetId: string | number): string {
    return `/api/v1/images/${s3KeyOrAssetId}/raw`;
  }
}

export const apiClient = new ApiClient();
