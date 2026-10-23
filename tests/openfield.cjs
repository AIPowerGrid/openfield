// "Make the whole short" plans only missing steps and prices them first.
const assert=require('node:assert/strict');
const vm=require('node:vm');
const {readFileSync}=require('node:fs');
const element=()=>({onclick:null,hidden:false,disabled:false,textContent:''});
const elements=new Map();
const shot=(id,extra={})=>({id,title:id,draft:{look_id:null},selected_take_id:null,...extra});
const project={id:'p',music:null,product:{packshot_shot_id:'pack'},shots:[
  shot('hook'),shot('reveal',{draft:{look_id:'l1'}}),shot('done',{selected_take_id:'t1'}),shot('pack'),
]};
const context=vm.createContext({
  $:id=>{if(!elements.has(id)) elements.set(id,element()); return elements.get(id);},
  config:{autobrief:true,estimates:{look:{seconds:8},take:{seconds:100},music:{label:'~0.40¢ on the Grid (est.)'}}},
  productProject:()=>project, isPackshot:s=>s?.id==='pack',
  productHooks:{controls(){}}, sleep:async()=>{}, shortProject:project, takes:[],
});
vm.runInContext(readFileSync(require('node:path').join(__dirname,'..','src','aipg_cinema','autopilot.js'),'utf8'),context);
const plan=code=>JSON.parse(JSON.stringify(vm.runInContext(code,context)));
const steps=plan('autopilotPlan()').map(s=>s.kind+(s.shot ? ':'+s.shot.id : ''));
assert.deepEqual(steps,['look:hook','take:hook','take:reveal','packshot:pack','music','export']);
assert.equal(vm.runInContext('autopilotEstimate(autopilotPlan())',context),'~3 min on your GPU + ~0.40¢ on the Grid (est.)');
context.config.autobrief=false;
assert.ok(!vm.runInContext('autopilotPlan()',context).some(s=>s.kind==='music'));
context.config.estimates.look={credits:2}; context.config.estimates.take={credits:18};
assert.equal(vm.runInContext('autopilotEstimate(autopilotPlan())',context),'~38 Cloud credits (est.)');
project.shots.forEach(s=>s.selected_take_id='t'); project.music={};
assert.deepEqual(plan('autopilotPlan()').map(s=>s.kind),['export']);
// A finished or running take of the shot's current look is resumed, not re-rendered.
context.shortProject=project; context.takes=[
  {id:'old',project_id:'p',shot_id:'reveal',look_id:'other',status:'succeeded',output_url:'/x'},
  {id:'done',project_id:'p',shot_id:'reveal',look_id:'l1',status:'succeeded',output_url:'/y'},
];
vm.runInContext('var takes=globalThis.takes',context);
assert.equal(vm.runInContext("resumableTake(project.shots[1])",Object.assign(context,{project})).id,'done');
context.takes.unshift({id:'live',project_id:'p',shot_id:'reveal',look_id:'l1',status:'running',active:true});
vm.runInContext('takes=globalThis.takes',context);
assert.equal(vm.runInContext("resumableTake(project.shots[1])",context).id,'live');
assert.equal(vm.runInContext("resumableTake(project.shots[0])",context),null);
project.shots[1].selected_take_id=null; context.config.estimates.take={credits:18};
const resumed=plan('autopilotPlan()').find(s=>s.kind==='take' && s.shot.id==='reveal');
assert.equal(resumed.resume,true);
console.log('openfield ok');
