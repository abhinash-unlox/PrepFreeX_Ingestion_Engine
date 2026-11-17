import { createFullMockQuestions } from './jee-mock-pattern';

export type AssessmentKind = 'Topic Practice' | 'Chapter Test' | 'Mixed-topic Test' | 'Sectional Assessment' | 'Full-length Mock' | 'Image Test';
export type Question = { id: number; subject: string; topic: string; type: 'single' | 'multiple' | 'numerical'; text: string; options?: string[]; answer: number | number[] | string; explanation: string };
export const assessmentKinds: { title: AssessmentKind; description: string; icon: string; duration: string; count: string }[] = [
  { title: 'Topic Practice', description: 'Focused drill on a single official topic.', icon: 'Target', duration: '15 min', count: '5 questions' },
  { title: 'Chapter Test', description: 'Comprehensive test across all 4 topics of a chapter.', icon: 'BookOpen', duration: '60 min', count: '20 questions (5/topic)' },
  { title: 'Mixed-topic Test', description: 'Combine chapters and topics with 5 questions per topic.', icon: 'Layers3', duration: 'Custom', count: '5 questions / topic' },
  { title: 'Sectional Assessment', description: 'A timed, subject-wise JEE Main simulation.', icon: 'Timer', duration: '60 min', count: '25 questions' },
  { title: 'Full-length Mock', description: 'JEE Main Paper 1: three subjects, 25 questions each.', icon: 'Award', duration: '3 hours', count: '75 · 300 marks' },
  { title: 'Image Test', description: 'Test and inspect all questions with diagrams stored in MinIO.', icon: 'Image', duration: 'Flexible', count: '47+ questions' },
];
export { chapters, topicsByChapter } from './jee-syllabus';
export const questions: Question[] = [
  { id: 1, subject: 'Physics', topic: 'Electrostatics', type: 'single', text: 'Two point charges $+q$ and $-q$ are placed at a distance $2a$. The electric field at the midpoint is:', options: ['$0$', '$\\dfrac{kq}{a^2}$', '$\\dfrac{2kq}{a^2}$', '$\\dfrac{4kq}{a^2}$'], answer: 2, explanation: 'At the midpoint, fields due to both charges point from +q toward −q. Each has magnitude $kq/a^2$, so the net field is $2kq/a^2$.' },
  { id: 2, subject: 'Chemistry', topic: 'Chemical Bonding', type: 'single', text: 'The hybridisation and shape of the central atom in $\\mathrm{SF_4}$ are:', options: ['sp³, tetrahedral', 'sp³d, see-saw', 'sp³d², square planar', 'sp², trigonal planar'], answer: 1, explanation: 'Sulfur has five electron domains in SF₄: four bond pairs and one lone pair. The electron geometry is trigonal bipyramidal and the molecular shape is see-saw.' },
  { id: 3, subject: 'Mathematics', topic: 'Limits & Continuity', type: 'numerical', text: 'Evaluate $\\displaystyle \\lim_{x \\to 0} \\frac{\\sin 3x}{x}$. Enter the numerical value.', answer: '3', explanation: 'Using $\\lim_{u\\to0} \\sin u/u=1$, rewrite as $3\\cdot\\sin(3x)/(3x)$, giving 3.' },
  { id: 4, subject: 'Physics', topic: 'Current Electricity', type: 'multiple', text: 'For a metallic conductor at constant temperature, select all correct statements.', options: ['Drift velocity is proportional to electric field', 'Resistance is independent of length', 'Current density is proportional to electric field', 'Resistivity depends on the conductor geometry'], answer: [0, 2], explanation: 'For an ohmic conductor, $v_d\\propto E$ and $J=\\sigma E$. Resistance depends on length, while resistivity is a material property independent of geometry.' },
  { id: 5, subject: 'Mathematics', topic: 'Vectors & 3D', type: 'single', text: 'If $\\vec a\\cdot\\vec b=0$ and $|\\vec a|=3$, $|\\vec b|=4$, then $|\\vec a+\\vec b|$ equals:', options: ['$1$', '$5$', '$7$', '$12$'], answer: 1, explanation: 'The vectors are perpendicular, so $|\\vec a+\\vec b|^2=|\\vec a|^2+|\\vec b|^2=9+16=25$.' },
  { id: 6, subject: 'Physics', topic: 'Kinematics', type: 'numerical', text: 'A body moves at a constant speed of 12 m/s for 5 s. What distance does it travel? Enter a numerical value in metres.', answer: '60', explanation: 'Distance equals speed multiplied by time: $12\\times5=60$ m.' },
  { id: 7, subject: 'Chemistry', topic: 'Some Basic Concepts in Chemistry', type: 'numerical', text: 'How many moles are present in 18 g of water ($\\mathrm{H_2O}$)? Use a molar mass of 18 g/mol.', answer: '1', explanation: 'The amount of substance is mass divided by molar mass: $18/18=1$ mol.' },
];
export const fullMockQuestions = createFullMockQuestions(questions);
export const weeklyProgress = [{ day: 'Mon', questions: 32 }, { day: 'Tue', questions: 48 }, { day: 'Wed', questions: 35 }, { day: 'Thu', questions: 62 }, { day: 'Fri', questions: 44 }, { day: 'Sat', questions: 76 }, { day: 'Sun', questions: 58 }];
export const subjectStats = [{ name: 'Physics', score: 78, fill: '#4f46e5' }, { name: 'Chemistry', score: 66, fill: '#0891b2' }, { name: 'Mathematics', score: 84, fill: '#f59e0b' }];
export const recentTests = [
  { title: 'Electrostatics · Topic practice', subject: 'Physics', date: 'Today, 10:42 AM', score: '18 / 25', accuracy: '72%', color: 'violet' },
  { title: 'Chemical Bonding · Chapter test', subject: 'Chemistry', date: 'Yesterday', score: '31 / 40', accuracy: '78%', color: 'cyan' },
  { title: 'JEE Main Mock Test 04', subject: 'Full mock', date: 'Oct 26, 2026', score: '186 / 300', accuracy: '74%', color: 'amber' },
];
