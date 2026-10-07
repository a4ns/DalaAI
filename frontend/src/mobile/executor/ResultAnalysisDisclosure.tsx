/** UI-only evidence supplied by the composition layer, never inferred from missing API data. */
export type ResultAnalysisMode = 'unknown' | 'openai' | 'rules_fallback';
export type ResultAssessmentStatus = 'unknown' | 'pending' | 'completed' | 'failed';
export interface ResultAnalysisDisclosureState {
  /** Current operator configuration, independent of what happened for this result. */
  configuredMode: ResultAnalysisMode;
  /** Completed requires a server-confirmed assessment for the current authorized attempt,
   * including verified provider identity. Configuration alone is never that evidence. */
  assessment: { status: ResultAssessmentStatus; method: ResultAnalysisMode };
}
export interface ResultAnalysisDisclosureProps {
  /** Missing input preserves unknown mode and unknown assessment. */
  state?: ResultAnalysisDisclosureState;
}

const MODE_LABELS: Record<ResultAnalysisMode, string> = {
  unknown: 'не подтверждён',
  openai: 'OpenAI',
  rules_fallback: 'проверка по правилам',
};
const UNKNOWN_STATE: ResultAnalysisDisclosureState = {
  configuredMode: 'unknown',
  assessment: { status: 'unknown', method: 'unknown' },
};

export function resultAssessmentMessage(assessment?: ResultAnalysisDisclosureState['assessment']): string {
  if (!assessment) return 'Статус проверки результата не подтверждён.';
  if (assessment.status === 'pending') return 'Проверка результата ещё не завершена.';
  if (assessment.status === 'failed') return 'Проверку результата не удалось завершить. Подтверждённого результата анализа нет.';
  if (assessment.status !== 'completed') return 'Статус проверки результата не подтверждён.';
  if (assessment.method === 'openai') return 'Результат анализа OpenAI получен.';
  if (assessment.method === 'rules_fallback') return 'Проверка по правилам завершена. Это не подтверждает анализ содержимого фото моделью.';
  return 'Проверка завершена. Способ проверки не подтверждён.';
}

/** Read-only disclosure. This component enables nothing and sends no work text or images. */
export function ResultAnalysisDisclosure({ state = UNKNOWN_STATE }: ResultAnalysisDisclosureProps) {
  const configuredMode = MODE_LABELS[state.configuredMode] ?? MODE_LABELS.unknown;
  return <section className="executor-notice" aria-label="Как проверяется результат">
    <h3>Проверка результата</h3>
    <p>Когда оператор включает OpenAI, описание выполненной работы и фотографии до и после выполнения передаются OpenAI для анализа. Иначе используется проверка по правилам.</p>
    <p><strong>Настроенный режим:</strong> {configuredMode}.</p>
    <p aria-live="polite">{resultAssessmentMessage(state.assessment)}</p>
    <p>Окончательное решение принимает мастер.</p>
  </section>;
}
