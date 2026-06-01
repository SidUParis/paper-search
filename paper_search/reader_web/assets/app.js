const state = { papers: [], paper: null, catalog: {topics: [], sources: []} };
const $ = (sel) => document.querySelector(sel);
const $$ = (sel) => Array.from(document.querySelectorAll(sel));
const page = document.body.dataset.page || 'discovery';
const esc = (s='') => String(s ?? '').replace(/[&<>"]/g, ch => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[ch]));
const navItems = [
  ['discovery','Discovery','index.html'], ['library','Library','library.html'], ['ai','AI Reader','ai.html'], ['admin','Admin','admin.html'], ['models','Models','models.html']
];
function renderNav(){ const box=$('[data-nav]'); if(!box) return; box.innerHTML=`<div class="brand-block"><div class="brand-mark">PR</div><div><strong>Paper Reader</strong><span>Sidney private lab</span></div></div><nav class="side-nav">${navItems.map(([id,label,href],i)=>`<a class="side-link ${page===id?'active':''}" href="${href}"><span>${String(i+1).padStart(2,'0')}</span>${label}</a>`).join('')}</nav><div class="sidebar-foot"><span class="live-dot"></span><div><strong>Private access</strong><small>Cloudflare Access</small></div></div>`; }
async function loadPapers(){ const res=await fetch('data/papers.json',{cache:'no-store'}); state.papers=await res.json(); try{ const c=await fetch('data/catalog.json',{cache:'no-store'}); state.catalog=await c.json(); }catch(_err){ state.catalog={topics:[],sources:[]}; } return state.papers; }
function uniq(values){ return [...new Set(values.filter(Boolean))].sort((a,b)=>String(a).localeCompare(String(b))); }
function sourceKey(v){ return String(v||'').trim().toLowerCase(); }
function sourceLabel(v){ const key=sourceKey(v); const labels={acl:'ACL',arxiv:'arXiv',scholar:'Scholar',emnlp:'EMNLP',naacl:'NAACL',eacl:'EACL',coling:'COLING',findings:'Findings',neurips:'NeurIPS',nips:'NIPS',iclr:'ICLR',icml:'ICML',aaai:'AAAI',facct:'FAccT',tacl:'TACL'}; return labels[key]||String(v||'').trim(); }
function paperSourceKeys(p){ return uniq([p.source_label,p.venue,p.display_venue].map(sourceKey)); }
function metaLine(p){ return [p.display_year||p.year,p.display_venue||p.venue||p.source_label].filter(Boolean).join(' · '); }
function summaryOf(p){ return p.zh_brief||p.tldr||p.summary||p.abstract||'待补充。'; }
function short(t,n=180){ t=String(t||''); return t.length>n?t.slice(0,n)+'…':t; }
function scoreFor(p){ const text=`${p.summary||''} ${p.zh_brief||''} ${p.results||''}`; let score=7.8; if(text.length>700) score+=0.8; if((p.tags||[]).some(t=>/benchmark|evaluation|fairness|bias/i.test(t))) score+=0.5; if(p.local_document||p.source_url) score+=0.3; return Math.min(9.8,score).toFixed(1); }
function noveltyFor(p){ const tags=(p.tags||[]).join(' '); if(/benchmark|dataset|evaluation/i.test(tags)) return 'High'; if(/survey|review/i.test(tags)) return 'Medium'; return 'Emerging'; }
function paperHref(p){ return `paper.html?id=${encodeURIComponent(p.paper_id)}`; }
function aiHref(p){ return `ai.html?id=${encodeURIComponent(p.paper_id)}`; }
function allTags(){ return uniq(state.papers.flatMap(p=>Array.isArray(p.tags)?p.tags:[])); }
function card(p, cls='paper-card'){ return `<a class="${cls}" href="${aiHref(p)}"><div class="card-meta"><span>${esc(p.topic_slug||'paper')}</span><span>${esc(metaLine(p))}</span></div><h3>${esc(p.title)}</h3><p>${esc(short(summaryOf(p), cls==='small-card'?150:210))}</p><div class="tag-row">${(p.tags||[]).slice(0,4).map(t=>`<em>${esc(t)}</em>`).join('')}</div></a>`; }
function renderMetrics(){ const box=$('#metrics'); if(!box)return; const topics=uniq(state.papers.map(p=>p.topic_slug)); const sources=uniq(state.papers.map(p=>p.source_label||p.venue)); const pdf=state.papers.filter(p=>p.local_document||p.source_url).length; box.innerHTML=[['Papers',state.papers.length,'synced records'],['Topics',topics.length,'Obsidian/Notion groups'],['Sources',sources.length,'venues/feeds'],['PDF-ready',pdf,'documents']].map(([k,v,d])=>`<article class="stat"><strong>${v}</strong><span>${k}</span><small>${d}</small></article>`).join(''); }
function renderDiscovery(){ const first=state.papers[0]; if(!first)return; $('#today-count').textContent=state.papers.length; $('#hero-paper').innerHTML=`<p class="eyebrow">Featured paper</p><h2>${esc(first.title)}</h2><p>${esc(short(summaryOf(first),420))}</p><div class="hero-footer"><span>${esc(metaLine(first))}</span><a class="primary-link" href="${aiHref(first)}">Read with AI →</a></div>`; $('#daily-list').innerHTML=state.papers.slice(1,6).map((p,i)=>`<a class="daily-item" href="${aiHref(p)}"><span>${String(i+1).padStart(2,'0')}</span><strong>${esc(p.title)}</strong><small>${esc(metaLine(p))}</small></a>`).join(''); $('#continue-grid').innerHTML=state.papers.slice(0,6).map(p=>card(p,'small-card')).join(''); }
function fillFilters(prefix=''){ const topic=$(`#${prefix}topic-filter`), source=$(`#${prefix}source-filter`), tag=$(`#${prefix}tag-filter`); const configuredTopics=(state.catalog.topics||[]).map(t=>t.slug||t.name).filter(Boolean); const configuredSources=(state.catalog.sources||[]).filter(Boolean); if(topic) uniq([...configuredTopics,...state.papers.map(p=>p.topic_slug)]).forEach(v=>topic.insertAdjacentHTML('beforeend',`<option value="${esc(v)}">${esc(v)}</option>`)); if(source){ const sourceKeys=uniq([...configuredSources.map(sourceKey),...state.papers.flatMap(p=>paperSourceKeys(p))]); sourceKeys.forEach(v=>source.insertAdjacentHTML('beforeend',`<option value="${esc(v)}">${esc(sourceLabel(v))}</option>`)); } if(tag) allTags().forEach(v=>tag.insertAdjacentHTML('beforeend',`<option value="${esc(v)}">${esc(v)}</option>`)); }
function renderTaxonomy(){
  const total=$('#taxonomy-total'); if(total) total.textContent=state.papers.length;
  const topicBox=$('#taxonomy-projects'), areaBox=$('#taxonomy-areas'), statusBox=$('#taxonomy-status');
  const makeItem=(label,value,type,count)=>`<button class="taxonomy-item" data-taxonomy-type="${type}" data-taxonomy-value="${esc(value)}"><span>${esc(label)}</span><em>${count}</em></button>`;
  if(topicBox){ const topics=uniq(state.papers.map(p=>p.topic_slug)); topicBox.innerHTML=topics.map(t=>makeItem(t,t,'topic',state.papers.filter(p=>p.topic_slug===t).length)).join(''); }
  if(areaBox){ const sources=uniq(state.papers.flatMap(p=>paperSourceKeys(p))).slice(0,14); areaBox.innerHTML=sources.map(s=>makeItem(sourceLabel(s),s,'source',state.papers.filter(p=>paperSourceKeys(p).includes(s)).length)).join(''); }
  if(statusBox){ const items=[['PDF ready','pdf'],['Has note','note'],['Needs summary','todo']]; statusBox.innerHTML=items.map(([label,val])=>makeItem(label,val,'status',state.papers.filter(p=>val==='pdf'?(p.local_document||p.source_url):val==='note'?summaryOf(p)!=='待补充。':summaryOf(p)==='待补充。').length)).join(''); }
  $$('[data-taxonomy-type]').forEach(btn=>btn.addEventListener('click',()=>{
    $$('[data-taxonomy-type]').forEach(b=>b.classList.remove('active'));
    btn.classList.add('active');
    const type=btn.dataset.taxonomyType, val=btn.dataset.taxonomyValue;
    if(type==='topic' && $('#ai-topic-filter')) $('#ai-topic-filter').value=val;
    if(type==='source' && $('#ai-source-filter')) $('#ai-source-filter').value=val;
    if(type==='status') state.statusFilter=val;
    if(type!=='status') state.statusFilter='';
    renderAiList();
  }));
  $('[data-reset-taxonomy]')?.addEventListener('click',()=>{ ['ai-topic-filter','ai-source-filter','ai-tag-filter','ai-paper-search'].forEach(id=>{ const el=document.getElementById(id); if(el) el.value=''; }); state.statusFilter=''; $$('[data-taxonomy-type]').forEach(b=>b.classList.remove('active')); renderAiList(); });
}
function filteredPapers(prefix=''){ const q=($(`#${prefix}paper-search`)?.value || $('#search')?.value || '').toLowerCase(); const topic=$(`#${prefix}topic-filter`)?.value || $('#topic-filter')?.value || ''; const source=sourceKey($(`#${prefix}source-filter`)?.value || ''); const tag=$(`#${prefix}tag-filter`)?.value || $('#tag-filter')?.value || ''; const status=prefix==='ai-'?state.statusFilter:''; return state.papers.filter(p=>{ const tags=Array.isArray(p.tags)?p.tags:[]; const text=`${p.title} ${summaryOf(p)} ${p.abstract||''} ${tags.join(' ')} ${p.venue||''} ${p.source_label||''}`.toLowerCase(); const statusOk=!status || (status==='pdf'&&(p.local_document||p.source_url)) || (status==='note'&&summaryOf(p)!=='待补充。') || (status==='todo'&&summaryOf(p)==='待补充。'); return (!q||text.includes(q)) && (!topic||p.topic_slug===topic) && (!source||paperSourceKeys(p).includes(source)) && (!tag||tags.includes(tag)) && statusOk; }); }
function renderLibrary(){ const grid=$('#paper-grid'); if(!grid)return; const papers=filteredPapers(''); grid.innerHTML=papers.map(p=>card(p)).join('')||'<div class="empty">No papers match this filter.</div>'; }
function pdfUrl(p){ if(p.local_document) return `/paper-assets/document/${encodeURIComponent(p.paper_id)}`; const u=String(p.source_url||''); if(/arxiv\.org\/abs\//.test(u)) return u.replace('/abs/','/pdf/')+'.pdf'; const acl=u.match(/^https?:\/\/aclanthology\.org\/([^/]+)\/?$/); if(acl) return `https://aclanthology.org/${acl[1]}.pdf`; return u; }
function noteHtml(p){ const sections=[['中文速览',p.zh_brief||p.tldr||p.summary],['TL;DR',p.tldr],['Motivation / 研究动机',p.motivation],['Method / 方法',p.method],['Results / 结果',p.results],['Limitations / 局限',p.limitations],['PhD Relevance',p.relevance],['Abstract',p.abstract]]; return sections.filter(([,v])=>v).map(([k,v])=>`<section class="content-section"><h2>${esc(k)}</h2><p>${esc(v)}</p></section>`).join('') || '<section class="content-section"><p>Notion / Obsidian note fields are not filled yet.</p></section>'; }
function selectPaper(p){ state.paper=p; const url=new URL(location.href); url.searchParams.set('id',p.paper_id); history.replaceState(null,'',url); $('#ai-paper-header').innerHTML=`<p class="eyebrow">${esc(p.topic_slug||'paper')} · ${esc(p.display_venue||p.venue||p.source_label||'')}</p><h1>${esc(p.title)}</h1><p>${esc((p.authors||[]).join(', '))}</p><div class="tag-row">${(p.tags||[]).slice(0,8).map(t=>`<em>${esc(t)}</em>`).join('')}</div>`; const pdf=pdfUrl(p); $('#pdf-frame').src=pdf||'about:blank'; $('#open-source').href=p.source_url||pdf||'#'; $('#pdf-status').textContent=p.local_document?'local synced PDF':(pdf?'external PDF/source':'no PDF found'); $('#synced-note').innerHTML=noteHtml(p); const tldr=$('#insight-tldr'); if(tldr) tldr.textContent=short(summaryOf(p),260); const score=$('#insight-score'); if(score) score.textContent=scoreFor(p); const nov=$('#insight-novelty'); if(nov) nov.textContent=noveltyFor(p); const meta=$('#insight-meta'); if(meta) meta.innerHTML=`<span>${esc(metaLine(p)||'No venue')}</span><span>${esc((p.tags||[]).slice(0,2).join(' · ')||p.topic_slug||'paper')}</span>`; $$('.ai-paper-item').forEach(el=>el.classList.toggle('active',el.dataset.id===p.paper_id)); }
function renderAiList(){ const list=$('#ai-paper-list'); if(!list)return; const papers=filteredPapers('ai-'); $('#ai-paper-count').textContent=papers.length; list.innerHTML=papers.map(p=>`<button class="ai-paper-item" data-id="${esc(p.paper_id)}"><strong>${esc(p.title)}</strong><span>${esc(metaLine(p))}</span><small>${esc((p.tags||[]).slice(0,3).join(' · '))}</small></button>`).join(''); $$('.ai-paper-item').forEach(b=>b.addEventListener('click',()=>selectPaper(state.papers.find(p=>p.paper_id===b.dataset.id)))); const id=new URLSearchParams(location.search).get('id'); const pdfReady = papers.find(p=>p.local_document||p.source_url) || state.papers.find(p=>p.local_document||p.source_url); const chosen=state.papers.find(p=>p.paper_id===id)||pdfReady||papers[0]||state.papers[0]; if(chosen) selectPaper(chosen); }
function setupAi(){ fillFilters('ai-'); renderTaxonomy(); ['ai-paper-search','ai-topic-filter','ai-source-filter','ai-tag-filter'].forEach(id=>document.getElementById(id)?.addEventListener('input',()=>{ if(id!=='ai-paper-search') state.statusFilter=''; renderAiList(); })); $('#show-pdf')?.addEventListener('click',()=>{ $('#pdf-frame').classList.remove('hidden'); $('#synced-note').classList.add('hidden'); $('#show-pdf').classList.add('active'); $('#show-note').classList.remove('active'); }); $('#show-note')?.addEventListener('click',()=>{ $('#pdf-frame').classList.add('hidden'); $('#synced-note').classList.remove('hidden'); $('#show-note').classList.add('active'); $('#show-pdf').classList.remove('active'); }); renderAiList(); }
function addBubble(role,text){ const log=$('#chat-log'); if(!log)return; log.insertAdjacentHTML('beforeend',`<div class="bubble ${role}">${esc(text)}</div>`); log.scrollTop=log.scrollHeight; }
function setupChat(){ const form=$('#chat-form'); if(!form)return; $$('.prompt-chip').forEach(b=>b.addEventListener('click',()=>{ $('#chat-question').value=b.dataset.prompt||b.textContent; $('#chat-question').focus(); })); form.addEventListener('submit',async e=>{ e.preventDefault(); const q=($('#chat-question')?.value||'').trim(); if(!q)return; $('[data-chat-starters]')?.classList.add('hidden'); addBubble('user',q); $('#chat-question').value=''; try{ const body={question:q,provider_id:$('#chat-provider')?.value||'deepseek',model:$('#chat-model')?.value||'deepseek-v4-flash',mode:state.paper?'deep':'library',max_tokens:state.paper?2600:4000}; if(state.paper) body.paper_key=state.paper.paper_id; const res=await fetch('/api/chat',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)}); const data=await res.json(); if(!res.ok) throw new Error(data.message||data.error||'chat failed'); addBubble('assistant',data.answer||'No answer returned.'); }catch(err){ addBubble('error',`Error: ${err.message||err}`); } }); }
function renderFigureGallery(p){ const box=$('#figure-gallery'), count=$('#figure-count'); if(!box) return; const figures=Array.isArray(p.figures)?p.figures:[]; if(count) count.textContent=String(figures.length); if(!figures.length){ box.innerHTML='<div class="empty-mini">No extracted figures yet. Run Admin → Fulltext + regenerate after PDFs are synced.</div>'; return; } box.innerHTML=figures.map((f,i)=>{ const title=esc(f.title||`${f.kind||'asset'} ${i+1}`); const caption=esc(f.caption||''); if(f.kind==='table'){ const rows=(f.preview||[]).slice(0,4).map(row=>`<tr>${row.slice(0,4).map(cell=>`<td>${esc(cell)}</td>`).join('')}</tr>`).join(''); return `<a class="figure-card" href="${esc(f.src)}" target="_blank" rel="noreferrer"><strong>${title}</strong><small>Page ${esc(f.page||'—')} · table</small><table>${rows}</table><p>${caption}</p></a>`; } return `<a class="figure-card" href="${esc(f.src)}" target="_blank" rel="noreferrer"><img src="${esc(f.src)}" loading="lazy" alt="${title}" /><strong>${title}</strong><small>Page ${esc(f.page||'—')} · image</small><p>${caption}</p></a>`; }).join(''); }
function renderPaperPage(){ const id=new URLSearchParams(location.search).get('id'); const p=state.papers.find(x=>x.paper_id===id)||state.papers[0]; state.paper=p; if(!p)return; $('#open-ai-reader').href=aiHref(p); $('#paper-hero').innerHTML=`<p class="eyebrow">${esc(p.topic_slug)} · ${esc(p.source_label||p.venue||'')}</p><h1>${esc(p.title)}</h1><p>${esc((p.authors||[]).join(', '))}</p><div class="hero-footer"><span>${esc(metaLine(p))}</span><a class="primary-link" href="${aiHref(p)}">Open PDF + Chat →</a></div>`; $('#paper-content').innerHTML=noteHtml(p); renderFigureGallery(p); $('#paper-meta').innerHTML=`<p class="eyebrow">Paper info</p><dl class="meta-list"><dt>Year</dt><dd>${esc(p.display_year||p.year||'—')}</dd><dt>Venue</dt><dd>${esc(p.display_venue||p.venue||p.source_label||'—')}</dd><dt>Tags</dt><dd>${(p.tags||[]).map(t=>`<em>${esc(t)}</em>`).join(' ')||'—'}</dd></dl>`; }

async function fetchJobs(){
  const box=$('#job-list'), out=$('#job-output'), title=$('#job-status-title');
  if(!box) return;
  try{
    const res=await fetch('/api/admin/jobs/status',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({})});
    const data=await res.json();
    const jobs=data.jobs||[];
    title.textContent=jobs[0]?.status||'idle';
    box.innerHTML=jobs.length?jobs.map(j=>`<button class="job-item" data-job-id="${esc(j.job_id)}"><strong><span>${esc(j.action)}</span><span>${esc(j.status)}</span></strong><small>${esc(j.updated_at||j.created_at)} · ${esc(j.job_id)}</small></button>`).join(''):'<div class="empty-log">No jobs yet.</div>';
    $$('.job-item').forEach(btn=>btn.addEventListener('click',async()=>{
      const r=await fetch('/api/admin/jobs/status',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({job_id:btn.dataset.jobId})});
      const j=await r.json();
      out.textContent=(j.output_tail||j.error||'No output yet.');
      title.textContent=j.status||'idle';
    }));
    if(out && jobs[0]) out.textContent=jobs[0].output_tail||jobs[0].error||'Job queued/running…';
  }catch(err){ if(out) out.textContent=`Failed to load jobs: ${err.message||err}`; }
}
function setupAdmin(){
  if(page!=='admin') return;
  $('[data-refresh-jobs]')?.addEventListener('click', fetchJobs);
  $$('[data-job-action]').forEach(btn=>btn.addEventListener('click',async()=>{
    const payload={
      action:btn.dataset.jobAction,
      topic:$('#admin-topic')?.value||'bias-fairness',
      source:$('#admin-source')?.value||'all',
      max_results:$('#admin-max-results')?.value||50,
      summarize:false,
    };
    const exportLimit=($('#admin-limit')?.value||'').trim();
    if(exportLimit) payload.limit=exportLimit;
    btn.disabled=true;
    try{
      const res=await fetch('/api/admin/jobs',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)});
      const data=await res.json();
      if(!res.ok) throw new Error(data.message||data.error||'job failed');
      $('#job-output').textContent=`Started ${data.action} job ${data.job_id}\n${(data.commands||[]).map(c=>'$ '+c.join(' ')).join('\n')}`;
      await fetchJobs();
    }catch(err){ $('#job-output').textContent=`Error: ${err.message||err}`; }
    finally{ btn.disabled=false; }
  }));
  fetchJobs();
}
function renderRankResults(results){ const box=$('[data-rank-results]'); if(!box) return; if(!results.length){ box.innerHTML='<div class="rank-empty">AI 没有找到可排序结果；可以换一个更具体的问题。</div>'; return; } box.innerHTML=results.map((r,i)=>{ const p=r.paper||{}; const pct=Math.round((Number(r.score)||0)*100); return `<a class="rank-card" href="${aiHref(p)}"><span class="rank-num">${String(i+1).padStart(2,'0')}</span><div><strong>${esc(p.title||r.paper_id)}</strong><p>${esc(r.reason||'')}</p><small>${pct}% · ${esc(r.suggested_action||'skim')} · ${esc(metaLine(p))}</small></div></a>`; }).join(''); }
function setupRanking(){ const form=$('[data-rank-form]'); if(!form) return; const input=$('[data-rank-query]'), status=$('[data-rank-status]'); form.addEventListener('submit',async e=>{ e.preventDefault(); const query=(input?.value||'').trim(); if(!query) return; if(status) status.textContent='LLM 正在 refine / rerank 当前 library…'; try{ const res=await fetch('/api/rank',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({query,provider_id:$('#chat-provider')?.value||'deepseek',model:$('#chat-model')?.value||'deepseek-v4-flash',limit:8,candidate_limit:40})}); const data=await res.json(); if(!res.ok) throw new Error(data.message||data.error||'ranking failed'); renderRankResults(data.results||[]); if(page==='library' && data.results?.length){ const ids=new Set(data.results.map(r=>r.paper_id)); const ranked=data.results.map(r=>r.paper).filter(Boolean); const rest=state.papers.filter(p=>!ids.has(p.paper_id)); state.papers=[...ranked,...rest]; renderLibrary(); } if(status) status.textContent=`Found ${data.results?.length||0} papers · ${esc(data.model||'model')}`; }catch(err){ if(status) status.textContent=`Error: ${err.message||err}`; } }); window.addEventListener('keydown',e=>{ if((e.metaKey||e.ctrlKey) && e.key.toLowerCase()==='k'){ e.preventDefault(); input?.focus(); } }); }

async function init(){ renderNav(); await loadPapers(); setupChat(); setupRanking(); if(page==='discovery'){renderMetrics();renderDiscovery();} if(page==='library'){fillFilters('');renderLibrary();['search','topic-filter','source-filter','tag-filter'].forEach(id=>document.getElementById(id)?.addEventListener('input',renderLibrary));} if(page==='ai') setupAi(); if(page==='paper') renderPaperPage(); setupAdmin(); }
init().catch(err=>{ console.error(err); document.body.insertAdjacentHTML('afterbegin',`<pre class="fatal">${esc(err.message||err)}</pre>`); });
