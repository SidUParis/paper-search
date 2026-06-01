const state = { papers: [], paper: null };
const $ = (sel) => document.querySelector(sel);
const $$ = (sel) => Array.from(document.querySelectorAll(sel));
const esc = (s='') => String(s ?? '').replace(/[&<>"]/g, ch => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[ch]));

async function loadPapers() {
  const res = await fetch('data/papers.json', { cache: 'no-store' });
  state.papers = await res.json();
  return state.papers;
}
function uniq(values) { return [...new Set(values.filter(Boolean))].sort((a,b)=>String(a).localeCompare(String(b))); }
function paperHref(p) { return `paper.html?id=${encodeURIComponent(p.paper_id)}`; }
function summaryOf(p) { return p.zh_brief || p.tldr || p.summary || p.abstract || '待补充。'; }
function short(text, n=180) { text = String(text || ''); return text.length > n ? text.slice(0,n) + '…' : text; }
function metaLine(p) { return [p.display_year || p.year, p.display_venue || p.venue || p.source_label].filter(Boolean).join(' · '); }

function renderMetrics() {
  const box = $('#metrics'); if (!box) return;
  const topics = uniq(state.papers.map(p => p.topic_slug));
  const sources = uniq(state.papers.map(p => p.source_label || p.venue));
  const deep = state.papers.filter(p => p.tldr || p.method || p.results || p.limitations || p.relevance).length;
  box.innerHTML = [
    ['Daily papers', state.papers.length, 'active corpus'], ['Topics', topics.length, 'research streams'], ['Sources', sources.length, 'venues / feeds'], ['Context-ready', deep, 'deep fields']
  ].map(([k,v,d])=>`<article class="stat"><strong>${esc(v)}</strong><span>${esc(k)}</span><small>${esc(d)}</small></article>`).join('');
}
function paperCard(p, cls='paper-card') {
  return `<a class="${cls}" href="${paperHref(p)}"><div class="card-meta"><span>${esc(p.topic_slug || 'paper')}</span><span>${esc(metaLine(p))}</span></div><h3>${esc(p.title)}</h3><p>${esc(short(summaryOf(p), cls==='large-card'?260:170))}</p><div class="tag-row">${(p.tags||[]).slice(0,4).map(t=>`<em>${esc(t)}</em>`).join('')}</div></a>`;
}
function renderDiscovery() {
  const hero = $('#hero-paper'); if (!hero) return;
  const papers = state.papers;
  const first = papers[0];
  $('#today-count').textContent = papers.length;
  if (first) {
    hero.innerHTML = `<p class="eyebrow">Featured paper</p><h2>${esc(first.title)}</h2><p>${esc(short(summaryOf(first), 420))}</p><div class="hero-footer"><span>${esc(metaLine(first))}</span><a class="primary-link" href="${paperHref(first)}">Start reading →</a></div>`;
  }
  $('#daily-list').innerHTML = papers.slice(1,6).map((p,i)=>`<a class="daily-item" href="${paperHref(p)}"><span>${String(i+1).padStart(2,'0')}</span><strong>${esc(p.title)}</strong><small>${esc(metaLine(p))}</small></a>`).join('');
  $('#continue-grid').innerHTML = papers.slice(0,6).map(p=>paperCard(p, 'small-card')).join('');
}
function fillFilters() {
  const topic = $('#topic-filter'), source = $('#source-filter'); if (!topic || !source) return;
  uniq(state.papers.map(p=>p.topic_slug)).forEach(v => topic.insertAdjacentHTML('beforeend', `<option value="${esc(v)}">${esc(v)}</option>`));
  uniq(state.papers.map(p=>p.source_label || p.venue)).forEach(v => source.insertAdjacentHTML('beforeend', `<option value="${esc(v)}">${esc(v)}</option>`));
}
function renderLibrary() {
  const grid = $('#paper-grid'); if (!grid) return;
  const q = ($('#search')?.value || '').toLowerCase();
  const t = $('#topic-filter')?.value || '';
  const s = $('#source-filter')?.value || '';
  const filtered = state.papers.filter(p => {
    const text = `${p.title} ${summaryOf(p)} ${p.abstract || ''} ${(p.tags||[]).join(' ')}`.toLowerCase();
    return (!q || text.includes(q)) && (!t || p.topic_slug === t) && (!s || (p.source_label || p.venue) === s);
  });
  grid.innerHTML = filtered.map(p=>paperCard(p)).join('') || '<div class="empty">No papers match this filter.</div>';
}
function activateView(id) {
  $$('.side-link').forEach(b=>b.classList.toggle('active', b.dataset.view === id));
  $$('.view').forEach(v=>v.classList.toggle('active', v.id === id));
}
function setupTabs() {
  $$('.side-link').forEach(btn => btn.addEventListener('click', () => activateView(btn.dataset.view)));
  $$('[data-view-target]').forEach(el => el.addEventListener('click', () => activateView(el.dataset.viewTarget)));
}
function addBubble(role, text) {
  const log = $('#chat-log'); if (!log) return;
  log.insertAdjacentHTML('beforeend', `<div class="bubble ${role}">${esc(text)}</div>`);
  log.scrollTop = log.scrollHeight;
}
function setupChat() {
  const form = $('#chat-form'); if (!form) return;
  $$('.prompt-chip').forEach(b => b.addEventListener('click', () => { $('#chat-question').value = b.dataset.prompt || b.textContent; $('#chat-question').focus(); }));
  form.addEventListener('submit', async (e) => {
    e.preventDefault();
    const q = ($('#chat-question')?.value || '').trim(); if (!q) return;
    const status = $('#chat-status'); const button = form.querySelector('button[type="submit"]');
    addBubble('user', q); $('#chat-question').value = ''; if(status) status.textContent='thinking…'; if(button) button.disabled=true;
    try {
      const body = { question: q, provider_id: $('#chat-provider')?.value || 'deepseek', model: $('#chat-model')?.value || 'deepseek-v4-flash', mode: state.paper ? 'balanced' : 'library', max_tokens: state.paper ? 2400 : 4000 };
      if (state.paper) body.paper_key = state.paper.paper_id;
      const res = await fetch('/api/chat', { method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify(body) });
      const data = await res.json();
      if (!res.ok) throw new Error(data.message || data.error || 'chat failed');
      addBubble('assistant', data.answer || 'No answer returned.');
    } catch (err) { addBubble('error', `Error: ${err.message || err}`); }
    finally { if(status) status.textContent='ready'; if(button) button.disabled=false; }
  });
}
function renderPaperPage() {
  const id = new URLSearchParams(location.search).get('id');
  const p = state.papers.find(x => x.paper_id === id) || state.papers[0]; state.paper = p;
  if (!p) return;
  document.title = `${p.title} · Sidney Deep Paper Reader`;
  $('#paper-hero').innerHTML = `<p class="eyebrow">${esc(p.topic_slug || 'paper')} · ${esc(p.source_label || p.venue || '')}</p><h1>${esc(p.title)}</h1><p>${esc((p.authors||[]).join(', '))}</p><div class="hero-footer"><span>${esc(metaLine(p))}</span>${p.source_url ? `<a class="primary-link" href="${esc(p.source_url)}" target="_blank" rel="noopener">Source ↗</a>` : ''}</div>`;
  const sections = [
    ['summary','中文速览', p.zh_brief || p.tldr || p.summary], ['tldr','TL;DR', p.tldr], ['motivation','Motivation / 研究动机', p.motivation], ['method','Method / 方法', p.method], ['results','Results / 结果', p.results], ['limitations','Limitations / 局限', p.limitations], ['relevance','Why relevant to Sidney PhD / 与我的博士相关性', p.relevance], ['abstract','Abstract', p.abstract]
  ];
  $('#paper-content').innerHTML = sections.filter(([, ,v])=>v).map(([id,k,v])=>`<section id="${id}" class="content-section"><h2>${esc(k)}</h2><p>${esc(v)}</p></section>`).join('') || '<section class="content-section"><p>待补充。</p></section>';
  $('#paper-meta').innerHTML = `<p class="eyebrow">Paper info</p><dl class="meta-list"><dt>Year</dt><dd>${esc(p.display_year || p.year || '—')}</dd><dt>Venue</dt><dd>${esc(p.display_venue || p.venue || p.source_label || '—')}</dd><dt>Tags</dt><dd>${(p.tags||[]).slice(0,6).map(t=>`<em>${esc(t)}</em>`).join(' ') || '—'}</dd></dl>`;
}
async function init() {
  await loadPapers();
  setupTabs(); setupChat();
  if (document.body.dataset.page === 'paper') renderPaperPage();
  else { renderMetrics(); renderDiscovery(); fillFilters(); renderLibrary(); ['search','topic-filter','source-filter'].forEach(id => document.getElementById(id)?.addEventListener('input', renderLibrary)); }
}
init().catch(err => { console.error(err); document.body.insertAdjacentHTML('afterbegin', `<pre class="fatal">${esc(err.message || err)}</pre>`); });
