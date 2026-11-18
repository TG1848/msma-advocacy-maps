// Shared helpers for MSMA Advocacy Maps
(function(){
  const CH = {house:'State House', senate:'State Senate'};
  const TITLE = {house:'Rep.', senate:'Sen.'};
  const PARTY = {R:'Republican', D:'Democrat'};
  const COLOR = {R:{I:'#b71c1c',N:'#ef8f8f'}, D:{I:'#1a4f9c',N:'#8db4ea'}};
  const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  function all(){
    const out=[];
    for (const k of ['senate','house']) for (const [id,m] of Object.entries(window.LEG[k])) out.push({k,id:Number(id),...m});
    return out;
  }
  function contactLink(k,id){ return k==='house' ? `https://house.mo.gov/MemberDetails.aspx?district=${String(id).padStart(3,'0')}` : `https://www.senate.mo.gov/DistrictWebApplication/Contact?DistrictNumber=${id}`; }

  // ---- Live data (office, phone, email, committees, filed bills) updated nightly from official sources
  let LIVE = {house:{}, senate:{}}, STATUS = {};
  const liveReady = Promise.all([
    fetch('data/live.json', {cache:'no-cache'}).then(r => r.ok ? r.json() : null).catch(() => null),
    fetch('data/status.json', {cache:'no-cache'}).then(r => r.ok ? r.json() : null).catch(() => null)
  ]).then(([l, s]) => { if (l) LIVE = l; if (s) STATUS = s; stamp(); return LIVE; });
  function liveFor(k, id){ return (LIVE[k] || {})[String(id)] || null; }
  function stamp(){
    const el = document.getElementById('liveStamp'); if (!el) return;
    const parts = [];
    if (LIVE.updated_display) parts.push(`Office, committee and bill information last changed ${LIVE.updated_display}.`);
    if (STATUS.checked_display && ((STATUS.house||{}).ok || (STATUS.senate||{}).ok)) parts.push(`Checked against official sources ${STATUS.checked_display}.`);
    el.textContent = parts.length ? parts.join(' ') : 'Office, committee and bill information updates automatically from official Missouri House and Senate sources.';
  }
  const PENDING = 'Capitol office, committee assignments and filed bills appear here automatically once they are published: bills can be prefiled starting December 1, 2026, and committees and offices are set when the session opens in January 2027.';
  function liveBlock(k, id, opts = {}){
    const L = liveFor(k, id), max = opts.maxBills ?? 8;
    if (!L) return `<p class="pending">${PENDING}</p>`;
    const comm = (L.committees || []).map(c => `<li>${esc(c.name)}${c.position && !/^member$/i.test(c.position) ? ` <span class="pos">${esc(c.position)}</span>` : ''}</li>`).join('');
    const bills = (L.bills || []).slice(0, max).map(b => `<li><a href="${esc(b.url)}" target="_blank" rel="noopener"><strong>${esc(b.id)}</strong></a> ${esc(b.title)}</li>`).join('');
    const more = (L.bills || []).length > max ? `<li><a href="${esc(L.page)}" target="_blank" rel="noopener">See all ${(L.bills||[]).length} bills on the official page →</a></li>` : '';
    return `<dl class="kv live">
      ${L.office ? `<dt>Capitol office</dt><dd>${esc(L.office)}</dd>` : ''}
      ${L.phone ? `<dt>Phone</dt><dd><a href="tel:${esc(L.phone.replace(/[^0-9+]/g,''))}">${esc(L.phone)}</a></dd>` : ''}
      ${L.email ? `<dt>Email</dt><dd><a href="mailto:${esc(L.email)}">${esc(L.email)}</a></dd>` : ''}
      <dt>Committees</dt><dd>${comm ? `<ul class="plain">${comm}</ul>` : `<span class="muted">${L.contact_from_session ? '2027 committee assignments are announced in January' : 'Not yet assigned'}</span>`}</dd>
      <dt>Bills filed (${(L.bills||[]).length})</dt><dd>${bills ? `<ul class="plain bills">${bills}${more}</ul>` : `<span class="muted">${L.contact_from_session ? '2027 bills appear here once filing opens (prefiling starts Dec. 1)' : 'None filed yet'}</span>`}${L.cosponsored ? `<div class="muted" style="font-size:13px">Co-sponsor on ${L.cosponsored} other bill${L.cosponsored>1?'s':''}</div>` : ''}</dd>
    </dl>`;
  }
  function mapLink(k,id){ return `map.html#${k}-${id}`; }
  function badges(m){
    return `<span class="badge ${m.party}">${PARTY[m.party]}</span><span class="badge ${m.status}">${m.status==='N'?'Newly elected (N)':'Incumbent (I)'}</span>${m.role?`<span class="badge lead">★ ${esc(m.role)}</span>`:''}`;
  }
  function personCard(m){
    return `<a class="person ${m.party}" href="${mapLink(m.k,m.id)}"><strong>${TITLE[m.k]} ${esc(m.name)}</strong><div class="meta">${CH[m.k]} District ${m.id} · ${esc(m.counties)}</div>${badges(m)}</a>`;
  }
  function countyKey(s){ return s.replace(/\s*\(part\)\s*/i,'').trim().toLowerCase(); }
  function search(q){
    q=q.trim().toLowerCase(); if(!q) return [];
    const num = /^\d+$/.test(q) ? Number(q) : null;
    return all().filter(m => {
      if (num!==null) return m.id===num;
      if (m.name.toLowerCase().includes(q)) return true;
      if ((m.role||'').toLowerCase().includes(q)) return true;
      return m.counties.split(/,\s*/).some(c => {const k=countyKey(c); return k.startsWith(q) || (k+' county').startsWith(q) || (q.endsWith(' county') && k===q.replace(/ county$/,''));});
    }).sort((a,b)=> (a.k===b.k?0:a.k==='senate'?-1:1) || a.id-b.id);
  }
  window.MSMA = {get LIVE(){return LIVE}, liveReady, liveFor, liveBlock, PENDING, contactLink, CH, TITLE, PARTY, COLOR, esc, all, mapLink, badges, personCard, search};
})();
