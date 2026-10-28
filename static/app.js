'use strict';
/* agently-web — front-end application */

/* ══════════════════ state ══════════════════ */
const state = {
  session: null,          // { loggedIn, accountId, email, aliasId, accounts[] }
  aliases: [],            // [{ aliasId, email, displayName }]
  activeAlias: null,
  folder: 'inbox',        // inbox | unread | sent | trash | starred
  messages: [],
  cursor: null,           // next_cursor
  hasMore: false,
  loading: false,
  selected: null,         // current message
  searchQuery: '',
  searchScope: '',
  stars: new Set(),       // message_id set
  contacts: [],           // [{name, email}]
  signature: { plain: '', html: '' },
  compose: {
    mode: 'new',          // new | reply | forward
    messageId: null,
    draftId: null,        // server-side draft id for autosave
    attachments: [],      // [{ name, size, contentfile_id }]
    quoted: '',
    dirty: false,
  },
  confirmResolve: null,
  pollTimer: null,
  draftTimer: null,
};

const $ = (id) => document.getElementById(id);
const el = (tag, cls, text) => {
  const n = document.createElement(tag);
  if (cls) n.className = cls;
  if (text !== undefined) n.textContent = text;
  return n;
};

/* ══════════════════ api ══════════════════ */
async function api(path, opts = {}) {
  const headers = {};
  let body;
  if (opts.rawBody !== undefined) {
    body = opts.rawBody;
    if (opts.contentType) headers['Content-Type'] = opts.contentType;
  } else if (opts.body !== undefined) {
    body = JSON.stringify(opts.body);
    headers['Content-Type'] = 'application/json';
  }
  const res = await fetch('/api/' + path.replace(/^\//, ''), {
    method: opts.method || 'GET',
    headers,
    body,
  });
  let data = null;
  try { data = await res.json(); } catch (_e) { /* ignore */ }
  if (!res.ok || !data || data.ok !== true) {
    const msg = (data && data.error && data.error.message) || `HTTP ${res.status}`;
    throw Object.assign(new Error(msg), { status: res.status, code: data && data.error && data.error.code });
  }
  return data.data;
}

/* ══════════════════ helpers ══════════════════ */
function escapeHtml(s) {
  return String(s == null ? '' : s)
    .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
}

function toast(msg, isErr) {
  const t = $('toast');
  t.textContent = msg;
  t.className = 'toast' + (isErr ? ' err' : '') + (t.className.includes('hidden') ? ' hidden' : '');
  t.classList.remove('hidden');
  clearTimeout(toast._t);
  toast._t = setTimeout(() => t.classList.add('hidden'), 3200);
}

function setConn(text, cls) {
  $('conn-text').textContent = text;
  $('conn-status').className = 'conn-status' + (cls ? ' ' + cls : '');
}

function fmtDate(v) {
  if (!v) return '';
  let d;
  if (typeof v === 'number') d = new Date(v > 1e12 ? v : v * 1000);
  else d = new Date(v);
  if (isNaN(d.getTime())) return String(v);
  const now = new Date();
  const sameDay = d.toDateString() === now.toDateString();
  if (sameDay) return d.toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' });
  if (d.getFullYear() === now.getFullYear()) return d.toLocaleDateString('zh-CN', { month: 'numeric', day: 'numeric' });
  return d.toLocaleDateString('zh-CN', { year: 'numeric', month: 'numeric', day: 'numeric' });
}

function fmtSize(n) {
  n = Number(n) || 0;
  if (n < 1024) return n + ' B';
  if (n < 1048576) return (n / 1024).toFixed(1) + ' KB';
  return (n / 1048576).toFixed(1) + ' MB';
}

function initial(name) {
  const s = String(name || '?').trim();
  return s ? s[0].toUpperCase() : '?';
}

function splitList(v) {
  if (!v) return [];
  if (Array.isArray(v)) return v.filter(Boolean);
  return String(v).split(/[,;]/).map((s) => s.trim()).filter(Boolean);
}

/** Normalise a message coming from any of the list/read/search shapes. */
function normMessage(raw) {
  const m = raw || {};
  const src = m.message && typeof m.message === 'object' ? { ...m.message, ...m } : m;
  const pick = (...keys) => {
    for (const k of keys) {
      if (src[k] !== undefined && src[k] !== null && src[k] !== '') return src[k];
    }
    return undefined;
  };

  const id = pick('message_id', 'messageId', 'id', 'msg_id') || '';
  const fromRaw = pick('from', 'sender', 'from_email');
  let fromName = '', fromEmail = '';
  if (typeof fromRaw === 'object' && fromRaw) {
    fromName = fromRaw.name || fromRaw.display_name || '';
    fromEmail = fromRaw.email || fromRaw.address || fromRaw.email_address || '';
  } else if (fromRaw) {
    const s = String(fromRaw);
    const mm = s.match(/^(.*?)\s*<(.+)>$/);
    if (mm) { fromName = mm[1].trim(); fromEmail = mm[2].trim(); }
    else fromEmail = s;
  }

  const toRaw = pick('to', 'to_recipients', 'recipients') || [];
  const toEmails = (Array.isArray(toRaw) ? toRaw : [toRaw])
    .map((r) => (typeof r === 'object' && r ? (r.email || r.address || r.email_address || r.name || '') : String(r)))
    .filter(Boolean);

  let attachments = pick('attachments', 'data_attachments') || [];
  if (!Array.isArray(attachments)) attachments = [];

  const bodyRaw = pick('body', 'text', 'content', 'body_text', 'html', 'body_html');
  const fmt = (pick('body_format', 'format', 'content_type') || '').toString().toUpperCase();

  return {
    id,
    fromName: fromName || fromEmail || '(未知发件人)',
    fromEmail,
    to: toEmails,
    cc: splitList(pick('cc', 'cc_recipients')),
    bcc: splitList(pick('bcc', 'bcc_recipients')),
    subject: pick('subject', 'title') || '(无主题)',
    snippet: pick('snippet', 'preview', 'summary', 'excerpt') || '',
    body: bodyRaw || '',
    bodyFormat: fmt.includes('HTML') ? 'HTML' : (fmt.includes('MARKDOWN') ? 'MARKDOWN' : 'PLAIN'),
    date: pick('created_at', 'date', 'sent_at', 'occurred_at', 'received_at') || '',
    isRead: pick('is_read', 'read', 'seen') === true || pick('is_read') === 'true',
    hasAttachments: pick('has_attachments') === true || attachments.length > 0,
    attachmentCount: Number(pick('attachment_count')) || attachments.length,
    attachments: attachments.map((a) => ({
      id: a.attachment_id || a.attachmentId || a.id || '',
      filename: a.filename || a.name || 'attachment',
      size: Number(a.size) || 0,
      contentType: a.content_type || a.contentType || '',
      contentTypeDescription: a.content_type_description || '',
    })),
    trashed: pick('deleted', 'trashed') === true,
    dir: pick('dir', 'folder', 'mailbox') || '',
    raw: m,
  };
}

