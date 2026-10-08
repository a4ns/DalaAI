import { StrictMode, useRef, useState } from 'react';
import type { MouseEvent } from 'react';
import { createRoot } from 'react-dom/client';
import { PanelScreen } from '../../src/panel/PanelScreen';
import type { PanelOrder, PanelScreenProps } from '../../src/panel/types';
import type { ResourceState } from '../../src/shared/ui/types';
import '../../src/shared/styles.css';

type Interruption = 'none' | 'move-focus' | 'lose-access' | 'unmount' | 'select-order';
const rows: readonly PanelOrder[] = [
  { id: 'synthetic-panel-a', number: 'SYNTHETIC-PANEL-A', title: 'Синтетическая работа А', sectionLabel: 'Синтетический участок',
    equipmentLabel: 'Синтетическое оборудование А', executorLabel: 'Синтетический исполнитель', status: 'accepted', priority: 'normal',
    dueAt: '2026-10-08T00:00:00Z', isOverdue: true, version: 1 },
  { id: 'synthetic-panel-b', number: 'SYNTHETIC-PANEL-B', title: 'Синтетическая работа Б', sectionLabel: 'Синтетический участок',
    equipmentLabel: 'Синтетическое оборудование Б', executorLabel: 'Синтетический исполнитель', status: 'issued', priority: 'normal',
    dueAt: '2026-10-09T00:00:00Z', isOverdue: false, version: 1 },
];

function Fixture() {
  const [tick, setTick] = useState(0);
  const [access, setAccess] = useState<PanelScreenProps['access']>('allowed');
  const [mounted, setMounted] = useState(true);
  const [selected, setSelected] = useState<string | null>(null);
  const [interruption, setInterruption] = useState<Interruption>('none');
  const sentinel = useRef<HTMLButtonElement>(null);
  const orders: ResourceState<readonly PanelOrder[]> = {
    snapshot: rows.map(row => ({ ...row, version: 1 + Math.floor(tick / 2) })), freshness: 'fresh',
    loadStatus: tick % 2 ? 'loading' : 'ready', error: null, incomplete: false,
    lastConfirmedAt: new Date(Date.parse('2026-10-08T01:00:00Z') + Math.floor(tick / 2) * 1000).toISOString(),
  };

  // React bubbles this handler after the real PanelScreen reset handler, before its
  // batched commit. This is a controlled same-event interruption, not a mocked hook,
  // timer, focus implementation, server response, or product navigation integration.
  function interruptReset(event: MouseEvent<HTMLDivElement>) {
    const target = event.target;
    if (!(target instanceof Element) || target.closest('button')?.textContent !== 'Сбросить фильтры') return;
    if (interruption === 'move-focus') sentinel.current?.focus({ preventScroll: true });
    if (interruption === 'lose-access') setAccess('forbidden');
    if (interruption === 'unmount') setMounted(false);
    if (interruption === 'select-order') setSelected('synthetic-panel-b');
  }

  // Exclude browser scroll anchoring from this fixture so the scroll assertion
  // isolates native focus scrolling when filtering changes content height.
  return <div onClick={interruptReset} style={{ overflowAnchor: 'none' }}>
    <aside style={{ background: '#ffe9ab', padding: 16 }}>
      <strong>СИНТЕТИЧЕСКИЙ UI-ТЕСТ ФОКУСА. Без API, БД, настоящего устройства и экранного диктора.</strong>
      <p>Настоящий React-компонент панели; обновление данных и прерывания заданы только тестом.</p>
      <label>Синтетическое прерывание <select data-testid="interruption" value={interruption}
        onChange={event => setInterruption(event.target.value as Interruption)}>
        <option value="none">Нет</option><option value="move-focus">Другой фокус до commit</option>
        <option value="lose-access">Потеря доступа до commit</option><option value="unmount">Уход с панели до commit</option>
        <option value="select-order">Выбор другого наряда до commit</option>
      </select></label>
      <button type="button" data-testid="sentinel" ref={sentinel}>Другая синтетическая цель фокуса</button>
      <button type="button" data-testid="poll" onClick={() => setTick(value => value + 1)}>Шаг синтетического обновления</button>
      <button type="button" data-testid="restore" onClick={() => { setAccess('allowed'); setMounted(true); setInterruption('none'); }}>
        Восстановить синтетическую панель
      </button>
      <output data-testid="poll-tick" hidden>{tick}</output>
    </aside>
    {mounted ? <PanelScreen orders={orders} selectedOrderId={selected} onSelectOrder={setSelected}
      access={access} dataOrigin="synthetic" /> : <h1>Синтетическая панель закрыта</h1>}
    <footer style={{ minHeight: 1200, padding: 16 }}>Синтетическая область прокрутки для проверки preventScroll</footer>
  </div>;
}

createRoot(document.getElementById('root')!).render(<StrictMode><Fixture /></StrictMode>);
