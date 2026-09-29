const fs=require('fs'),vm=require('vm'),assert=require('node:assert/strict');
const html=fs.readFileSync('static/checklist_tareas.html','utf8');
const js=html.match(/<script>([\s\S]*?)<\/script>/)[1];
new vm.Script(js);
const nodes={};
const ctx={document:{getElementById:id=>nodes[id]??={value:'',innerHTML:''}}};
vm.createContext(ctx);
vm.runInContext(js.slice(0,js.indexOf("  document.querySelectorAll('.tab-btn')")),ctx);
vm.runInContext(`state.context={users:[]};state.board={date:'2026-09-23',items:[{title:'A',responsible_username:'ana',status:'pending',duration_minutes:10},{title:'B',responsible_username:'ana',status:'completed',duration_minutes:20}],overdue:[{title:'A',responsible_username:'ana',status:'overdue'},{title:'C',responsible_username:'bob',status:'overdue'},{title:'D',responsible_username:null,status:'overdue'}]};renderKpis();renderSummary();`,ctx);
assert.match(nodes.kpis.innerHTML,/kpi-number">3<\/div>/);
assert.match(nodes['summary-body'].innerHTML,/<strong>ana<\/strong><\/td><td>1<\/td><td>1<\/td><td>1<\/td><td>10<\/td><td>50%/);
assert.match(nodes['summary-body'].innerHTML,/<strong>bob<\/strong><\/td><td>0<\/td><td>0<\/td><td>1/);
assert.match(nodes['summary-body'].innerHTML,/Sin responsable/);
for(const [user,status,search,count] of [['bob','','',1],['__unassigned__','','',1],['','completed','',0],['','','A',1],['','','missing',0]]){
 nodes['user-filter'].value=user;nodes['status-filter'].value=status;nodes['search-filter'].value=search;
 vm.runInContext('renderKpis();renderSummary();renderOverdue();',ctx);
 assert.equal(vm.runInContext('boardMetrics().overdue.length',ctx),count);
 const rows=[...nodes['summary-body'].innerHTML.matchAll(/<tr><td><strong>.*?<\/strong><\/td><td>\d+<\/td><td>\d+<\/td><td>(\d+)<\/td>/g)];
 assert.equal(rows.reduce((sum,r)=>sum+Number(r[1]),0),count);
}
vm.runInContext(`
state.context={users:[{username:'ana',display_name:'Ana',assignable:true},{username:'bob',display_name:'Bob',assignable:true}]};
state.catalog={
 tasks:[{task_id:1,title:'Control A',duration_minutes:10,active:1},{task_id:2,title:'Control B',duration_minutes:20,active:1},{task_id:3,title:'Control C',duration_minutes:30,active:1}],
 assignments:[
  {assignment_id:11,task_id:1,task_title:'Control A',username:'ana',shift:'M',duration_minutes:10,active:1},
  {assignment_id:12,task_id:1,task_title:'Control A',username:'bob',shift:'T',duration_minutes:10,active:1},
  {assignment_id:21,task_id:2,task_title:'Control B',username:'bob',shift:'T',duration_minutes:20,active:0},
  {assignment_id:31,task_id:3,task_title:'Control C',username:null,shift:null,duration_minutes:30,active:1}
 ]};
state.catalogFilter='';state.catalogUserFilter='bob';state.selectedTaskId=null;renderCatalog();
`,ctx);
assert.match(nodes['tasks-catalog-body'].innerHTML,/Control A/);
assert.match(nodes['tasks-catalog-body'].innerHTML,/Control B/);
assert.doesNotMatch(nodes['tasks-catalog-body'].innerHTML,/Control C/);
assert.match(nodes['assignments-body'].innerHTML,/Bob \(bob\)/);
assert.doesNotMatch(nodes['assignments-body'].innerHTML,/Ana \(ana\)/);
assert.match(nodes['catalog-filter-note'].textContent,/Bob \(bob\) · 1 asignaciones activas/);
vm.runInContext("state.catalogUserFilter='__unassigned__';renderCatalog();",ctx);
assert.match(nodes['tasks-catalog-body'].innerHTML,/Control C/);
assert.doesNotMatch(nodes['tasks-catalog-body'].innerHTML,/Control A/);
assert.match(nodes['assignments-body'].innerHTML,/Sin responsable/);
console.log('OK: periods, overdue-only owners, unassigned tasks, daily totals and filters stay consistent.');
