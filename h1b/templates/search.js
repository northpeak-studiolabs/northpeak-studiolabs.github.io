(function(){
  var box=document.getElementById('q'),out=document.getElementById('results');
  if(!box)return;
  var base=box.getAttribute('data-base'),idx=null,loading=false,sel=-1,waiting=[];
  var kinds={e:['employer','Employer'],t:['title','Job title'],c:['city','City']};
  function load(cb){if(idx)return cb();waiting=[cb];if(loading)return;loading=true;
    fetch(base+'/search.json').then(function(r){return r.json()}).then(function(j){
      idx=[];for(var k in kinds)(j[k]||[]).forEach(function(a){idx.push([a[0],a[0].toLowerCase(),kinds[k][0]+'/'+a[1]+'/',kinds[k][1],a[2]])});waiting.forEach(function(f){f()});waiting=[];}).catch(function(){loading=false});}
  function esc(s){return s.replace(/[&<>"]/g,function(c){return{'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]})}
  function run(){var q=box.value.trim().toLowerCase();sel=-1;if(q.length<2){out.innerHTML='';return}
    load(function(){var terms=q.split(/\s+/),hits=[];
      for(var i=0;i<idx.length;i++){var it=idx[i],ok=true;for(var t=0;t<terms.length;t++)if(it[1].indexOf(terms[t])<0){ok=false;break}
        if(ok)hits.push([(it[1].indexOf(q)===0?1e7:0)+it[4],it])}
      hits.sort(function(a,b){return b[0]-a[0]});
      out.innerHTML=hits.slice(0,12).map(function(h){var it=h[1];return '<li><a href="'+base+'/'+it[2]+'"><span>'+esc(it[0])+'</span><em>'+it[3]+' · '+it[4].toLocaleString()+' filings</em></a></li>'}).join('')||'<li><a href="#" onclick="return false"><span>No matches</span></a></li>';});}
  box.addEventListener('input',run);box.addEventListener('focus',function(){load(function(){})});
  box.addEventListener('keydown',function(e){var a=out.querySelectorAll('a');if(!a.length)return;
    if(e.key==='ArrowDown'||e.key==='ArrowUp'){e.preventDefault();if(sel>=0)a[sel].classList.remove('on');sel=(sel+(e.key==='ArrowDown'?1:-1)+a.length)%a.length;a[sel].classList.add('on')}
    else if(e.key==='Enter'){location.href=a[sel<0?0:sel].href}});
})();