function messagesOf(data) {
  if (!data) return [];
  if (Array.isArray(data)) return data;
  if (Array.isArray(data.data)) return data.data;
  if (Array.isArray(data.messages)) return data.messages;
  if (Array.isArray(data.items)) return data.items;
  return [];
}

function paginationOf(data) {
  const p = (data && data.pagination) || {};
  return { nextCursor: p.next_cursor || p.nextCursor || null, hasMore: p.has_more === true || !!p.next_cursor };
}

/* ══════════════════ markdown-lite renderer ══════════════════ */
function renderMarkdown(md) {
  const esc = escapeHtml(md);
  const blocks = esc.split(/\n{2,}/);
  return blocks.map((b) => {
    const t = b.trim();
    if (/^#{1,6}\s/.test(t)) {
      const lvl = t.match(/^#+/)[0].length;
      return `<h${Math.min(lvl + 2, 6)}>${inlineMd(t.replace(/^#+\s*/, ''))}</h${Math.min(lvl + 2, 6)}>`;
    }
    if (/^[-*]\s/.test(t)) {
      const items = t.split('\n').filter((l) => /^[-*]\s/.test(l.trim()))
        .map((l) => `<li>${inlineMd(l.replace(/^[-*]\s*/, ''))}</li>`).join('');
      return `<ul>${items}</ul>`;
    }
    if (/^\d+\.\s/.test(t)) {
      const items = t.split('\n').filter((l) => /^\d+\.\s/.test(l.trim()))
        .map((l) => `<li>${inlineMd(l.replace(/^\d+\.\s*/, ''))}</li>`).join('');
      return `<ol>${items}</ol>`;
    }
    if (/^&gt;\s?/.test(t)) {
      return `<blockquote>${inlineMd(t.replace(/^(&gt;\s?)+/, ''))}</blockquote>`;
    }
    return `<p>${inlineMd(t).replace(/\n/g, '<br>')}</p>`;
  }).join('');
}
function inlineMd(s) {
  return s
    .replace(/`([^`]+)`/g, '<code>$1</code>')
    .replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>')
    .replace(/(^|[^*])\*([^*]+)\*/g, '$1<em>$2</em>')
    .replace(/\[([^\]]+)\]\(([^)]+)\)/g, '<a href="$2" target="_blank" rel="noopener noreferrer">$1</a>');
}

function renderBody(msg) {
  if (!msg.body) return '<p style="color:var(--text-faint)">（无正文）</p>';
  if (msg.bodyFormat === 'HTML') return msg.body;
  if (msg.bodyFormat === 'MARKDOWN') return renderMarkdown(msg.body);
  return `<div class="plain">${escapeHtml(msg.body)}</div>`;
}

/* ══════════════════ boot ══════════════════ */
async function boot() {
  try {
    const s = await api('auth/session');
    state.session = s;
    if (s.loggedIn) {
      await enterApp();
    } else {
      showLogin();
    }
  } catch (e) {
    showLogin();
  }
}

function showLogin() {
  $('login-view').classList.remove('hidden');
  $('app-view').classList.add('hidden');
  $('login-step-start').classList.remove('hidden');
  $('login-step-wait').classList.add('hidden');
  $('login-step-error').classList.add('hidden');
}

async function enterApp() {
  $('login-view').classList.add('hidden');
  $('app-view').classList.remove('hidden');
  renderAccount();
  await Promise.all([loadAliases(), loadStars(), loadContacts(), loadSignature()]);
  await loadMessages();
  startEventWatch();
}

/* ══════════════════ login flow ══════════════════ */
let loginId = null;
let loginPoll = null;

async function beginLogin() {
  $('login-step-start').classList.add('hidden');
  $('login-step-error').classList.add('hidden');
  $('login-step-wait').classList.remove('hidden');
  $('login-status-text').textContent = '正在创建授权会话…';
  try {
    const d = await api('auth/login/start', { method: 'POST' });
    loginId = d.loginId;
    $('login-user-code').textContent = d.userCode || '------';
    const a = $('login-browser-url');
    a.href = d.browserUrl;
    a.textContent = d.browserUrl;
    $('login-status-text').textContent = '等待授权…';
    tickExpiry(d.expiresIn);
    clearInterval(loginPoll);
    loginPoll = setInterval(pollLogin, 2000);
  } catch (e) {
    loginError(e.message);
  }
}

let expiryTimer = null;
function tickExpiry(sec) {
  clearInterval(expiryTimer);
  let left = sec || 600;
  const render = () => {
    $('login-expiry').textContent = `授权码 ${Math.floor(left / 60)}:${String(left % 60).padStart(2, '0')} 后过期`;
    left--;
    if (left < 0) clearInterval(expiryTimer);
  };
  render();
  expiryTimer = setInterval(render, 1000);
}

async function pollLogin() {
  if (!loginId) return;
  try {
    const d = await api('auth/login/' + loginId);
    if (d.status === 'complete') {
      clearInterval(loginPoll);
      clearInterval(expiryTimer);
      $('login-status-text').textContent = '授权成功，正在进入…';
      const s = await api('auth/session');
      state.session = s;
      await enterApp();
    } else if (d.status === 'error') {
      clearInterval(loginPoll);
      clearInterval(expiryTimer);
      loginError(d.error || '授权失败');
    } else if (d.status === 'expired') {
      clearInterval(loginPoll);
      clearInterval(expiryTimer);
      loginError(d.error || '授权已过期');
    }
  } catch (e) {
    /* transient — keep polling */
  }
}

function loginError(msg) {
  $('login-step-wait').classList.add('hidden');
  $('login-step-error').classList.remove('hidden');
  $('login-error-text').textContent = msg;
}

async function cancelLogin() {
  if (loginId) {
    try { await api(`auth/login/${loginId}/cancel`, { method: 'POST' }); } catch (_e) { /* ignore */ }
  }
  clearInterval(loginPoll);
  clearInterval(expiryTimer);
  loginId = null;
  showLogin();
}

/* ══════════════════ account ══════════════════ */
function renderAccount() {
  const s = state.session || {};
  $('account-avatar').textContent = initial(s.email);
  $('dd-email').textContent = s.email || '(未获取邮箱)';
  $('dd-alias').textContent = s.aliasId ? '别名 ID: ' + s.aliasId : '';
  const wrap = $('dd-accounts');
  wrap.innerHTML = '';
  (s.accounts || []).forEach((a) => {
    const b = el('button', 'dropdown-item' + (a.id === s.accountId ? ' active' : ''));
    b.innerHTML = `<span class="alias-dot"></span><span>${escapeHtml(a.email || a.id)}</span>`;
    b.onclick = () => switchAccount(a.id);
    wrap.appendChild(b);
  });
}

async function switchAccount(id) {
  try {
    await api('auth/switch', { method: 'POST', body: { accountId: id } });
    state.session = await api('auth/session');
    closeDropdowns();
    renderAccount();
    await loadAliases();
    await loadMessages();
    toast('已切换账号');
  } catch (e) { toast(e.message, true); }
}

async function loadAliases() {
  try {
    const d = await api('aliases');
    state.aliases = d.aliases || [];
    state.activeAlias = d.defaultAliasId || (state.aliases[0] && state.aliases[0].aliasId) || null;
    renderAliases();
  } catch (e) {
    setConn('别名加载失败', 'err');
    renderAliases();
  }
}

function renderAliases() {
  const wrap = $('alias-list');
  wrap.innerHTML = '';
  if (!state.aliases.length) {
    wrap.appendChild(el('div', 'alias-item', state.activeAlias || '默认'));
    return;
  }
  state.aliases.forEach((a) => {
    const b = el('button', 'alias-item' + (a.aliasId === state.activeAlias ? ' active' : ''));
    b.innerHTML = `<span class="alias-dot"></span><span>${escapeHtml(a.email || a.aliasId)}</span>`;
    b.title = a.email || a.aliasId;
    b.onclick = () => {
      state.activeAlias = a.aliasId;
      renderAliases();
      loadMessages();
    };
    wrap.appendChild(b);
  });
}

/* ══════════════════ messages ══════════════════ */
async function loadMessages(append) {
  if (!state.activeAlias) {
    $('message-list').innerHTML =
      '<div class="empty-state"><div class="empty-icon">📭</div><p>没有可用的邮箱别名</p></div>';
    return;
  }
  if (state.loading) return;
  state.loading = true;
  setConn('加载中…', 'busy');

  try {
    let data;
    if (state.searchQuery) {
      data = await api(`aliases/${state.activeAlias}/messages/search?q=${encodeURIComponent(state.searchQuery)}` +
        (state.searchScope ? `&search-in=${encodeURIComponent(state.searchScope)}` : ''));
      state.messages = messagesOf(data).map(normMessage);
      state.cursor = null;
      state.hasMore = false;
    } else {
      const params = new URLSearchParams();
      params.set('limit', '50');
      if (state.folder === 'unread') params.set('is-read', 'false');
      if (state.folder === 'sent') params.set('folder', 'sent');
      if (state.folder === 'trash') params.set('folder', 'trash');
      if (append && state.cursor) params.set('before', state.cursor);
      data = await api(`aliases/${state.activeAlias}/messages?${params.toString()}`);
      let list = messagesOf(data).map(normMessage);
      if (state.folder === 'starred') list = list.filter((x) => state.stars.has(x.id));
      const pg = paginationOf(data);
      state.messages = append ? state.messages.concat(list) : list;
      state.cursor = pg.nextCursor;
      state.hasMore = pg.hasMore;
    }
    renderList();
    setConn('就绪');
  } catch (e) {
    setConn(e.message, 'err');
    if (!append) {
      $('message-list').innerHTML =
        `<div class="empty-state"><div class="empty-icon">⚠️</div><p>${escapeHtml(e.message)}</p></div>`;
    }
  } finally {
    state.loading = false;
  }
}

function renderList() {
  const wrap = $('message-list');
  wrap.innerHTML = '';

  const titles = { inbox: '收件箱', unread: '未读', sent: '已发送', trash: '回收站', starred: '星标邮件' };
  $('list-title').textContent = state.searchQuery ? `搜索: ${state.searchQuery}` : titles[state.folder];
  $('list-count').textContent = state.messages.length ? `${state.messages.length} 封` : '';
  $('btn-empty-trash').classList.toggle('hidden', state.folder !== 'trash');

  if (!state.messages.length) {
    wrap.innerHTML = '<div class="empty-state"><div class="empty-icon">📭</div><p>暂无邮件</p></div>';
    return;
  }

  state.messages.forEach((m) => {
    const isStarred = state.stars.has(m.id);
    const row = el('div', 'msg-row' + (m.isRead ? '' : ' unread') +
      (state.selected && state.selected.id === m.id ? ' active' : ''));
    row.dataset.id = m.id;

    const chips = [];
    if (m.hasAttachments) chips.push(`<span class="chip att">📎 ${m.attachmentCount || ''}</span>`);
    if (m.trashed) chips.push('<span class="chip trashed">回收站</span>');
    if (m.dir) chips.push(`<span class="chip">${escapeHtml(String(m.dir))}</span>`);

    row.innerHTML =
      `<button class="msg-star ${isStarred ? 'on' : ''}" title="${isStarred ? '取消星标' : '标为星标'}">${isStarred ? '★' : '☆'}</button>` +
      `<div class="msg-avatar">${escapeHtml(initial(m.fromName))}</div>` +
      `<div class="msg-main">` +
      `<div class="msg-top"><span class="msg-from">${escapeHtml(m.fromName)}</span>` +
      `<span class="msg-date">${escapeHtml(fmtDate(m.date))}</span></div>` +
      `<div class="msg-subject">${escapeHtml(m.subject)}</div>` +
      (m.snippet ? `<div class="msg-snippet">${escapeHtml(m.snippet)}</div>` : '') +
      (chips.length ? `<div class="msg-flags">${chips.join('')}</div>` : '') +
      `</div>`;

    row.querySelector('.msg-star').onclick = (e) => toggleStar(m.id, e);
    row.onclick = () => openMessage(m);
    wrap.appendChild(row);
  });

  if (state.hasMore && state.cursor) {
    const more = el('div', 'list-loading', '加载更多…');
    more.style.cursor = 'pointer';
    more.onclick = () => loadMessages(true);
    wrap.appendChild(more);
  }

  updateUnreadBadge();
}

function updateUnreadBadge() {
  const n = state.messages.filter((m) => !m.isRead).length;
  $('badge-inbox').textContent = n || '';
}

/* ══════════════════ read ══════════════════ */
async function openMessage(m) {
  state.selected = m;
  renderList();
  const pane = $('read-pane');
  pane.classList.remove('hidden');
  pane.innerHTML = '<div class="list-loading"><span class="spinner"></span> 加载中…</div>';

  let full = m;
  try {
    const data = await api(`aliases/${state.activeAlias}/messages/${encodeURIComponent(m.id)}`);
    const list = messagesOf(data);
    const raw = list.length ? list[0] : (data.message || data);
    full = normMessage({ ...m.raw, ...raw, body: raw.body || m.body });
    state.selected = full;
  } catch (e) {
    toast('读取详情失败: ' + e.message, true);
  }
  renderRead(full);
}

function renderRead(m) {
  const pane = $('read-pane');
  const atts = (m.attachments || []).map((a) =>
    `<div class="att-item" data-att="${escapeHtml(a.id)}">` +
    `<span class="att-icon">📄</span>` +
    `<span><div class="att-name">${escapeHtml(a.filename)}</div>` +
    `<div class="att-size">${escapeHtml(fmtSize(a.size))}${a.contentType ? ' · ' + escapeHtml(a.contentType) : ''}</div></span>` +
    `</div>`).join('');
  const isStarred = state.stars.has(m.id);

  pane.innerHTML =
    `<div class="read-content">` +
    `<div class="read-head">` +
    `<h1 class="read-subject">${escapeHtml(m.subject)}</h1>` +
    `<div class="read-meta">` +
    `<div class="msg-avatar">${escapeHtml(initial(m.fromName))}</div>` +
    `<div class="read-meta-main">` +
    `<div class="read-from">${escapeHtml(m.fromName)}` +
    (m.fromEmail ? ` <span class="read-from-email">&lt;${escapeHtml(m.fromEmail)}&gt;</span>` : '') + `</div>` +
    (m.to.length ? `<div class="read-to">收件人: ${escapeHtml(m.to.join(', '))}</div>` : '') +
    (m.cc.length ? `<div class="read-to">抄送: ${escapeHtml(m.cc.join(', '))}</div>` : '') +
    `</div>` +
    `<div class="read-date">${escapeHtml(fmtDate(m.date))}</div>` +
    `</div>` +
    `</div>` +
    `<div class="read-actions">` +
    `<button class="btn btn-ghost" id="ra-star" title="${isStarred ? '取消星标' : '标为星标'}">${isStarred ? '★ 已加星标' : '☆ 加星标'}</button>` +
    `<button class="btn btn-ghost" id="ra-reply">↩ 回复</button>` +
    `<button class="btn btn-ghost" id="ra-reply-all">↩↩ 回复全部</button>` +
    `<button class="btn btn-ghost" id="ra-forward">⇉ 转发</button>` +
    (m.trashed
      ? `<button class="btn btn-ghost" id="ra-restore">♻ 移出回收站</button>`
      : `<button class="btn btn-ghost" id="ra-trash">🗑 删除</button>`) +
    `<button class="btn btn-ghost" id="ra-delete" style="color:var(--danger)">✕ 彻底删除</button>` +
    `</div>` +
    `<div class="read-card"><div class="read-body ${m.bodyFormat === 'HTML' ? 'html' : m.bodyFormat === 'MARKDOWN' ? 'md' : 'plain'}">${renderBody(m)}</div></div>` +
    (atts ? `<div class="read-attachments"><div class="read-attachments-title">附件 (${m.attachments.length})</div><div class="att-grid">${atts}</div></div>` : '') +
    `<details class="read-raw"><summary>查看原始数据</summary><pre>${escapeHtml(JSON.stringify(m.raw, null, 2))}</pre></details>` +
    `</div>`;

  $('ra-reply').onclick = () => openCompose('reply', m, false);
  $('ra-star').onclick = () => toggleStar(m.id);
  $('ra-reply-all').onclick = () => openCompose('reply', m, true);
  $('ra-forward').onclick = () => openCompose('forward', m);
  const tr = $('ra-trash');
  if (tr) tr.onclick = () => trashMessage(m);
  const rs = $('ra-restore');
  if (rs) rs.onclick = () => restoreMessage(m);
  $('ra-delete').onclick = () => deleteMessage(m);

  pane.querySelectorAll('.att-item').forEach((n) => {
    n.onclick = () => downloadAttachment(m, n.dataset.att);
  });
}

/* ══════════════════ actions ══════════════════ */
async function trashMessage(m) {
  if (!(await confirmDialog(`将「${m.subject}」移到回收站？`))) return;
  try {
    await api(`aliases/${state.activeAlias}/messages/${encodeURIComponent(m.id)}`, { method: 'DELETE' });
    toast('已移到回收站');
    state.messages = state.messages.filter((x) => x.id !== m.id);
    state.selected = null;
    renderList();
    $('read-pane').innerHTML = '<div class="read-placeholder"><div class="empty-icon">📬</div><p>选择一封邮件开始阅读</p></div>';
  } catch (e) { toast(e.message, true); }
}

async function restoreMessage(m) {
  try {
    // Move out of trash = re-send is not viable; the API has no un-trash.
    // Best effort: mark as read so it surfaces in the inbox view.
    toast('该 API 未提供「移出回收站」，请重新发送或联系管理员', true);
  } catch (e) { toast(e.message, true); }
}

async function deleteMessage(m) {
  if (!(await confirmDialog(`永久删除「${m.subject}」？此操作不可恢复，并会释放邮箱存储空间。`))) return;
  try {
    await api(`aliases/${state.activeAlias}/messages/${encodeURIComponent(m.id)}/permanent`, { method: 'POST', body: {} });
    toast('已永久删除');
    state.messages = state.messages.filter((x) => x.id !== m.id);
    state.selected = null;
    renderList();
    $('read-pane').innerHTML = '<div class="read-placeholder"><div class="empty-icon">📬</div><p>选择一封邮件开始阅读</p></div>';
  } catch (e) { toast(e.message, true); }
}

async function downloadAttachment(m, attId) {
  const a = (m.attachments || []).find((x) => x.id === attId);
  toast(`正在获取 ${a ? a.filename : '附件'}…`);
  try {
    const d = await api(`aliases/${state.activeAlias}/messages/${encodeURIComponent(m.id)}/attachments/${encodeURIComponent(attId)}`);
    // The API returns either a URL or base64 content.
    let href = null, name = a ? a.filename : 'attachment';
    if (typeof d === 'string') {
      if (/^https?:\/\//.test(d)) href = d;
      else {
        const blob = new Blob([Uint8Array.from(atob(d), (c) => c.charCodeAt(0))]);
        href = URL.createObjectURL(blob);
      }
    } else if (d && typeof d === 'object') {
      const url = d.url || d.download_url || d.href;
      const b64 = d.content || d.data || d.base64;
      if (url) href = url;
      else if (b64) {
        const blob = new Blob([Uint8Array.from(atob(b64), (c) => c.charCodeAt(0))], { type: a ? a.contentType : '' });
        href = URL.createObjectURL(blob);
      }
    }
    if (!href) { toast('附件数据格式未知，请查看控制台', true); console.log('attachment payload', d); return; }
    const link = document.createElement('a');
    link.href = href;
    link.download = name;
    link.target = '_blank';
    document.body.appendChild(link);
    link.click();
    link.remove();
    toast('已开始下载');
  } catch (e) { toast(e.message, true); }
}

/* ══════════════════ compose ══════════════════ */
function openCompose(mode, msg, replyAll) {
  state.compose = { mode, messageId: msg ? msg.id : null, draftId: null,
                    attachments: [], quoted: '', dirty: false };
  $('compose-modal').classList.remove('hidden');
  $('compose-title').textContent = mode === 'reply' ? (replyAll ? '回复全部' : '回复') : mode === 'forward' ? '转发' : '新邮件';

  $('compose-to').value = '';
  $('compose-cc').value = '';
  $('compose-bcc').value = '';
  $('compose-subject').value = '';
  $('compose-body').value = '';
  $('compose-attachments').innerHTML = '';
  $('compose-quoted').classList.add('hidden');
  $('compose-status').textContent = '';
  $('compose-files').value = '';

  // Recipients datalist from contacts
  const dl = $('contacts-datalist');
  dl.innerHTML = (state.contacts || []).map((c) =>
    `<option value="${escapeHtml(c.email)}">${escapeHtml(c.name || c.email)}</option>`
  ).join('');

  // Signature insertion for plain format
  if (state.signature && state.signature.plain) {
    $('compose-body').value = '\n\n' + state.signature.plain;
  }

  if (mode === 'reply') {
    $('compose-to').value = msg.fromEmail || msg.fromName;
    if (replyAll) {
      const others = (msg.to || []).filter((e) => e && e !== (state.session || {}).email);
      const cc = (msg.cc || []).concat(others);
      if (cc.length) $('compose-cc').value = cc.join(', ');
    }
    $('compose-subject').value = /^(re|回复|RE)\s*[:：]/i.test(msg.subject) ? msg.subject : 'Re: ' + msg.subject;
    const quote = `\n\n---- 原始邮件 ----\n发件人: ${msg.fromName} <${msg.fromEmail}>\n日期: ${fmtDate(msg.date)}\n主题: ${msg.subject}\n\n${msg.snippet || ''}`;
    state.compose.quoted = quote;
    const q = $('compose-quoted');
    q.textContent = quote;
    q.classList.remove('hidden');
  } else if (mode === 'forward') {
    $('compose-subject').value = /^(fw|fwd|转发)\s*[:：]/i.test(msg.subject) ? msg.subject : 'Fw: ' + msg.subject;
    const quote = `\n\n---- 转发邮件 ----\n发件人: ${msg.fromName} <${msg.fromEmail}>\n日期: ${fmtDate(msg.date)}\n主题: ${msg.subject}\n\n${msg.body || msg.snippet || ''}`;
    state.compose.quoted = quote;
    const q = $('compose-quoted');
    q.textContent = quote;
    q.classList.remove('hidden');
  }

  // wire field listeners for autosave (once)
  if (!openCompose._wired) {
    ['compose-to', 'compose-cc', 'compose-bcc', 'compose-subject', 'compose-body', 'compose-format'].forEach((id) => {
      const n = $(id);
      n.addEventListener('input', markComposeDirty);
      n.addEventListener('change', markComposeDirty);
    });
    $('compose-to').addEventListener('blur', () => {
      if ($('compose-to').value && state.contacts.every((c) => c.email !== $('compose-to').value.split(',').pop().trim())) {
        addContactFromTo();
      }
    });
    openCompose._wired = true;
  }

  setTimeout(() => $('compose-body').focus(), 50);
}

function closeCompose() {
  clearTimeout(state.draftTimer);
  state.compose.dirty = false;
  $('compose-modal').classList.add('hidden');
}

function renderComposeAttachments() {
  const wrap = $('compose-attachments');
  wrap.innerHTML = '';
  state.compose.attachments.forEach((a, i) => {
    const n = el('div', 'compose-att');
    n.innerHTML = `📎 <span>${escapeHtml(a.name)}</span> <span style="color:var(--text-faint)">${escapeHtml(fmtSize(a.size))}</span>`;
    const x = el('button', '', '✕');
    x.onclick = () => {
      state.compose.attachments.splice(i, 1);
      renderComposeAttachments();
    };
    n.appendChild(x);
    wrap.appendChild(n);
  });
}

async function handleFiles(fileList) {
  for (const f of Array.from(fileList || [])) {
    $('compose-status').textContent = `正在上传 ${f.name}…`;
    try {
      const buf = await f.arrayBuffer();
      const d = await api(
        `aliases/${state.activeAlias}/files/upload?filename=${encodeURIComponent(f.name)}&content-type=${encodeURIComponent(f.type || 'application/octet-stream')}`,
        { method: 'POST', rawBody: buf, contentType: f.type || 'application/octet-stream' }
      );
      const cfid = (d && (d.contentfile_id || d.file_id || d.id)) || '';
      state.compose.attachments.push({ name: f.name, size: f.size, contentfile_id: cfid, type: f.type });
      renderComposeAttachments();
      $('compose-status').textContent = '';
    } catch (e) {
      toast('上传失败: ' + e.message, true);
      $('compose-status').textContent = '';
    }
  }
}

/** Two-step confirmation aware send. */
async function doSend() {
  const to = splitList($('compose-to').value);
  if (!to.length) { toast('请填写收件人', true); return; }

  const body = $('compose-body').value;
  const format = $('compose-format').value;
  const payload = {
    to_recipients: to.map((e) => ({ email: e })),
    cc_recipients: splitList($('compose-cc').value).map((e) => ({ email: e })),
    bcc_recipients: splitList($('compose-bcc').value).map((e) => ({ email: e })),
    subject: $('compose-subject').value || '(无主题)',
    body: body,
    body_format: format,
  };
  const cfs = state.compose.attachments.map((a) => a.contentfile_id).filter(Boolean);
  if (cfs.length) payload.contentfile_id = cfs;

  $('btn-send').disabled = true;
  $('compose-status').textContent = '发送中…';

  const path = state.compose.mode === 'reply'
    ? `aliases/${state.activeAlias}/messages/${encodeURIComponent(state.compose.messageId)}/reply`
    : state.compose.mode === 'forward'
      ? `aliases/${state.activeAlias}/messages/${encodeURIComponent(state.compose.messageId)}/forward`
      : `aliases/${state.activeAlias}/messages/send`;

  try {
    let d = await api(path, { method: 'POST', body: payload });

    // Step 1 of two-step confirmation?
    if (d && d.confirmation_required && d.confirmation_token) {
      $('compose-status').textContent = '等待确认…';
      const ok = await confirmDialog(
        '服务器要求二次确认后才会真正发送。\n\n' +
        `收件人: ${to.join(', ')}\n主题: ${payload.subject}\n\n确认发送？`
      );
      if (!ok) {
        $('compose-status').textContent = '已取消';
        return;
      }
      d = await api(path, { method: 'POST', body: { ...payload, confirmation_token: d.confirmation_token } });
    }

    $('compose-status').textContent = '已发送 ✓';
    toast('发送成功');
    if (state.compose.draftId) {
      try { await api(`drafts/${state.compose.draftId}`, { method: 'DELETE' }); } catch (_e) { /* ignore */ }
    }
    state.compose.dirty = false;
    setTimeout(() => { closeCompose(); loadMessages(); }, 700);
  } catch (e) {
    $('compose-status').textContent = '';
    toast('发送失败: ' + e.message, true);
  } finally {
    $('btn-send').disabled = false;
  }
}

/* ══════════════════ confirm dialog ══════════════════ */
function confirmDialog(text) {
  return new Promise((resolve) => {
    $('confirm-text').textContent = text;
    $('confirm-modal').classList.remove('hidden');
    state.confirmResolve = resolve;
  });
}
function resolveConfirm(v) {
  $('confirm-modal').classList.add('hidden');
  if (state.confirmResolve) state.confirmResolve(v);
  state.confirmResolve = null;
}

/* ══════════════════ events (watch) ══════════════════ */
function startEventWatch() {
  stopEventWatch();
  const tick = async () => {
    if (!state.activeAlias) return;
    try {
      await api(`aliases/${state.activeAlias}/events/wait`);
      await loadMessages();
    } catch (_e) { /* ignore */ }
    state.pollTimer = setTimeout(tick, 5000);
  };
  state.pollTimer = setTimeout(tick, 8000);
}
function stopEventWatch() {
  if (state.pollTimer) clearTimeout(state.pollTimer);
  state.pollTimer = null;
}

/* ══════════════════ account management ══════════════════ */
function openAccountsModal() {
  const wrap = $('accounts-list');
  wrap.innerHTML = '';
  const accounts = (state.session && state.session.accounts) || [];
  if (!accounts.length) wrap.appendChild(el('div', 'account-row-sub', '暂无账号'));
  accounts.forEach((a) => {
    const row = el('div', 'account-row' + (a.id === state.session.accountId ? ' current' : ''));
    row.innerHTML =
      `<span class="avatar">${escapeHtml(initial(a.email))}</span>` +
      `<div class="account-row-main"><div class="account-row-email">${escapeHtml(a.email || a.id)}</div>` +
      `<div class="account-row-sub">${a.id === state.session.accountId ? '当前账号 · ' : ''}${escapeHtml(a.aliasId || '')}</div></div>`;
    if (a.id !== state.session.accountId) {
      const sw = el('button', 'text-btn', '切换');
      sw.onclick = () => { closeAccountsModal(); switchAccount(a.id); };
      row.appendChild(sw);
    }
    const del = el('button', 'text-btn', '移除');
    del.style.color = 'var(--danger)';
    del.onclick = async () => {
      if (!(await confirmDialog(`移除账号 ${a.email || a.id}？本地凭证将被删除。`))) return;
      try {
        await api('accounts/' + a.id, { method: 'DELETE' });
        state.session = await api('auth/session');
        renderAccount();
        openAccountsModal();
        if (!state.session.loggedIn) { closeAccountsModal(); showLogin(); }
        toast('已移除');
      } catch (e) { toast(e.message, true); }
    };
    row.appendChild(del);
    wrap.appendChild(row);
  });
  $('accounts-modal').classList.remove('hidden');
}
function closeAccountsModal() { $('accounts-modal').classList.add('hidden'); }

function closeDropdowns() {
  $('account-dropdown').classList.add('hidden');
}

/* ══════════════════ stars ══════════════════ */
async function loadStars() {
  try {
    const ids = await api('stars');
    state.stars = new Set(ids || []);
  } catch (_e) { /* ignore */ }
}
async function toggleStar(mid, ev) {
  if (ev) { ev.stopPropagation(); }
  const isStarred = state.stars.has(mid);
  try {
    if (isStarred) {
      await api(`stars/${encodeURIComponent(mid)}`, { method: 'DELETE' });
      state.stars.delete(mid);
    } else {
      await api(`stars/${encodeURIComponent(mid)}`, { method: 'POST' });
      state.stars.add(mid);
    }
    if (state.selected && state.selected.id === mid) state.selected.starred = !isStarred;
    const msg = state.messages.find((x) => x.id === mid);
    if (msg) msg.starred = !isStarred;
    renderList();
    if (state.selected && state.selected.id === mid) renderRead(state.selected);
    if (state.folder === 'starred' && isStarred) {
      // it just got unstarred — drop from view
      state.messages = state.messages.filter((x) => x.id !== mid);
      renderList();
    }
  } catch (e) { toast(e.message, true); }
}

/* ══════════════════ contacts ══════════════════ */
async function loadContacts() {
  try {
    state.contacts = await api('contacts') || [];
  } catch (_e) { /* ignore */ }
}
async function addContactFromTo() {
  const to = splitList($('compose-to').value);
  const last = to[to.length - 1];
  if (!last || !/.+@.+\..+/.test(last)) return;
  const name = to.length > 1 ? to.slice(0, -1).join(', ') : '';
  try {
    await api('contacts', { method: 'POST', body: { email: last, name } });
    await loadContacts();
    toast(`已保存 ${last} 到地址簿`);
  } catch (_e) { /* ignore */ }
}
async function removeContact(email) {
  try {
    await api(`contacts/${encodeURIComponent(email)}`, { method: 'DELETE' });
    state.contacts = state.contacts.filter((c) => c.email !== email);
    openContactsModal();
    toast('已删除');
  } catch (e) { toast(e.message, true); }
}

/* ══════════════════ signature ══════════════════ */
async function loadSignature() {
  try {
    state.signature = await api('signature') || { plain: '', html: '' };
  } catch (_e) { /* ignore */ }
}
async function saveSignature() {
  state.signature.plain = $('sig-plain').value;
  state.signature.html = $('sig-html').value;
  try {
    await api('signature', { method: 'POST', body: state.signature });
    toast('签名已保存');
  } catch (e) { toast(e.message, true); }
}
function openSettingsModal() {
  $('settings-modal').classList.remove('hidden');
  $('sig-plain').value = state.signature.plain || '';
  $('sig-html').value = state.signature.html || '';
}
function closeSettingsModal() { $('settings-modal').classList.add('hidden'); }
function openContactsModal() {
  const wrap = $('contacts-list');
  wrap.innerHTML = '';
  if (!state.contacts.length) wrap.appendChild(el('div', 'account-row-sub', '暂无地址簿联系人'));
  state.contacts.forEach((c) => {
    const row = el('div', 'account-row');
    row.innerHTML =
      `<span class="avatar">${escapeHtml(initial(c.name || c.email))}</span>` +
      `<div class="account-row-main"><div class="account-row-email">${escapeHtml(c.email)}</div>` +
      `<div class="account-row-sub">${escapeHtml(c.name || '')}</div></div>`;
    const del = el('button', 'text-btn', '删除');
    del.style.color = 'var(--danger)';
    del.onclick = () => removeContact(c.email);
    row.appendChild(del);
    wrap.appendChild(row);
  });
  $('contacts-modal').classList.remove('hidden');
}
function closeContactsModal() { $('contacts-modal').classList.add('hidden'); }

/* ══════════════════ drafts (autosave) ══════════════════ */
function snapshotDraft() {
  return {
    draftId: state.compose.draftId || undefined,
    mode: state.compose.mode,
    messageId: state.compose.messageId || undefined,
    to: $('compose-to').value,
    cc: $('compose-cc').value,
    bcc: $('compose-bcc').value,
    subject: $('compose-subject').value,
    body: $('compose-body').value,
    bodyFormat: $('compose-format').value,
    quoted: state.compose.quoted,
    attachmentCount: state.compose.attachments.length,
  };
}
function autosaveDraft() {
  if (!state.compose.dirty) return;
  clearTimeout(state.draftTimer);
  state.draftTimer = setTimeout(async () => {
    if (!$('compose-modal') || $('compose-modal').classList.contains('hidden')) return;
    try {
      const saved = await api('drafts', { method: 'POST', body: snapshotDraft() });
      if (saved && saved.draftId) state.compose.draftId = saved.draftId;
      $('compose-status').textContent = '已自动保存草稿';
      setTimeout(() => {
        if ($('compose-status').textContent === '已自动保存草稿') $('compose-status').textContent = '';
      }, 1500);
    } catch (_e) { /* ignore */ }
  }, 1200);
}
function markComposeDirty() {
  state.compose.dirty = true;
  autosaveDraft();
}

/* ══════════════════ wiring ══════════════════ */
function wire() {
  // login
  $('btn-login-start').onclick = beginLogin;
  $('btn-login-retry').onclick = beginLogin;
  $('btn-login-cancel').onclick = cancelLogin;

  // topbar
  $('btn-account').onclick = (e) => { e.stopPropagation(); $('account-dropdown').classList.toggle('hidden'); };
  document.addEventListener('click', (e) => {
    if (!e.target.closest('.account-menu')) closeDropdowns();
  });
  $('btn-logout').onclick = async () => {
    if (!(await confirmDialog('退出当前账号？本地保存的 OAuth 凭证将被撤销并删除。'))) return;
    stopEventWatch();
    await api('auth/logout', { method: 'POST' });
    closeDropdowns();
    showLogin();
    toast('已退出');
  };
  $('btn-add-account').onclick = () => { closeDropdowns(); beginLogin(); };
  $('btn-manage-accounts').onclick = () => { closeDropdowns(); openAccountsModal(); };
  $('btn-settings').onclick = () => { closeDropdowns(); openSettingsModal(); };
  $('btn-contacts').onclick = () => { closeDropdowns(); openContactsModal(); };
  $('btn-settings-close').onclick = closeSettingsModal;
  $('settings-modal').addEventListener('click', (e) => { if (e.target === $('settings-modal')) closeSettingsModal(); });
  $('btn-sig-save').onclick = saveSignature;
  $('btn-contacts-close').onclick = closeContactsModal;
  $('contacts-modal').addEventListener('click', (e) => { if (e.target === $('contacts-modal')) closeContactsModal(); });
  $('btn-refresh').onclick = () => {
    state.searchQuery = '';
    $('search-input').value = '';
    loadMessages();
  };

  // search
  let searchDebounce = null;
  $('search-input').addEventListener('input', (e) => {
    clearTimeout(searchDebounce);
    searchDebounce = setTimeout(() => {
      state.searchQuery = e.target.value.trim();
      loadMessages();
    }, 450);
  });
  $('search-input').addEventListener('keydown', (e) => {
    if (e.key === 'Escape') { e.target.value = ''; state.searchQuery = ''; loadMessages(); }
  });
  $('search-scope').onchange = (e) => {
    state.searchScope = e.target.value;
    if (state.searchQuery) loadMessages();
  };

  // folders
  document.querySelectorAll('#folder-nav .nav-item').forEach((b) => {
    b.onclick = () => {
      document.querySelectorAll('#folder-nav .nav-item').forEach((x) => x.classList.remove('active'));
      b.classList.add('active');
      state.folder = b.dataset.folder;
      state.searchQuery = '';
      $('search-input').value = '';
      state.selected = null;
      $('read-pane').innerHTML = '<div class="read-placeholder"><div class="empty-icon">📬</div><p>选择一封邮件开始阅读</p></div>';
      loadMessages();
    };
  });
  $('btn-empty-trash').onclick = async () => {
    if (!(await confirmDialog('清空回收站？所有邮件将被永久删除并释放存储空间。'))) return;
    try {
      await api(`aliases/${state.activeAlias}/trash/empty`, { method: 'POST', body: {} });
      toast('回收站已清空');
      loadMessages();
    } catch (e) { toast(e.message, true); }
  };

  // sidebar (mobile)
  $('btn-menu').onclick = () => $('sidebar').classList.toggle('open');

  // compose
  $('btn-compose').onclick = () => openCompose('new', null);
  $('btn-compose-close').onclick = closeCompose;
  $('btn-send').onclick = doSend;
  $('compose-files').onchange = (e) => handleFiles(e.target.files);

  // confirm
  $('btn-confirm-yes').onclick = () => resolveConfirm(true);
  $('btn-confirm-no').onclick = () => resolveConfirm(false);

  // accounts modal
  $('btn-accounts-close').onclick = closeAccountsModal;
  $('accounts-modal').addEventListener('click', (e) => { if (e.target === $('accounts-modal')) closeAccountsModal(); });
  $('compose-modal').addEventListener('click', (e) => { if (e.target === $('compose-modal')) closeCompose(); });

  // keyboard
  document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape') {
      if (!$('compose-modal').classList.contains('hidden')) closeCompose();
      else if (!$('confirm-modal').classList.contains('hidden')) resolveConfirm(false);
      else if (!$('accounts-modal').classList.contains('hidden')) closeAccountsModal();
      else closeDropdowns();
    }
    if (e.key === 'c' && !/input|textarea|select/i.test((e.target.tagName || ''))) {
      openCompose('new', null);
    }
    if (e.key === 'r' && !/input|textarea|select/i.test((e.target.tagName || ''))) {
      loadMessages();
    }
  });
}

/* ══════════════════ go ══════════════════ */
wire();
boot();
