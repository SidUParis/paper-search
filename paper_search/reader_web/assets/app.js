const state = { papers: [], paper: null };
const $ = (sel) => document.querySelector(sel);
const $$ = (sel) => Array.from(document.querySelectorAll(sel));
const esc = (s='') => String(s).replace(/[&<>"]/g, ch => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[ch]));

async function loadPapers() {
  const res = await fetch('data/papers.json', { cache: 'no-store' });
  state.papers = await res.json();
  return state.papers;
}
function uniq(values) { return [...new Set(values.filter(Boolean))].sort(); }
function paperHref(p) { return `paper.html?id=${encodeURIComponent(p.paper_id)}`; }
function summaryOf(p) { return p.zh_brief || p.tldr || p.summary || p.abstract || '待补充。'; }
function renderMetrics() {
  const box = $('#metrics'); if (!box) return;
  const topics = uniq(state.papers.map(p => p.topic_slug));
  const sources = uniq(state.papers.map(p => p.source_label || p.venue));
  const deep = state.papers.filter(p => p.tldr || p.method || p.results || p.limitations || p.relevance).length;
  box.innerHTML = [
    ['Papers', state.papers.length, '可问答论文'], ['Topics', topics.length, '研究方向'], ['Sources', sources.length, '会议/来源'], ['Deep', deep, '深度字段']
  ].map(([k,v,d],i)=>`<article class="metric ${i===0?'primary':''}"><span>0${i+1}</span><strong>${v}</strong><p>${k}</p><small>${d}</small></article>`).join('');
}
function renderQueue() {
  const box = $('#reading-queue'); if (!box) return;
  box.innerHTML = state.papers.slice(0,6).map(p=>`<a class="queue-item" href="${paperHref(p)}"><strong>${esc(p.title)}</strong><span>${esc(p.display_year || p.year || '')} · ${esc(p.display_venue || p.venue || p.source_label || '')}</span></a>`).join('');
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
    const text = `${p.title} ${summaryOf(p)} ${(p.tags||[]).join(' ')}`.toLowerCase();
    return (!q || text.includes(q)) && (!t || p.topic_slug === t) && (!s || (p.source_label || p.venue) === s);
  });
  grid.innerHTML = filtered.map(p=>`<a class="paper-card" href="${paperHref(p)}"><div class="paper-top"><span>${esc(p.topic_slug || 'paper')}</span><span>${esc(p.display_year || '')}</span></div><h3>${esc(p.title)}</h3><p>${esc(summaryOf(p)).slice(0,220)}${summaryOf(p).length>220?'…':''}</p><div class="tag-row">${(p.tags||[]).slice(0,4).map(t=>`<em>${esc(t)}</em>`).join('')}</div></a>`).join('');
}
function setupTabs() {
  $$('.nav-item').forEach(btn => btn.addEventListener('click', () => {
    $$('.nav-item').forEach(b=>b.classList.toggle('active', b===btn));
    $$('.view').forEach(v=>v.classList.toggle('active', v.id===btn.dataset.view));
  }));
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
  document.title = `${p.title} · Sidney Deep Paper Reader`;
  $('#paper-hero').innerHTML = `<p class="kicker">${esc(p.topic_slug)} · ${esc(p.source_label || p.venue || '')}</p><h1>${esc(p.title)}</h1><p>${esc((p.authors||[]).join(', '))} · ${esc(p.display_year || p.year || '')} · ${esc(p.display_venue || p.venue || '')}</p><div class="tag-row">${(p.tags||[]).map(t=>`<em>${esc(t)}</em>`).join('')}</div>`;
  const sections = [['中文速览', p.zh_brief || p.tldr || p.summary], ['TL;DR', p.tldr], ['Method / 方法', p.method], ['Results / 结果', p.results], ['Limitations / 局限', p.limitations], ['PhD Relevance', p.relevance], ['Abstract', p.abstract]];
  $('#paper-content').innerHTML = sections.filter(([,v])=>v).map(([k,v])=>`<section class="content-section"><h2>${esc(k)}</h2><p>${esc(v)}</p></section>`).join('') || '<section class="content-section"><p>待补充。</p></section>';
}
async function init() {
  await loadPapers();
  setupTabs(); setupChat();
  if (document.body.dataset.page === 'paper') renderPaperPage();
  else { renderMetrics(); renderQueue(); fillFilters(); renderLibrary(); ['search','topic-filter','source-filter'].forEach(id => document.getElementById(id)?.addEventListener('input', renderLibrary)); }
}
init().catch(err => { console.error(err); document.body.insertAdjacentHTML('afterbegin', `<pre class="fatal">${esc(err.message || err)}</pre>`); });
