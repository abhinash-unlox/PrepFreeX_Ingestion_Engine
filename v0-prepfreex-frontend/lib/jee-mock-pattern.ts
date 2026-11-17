export const fullMockSubjects = ['Physics', 'Chemistry', 'Mathematics'] as const;
export const fullMockQuestionsPerSubject = 25;
export const fullMockMcqPerSubject = 20;
export const fullMockNumericalPerSubject = 5;
export const fullMockDurationMinutes = 180;
export const fullMockTotalQuestions = fullMockSubjects.length * fullMockQuestionsPerSubject;
export const fullMockTotalMarks = fullMockTotalQuestions * 4;

export function createFullMockQuestions<T extends { subject: string; type: string }>(questions: T[]) {
  return fullMockSubjects.flatMap((subject) => {
    const multipleChoice = questions.filter((question) => question.subject === subject && question.type === 'single');
    const numerical = questions.filter((question) => question.subject === subject && question.type === 'numerical');

    if (!multipleChoice.length || !numerical.length) {
      throw new Error(`Full mock question bank must include MCQ and numerical questions for ${subject}.`);
    }

    return [
      ...Array.from({ length: fullMockMcqPerSubject }, (_, index) => multipleChoice[index % multipleChoice.length]),
      ...Array.from({ length: fullMockNumericalPerSubject }, (_, index) => numerical[index % numerical.length]),
    ];
  });
}
