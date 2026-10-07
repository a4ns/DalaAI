import { expect, test } from '@playwright/test';
import { createElement } from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { ssrSourceModule } from '../support/ssr-source';
import type * as Disclosure from '../../src/mobile/executor/ResultAnalysisDisclosure';
const { ResultAnalysisDisclosure, resultAssessmentMessage } = ssrSourceModule<typeof Disclosure>('src/mobile/executor/ResultAnalysisDisclosure.tsx');
const modes: Disclosure.ResultAnalysisMode[] = ['unknown', 'openai', 'rules_fallback'];
const render = (state?: Disclosure.ResultAnalysisDisclosureState) => renderToStaticMarkup(createElement(ResultAnalysisDisclosure, { state }));

test('result disclosure defaults to unknown, stays inert and makes only a conditional transfer statement', () => {
  const html = render();
  expect(html).toContain('Настроенный режим:</strong> не подтверждён');
  expect(html).toContain('Статус проверки результата не подтверждён');
  expect(html).toContain('Когда оператор включает OpenAI, описание выполненной работы и фотографии до и после выполнения передаются OpenAI');
  expect(html).toContain('Окончательное решение принимает мастер');
  expect(html).not.toMatch(/<button|<input|<form|<img|<iframe|<script|Результат анализа OpenAI получен|Проверка по правилам завершена/);
});

test('every configured mode remains independent of unknown, pending and failed assessment methods', () => {
  for (const configuredMode of modes) {
    for (const status of ['unknown', 'pending', 'failed'] as const) {
      for (const method of modes) {
        const html = render({ configuredMode, assessment: { status, method } });
        expect(html).not.toContain('Результат анализа OpenAI получен');
        expect(html).not.toContain('Проверка по правилам завершена');
        expect(html).not.toMatch(/Фото проверены|Работа безопасна|Работа выполнена правильно/);
        expect(html).toContain('Окончательное решение принимает мастер');
        const message = resultAssessmentMessage({ status, method });
        expect(message).toBe(status === 'unknown' ? 'Статус проверки результата не подтверждён.' : status === 'pending' ? 'Проверка результата ещё не завершена.' : 'Проверку результата не удалось завершить. Подтверждённого результата анализа нет.');
      }
    }
  }
});

test('completed result copy follows the supplied verified assessment method, never the configured operator mode', () => {
  for (const configuredMode of modes) {
    const rules = render({ configuredMode, assessment: { status: 'completed', method: 'rules_fallback' } });
    expect(rules).toContain('Проверка по правилам завершена. Это не подтверждает анализ содержимого фото моделью.');
    expect(rules).not.toContain('Результат анализа OpenAI получен');
    const openai = render({ configuredMode, assessment: { status: 'completed', method: 'openai' } });
    expect(openai).toContain('Результат анализа OpenAI получен');
    expect(openai).not.toContain('Проверка по правилам завершена');
    const unknownMethod = render({ configuredMode, assessment: { status: 'completed', method: 'unknown' } });
    expect(unknownMethod).toContain('Способ проверки не подтверждён');
    expect(unknownMethod).not.toMatch(/Результат анализа OpenAI получен|Проверка по правилам завершена/);
  }
});

test('rendering a newer unknown or failed result cannot retain a former completed provider claim', () => {
  const completed = render({ configuredMode: 'openai', assessment: { status: 'completed', method: 'openai' } });
  expect(completed).toContain('Результат анализа OpenAI получен');
  for (const state of [undefined, { configuredMode: 'openai' as const, assessment: { status: 'failed' as const, method: 'openai' as const } }]) {
    const next = render(state);
    expect(next).not.toContain('Результат анализа OpenAI получен');
    expect(next).not.toContain('Фото не отправлялись');
  }
});
