import { useRef, useState } from 'react';
import { createRoot } from 'react-dom/client';
import { ExecutorScreen } from '../../src/mobile/executor/ExecutorScreen';
import type { ExecutorDraft, ExecutorIntent, ExecutorIntentSummary, ExecutorOrderViewModel } from '../../src/mobile/executor/types';
import { PhotoPicker } from '../../src/pwa/PhotoPicker';
import { preparePhoto } from '../../src/pwa/photoPreparation';
import type { PreparedPhoto } from '../../src/pwa/photoPreparation';
import type { MutationOutcome, MutationState, ResourceState } from '../../src/shared/ui/types';
import '../../src/shared/styles.css';

const resource = <T,>(snapshot: T, version = 0): ResourceState<T> => ({ snapshot, freshness: 'fresh', loadStatus: 'ready', lastConfirmedAt: new Date(Date.parse('2026-10-08T00:00:00Z') + version * 1000).toISOString(), incomplete: false, error: null });
const initialOrders = (): ExecutorOrderViewModel[] => ['A', 'B'].map(letter => ({ id: `synthetic-${letter}`, number: `OWNED-${letter}`, version: 1, assignmentRevision: 1, sectionId: 'synthetic-section', sectionLabel: 'Синтетический участок', equipmentLabel: `Синтетическое оборудование ${letter}`, status: 'issued', type: 'planned', priority: 'normal', description: Array(12).fill(`Синтетический наряд ${letter}. Проверка намеренной прокрутки и поздних ответов.`).join('\n'), comment: '', dueAt: '2026-10-08T04:00:00Z', isOverdue: false }));
type Operation = { mutation: MutationState; intent: ExecutorIntentSummary | null };
const idle = (): Operation => ({ mutation: { status: 'idle', error: null }, intent: null });
type Pending = { orderId: string; intent: ExecutorIntentSummary; resolve: (outcome: MutationOutcome) => void };
function photoFile(name: string): File {
  const canvas = document.createElement('canvas'); canvas.width = 32; canvas.height = 32;
  const context = canvas.getContext('2d'); if (!context) throw new Error('Synthetic fixture requires Canvas2D');
  context.fillStyle = '#27856d'; context.fillRect(0, 0, 32, 32);
  const bytes = Uint8Array.from(atob(canvas.toDataURL('image/png').split(',')[1]), char => char.charCodeAt(0));
  return new File([bytes], name, { type: 'image/png' });
}
function Fixture() {
  const [orders, setOrders] = useState(initialOrders);
  const [selected, setSelected] = useState('synthetic-A');
  const [revision, setRevision] = useState(0);
  const [drafts, setDrafts] = useState<Record<string, ExecutorDraft>>({});
  const [operations, setOperations] = useState<Record<string, Operation>>({});
  const [commands, setCommands] = useState(0); const [retries, setRetries] = useState(0);
  const pending = useRef<Pending | null>(null);
  function reserve(orderId: string, intent: ExecutorIntentSummary): Promise<MutationOutcome> {
    setOperations(previous => ({ ...previous, [orderId]: { intent, mutation: { status: 'pending', error: null } } }));
    return new Promise(resolve => { pending.current = { orderId, intent, resolve }; });
  }
  function onIntent(intent: ExecutorIntent): Promise<MutationOutcome> {
    setCommands(value => value + 1);
    return reserve(intent.orderId, { orderId: intent.orderId, expectedVersion: intent.expectedVersion, action: intent.action });
  }
  function settle(kind: 'confirmed' | 'unknown') {
    const request = pending.current; if (!request) return; pending.current = null;
    const outcome: MutationOutcome = kind === 'confirmed' ? { kind } : { kind, message: 'Синтетический потерянный ответ' };
    setOperations(previous => ({ ...previous, [request.orderId]: { intent: request.intent, mutation: { status: kind === 'confirmed' ? 'confirmed' : 'unknown_result', error: kind === 'confirmed' ? null : 'Синтетический потерянный ответ' } } }));
    if (kind === 'confirmed') setOrders(previous => previous.map(order => order.id === request.orderId ? { ...order, version: order.version + 1, status: 'accepted' } : order));
    request.resolve(outcome);
  }
  function poll(confirmed = false) {
    const current = orders.find(order => order.id === selected)!;
    setRevision(value => value + 1); setOrders(previous => previous.map(order => ({ ...order, version: order.version + 1 })));
    if (confirmed) setOperations(previous => ({ ...previous, [selected]: { intent: { orderId: selected, expectedVersion: current.version, action: 'accept' }, mutation: { status: 'confirmed', error: null } } }));
  }
  const operation = operations[selected] ?? idle();
  const [photos, setPhotos] = useState<PreparedPhoto[]>([]);
  const [photoDisabled, setPhotoDisabled] = useState(false); const [photoBusy, setPhotoBusy] = useState(false);
  const [seeding, setSeeding] = useState(false);
  const [deletion, setDeletion] = useState<'immediate' | 'deferred' | 'redirect'>('immediate');
  const delayedPhotos = useRef<PreparedPhoto[] | null>(null); const outside = useRef<HTMLInputElement>(null);
  async function seedPhotos() {
    setSeeding(true);
    try { setPhotos(await Promise.all([preparePhoto(photoFile('synthetic-one.png')), preparePhoto(photoFile('synthetic-two.png'))])); }
    finally { setSeeding(false); }
  }
  function changePhotos(next: PreparedPhoto[]) {
    if (deletion === 'deferred') { delayedPhotos.current = next; return; }
    setPhotos(next); if (deletion === 'redirect') outside.current?.focus();
  }
  return <main style={{ maxWidth: 1100, margin: '0 auto', padding: 12 }}>
    <aside style={{ padding: 12, background: '#fff0bc' }} aria-label="Синтетические управляющие события">
      <strong>СИНТЕТИЧЕСКИЙ ТЕСТ реальных компонентов. Без API, БД, модели и физического устройства.</strong>
      <p>Обычный ответ, поздний ответ и обновление снимка задаются явно. Прокрутку и фокус выполняют сами выпущенные компоненты.</p>
      <button type="button" data-testid="resolve-confirmed" onClick={() => settle('confirmed')}>Завершить ответ подтверждением</button>
      <button type="button" data-testid="resolve-unknown" onClick={() => settle('unknown')}>Завершить ответ неопределённостью</button>
      <button type="button" data-testid="poll" onClick={() => poll()}>Синтетическое обновление снимка</button>
      <button type="button" data-testid="poll-confirmed" onClick={() => poll(true)}>Подтверждение только из снимка</button>
      <output data-testid="command-count" hidden>{commands}</output><output data-testid="retry-count" hidden>{retries}</output>
    </aside>
    <ExecutorScreen sessionKey="synthetic-owned-session" operationScopeKey={`synthetic-owned-session/${selected}/1`}
      orders={resource(orders, revision)} dictionaries={resource({ workCodes: [], materials: [] })} selectedOrderId={selected}
      drafts={drafts} mutation={operation.mutation} pendingIntent={operation.intent}
      onSelectOrder={setSelected} onDraftChange={(id, draft) => setDrafts(previous => ({ ...previous, [id]: draft }))}
      onIntent={onIntent} onRetry={() => { setRetries(value => value + 1); if (!operation.intent) return Promise.resolve({ kind: 'rejected', message: 'Нет исходного намерения' }); return reserve(selected, operation.intent); }}
      onRefresh={() => poll()} onResolveConflict={() => setOperations(previous => ({ ...previous, [selected]: idle() }))}/>
    <section aria-label="Синтетические события фото" style={{ marginTop: 24 }}>
      <h2>Подготовка и удаление синтетических фото</h2>
      <p>Изображения создаются Canvas2D этой страницы и проходят настоящий preparePhoto. Это не камера, серверная загрузка или доказательство работ.</p>
      <button type="button" data-testid="seed-photos" disabled={seeding || photoBusy} onClick={() => { void seedPhotos(); }}>Подготовить два синтетических фото</button>
      <button type="button" data-testid="disable-photos" onClick={() => setPhotoDisabled(true)}>Прервать подготовку внешней блокировкой</button>
      <button type="button" data-testid="enable-photos" onClick={() => setPhotoDisabled(false)}>Снять внешнюю блокировку</button>
      <label>Тестовое применение удаления<select data-testid="deletion-mode" value={deletion} onChange={event => setDeletion(event.target.value as typeof deletion)}><option value="immediate">Сразу</option><option value="deferred">Поздний ответ родителя</option><option value="redirect">Фокус уже передан другому полю</option></select></label>
      <button type="button" data-testid="apply-delayed-delete" onClick={() => { if (delayedPhotos.current) { setPhotos(delayedPhotos.current); delayedPhotos.current = null; } }}>Применить позднее удаление</button>
      <label>Другое поле для внимания<input ref={outside} data-testid="outside-focus" /></label>
      <output data-testid="photo-count" hidden>{photos.length}</output><output data-testid="photo-busy" hidden>{String(photoBusy)}</output>
      <PhotoPicker contextKey="synthetic-owned-photo-context" phase="after" value={photos} maxPhotos={2} disabled={photoDisabled} onChange={changePhotos} onBusyChange={setPhotoBusy}/>
    </section>
  </main>;
}
createRoot(document.getElementById('root')!).render(<Fixture/>);
