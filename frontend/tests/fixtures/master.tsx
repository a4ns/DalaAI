import { useRef, useState } from 'react';
import { createRoot } from 'react-dom/client';
import { MasterScreen, emptyMasterCreateDraft } from '../../src/mobile/master/MasterScreen';
import type { MasterCreateDraft, MasterDictionaries, MasterOrderVM } from '../../src/mobile/master/types';
import type { MutationOutcome, ResourceState } from '../../src/shared/ui/types';
import '../../src/shared/styles.css';

const fresh = <T,>(snapshot: T, stamp = '2026-10-07T19:00:00Z'): ResourceState<T> => ({ snapshot, freshness: 'fresh', loadStatus: 'ready', error: null, lastConfirmedAt: stamp, incomplete: false });
const dictionaries: MasterDictionaries = {
  sections: [{ id: 'section', label: 'Синтетический участок' }], equipment: [{ id: 'equipment', label: 'Синтетический насос', sectionId: 'section' }],
  brigades: [], executors: [{ id: 'executor', label: 'Синтетический исполнитель', sectionIds: ['section'], brigadeId: null, onShift: true, activeOrderId: null, queueCount: 0 }],
};
const initial = (): MasterCreateDraft => ({ ...emptyMasterCreateDraft(), description: 'Синтетическая задача', sectionId: 'section', equipmentId: 'equipment', executorId: 'executor', dueLocal: '2026-10-08T09:00', normMinutes: '30' });
function Fixture() {
  const [epoch, setEpoch] = useState(1);
  const [draft, setDraft] = useState(initial);
  const [outcome, setOutcome] = useState<'unknown' | 'conflict'>('unknown');
  const [stamp, setStamp] = useState('2026-10-07T19:00:00Z');
  const [calls, setCalls] = useState(0);
  const [retries, setRetries] = useState(0);
  const delayedPhoto = useRef<((ids: string[]) => void) | null>(null);
  const photoSequence = useRef(0);
  const reply = async (): Promise<MutationOutcome> => { setCalls(value => value + 1); return { kind: outcome, message: 'Синтетический ответ UI-теста' }; };
  return <>
    <aside style={{ background: '#ffe9ab', padding: 16 }}><strong>СИНТЕТИЧЕСКИЙ UI-ТЕСТ. Без API, БД и настоящей загрузки фото.</strong>
      <select data-testid="outcome" value={outcome} onChange={event => setOutcome(event.target.value as 'unknown' | 'conflict')} aria-label="Тестовый исход"><option value="unknown">Потерян ответ</option><option value="conflict">Конфликт</option></select>
      <button data-testid="complete-photo" onClick={() => { photoSequence.current += 1; delayedPhoto.current?.([`synthetic-confirmed-photo-${photoSequence.current}`]); }}>Завершить тестовое фото</button>
      <button data-testid="switch-identity" onClick={() => { setEpoch(value => value + 1); setDraft(initial()); }}>Сменить тестовую сессию</button>
      <output hidden data-testid="draft">{JSON.stringify(draft)}</output><output hidden data-testid="calls">{calls}</output><output hidden data-testid="retries">{retries}</output>
    </aside>
    <MasterScreen key={epoch} dictionaries={fresh(dictionaries, stamp)} orders={fresh<MasterOrderVM[]>([], stamp)}
      createDraft={draft} onCreateDraftChange={setDraft} reviewDrafts={{}} onReviewDraftChange={() => undefined} online domainNow="2026-10-07T19:00:00Z"
      onCreate={reply} onReview={reply} onRetryCreate={async () => { setRetries(value => value + 1); return { kind: 'confirmed' }; }}
      onReload={async () => setStamp('2026-10-07T19:01:00Z')}
      renderBeforePhotos={context => <button disabled={context.disabled} type="button" data-testid="start-photo" onClick={() => { delayedPhoto.current = context.onPhotoIdsChange; }}>Начать синтетическое фото</button>}/>
  </>;
}
createRoot(document.getElementById('root')!).render(<Fixture/>);
