const state = { papers: [], paper: null, catalog: {topics: [], sources: []}, featured: null, modelConfig: null, lastNoteDraft: null, selectedVisual: null, uploadedFiles: [], webSearch: false, viewerIndex: 0, viewerZoom: 1, pdfPage: 1, pdfPages: 0, pdfZoom: 1, taxonomyMode: 'all', taxonomyValue: '' };
const $ = (sel) => document.querySelector(sel);
const $$ = (sel) => Array.from(document.querySelectorAll(sel));
const page = document.body.dataset.page || 'discovery';
const esc = (s='') => String(s ?? '').replace(/[&<>"]/g, ch => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[ch]));
const navItems = [
  ['discovery','Discovery','index.html'], ['library','Library','library.html'], ['ai','AI Reader','ai.html'], ['admin','Admin','admin.html'], ['models','Models','models.html']
];
function renderNav(){ const box=$('[data-nav]'); if(!box) return; box.innerHTML=`<a class="brand-block brand-link" href="https://www.xfairllm.com/" aria-label="Back to xfairllm.com"><img class="brand-logo" src="assets/xfair-logo.png" alt="XFaiR LLM logo" /><div><strong>XFaiR LLM</strong><span>Back to main site</span></div></a><nav class="side-nav">${navItems.map(([id,label,href],i)=>`<a class="side-link ${page===id?'active':''}" href="${href}"><span>${String(i+1).padStart(2,'0')}</span>${label}</a>`).join('')}</nav><div class="sidebar-foot"><span class="live-dot"></span><div><strong>Private access</strong><small>Cloudflare Access</small></div></div>`; }
async function loadPapers(){ const res=await fetch('data/papers.json',{cache:'no-store'}); state.papers=await res.json(); try{ const c=await fetch('data/catalog.json',{cache:'no-store'}); state.catalog=await c.json(); }catch(_err){ state.catalog={topics:[],sources:[]}; } try{ const f=await fetch('data/daily-featured.json',{cache:'no-store'}); state.featured=await f.json(); }catch(_err){ state.featured=null; } return state.papers; }
function uniq(values){ return [...new Set(values.filter(Boolean))].sort((a,b)=>String(a).localeCompare(String(b))); }
function uniqBy(values,keyFn){ const seen=new Set(); const out=[]; values.filter(Boolean).forEach(v=>{ const key=keyFn(v); if(!seen.has(key)){ seen.add(key); out.push(v); } }); return out; }
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
function paperProjects(p){ const values=Array.isArray(p.projects)?p.projects:[]; return values.filter(Boolean); }
function countBy(items){ const m=new Map(); items.filter(Boolean).forEach(v=>m.set(v,(m.get(v)||0)+1)); return [...m.entries()].sort((a,b)=>b[1]-a[1]||String(a[0]).localeCompare(String(b[0]))); }
function setHiddenFilter(id,value){ const el=document.getElementById(id); if(el) el.value=value||''; }
function taxonomyLabel(mode,value){ if(mode==='project') return value; if(mode==='topic') return value; if(mode==='venue') return sourceLabel(value); if(mode==='status') return value==='pdf'?'PDF ready':value==='note'?'Has note':'Needs summary'; return 'All Papers'; }
function card(p, cls='paper-card'){ return `<a class="${cls}" href="${aiHref(p)}"><div class="card-meta"><span>${esc(p.topic_slug||'paper')}</span><span>${esc(metaLine(p))}</span></div><h3>${esc(p.title)}</h3><p>${esc(short(summaryOf(p), cls==='small-card'?150:210))}</p><div class="tag-row">${(p.tags||[]).slice(0,4).map(t=>`<em>${esc(t)}</em>`).join('')}</div></a>`; }
function renderMetrics(){ const box=$('#metrics'); if(!box)return; const topics=uniq(state.papers.map(p=>p.topic_slug)); const sources=uniq(state.papers.map(p=>p.source_label||p.venue)); const pdf=state.papers.filter(p=>p.local_document||p.source_url).length; box.innerHTML=[['Papers',state.papers.length,'synced records'],['Topics',topics.length,'Obsidian/Notion groups'],['Sources',sources.length,'venues/feeds'],['PDF-ready',pdf,'documents']].map(([k,v,d])=>`<article class="stat"><strong>${v}</strong><span>${k}</span><small>${d}</small></article>`).join(''); }
function resolveFeaturedPaper(item){ if(!item) return null; const source=String(item.source_url||'').trim(); const title=String(item.title||'').trim().toLowerCase(); return state.papers.find(p=>source && String(p.source_url||'').trim()===source) || state.papers.find(p=>title && String(p.title||'').trim().toLowerCase()===title) || null; }
function renderDiscovery(){ const digestItems=Array.isArray(state.featured?.daily)?state.featured.daily:[]; const digestPapers=digestItems.map(resolveFeaturedPaper).filter(Boolean); const first=digestPapers[0]||state.papers[0]; if(!first)return; const daily=uniqBy([...digestPapers,...state.papers.slice(1,6)], p=>p.paper_id).slice(0,5); $('#today-count').textContent=state.papers.length; const stamp=state.featured?.generated_at?` · ${state.featured.generated_at}`:''; $('#hero-paper').innerHTML=`<p class="eyebrow">Featured from daily digest${esc(stamp)}</p><h2>${esc(first.title)}</h2><p>${esc(short(summaryOf(first),420))}</p><div class="hero-footer"><span>${esc(metaLine(first))}</span><a class="primary-link" href="${aiHref(first)}">Read with AI →</a></div>`; $('#daily-list').innerHTML=daily.map((p,i)=>`<a class="daily-item" href="${aiHref(p)}"><span>${String(i+1).padStart(2,'0')}</span><strong>${esc(p.title)}</strong><small>${esc(metaLine(p))}</small></a>`).join(''); $('#continue-grid').innerHTML=state.papers.slice(0,6).map(p=>card(p,'small-card')).join(''); }
function fillFilters(prefix=''){ const topic=$(`#${prefix}topic-filter`), source=$(`#${prefix}source-filter`), tag=$(`#${prefix}tag-filter`); const configuredTopics=(state.catalog.topics||[]).map(t=>t.slug||t.name).filter(Boolean); const configuredSources=(state.catalog.sources||[]).filter(Boolean); if(topic) uniq([...configuredTopics,...state.papers.map(p=>p.topic_slug)]).forEach(v=>topic.insertAdjacentHTML('beforeend',`<option value="${esc(v)}">${esc(v)}</option>`)); if(source){ const sourceKeys=uniq([...configuredSources.map(sourceKey),...state.papers.flatMap(p=>paperSourceKeys(p))]); sourceKeys.forEach(v=>source.insertAdjacentHTML('beforeend',`<option value="${esc(v)}">${esc(sourceLabel(v))}</option>`)); } if(tag) allTags().forEach(v=>tag.insertAdjacentHTML('beforeend',`<option value="${esc(v)}">${esc(v)}</option>`)); }
function inlineTaxonomySubmenu(type,value){
  if(state.taxonomyMode!==type || state.taxonomyValue!==String(value||'')) return '';
  const papers=filteredPapers('ai-');
  const title=taxonomyLabel(type,value);
  return `<div class="inline-taxonomy-submenu" aria-live="polite"><div class="submenu-title"><strong>${esc(title)}</strong><span>${papers.length} papers</span></div><div class="submenu-papers">${papers.slice(0,12).map(p=>`<button data-subpaper="${esc(p.paper_id)}"><strong>${esc(short(p.title,66))}</strong><span>${esc(metaLine(p))}</span></button>`).join('')||'<p>No papers in this group.</p>'}</div></div>`;
}
function wireInlineSubmenus(){
  $$('[data-subpaper]').forEach(btn=>btn.addEventListener('click',()=>{ const p=state.papers.find(x=>x.paper_id===btn.dataset.subpaper); if(p) selectPaper(p); }));
}
function renderTaxonomy(){
  const total=$('#taxonomy-total'); if(total) total.textContent=state.papers.length;
  const projectBox=$('#taxonomy-projects'), topicBox=$('#taxonomy-topics'), venueBox=$('#taxonomy-venues'), statusBox=$('#taxonomy-status');
  const makeItem=(label,value,type,count)=>`<div class="taxonomy-node"><button class="taxonomy-item ${state.taxonomyMode===type&&state.taxonomyValue===String(value)?'active':''}" data-taxonomy-type="${type}" data-taxonomy-value="${esc(value)}"><span>${esc(label)}</span><em>${count}</em></button>${inlineTaxonomySubmenu(type,value)}</div>`;
  if(projectBox){
    const projects=countBy(state.papers.flatMap(p=>paperProjects(p)));
    projectBox.innerHTML=projects.length ? projects.map(([name,count])=>makeItem(name,name,'project',count)).join('') : '<p class="taxonomy-empty">No Notion Review Project yet</p>';
  }
  if(topicBox){ const topics=countBy(state.papers.map(p=>p.topic_slug)); topicBox.innerHTML=topics.map(([t,count])=>makeItem(t,t,'topic',count)).join(''); }
  if(venueBox){ const venues=countBy(state.papers.flatMap(p=>paperSourceKeys(p))).slice(0,24); venueBox.innerHTML=venues.map(([s,count])=>makeItem(sourceLabel(s),s,'venue',count)).join(''); }
  if(statusBox){ const items=[['PDF ready','pdf'],['Has note','note'],['Needs summary','todo']]; statusBox.innerHTML=items.map(([label,val])=>makeItem(label,val,'status',state.papers.filter(p=>val==='pdf'?(p.local_document||p.source_url):val==='note'?summaryOf(p)!=='待补充。':summaryOf(p)==='待补充。').length)).join(''); }
  $$('[data-taxonomy-type]').forEach(btn=>btn.addEventListener('click',()=>selectTaxonomy(btn.dataset.taxonomyType, btn.dataset.taxonomyValue)));
  $('[data-reset-taxonomy]')?.addEventListener('click',()=>selectTaxonomy('all',''));
  wireInlineSubmenus();
}
function selectTaxonomy(type,value){
  if(type === state.taxonomyMode && String(value||'') === state.taxonomyValue){ type='all'; value=''; }
  state.taxonomyMode=type||'all'; state.taxonomyValue=value||''; state.statusFilter=type==='status'?value:'';
  setHiddenFilter('ai-topic-filter', type==='topic'?value:'');
  setHiddenFilter('ai-source-filter', type==='venue'?value:'');
  setHiddenFilter('ai-tag-filter','');
  setHiddenFilter('ai-paper-search','');
  renderTaxonomy();
}
function filteredPapers(prefix=''){ const q=($(`#${prefix}paper-search`)?.value || $('#search')?.value || '').toLowerCase(); const topic=$(`#${prefix}topic-filter`)?.value || $('#topic-filter')?.value || ''; const source=sourceKey($(`#${prefix}source-filter`)?.value || ''); const tag=$(`#${prefix}tag-filter`)?.value || $('#tag-filter')?.value || ''; const status=prefix==='ai-'?state.statusFilter:''; return state.papers.filter(p=>{ const tags=Array.isArray(p.tags)?p.tags:[]; const projects=paperProjects(p); const text=`${p.title} ${summaryOf(p)} ${p.abstract||''} ${tags.join(' ')} ${projects.join(' ')} ${p.venue||''} ${p.source_label||''}`.toLowerCase(); const taxonomyOk=prefix!=='ai-' || state.taxonomyMode==='all' || (state.taxonomyMode==='project'&&projects.includes(state.taxonomyValue)) || (state.taxonomyMode==='topic'&&p.topic_slug===state.taxonomyValue) || (state.taxonomyMode==='venue'&&paperSourceKeys(p).includes(sourceKey(state.taxonomyValue))) || state.taxonomyMode==='status'; const statusOk=!status || (status==='pdf'&&(p.local_document||p.source_url)) || (status==='note'&&summaryOf(p)!=='待补充。') || (status==='todo'&&summaryOf(p)==='待补充。'); return taxonomyOk && (!q||text.includes(q)) && (!topic||p.topic_slug===topic) && (!source||paperSourceKeys(p).includes(source)) && (!tag||tags.includes(tag)) && statusOk; }); }
function renderLibrary(){ const grid=$('#paper-grid'); if(!grid)return; const papers=filteredPapers(''); grid.innerHTML=papers.map(p=>card(p)).join('')||'<div class="empty">No papers match this filter.</div>'; }
function pdfUrl(p){ if(p.local_document||p.source_url) return `/paper-assets/pdf/${encodeURIComponent(p.paper_id)}`; return ''; }

async function loadPdfPreview(p){
  const stage=$('#pdf-page-stage'), label=$('#pdf-page-label'), full=$('#open-pdf-full');
  if(!stage) return;
  state.pdfPage=1; state.pdfPages=0; state.pdfZoom=1;
  const pdf=pdfUrl(p);
  if(full) full.href=pdf||'#';
  if(!pdf){ stage.innerHTML='<div class="empty-mini">No PDF found for this paper.</div>'; if(label) label.textContent='Page — / —'; updatePdfZoomLabel(); return; }
  stage.innerHTML='<div class="empty-mini">Rendering PDF page…</div>';
  updatePdfZoomLabel();
  try{
    const res=await fetch(`/api/papers/${encodeURIComponent(p.paper_id)}/pdf-info`,{cache:'no-store'});
    const info=await res.json();
    if(!res.ok) throw new Error(info.message||info.error||'PDF not available');
    state.pdfPages=Number(info.pages||1)||1;
    renderPdfPage();
  }catch(err){
    stage.innerHTML=`<div class="empty-mini">PDF preview failed: ${esc(err.message||err)}<br><a class="tiny" href="${esc(pdf)}" target="_blank" rel="noopener">Open full PDF</a></div>`;
    if(label) label.textContent='Page — / —';
  }
}
function updatePdfZoomLabel(){ const z=$('#pdf-zoom-label'); if(z) z.textContent=`${Math.round((state.pdfZoom||1)*100)}%`; }
function renderPdfPage(){
  const stage=$('#pdf-page-stage'), label=$('#pdf-page-label'), prev=$('#pdf-prev-page'), next=$('#pdf-next-page');
  if(!stage||!state.paper) return;
  const total=Math.max(1, state.pdfPages||1);
  state.pdfPage=Math.max(1, Math.min(state.pdfPage||1, total));
  if(label) label.textContent=`Page ${state.pdfPage} / ${total}`;
  if(prev) prev.disabled=state.pdfPage<=1;
  if(next) next.disabled=state.pdfPage>=total;
  updatePdfZoomLabel();
  const src=`/paper-assets/pdf-page/${encodeURIComponent(state.paper.paper_id)}/${state.pdfPage}.png`;
  stage.innerHTML=`<img class="pdf-page-image" src="${src}" alt="Rendered PDF page ${state.pdfPage}" loading="eager" style="width:${Math.round((state.pdfZoom||1)*100)}%;max-width:none" />`;
}
function changePdfPage(delta){ if(!state.paper) return; state.pdfPage=(state.pdfPage||1)+delta; renderPdfPage(); }
function zoomPdf(delta){ state.pdfZoom=Math.max(.5, Math.min(2.5, Math.round(((state.pdfZoom||1)+delta)*10)/10)); const img=$('.pdf-page-image'); if(img){ img.style.width=`${Math.round(state.pdfZoom*100)}%`; img.style.maxWidth='none'; } updatePdfZoomLabel(); }
function audioUrl(p){ const raw=String(p?.notebooklm_audio||'').trim(); if(!raw) return ''; if(/^https?:\/\//i.test(raw) || /^data:audio\//i.test(raw) || raw.startsWith('assets/')) return raw; return `/paper-assets/audio/${encodeURIComponent(p.paper_id)}`; }
function noteHtml(p){ const sections=[['中文速览',p.zh_brief||p.tldr||p.summary],['TL;DR',p.tldr],['Motivation / 研究动机',p.motivation],['Method / 方法',p.method],['Results / 结果',p.results],['Limitations / 局限',p.limitations],['PhD Relevance',p.relevance],['Abstract',p.abstract]]; return sections.filter(([,v])=>v).map(([k,v])=>`<section class="content-section"><h2>${esc(k)}</h2><p>${esc(v)}</p></section>`).join('') || '<section class="content-section"><p>Notion / Obsidian note fields are not filled yet.</p></section>'; }
function renderAudioPanel(p){ const box=$('#audio-player-card'); if(!box)return; const src=audioUrl(p); if(!src){ box.innerHTML='<div class="empty-mini">这篇论文还没有同步 NotebookLM audio。可以直接从当前 PDF 生成一个中文 Deep Dive 音频；生成会在后台运行，完成后刷新页面即可播放。</div><div class="audio-actions"><button class="tiny" data-generate-audio>Generate NotebookLM deep dive</button></div>'; box.querySelector('[data-generate-audio]')?.addEventListener('click',startNotebookAudioJob); return; } box.innerHTML=`<div class="audio-cover"><span>NotebookLM</span><strong>Audio Deep Dive</strong></div><div class="audio-copy"><p class="eyebrow">Paper audio</p><h3>${esc(p.title||'Audio deep dive')}</h3><p>播放 NotebookLM 创建的论文讲解音频；适合边读 PDF 边听。</p><audio controls preload="metadata" src="${esc(src)}"></audio><div class="audio-actions"><button class="tiny" data-audio-chat>Ask about this audio</button><button class="tiny ghost" data-generate-audio>Regenerate audio</button>${/^https?:\/\//i.test(src)?`<a class="tiny ghost" href="${esc(src)}" target="_blank" rel="noopener">Open audio source</a>`:''}</div></div>`; box.querySelector('[data-audio-chat]')?.addEventListener('click',()=>{ const q=$('#chat-question'); if(!q)return; q.value='请结合这篇论文的 NotebookLM audio deep dive，用中文总结音频里最值得注意的研究点，并指出和我的 PhD 方向的关系。'; q.focus(); }); box.querySelector('[data-generate-audio]')?.addEventListener('click',startNotebookAudioJob); }
function selectPaper(p){ state.paper=p; state.lastNoteDraft=null; state.selectedVisual=null; const noteEditor=$('#reading-note-editor'); if(noteEditor) noteEditor.value=''; const url=new URL(location.href); url.searchParams.set('id',p.paper_id); history.replaceState(null,'',url); $('#ai-paper-header').innerHTML=`<p class="eyebrow">${esc(p.topic_slug||'paper')} · ${esc(p.display_venue||p.venue||p.source_label||'')}</p><h1>${esc(p.title)}</h1><p>${esc((p.authors||[]).join(', '))}</p><div class="tag-row">${(p.tags||[]).slice(0,8).map(t=>`<em>${esc(t)}</em>`).join('')}</div>`; const pdf=pdfUrl(p); loadPdfPreview(p); $('#open-source').href=p.source_url||pdf||'#'; $('#pdf-status').textContent=p.local_document?'local synced PDF':(pdf?'rendered same-origin PDF':'no PDF found'); $('#synced-note').innerHTML=noteHtml(p); renderFigureGallery(p); renderAudioPanel(p); const tldr=$('#insight-tldr'); if(tldr) tldr.textContent=short(summaryOf(p),260); const score=$('#insight-score'); if(score) score.textContent=scoreFor(p); const nov=$('#insight-novelty'); if(nov) nov.textContent=noveltyFor(p); const meta=$('#insight-meta'); if(meta) meta.innerHTML=`<span>${esc(metaLine(p)||'No venue')}</span><span>${esc((p.tags||[]).slice(0,2).join(' · ')||p.topic_slug||'paper')}</span>`; $$('.ai-paper-item').forEach(el=>el.classList.toggle('active',el.dataset.id===p.paper_id)); }
function renderAiList(){ renderTaxonomy(); }
function setReadingView(view){ const pdf=$('#pdf-frame'), canvas=$('.reading-canvas'), note=$('#synced-note'), visuals=$('#visuals-panel'), audio=$('#audio-panel'); const showPdf=view==='pdf'; const showNote=view==='note'; const showFigures=view==='figures'; const showAudio=view==='audio'; if(canvas) canvas.classList.toggle('hidden',!showPdf); if(pdf) pdf.classList.toggle('hidden',!showPdf); if(note) note.classList.toggle('hidden',!showNote); if(visuals) visuals.classList.toggle('hidden',!showFigures); if(audio) audio.classList.toggle('hidden',!showAudio); $('#show-pdf')?.classList.toggle('active',showPdf); $('#show-note')?.classList.toggle('active',showNote); $('#show-figures')?.classList.toggle('active',showFigures); $('#show-audio')?.classList.toggle('active',showAudio); }
async function extractCurrentFigures(){ if(!state.paper){ addBubble('assistant','先选择一篇论文。'); return; } const btn=$('#extract-current-figures'); if(btn) btn.disabled=true; const box=$('#figure-gallery'); if(box) box.innerHTML='<div class="empty-mini">Extracting figures from current PDF…</div>'; try{ const res=await fetch('/api/figures/extract',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({paper_key:state.paper.paper_id})}); const data=await res.json(); if(!res.ok) throw new Error(data.message||data.error||'extract failed'); state.paper.figures=data.figures||[]; const idx=state.papers.findIndex(p=>p.paper_id===state.paper.paper_id); if(idx>=0) state.papers[idx].figures=state.paper.figures; renderFigureGallery(state.paper); addBubble('assistant',`已提取 ${state.paper.figures.length} 个图表/表格；点击 Figures 里的 “Use in chat” 就能把图表加入下一次提问上下文。`); }catch(err){ if(box) box.innerHTML=`<div class="empty-mini">Extract failed: ${esc(err.message||err)}</div>`; addBubble('error',`Figure extraction failed: ${err.message||err}`); } finally{ if(btn) btn.disabled=false; } }
async function startNotebookAudioJob(){ if(!state.paper){ addBubble('assistant','先选择一篇论文。'); return; } const btn=$('[data-generate-audio]'); if(btn) btn.disabled=true; addBubble('assistant','已启动 NotebookLM 中文 Deep Dive 音频生成。这个任务通常需要几分钟；生成完成后刷新页面或回到 Audio tab 播放。'); try{ const res=await fetch('/api/admin/jobs',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({action:'notebooklm-audio',paper_key:state.paper.paper_id})}); const data=await res.json(); if(!res.ok) throw new Error(data.message||data.error||'audio job failed'); addBubble('assistant',`NotebookLM audio job queued: ${data.job_id}. 你可以在 Admin / Sync Dashboard 查看日志。`); }catch(err){ addBubble('error',`NotebookLM audio job failed: ${err.message||err}`); } finally{ if(btn) btn.disabled=false; } }
function setupAi(){ fillFilters('ai-'); renderTaxonomy(); ['ai-paper-search','ai-topic-filter','ai-source-filter','ai-tag-filter'].forEach(id=>document.getElementById(id)?.addEventListener('input',()=>{ if(id!=='ai-paper-search'){ state.statusFilter=''; state.taxonomyMode='all'; state.taxonomyValue=''; renderTaxonomy(); } renderAiList(); })); $('#show-pdf')?.addEventListener('click',()=>setReadingView('pdf')); $('#pdf-prev-page')?.addEventListener('click',()=>changePdfPage(-1)); $('#pdf-next-page')?.addEventListener('click',()=>changePdfPage(1)); $('#pdf-zoom-in')?.addEventListener('click',()=>zoomPdf(.1)); $('#pdf-zoom-out')?.addEventListener('click',()=>zoomPdf(-.1)); $('#show-note')?.addEventListener('click',()=>setReadingView('note')); $('#show-figures')?.addEventListener('click',()=>setReadingView('figures')); $('#show-audio')?.addEventListener('click',()=>setReadingView('audio')); $('#extract-current-figures')?.addEventListener('click',extractCurrentFigures); $('#send-note-to-chat')?.addEventListener('click',()=>{ const note=($('#reading-note-editor')?.value||'').trim(); const q=$('#chat-question'); if(!note||!q)return; q.value=`结合我的阅读笔记回答：${note}`; q.focus(); }); $('#save-reading-note')?.addEventListener('click',()=>{ const note=($('#reading-note-editor')?.value||'').trim(); if(!note){ addBubble('assistant','先在 Reading Notes 里写一点笔记，再保存到 Notion。'); return; } state.lastNoteDraft={question:'Reading note',answer:note,paper_key:state.paper?.paper_id}; showNoteConfirmation({destination:'AI Note',mode:'append'}); }); renderAiList(); }
function addBubble(role,text){ const log=$('#chat-log'); if(!log)return; log.insertAdjacentHTML('beforeend',`<div class="bubble ${role}">${esc(text)}</div>`); log.scrollTop=log.scrollHeight; }
function addThinkingBubble(){ const log=$('#chat-log'); if(!log)return null; log.insertAdjacentHTML('beforeend',`<div class="bubble assistant model-thinking" data-thinking-bubble><span></span><span></span><span></span><em>Model is thinking… reading the PDF context</em></div>`); log.scrollTop=log.scrollHeight; return log.lastElementChild; }
function removeThinkingBubble(el){ el?.remove(); }
function setNoteDraft(question,answer){ state.lastNoteDraft={question,answer,paper_key:state.paper?.paper_id}; }
function detectNotionIntent(text){ const t=String(text||'').toLowerCase(); if(!/(notion|保存|写进|写入|更新|追加|存到|save|append|update)/i.test(t)) return null; let destination='AI Note', mode='append'; if(/phd|博士|relevance|相关/.test(t)){ destination='PhD Relevance'; mode='property'; } else if(/related work|引用/.test(t)){ destination='Related Work'; mode='append'; } else if(/tldr|一句话/.test(t)){ destination='TLDR'; mode='property'; } else if(/中文|速览|brief/.test(t)){ destination='Chinese Brief'; mode='property'; } else if(/方法|method/.test(t)){ destination='Method'; mode='property'; } else if(/结果|results?/.test(t)){ destination='Results'; mode='property'; } else if(/局限|limitations?/.test(t)){ destination='Limitations'; mode='property'; } if(/追加|append|note|笔记/.test(t)) mode='append'; return {destination,mode}; }
function noteConfirmHtml(intent){ return `<div class="note-confirm" data-note-confirm><strong>准备写入 Notion</strong><span>${esc(intent.destination)} · ${esc(intent.mode==='property'?'Update field':'Append note')}</span><p>我会使用上一条 AI 回答作为内容。确认后才会写入 Notion。</p><div><button class="confirm-note-save" data-confirm-note-save>Confirm save</button><button class="cancel-note-save" data-cancel-note-save>Cancel</button></div></div>`; }
async function saveCurrentNote(intent){ if(!state.lastNoteDraft||!state.paper){ addBubble('assistant','还没有可保存的 AI 回答。先问我一个关于当前论文的问题，再说“保存到 Notion”。'); return; } const payload={...state.lastNoteDraft,paper_key:state.paper.paper_id,destination:intent.destination||'AI Note',mode:intent.mode||'append'}; addBubble('assistant',`Saving to Notion… ${payload.destination}`); try{ const res=await fetch('/api/notes/save',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)}); const data=await res.json(); if(!res.ok) throw new Error(data.message||data.error||'save failed'); addBubble('assistant',`Saved to Notion ✓ ${data.destination||payload.destination} · ${data.mode||payload.mode}`); }catch(err){ addBubble('error',`Save failed: ${err.message||err}`); } }
function showNoteConfirmation(intent){ const log=$('#chat-log'); if(!log)return; log.insertAdjacentHTML('beforeend',`<div class="bubble assistant">${noteConfirmHtml(intent)}</div>`); const bubble=log.lastElementChild; log.scrollTop=log.scrollHeight; bubble?.querySelector('[data-confirm-note-save]')?.addEventListener('click',()=>saveCurrentNote(intent)); bubble?.querySelector('[data-cancel-note-save]')?.addEventListener('click',e=>{ e.currentTarget.closest('.bubble')?.remove(); }); }
async function loadModelPresets(){
  const preset=$('#chat-model-preset');
  if(!preset) return;
  try{
    const res=await fetch('/api/models',{cache:'no-store'});
    if(!res.ok) throw new Error('models api unavailable');
    const cfg=await res.json();
    const presets=(cfg.presets||[]).filter(p=>p.enabled!==false);
    if(presets.length){
      preset.innerHTML=presets.map(p=>`<option value="${esc(p.value)}" ${p.has_key?'':'disabled'}>${esc(p.label||`${p.provider_label} · ${p.model}`)}${p.has_key?'':' · key missing'}</option>`).join('');
      const defaultValue=cfg.defaults?.chat_value || presets.find(p=>p.has_key)?.value || presets[0].value;
      if([...preset.options].some(o=>o.value===defaultValue && !o.disabled)) preset.value=defaultValue;
      else if(presets.find(p=>p.has_key)) preset.value=presets.find(p=>p.has_key).value;
      state.modelConfig=cfg;
    }
  }catch(err){
    console.warn('Using built-in model preset fallback:', err);
  }
}
function syncModelPreset(){ const preset=$('#chat-model-preset'); if(!preset)return; const [provider,model]=String(preset.value||'deepseek|deepseek-v4-flash').split('|'); if($('#chat-provider')) $('#chat-provider').value=provider||'deepseek'; if($('#chat-model')) $('#chat-model').value=model||'deepseek-v4-flash'; }
function fileToChatAttachment(file){ return new Promise((resolve,reject)=>{ const isPdf=/pdf/i.test(file.type||file.name); const reader=new FileReader(); reader.onerror=()=>reject(reader.error||new Error('file read failed')); reader.onload=()=>{ const result=String(reader.result||''); if(isPdf){ resolve({name:file.name,type:file.type||'application/pdf',size:file.size,data_base64:result.split(',').pop()||''}); } else { resolve({name:file.name,type:file.type||'text/plain',size:file.size,text:result.slice(0,120000)}); } }; if(isPdf) reader.readAsDataURL(file); else reader.readAsText(file); }); }
function renderUploadChips(){ const box=$('#upload-chip-row'); if(!box)return; box.innerHTML=state.uploadedFiles.map((f,i)=>`<button type="button" class="upload-chip" data-remove-upload="${i}" title="Temporary file: cleared when this tab/session ends"><span>📎</span>${esc(f.name)}<em>×</em></button>`).join(''); $$('[data-remove-upload]').forEach(btn=>btn.addEventListener('click',()=>{ state.uploadedFiles.splice(Number(btn.dataset.removeUpload),1); renderUploadChips(); })); }
async function handleFileInput(files){ const incoming=Array.from(files||[]).slice(0,6); if(!incoming.length)return; const converted=[]; for(const file of incoming){ if(file.size>15*1024*1024){ addBubble('assistant',`${file.name} 太大了，暂时跳过（上限 15MB，避免把会话 payload 撑爆）。`); continue; } converted.push(await fileToChatAttachment(file)); } state.uploadedFiles=[...state.uploadedFiles,...converted].slice(0,6); renderUploadChips(); if(converted.length) addBubble('assistant',`已临时附加 ${converted.length} 个文件。它们只保存在当前浏览器 tab 内，关闭/刷新页面后会清空。`); }
window.addEventListener('pagehide',()=>{ state.uploadedFiles=[]; });
function setupChat(){ const form=$('#chat-form'); if(!form)return; syncModelPreset(); $('#chat-model-preset')?.addEventListener('change',syncModelPreset); $('#chat-file-input')?.addEventListener('change',async e=>{ try{ await handleFileInput(e.target.files); e.target.value=''; }catch(err){ addBubble('error',`File upload failed: ${err.message||err}`); } }); $('#web-search-toggle')?.addEventListener('click',e=>{ state.webSearch=!state.webSearch; e.currentTarget.classList.toggle('active',state.webSearch); e.currentTarget.setAttribute('aria-pressed',String(state.webSearch)); addBubble('assistant',state.webSearch?'联网搜索已开启：下一次提问会附加实时网页搜索结果。':'联网搜索已关闭。'); }); $$('.prompt-chip').forEach(b=>b.addEventListener('click',()=>{ $('#chat-question').value=b.dataset.prompt||b.textContent; $('#chat-question').focus(); })); form.addEventListener('submit',async e=>{ e.preventDefault(); syncModelPreset(); const q=($('#chat-question')?.value||'').trim(); if(!q)return; $('[data-chat-starters]')?.classList.add('hidden'); addBubble('user',q); $('#chat-question').value=''; const notionIntent=detectNotionIntent(q); if(notionIntent){ showNoteConfirmation(notionIntent); return; } let thinking=null; try{ thinking=addThinkingBubble(); const body={question:q,provider_id:$('#chat-provider')?.value||'deepseek',model:$('#chat-model')?.value||'deepseek-v4-flash',mode:state.paper?'full_pdf':'library',max_tokens:state.paper?3200:4000,max_fulltext_chars:200000,attachments:state.uploadedFiles,web_search:state.webSearch}; if(state.paper) body.paper_key=state.paper.paper_id; const readingNote=($('#reading-note-editor')?.value||'').trim(); if(readingNote) body.reading_note=readingNote; if(state.selectedVisual) body.selected_visual=state.selectedVisual; const res=await fetch('/api/chat',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)}); const data=await res.json(); if(!res.ok) throw new Error(data.message||data.error||'chat failed'); const answer=data.answer||'No answer returned.'; removeThinkingBubble(thinking); addBubble('assistant',answer); setNoteDraft(q,answer); }catch(err){ addBubble('error',`Error: ${err.message||err}`); } }); }
function isImageAsset(f){ return /\.(png|jpe?g|webp|gif)$/i.test(String(f?.src||'')); }
function ensureFigureViewer(){
  let viewer=$('#figure-viewer');
  if(viewer) return viewer;
  document.body.insertAdjacentHTML('beforeend',`<div id="figure-viewer" class="figure-viewer hidden" role="dialog" aria-modal="true" aria-label="Figure viewer"><div class="viewer-backdrop" data-viewer-close></div><section class="viewer-stage"><header class="viewer-top"><div><strong data-viewer-title>Figure</strong><span data-viewer-meta></span></div><button class="tiny" data-viewer-close>Close</button></header><div class="viewer-canvas" data-viewer-canvas></div><footer class="viewer-controls"><button class="tiny" id="viewer-prev">← Prev</button><div class="viewer-pagination"><span data-viewer-page>1 / 1</span><div class="viewer-dots" data-viewer-dots></div></div><button class="tiny" id="viewer-next">Next →</button><span class="viewer-sep"></span><button class="tiny" id="viewer-zoom-out">−</button><strong data-viewer-zoom>100%</strong><button class="tiny" id="viewer-zoom-in">＋</button><button class="tiny" id="viewer-zoom-reset">Reset</button><button class="tiny ghost" id="viewer-use-chat">Use in chat</button></footer></section></div>`);
  viewer=$('#figure-viewer');
  viewer.querySelectorAll('[data-viewer-close]').forEach(el=>el.addEventListener('click',closeFigureViewer));
  $('#viewer-prev')?.addEventListener('click',()=>stepFigureViewer(-1));
  $('#viewer-next')?.addEventListener('click',()=>stepFigureViewer(1));
  $('#viewer-zoom-out')?.addEventListener('click',()=>zoomFigureViewer(-0.2));
  $('#viewer-zoom-in')?.addEventListener('click',()=>zoomFigureViewer(0.2));
  $('#viewer-zoom-reset')?.addEventListener('click',()=>{ state.viewerZoom=1; renderFigureViewer(); });
  $('#viewer-use-chat')?.addEventListener('click',()=>useFigureInChat(state.viewerIndex));
  window.addEventListener('keydown',e=>{ if(viewer.classList.contains('hidden')) return; if(e.key==='Escape') closeFigureViewer(); if(e.key==='ArrowLeft') stepFigureViewer(-1); if(e.key==='ArrowRight') stepFigureViewer(1); if(e.key==='+'||e.key==='=') zoomFigureViewer(0.2); if(e.key==='-') zoomFigureViewer(-0.2); });
  return viewer;
}
function currentFigures(){ return Array.isArray(state.paper?.figures)?state.paper.figures:[]; }
function openFigureViewer(index){ state.viewerIndex=Number(index)||0; state.viewerZoom=1; ensureFigureViewer().classList.remove('hidden'); renderFigureViewer(); }
function closeFigureViewer(){ $('#figure-viewer')?.classList.add('hidden'); }
function stepFigureViewer(delta){ const figures=currentFigures(); if(!figures.length) return; state.viewerIndex=(state.viewerIndex+delta+figures.length)%figures.length; state.viewerZoom=1; renderFigureViewer(); }
function zoomFigureViewer(delta){ state.viewerZoom=Math.max(0.5,Math.min(3,state.viewerZoom+delta)); renderFigureViewer(); }
function useFigureInChat(index){ const fig=currentFigures()[Number(index)]; if(!fig)return; state.selectedVisual=fig; addBubble('assistant',`已把 ${fig.title||'这个图表'} 加入下一次提问的上下文。你可以问：这张图说明了什么？`); const q=$('#chat-question'); if(q){ q.value=q.value||'结合选中的图表和我的阅读笔记解释这部分。'; q.focus(); } }
function renderFigureViewer(){
  const viewer=ensureFigureViewer(), figures=currentFigures(), fig=figures[state.viewerIndex]; if(!fig) return;
  const title=fig.title||`${fig.kind||'asset'} ${state.viewerIndex+1}`;
  viewer.querySelector('[data-viewer-title]').textContent=title;
  viewer.querySelector('[data-viewer-meta]').textContent=`${state.viewerIndex+1} / ${figures.length} · Page ${fig.page||'—'} · ${fig.kind||'visual'}`;
  viewer.querySelector('[data-viewer-page]').textContent=`${state.viewerIndex+1} / ${figures.length}`;
  viewer.querySelector('[data-viewer-zoom]').textContent=`${Math.round(state.viewerZoom*100)}%`;
  viewer.querySelector('[data-viewer-dots]').innerHTML=figures.map((_,i)=>`<button class="viewer-dot ${i===state.viewerIndex?'active':''}" data-viewer-jump="${i}" aria-label="Go to visual ${i+1}"></button>`).join('');
  viewer.querySelectorAll('[data-viewer-jump]').forEach(btn=>btn.addEventListener('click',()=>{ state.viewerIndex=Number(btn.dataset.viewerJump); state.viewerZoom=1; renderFigureViewer(); }));
  const canvas=viewer.querySelector('[data-viewer-canvas]');
  const caption=fig.caption?`<p>${esc(fig.caption)}</p>`:'';
  if(isImageAsset(fig)) canvas.innerHTML=`<div class="viewer-image-wrap"><img src="${esc(fig.src)}" alt="${esc(title)}" style="transform:scale(${state.viewerZoom})" /></div>${caption}`;
  else { const rows=(fig.preview||[]).slice(0,12).map(row=>`<tr>${row.slice(0,8).map(cell=>`<td>${esc(cell)}</td>`).join('')}</tr>`).join(''); canvas.innerHTML=`<div class="viewer-table-wrap" style="transform:scale(${state.viewerZoom})"><table>${rows}</table></div>${caption}`; }
}
function renderFigureGallery(p){ const box=$('#figure-gallery'), count=$('#figure-count'); if(!box) return; const figures=Array.isArray(p.figures)?p.figures:[]; if(count) count.textContent=String(figures.length); if(!figures.length){ box.innerHTML='<div class="empty-mini">No extracted figures yet. Run Admin → Fulltext + regenerate after PDFs are synced.</div>'; return; } box.innerHTML=figures.map((f,i)=>{ const title=esc(f.title||`${f.kind||'asset'} ${i+1}`); const caption=esc(f.caption||''); const action=`<button class="tiny use-visual" data-visual-idx="${i}">Use in chat</button>`; const rows=(f.preview||[]).slice(0,4).map(row=>`<tr>${row.slice(0,4).map(cell=>`<td>${esc(cell)}</td>`).join('')}</tr>`).join(''); const thumb=isImageAsset(f)?`<button class="visual-thumb" data-open-visual="${i}" aria-label="Open ${title}"><img src="${esc(f.src)}" loading="lazy" alt="${title}" /></button>`:`<button class="visual-thumb table-thumb" data-open-visual="${i}" aria-label="Open ${title}"><table>${rows}</table><span>Open enlarged table</span></button>`; return `<article class="figure-card" data-open-visual="${i}">${thumb}<div class="figure-card-head"><strong>${title}</strong>${action}</div><small>Page ${esc(f.page||'—')} · ${esc(f.kind||'visual')}</small><p>${caption}</p></article>`; }).join(''); $$('[data-open-visual]').forEach(el=>el.addEventListener('click',e=>{ if(e.target.closest('.use-visual')) return; openFigureViewer(el.dataset.openVisual); })); $$('.use-visual').forEach(btn=>btn.addEventListener('click',e=>{ e.stopPropagation(); useFigureInChat(btn.dataset.visualIdx); })); }
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

async function init(){ renderNav(); await loadPapers(); await loadModelPresets(); setupChat(); setupRanking(); if(page==='discovery'){renderMetrics();renderDiscovery();} if(page==='library'){fillFilters('');renderLibrary();['search','topic-filter','source-filter','tag-filter'].forEach(id=>document.getElementById(id)?.addEventListener('input',renderLibrary));} if(page==='ai') setupAi(); if(page==='paper') renderPaperPage(); setupAdmin(); }
init().catch(err=>{ console.error(err); document.body.insertAdjacentHTML('afterbegin',`<pre class="fatal">${esc(err.message||err)}</pre>`); });
