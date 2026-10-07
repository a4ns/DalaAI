import { useEffect, useRef, useState, useSyncExternalStore } from 'react';
import type { FormEvent, ReactNode } from 'react';
import { ApiClient, ApiError, safeErrorMessage, SessionChangedError } from '../shared/api/client';
import { OrderStore } from '../shared/api/orderStore';
import { ru } from '../shared/i18n/ru';
import type { Session } from '../shared/api/wire';
import { Workspace } from './Workspace';
import { PushPreferences } from './PushPreferences';

const defaultClient = new ApiClient();
const defaultOrders = new OrderStore(defaultClient);
const roleLabels = { master: 'Мастер', executor: 'Исполнитель', manager: 'Руководитель', admin: 'Администратор' };
export interface AppSlots {
  renderWorkspace?: (context: { client: ApiClient; orders: OrderStore; session: Session; sessionKey: string; section: string }) => ReactNode;
}
export function App({ client = defaultClient, orders = defaultOrders, renderWorkspace }: AppSlots & { client?: ApiClient; orders?: OrderStore }) {
  const session = useSyncExternalStore(listener => client.subscribe(listener), () => client.session);
  const [section, setSection] = useState('Наряды');
  const [checking, setChecking] = useState(true);
  const [busy, setBusy] = useState(false);
  const [authError, setAuthError] = useState<string | null>(null);
  const [employeeCode, setEmployeeCode] = useState('');
  const [pin, setPin] = useState('');
  const authPending = useRef(false);
  const sessionKey = `${client.epoch}:${session?.principal.user_id ?? 'anonymous'}`;
  const tabs = !session ? ['Наряды', 'Исполнение', 'Проверка'] : session.principal.role === 'master' ? ['Наряды', 'Обзор смены', 'Аналитика и отчёты'] : session.principal.role === 'executor' ? ['Мои наряды'] : session.principal.role === 'manager' ? ['Обзор смены'] : ['Доступ'];
  const activeSection = tabs.includes(section) ? section : tabs[0];
  useEffect(() => {
    let active = true;
    client.getMe().catch(error => {
      if (active && !(error instanceof SessionChangedError) && !(error instanceof ApiError && error.status === 401)) setAuthError(safeErrorMessage(error));
    }).finally(() => { if (active) setChecking(false); });
    return () => { active = false; };
  }, [client]);
  useEffect(() => {
    if (!session || !session.principal.active || session.principal.role === 'admin') return;
    void orders.refresh();
    const timer = setInterval(() => { if (document.visibilityState === 'visible') void orders.refresh(); }, 2000);
    const refresh = () => { if (document.visibilityState === 'visible') void client.getMe().then(() => orders.refresh()).catch(error => { if (!(error instanceof SessionChangedError)) setAuthError(safeErrorMessage(error)); }); };
    window.addEventListener('online', refresh); document.addEventListener('visibilitychange', refresh);
    return () => { clearInterval(timer); window.removeEventListener('online', refresh); document.removeEventListener('visibilitychange', refresh); };
  }, [sessionKey, orders, session, client]);
  async function login(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (authPending.current) return;
    authPending.current = true; setBusy(true); setAuthError(null);
    const credentials = { employee_code: employeeCode.trim(), pin };
    setPin('');
    try { await client.login(credentials); }
    catch (error) { if (!(error instanceof SessionChangedError)) setAuthError(safeErrorMessage(error)); }
    finally { authPending.current = false; setBusy(false); setChecking(false); }
  }
  async function logout() {
    if (authPending.current || !window.confirm('Выйти? Несохранённые черновики будут потеряны. Операции с неподтверждённым результатом нужно проверить после нового входа.')) return;
    authPending.current = true; setBusy(true); setAuthError(null);
    try { await client.logout(); }
    catch (error) { if (!(error instanceof SessionChangedError)) setAuthError('Данные на странице очищены. Серверный выход не подтверждён: проверьте соединение перед передачей устройства.'); }
    finally { authPending.current = false; setBusy(false); setEmployeeCode(''); setPin(''); }
  }
  return <div className="app-shell">
    <a className="skip-link" href="#main">Перейти к содержимому</a>
    <header className="app-header"><div><span className="eyebrow">DalaAI · рабочая смена</span><h1>{ru.product}</h1></div><span className="environment-tag">Прототип</span></header>
    {session && <div className="session-bar"><span>{roleLabels[session.principal.role]} · {session.principal.employee_code}</span><button className="secondary" type="button" onClick={() => void logout()} disabled={busy}>Выйти</button></div>}
    <nav className="main-nav" aria-label="Основная навигация">
      {tabs.map(label => <button key={label} type="button" aria-current={activeSection === label ? 'page' : undefined} onClick={() => setSection(label)}>{label}</button>)}
    </nav>
    <main id="main" tabIndex={-1}>
      <div className="section-heading"><p className="eyebrow">Единый порядок работы</p><h2>{activeSection}</h2><p>Выдача → исполнение → результат → решение мастера</p></div>
      {authError && <p className="error" role="alert">{authError}</p>}
      {checking && !session ? <section className="card" role="status"><h3>Проверяем сессию…</h3><p>Данные нарядов пока не загружены.</p></section> : !session ?
        <section className="card" aria-labelledby="login-title"><span className="status-label">Вход в рабочую смену</span><h3 id="login-title">Войдите в систему</h3><p>Используйте выданную тестовую учётную запись. Роль и доступ определяет сервер.</p><form className="form-stack" onSubmit={event => void login(event)}><label htmlFor="employee-code">Табельный код<input id="employee-code" autoComplete="username" value={employeeCode} maxLength={40} required onChange={event => setEmployeeCode(event.target.value)} disabled={busy}/></label><label htmlFor="pin">PIN<input id="pin" type="password" inputMode="numeric" autoComplete="current-password" value={pin} minLength={4} maxLength={64} required onChange={event => setPin(event.target.value)} disabled={busy}/></label><button type="submit" disabled={busy}>{busy ? 'Входим…' : 'Войти'}</button></form><p className="hint">Вход требует работающего API на том же адресе. Тестовые пароли здесь не публикуются.</p></section> :
        <div key={sessionKey}>
          {renderWorkspace ? renderWorkspace({ client, orders, session, sessionKey, section: activeSection }) : <Workspace isAuthReady={() => !authPending.current} authBusy={busy} client={client} orders={orders} session={session} sessionKey={sessionKey} section={activeSection}/>}
        {session.principal.active && <PushPreferences client={client} isAuthReady={() => !authPending.current} disabled={busy}/>}
        </div>}
      <aside className="notice"><strong>Черновики</strong><p>{ru.memoryDraft}</p></aside>
    </main>
    <footer>Время в интерфейсе: UTC+5 · Решение о выполнении принимает мастер</footer>
  </div>;
}
