import { useState } from 'react';
import { ru } from '../shared/i18n/ru';

export function App() {
  const [section, setSection] = useState('Наряды');
  return <div className="app-shell">
    <a className="skip-link" href="#main">Перейти к содержимому</a>
    <header className="app-header"><div><span className="eyebrow">DalaAI · рабочая смена</span><h1>{ru.product}</h1></div><span className="environment-tag">Прототип</span></header>
    <nav className="main-nav" aria-label="Основная навигация">
      {['Наряды', 'Исполнение', 'Проверка'].map(label => <button key={label} type="button" aria-current={section === label ? 'page' : undefined} onClick={() => setSection(label)}>{label}</button>)}
    </nav>
    <main id="main" tabIndex={-1}>
      <div className="section-heading"><p className="eyebrow">Единый порядок работы</p><h2>{section}</h2><p>Выдача → исполнение → результат → решение мастера</p></div>
      <section className="card" aria-labelledby="connection-title"><span className="status-label">Подключение ещё не подтверждено</span><h3 id="connection-title">Нужен рабочий API и вход</h3><p>Данные нарядов пока не загружены. Эта оболочка не показывает вымышленные результаты.</p><button type="button" disabled>Операции пока недоступны</button><p className="hint">Роль и доступные действия будут определены серверной сессией.</p></section>
      <aside className="notice"><strong>Черновики</strong><p>{ru.memoryDraft}</p></aside>
    </main>
    <footer>Время в интерфейсе: UTC+5 · Решение о выполнении принимает мастер</footer>
  </div>;
}
