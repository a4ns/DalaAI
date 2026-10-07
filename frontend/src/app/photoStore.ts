import { ApiError, safeErrorMessage, SessionChangedError } from '../shared/api/client';
import type { ApiClient, PreparedMutation, StagePhotoInput } from '../shared/api/client';
import type { StagedPhoto } from '../shared/api/wire';
import { mutationFailureState } from './mutationFailure';
import type { PreparedPhoto } from '../pwa/photoPreparation';

export type PhotoContext = { key: string; sectionId: string; phase: 'before' } | { key: string; sectionId: string; phase: 'after'; orderId: string; assignmentRevision: number };
export interface PhotoJob { status: 'pending' | 'unknown' | 'confirmed' | 'failed'; error: string | null; photo: StagedPhoto | null }
export interface PhotoBag { files: readonly PreparedPhoto[]; processing: boolean; jobs: Readonly<Record<string, PhotoJob>> }
const EMPTY: PhotoBag = { files: [], processing: false, jobs: {} };

/** Memory-only, per-session photo intents. Selection, preparation and server receipts are distinct. */
export class PhotoStore {
  #client: ApiClient;
  #epoch: number;
  #bags = new Map<string, PhotoBag>();
  #tokens = new Map<string, PreparedMutation<StagedPhoto>>();
  #unresolved = new Set<string>();
  #listeners = new Set<() => void>();
  #version = 0;
  #now = Date.now();
  constructor(client: ApiClient) { this.#client = client; this.#epoch = client.epoch; }
  subscribe = (listener: () => void): (() => void) => { this.#listeners.add(listener); return () => { this.#listeners.delete(listener); }; };
  get hasWork(): boolean { return [...this.#bags.values()].some(bag => bag.processing || bag.files.length > 0); }
  getSnapshot = (): number => this.#version;
  isExpired(photo: StagedPhoto): boolean { return Date.parse(photo.expires_at) <= this.#now; }
  tick(): void {
    const previous = this.#now; this.#now = Date.now();
    const expired = [...this.#bags.values()].some(bag => Object.values(bag.jobs).some(job => job.photo && Date.parse(job.photo.expires_at) > previous && this.isExpired(job.photo)));
    if (expired) { this.#version++; this.#listeners.forEach(listener => listener()); }
  }
  get(context: PhotoContext): PhotoBag { return this.#bags.get(context.key) ?? EMPTY; }
  #set(context: PhotoContext, bag: PhotoBag): void { if (this.#client.epoch !== this.#epoch) return; this.#bags.set(context.key, bag); this.#version++; this.#listeners.forEach(listener => listener()); }
  processing(context: PhotoContext, busy: boolean): void { this.#set(context, { ...this.get(context), processing: busy }); }
  blocked(context: PhotoContext): boolean {
    const bag = this.get(context);
    return bag.processing || bag.files.some(file => bag.jobs[file.id]?.status !== 'confirmed' || Boolean(bag.jobs[file.id].photo && this.isExpired(bag.jobs[file.id].photo!)));
  }
  transportLocked(context: PhotoContext): boolean { return Object.values(this.get(context).jobs).some(job => job.status === 'pending' || job.status === 'unknown'); }
  confirmedIds(context: PhotoContext): string[] {
    const bag = this.get(context);
    return bag.files.flatMap(file => { const job = bag.jobs[file.id]; return job?.status === 'confirmed' && job.photo && !this.isExpired(job.photo) ? [job.photo.id] : []; });
  }
  select(context: PhotoContext, files: PreparedPhoto[]): void {
    if (this.transportLocked(context) || this.#client.epoch !== this.#epoch) return;
    const prior = this.get(context); const jobs: Record<string, PhotoJob> = {};
    for (const file of files) jobs[file.id] = prior.jobs[file.id] ?? { status: 'pending', error: null, photo: null };
    // Reserve every new upload synchronously before local preparation announces it is finished.
    this.#set(context, { ...prior, files: [...files], jobs });
    for (const file of files) if (!prior.jobs[file.id]) void this.#send(context, file);
  }
  retry(context: PhotoContext, file: PreparedPhoto): void {
    if (this.get(context).jobs[file.id]?.status === 'pending' || this.#client.epoch !== this.#epoch) return;
    const job = this.get(context).jobs[file.id];
    if (!job || (job.status !== 'unknown' && job.status !== 'failed')) return;
    this.#job(context, file.id, { ...job, status: 'pending', error: null });
    void this.#send(context, file);
  }
  #job(context: PhotoContext, fileId: string, job: PhotoJob): void {
    const bag = this.get(context);
    if (!bag.files.some(file => file.id === fileId)) return;
    this.#set(context, { ...bag, jobs: { ...bag.jobs, [fileId]: job } });
  }
  async #send(context: PhotoContext, file: PreparedPhoto): Promise<void> {
    const key = `${context.key}:${file.id}`;
    try {
      let token = this.#tokens.get(key);
      if (!token) {
        const input: StagePhotoInput = context.phase === 'before' ? { purpose: 'before', sectionId: context.sectionId, file: file.file } : { purpose: 'after', sectionId: context.sectionId, orderId: context.orderId, assignmentRevision: context.assignmentRevision, file: file.file };
        token = await this.#client.preparePhoto(input);
        if (this.#client.epoch !== this.#epoch) return;
        this.#tokens.set(key, token);
      }
      const photo = await this.#client.execute(token);
      if (this.#client.epoch !== this.#epoch) return;
      const matches = photo.section_id === context.sectionId && photo.purpose === context.phase && photo.owner_id === this.#client.session?.principal.user_id && (context.phase === 'before' ? photo.order_id === null && photo.assignment_revision === null : photo.order_id === context.orderId && photo.assignment_revision === context.assignmentRevision);
      if (!matches) throw new ApiError('Подтверждение загрузки относится к другому контексту. Фото не прикреплено.', 200, null, true);
      this.#unresolved.delete(key);
      if (Date.parse(photo.expires_at) <= Date.now()) throw new ApiError('Срок хранения фото истёк. Удалите его из выбора и загрузите заново.');
      this.#job(context, file.id, { status: 'confirmed', error: null, photo });
    } catch (error) {
      if (this.#client.epoch !== this.#epoch || error instanceof SessionChangedError) return;
      const unknown = mutationFailureState(error, this.#unresolved.has(key)) === 'unknown_result';
      if (unknown) this.#unresolved.add(key);
      this.#job(context, file.id, { status: unknown ? 'unknown' : 'failed', error: unknown ? 'Результат исходной загрузки всё ещё не подтверждён. Повторите ту же операцию.' : safeErrorMessage(error), photo: null });
    }
  }
}
