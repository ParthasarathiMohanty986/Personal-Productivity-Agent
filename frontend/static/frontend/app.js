'use strict';
const $ = (s, root = document) => root.querySelector(s);
const $$ = (s, root = document) => [...root.querySelectorAll(s)];
const zone = document.body.dataset.timezone;
let tasks = [], goals = [], plans = [], currentPage = 'dashboard', noticeTimer;
const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const empty = text => `<div class="empty"><span class="empty-symbol">◎</span>${esc(text)}</div>`;
const fmt = value => value ? new Intl.DateTimeFormat('en-IN', {timeZone:zone, month:'short',day:'numeric',hour:'2-digit',minute:'2-digit'}).format(new Date(value)) : 'No deadline';
function dateKey(value = new Date()) {
  const parts = Object.fromEntries(new Intl.DateTimeFormat('en-CA', {timeZone:zone,year:'numeric',month:'2-digit',day:'2-digit'}).formatToParts(new Date(value)).map(p => [p.type,p.value]));
  return `${parts.year}-${parts.month}-${parts.day}`;
}
function localInput(value) {
  if (!value) return '';
  const parts = Object.fromEntries(new Intl.DateTimeFormat('en-CA', {timeZone:zone,year:'numeric',month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit',hourCycle:'h23'}).formatToParts(new Date(value)).map(p => [p.type,p.value]));
  return `${parts.year}-${parts.month}-${parts.day}T${parts.hour}:${parts.minute}`;
}
function zonedISO(value) {
  if (!value) return null;
  const target = Date.parse(value + ':00Z');
  let instant = target;
  for (let i=0;i<3;i++) {
    const rendered = Date.parse(localInput(new Date(instant)) + ':00Z');
    instant += target-rendered;
  }
  if (localInput(new Date(instant)) !== value) throw new Error('This local time does not exist in the configured timezone.');
  return new Date(instant).toISOString();
}
function notify(message, error=false) {
  const node = $('#notice'); node.textContent=message; node.className=error?'error':''; node.hidden=false;
  clearTimeout(noticeTimer); noticeTimer=setTimeout(()=>node.hidden=true,error?10000:4500);
}
async function api(path, options={}) {
  const csrf = document.cookie.split('; ').find(x=>x.startsWith('csrftoken='))?.split('=')[1];
  const response = await fetch(path,{...options,headers:{'Content-Type':'application/json','X-CSRFToken':csrf||'','X-Productivity-UI':'1',...options.headers},credentials:'same-origin'});
  const data = response.status===204 ? null : await response.json().catch(()=>({detail:'Unexpected server response.'}));
  if(!response.ok) throw new Error(typeof data?.detail==='string'?data.detail:JSON.stringify(data));
  return data;
}
async function all(path) {
  let items=[], next=path;
  while(next){ const data=await api(next); if(Array.isArray(data)) return data; items.push(...data.results); next=data.next; }
  return items;
}
async function busy(button, fn) {
  const old=button.textContent; button.disabled=true;button.textContent='Working…';
  try{return await fn();} catch(error){notify(error.message,true);} finally{button.disabled=false;button.textContent=old;}
}
async function confirmAction(title, copy) {
  const dialog=$('#confirm-dialog');$('#confirm-title').textContent=title;$('#confirm-copy').textContent=copy;
  dialog.returnValue='cancel';dialog.showModal();
  return new Promise(resolve=>dialog.addEventListener('close',()=>resolve(dialog.returnValue==='confirm'),{once:true}));
}
function taskRow(t, compact=false) {
  return `<div class="task-row"><button class="task-check ${t.status==='completed'?'done':''}" data-complete="${t.id}" aria-label="${t.status==='completed'?'Reopen':'Complete'} ${esc(t.title)}">${t.status==='completed'?'✓':''}</button><div class="task-main"><div class="task-title">${esc(t.title)}</div><div class="task-meta">#${t.id} · ${esc(t.category||t.status.replace('_',' '))} · ${esc(fmt(t.deadline))}${t.estimated_minutes?' · '+t.estimated_minutes+' min':''}</div></div><span class="priority ${t.priority}">${t.priority}</span>${compact?'':`<div class="task-actions"><button class="text-button" data-edit-task="${t.id}">Edit</button><button class="text-button danger" data-delete-task="${t.id}">Delete</button></div>`}</div>`;
}
function statsHTML(s) {
  return [['Open tasks',s.total-s.completed-(s.status_distribution.cancelled||0),'A clear next step',''],['Completed',s.completed,'Every step counts',''],['Overdue',s.overdue,'Time to reassess','warn'],['Completion',s.completion_rate+'%','Excludes cancelled tasks','']].map(([label,value,foot,cls])=>`<div class="stat ${cls}"><div class="stat-label">${label}<span>↗</span></div><div class="stat-value">${value}</div><div class="stat-foot">${foot}</div></div>`).join('');
}
async function refresh() {
  [tasks,goals,plans]=await Promise.all([all('/api/tasks/'),all('/api/goals/'),all('/api/agent/plans/')]);
  await renderPage();
}
async function renderPage() {
  if(currentPage==='dashboard') {
    const s=await api('/api/analytics/summary/');$('#dashboard-stats').innerHTML=statsHTML(s);
    const scheduled=new Set(plans.filter(p=>p.status==='approved').flatMap(p=>(p.proposal.blocks||[]).filter(b=>dateKey(b.start)===dateKey()).map(b=>b.task_id)));
    const active=tasks.filter(t=>['pending','in_progress'].includes(t.status));
    const today=active.filter(t=>scheduled.has(t.id)||(t.deadline&&dateKey(t.deadline)===dateKey()));
    $('#today-tasks').innerHTML=today.slice(0,6).map(t=>taskRow(t,true)).join('')||empty('Nothing scheduled for today. Add a task or make a plan.');
    const upcoming=active.filter(t=>t.deadline).sort((a,b)=>new Date(a.deadline)-new Date(b.deadline)).slice(0,5);
    $('#upcoming-tasks').innerHTML=upcoming.map(t=>taskRow(t,true)).join('')||empty('Your upcoming deadlines will appear here.');
    $('#progress-copy').textContent=s.facts;$('#progress-bar').style.width=s.completion_rate+'%';$('#progress-value').textContent=s.completion_rate+'%';
  }
  if(currentPage==='tasks') renderTasks();
  if(currentPage==='goals') renderGoals();
  if(currentPage==='planner') renderPlans();
  if(currentPage==='analytics') await renderAnalytics();
  if(currentPage==='activity') {
    const events=await all('/api/activity/');
    $('#activity-list').innerHTML=events.map(e=>`<div class="history-row"><span class="history-dot"></span><div><strong>${esc(e.description)}</strong><p class="muted">${esc(e.action)} · ${esc(e.source)} · ${esc(fmt(e.created_at))}</p></div></div>`).join('')||empty('Your activity history starts with your first task.');
  }
}
async function navigate(page) {
  if(!$('#page-'+page)) page='dashboard';
  currentPage=page;$$('.page').forEach(n=>n.hidden=n.id!=='page-'+page);
  $$('nav button').forEach(n=>n.classList.toggle('active',n.dataset.page===page));
  $('#breadcrumb').textContent=$(`nav [data-page="${page}"]`).textContent.replace('AI','').trim();
  history.replaceState(null,'','#'+page);await renderPage();
}
function renderTasks() {
  const search=$('#search').value.toLowerCase(), status=$('#status-filter').value, priority=$('#priority-filter').value;
  const shown=tasks.filter(t=>(!status||t.status===status)&&(!priority||t.priority===priority)&&`${t.title} ${t.description}`.toLowerCase().includes(search));
  $('#task-list').innerHTML=shown.map(t=>taskRow(t)).join('')||empty('No matching tasks. Create one to get started.');
}
function renderGoals() {
  $('#goal-list').innerHTML=goals.map(g=>{
    const linked=tasks.filter(t=>t.goal===g.id),done=linked.filter(t=>t.status==='completed').length,pct=linked.length?done/linked.length*100:0;
    return `<section class="card goal-card"><span class="badge">${esc(g.status.replace('_',' '))}</span><h2 class="spaced">${esc(g.title)}</h2><p>${esc(g.description||'Make this goal concrete by linking tasks to it.')}</p><p>Target: ${esc(g.target_date||'Not set')}</p><div class="progress"><span style="width:${pct}%"></span></div><small class="muted">${done} of ${linked.length} tasks completed</small><div class="form-footer"><button class="text-button" data-edit-goal="${g.id}">Edit goal</button><button class="text-button danger" data-delete-goal="${g.id}">Delete</button></div></section>`;
  }).join('')||empty('Start with a goal that matters to you.');
}
function planHTML(p) {
  const proposal=p.proposal, blocks=proposal.blocks||[], ops=proposal.operations||[];
  return `<section class="card plan-card"><div class="plan-header"><div><h2>${esc(p.title)}</h2><small class="muted">#${p.id} · Revision ${p.revision} · ${esc(p.start_date)} – ${esc(p.end_date)}</small></div><span class="badge ${p.status}">${p.status}</span></div>${blocks.map(b=>`<div class="schedule-row"><time>${esc(fmt(b.start))}</time><strong>${esc(b.title||tasks.find(t=>t.id===b.task_id)?.title||'Task #'+b.task_id)}</strong><span class="muted">until ${esc(fmt(b.end))}</span></div>`).join('')}${ops.map(o=>`<div class="operation"><strong>${esc(o.kind.replaceAll('_',' '))}${o.task_id?' #'+o.task_id:''}: ${esc(o.data?.title||'')}</strong><pre>${esc(JSON.stringify(o.data||{},null,2))}</pre></div>`).join('')}${(proposal.unscheduled||[]).map(u=>`<div class="warning"><strong>${esc(u.title||'Task #'+u.task_id)}</strong> — ${esc(u.reason)}</div>`).join('')}${(proposal.warnings||[]).map(w=>`<div class="warning">${esc(w)}</div>`).join('')}${proposal.explanation?`<p class="muted">${esc(proposal.explanation)}</p>`:''}${!blocks.length&&!ops.length?'<p class="muted">No changes or schedule blocks in this proposal.</p>':''}<div class="form-footer">${p.status==='draft'?`<div><button class="button primary" data-plan-action="approve" data-id="${p.id}">Approve plan</button> <button class="button secondary" data-plan-action="reject" data-id="${p.id}">Reject</button></div>`:'<span></span>'}${['draft','approved'].includes(p.status)?`<div><button class="text-button" data-edit-plan="${p.id}">Edit proposal</button>${Object.keys(p.constraints).length?`<button class="text-button" data-plan-action="revise" data-id="${p.id}">Recalculate</button>`:''}</div>`:''}</div></section>`;
}
function renderPlans(){ $('#plans-list').innerHTML=plans.map(planHTML).join('')||empty('Your draft plans will appear here.'); }
async function renderAnalytics() {
  const [s,t]=await Promise.all([api('/api/analytics/summary/'),api('/api/analytics/trends/')]);
  $('#analytics-stats').innerHTML=statsHTML(s);const max=Math.max(1,...t.daily.map(d=>d.completed));
  $('#trend-chart').innerHTML=t.daily.map(d=>`<div class="chart-col"><div class="chart-bar" style="height:${Math.max(3,d.completed/max*145)}px" title="${d.date}: ${d.completed} completed"><span class="chart-count">${d.completed}</span></div><span class="chart-label">${d.date.slice(8)}</span></div>`).join('');
  $('#priority-chart').innerHTML=['urgent','high','medium','low'].map(p=>`<div class="breakdown-row"><div><span class="priority ${p}">${p}</span><span>${s.priority_breakdown[p]||0}</span></div><div class="progress"><span style="width:${s.total?(s.priority_breakdown[p]||0)/s.total*100:0}%"></span></div></div>`).join('');
  $('#analytics-facts').textContent=`${s.facts} ${s.postponed_tasks} tasks have recorded deadline extensions. Latest 7 days: ${t.weekly[1].completed} completions; previous 7 days: ${t.weekly[0].completed}.`;
  for(const issue of s.schedule_issues||[]){const line=document.createElement('div');line.className='warning';line.textContent=`Task #${issue.task_id}, plan #${issue.plan_id}: ${issue.reason} Review the plan in Planner.`;$('#analytics-facts').append(line);}
  const d=s.estimated_vs_actual;$('#duration-facts').textContent=d?`For ${d.sample_count} completed tasks with both durations: ${d.estimated_minutes} minutes estimated, ${d.actual_minutes} minutes actual.`:'Add actual durations to completed tasks to compare estimates with time spent.';
}
function openTask(id) {
  const form=$('#task-form');form.reset();$('.form-error',form).textContent='';
  const task=tasks.find(t=>t.id===Number(id));
  form.elements.goal.innerHTML='<option value="">No goal</option>'+goals.map(g=>`<option value="${g.id}">${esc(g.title)}</option>`).join('');
  form.elements.id.value=task?.id||'';
  if(task) for(const key of ['title','description','status','priority','category','estimated_minutes','actual_minutes','goal']) form.elements[key].value=task[key]??'';
  form.elements.deadline.value=localInput(task?.deadline);form.elements.dependencies.value=task?.dependencies.join(', ')||'';
  $('#task-dialog-title').textContent=task?'Edit task':'New task';$('#task-dialog').showModal();
}
function openGoal(id) {
  const form=$('#goal-form');form.reset();$('.form-error',form).textContent='';const goal=goals.find(g=>g.id===Number(id));
  form.elements.id.value=goal?.id||'';if(goal) for(const key of ['title','description','target_date','status']) form.elements[key].value=goal[key]??'';
  $('#goal-dialog').showModal();
}
function formHandler(selector, fn) {
  $(selector).addEventListener('submit',async event=>{
    event.preventDefault();const form=event.currentTarget,button=$('[type=submit]',form),old=button.textContent;button.disabled=true;button.textContent='Saving…';
    const error=$('.form-error',form);if(error)error.textContent='';
    try {await fn(form);}catch(e){if(error)error.textContent=e.message;else notify(e.message,true);}finally{button.disabled=false;button.textContent=old;}
  });
}
formHandler('#task-form',async form=>{
  const data=Object.fromEntries(new FormData(form)),id=data.id;delete data.id;
  data.deadline=zonedISO(data.deadline);for(const k of ['estimated_minutes','actual_minutes','goal'])data[k]=data[k]===''?null:Number(data[k]);
  data.dependencies=data.dependencies?data.dependencies.split(',').map(x=>Number(x.trim())):[];
  await api('/api/tasks/'+(id?id+'/':''),{method:id?'PATCH':'POST',body:JSON.stringify(data)});$('#task-dialog').close();await refresh();notify('Task saved.');
});
formHandler('#goal-form',async form=>{
  const data=Object.fromEntries(new FormData(form)),id=data.id;delete data.id;data.target_date=data.target_date||null;
  await api('/api/goals/'+(id?id+'/':''),{method:id?'PATCH':'POST',body:JSON.stringify(data)});$('#goal-dialog').close();await refresh();notify('Goal saved.');
});
formHandler('#quick-form',async form=>{await api('/api/tasks/',{method:'POST',body:JSON.stringify({title:$('#quick-title').value})});form.reset();await refresh();notify('Task added.');});
formHandler('#plan-form',async form=>{
  const data=Object.fromEntries(new FormData(form));data.daily_minutes=Number(data.daily_minutes);data.weekdays=data.days==='weekdays'?[0,1,2,3,4]:data.days==='weekends'?[5,6]:[0,1,2,3,4,5,6];delete data.days;
  data.task_ids=data.task_ids.trim()?data.task_ids.split(',').map(x=>Number(x.trim())):null;data.busy=data.busy.trim()?JSON.parse(data.busy):[];
  await api('/api/agent/plans/',{method:'POST',body:JSON.stringify(data)});await refresh();notify('Draft generated. Review before approving.');
});
formHandler('#revision-form',async form=>{await api(`/api/agent/plans/${form.elements.id.value}/revise/`,{method:'POST',body:JSON.stringify({proposal:JSON.parse(form.elements.proposal.value)})});$('#revision-dialog').close();await refresh();notify('Revised draft saved.');});
function addMessage(content,role,events) {
  const node=document.createElement('div');node.className='chat-message '+role;
  if(role==='assistant'){const avatar=document.createElement('span');avatar.className='chat-avatar';avatar.textContent='✧';node.append(avatar);}
  const body=document.createElement('div');body.textContent=content;node.append(body);
  if(events?.length){const detail=document.createElement('details'),summary=document.createElement('summary'),pre=document.createElement('pre');summary.textContent='View actual workflow results';pre.textContent=JSON.stringify(events,null,2);detail.append(summary,pre);body.append(detail);}
  $('#chat-log').append(node);$('#chat-log').scrollTop=$('#chat-log').scrollHeight;return node;
}
formHandler('#chat-form',async form=>{
  const message=$('#chat-input').value;addMessage(message,'user');const loading=addMessage('Processing your request…','assistant');
  try{const payload={message};const session=sessionStorage.getItem('daylight-session');if(session)payload.session_id=session;
    const result=await api('/api/agent/'+($('#extract-mode').checked?'parse-tasks':'chat')+'/',{method:'POST',body:JSON.stringify(payload)});
    sessionStorage.setItem('daylight-session',result.session_id);loading.remove();addMessage(result.answer,'assistant',result.events);
    if(result.extraction){const detail=document.createElement('details'),summary=document.createElement('summary'),pre=document.createElement('pre');summary.textContent='Structured extraction';pre.textContent=JSON.stringify(result.extraction,null,2);detail.append(summary,pre);$('#chat-log').lastChild.append(detail);}
    plans=await all('/api/agent/plans/');$('#chat-proposals').innerHTML=result.plans.map(planHTML).join('');$('#chat-input').value='';
  }catch(error){loading.remove();addMessage(error.message,'assistant');throw error;}
});
document.addEventListener('click',async event=>{
  const button=event.target.closest('button');if(!button)return;
  try{
    if(button.dataset.page)await navigate(button.dataset.page);
    if(button.dataset.close)$('#'+button.dataset.close).close();
    if(button.dataset.editTask)openTask(button.dataset.editTask);
    if(button.dataset.editGoal)openGoal(button.dataset.editGoal);
    if(button.dataset.prompt){$('#chat-input').value=button.dataset.prompt;$('#chat-input').focus();}
    if(button.dataset.complete)await busy(button,async()=>{const task=tasks.find(t=>t.id===Number(button.dataset.complete));await api(`/api/tasks/${task.id}/`,{method:'PATCH',body:JSON.stringify({status:task.status==='completed'?'pending':'completed'})});await refresh();notify('Task status updated.');});
    for(const kind of ['task','goal']){
      const id=button.dataset[kind==='task'?'deleteTask':'deleteGoal'];
      if(id&&await confirmAction(`Delete ${kind}?`,kind==='task'?'This removes the task and its schedule blocks. Activity history is retained.':'Linked tasks will be kept without this goal.'))await busy(button,async()=>{await api(`/api/${kind}s/${id}/`,{method:'DELETE'});await refresh();notify(`${kind} deleted.`);});
    }
    if(button.dataset.planAction){const action=button.dataset.planAction,id=button.dataset.id;
      if(action==='approve'&&!await confirmAction('Apply this plan?', 'This applies all proposed task changes and schedule blocks. An approved revision replaces the previous plan’s schedule.'))return;
      await busy(button,async()=>{await api(`/api/agent/plans/${id}/${action}/`,{method:'POST',body:'{}'});await refresh();$('#chat-proposals').innerHTML=plans.filter(p=>p.status==='draft').map(planHTML).join('');notify(action==='revise'?'New draft generated.':`Plan ${action==='approve'?'approved':'rejected'}.`);});
    }
    if(button.dataset.editPlan){const p=plans.find(p=>p.id===Number(button.dataset.editPlan));if(p.status==='approved'&&p.proposal.operations?.length){notify('These changes are already applied. Edit the saved tasks in My tasks.');return;}const form=$('#revision-form');form.elements.id.value=p.id;form.elements.proposal.value=JSON.stringify(p.proposal,null,2);$('.form-error',form).textContent='';$('#revision-dialog').showModal();}
  }catch(error){notify(error.message,true);}
});
$('#header-add').onclick=()=>openTask();$('#tasks-add').onclick=()=>openTask();$('#goal-add').onclick=()=>openGoal();
for(const id of ['search','status-filter','priority-filter'])$('#'+id).addEventListener(id==='search'?'input':'change',renderTasks);
$('#refresh-plans').onclick=event=>busy(event.currentTarget,refresh);
$('#download-report').onclick=event=>busy(event.currentTarget,async()=>{const report=await api('/api/analytics/report/',{method:'POST',body:'{}'});const url=URL.createObjectURL(new Blob([JSON.stringify(report,null,2)],{type:'application/json'}));const a=document.createElement('a');a.href=url;a.download='daylight-report.json';a.click();URL.revokeObjectURL(url);});
$('#ai-summary').onclick=async()=>{await navigate('assistant');$('#chat-input').value='Summarize my productivity this week, clearly separating observed facts from recommendations.';$('#chat-input').focus();};
$('#today-label').textContent=new Intl.DateTimeFormat('en-IN',{timeZone:zone,weekday:'short',month:'short',day:'numeric'}).format(new Date());
$('#day-badge').textContent=dateKey();for(const name of ['start_date','end_date'])$('#plan-form').elements[name].value=dateKey();
refresh().then(()=>navigate(location.hash.slice(1)||'dashboard')).catch(error=>notify(error.message,true));
